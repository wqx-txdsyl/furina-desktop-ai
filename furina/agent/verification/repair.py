"""Phase 16F — BoundedRepairLoop：严格有界修复循环（16F 任务书 §5 + 关键锁定 9–12
+ Reviewer Patch 1 blocker 4/6 + Reviewer Patch 3（blocker B3）+ Patch 4（P4-D）。

- **接受 VERIFIED 前的真正封闭最终边界（P4-D + P5-A）**：``_accept_verified_
  report``（seal 认证 / standard·hash 属性访问——都可能携带调用方回调副作用）
  **完成后**，经**单一权威快照接口** ``_take_final_boundary`` 以**版本一致性
  协议**取得权威 :class:`BoundarySnapshot`：见证采集（cancel→cost→now）暴露
  的越界立即停止（拒绝路径零逃逸面）；仅当见证干净时进行权威采集
  （now→cancel→cost→now→cancel——now 夹逼取消/成本读取），并**证明两次采集
  一致**（epoch ledger 精确记账 / 契约 hash 一致 / 时钟单调 / 回调零异常），
  无法证明一致 → ``UNSTABLE_BOUNDARY`` fail-closed；值聚合一律 fail-closed
  worst-wins（cancelled 取 OR、cost 取 max、now 取最新）。判定与 RepairOutcome
  构造**只依据该快照**（``snapshot.now`` 直接作为 finished_at_epoch），此后零
  回调（cost/cancel/now/verifier 一律不再调用）。越界（成本超限/取消/超时/
  契约漂移）→ 立即停止且 ``final_report=None``（VERIFIED 绝不成为成功结果）。
  P4-D 的单次顺序读取不是原子快照——最后的 now_fn 回调可改写已读取的
  cost/cancel 让越界 VERIFIED 逃逸；"调整顺序"或"有限轮重复扫描"同样无法
  封闭（任意有限读取序列都有最后一个读取项）——版本一致性协议把"最后一次
  回调改写其它边界状态"从不可见副作用转为可证明的不一致/可捕获的越界。
  ——cancellation 回调把 cost 从 0 改成 6（读取次序 cancel→cost 暴露其副作用）、
  cost 回调推进时钟（cost→now 暴露其副作用）、seal 认证回调翻转取消 /
  standard_hash 属性推进 deadline、**最终 now 回调改写 cost/cancel** 全部被
  该协议拦截。

- **修复允许条件**：WorkContract 允许（``budget.max_attempts > 1`` 才有修复余地；
  approval-gated 策略必须提供 ``approval_authority``，否则构造期 fail-closed）
  且预算仍有剩余。
- **每次 attempt 全新身份**：新 attempt_id + 新 run_id（工厂产出、逐次校验唯一），
  绑定**同一不可变契约**——verifier 与 collect 只拿契约只读事实，contract
  content_hash 逐 attempt 记录并校验不变；不得扩大 workspace / capabilities /
  backends / permission / 预算（结构上不可能：collect_evidence 只收到
  attempt_id/run_id，verifier 绑定构造期契约，无任何改约通道）。
- **边界复核（blocker 4 + B5）**：cancellation / deadline / cost meter /
  contract hash 在 attempt/approval/factory/collect/verify 的真实副作用边界
  **前后**都要复核，且读取次序保证每个回调的副作用都被其后的读取捕获：
  attempt 启动前（``used >= limit`` → 零 collect）、**run_id_factory 回调
  之后**（factory 期间的取消/超时/成本耗尽/mutation 必须阻止 collect）、
  approval 回调之后、以及**接受 VERIFIED 前**（post 复核全部使用回调结束
  后的**新鲜当前时间**——cost meter 自身推进时钟后必须再次读取当前时间，
  绝不缓存旧时间；``used > limit`` → BUDGET_EXHAUSTED；新鲜时间 > deadline
  → TIMEOUT；attempt 中出现 cancellation → CANCELLED；contract hash 漂移
  → CONTRACT_MUTATED）。越界后的 VERIFIED report 不得成为成功结果
  （``final_report`` 置空，stop reason 如实反映越界边界）。
- **VERIFIED 接受门（blocker B4）**：RepairLoop 只接受**当前验证器**的真实
  报告——``seal_is_authentic``（当前实例密钥）+ contract_id/run_id/
  contract_hash/standard_hash 与当前契约和本次 attempt 精确一致全部通过才
  接受；foreign-signer / 旧 attempt / run 或 contract mismatch 报告一律
  ``REPORT_REJECTED``（final_report=None，绝不修补或重新签署外来报告）。
- **严格 cost meter（blocker 4）**：``cost_used`` 必须是严格数值类型
  （bool/str 拒绝）、finite、``>= 0``——meter 异常 / NaN / Inf / 负数一律
  fail-closed（视同 +inf → BUDGET_EXHAUSTED），零误判。
- **重入点**：失败/不确定 → 重新收集证据（BACKEND_DONE_UNVERIFIED 语义的
  等价物）→ 再次独立验证；**绝不修补 verdict**（VERIFIED 只能来自 verifier）。
- **精确停止**：VERIFIED / hard failure / approval deny·timeout / cancellation /
  超时（deadline 前不允许启动任何新 attempt）/ 成本超限 / attempts 耗尽 /
  重复相同 failure signature 断路 / **外来报告拒绝**。
- failure signature：对 failed/not_evaluable 检查的确定性摘要（check_id + result
  + explanation 的 canonical SHA-256）——不含时间戳/run_id，因此"同一原因再失败"
  会被识别；不同原因不误断；前置载荷同样脱敏（raw secret text 不进入签名载荷）。
- **秘密边界（blocker 6 + B6）**：所有进入 RepairOutcome / AttemptRecord /
  diagnostic 的字符串面（HardBackendFailure / approval / cost / collector
  diagnostic）统一脱敏；**run_id_factory 输出直接经公开 canonical
  ``validate_identity``**（含 ``_``/``.``/``-``/``:`` 分隔前缀的秘密形态，
  非字符串拒绝、绝不 ``str()`` 强转、绝不静默 trim）——原始 secret text
  不进入对象字段、异常、stop 诊断与 failure signature 载荷。

本模块零 DB / 零 C1–C7 / 零事件总线 / 零持久化（C6/C7/C3 写入属 16G）。
"""
from __future__ import annotations

import enum
import hashlib
import json
import math
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
    #: blocker B4：VERIFIED 格式报告未通过当前验证器 seal/精确身份复核——
    # 绝不接受、绝不修补/重签外来报告（final_report=None，立即停止）。
    REPORT_REJECTED = "REPORT_REJECTED"
    #: Patch 3 B3：接受 VERIFIED 前的最终稳定边界复核无法取得稳定安全结果
    # （回调异常）→ fail-closed，final_report=None，VERIFIED 绝不成为成功结果。
    UNSTABLE_BOUNDARY = "UNSTABLE_BOUNDARY"


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

    def __post_init__(self) -> None:
        # 秘密边界（blocker 6）：诊断字符串面统一脱敏后限长
        object.__setattr__(self, "diagnostic",
                           scrub_secrets(self.diagnostic or "")[:MAX_DIAGNOSTIC_CHARS])


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostic",
                           scrub_secrets(self.diagnostic or "")[:MAX_DIAGNOSTIC_CHARS])


def _failure_signature(report: VerificationReport) -> str:
    """失败签名：failed/not_evaluable 检查的确定性摘要（不含时间戳/run_id）。

    明文前置载荷同样经脱敏——raw secret text 不进入签名前置载荷（blocker 6）。
    """
    rows = [[c.check_id, c.result.value, scrub_secrets(c.explanation)]
            for c in report.checks if c.result.value != "PASS"]
    payload = json.dumps({"verdict": report.verdict.value, "failed": rows},
                         sort_keys=True, ensure_ascii=True, allow_nan=False,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _diag_signature(diagnostic: str) -> str:
    return hashlib.sha256(f"collect:{diagnostic}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BoundarySnapshot:
    """P4-D + P5-A：接受 VERIFIED 前的**单一权威边界快照**（版本一致性协议）。

    一次调用同时取得 contract hash / cancellation / cost / 新鲜当前时间——
    判定与 RepairOutcome 构造**只依据本快照**；此后不得再调用任何
    cost/cancel/now/verifier 回调。``version`` 是快照取得时的边界版本
    （epoch ledger：采集窗口内每个边界回调调用恰递增一次）。
    """

    contract_hash: str
    cancelled: bool
    cost_used: Optional[float]      # None = 未注入 cost meter
    now: float
    version: int = 0


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
        # P5-A：边界回调仪表化——epoch ledger（采集窗口内每次调用恰 +1，用于
        # 版本一致性证明）与重入检测（采集期间回调经仪表通道再入其它边界
        # 回调 → 无法证明一致 → fail-closed）。采集窗口外仪表零副作用。
        self._bepoch = 0
        self._w_depth = 0
        self._boundary_active = False
        self._boundary_reentrant = False
        self._w_cancel = self._wrap_boundary_callback(self._cancel_requested)
        self._w_cost_used = (self._wrap_boundary_callback(self._cost_used)
                             if self._cost_used is not None else None)
        self._w_now = self._wrap_boundary_callback(self._now_fn)

    def _wrap_boundary_callback(self, fn):
        """边界回调仪表包装：仅当最终边界采集窗口激活时递增 epoch 并检测重入。"""
        def wrapped():
            if self._boundary_active:
                self._bepoch += 1
                if self._w_depth > 0:
                    self._boundary_reentrant = True
            self._w_depth += 1
            try:
                return fn()
            finally:
                self._w_depth -= 1
        return wrapped

    # -- 主循环 ----------------------------------------------------------------
    def run(self) -> RepairOutcome:
        started = self._now_fn()
        attempts: List[AttemptRecord] = []
        last_signature = ""
        stop: Optional[RepairStopReason] = None
        stop_diag = ""
        final_report: Optional[VerificationReport] = None
        final_now: Optional[float] = None    # P4-D：最终边界快照的 now（构造
        # RepairOutcome 直接使用；此后零回调）
        max_attempts = self._contract.budget.max_attempts

        while len(attempts) < max_attempts:
            # 1. 副作用边界前复核：contract hash / cost（>= limit → 零 collect）/
            #    cancellation / deadline（deadline 前不启动新 attempt）。
            #    读取次序 hash→cost→cancel→time：每个回调副作用都被其后的
            #    读取捕获（blocker B5——cost meter 可能推进时钟/翻转取消）。
            reason, diag = self._boundary_violation(pre=True)
            if reason is not None:
                stop, stop_diag = reason, diag
                break
            # 2. 身份分配：run_id_factory 输出直接经 canonical validate_identity
            #    （blocker B6——非 str 拒绝、秘密形态拒绝、绝不 str() 强转）。
            attempt_id, run_id = self._allocate_ids(len(attempts) + 1)
            # 3. factory 回调（外部代码边界）之后复核：factory 期间出现的
            #    cancellation / 超时 / 成本耗尽 / contract mutation 必须阻止
            #    collect（blocker B5）。
            reason, diag = self._boundary_violation(pre=True)
            if reason is not None:
                stop, stop_diag = reason, diag
                break
            # 4. 审批门：未明确 approve 一律不放行（deny/timeout/pending/未知/空 → 停）。
            if self._approval_authority is not None:
                verdict_str = self._approval_authority(attempt_id, run_id)
                if verdict_str != "approve":
                    stop = RepairStopReason.APPROVAL_DENIED
                    stop_diag = f"approval_not_granted:{scrub_secrets(str(verdict_str))[:64]}"
                    break
                # 审批回调（外部副作用边界）之后再次复核边界。
                reason, diag = self._boundary_violation(pre=True)
                if reason is not None:
                    stop, stop_diag = reason, diag
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
                # 硬失败信号：记录该 attempt 后**立即停止**（绝不重试）；
                # 消息面脱敏（blocker 6）。
                hard = True
                diagnostic = f"hard_backend_failure:{scrub_secrets(str(exc))[:128]}"
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
            else:
                signature = _diag_signature(diagnostic)
                attempts.append(AttemptRecord(
                    attempt_id=attempt_id, run_id=run_id,
                    contract_hash=self._contract.content_hash,
                    verdict="", report_id="", failure_signature=signature,
                    started_at_epoch=attempt_started, finished_at_epoch=attempt_finished,
                    diagnostic=diagnostic[:MAX_DIAGNOSTIC_CHARS]))

            # 6. VERIFIED 接受门（blocker B4）：只能来自**当前验证器**的真实
            #    密封报告——seal 真实性 + contract/run/standard/hash 精确身份
            #    全部复核；任一不满足绝不接受、绝不修补/重签（final_report=None）。
            #    （VERIFIED 路径不再单独跑 legacy 后置复核——P5-A 的最终边界
            #    双采集严格覆盖其后置复核的全部判定面。）
            if report is not None and report.verdict is VerificationVerdict.VERIFIED:
                accepted, why = self._accept_verified_report(report, run_id)
                if not accepted:
                    stop = RepairStopReason.REPORT_REJECTED
                    stop_diag = f"verification_report_rejected:{why[:256]}"
                    final_report = None
                    break
                # 6a. P4-D + P5-A：接受门（seal/身份复核）完成后，经**单一权威
                #     快照接口**以版本一致性协议取得最终 BoundarySnapshot——
                #     见证采集暴露的越界立即以该原因停止；权威采集 + 一致性
                #     证明（epoch ledger / 契约 hash / 时钟单调 / 回调异常）
                #     无法证明一致 → UNSTABLE_BOUNDARY fail-closed；越界
                #     （cost 超限/取消/超时/契约漂移）→ final_report=None，
                #     VERIFIED 绝不成为成功结果。此后不得再调用任何
                #     cost/cancel/now/verifier 回调；判定与 RepairOutcome
                #     只依据该快照（finished_at_epoch == snapshot.now）。
                try:
                    bsnap, pre_reason, pre_diag = self._take_final_boundary()
                except Exception as exc:
                    stop = RepairStopReason.UNSTABLE_BOUNDARY
                    stop_diag = f"final_boundary_unstable:{type(exc).__name__}"
                    final_report = None
                    break
                if pre_reason is not None:
                    stop, stop_diag = pre_reason, pre_diag
                    final_report = None
                    break
                reason, diag = self._decide_final_boundary(bsnap)
                if reason is not None:
                    stop, stop_diag = reason, diag
                    final_report = None
                    break
                final_now = bsnap.now
                stop, final_report = RepairStopReason.VERIFIED, report
                break
            # 5b. 非 VERIFIED 报告：既有后置边界复核（attempt 完成后、下一
            #     attempt 前的越界停止——cost/cancel/时钟/契约漂移）。
            reason, diag = self._boundary_violation(pre=False,
                                                    attempt_finished=attempt_finished)
            # 7. 硬失败：立即停止（绝不重试）。
            if hard:
                stop = RepairStopReason.HARD_FAILURE
                stop_diag = diagnostic
                break
            # 8. 重复相同 failure signature → 断路（不烧剩余 attempts）；
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
        # P4-D：VERIFIED 成功路径用最终边界快照的 now 构造 RepairOutcome——
        # 此后零回调（不再调用 now_fn/cost/cancel/verifier）。非成功路径无
        # 边界快照，沿用既有单次 now_fn 读取。
        return RepairOutcome(
            stop_reason=stop, contract_id=self._contract.contract_id,
            contract_hash=self._contract.content_hash, attempts=tuple(attempts),
            final_report=final_report, started_at_epoch=started,
            finished_at_epoch=(final_now if final_now is not None
                               else self._now_fn()), diagnostic=stop_diag)

    # -- VERIFIED 接受门（blocker B4） ------------------------------------------
    def _accept_verified_report(self, report: VerificationReport,
                                run_id: str) -> Tuple[bool, str]:
        """接受 VERIFIED 的完整条件（全部精确一致才接受）：

        1. verdict == VERIFIED（调用方已判）；
        2. seal 经**当前**验证器 ``seal_is_authentic`` 真实性复核通过——
           另一实例/子类代理签发的有效格式报告一律拒绝；
        3. contract_id 与当前不可变契约精确一致；
        4. run_id 与本次 attempt 分配的 run_id 精确一致（非旧 attempt）；
        5. contract_hash / verification standard hash 与当前 verifier/契约
           预期精确一致。
        报告来自本次 collect/verify 调用是结构事实（run() 内局部变量）；
        4+5 将任何旧 attempt/异契约报告排除在外。失败返回 (False, 原因)，
        绝不修补或重新签署外来报告。
        """
        reasons: List[str] = []
        if not self._verifier.seal_is_authentic(report):
            reasons.append("seal_not_authentic_for_current_verifier")
        if report.contract_id != self._contract.contract_id:
            reasons.append("contract_id_mismatch")
        if report.run_id != run_id:
            reasons.append("run_id_mismatch")
        if report.contract_hash != self._contract.content_hash:
            reasons.append("contract_hash_mismatch")
        if report.standard_hash != self._verifier.standard_hash:
            reasons.append("standard_hash_mismatch")
        return (not reasons), ":".join(reasons)

    def _take_final_boundary(self) -> Tuple[BoundarySnapshot,
                                            Optional[RepairStopReason], str]:
        """P5-A：**单一权威快照接口**——版本一致性协议下的双重边界采集。

        P4-D 的单次顺序读取（cancel→cost→now）不是原子快照：最后的 ``now_fn``
        回调仍可改写已读取的 cost/cancel 让越界 VERIFIED 逃逸，且"调整读取
        顺序"或"再多扫一轮"都不能封闭（任意有限读取序列都有最后一个读取项，
        其副作用对更早读取的值不可见）。本协议以**两次采集 + 一致性证明**封闭：

        - **见证采集（acq1，cancel→cost→now）**后先做前置越界判定——见证已
          暴露的越界立即以该原因停止（拒绝路径零逃逸面，无需第二采集；
          P2-R/P3-G(b) 的"cost 回调推时钟"在此被捕获，且不触发第二采集的
          额外回调）；
        - 仅当见证采集干净时进行**权威采集（acq2，now→cancel→cost→now→
          cancel）**——now 夹逼取消/成本读取（now 改写 cost 被其后的 cost
          读取捕获；cost 推时钟被其后的 now 读取捕获），尾随 cancel 见证
          封闭 now 改写取消的通道；
        - **一致性证明**（任一不成立 → 异常 → UNSTABLE_BOUNDARY，零报告）：
          epoch ledger 精确记账（采集窗口内回调调用次数与协议期望一致——
          重入/隐藏调用 → 无法证明一致）；两次采集契约 hash 一致（采集中途
          漂移 → 无法证明一致）；时钟单调 now₁ ≤ now₂ ≤ now₃（回拨 → 无法
          证明一致）；任一回调异常 → 传播；
        - **值聚合一律 fail-closed worst-wins**：cancelled = c1∨c2∨c3、
          cost = max(有读数者)、now = n₃（最新权威读数）——两次采集间的
          值差异绝不取"较乐观"值，绝不作为"已稳定"的信任依据。

        返回 ``(权威快照, 见证越界原因或 None, 诊断)``；调用方此后不得再调用
        任何 cost/cancel/now/verifier 回调。
        """
        self._boundary_active = True
        self._boundary_reentrant = False
        try:
            e0 = self._bepoch
            h1 = self._contract.content_hash
            c1 = bool(self._w_cancel())
            k1: Optional[float] = None
            if self._w_cost_used is not None:
                k1, err = self._read_cost_used()
                if err:
                    k1 = float("inf")
            n1 = float(self._w_now())
            e1 = self._bepoch
        finally:
            self._boundary_active = False
        witness = BoundarySnapshot(contract_hash=h1, cancelled=c1, cost_used=k1,
                                   now=n1, version=e1)
        # 见证采集已暴露的越界 → 立即以该原因停止（final_report=None）。
        pre_reason, pre_diag = self._decide_final_boundary(witness)
        if pre_reason is not None:
            return witness, pre_reason, pre_diag
        self._boundary_active = True
        try:
            n2 = float(self._w_now())
            c2 = bool(self._w_cancel())
            k2: Optional[float] = None
            if self._w_cost_used is not None:
                k2, err = self._read_cost_used()
                if err:
                    k2 = float("inf")
            n3 = float(self._w_now())
            c3 = bool(self._w_cancel())
            e2 = self._bepoch
            h2 = self._contract.content_hash
        finally:
            self._boundary_active = False
        # ---- 版本一致性证明（无法证明一致 → fail-closed）----
        per_acq1 = 2 + (1 if self._w_cost_used is not None else 0)   # cancel+cost?+now
        per_acq2 = 4 + (1 if self._w_cost_used is not None else 0)   # now+cancel+cost?+now+cancel
        if self._boundary_reentrant or (e1 - e0) != per_acq1 \
                or (e2 - e1) != per_acq2:
            raise VerificationError("boundary_version_mismatch")
        if h2 != h1:
            raise VerificationError("boundary_contract_drift_during_snapshot")
        if not (n1 <= n2 <= n3):
            raise VerificationError("boundary_clock_not_monotonic")
        cancelled = bool(c1 or c2 or c3)
        present = [v for v in (k1, k2) if v is not None]
        cost = max(present) if present else None
        return (BoundarySnapshot(contract_hash=h2, cancelled=cancelled,
                                 cost_used=cost, now=n3, version=e2),
                None, "")

    def _decide_final_boundary(self, bsnap: BoundarySnapshot
                               ) -> Tuple[Optional[RepairStopReason], str]:
        """P4-D：**纯快照判定**——不读取任何回调，只依据传入的 BoundarySnapshot
        （契约 hash 漂移 / 成本超限 / 取消 / 新鲜时间越过 deadline 任一 → 越界
        停止；VERIFIED 绝不成为成功结果）。"""
        if bsnap.contract_hash != self._initial_hash:
            return RepairStopReason.CONTRACT_MUTATED, "contract_hash_changed"
        limit = self._contract.budget.cost_limit.amount
        if bsnap.cost_used is not None and bsnap.cost_used > limit:
            return RepairStopReason.BUDGET_EXHAUSTED, "cost_limit_exceeded"
        if bsnap.cancelled:
            return RepairStopReason.CANCELLED, "cancellation_requested"
        if bsnap.now > self._deadline:
            return RepairStopReason.TIMEOUT, "time_budget_exhausted"
        return None, ""

    # -- 边界复核 / 计量器 -------------------------------------------------------
    def _boundary_violation(self, *, pre: bool,
                            attempt_finished: Optional[float] = None
                            ) -> Tuple[Optional[RepairStopReason], str]:
        """contract hash / cost meter / cancellation / deadline 的边界复核
        （blocker B5：读取次序 hash→cost→cancel→time——cost meter 是可能推进
        时钟/翻转取消的调用方回调，其副作用必须被其后的 cancellation 与
        **新鲜当前时间**读取捕获，绝不缓存回调前的旧时间）。

        pre=True：attempt 副作用边界**前**（``used >= limit`` → 零 collect；
        ``now >= deadline`` → 不启动新 attempt）。pre=False：attempt 完成后、
        接受 VERIFIED **前**（``used > limit`` / ``max(完成时间, 新鲜当前时间)
        > deadline`` → 越界）。
        返回 ``(停止原因或 None, 诊断)``。
        """
        if self._contract.content_hash != self._initial_hash:
            return RepairStopReason.CONTRACT_MUTATED, "contract_hash_changed"
        limit = self._contract.budget.cost_limit.amount
        if self._w_cost_used is not None:
            used, err = self._read_cost_used()
            if err:
                return RepairStopReason.BUDGET_EXHAUSTED, err
            over = (used >= limit) if pre else (used > limit)
            if over:
                return RepairStopReason.BUDGET_EXHAUSTED, "cost_limit_exceeded"
        # cost meter 回调之后读取 cancellation（回调可能翻转取消标志）。
        if bool(self._w_cancel()):
            return RepairStopReason.CANCELLED, "cancellation_requested"
        if pre:
            if self._w_now() >= self._deadline:
                return RepairStopReason.TIMEOUT, "time_budget_exhausted"
        elif attempt_finished is not None:
            # 全部回调结束后的新鲜时间（cost meter 可能已把时钟推过 deadline）。
            finished = max(float(attempt_finished), float(self._w_now()))
            if finished > self._deadline:
                return RepairStopReason.TIMEOUT, "time_budget_exhausted"
        return None, ""

    def _read_cost_used(self) -> Tuple[float, str]:
        """严格 cost meter 读取（零误判）：严格数值类型（bool/str 拒绝）、finite、
        ``>= 0``；meter 异常 / NaN / Inf / 负数一律 fail-closed——返回
        ``(+inf, 诊断)`` → BUDGET_EXHAUSTED，绝不误判为可用预算。"""
        try:
            raw = self._w_cost_used()
        except Exception as exc:
            return float("inf"), f"cost_meter_error:{type(exc).__name__}"
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return float("inf"), f"cost_meter_invalid_type:{type(raw).__name__}"
        value = float(raw)
        if not math.isfinite(value):
            return float("inf"), "cost_meter_non_finite"
        if value < 0:
            return float("inf"), "cost_meter_negative"
        return value, ""

    # -- 工具 ----------------------------------------------------------------
    def _allocate_ids(self, n: int) -> Tuple[str, str]:
        """身份分配（blocker B6）：run_id_factory 输出**直接**经公开的统一
        canonical ``validate_identity``（词法 contract + 秘密形态拒绝）——
        不得先 ``str()`` 强制转换非字符串返回值；原始秘密绝不进入
        AttemptRecord（拒绝先于存储）。attempt_id 同走同一 canonical contract。
        """
        from .models import validate_identity
        attempt_id = validate_identity(f"att_{n:02d}_{uuid.uuid4().hex[:8]}",
                                       "attempt_id")
        raw = self._run_id_factory(attempt_id)
        if not isinstance(raw, str):
            raise VerificationError(
                f"run_id_factory 必须返回 str，得到 {type(raw).__name__}")
        run_id = validate_identity(raw, "run_id")
        if not run_id or run_id in self._seen_run_ids:
            raise VerificationError(
                f"run_id_factory 必须产出唯一非空 run_id，得到 {run_id!r}")
        self._seen_run_ids.add(run_id)
        return attempt_id, run_id
