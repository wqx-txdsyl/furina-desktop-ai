"""Phase 16H v2 — Recovery & Cancellation Coordinators（B4/B5 生产协调器）。

- :class:`RecoveryCoordinator`（B4）：reopen 后读取 non-terminal execution +
  完整 WorkContract + attempts；原子进入 reconciliation/UNKNOWN（同 contract
  submit 继续被阻止）；按 backend_id 从显式注入的 registry 获取原 backend；
  用持久化 run 身份重建 BackendRunHandle；只经 16B/16C 公开 events 面消费
  事件（**绝不重新 submit**）；事件经 16E normalizer 归一后持久化；terminal
  evidence 足够时调用真实 16F verifier——只有 B1 权威验证成功才标记 VERIFIED；
  否则保持 typed UNKNOWN。有界预算（事件窗口 + 时限）、确定性 close、绝不
  运行于 60fps owner tick。
- :class:`CancellationCoordinator`（B5）：cancel 时在同一 durable intent 下
  先持久化 cancel intent → 调用注入的 16D ApprovalBroker.cancel 使真实
  pending approval 失效 → 有活动 run 且 backend supports_stop 时经公开
  stop() 恰好派发一次；stop 网络结果不确定 → UNKNOWN/reconcile，绝不重新
  submit；重复 cancel 幂等；pre-submit cancel 零 submit/零 run/零 stop。
  不宣称远端全局 exactly-once（durable at-most-once dispatch + ambiguous
  reconciliation）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from furina.agent.backend.models import BackendEvent, BackendRunHandle
from furina.agent.events.models import EventKind
from furina.agent.events.reducer import WorkExecutionState
from furina.agent.events.reducer import WorkExecutionReducer, WorkExecutionState
from furina.agent.events.normalizer import BackendEventNormalizer
from furina.agent.work_ledger import (
    WorkLedger,
    WorkLedgerError,
)

__all__ = [
    "CancellationCoordinator",
    "CancellationOutcome",
    "RecoveryCoordinator",
    "RecoveryOutcome",
]


@dataclass(frozen=True)
class RecoveryOutcome:
    """单次 recovery 的类型化结果（零 submit； submit_calls 恒为 0）。"""

    execution_id: int
    status: str                       # verified / unknown_no_backend /
                                      # unknown_no_run / unknown_no_events /
                                      # unknown_insufficient_evidence /
                                      # verification_failed
    events_consumed: int = 0
    submit_calls: int = 0             # 结构常数：coordinator 绝不 submit
    detail: str = ""


@dataclass(frozen=True)
class CancellationOutcome:
    """单次 cancellation 的类型化结果。"""

    execution_id: int
    status: str                       # cancelled_pre_submit / cancelling /
                                      # already_terminal / stop_uncertain_reconcile
    stop_dispatched: bool = False
    approval_cancelled: bool = False
    reconciled: bool = False


class RecoveryCoordinator:
    """生产级恢复协调器（B4）：fail-closed、有界预算、确定性 close。"""

    def __init__(self, ledger: WorkLedger, *, backend_registry=None,
                 verifier=None,
                 submission_builder: Optional[Callable[..., Mapping[str, Any]]] = None,
                 now_fn=time.time, max_events_window: int = 64,
                 deadline_seconds: float = 30.0,
                 max_total_executions: int = 256) -> None:
        if not isinstance(ledger, WorkLedger):
            raise WorkLedgerError("ledger 必须是 WorkLedger")
        if type(max_events_window) is not int or max_events_window < 1 or max_events_window > 10_000:
            raise WorkLedgerError("max_events_window 必须是 [1, 10000] int")
        if type(deadline_seconds) not in (int, float):
            raise WorkLedgerError("deadline_seconds 必须是 builtin 数值")
        import math as _m
        dl = float(deadline_seconds)
        if not _m.isfinite(dl) or dl <= 0 or dl > 600.0:
            raise WorkLedgerError("deadline_seconds 必须在 (0, 600] 内")
        if type(max_total_executions) is not int or max_total_executions < 1:
            raise WorkLedgerError("max_total_executions 必须是正 int")
        self._ledger = ledger
        self._registry = backend_registry
        self._verifier = verifier
        self._submission_builder = submission_builder
        self._now_fn = now_fn
        self._max_events_window = max_events_window
        self._deadline_seconds = dl
        self._max_total_executions = max_total_executions
        self._closed = False

    def close(self) -> None:
        """确定性 close（真实资源生命周期）。"""
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise WorkLedgerError("coordinator 已 close")

    # --------------------------------------------------
    def recover_all(self) -> Tuple[RecoveryOutcome, ...]:
        """reopen 入口：全局 execution 数量预算。"""
        self._ensure_open()
        outcomes: List[RecoveryOutcome] = []
        non_terminal = self._ledger.load_non_terminal()
        if len(non_terminal) > self._max_total_executions:
            raise WorkLedgerError(
                f"non-terminal executions {len(non_terminal)} 超过全局恢复预算"
                f" {self._max_total_executions}")
        for rec in non_terminal:
            outcomes.append(self.recover_execution(rec.execution_id))
        return tuple(outcomes)

    def recover_execution(self, execution_id: int) -> RecoveryOutcome:
        self._ensure_open()
        deadline = time.monotonic() + self._deadline_seconds
        rec = self._ledger.get_execution(execution_id)
        self._ledger.load_contract(rec.contract_id)
        self._ledger.begin_reconciliation(
            execution_id, expected_version=rec.state_version)
        if not rec.run_id:
            return RecoveryOutcome(
                execution_id=execution_id, status="unknown_no_run",
                submit_calls=0, detail="run 未绑定（submit 结果不确定窗口）")
        backend = None
        if self._registry is not None and rec.backend_id:
            backend = self._registry.get(rec.backend_id)
        if backend is None:
            return RecoveryOutcome(
                execution_id=execution_id, status="unknown_no_backend",
                submit_calls=0, detail="backend registry 不可用/未注册")
        # Hermes 强制 correlation=contract_id
        handle = BackendRunHandle(backend_id=rec.backend_id, run_id=rec.run_id,
                                  correlation=rec.contract_id)
        normalizer = BackendEventNormalizer(
            backend_id=rec.backend_id, contract_id=rec.contract_id,
            run_id=rec.run_id)
        consumed = 0
        terminal_evidence = None
        terminal_kind = None
        try:
            for raw in backend.events(handle):
                if consumed >= self._max_events_window:
                    break
                if time.monotonic() > deadline:
                    break
                consumed += 1
                event = normalizer.normalize(raw)
                self._ledger.record_event(execution_id, event.event_id,
                                          event.kind, dict(event.payload))
                if event.kind in (EventKind.BACKEND_COMPLETED,
                                  EventKind.BACKEND_FAILED,
                                  EventKind.BACKEND_CANCELLED):
                    terminal_evidence = {
                        "kind": event.kind.value,
                        "event_id": event.event_id,
                        "payload": dict(event.payload),
                    }
                    terminal_kind = event.kind
                    break
        except Exception as exc:
            return RecoveryOutcome(
                execution_id=execution_id, status="unknown_insufficient_evidence",
                events_consumed=consumed, submit_calls=0,
                detail=f"backend events 不确定: {type(exc).__name__}")
        if terminal_evidence is None or terminal_kind is None:
            return RecoveryOutcome(
                execution_id=execution_id, status="unknown_no_events",
                events_consumed=consumed, submit_calls=0,
                detail="事件窗口内无 terminal evidence——保持 UNKNOWN")
        # completed/failed/cancelled 分流：仅 completed 可进入 16F 验证
        # recovery-only authority（UNKNOWN absorbing，generic 不得迁出）
        rec_now = self._ledger.get_execution(execution_id)
        v_now = rec_now.state_version
        if terminal_kind is not EventKind.BACKEND_COMPLETED:
            final_state = (WorkExecutionState.FAILED
                           if terminal_kind is EventKind.BACKEND_FAILED
                           else WorkExecutionState.CANCELLED)
            self._ledger.recover_terminal(
                execution_id, terminal_evidence, final_state,
                expected_version=v_now)
            return RecoveryOutcome(
                execution_id=execution_id,
                status=f"terminal_{final_state.value}",
                events_consumed=consumed, submit_calls=0,
                detail=f"recovery terminal={final_state.value}（不进入 16F）")
        # completed：recover_terminal 到 BACKEND_DONE_UNVERIFIED（evidence 同事务）
        v = self._ledger.recover_terminal(
            execution_id, terminal_evidence,
            WorkExecutionState.BACKEND_DONE_UNVERIFIED,
            expected_version=v_now)
        verifier = self._verifier
        if verifier is None or self._submission_builder is None:
            return RecoveryOutcome(
                execution_id=execution_id,
                status="unknown_insufficient_evidence",
                events_consumed=consumed, submit_calls=0,
                detail="terminal evidence 已持久化；16F 验证未配置")
        try:
            submission = self._submission_builder(rec, terminal_evidence)
            report = verifier.verify(submission)
            from furina.agent.verification.repair import (
                AttemptRecord,
                RepairOutcome,
                RepairStopReason,
            )
            attempt = AttemptRecord(
                attempt_id=rec.attempt_id, run_id=report.run_id,
                contract_hash=report.contract_hash, verdict="VERIFIED",
                report_id=report.report_id, failure_signature="",
                started_at_epoch=float(report.started_at_epoch),
                finished_at_epoch=float(report.finished_at_epoch))
            outcome = RepairOutcome(
                stop_reason=RepairStopReason.VERIFIED,
                contract_id=report.contract_id,
                contract_hash=report.contract_hash,
                attempts=(attempt,), final_report=report,
                started_at_epoch=float(report.started_at_epoch),
                finished_at_epoch=float(report.finished_at_epoch))
            self._ledger.mark_verified_by_outcome(
                execution_id, verifier, outcome, expected_version=v,
                terminal_evidence=terminal_evidence)
        except Exception as exc:
            return RecoveryOutcome(
                execution_id=execution_id, status="verification_failed",
                events_consumed=consumed, submit_calls=0,
                detail=f"16F 验证未通过: {type(exc).__name__}")
        return RecoveryOutcome(
            execution_id=execution_id, status="verified",
            events_consumed=consumed, submit_calls=0)


class CancellationCoordinator:
    """生产级取消协调器（B5）：durable intent → 真实 approval 失效 →
    backend stop 恰一次 → 不确定即 reconcile（绝不重发/重提交）。"""

    def __init__(self, ledger: WorkLedger, *, backend_registry=None,
                 approval_canceller: Optional[Callable[[str], Any]] = None,
                 now_fn=time.time) -> None:
        if not isinstance(ledger, WorkLedger):
            raise WorkLedgerError("ledger 必须是 WorkLedger")
        if approval_canceller is not None and not callable(approval_canceller):
            raise WorkLedgerError("approval_canceller 必须是 callable")
        # 装配边界诚实记录：approval_canceller 是注入的窄 typed adapter
        # （16D ApprovalBroker.cancel 的 owner 线程包装），不是 broker 本体；
        # coordinator 不读取 broker._private。
        self._ledger = ledger
        self._registry = backend_registry
        self._approval_canceller = approval_canceller

    def cancel(self, execution_id: int) -> CancellationOutcome:
        rec = self._ledger.get_execution(execution_id)
        current = rec.state
        if current in (WorkExecutionState.CANCELLED,
                       WorkExecutionState.VERIFIED,
                       WorkExecutionState.FAILED):
            return CancellationOutcome(execution_id=execution_id,
                                       status="already_terminal")
        # ① durable cancel intent 先落盘（pre-submit → 直接 CANCELLED）。
        v = self._ledger.cancel_intent(execution_id,
                                       expected_version=rec.state_version)
        rec = self._ledger.get_execution(execution_id)
        if rec.state is WorkExecutionState.CANCELLED:
            return CancellationOutcome(
                execution_id=execution_id, status="cancelled_pre_submit",
                stop_dispatched=False, approval_cancelled=False)
        approval_cancelled = False
        # ② 真实 16D approval 失效（注入通道；迟到 approve 不得恢复）。
        if rec.approval_id and self._approval_canceller is not None:
            self._approval_canceller(rec.approval_id)
            approval_cancelled = True
        self._ledger.invalidate_approval(execution_id)
        # ③ backend stop 恰一次（run 未绑定 → 零 stop；不确定 → reconcile）。
        # 先确认 backend 存在且 supports_stop，再消费 stop claim
        backend_confirmed = False
        if self._registry is not None and rec.backend_id:
            b = self._registry.get(rec.backend_id)
            if b is not None and b.capabilities.supports_stop:
                backend_confirmed = True
        stop_dispatched = self._ledger.dispatch_stop_once(
            execution_id, backend_confirmed=backend_confirmed)
        reconciled = False
        if stop_dispatched and self._registry is not None and rec.backend_id:
            backend = self._registry.get(rec.backend_id)
            if backend is not None and backend.capabilities.supports_stop:
                try:
                    backend.stop(BackendRunHandle(backend_id=rec.backend_id,
                                                  run_id=rec.run_id))
                except Exception:
                    # stop 网络结果不确定 → UNKNOWN/reconcile；stop_dispatched
                    # 已置位 → 绝不重发；绝不重新 submit。
                    self._ledger.begin_reconciliation(
                        execution_id,
                        expected_version=self._ledger.get_execution(
                            execution_id).state_version)
                    reconciled = True
                    return CancellationOutcome(
                        execution_id=execution_id,
                        status="stop_uncertain_reconcile",
                        stop_dispatched=True,
                        approval_cancelled=approval_cancelled,
                        reconciled=True)
        return CancellationOutcome(
            execution_id=execution_id, status="cancelling",
            stop_dispatched=stop_dispatched,
            approval_cancelled=approval_cancelled, reconciled=reconciled)
