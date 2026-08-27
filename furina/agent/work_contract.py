"""Phase 16A — WorkContract 数据契约（FURINA-NATIVE，独立工作域）。

本模块只定义 **不可变、可校验** 的 WorkContract 数据契约与词汇表：

- 定义"什么被授权"（canonical 请求 / objective / commitment scope）、
  "工作可以在哪里发生"（WorkspaceScope）、"什么算成功"（VerificationStandard +
  ArtifactExpectation）以及硬预算（ExecutionBudget）。
- 稳定 ``contract_id`` / ``contract_version`` + 确定性内容摘要（SHA-256 over canonical
  JSON）；同 id 不同内容是 **冲突**，永远不是更新。
- 提供给 backend 的只读序列化 projection：backend 只能读，输出不能反向改约。

边界（Phase 16 锁定）：
- 独立工作域，不属于 C1–C7 cognition stores；无任何数据库 / schema / 持久化行为。
- 不选择 backend、不执行工作、不含 willingness/情绪/关系主观因素。
- ApprovalPolicyRef 只是引用（16D 拥有 grants），不存在全局布尔永久授权开关。

字段锁定来源：docs/phase/Phase_16/01_..._Master_Plan_EXACT.md §7。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Tuple

__all__ = [
    "CONTRACT_SCHEMA_MARKER",
    "HASH_VERSION",
    "MAX_ATTEMPTS",
    "MAX_BUDGET_DURATION_SECONDS",
    "MAX_COST_AMOUNT",
    "ArtifactExpectation",
    "ApprovalPolicyRef",
    "ContractIdConflictError",
    "CostBudget",
    "ExecutionBudget",
    "VERIFICATION_CRITERION_KINDS",
    "VerificationCriterion",
    "VerificationStandard",
    "WorkContract",
    "WorkContractValidationError",
    "compute_content_hash",
    "ensure_no_conflict",
]

# ---------------------------------------------------------------------------
# 常量 / 词汇表
# ---------------------------------------------------------------------------

#: 序列化 envelope 标记；也用于识别本契约的持久化语义（仅 dict 往返，无隐藏存储）。
CONTRACT_SCHEMA_MARKER = "phase16.work_contract.v1"

#: 内容摘要算法版本；payload 变更语义时必须 bump。
HASH_VERSION = 1

_HASH_ALGORITHM = "sha256"

#: 硬预算 sanity 上限——防御"事实上无界"的预算值。
MAX_BUDGET_DURATION_SECONDS = 86400 * 365  # 1 年；更大的"预算"视为无界
MAX_COST_AMOUNT = 1_000_000_000.0
MAX_ATTEMPTS = 99

contract_id_PATTERN = re.compile(r"^wc_[0-9a-zA-Z][0-9a-zA-Z._:-]{2,63}$")
contract_version_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
source_event_id_PATTERN = re.compile(r"^lev_\d{10,17}_[0-9a-f]{4,32}$")
verifier_ref_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.]{2,119}$")
capability_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:\-/]{1,119}$")

#: ApprovalPolicyRef 允许的策略种类（白名单；16D 拥有实际 grants 与审批运行时）。
APPROVAL_POLICY_KINDS = (
    "approval_required_each_step",
    "approval_required_on_risk_level",
    "pre_approved_scoped",
)

#: VerificationCriterion 允许的机器可查判据种类 → 必需参数键。
VERIFICATION_CRITERION_KINDS: Dict[str, Tuple[str, ...]] = {
    "process_exit_zero": ("command",),
    "artifact_file_exists": ("path",),
    "artifact_sha256": ("path", "sha256_hex"),
    "text_contains": ("path", "needle"),
    "regex_matches": ("path", "pattern"),
}

_WILLINGNESS_TOKENS = (
    "willingness",
    "emotion",
    "intimacy",
    "relationship",
    "affection",
    "mood",
    "personality_pref",
)
_FORBIDDEN_BOOL_FIELDS = ("grant_permanent", "permanent", "always_allow", "approved_forever")


class WorkContractValidationError(ValueError):
    """契约字段非法。所有 __post_init__ 校验失败都抛本类型。"""


class ContractIdConflictError(ValueError):
    """同一 contract_id + 不同不可变内容的冲突——重试不允许静默改约。"""


def _fail(msg: str) -> None:
    raise WorkContractValidationError(msg)


def _clean_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        _fail(f"{field_name} 必须是 str，得到 {type(value).__name__}")
    v = value.strip()
    if not v:
        _fail(f"{field_name} 不能为空")
    return v


def compute_content_hash(payload: Mapping[str, Any]) -> str:
    """确定性内容摘要：SHA-256 over canonical JSON（sorted keys、紧凑分隔符、ASCII）。

    对相同逻辑内容跨进程 / 跨平台稳定；不涉及任何运行时状态。
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_json_default
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_default(obj: Any) -> Any:
    return obj


# ---------------------------------------------------------------------------
# 子结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostBudget:
    """成本上限（amount > 0 且有限；币种显式声明）。"""

    amount: float
    currency: str = "CNY"

    def to_dict(self) -> Dict[str, Any]:
        return {"amount": self.amount, "currency": self.currency}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "CostBudget":
        return cls(amount=float(d["amount"]), currency=str(d.get("currency", "CNY")))


@dataclass(frozen=True)
class WorkspaceScope:
    """显式工作区边界：允许读取的根目录 + 允许写入的根目录。

    - 根必须是绝对路径，规范化后不得是文件系统根 / 盘根 / 用户主目录本身（过宽拒绝）；
    - 集合内重复（大小写不敏感规范化后）拒绝；读集合可以为空（只写场景不存在，
      写前必读由执行层负责，但契约层面 write_roots 可独立成立）。
    """

    read_roots: Tuple[str, ...] = ()
    write_roots: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("read_roots", "write_roots"):
            raw = getattr(self, name)
            if not isinstance(raw, (tuple, list)):
                _fail(f"workspace_scope.{name} 必须是序列")
            normalized = tuple(self._normalize_root(r, f"workspace_scope.{name}") for r in raw)
            object.__setattr__(self, name, normalized)
            seen = set()
            for r in normalized:
                key = os.path.normcase(r)
                if key in seen:
                    _fail(f"workspace_scope.{name} 存在重复根: {r}")
                seen.add(key)

    @staticmethod
    def _normalize_root(root: Any, field_name: str) -> str:
        if not isinstance(root, str):
            _fail(f"{field_name} 根必须是 str")
        s = root.strip()
        if not s or s == ".":
            # 必须在 abspath 之前拦截："" 会被解析为进程 CWD，等同隐式边界
            _fail(f"{field_name} 拒绝空根路径或相对当前目录根")
        r = os.path.normpath(os.path.abspath(os.path.expanduser(s)))
        if os.path.dirname(r) == r:
            # "/"、"C:\\" 等：文件系统根或盘根本身 = 过宽边界
            _fail(f"{field_name} 拒绝过宽根（文件系统/盘根）: {r}")
        if os.path.normcase(r) == os.path.normcase(os.path.expanduser("~")):
            _fail(f"{field_name} 拒绝过宽根（用户主目录整体）: {r}")
        return r

    def contains_path(self, path: str, *, writable: bool = False) -> bool:
        """path 是否落在（可选：write）范围内。"""
        p = os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(path))))
        roots = self.write_roots if writable else self.read_roots + self.write_roots
        for root in roots:
            rc = os.path.normcase(root)
            if p == rc or p.startswith(rc + os.sep):
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {"read_roots": list(self.read_roots), "write_roots": list(self.write_roots)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "WorkspaceScope":
        return cls(read_roots=tuple(d.get("read_roots", ())), write_roots=tuple(d.get("write_roots", ())))


@dataclass(frozen=True)
class ExecutionBudget:
    """时间 / 成本 / 尝试次数硬预算——三项全部必填且有界（拒绝负数与无界值）。"""

    max_duration_seconds: float
    cost_limit: CostBudget
    max_attempts: int

    def __post_init__(self) -> None:
        dur = self.max_duration_seconds
        if isinstance(dur, bool) or not isinstance(dur, (int, float)):
            _fail("budget.max_duration_seconds 必须是数值")
        dur = float(dur)
        if math.isnan(dur) or math.isinf(dur):
            _fail("budget.max_duration_seconds 不允许 NaN/Inf（无界预算）")
        if dur <= 0:
            _fail(f"budget.max_duration_seconds 必须 > 0，得到 {dur}")
        if dur > MAX_BUDGET_DURATION_SECONDS:
            _fail(f"budget.max_duration_seconds 超过事实无界上限 {MAX_BUDGET_DURATION_SECONDS}")
        object.__setattr__(self, "max_duration_seconds", dur)

        cost = self.cost_limit
        if not isinstance(cost, CostBudget):
            _fail("budget.cost_limit 必须是 CostBudget")
        if math.isnan(cost.amount) or math.isinf(cost.amount):
            _fail("budget.cost_limit.amount 不允许 NaN/Inf（无界预算）")
        if cost.amount <= 0 or cost.amount > MAX_COST_AMOUNT:
            _fail(f"budget.cost_limit.amount 必须在 (0, {MAX_COST_AMOUNT}] 内，得到 {cost.amount}")

        attempts = self.max_attempts
        if isinstance(attempts, bool) or not isinstance(attempts, int):
            _fail("budget.max_attempts 必须是 int")
        if attempts < 1 or attempts > MAX_ATTEMPTS:
            _fail(f"budget.max_attempts 必须在 [1, {MAX_ATTEMPTS}] 内，得到 {attempts}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_duration_seconds": self.max_duration_seconds,
            "cost_limit": self.cost_limit.to_dict(),
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ExecutionBudget":
        return cls(
            max_duration_seconds=float(d["max_duration_seconds"]),
            cost_limit=CostBudget.from_dict(d["cost_limit"]),
            max_attempts=int(d["max_attempts"]),
        )


@dataclass(frozen=True)
class ArtifactExpectation:
    """预期产物：稳定 artifact 身份 + 归属路径 + 是否必需。

    同一契约内 artifact_id 或 expected_path 重复都视为重复身份（契约层校验）。
    """

    artifact_id: str
    artifact_type: str
    expected_path: str
    required: bool = True

    def __post_init__(self) -> None:
        aid = _clean_str(self.artifact_id, "artifact.artifact_id")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.\-]{2,63}", aid):
            _fail(f"artifact.artifact_id 格式非法: {aid!r}")
        object.__setattr__(self, "artifact_id", aid)
        atype = _clean_str(self.artifact_type, "artifact.artifact_type")
        object.__setattr__(self, "artifact_type", atype)
        path = _clean_str(self.expected_path, "artifact.expected_path")
        object.__setattr__(self, "expected_path", os.path.normpath(os.path.abspath(os.path.expanduser(path))))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "expected_path": self.expected_path,
            "required": bool(self.required),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ArtifactExpectation":
        return cls(
            artifact_id=str(d["artifact_id"]),
            artifact_type=str(d["artifact_type"]),
            expected_path=str(d["expected_path"]),
            required=bool(d.get("required", True)),
        )


@dataclass(frozen=True)
class VerificationCriterion:
    """单条机器可查验收判据（kind 白名单 + 固定必需参数键，杜绝自由散文标准）。"""

    criterion_id: str
    kind: str
    params: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        cid = _clean_str(self.criterion_id, "criterion.criterion_id")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.\-]{2,63}", cid):
            _fail(f"criterion.criterion_id 格式非法: {cid!r}")
        object.__setattr__(self, "criterion_id", cid)

        if self.kind not in VERIFICATION_CRITERION_KINDS:
            _fail(
                f"criterion.kind '{self.kind}' 不在机器可查白名单 "
                f"{sorted(VERIFICATION_CRITERION_KINDS)} 内——不可校验的成功标准被拒绝"
            )
        param_map = dict(self.params)
        if set(param_map) != set(VERIFICATION_CRITERION_KINDS[self.kind]):
            _fail(
                f"criterion '{cid}' (kind={self.kind}) 参数键必须恰为 "
                f"{list(VERIFICATION_CRITERION_KINDS[self.kind])}"
            )
        normalized = tuple(sorted((k, str(v).strip()) for k, v in param_map.items()))
        for k, v in normalized:
            if not v:
                _fail(f"criterion '{cid}' 参数 {k} 不能为空")
        object.__setattr__(self, "params", normalized)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "kind": self.kind,
            "params": {k: v for k, v in self.params},
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "VerificationCriterion":
        return cls(
            criterion_id=str(d["criterion_id"]),
            kind=str(d["kind"]),
            params=tuple(dict(d.get("params", {})).items()),
        )


@dataclass(frozen=True)
class VerificationStandard:
    """验收标准：≥1 条机器可查判据 和/或 类型化 verifier 引用（16F 消费；backend 无权宣告满足）。"""

    criteria: Tuple[VerificationCriterion, ...] = ()
    verifier_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for c in self.criteria:
            if not isinstance(c, VerificationCriterion):
                _fail("verification.criteria 元素必须是 VerificationCriterion")
        refs = []
        for ref in self.verifier_refs:
            ref_s = _clean_str(ref, "verification.verifier_refs")
            if not verifier_ref_PATTERN.match(ref_s):
                _fail(f"verification.verifier_refs 引用格式非法: {ref_s!r}")
            refs.append(ref_s)
        object.__setattr__(self, "verifier_refs", tuple(refs))
        cids = [c.criterion_id for c in self.criteria]
        if len(cids) != len(set(cids)):
            dup = sorted({x for x in cids if cids.count(x) > 1})
            _fail(f"verification.criteria 存在重复 criterion_id: {dup}")
        if not self.criteria and not self.verifier_refs:
            _fail("verification_standard 为空：至少需要一条机器可查判据或类型化 verifier 引用")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "criteria": [c.to_dict() for c in self.criteria],
            "verifier_refs": list(self.verifier_refs),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "VerificationStandard":
        return cls(
            criteria=tuple(VerificationCriterion.from_dict(x) for x in d.get("criteria", ())),
            verifier_refs=tuple(d.get("verifier_refs", ())),
        )


@dataclass(frozen=True)
class ApprovalPolicyRef:
    """对 16D 授权策略/授权记录的 **引用**。不是授权本身；禁止任何全局布尔永久开关。"""

    policy_id: str
    policy_kind: str
    scope_note: str = ""
    #: 指向 16D 产生的具体 AuthorizationGrant 记录的 provenance 指针（可为空）。
    grant_record_ref: str = ""

    def __post_init__(self) -> None:
        pid = _clean_str(self.policy_id, "approval_policy.policy_id")
        object.__setattr__(self, "policy_id", pid)
        kind = _clean_str(self.policy_kind, "approval_policy.policy_kind")
        lowered = kind.lower()
        if any(tok in lowered for tok in ("always", "permanent", "forever")):
            _fail(f"approval_policy.policy_kind 禁止永久/always 语义: {kind}")
        if kind not in APPROVAL_POLICY_KINDS:
            _fail(f"approval_policy.policy_kind 不在白名单 {list(APPROVAL_POLICY_KINDS)} 内: {kind}")
        object.__setattr__(self, "policy_kind", kind)
        for fname in ("scope_note", "grant_record_ref"):
            v = getattr(self, fname)
            if not isinstance(v, str):
                _fail(f"approval_policy.{fname} 必须是 str")
            object.__setattr__(self, fname, v.strip())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_kind": self.policy_kind,
            "scope_note": self.scope_note,
            "grant_record_ref": self.grant_record_ref,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ApprovalPolicyRef":
        return cls(
            policy_id=str(d["policy_id"]),
            policy_kind=str(d["policy_kind"]),
            scope_note=str(d.get("scope_note", "")),
            grant_record_ref=str(d.get("grant_record_ref", "")),
        )


# ---------------------------------------------------------------------------
# WorkContract 本体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkContract:
    """不可变工作契约（独立工作域对象；不属于 C1–C7，也无任何隐藏持久化）。

    - ``contract_id``：调用方提供的稳定幂等键（``wc_*``），不由 backend 改写；
    - ``content_hash``：对全部承诺性内容（含 version）的 SHA-256 canonical 摘要，
      排除运行时状态（created_at）；同 id + 不同 hash = 冲突；
    - 结构不可变（frozen）且嵌套均为 frozen/tuple。
    """

    contract_id: str
    contract_version: str
    canonical_user_request: str
    objective: str
    commitment_scope_included: Tuple[str, ...]
    workspace_scope: WorkspaceScope
    budget: ExecutionBudget
    verification_standard: VerificationStandard
    approval_policy: ApprovalPolicyRef
    source_event_id: str
    allowed_capabilities: Tuple[str, ...] = ()
    allowed_backends: Tuple[str, ...] = ()
    commitment_scope_excluded: Tuple[str, ...] = ()
    artifact_expectations: Tuple[ArtifactExpectation, ...] = ()
    #: 构造时刻 epoch 秒（运行时状态；**不计入** content_hash）。
    created_at_epoch: float = field(default_factory=time.time)
    content_hash: str = ""  # 由 __post_init__ 计算/校验

    # -- 构造与校验 ---------------------------------------------------------

    def __post_init__(self) -> None:
        cid = _clean_str(self.contract_id, "contract_id")
        if not contract_id_PATTERN.match(cid):
            _fail(f"contract_id 必须匹配 ^wc_[alnum]._:-{{3..}} 形如 'wc_xxx'，得到 {cid!r}")
        object.__setattr__(self, "contract_id", cid)

        ver = _clean_str(self.contract_version, "contract_version")
        if not contract_version_PATTERN.match(ver):
            _fail(f"contract_version 必须是 semver 三段式（如 '1.0.0'），得到 {ver!r}")
        object.__setattr__(self, "contract_version", ver)

        request = _clean_str(self.canonical_user_request, "canonical_user_request")
        object.__setattr__(self, "canonical_user_request", request)
        objective = _clean_str(self.objective, "objective")
        object.__setattr__(self, "objective", objective)

        incl = self._string_tuple(self.commitment_scope_included, "commitment_scope_included")
        if not incl:
            _fail("commitment_scope_included 不能为空：必须显式声明包含项")
        excl = self._string_tuple(self.commitment_scope_excluded, "commitment_scope_excluded")
        overlap = set(incl) & set(excl)
        if overlap:
            _fail(f"commitment_scope 包含/排除项重叠: {sorted(overlap)}")
        object.__setattr__(self, "commitment_scope_included", incl)
        object.__setattr__(self, "commitment_scope_excluded", excl)

        caps = self._token_tuple(self.allowed_capabilities, "allowed_capabilities")
        if not caps:
            _fail("allowed_capabilities 不能为空：工作域要求显式能力集合")
        backends = self._token_tuple(self.allowed_backends, "allowed_backends")
        if not backends:
            _fail("allowed_backends 不能为空：技术路由不得越过用户允许的 backend 集合")
        object.__setattr__(self, "allowed_capabilities", caps)
        object.__setattr__(self, "allowed_backends", backends)

        source_event = _clean_str(self.source_event_id, "source_event_id")
        if not source_event_id_PATTERN.match(source_event):
            _fail(
                f"source_event_id 必须是 canonical C6 USER 事件 id（lev_<ms>_<hex>），得到 {source_event!r}"
            )
        object.__setattr__(self, "source_event_id", source_event)

        if not isinstance(self.workspace_scope, WorkspaceScope):
            object.__setattr__(
                self, "workspace_scope", WorkspaceScope.from_dict(self.workspace_scope)
            )
        if not isinstance(self.budget, ExecutionBudget):
            object.__setattr__(self, "budget", ExecutionBudget.from_dict(self.budget))
        if not isinstance(self.verification_standard, VerificationStandard):
            object.__setattr__(
                self, "verification_standard", VerificationStandard.from_dict(self.verification_standard)
            )
        if not isinstance(self.approval_policy, ApprovalPolicyRef):
            object.__setattr__(self, "approval_policy", ApprovalPolicyRef.from_dict(self.approval_policy))

        arts = []
        for a in self.artifact_expectations:
            if not isinstance(a, ArtifactExpectation):
                a = ArtifactExpectation.from_dict(a)
            arts.append(a)
        arts_t = tuple(arts)
        aids = [a.artifact_id for a in arts_t]
        paths = [os.path.normcase(a.expected_path) for a in arts_t]
        if len(aids) != len(set(aids)):
            dup = sorted({x for x in aids if aids.count(x) > 1})
            _fail(f"artifact_expectations 存在重复 artifact_id: {dup}")
        if len(paths) != len(set(paths)):
            dup = sorted({x for x in paths if paths.count(x) > 1})
            _fail(f"artifact_expectations 存在重复 expected_path: {dup}")
        for a in arts_t:
            if not self.workspace_scope.contains_path(a.expected_path, writable=True):
                _fail(
                    f"artifact '{a.artifact_id}' 的 expected_path 不在任何 write root 内: {a.expected_path}"
                )
        object.__setattr__(self, "artifact_expectations", arts_t)

        computed = compute_content_hash(self._hash_payload())
        if self.content_hash and self.content_hash != computed:
            raise WorkContractValidationError(
                f"content_hash 与内容不符（传入 {self.content_hash[:12]}…, 实算 {computed[:12]}…）："
                "拒绝篡改载荷"
            )
        object.__setattr__(self, "content_hash", computed)

    @staticmethod
    def _string_tuple(values: Any, field_name: str) -> Tuple[str, ...]:
        if not isinstance(values, (tuple, list)):
            _fail(f"{field_name} 必须是序列")
        out = []
        for v in values:
            s = _clean_str(v, f"{field_name} 条目")
            out.append(s)
        if len(out) != len(set(out)):
            _fail(f"{field_name} 存在重复条目")
        return tuple(out)

    @staticmethod
    def _token_tuple(values: Any, field_name: str) -> Tuple[str, ...]:
        out = []
        for v in values:
            s = _clean_str(v, f"{field_name} 条目")
            if not capability_PATTERN.match(s):
                _fail(f"{field_name} 条目格式非法（期望小写命名空间 token）: {s!r}")
            out.append(s)
        if len(out) != len(set(out)):
            _fail(f"{field_name} 存在重复条目")
        return tuple(sorted(out))

    # -- 内容摘要 -----------------------------------------------------------

    def _hash_payload_fields(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "canonical_user_request": self.canonical_user_request,
            "objective": self.objective,
            "commitment_scope_included": list(self.commitment_scope_included),
            "commitment_scope_excluded": list(self.commitment_scope_excluded),
            "allowed_capabilities": list(self.allowed_capabilities),
            "allowed_backends": list(self.allowed_backends),
            "workspace_scope": self.workspace_scope.to_dict(),
            "budget": self.budget.to_dict(),
            "artifact_expectations": [a.to_dict() for a in self.artifact_expectations],
            "verification_standard": self.verification_standard.to_dict(),
            "approval_policy": self.approval_policy.to_dict(),
            "source_event_id": self.source_event_id,
        }

    def _hash_payload(self) -> Dict[str, Any]:
        return {"hash_version": HASH_VERSION, "algorithm": _HASH_ALGORITHM, "fields": self._hash_payload_fields()}

    # -- 冲突语义 -----------------------------------------------------------

    def conflicts_with(self, other: "WorkContract") -> bool:
        """同 contract_id + 不同内容 = 冲突（True）；不同 id 永不冲突；完全一致 = 幂等重放。"""
        return self.contract_id == other.contract_id and self.content_hash != other.content_hash

    # -- 序列化（唯一持久化语义：纯 dict 往返，无隐藏存储） -----------------

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {f: getattr(self, f) for f in self.__dataclass_fields__}
        d["schema_marker"] = CONTRACT_SCHEMA_MARKER
        d["workspace_scope"] = self.workspace_scope.to_dict()
        d["budget"] = self.budget.to_dict()
        d["verification_standard"] = self.verification_standard.to_dict()
        d["approval_policy"] = self.approval_policy.to_dict()
        d["commitment_scope_included"] = list(self.commitment_scope_included)
        d["commitment_scope_excluded"] = list(self.commitment_scope_excluded)
        d["allowed_capabilities"] = list(self.allowed_capabilities)
        d["allowed_backends"] = list(self.allowed_backends)
        d["artifact_expectations"] = [a.to_dict() for a in self.artifact_expectations]
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "WorkContract":
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in dict(d).items() if k in known}
        try:
            rebuilt = cls(**kwargs)
        except TypeError as exc:  # 缺少必填键等
            raise WorkContractValidationError(f"from_dict 失败：{exc}") from exc
        provided_hash = dict(d).get("content_hash", "")
        if provided_hash and provided_hash != rebuilt.content_hash:
            raise WorkContractValidationError("from_dict：反序列化后内容摘要不一致（载荷被篡改或跨版本）")
        return rebuilt

    # -- backend 只读 projection ----------------------------------------------

    def to_backend_projection(self) -> Mapping[str, Any]:
        """深度只读投影：backend 输入只能读；任何原地修改尝试都会失败，
        且即便调用方自行复制修改也不会影响 canonical 契约与内容摘要。"""
        return _freeze_tree(self.to_dict())

    def describe_hash_algorithm(self) -> str:
        return (
            f"{_HASH_ALGORITHM}:{HASH_VERSION}:"
            "json(sort_keys=true,separators=',:',ensure_ascii=true) over fields payload"
        )


def _freeze_tree(obj: Any) -> Any:
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze_tree(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_freeze_tree(v) for v in obj)
    return obj


def ensure_no_conflict(existing: WorkContract, incoming: WorkContract) -> None:
    """幂等重放放行；同 id 改约直接抛 :class:`ContractIdConflictError`。"""
    if existing.contract_id == incoming.contract_id and existing.content_hash == incoming.content_hash:
        return
    if incoming.conflicts_with(existing):
        raise ContractIdConflictError(
            f"contract_id '{incoming.contract_id}' 已存在不同不可变内容 "
            f"(old={existing.content_hash[:12]}… new={incoming.content_hash[:12]}…)：冲突而非更新"
        )
