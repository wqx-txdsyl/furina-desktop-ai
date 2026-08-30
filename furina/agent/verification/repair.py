"""Phase 16F — BoundedRepairLoop：严格有界修复循环（16F 任务书 §5 + 关键锁定 9–12
+ Reviewer Patch 1 blocker 4/6 + Reviewer Patch 3（blocker B3）+ Patch 4（P4-D）
+ Patch 6（P6-A）。

- **接受 VERIFIED 前的真正封闭最终边界（P6-A：单一权威快照源）**：
  ``_accept_verified_report``（seal 认证 / standard·hash 属性访问——都可能携带
  调用方回调副作用）**完成后**，最终边界**只**从调用方提供的**单一权威边界
  快照源**（``boundary_snapshot``——一次调用原子返回 contract hash /
  cancellation / cost / now / version 的受控共享状态）取得权威
  :class:`BoundarySnapshot`：见证读取暴露的越界立即停止（拒绝路径零逃逸面，
  零第二读取）；仅当见证干净时做第二次读取并**证明同一状态版本**（version
  一致 + 契约 hash / cancelled / cost 逐值一致 + now 单调不减），无法取得
  同一状态版本 → ``UNSTABLE_BOUNDARY`` fail-closed（final_report=None）。
  判定与 RepairOutcome 构造**只依据该快照**（``snapshot.now`` 直接作为
  finished_at_epoch），此后零回调（cost/cancel/now/verifier 与快照源一律
  不再调用）。越界（成本超限/取消/超时/契约漂移）→ 立即停止且
  ``final_report=None``（VERIFIED 绝不成为成功结果）。

  **为什么独立的 effectful cost/cancel/now 回调不能构成最终边界（P6-A 移除
  P4-D/P5-A 的伪原子有限回调协议）**：任何由独立回调组成的有限读取序列都有
  **最后一个读取项**，其内部对其它边界状态的改写对更早读取的值不可见——
  调整读取顺序、双采集、epoch 调用计数（wrapper 记账）都无法观察"最后一个
  回调内部改写其它状态"，因此把独立回调包装后宣称为原子快照本身就是伪原子。
  唯一封闭结构是**真正的单一权威快照源**：一次调用返回同一状态版本的全部
  边界值（源内部回调的改写在值读取前完成、随快照整体可见），配合 version
  协议（状态任何变更递增 version）证明两次读取之间状态未变。未提供快照源
  （或快照源异常 / 版本不一致 / 值漂移 / 时钟回拨）→ VERIFIED 绝不被接受
  （``UNSTABLE_BOUNDARY``）；attempt 生命周期内（attempt 前/factory 后/
  approval 后/非 VERIFIED 后置）的边界复核仍走独立回调——那些位置每个回调
  的副作用都被其后的读取捕获，且从不宣称为原子快照。

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
    "BoundarySnapshot",
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


def _validate_boundary_snapshot_fields(contract_hash: Any, cancelled: Any,
                                       cost_used: Any, now: Any,
                                       version: Any) -> None:
    """P7-A：BoundarySnapshot 字段严格类型校验（静态失败码，零值回显）——
    contract_hash（非空 str）/ cancelled（严格 bool）/ cost_used（None 或
    非负有限数值，bool 拒绝）/ now（有限数值，bool 拒绝）/ version（非负
    int，bool 拒绝）。构造期（``__post_init__``）与权威读取期（快照源可能
    经 ``object.__new__`` 旁路构造出非法实例）双重执行，绝不补默认值/强转。"""
    if not isinstance(contract_hash, str) or not contract_hash:
        raise VerificationError("boundary_snapshot_contract_hash_invalid")
    if not isinstance(cancelled, bool):
        raise VerificationError("boundary_snapshot_cancelled_not_bool")
    if cost_used is not None:
        if isinstance(cost_used, bool) or not isinstance(cost_used, (int, float)) \
                or not math.isfinite(float(cost_used)) or float(cost_used) < 0:
            raise VerificationError("boundary_snapshot_cost_invalid")
    if isinstance(now, bool) or not isinstance(now, (int, float)) \
            or not math.isfinite(float(now)):
        raise VerificationError("boundary_snapshot_now_invalid")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise VerificationError("boundary_snapshot_version_invalid")


@dataclass(frozen=True)
class BoundarySnapshot:
    """P6-A：接受 VERIFIED 前的**单一权威边界快照**（快照源一次调用原子返回）。

    全部字段来自**同一次**快照源调用（同一状态版本）——判定与 RepairOutcome
    构造**只依据本快照**；此后不得再调用任何 cost/cancel/now/verifier 回调
    或快照源。``version`` 是快照源的状态版本（受控共享状态协议：状态任何
    变更递增 version；两次读取 version 一致 ⇒ 状态未变）。

    P7-A：本类是**唯一**可被 :class:`BoundedRepairLoop` 接受的权威快照值——
    Furina 自有、冻结（frozen dataclass）、构造期经
    :func:`_validate_boundary_snapshot_fields` 严格类型校验；权威读取通道
    （``_read_boundary_snapshot``）按**精确类型**接受（``type(x) is
    BoundarySnapshot``），Mapping、dict、代理及子类一律拒绝。
    """

    contract_hash: str
    cancelled: bool
    cost_used: Optional[float]      # None = 未注入 cost meter
    now: float
    version: int = 0

    def __post_init__(self) -> None:
        _validate_boundary_snapshot_fields(self.contract_hash, self.cancelled,
                                           self.cost_used, self.now,
                                           self.version)


class BoundedRepairLoop:
    """同一不可变契约上的有界验证-修复驱动器（验证权威始终在 IndependentVerifier）。"""

    def __init__(self, *, contract: WorkContract, verifier: IndependentVerifier,
                 collect_evidence: Callable[[str, str], Mapping[str, Any]],
                 cancel_requested: Optional[Callable[[], bool]] = None,
                 approval_authority: Optional[Callable[[str, str], str]] = None,
                 cost_used: Optional[Callable[[], float]] = None,
                 run_id_factory: Optional[Callable[[str], str]] = None,
                 now_fn: Callable[[], float] = time.time,
                 boundary_snapshot: Optional[Callable[[], BoundarySnapshot]] = None
                 ) -> None:
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
        if boundary_snapshot is not None and not callable(boundary_snapshot):
            raise VerificationError("boundary_snapshot 必须是 callable（单一权威快照源）")

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
        # P6-A：单一权威边界快照源（接受 VERIFIED 前的最终边界唯一读取通道）。
        # 只接受 Furina 自有、冻结、严格类型校验的 :class:`BoundarySnapshot`
        # 精确类型（P7-A——Mapping/dict/代理/子类一律拒绝）。未提供 → 无法
        # 取得同一状态版本的 contract/cancel/cost/now → VERIFIED 绝不被接受
        # （UNSTABLE_BOUNDARY fail-closed）。
        self._boundary_snapshot = boundary_snapshot
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
        final_now: Optional[float] = None    # P6-A：最终边界快照的 now（构造
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
            #    （VERIFIED 路径不再单独跑 legacy 后置复核——P6-A 的最终
            #    边界单一权威快照严格覆盖其后置复核的全部判定面。）
            if report is not None and report.verdict is VerificationVerdict.VERIFIED:
                accepted, why = self._accept_verified_report(report, run_id)
                if not accepted:
                    stop = RepairStopReason.REPORT_REJECTED
                    stop_diag = f"verification_report_rejected:{why[:256]}"
                    final_report = None
                    break
                # 6a. P6-A：接受门（seal/身份复核）完成后，最终边界**只**从
                #     单一权威快照源取得 BoundarySnapshot：见证读取暴露的越界
                #     立即以该原因停止；第二次读取必须证明同一状态版本
                #     （version 一致 + 逐值一致 + now 单调）——无法取得同一
                #     版本 → UNSTABLE_BOUNDARY fail-closed；越界（cost 超限/
                #     取消/超时/契约漂移）→ final_report=None，VERIFIED 绝不
                #     成为成功结果。此后不得再调用任何 cost/cancel/now/
                #     verifier 回调或快照源；判定与 RepairOutcome 只依据该
                #     快照（finished_at_epoch == snapshot.now）。
                try:
                    bsnap, pre_reason, pre_diag = self._take_final_boundary()
                except Exception as exc:
                    stop = RepairStopReason.UNSTABLE_BOUNDARY
                    # 本模块自产的 VerificationError 携带静态失败码（零秘密），
                    # 可安全进入诊断；外部异常只记类型名（零 raw secret 回显）。
                    detail = (scrub_secrets(str(exc))[:128]
                              if isinstance(exc, VerificationError)
                              else type(exc).__name__)
                    stop_diag = f"final_boundary_unstable:{detail}"
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
        # P6-A：VERIFIED 成功路径用最终边界快照的 now 构造 RepairOutcome——
        # 此后零回调（不再调用 now_fn/cost/cancel/verifier/快照源）。非成功
        # 路径无边界快照，沿用既有单次 now_fn 读取。
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

    # -- 最终边界（P6-A：单一权威快照源；P7-A：精确类型不可变快照值） ----------
    def _read_boundary_snapshot(self) -> BoundarySnapshot:
        """单次调用快照源并做**精确类型**校验（P7-A，fail-closed）。

        快照源必须一次调用原子返回 Furina 自有、冻结、严格类型校验的
        :class:`BoundarySnapshot` **实例本身**——按精确类型匹配（``type(x)
        is BoundarySnapshot``）接受：任意 ``Mapping``（含 dict、代理）与
        ``BoundarySnapshot`` 子类一律拒绝（拒绝消息只用静态失败码 + 安全
        类型名）。本方法**绝不**调用外部对象的 ``keys()``、``__getitem__()``
        、``str()``、``repr()``——字段只能作为本类自有冻结属性经构造期
        （``__post_init__``）与读取期（防御 ``object.__new__`` 旁路构造的
        非法实例）双重严格类型校验后使用，绝不补默认值/强转。源异常/类型
        不符/字段违约一律 :class:`VerificationError`（调用方转
        UNSTABLE_BOUNDARY）。
        """
        try:
            raw = self._boundary_snapshot()
        except Exception as exc:
            raise VerificationError(
                f"boundary_snapshot_error:{type(exc).__name__}") from None
        if type(raw) is not BoundarySnapshot:
            raise VerificationError(
                f"boundary_snapshot_not_boundary_snapshot:"
                f"{type(raw).__name__}")
        # 权威读取期重校验：快照源理论上可经 object.__new__ 绕过构造期校验
        # 交付字段违约的实例——零默认值/零强转，违约即 fail-closed。
        _validate_boundary_snapshot_fields(raw.contract_hash, raw.cancelled,
                                           raw.cost_used, raw.now, raw.version)
        return raw

    def _take_final_boundary(self) -> Tuple[BoundarySnapshot,
                                            Optional[RepairStopReason], str]:
        """P6-A：**单一权威快照源**下的最终边界——两次原子读取 + 同版本证明。

        P4-D 的单次顺序读取与 P5-A 的双重采集 + epoch 记账都是**伪原子**：
        任何由独立 effectful 回调组成的有限读取序列都有最后一个读取项，其
        内部对其它边界状态的改写对更早读取的值不可见（wrapper 记账只能证明
        "每个回调被调用了几次"，证明不了"最后一个回调没有改写其它状态"）。
        本协议因此**只**信任单一权威快照源——一次调用原子返回同一状态版本的
        不可变 :class:`BoundarySnapshot`（P7-A：精确类型、冻结、严格校验）：

        - **见证读取（s1）**后先做越界判定——见证已暴露的越界立即以该原因
          停止（拒绝路径零逃逸面，零第二读取）；
        - 仅当见证干净时做**权威读取（s2）**并证明同一状态版本：version
          一致 + contract hash / cancelled / cost 逐值一致（源违反"状态变更
          必须递增 version"的协议义务 → 值漂移被捕获）+ now 单调不减；
          任一不成立 → 异常 → 调用方 UNSTABLE_BOUNDARY fail-closed；
        - 未提供快照源 → 无法取得同一状态版本的 contract/cancel/cost/now →
          直接异常（UNSTABLE_BOUNDARY）——独立的 effectful 回调绝不被包装后
          宣称为原子快照。

        返回 ``(权威快照, 见证越界原因或 None, 诊断)``；调用方此后不得再调用
        任何 cost/cancel/now/verifier 回调或快照源。
        """
        if self._boundary_snapshot is None:
            raise VerificationError("boundary_snapshot_source_unavailable")
        s1 = self._read_boundary_snapshot()
        # 见证读取已暴露的越界 → 立即以该原因停止（final_report=None）。
        pre_reason, pre_diag = self._decide_final_boundary(s1)
        if pre_reason is not None:
            return s1, pre_reason, pre_diag
        s2 = self._read_boundary_snapshot()
        # ---- 同一状态版本证明（无法证明 → fail-closed）----
        if s2.version != s1.version:
            raise VerificationError("boundary_version_mismatch")
        if s2.contract_hash != s1.contract_hash:
            raise VerificationError("boundary_contract_drift_during_snapshot")
        if s2.cancelled != s1.cancelled:
            raise VerificationError("boundary_cancelled_value_drift")
        if s2.cost_used != s1.cost_used:
            raise VerificationError("boundary_cost_value_drift")
        if s2.now < s1.now:
            raise VerificationError("boundary_clock_not_monotonic")
        return s2, None, ""

    def _decide_final_boundary(self, bsnap: BoundarySnapshot
                               ) -> Tuple[Optional[RepairStopReason], str]:
        """P4-D/P6-A：**纯快照判定**——不读取任何回调，只依据传入的 BoundarySnapshot
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

        这些是 attempt 生命周期内的**顺序复核**（每个回调副作用都被其后的
        读取捕获，从不宣称为原子快照）；接受 VERIFIED 前的最终边界走
        ``_take_final_boundary``（P6-A 单一权威快照源）。
        """
        if self._contract.content_hash != self._initial_hash:
            return RepairStopReason.CONTRACT_MUTATED, "contract_hash_changed"
        limit = self._contract.budget.cost_limit.amount
        if self._cost_used is not None:
            used, err = self._read_cost_used()
            if err:
                return RepairStopReason.BUDGET_EXHAUSTED, err
            over = (used >= limit) if pre else (used > limit)
            if over:
                return RepairStopReason.BUDGET_EXHAUSTED, "cost_limit_exceeded"
        # cost meter 回调之后读取 cancellation（回调可能翻转取消标志）。
        if bool(self._cancel_requested()):
            return RepairStopReason.CANCELLED, "cancellation_requested"
        if pre:
            if self._now_fn() >= self._deadline:
                return RepairStopReason.TIMEOUT, "time_budget_exhausted"
        elif attempt_finished is not None:
            # 全部回调结束后的新鲜时间（cost meter 可能已把时钟推过 deadline）。
            finished = max(float(attempt_finished), float(self._now_fn()))
            if finished > self._deadline:
                return RepairStopReason.TIMEOUT, "time_budget_exhausted"
        return None, ""

    def _read_cost_used(self) -> Tuple[float, str]:
        """严格 cost meter 读取（零误判）：严格数值类型（bool/str 拒绝）、finite、
        ``>= 0``；meter 异常 / NaN / Inf / 负数一律 fail-closed——返回
        ``(+inf, 诊断)`` → BUDGET_EXHAUSTED，绝不误判为可用预算。"""
        try:
            raw = self._cost_used()
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
