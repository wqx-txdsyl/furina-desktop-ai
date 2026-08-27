"""Phase 16D — Permission & Approval Boundary 数据模型（typed approval channel）。

位置（任务书 §1/§4）：位于既有同步 L0–L3 PermissionManager **之上**的一等异步审批
通道。effective permission = WorkContract scope ∩ PermissionManager L0–L3 ∩
explicit approval decision/grant ∩ backend capability；**任何一层都不得放宽另一层**。

本模块只定义数据模型与类型化错误：
- :class:`ApprovalRequest`：approval_id / contract_id / run_id / tool / capability /
  redacted args summary / requested scope / reason / risk level / created+expires /
  provenance；
- :class:`ApprovalDecisionKind`：approve_once / approve_session / deny / timeout /
  revoked（+ :class:`ResolutionStatus` 返回 duplicate / conflict / late / unknown）；
- :class:`AuthorizationGrant`：会话/持久授权——强制 canonical USER provenance
  （``lev_<ms>_<hex>`` 事件 id）、精确 capability / 规范化 tool pattern、workspace
  必须声明至少一个根、expiry 有限（**无永久 grant**）、可撤销；
- :class:`ApprovalEvent`：redacted 域事件（broker 日志 / 外部 emit 均只含脱敏载荷）；
- :func:`redact_args`：参数/秘密进入事件与日志前必须 redaction。

状态机与 owner 线程边界在 broker.py；四层交集判定在 gate.py。

边界（任务书 §6）：不替换/削弱 PermissionManager；无 UI/Hermes/verifier/C7 写入；
无 C1–C7 schema / DB 迁移；无任何持久化行为。
"""
from __future__ import annotations

import enum
import fnmatch
import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from furina.agent.permission import Permission
from furina.agent.work_contract import APPROVAL_POLICY_KINDS, WorkspaceScope
from furina.core import FurinaError

__all__ = [
    "APPROVAL_EVENT_TYPES",
    "USER_EVENT_ID_PATTERN",
    "ApprovalDecisionKind",
    "ApprovalEvent",
    "ApprovalRequest",
    "ApprovalResolution",
    "ApprovalState",
    "ApprovalStateError",
    "AuthorizationGrant",
    "ResolutionStatus",
    "redact_args",
]


class ApprovalStateError(FurinaError):
    """审批域类型化错误（非法字段 / 非 owner 变更 / 未知 id / 非法决议）。"""


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class ApprovalState(str, enum.Enum):
    """请求生命周期：PENDING → 终态（终态不可逆）。

    - APPROVED_ONCE：一次性批准（gate 消费一次后失效）；
    - APPROVED_SESSION：会话批准（多次放行，可 revoke）；
    - DENIED / TIMED_OUT / REVOKED / CANCELLED：拒绝类终态。
    """

    PENDING = "pending"
    APPROVED_ONCE = "approved_once"
    APPROVED_SESSION = "approved_session"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    REVOKED = "revoked"
    CANCELLED = "cancelled"


class ApprovalDecisionKind(str, enum.Enum):
    """用户/系统可产生的决议种类（任务书 §3）。"""

    APPROVE_ONCE = "approve_once"
    APPROVE_SESSION = "approve_session"
    DENY = "deny"
    TIMEOUT = "timeout"
    REVOKED = "revoked"

    def to_state(self) -> ApprovalState:
        return {
            ApprovalDecisionKind.APPROVE_ONCE: ApprovalState.APPROVED_ONCE,
            ApprovalDecisionKind.APPROVE_SESSION: ApprovalState.APPROVED_SESSION,
            ApprovalDecisionKind.DENY: ApprovalState.DENIED,
            ApprovalDecisionKind.TIMEOUT: ApprovalState.TIMED_OUT,
            ApprovalDecisionKind.REVOKED: ApprovalState.REVOKED,
        }[self]


class ResolutionStatus(str, enum.Enum):
    """resolve 返回的类型化结果：

    - RESOLVED：首次决议生效；
    - DUPLICATE：相同决议重复 → 幂等 no-op（ok=True，不重复消费）；
    - CONFLICT：与既有**用户决议**冲突 → 类型化拒绝（ok=False）；
    - LATE：决议迟于 timeout/cancel → 类型化拒绝（ok=False）；
    - UNKNOWN：approval_id 不存在（ok=False）。
    """

    RESOLVED = "resolved"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    LATE = "late"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# 词法与 provenance
# ---------------------------------------------------------------------------
_APPROVAL_ID_PATTERN = re.compile(r"^apv_[0-9a-f]{8,32}$")
_GRANT_ID_PATTERN = re.compile(r"^gr_[0-9a-f]{8,32}$")

#: canonical C6 USER 事件 id（与 WorkContract.source_event_id 同形）：USER provenance
#: 的唯一机器可验证来源。backend 文本 / adapter 默认 / 推断意图 / LLM 输出一律无法匹配。
USER_EVENT_ID_PATTERN = re.compile(r"^lev_\d{10,17}_[0-9a-f]{4,32}$")

_CAP_TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:\-/]{1,119}$")
_TOOL_PATTERN_PATTERN = re.compile(r"^[a-zA-Z0-9_.:*\-]{1,120}$")


# ---------------------------------------------------------------------------
# redaction（参数/秘密进入事件与日志前必须脱敏）
# ---------------------------------------------------------------------------
_REDACTED = "[REDACTED]"
_MAX_STR_LEN = 500

#: 敏感键名 token（键名小写后任一 token 出现即整值脱敏；宁可多脱敏不可泄漏）。
_SENSITIVE_KEY_TOKENS = (
    "password", "passwd", "token", "secret", "api", "authorization", "credential",
    "private", "pin", "otp", "cookie", "session",
)
#: 秘密值形态（整体像凭据的字符串）：authorization/token/password/secret 头或 k=v。
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(bearer\s+\S+|authorization\s*[:=]\s*\S+|password\s*[:=]\s*\S+|"
    r"token\s*[:=]\s*\S+|secret\s*[:=]\s*\S+|api[_-]?key\s*[:=]\s*\S+)"
)


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_STR_LEN:
        return value[:_MAX_STR_LEN] + "...[truncated]"
    return value


def redact_args(args: Any) -> Any:
    """递归 redaction：敏感键名 / 秘密值 / 超长值 → [REDACTED]；返回全新对象，绝不修改入参。"""
    if isinstance(args, Mapping):
        out: Dict[Any, Any] = {}
        for k, v in args.items():
            key = str(k).lower()
            if any(tok in key for tok in _SENSITIVE_KEY_TOKENS):
                out[k] = _REDACTED
            elif isinstance(v, str) and _SECRET_VALUE_PATTERN.search(v):
                out[k] = _REDACTED
            else:
                out[k] = redact_args(v)
        return out
    if isinstance(args, (list, tuple)):
        return type(args)(redact_args(v) for v in args)
    return _truncate(args)


# ---------------------------------------------------------------------------
# ApprovalRequest
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ApprovalRequest:
    """一次异步审批请求（不可变；只存 redacted 参数摘要，原始参数不进入审批域）。"""

    approval_id: str
    contract_id: str
    run_id: str
    tool: str
    capability: str
    #: normalized/redacted 参数摘要（由 broker 在 create 时 redact，永不存原始参数）。
    args_redacted: Mapping[str, Any]
    #: 请求作用的规范化路径集合（requested scope）。
    requested_scope: Tuple[str, ...]
    reason: str
    risk_level: Permission
    created_at: float
    expires_at: float
    policy_kind: str
    provenance: str

    def __post_init__(self) -> None:
        aid = self.approval_id
        if not isinstance(aid, str) or not _APPROVAL_ID_PATTERN.match(aid):
            raise ApprovalStateError(f"approval_id 必须匹配 apv_<hex>，得到 {aid!r}")
        object.__setattr__(self, "approval_id", aid)
        for fname in ("contract_id", "run_id", "tool", "capability",
                      "policy_kind", "provenance"):
            v = getattr(self, fname)
            if not isinstance(v, str) or not v.strip():
                raise ApprovalStateError(f"ApprovalRequest.{fname} 必须是非空 str，得到 {v!r}")
            object.__setattr__(self, fname, v.strip())
        if not isinstance(self.reason, str):   # reason 允许为空（可选说明），但必须 str
            raise ApprovalStateError(f"ApprovalRequest.reason 必须是 str，得到 {type(self.reason).__name__}")
        object.__setattr__(self, "reason", self.reason.strip())
        if self.policy_kind not in APPROVAL_POLICY_KINDS:
            raise ApprovalStateError(
                f"policy_kind 必须 ∈ {list(APPROVAL_POLICY_KINDS)}，得到 {self.policy_kind!r}")
        if not isinstance(self.risk_level, Permission):
            raise ApprovalStateError(
                f"risk_level 必须是 Permission（int enum），得到 {type(self.risk_level).__name__}")
        for fname in ("created_at", "expires_at"):
            v = getattr(self, fname)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ApprovalStateError(f"ApprovalRequest.{fname} 必须是非 bool 数值，得到 {v!r}")
            if not math.isfinite(float(v)):
                raise ApprovalStateError(f"ApprovalRequest.{fname} 必须有限（NaN/Inf 拒绝）")
            object.__setattr__(self, fname, float(v))
        if self.created_at > self.expires_at:
            raise ApprovalStateError(
                f"ApprovalRequest 时序非法：created_at {self.created_at} > expires_at {self.expires_at}")
        if not isinstance(self.args_redacted, Mapping):
            raise ApprovalStateError("args_redacted 必须是 Mapping（redacted summary）")
        object.__setattr__(self, "args_redacted", MappingProxyType(dict(self.args_redacted)))
        scope = []
        for p in self.requested_scope:
            if not isinstance(p, str) or not p.strip():
                raise ApprovalStateError("requested_scope 条目必须是非空 str")
            scope.append(p.strip())
        object.__setattr__(self, "requested_scope", tuple(scope))

    def to_audit_dict(self) -> Dict[str, Any]:
        """用户可见/审计 payload：只含 redacted 字段（args 已脱敏，值永不泄漏）。"""
        return {
            "approval_id": self.approval_id,
            "contract_id": self.contract_id,
            "run_id": self.run_id,
            "tool": self.tool,
            "capability": self.capability,
            "args_redacted": dict(self.args_redacted),
            "requested_scope": list(self.requested_scope),
            "reason": self.reason,
            "risk_level": self.risk_level.name,
            "policy_kind": self.policy_kind,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "provenance": self.provenance,
        }


# ---------------------------------------------------------------------------
# ApprovalResolution / ApprovalEvent
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ApprovalResolution:
    """resolve/wait_for_resolution/cancel 的类型化结果（ok=True 仅表示该次决议被接受/生效）。"""

    ok: bool
    status: ResolutionStatus
    approval_id: str
    decision: Optional[ApprovalDecisionKind] = None
    decided_at: float = 0.0
    detail: str = ""


#: broker 产生的域事件类型（均只携带 redacted payload）。
APPROVAL_EVENT_TYPES = (
    "approval.requested",
    "approval.decided",
    "approval.timed_out",
    "approval.cancelled",
    "approval.grant_created",
    "approval.grant_revoked",
)


@dataclass(frozen=True)
class ApprovalEvent:
    """redacted 域事件（broker.events 日志 / 外部 emit 的统一载荷）。"""

    etype: str
    approval_id: str = ""
    grant_id: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# AuthorizationGrant（会话/持久授权）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthorizationGrant:
    """会话授权记录：强制 canonical USER provenance + 有界 scope + 可撤销。

    - ``user_event_id`` 必须是 canonical C6 USER 事件 id（``lev_<ms>_<hex>``）——
      backend 文本 / adapter 默认 / 推断意图 / LLM 输出一律不可能伪造；
    - ``capability`` 精确绑定；``tool_pattern`` 精确名或仅安全字符集的 glob；
    - ``workspace_scope`` 必须有至少一个根（无界 grant 拒绝）；
    - ``expiry`` 有限且 ≥ issued_at（**无永久 grant**）；``revoked_at`` 由 broker 记录。
    """

    grant_id: str
    user_event_id: str
    capability: str
    tool_pattern: str
    workspace_scope: WorkspaceScope
    issued_at: float
    expiry: float
    scope_note: str = ""

    def __post_init__(self) -> None:
        gid = self.grant_id
        if not isinstance(gid, str) or not _GRANT_ID_PATTERN.match(gid):
            raise ApprovalStateError(f"grant_id 必须匹配 gr_<hex>，得到 {gid!r}")
        object.__setattr__(self, "grant_id", gid)
        ue = self.user_event_id
        if not isinstance(ue, str) or not USER_EVENT_ID_PATTERN.match(ue):
            raise ApprovalStateError(
                f"grant 必须携带 canonical USER 事件 id（lev_<ms>_<hex>），得到 {ue!r}："
                "backend/LLM 无权创建授权")
        object.__setattr__(self, "user_event_id", ue)
        cap = self.capability
        if not isinstance(cap, str) or not _CAP_TOKEN_PATTERN.match(cap):
            raise ApprovalStateError(f"grant.capability 词法非法: {cap!r}")
        object.__setattr__(self, "capability", cap)
        tp = self.tool_pattern
        if not isinstance(tp, str) or not _TOOL_PATTERN_PATTERN.match(tp):
            raise ApprovalStateError(f"grant.tool_pattern 词法非法（仅安全字符集 + * glob）: {tp!r}")
        object.__setattr__(self, "tool_pattern", tp)
        if not isinstance(self.workspace_scope, WorkspaceScope):
            raise ApprovalStateError("grant.workspace_scope 必须是 WorkspaceScope")
        if not (self.workspace_scope.read_roots or self.workspace_scope.write_roots):
            raise ApprovalStateError("grant.workspace_scope 必须声明至少一个根（无界 grant 拒绝）")
        for fname in ("issued_at", "expiry"):
            v = getattr(self, fname)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ApprovalStateError(f"grant.{fname} 必须是非 bool 数值，得到 {v!r}")
            if not math.isfinite(float(v)):
                raise ApprovalStateError(f"grant.{fname} 必须有限（NaN/Inf 拒绝）")
            object.__setattr__(self, fname, float(v))
        if self.issued_at > self.expiry:
            raise ApprovalStateError(
                f"grant 时序非法：issued_at {self.issued_at} > expiry {self.expiry}")
        sn = self.scope_note
        if not isinstance(sn, str):
            raise ApprovalStateError("grant.scope_note 必须是 str")
        object.__setattr__(self, "scope_note", sn.strip())

    def matches(self, tool: str, capability: str, paths: Tuple[str, ...]) -> bool:
        """grant 是否覆盖该 step：capability 精确 + tool pattern（fnmatch）+ 全部路径在 scope 内。"""
        if capability != self.capability:
            return False
        if not fnmatch.fnmatchcase(tool, self.tool_pattern):
            return False
        for p in paths:
            if not self.workspace_scope.contains_path(p):
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "user_event_id": self.user_event_id,
            "capability": self.capability,
            "tool_pattern": self.tool_pattern,
            "workspace_scope": self.workspace_scope.to_dict(),
            "issued_at": self.issued_at,
            "expiry": self.expiry,
            "scope_note": self.scope_note,
        }
