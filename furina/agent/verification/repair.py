"""Phase 16F — BoundedRepairLoop：严格有界修复循环（16F 任务书 §5 + 关键锁定 9–12）。

- **修复允许条件**：WorkContract 允许（``budget.max_attempts > 1`` 才有修复余地；
  approval-gated 策略必须提供 ``approval_authority``，否则构造期 fail-closed）
  且预算仍有剩余。
- **每次 attempt 全新身份**：新 attempt_id + 新 run_id（工厂产出、逐次校验唯一），
  绑定**同一不可变契约**——verifier 与 collect 只拿契约只读事实，contract
  content_hash 逐 attempt 记录并校验不变；不得扩大 workspace / capabilities /
  backends / permission / 预算（结构上不可能：collect_evidence 只收到
  attempt_id/run_id，verifier 绑定构造期契约，无任何改约通道）。
- **重入点**：失败/不确定 → 重新收集证据（BACKEND_DONE_UNVERIFIED 语义的
  等价物）→ 再次独立验证；**绝不修补 verdict**（VERIFIED 只能来自 verifier）。
- **精确停止**：VERIFIED / hard failure / approval deny·timeout / cancellation /
  超时（deadline 前不允许启动任何新 attempt）/ 成本超限 / attempts 耗尽 /
  **重复相同 failure signature 断路**。
- failure signature：对 failed/not_evaluable 检查的确定性摘要（check_id + result
  + explanation 的 canonical SHA-256）——不含时间戳/run_id，因此"同一原因再失败"
  会被识别；不同原因不误断。

本模块零 DB / 零 C1–C7 / 零事件总线 / 零持久化（C6/C7/C3 写入属 16G）。
"""
from __future__ import annotations

import enum
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional, Tuple

from furina.agent.work_contract import WorkContract

from .models import (
    MAX_DIAGNOSTIC_CHARS,
    VerificationError,
    VerificationReport,
    VerificationVerdict,
    scrub_secrets,
)
from .verifier import IndependentVerifier

__all__ = [
    "AttemptRecord",
    "BoundedRepairLoop",
    "HardBackendFailure",
    "RepairOutcome",
    "RepairStopReason",
]


class HardBackendFailure(Exception):
    """collect 侧显式抛出的硬失败信号（不可修复的 backend/环境故障）→ 立即停止。"""


class RepairStopReason(str, enum.Enum):
    VERIFIED = "VERIFIED"
    ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    REPEATED_FAILURE = "REPEATED_FAILURE"
    CANCELLED = "CANCELLED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    HARD_FAILURE = "HARD_FAILURE"
    CONTRACT_MUTATED = "CONTRACT_MUTATED"


@dataclass(frozen=True)
class AttemptRecord:
    """单次 attempt 的不可变记录（attempt/run 身份 + 契约 hash + 结果/签名）。"""

    attempt_id: str
    run_id: str
    contract_hash: str
    verdict: str                 # 报告 verdict 值；collect 层失败时为 ""
    report_id: str
    failure_signature: str       # VERIFIED 时为 ""
    started_at_epoch: float
    finished_at_epoch: float
    diagnostic: str = ""


@dataclass(frozen=True)
class RepairOutcome:
    """修复循环终局（不可变；bounded attempts 列表）。"""

    stop_reason: RepairStopReason
    contract_id: str
    contract_hash: str
    attempts: Tuple[AttemptRecord, ...]
    final_report: Optional[VerificationReport]
    started_at_epoch: float
    finished_at_epoch: float
    diagnostic: str = ""


def _failure_signature(report: VerificationReport) -> str:
    """失败签名：failed/not_evaluable 检查的确定性摘要（不含时间戳/run_id）。"""
    rows = [[c.check_id, c.result.value, c.explanation]
            for c in report.checks if c.result.value != "PASS"]
    payload = json.dumps({"verdict": report.verdict.value, "failed": rows},
                         sort_keys=True, ensure_ascii=True, allow_nan=False,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _diag_signature(diagnostic: str) -> str:
    return hashlib.sha256(f"collect:{diagnostic}".encode("utf-8")).hexdigest()


class BoundedRepairLoop:
    """同一不可变契约上的有界验证-修复驱动器（验证权威始终在 IndependentVerifier）。"""

    def __init__(self, *, contract: WorkContract, verifier: IndependentVerifier,
                 collect_evidence: Callable[[str, str], Mapping[str, Any]],
                 cancel_requested: Optional[Callable[[], bool]] = None,
                 approval_authority: Optional[Callable[[str, str], str]] = None,
                 cost_used: Optional[Callable[[], float]] = None,
                 run_id_factory: Optional[Callable[[str], str]] = None,
                 now_fn: Callable[[], float] = time.time) -> None:
        if not isinstance(contract, WorkContract):
            raise VerificationError(
                f"repair 必须绑定 16A WorkContract，得到 {type(contract).__name__}")
        if not isinstance(verifier, IndependentVerifier):
            raise VerificationError("repair 必须绑定 IndependentVerifier（验证权威唯一）")
        if verifier.contract_id != contract.contract_id \
                or verifier.contract_hash != contract.content_hash:
            raise VerificationError("verifier 与 repair 绑定的契约身份不一致")
        if not callable(collect_evidence):
            raise VerificationError("collect_evidence 必须是 callable")

        policy_kind = contract.approval_policy.policy_kind
        if policy_kind in ("approval_required_each_step",
                           "approval_required_on_risk_level") \
                and approval_authority is None:
            raise VerificationError(
                "approval-gated 契约的 repair 必须提供 approval_authority（fail-closed）")

        self._contract = contract
        self._verifier = verifier
        self._collect = collect_evidence
        self._cancel_requested = cancel_requested or (lambda: False)
        self._approval_authority = approval_authority
        self._cost_used = cost_used
        self._run_id_factory = run_id_factory or (lambda attempt_id: f"run_{attempt_id}")
        self._now_fn = now_fn
        self._initial_hash = contract.content_hash
        self._deadline = self._now_fn() + contract.budget.max_duration_seconds
        self._seen_run_ids: set = set()

    # -- 主循环 ----------------------------------------------------------------
    def run(self) -> RepairOutcome:
        started = self._now_fn()
        attempts: List[AttemptRecord] = []
        last_signature = ""
        stop: Optional[RepairStopReason] = None
        stop_diag = ""
        final_report: Optional[VerificationReport] = None
        max_attempts = self._contract.budget.max_attempts

        while len(attempts) < max_attempts:
            # 1. cancellation：取消后绝不启动新 attempt。
            if bool(self._cancel_requested()):
                stop, stop_diag = RepairStopReason.CANCELLED, "cancellation_requested"
                break
            # 2. 契约不可变防御：content_hash 漂移即停（frozen 对象下不可达，守卫保留）。
            if self._contract.content_hash != self._initial_hash:
                stop, stop_diag = RepairStopReason.CONTRACT_MUTATED, "contract_hash_changed"
                break
            # 3. 审批门：未明确 approve 一律不放行（deny/timeout/pending/未知/空 → 停）。
            attempt_id, run_id = self._allocate_ids(len(attempts) + 1)
            if self._approval_authority is not None:
                verdict_str = self._approval_authority(attempt_id, run_id)
                if verdict_str != "approve":
                    stop = RepairStopReason.APPROVAL_DENIED
                    stop_diag = f"approval_not_granted:{str(verdict_str)[:64]}"
                    break
            # 4. 时间预算：deadline 后绝不启动新 attempt（精确停止）。
            if self._now_fn() >= self._deadline:
                stop, stop_diag = RepairStopReason.TIMEOUT, "time_budget_exhausted"
                break
            # 5. 成本预算：真实读取累计成本，超限即停。
            if self._cost_used is not None:
                try:
                    used = float(self._cost_used())
                except Exception as exc:
                    used = float("inf")
                    stop_diag = f"cost_meter_error:{type(exc).__name__}"
                if used > self._contract.budget.cost_limit.amount:
                    stop = RepairStopReason.BUDGET_EXHAUSTED
                    stop_diag = stop_diag or "cost_limit_exceeded"
                    break

            attempt_started = self._now_fn()
            diagnostic = ""
            report: Optional[VerificationReport] = None
            signature = ""
            hard = False
            try:
                submission = self._collect(attempt_id, run_id)
                if not isinstance(submission, Mapping):
                    diagnostic = "collect_not_mapping"
                elif submission.get("run_id") != run_id:
                    diagnostic = "run_id_mismatch"
                else:
                    report = self._verifier.verify(submission)
            except HardBackendFailure as exc:
                # 硬失败信号：记录该 attempt 后**立即停止**（绝不重试）。
                hard = True
                diagnostic = f"hard_backend_failure:{str(exc)[:128]}"
            except Exception as exc:
                # VerificationInputError（含伪造证据）与其它 collect/verify 异常：
                # 记为该次 attempt 的失败（有界重试；重复签名由断路器拦截）。
                diagnostic = f"collect_or_verify_error:{type(exc).__name__}:" \
                             f"{scrub_secrets(str(exc))[:MAX_DIAGNOSTIC_CHARS]}"

            attempt_finished = self._now_fn()
            if report is not None:
                signature = ("" if report.verdict is VerificationVerdict.VERIFIED
                             else _failure_signature(report))
                attempts.append(AttemptRecord(
                    attempt_id=attempt_id, run_id=run_id,
                    contract_hash=self._contract.content_hash,
                    verdict=report.verdict.value, report_id=report.report_id,
                    failure_signature=signature,
                    started_at_epoch=attempt_started, finished_at_epoch=attempt_finished))
                if report.verdict is VerificationVerdict.VERIFIED:
                    stop, final_report = RepairStopReason.VERIFIED, report
                    break
            else:
                signature = _diag_signature(diagnostic)
                attempts.append(AttemptRecord(
                    attempt_id=attempt_id, run_id=run_id,
                    contract_hash=self._contract.content_hash,
                    verdict="", report_id="", failure_signature=signature,
                    started_at_epoch=attempt_started, finished_at_epoch=attempt_finished,
                    diagnostic=diagnostic[:MAX_DIAGNOSTIC_CHARS]))

            # 6. 硬失败：立即停止（优先于断路检查——硬失败绝不重试）。
            if hard:
                stop = RepairStopReason.HARD_FAILURE
                stop_diag = diagnostic
                break
            # 7. 重复相同 failure signature → 断路（不烧剩余 attempts）；
            #    最后一次验证报告作为 final_report 携带（绝不修补其 verdict）。
            if signature and signature == last_signature:
                stop = RepairStopReason.REPEATED_FAILURE
                stop_diag = "repeated_identical_failure_signature"
                final_report = report
                break
            last_signature = signature

        if stop is None:
            stop = RepairStopReason.ATTEMPTS_EXHAUSTED
            stop_diag = "max_attempts_reached"
        return RepairOutcome(
            stop_reason=stop, contract_id=self._contract.contract_id,
            contract_hash=self._contract.content_hash, attempts=tuple(attempts),
            final_report=final_report, started_at_epoch=started,
            finished_at_epoch=self._now_fn(), diagnostic=stop_diag)

    # -- 工具 ----------------------------------------------------------------
    def _allocate_ids(self, n: int) -> Tuple[str, str]:
        attempt_id = f"att_{n:02d}_{uuid.uuid4().hex[:8]}"
        run_id = str(self._run_id_factory(attempt_id))
        if not run_id or run_id in self._seen_run_ids:
            raise VerificationError(f"run_id_factory 必须产出唯一非空 run_id，得到 {run_id!r}")
        import re as _re
        from .models import _RUN_ID_PATTERN
        if not _RUN_ID_PATTERN.match(run_id):
            raise VerificationError(f"run_id 词法非法: {run_id!r}")
        self._seen_run_ids.add(run_id)
        return attempt_id, run_id
