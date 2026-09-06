"""Phase 16F — BoundedRepairLoop：严格有界修复循环（16F 任务书 §5 + 关键锁定 9–12
+ Reviewer Patch 1 blocker 4/6 + Reviewer Patch 3（blocker B3）+ Patch 4（P4-D）
+ Patch 6（P6-A）+ Patch 8（B1–B4）。

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

Patch 8（外部 Reviewer 确认的四组 blocker）：

- **B1 消费 post-attempt 边界结果**：非 VERIFIED attempt 完成后的
  CONTRACT_MUTATED / BUDGET_EXHAUSTED / CANCELLED / TIMEOUT 立即停止，优先于
  HARD_FAILURE / REPEATED_FAILURE / ATTEMPTS_EXHAUSTED；boundary stop 时
  final_report=None、已完成 attempt 记录保留——绝不依赖"下一轮 pre-check
  偶然补抓"。
- **B2 BoundarySnapshot 真正 builtin 值语义**：``type(x) is …`` 精确匹配
  （bool/str/int/float 子类全部拒绝），数值构造期规范化为 builtin float，
  快照内不保留用户子类——敌意 ``__gt__``/``__lt__``/``__float__`` 无法介入
  越界判定；拒绝前绝不调用外部对象任何协议方法。
- **B3 全部 repair 时钟读取 fail-closed**：单一 ``_read_clock`` 严格通道
  （仅 builtin int/float；bool/子类/NaN/±Inf/非数值/回调异常 →
  VerificationError）覆盖 deadline 构造 / run started / attempt
  started·finished / pre·post boundary / 非成功 finished 时间；
  AttemptRecord / RepairOutcome 时间戳构造面有限性结构校验——NaN 比较恒
  False 的 VERIFIED 通道被关闭。
- **B4 非字符串/敌意对象封闭补全**：approval_authority 只接受 builtin str
  （精确 "approve" 放行；回调异常/非字符串静态 fail-closed）；
  cancel_requested 只接受 builtin bool（非 bool/异常绝不当作 False）；
  cost_used 只接受 builtin 数值；异常诊断面 ``_safe_exc_diag``（args 全为
  builtin str 才脱敏导出，否则只记类型名）——敌意 ``__str__``/``__repr__``/
  ``__bool__``/``__eq__`` 零调用、raw secret 零传播。

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

from furina.agent.work_contract import MAX_ATTEMPTS, WorkContract

from .models import (
    MAX_DIAGNOSTIC_CHARS,
    VerificationError,
    VerificationInputError,
    VerificationReport,
    VerificationVerdict,
    _REPORT_ID_PATTERN,
    _SHA256_PATTERN,
    _safe_type_name,
    scrub_secrets,
    validate_identity,
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


def _finite_epoch(value: Any, field_name: str) -> float:
    """P8-B3 + P9-B3：时间戳字段唯一入口——只接受 **builtin** int/float
    （bool/数值子类/NaN/±Inf/非数值一律 :class:`VerificationError`），返回
    规范化 builtin float。RepairOutcome / AttemptRecord 的时间面因此**结构上
    不可能**携带 NaN/Inf（NaN 比较恒 False 的 VERIFIED 通道被构造面关闭）。"""
    if type(value) not in (int, float):
        raise VerificationError(
            f"{field_name} 必须是 builtin int/float，得到 "
            f"{_safe_type_name(type(value))}")
    v = float(value)
    if not math.isfinite(v):
        raise VerificationError(f"{field_name} 必须是有限数值（NaN/Inf 拒绝）")
    return v


_ATTEMPT_STR_FIELDS = ("attempt_id", "run_id", "contract_hash", "verdict",
                       "report_id", "failure_signature")
#: P10-B2：AttemptRecord.verdict 封闭词表（"" = collect 层失败）。
_ATTEMPT_VERDICTS = ("", "VERIFIED", "FAILED", "INCONCLUSIVE")


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
        # P9-B3：公开冻结值模型 exact-builtin 扫描——全部字符串字段必须是
        # **builtin str**（子类不得进入冻结对象或导出树）。
        for _name in _ATTEMPT_STR_FIELDS:
            if type(getattr(self, _name)) is not str:
                raise VerificationError(
                    f"{_name} 必须是 builtin str，得到 "
                    f"{_safe_type_name(type(getattr(self, _name)))}")
        # P10-B2：语义一致性——attempt_id/run_id 走 canonical identity；
        # contract_hash 严格 64 位小写 hex；verdict 封闭词表；
        # verdict="" ⇒ report_id="" 且 failure_signature 为 64-hex 签名；
        # verdict≠"" ⇒ report_id 为 vrp_ 报告身份且 VERIFIED ⇒ 签名为 ""。
        validate_identity(self.attempt_id, "attempt_id")
        validate_identity(self.run_id, "run_id")
        if not _SHA256_PATTERN.match(self.contract_hash):
            raise VerificationError("attempt contract_hash 必须是 64 位小写 hex")
        if self.verdict not in _ATTEMPT_VERDICTS:
            raise VerificationError(
                f"attempt verdict 必须是封闭词表值，得到 "
                f"{scrub_secrets(self.verdict)[:32]!r}")
        if self.verdict == "":
            if self.report_id != "" \
                    or not _SHA256_PATTERN.match(self.failure_signature):
                raise VerificationError(
                    "collect 层失败记录必须 report_id=\"\" 且携带 64-hex 签名")
        else:
            if not _REPORT_ID_PATTERN.match(self.report_id):
                raise VerificationError("attempt report_id 词法非法")
            if self.verdict == "VERIFIED":
                if self.failure_signature != "":
                    raise VerificationError("VERIFIED 记录不得携带失败签名")
            else:
                # P11-B2：FAILED/INCONCLUSIVE 必须携带 64 位小写 hex 失败签名
                #（空签名缺口关闭——reviewer 实测 FAILED + failure_signature=""
                # 曾可构造）。
                if not _SHA256_PATTERN.match(self.failure_signature):
                    raise VerificationError(
                        "FAILED/INCONCLUSIVE 记录必须携带 64 位小写 hex 失败签名")
        # P8-B3：时间戳有限数值结构校验（bool/子类/NaN/Inf 拒绝）+ float 规范。
        object.__setattr__(self, "started_at_epoch",
                           _finite_epoch(self.started_at_epoch, "started_at_epoch"))
        object.__setattr__(self, "finished_at_epoch",
                           _finite_epoch(self.finished_at_epoch, "finished_at_epoch"))
        # P10-B2：attempt 时序一致。
        if self.finished_at_epoch < self.started_at_epoch:
            raise VerificationError("attempt 时序非法：finished < started")
        # P9-B3：诊断必须是 builtin str——非字符串拒绝（绝不 `value or ""`
        # truthiness、绝不调用其 __bool__/__str__）；秘密边界（blocker 6）：
        # 诊断字符串面统一脱敏后限长。
        if type(self.diagnostic) is not str:
            raise VerificationError(
                f"diagnostic 必须是 builtin str，得到 "
                f"{_safe_type_name(type(self.diagnostic))}")
        object.__setattr__(self, "diagnostic",
                           scrub_secrets(self.diagnostic)[:MAX_DIAGNOSTIC_CHARS])


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
        # P9-B3：公开冻结值模型 exact-builtin 扫描——stop_reason/容器/元素/
        # final_report 全部精确类型（子类不得冒充进入导出树）。
        if type(self.stop_reason) is not RepairStopReason:
            raise VerificationError(
                f"stop_reason 必须是 RepairStopReason，得到 "
                f"{_safe_type_name(type(self.stop_reason))}")
        if type(self.contract_id) is not str or type(self.contract_hash) is not str:
            raise VerificationError("contract_id/contract_hash 必须是 builtin str")
        if type(self.attempts) is not tuple:
            raise VerificationError("attempts 必须是 builtin tuple（封闭导出树）")
        # P12-B2：O(1) 全局 attempt 数量硬上限——**先封数量再遍历账本**（超限
        # 账本零遍历、元素级校验不执行；reviewer 实测 100 个身份唯一、时序
        # 合法的 attempts 曾可构造而 WorkContract 全局上限为 99——通道关闭）。
        if len(self.attempts) > MAX_ATTEMPTS:
            raise VerificationError(
                f"attempts 数量 {len(self.attempts)} 超界全局硬上限 "
                f"{MAX_ATTEMPTS}（先封数量再遍历）")
        if not all(type(a) is AttemptRecord for a in self.attempts):
            raise VerificationError("attempts 必须全部是 AttemptRecord")
        if self.final_report is not None \
                and type(self.final_report) is not VerificationReport:
            raise VerificationError("final_report 必须是 None 或 VerificationReport")
        # P10-B2：语义一致性——contract_id canonical、contract_hash 64-hex、
        # 时序单调、VERIFIED 终局必须携带与最后 attempt 精确一致的 VERIFIED
        # 报告；非 VERIFIED 终局绝不携带 VERIFIED 报告。（closeout 明确：
        # RepairOutcome 是结构化执行结果，不是第二验证权威——final_report 的
        # seal 真实性仍只能由当前 IndependentVerifier 复核。）
        validate_identity(self.contract_id, "contract_id")
        if not _SHA256_PATTERN.match(self.contract_hash):
            raise VerificationError("contract_hash 必须是 64 位小写 hex")
        # P8-B3：时间戳有限数值结构校验——RepairOutcome 不得包含 NaN/Inf。
        object.__setattr__(self, "started_at_epoch",
                           _finite_epoch(self.started_at_epoch, "started_at_epoch"))
        object.__setattr__(self, "finished_at_epoch",
                           _finite_epoch(self.finished_at_epoch, "finished_at_epoch"))
        if self.finished_at_epoch < self.started_at_epoch:
            raise VerificationError("终局时序非法：finished < started")
        for a in self.attempts:
            if a.contract_hash != self.contract_hash:
                raise VerificationError("attempt 契约 hash 与终局不一致")
        if self.stop_reason is RepairStopReason.VERIFIED:
            if self.final_report is None:
                raise VerificationError(
                    "VERIFIED 终局必须携带 final_report（不得为 None）")
            if self.final_report.verdict is not VerificationVerdict.VERIFIED:
                raise VerificationError("VERIFIED 终局的 final_report verdict 非法")
            if not self.attempts:
                raise VerificationError("VERIFIED 终局必须携带非空 attempts")
        elif self.final_report is not None \
                and self.final_report.verdict is VerificationVerdict.VERIFIED:
            raise VerificationError(
                "非 VERIFIED 终局不得携带 VERIFIED final_report")
        # P11-B1：final_report 非 None 时（无论 stop_reason）与终局/最后
        # attempt 的**完整身份绑定**——contract_id、contract_hash、run_id、
        # report_id、verdict 全部一致（RepairOutcome 本身只负责结构绑定；
        # seal 真实性只能经 IndependentVerifier 的 outcome 真实性 API 复核）。
        if self.final_report is not None:
            rep = self.final_report
            if rep.contract_id != self.contract_id:
                raise VerificationError(
                    "final_report contract_id 与终局不一致（跨契约报告拒绝）")
            if rep.contract_hash != self.contract_hash:
                raise VerificationError(
                    "final_report contract_hash 与终局不一致")
            if not self.attempts:
                raise VerificationError(
                    "携带 final_report 的终局必须包含最后 attempt")
            last = self.attempts[-1]
            if rep.run_id != last.run_id or rep.report_id != last.report_id \
                    or rep.verdict.value != last.verdict:
                raise VerificationError(
                    "final_report 与最后 attempt 身份不一致")
            if last.contract_hash != self.contract_hash:
                raise VerificationError("最后 attempt 契约 hash 与终局不一致")
        # P11-B2：attempt 账本语义闭合——身份唯一、时间窗封闭、按时间非递减。
        seen_attempt_ids: set = set()
        seen_attempt_runs: set = set()
        prev_finish = self.started_at_epoch
        for a in self.attempts:
            if a.attempt_id in seen_attempt_ids or a.run_id in seen_attempt_runs:
                raise VerificationError("attempt 身份重复（attempt_id/run_id）")
            seen_attempt_ids.add(a.attempt_id)
            seen_attempt_runs.add(a.run_id)
            if a.started_at_epoch < prev_finish:
                raise VerificationError(
                    "attempt 时间轴非法（未按时间非递减排列）")
            if a.finished_at_epoch > self.finished_at_epoch \
                    or a.started_at_epoch < self.started_at_epoch:
                raise VerificationError(
                    "attempt 时间完全/部分落在 outcome 时间窗之外")
            prev_finish = a.finished_at_epoch
        # P9-B3：诊断必须是 builtin str（绝不 `value or ""` truthiness）。
        if type(self.diagnostic) is not str:
            raise VerificationError(
                f"diagnostic 必须是 builtin str，得到 "
                f"{_safe_type_name(type(self.diagnostic))}")
        object.__setattr__(self, "diagnostic",
                           scrub_secrets(self.diagnostic)[:MAX_DIAGNOSTIC_CHARS])


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


def _safe_exc_diag(exc: BaseException) -> str:
    """P9-B2：异常诊断面**完全封闭**——

    - 不对不可信异常调用 ``getattr(exc, "args")``/``str()``/``repr()``/
      ``bool()`` 或任何用户属性（敌意异常可用 ``args`` property 让携密
      RuntimeError 直接逃出 repair loop——通道关闭）；
    - 仅当 ``type(exc)`` **恰为**本模块白名单静态错误类型
      :class:`VerificationError` / :class:`VerificationInputError` /
      :class:`HardBackendFailure`（Furina 自有的类型化信号，exact 类型匹配
      ——敌意子类经 ``args`` property 劫持的通道关闭）时，经**直接属性
      访问** ``exc.args`` 读取并脱敏导出（消息全部为构造期写入的 builtin
      str 静态失败码/信号文本）；
    - 其余一切外部异常只输出 ``external_exception`` 固定安全错误码 + 经
      :func:`_safe_type_name` 清洗后的类型名——不输出任何动态消息；
    - 全过程 try/except 包裹：诊断本身绝不可能抛出，绝不可能逃出 repair
      loop；raw secret 不存储、不哈希、不导出。
    """
    try:
        tp = type(exc)
        if tp is VerificationError or tp is VerificationInputError \
                or tp is HardBackendFailure:
            args = exc.args                     # 白名单类型：直接属性访问
            if type(args) is tuple and args \
                    and all(type(a) is str for a in args):
                return scrub_secrets(" ".join(args))[:MAX_DIAGNOSTIC_CHARS]
        return f"external_exception:{_safe_type_name(tp)}"
    except Exception:
        return "external_exception"


def _validate_boundary_snapshot_fields(contract_hash: Any, cancelled: Any,
                                       cost_used: Any, now: Any,
                                       version: Any) -> None:
    """P7-A + P8-B2：BoundarySnapshot 字段**精确 builtin 类型**校验（静态失败
    码，零值回显）——contract_hash（builtin str 且 canonical 64 位小写
    SHA-256）/ cancelled（builtin bool）/ cost_used（None 或 builtin
    int/float，有限非负）/ now（builtin int/float，有限）/ version（builtin
    int，非负）。

    全部校验只做 ``type(x) is …`` 精确匹配——**bool、str/int/float 子类一律
    拒绝**（敌意数值子类可重载 ``__gt__``/``__lt__``/``__float__`` 使越界
    比较恒 False）；**拒绝前绝不调用外部对象的** ``__float__``/``__eq__``/
    ``__ne__``/``__gt__``/``__lt__``/``__bool__``/``__str__``/``__repr__``
    （``float(x)`` 只在精确类型确认后执行——builtin 值语义固定）。构造期
    （``__post_init__``）与权威读取期（快照源可能经 ``object.__new__`` 旁路
    构造出非法实例）双重执行，绝不补默认值/强转。"""
    if type(contract_hash) is not str or not contract_hash \
            or not _SHA256_PATTERN.match(contract_hash):
        raise VerificationError("boundary_snapshot_contract_hash_invalid")
    if type(cancelled) is not bool:
        raise VerificationError("boundary_snapshot_cancelled_not_bool")
    if cost_used is not None:
        if type(cost_used) not in (int, float):
            raise VerificationError("boundary_snapshot_cost_invalid")
        cost_value = float(cost_used)
        if not math.isfinite(cost_value) or cost_value < 0:
            raise VerificationError("boundary_snapshot_cost_invalid")
    if type(now) not in (int, float):
        raise VerificationError("boundary_snapshot_now_invalid")
    if not math.isfinite(float(now)):
        raise VerificationError("boundary_snapshot_now_invalid")
    if type(version) is not int or version < 0:
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

    P8-B2：字段是**真正的 builtin 值语义**——数值字段在构造时复制/规范化为
    builtin float（``type(x)`` 恒为 float/int/str/bool/NoneType 本尊），快照
    内**绝不保留**任何用户子类实例；全部越界判定（``>``/``<``/``==``）因此
    是 builtin 比较，敌意子类无从介入。
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
        # P8-B2：校验通过（builtin 精确类型）后规范化——int → float、值复制，
        # 冻结对象内不保留任何调用方传入的原始子类/引用。
        object.__setattr__(self, "cost_used",
                           None if self.cost_used is None
                           else float(self.cost_used))
        object.__setattr__(self, "now", float(self.now))


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
        # P10-B1：权威装配边界 exact trusted type——WorkContract 与
        # IndependentVerifier 的子类（可覆盖 verify()/seal_is_authentic()/
        # standard_hash 伪造零 checks VERIFIED 或固定 True 认证）不得进入
        # verifier/repair 权威路径。
        if type(contract) is not WorkContract:
            raise VerificationError(
                f"repair 必须绑定 exact WorkContract（子类不得进入权威路径），"
                f"得到 {_safe_type_name(type(contract))}")
        if type(verifier) is not IndependentVerifier:
            raise VerificationError(
                f"repair 必须绑定 exact IndependentVerifier（子类不得进入权威"
                f"路径），得到 {_safe_type_name(type(verifier))}")
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
        # P10-B1：安全关键 verifier 调用经**类级**绑定取得（verify /
        # seal_is_authentic / standard_hash）——exact trusted type + 类级取用
        # 使实例属性 shadowing 与子类 override 都无法替换权威行为。
        self._verify_submission = IndependentVerifier.verify.__get__(verifier)
        self._seal_is_authentic = IndependentVerifier.seal_is_authentic.__get__(
            verifier)
        self._verifier_standard_hash = IndependentVerifier.standard_hash.fget(
            verifier)
        self._collect = collect_evidence
        # P9-B1：optional callback 一律 **只**用 `is None` 判断是否采用默认值
        # ——`callback or default` 会调用回调对象的 __bool__：falsey callable
        # （__bool__ 返回 False 的可调用对象）被静默替换为默认函数、其真实
        # 返回值（如 cancel=True）被丢弃；__bool__ 主动抛异常的 callable 也会
        # 在构造期爆炸。审计覆盖 BoundedRepairLoop 内全部 optional 回调：
        # cancel_requested / run_id_factory（此处）、approval_authority /
        # cost_used / boundary_snapshot（直接赋值 + `is None` 判定）。
        self._cancel_requested = (cancel_requested if cancel_requested is not None
                                  else (lambda: False))
        self._approval_authority = approval_authority
        self._cost_used = cost_used
        self._run_id_factory = (run_id_factory if run_id_factory is not None
                                else (lambda attempt_id: f"run_{attempt_id}"))
        self._now_fn = now_fn
        # P6-A：单一权威边界快照源（接受 VERIFIED 前的最终边界唯一读取通道）。
        # 只接受 Furina 自有、冻结、严格类型校验的 :class:`BoundarySnapshot`
        # 精确类型（P7-A——Mapping/dict/代理/子类一律拒绝）。未提供 → 无法
        # 取得同一状态版本的 contract/cancel/cost/now → VERIFIED 绝不被接受
        # （UNSTABLE_BOUNDARY fail-closed）。
        self._boundary_snapshot = boundary_snapshot
        self._initial_hash = contract.content_hash
        # P9-B4：最后可信时钟哨兵（-inf 只存在于构造期第一次读取之前——读取
        # 成功即被覆盖为有限值；读取失败则构造直接失败，无对象存活）。
        self._last_trusted_clock = float("-inf")
        # P8-B3 + P9-B4：构造期 deadline 由**单一严格时钟读取**派生——非法
        # 时钟（bool/子类/NaN/Inf/非数值/回调异常）在构造面即 VerificationError
        # fail-closed（NaN deadline 使全部越界比较恒 False 的 VERIFIED 通道
        # 被关闭）。该次读取同时建立**最后可信时钟**（P9-B4：此后任何
        # _read_clock() 早于可信值 → clock_regressed → UNSTABLE_BOUNDARY）。
        self._last_trusted_clock = self._read_clock()
        self._deadline = self._last_trusted_clock + contract.budget.max_duration_seconds
        self._seen_run_ids: set = set()

    # -- 主循环 ----------------------------------------------------------------
    def run(self) -> RepairOutcome:
        # P8-B3 + P9-B4：run 起点时钟与构造期 deadline 同一严格读取通道——
        # 非法/回退时钟 → UNSTABLE_BOUNDARY 终局（final_report=None、零
        # attempt；时间戳取构造期最后可信有限值——绝不产生 NaN/Inf，绝不
        # VERIFIED）。
        try:
            started = self._read_clock()
        except VerificationError as exc:
            trusted = self._last_trusted_clock
            return RepairOutcome(
                stop_reason=RepairStopReason.UNSTABLE_BOUNDARY,
                contract_id=self._contract.contract_id,
                contract_hash=self._contract.content_hash, attempts=(),
                final_report=None, started_at_epoch=trusted,
                finished_at_epoch=trusted,
                diagnostic=f"clock_read_failed:{_safe_exc_diag(exc)[:96]}")
        last_known = started               # P8-B3：最后已知的有限时钟读数
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
            # 4. 审批门（P8-B4）：authority 输出只接受 **builtin str**——只有
            #    精确 "approve" 放行；其他字符串正常拒绝；非字符串/回调异常
            #    静态 fail-closed（诊断只用安全类型名/脱敏 args），**禁止调用
            #    其 __eq__/__bool__/__str__/__repr__**，敌意 RuntimeError 绝不
            #    逃出 repair loop。
            if self._approval_authority is not None:
                try:
                    raw_verdict = self._approval_authority(attempt_id, run_id)
                except Exception as exc:
                    stop = RepairStopReason.APPROVAL_DENIED
                    stop_diag = f"approval_not_granted:authority_error:" \
                                f"{_safe_exc_diag(exc)[:96]}"
                    break
                if type(raw_verdict) is not str:
                    stop = RepairStopReason.APPROVAL_DENIED
                    stop_diag = f"approval_not_granted:non_string:" \
                                f"{_safe_type_name(type(raw_verdict))}"
                    break
                if raw_verdict != "approve":
                    stop = RepairStopReason.APPROVAL_DENIED
                    stop_diag = f"approval_not_granted:{scrub_secrets(raw_verdict)[:64]}"
                    break
                # 审批回调（外部副作用边界）之后再次复核边界。
                reason, diag = self._boundary_violation(pre=True)
                if reason is not None:
                    stop, stop_diag = reason, diag
                    break

            # P8-B3：attempt 起点时钟严格读取——失效 → UNSTABLE_BOUNDARY，
            # final_report=None，不启动任何 collect/下一 attempt。
            try:
                attempt_started = self._read_clock()
                last_known = attempt_started
            except VerificationError as exc:
                stop = RepairStopReason.UNSTABLE_BOUNDARY
                stop_diag = f"attempt_clock_failed:{_safe_exc_diag(exc)[:96]}"
                final_report = None
                break
            diagnostic = ""
            report: Optional[VerificationReport] = None
            signature = ""
            hard = False
            try:
                submission = self._collect(attempt_id, run_id)
                # P10-B3：collect 返回值在调用 get()/解析前封闭为 exact
                # builtin dict（容器子类的 keys/len/iter/getitem 零调用）。
                if type(submission) is not dict:
                    diagnostic = "collect_not_mapping"
                elif submission.get("run_id") != run_id:
                    diagnostic = "run_id_mismatch"
                else:
                    report = self._verify_submission(submission)
            except HardBackendFailure as exc:
                # 硬失败信号：记录该 attempt 后**立即停止**（绝不重试）；
                # P8-B4：诊断面封闭——args 全为 builtin str 才脱敏导出，否则
                # 只记类型名（绝不无条件 str(exc)）。
                hard = True
                diagnostic = f"hard_backend_failure:{_safe_exc_diag(exc)[:128]}"
            except Exception as exc:
                # VerificationInputError（含伪造证据）与其它 collect/verify 异常：
                # 记为该次 attempt 的失败（有界重试；重复签名由断路器拦截）。
                # P8-B4：诊断面封闭（同上——敌意异常 __str__ 零调用）。
                diagnostic = f"collect_or_verify_error:{_safe_type_name(type(exc))}:" \
                             f"{_safe_exc_diag(exc)[:MAX_DIAGNOSTIC_CHARS]}"

            # P8-B3：attempt 完成时钟严格读取——失效时该 attempt 的副作用已经
            # 真实发生：保留记录（完成时间取最后已知有限读数），UNSTABLE_BOUNDARY
            # 停止，绝不启动下一 attempt，绝不产生 NaN 时间戳。
            try:
                attempt_finished = self._read_clock()
                last_known = attempt_finished
            except VerificationError as exc:
                attempts.append(AttemptRecord(
                    attempt_id=attempt_id, run_id=run_id,
                    contract_hash=self._contract.content_hash,
                    verdict="", report_id="",
                    failure_signature=_diag_signature("clock_read_failed_after_attempt"),
                    started_at_epoch=attempt_started, finished_at_epoch=last_known,
                    diagnostic=f"clock_read_failed_after_attempt:"
                               f"{_safe_exc_diag(exc)[:96]}"))
                stop = RepairStopReason.UNSTABLE_BOUNDARY
                stop_diag = "clock_read_failed_after_attempt"
                final_report = None
                break
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
                    # P8-B4：诊断面封闭——自产 VerificationError 携带静态失败
                    # 码（args 全为 builtin str）→ 脱敏导出；外部异常只记
                    # 安全类型名（敌意 __str__ 零调用、零 raw secret 回显）。
                    stop_diag = f"final_boundary_unstable:{_safe_exc_diag(exc)[:128]}"
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
            # 5b. 非 VERIFIED 报告：后置边界复核（attempt 完成后、下一 attempt
            #     前的越界停止——cost/cancel/时钟/契约漂移）。P8-B1：边界结果
            #     **必须消费**——CONTRACT_MUTATED / BUDGET_EXHAUSTED / CANCELLED /
            #     TIMEOUT 立即停止，**优先于** HARD_FAILURE / REPEATED_FAILURE /
            #     ATTEMPTS_EXHAUSTED（绝不依赖"下一轮 pre-check 偶然补抓"）；
            #     boundary stop 时 final_report=None（越界后的报告绝不携带），
            #     已完成 attempt 记录保留。
            reason, diag = self._boundary_violation(pre=False,
                                                    attempt_finished=attempt_finished)
            if reason is not None:
                stop, stop_diag = reason, diag
                final_report = None
                break
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
        # 路径无边界快照：P8-B3 严格时钟读取（失效时取最后已知有限读数——
        # 绝不产生 NaN/Inf 时间戳）。
        if final_now is not None:
            end_time: float = final_now
        else:
            try:
                end_time = self._read_clock()
            except VerificationError:
                end_time = last_known
        return RepairOutcome(
            stop_reason=stop, contract_id=self._contract.contract_id,
            contract_hash=self._contract.content_hash, attempts=tuple(attempts),
            final_report=final_report, started_at_epoch=started,
            finished_at_epoch=end_time, diagnostic=stop_diag)

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
        # P10-B1：seal/standard_hash 复核经类级绑定的权威实现（不可被子类/
        # 实例属性替换）；报告对象必须是 exact VerificationReport（伪造/
        # 旁路报告在身份复核面拒绝）。
        if not self._seal_is_authentic(report):
            reasons.append("seal_not_authentic_for_current_verifier")
        if report.contract_id != self._contract.contract_id:
            reasons.append("contract_id_mismatch")
        if report.run_id != run_id:
            reasons.append("run_id_mismatch")
        if report.contract_hash != self._contract.content_hash:
            reasons.append("contract_hash_mismatch")
        if report.standard_hash != self._verifier_standard_hash:
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
                f"boundary_snapshot_error:{_safe_type_name(type(exc))}") from None
        if type(raw) is not BoundarySnapshot:
            raise VerificationError(
                f"boundary_snapshot_not_boundary_snapshot:"
                f"{_safe_type_name(type(raw))}")
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
        停止；VERIFIED 绝不成为成功结果）。P9-B4：快照 now 早于 repair 最后
        可信时钟（构造期第一次读钟起维护）→ clock_regressed → UNSTABLE_BOUNDARY
        （最终快照时间回退不得产生 VERIFIED）。"""
        if bsnap.contract_hash != self._initial_hash:
            return RepairStopReason.CONTRACT_MUTATED, "contract_hash_changed"
        limit = self._contract.budget.cost_limit.amount
        if bsnap.cost_used is not None and bsnap.cost_used > limit:
            return RepairStopReason.BUDGET_EXHAUSTED, "cost_limit_exceeded"
        if bsnap.cancelled:
            return RepairStopReason.CANCELLED, "cancellation_requested"
        if bsnap.now < self._last_trusted_clock:
            return RepairStopReason.UNSTABLE_BOUNDARY, "clock_regressed"
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
        # P8-B4：cancel_requested 只接受 **builtin bool**——非 bool/回调异常
        # 绝不当作 False（fail-closed UNSTABLE_BOUNDARY），绝不调用其
        # __bool__/__eq__。
        try:
            raw_cancel = self._cancel_requested()
        except Exception as exc:
            return (RepairStopReason.UNSTABLE_BOUNDARY,
                    f"cancel_flag_error:{_safe_exc_diag(exc)[:96]}")
        if type(raw_cancel) is not bool:
            return (RepairStopReason.UNSTABLE_BOUNDARY,
                    f"cancel_flag_invalid_type:{_safe_type_name(type(raw_cancel))}")
        if raw_cancel:
            return RepairStopReason.CANCELLED, "cancellation_requested"
        # P8-B3：时钟读取走单一严格通道——失效 → UNSTABLE_BOUNDARY fail-closed
        # （NaN/Inf/子类时钟使越界比较恒 False 的通道被关闭）。
        if pre:
            try:
                now_value = self._read_clock()
            except VerificationError as exc:
                return (RepairStopReason.UNSTABLE_BOUNDARY,
                        f"clock_read_failed:{_safe_exc_diag(exc)[:96]}")
            if now_value >= self._deadline:
                return RepairStopReason.TIMEOUT, "time_budget_exhausted"
        elif attempt_finished is not None:
            # 全部回调结束后的新鲜时间（cost meter 可能已把时钟推过 deadline）。
            try:
                fresh = self._read_clock()
            except VerificationError as exc:
                return (RepairStopReason.UNSTABLE_BOUNDARY,
                        f"clock_read_failed:{_safe_exc_diag(exc)[:96]}")
            finished = max(float(attempt_finished), fresh)
            if finished > self._deadline:
                return RepairStopReason.TIMEOUT, "time_budget_exhausted"
        return None, ""

    def _read_clock(self) -> float:
        """P8-B3 + P9-B4：**单一严格时钟读取**（所有 repair 时钟面唯一入口）——

        - 仅接受 **builtin int/float**（bool、数值子类、NaN、±Inf、非数值、
          回调异常一律 :class:`VerificationError` fail-closed），返回规范化
          builtin float；
        - **跨读取单调（防回退）**：任何读取早于当前最后可信时间 →
          ``clock_regressed`` fail-closed（回退不得延长预算、不得产生
          VERIFIED——reviewer 实测：构造期 100、后续 0、最终快照 0 仍得
          VERIFIED 的通道被关闭）；成功读取推进最后可信时间。

        构造阶段（deadline）非法/回退时钟 → VerificationError 直接传播；
        run/attempt 阶段由调用方折算 UNSTABLE_BOUNDARY（final_report=None、
        不启动下一 attempt）。"""
        try:
            raw = self._now_fn()
        except Exception as exc:
            raise VerificationError(
                f"clock_read_error:{_safe_type_name(type(exc))}") from None
        if type(raw) not in (int, float):
            raise VerificationError(
                f"clock_invalid_type:{_safe_type_name(type(raw))}")
        value = float(raw)
        if not math.isfinite(value):
            raise VerificationError("clock_not_finite")
        if value < self._last_trusted_clock:
            raise VerificationError("clock_regressed")
        self._last_trusted_clock = value
        return value

    def _read_cost_used(self) -> Tuple[float, str]:
        """严格 cost meter 读取（零误判）：**builtin** int/float（bool/子类
        拒绝——P8-B4）、finite、``>= 0``；meter 异常 / NaN / Inf / 负数一律
        fail-closed——返回 ``(+inf, 诊断)`` → BUDGET_EXHAUSTED，绝不误判为
        可用预算。``float(x)`` 只在精确类型确认后执行（敌意 ``__float__``
        零调用）。"""
        try:
            raw = self._cost_used()
        except Exception as exc:
            return float("inf"), f"cost_meter_error:{_safe_type_name(type(exc))}"
        if type(raw) not in (int, float):
            return float("inf"), f"cost_meter_invalid_type:{_safe_type_name(type(raw))}"
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
                f"run_id_factory 必须返回 str，得到 {_safe_type_name(type(raw))}")
        run_id = validate_identity(raw, "run_id")
        if not run_id or run_id in self._seen_run_ids:
            raise VerificationError(
                f"run_id_factory 必须产出唯一非空 run_id，得到 {run_id!r}")
        self._seen_run_ids.add(run_id)
        return attempt_id, run_id
