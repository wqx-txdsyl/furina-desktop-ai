"""Phase 16D — Permission & Approval Boundary 数据模型（typed approval channel）。

位置（任务书 §1/§4）：位于既有同步 L0–L3 PermissionManager **之上**的一等异步审批
通道。effective permission = WorkContract scope ∩ PermissionManager L0–L3 ∩
explicit approval decision/grant ∩ backend capability；**任何一层都不得放宽另一层**。

Reviewer Patch 关键收紧（本文件）：
- **审批身份完整性**：ApprovalRequest 携带 ``contract_hash``（16A 内容摘要）与
  ``args_digest``（规范化参数摘要）；请求身份 = contract_id + contract_hash + run_id +
  tool + capability + requested_scope + risk_level + policy_kind + args_digest——
  **不同操作不得复用同一审批**；
- **canonical USER evidence**：``VerifiedUserEvidence`` 只能由 broker 经**可信入口
  注入的验证器**（``user_evidence_verifier``）产生；格式正则只是必要条件，不是
  真实性证明；approve_session 与 grant 一律要求该证据；
- **递归不可变 + 导出防御复制**：request/event 审计载荷存储时递归冻结
  （MappingProxyType/tuple），导出（to_audit_dict / to_payload）深拷贝为全新对象图；
- **可见文本统一限长/脱敏**：``sanitize_text`` —— 控制字符清除 + 秘密形态脱敏 +
  限长截断；所有进入事件/审计/决议 detail 的自由文本一律经过它；
- **grant 写语义**：``matches`` 区分 write_paths——read_roots 不授予写权限；
- **ToolPermit**：gate ALLOW → 真实工具边界 ``consume_permit`` 原子消费/复核，
  消除 ALLOW 与 tool.run 之间的撤销 TOCTOU。

状态机与 owner 线程边界在 broker.py（owner 只在**构造时**由可信组合根绑定，
backend 线程不得抢占）；四层交集判定在 gate.py。

边界（任务书 §6）：不替换/削弱 PermissionManager；无 UI/Hermes/verifier/C7 写入；
无 C1–C7 schema / DB 迁移；无任何持久化行为。
"""
from __future__ import annotations

import enum
import fnmatch
import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from furina.agent.permission import Permission
from furina.agent.work_contract import APPROVAL_POLICY_KINDS, WorkspaceScope
from furina.core import FurinaError

__all__ = [
    "APPROVAL_EVENT_TYPES",
    "MAX_PERMIT_TTL_SECONDS",
    "PERMIT_ID_PATTERN",
    "READ_ONLY_TOOLS",
    "USER_EVENT_ID_PATTERN",
    "ApprovalDecisionKind",
    "ApprovalEvent",
    "ApprovalRequest",
    "ApprovalResolution",
    "ApprovalState",
    "ApprovalStateError",
    "AuthorizationGrant",
    "PermitOutcome",
    "ResolutionStatus",
    "ToolPermit",
    "VerifiedUserEvidence",
    "canonical_args_digest",
    "classify_step_paths",
    "deep_freeze",
    "redact_args",
    "sanitize_text",
    "sanitize_tree",
    "thaw_tree",
]


class ApprovalStateError(FurinaError):
    """审批域类型化错误（非法字段 / 非 owner 变更 / 未知 id / 非法决议）。"""


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class ApprovalState(str, enum.Enum):
    """请求生命周期：PENDING → 终态（终态不可逆）。

    - APPROVED_ONCE：一次性批准（permit 在真实工具边界消费后失效）；
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
PERMIT_ID_PATTERN = re.compile(r"^pmt_[0-9a-f]{8,32}$")
_CONTRACT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: canonical C6 USER 事件 id（与 WorkContract.source_event_id 同形）：USER provenance
#: 的**必要非充分**条件。真实性由 broker 构造时注入的可信入口验证器
#: （user_evidence_verifier → VerifiedUserEvidence）证明；backend 文本 / adapter
#: 默认 / 推断意图 / LLM 输出即使凑出该形态也无法通过验证器。
USER_EVENT_ID_PATTERN = re.compile(r"^lev_\d{10,17}_[0-9a-f]{4,32}$")

_CAP_TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:\-/]{1,119}$")
_TOOL_PATTERN_PATTERN = re.compile(r"^[a-zA-Z0-9_.:*\-]{1,120}$")

#: permit TTL 上限——更长的"许可窗口"等于重新打开 ALLOW→tool.run 的撤销 TOCTOU。
MAX_PERMIT_TTL_SECONDS = 300.0

#: 只读工具白名单（**保守 fail-closed**）：不在此白名单内的工具，其全部路径
#: 一律按**写目标**校验（必须落入 contract/grant 的 write_roots；read_roots 不授予
#: 写权限）。白名单外的新工具默认更严，不会静默获得读根写权。
READ_ONLY_TOOLS = frozenset({
    "fs.list_dir", "fs.read_file", "fs.exists", "fs.stat", "fs.search",
    "doc.read", "desktop.list_windows", "desktop.active_window",
})


# ---------------------------------------------------------------------------
# redaction / sanitize（参数/秘密/自由文本进入事件与日志前必须处理）
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
#: 控制字符（保留 \t \n \r）：可见文本不得携带不可见控制序列。
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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


def sanitize_text(value: Any, *, max_len: int = _MAX_STR_LEN) -> str:
    """**所有用户可见/审计文本**的统一出口：控制字符清除 + 秘密形态脱敏 + 限长截断。

    非 str 输入先 ``str()`` 化（类型错误在字段层已拒绝；此处是最后出口）。
    """
    s = value if isinstance(value, str) else str(value)
    s = _CONTROL_CHARS_PATTERN.sub(" ", s)
    s = _SECRET_VALUE_PATTERN.sub(_REDACTED, s)
    if len(s) > max_len:
        s = s[:max_len] + "...[truncated]"
    return s


def sanitize_tree(obj: Any) -> Any:
    """递归 sanitize：树内所有 str 节点过 ``sanitize_text``；容器重建，绝不修改入参。"""
    if isinstance(obj, Mapping):
        return {k: sanitize_tree(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(sanitize_tree(v) for v in obj)
    if isinstance(obj, str):
        return sanitize_text(obj)
    return obj


def deep_freeze(obj: Any) -> Any:
    """递归不可变：dict→MappingProxyType、list/tuple→tuple（叶子标量原样）。"""
    if isinstance(obj, dict):
        return MappingProxyType({k: deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(deep_freeze(v) for v in obj)
    return obj


def thaw_tree(obj: Any) -> Any:
    """防御复制导出：冻结树（或混合树）→ 全新 plain dict/list 对象图（可 JSON 化）。"""
    if isinstance(obj, Mapping):
        return {k: thaw_tree(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [thaw_tree(v) for v in obj]
    return obj


def canonical_args_digest(redacted_args: Any) -> str:
    """规范化参数摘要：对 redacted args 的 canonical JSON（sorted/紧凑/ASCII/严格域）
    取 SHA-256。审批身份的"操作"绑定（同 tool 不同 args ⇒ 不同摘要 ⇒ 不同审批）。"""
    try:
        canonical = json.dumps(
            thaw_tree(redacted_args), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False, default=repr,
        )
    except (TypeError, ValueError) as exc:
        raise ApprovalStateError(f"args 摘要载荷不可规范化: {exc}") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_step_paths(tool: str, paths: Tuple[str, ...]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """按工具语义切分 (write_paths, read_paths)。

    保守 fail-closed：tool ∉ READ_ONLY_TOOLS ⇒ **全部**路径视为写目标
    （必须落入 write_roots）。read_roots 不授予写权限。
    """
    if tool in READ_ONLY_TOOLS:
        return (), tuple(paths)
    return tuple(paths), ()


# ---------------------------------------------------------------------------
# VerifiedUserEvidence（canonical USER 证据）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VerifiedUserEvidence:
    """经**可信入口验证器**确认的 canonical USER 事件证据。

    唯一合法产生路径：``ApprovalBroker.verify_user_evidence(user_event_id)``——
    broker 构造时注入 ``user_evidence_verifier``（可信组合根所有）；验证器返回
    真值才铸造本对象。**格式正则不是真实性证明**：凑出 ``lev_<ms>_<hex>`` 形态
    的 backend/LLM 文本无法通过验证器。
    """

    user_event_id: str
    verified_at: float
    verified_by: str

    def __post_init__(self) -> None:
        ue = self.user_event_id
        if not isinstance(ue, str) or not USER_EVENT_ID_PATTERN.match(ue):
            raise ApprovalStateError(
                f"USER 证据事件 id 必须匹配 lev_<ms>_<hex>，得到 {ue!r}")
        object.__setattr__(self, "user_event_id", ue)
        va = self.verified_at
        if isinstance(va, bool) or not isinstance(va, (int, float)) or not math.isfinite(float(va)):
            raise ApprovalStateError(f"USER 证据 verified_at 必须是有限数值，得到 {va!r}")
        object.__setattr__(self, "verified_at", float(va))
        vb = self.verified_by
        if not isinstance(vb, str) or not vb.strip():
            raise ApprovalStateError(f"USER 证据 verified_by 必须是非空 str，得到 {vb!r}")
        object.__setattr__(self, "verified_by", sanitize_text(vb, max_len=120))


# ---------------------------------------------------------------------------
# ApprovalRequest
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ApprovalRequest:
    """一次异步审批请求（不可变；只存 redacted 参数摘要，原始参数不进入审批域）。

    **审批身份**（Reviewer Patch）：contract_id + contract_hash + run_id + tool +
    capability + requested_scope + risk_level + policy_kind + args_digest——
    请求身份完整绑定被批准的操作；不同操作不得复用。
    """

    approval_id: str
    contract_id: str
    run_id: str
    tool: str
    capability: str
    #: normalized/redacted 参数摘要（由 broker 在 create 时 redact，永不存原始参数）。
    args_redacted: Mapping[str, Any]
    #: 规范化参数摘要（redacted args 的 SHA-256 canonical JSON）——身份绑定。
    args_digest: str
    #: 16A WorkContract 内容摘要（64 hex；空串表示未绑定契约 hash 的裸请求）。
    contract_hash: str
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
            object.__setattr__(self, fname, sanitize_text(v.strip()))
        if not isinstance(self.reason, str):   # reason 允许为空（可选说明），但必须 str
            raise ApprovalStateError(f"ApprovalRequest.reason 必须是 str，得到 {type(self.reason).__name__}")
        # 可见文本统一出口：限长 + 控制字符清除 + 秘密形态脱敏
        object.__setattr__(self, "reason", sanitize_text(self.reason.strip()))
        if not isinstance(self.args_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.args_digest):
            raise ApprovalStateError(
                f"args_digest 必须是 64 位小写 hex（canonical_args_digest），得到 {self.args_digest!r}")
        object.__setattr__(self, "args_digest", self.args_digest)
        if not isinstance(self.contract_hash, str):
            raise ApprovalStateError(f"contract_hash 必须是 str，得到 {self.contract_hash!r}")
        if self.contract_hash and not _CONTRACT_HASH_PATTERN.match(self.contract_hash):
            raise ApprovalStateError(
                f"contract_hash 必须是 64 位小写 hex 或空串，得到 {self.contract_hash!r}")
        object.__setattr__(self, "contract_hash", self.contract_hash)
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
        # 存储递归不可变（dict→MappingProxyType、list→tuple）；导出经 to_audit_dict 深拷贝
        object.__setattr__(self, "args_redacted", deep_freeze(dict(self.args_redacted)))
        scope = []
        for p in self.requested_scope:
            if not isinstance(p, str) or not p.strip():
                raise ApprovalStateError("requested_scope 条目必须是非空 str")
            scope.append(p.strip())
        object.__setattr__(self, "requested_scope", tuple(scope))

    def to_audit_dict(self) -> Dict[str, Any]:
        """用户可见/审计 payload：只含 redacted 字段（args 已脱敏，值永不泄漏）；
        **防御复制**——返回全新 plain 对象图，修改不影响存储的不可变状态。"""
        return {
            "approval_id": self.approval_id,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "run_id": self.run_id,
            "tool": self.tool,
            "capability": self.capability,
            "args_redacted": thaw_tree(self.args_redacted),
            "args_digest": self.args_digest,
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", sanitize_text(self.detail))


#: broker 产生的域事件类型（均只携带 redacted + sanitized payload）。
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
    """redacted 域事件（broker.events 日志 / 外部 emit 的统一载荷）。

    payload 构造时递归 sanitize + 递归冻结（不可变）；导出经 ``to_payload`` 深拷贝。
    """

    etype: str
    approval_id: str = ""
    grant_id: str = ""
    payload: Mapping[str, Any] = None   # type: ignore[assignment]
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.payload is None:
            object.__setattr__(self, "payload", MappingProxyType({}))
        elif isinstance(self.payload, Mapping):
            object.__setattr__(self, "payload", deep_freeze(dict(self.payload)))
        else:
            raise ApprovalStateError("ApprovalEvent.payload 必须是 Mapping")

    def to_payload(self) -> Dict[str, Any]:
        """防御复制导出：全新 plain dict（可 JSON 化）；修改不影响存储事件。"""
        return thaw_tree(self.payload)


# ---------------------------------------------------------------------------
# AuthorizationGrant（会话/持久授权）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthorizationGrant:
    """会话授权记录：强制 canonical USER provenance + 有界 scope + 可撤销。

    - ``user_event_id`` 必须是 canonical C6 USER 事件 id（``lev_<ms>_<hex>``）**且**
      经 broker 的可信入口验证器确认为真（格式正则只是必要条件，见
      ``ApprovalBroker.verify_user_evidence``）——backend 文本 / adapter 默认 /
      推断意图 / LLM 输出一律不可能通过；
    - ``capability`` 精确绑定；``tool_pattern`` 精确名或仅安全字符集的 glob；
    - ``workspace_scope`` 必须有至少一个根（无界 grant 拒绝）；**read_roots 不授予
      写权限**（``matches`` 对 write_paths 强制落入 write_roots）；
    - ``expiry`` 有限且 ≥ issued_at（**无永久 grant**）；有效窗口
      ``issued_at <= now < expiry``；``revoked_at`` 由 broker 记录。
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
        object.__setattr__(self, "scope_note", sanitize_text(sn.strip()))

    def matches(self, tool: str, capability: str, paths: Tuple[str, ...],
                write_paths: Tuple[str, ...] = ()) -> bool:
        """grant 是否覆盖该 step：capability 精确 + tool pattern（fnmatch）+ 全部路径
        在 scope 内，且**写目标必须落入 write_roots**（read_roots 不授予写权限）。"""
        if capability != self.capability:
            return False
        if not fnmatch.fnmatchcase(tool, self.tool_pattern):
            return False
        for p in paths:
            if not self.workspace_scope.contains_path(p):
                return False
        for p in (write_paths or ()):
            if not self.workspace_scope.contains_path(p, writable=True):
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


# ---------------------------------------------------------------------------
# ToolPermit（ALLOW → tool.run 的原子消费凭证）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolPermit:
    """工具边界许可：gate ALLOW 时签发，真实工具边界 ``consume_permit`` 原子消费。

    - 绑定被放行的操作身份（tool/capability/args_digest）与授权来源
      （approval_id 或 grant_id，二者可同时为空 = 无需审批路径）；
    - 有效窗口 ``not_before <= now < valid_until``（有界 TTL，拒绝长窗口重新
      打开撤销 TOCTOU）；
    - 消费在 broker 单锁内**原子**完成：approve_once 恰好消费一次、approve_session
      仍处 APPROVED_SESSION、grant 未撤销且 ``issued_at <= now < expiry``——
      任一不满足即消费失败 → 零 tool call。
    """

    permit_id: str
    tool: str
    capability: str
    args_digest: str
    approval_id: str = ""
    grant_id: str = ""
    not_before: float = 0.0
    valid_until: float = 0.0

    def __post_init__(self) -> None:
        pid = self.permit_id
        if not isinstance(pid, str) or not PERMIT_ID_PATTERN.match(pid):
            raise ApprovalStateError(f"permit_id 必须匹配 pmt_<hex>，得到 {pid!r}")
        for fname in ("tool", "capability"):
            v = getattr(self, fname)
            if not isinstance(v, str) or not v.strip():
                raise ApprovalStateError(f"ToolPermit.{fname} 必须是非空 str，得到 {v!r}")
            object.__setattr__(self, fname, sanitize_text(v.strip()))
        if not isinstance(self.args_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.args_digest):
            raise ApprovalStateError(f"ToolPermit.args_digest 必须是 64 位小写 hex")
        for fname in ("approval_id", "grant_id"):
            v = getattr(self, fname)
            if not isinstance(v, str):
                raise ApprovalStateError(f"ToolPermit.{fname} 必须是 str，得到 {v!r}")
            object.__setattr__(self, fname, v.strip())
        for fname in ("not_before", "valid_until"):
            v = getattr(self, fname)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                raise ApprovalStateError(f"ToolPermit.{fname} 必须是有限数值，得到 {v!r}")
            object.__setattr__(self, fname, float(v))
        if self.not_before >= self.valid_until:
            raise ApprovalStateError(
                f"ToolPermit 有效窗口非法：not_before {self.not_before} >= valid_until {self.valid_until}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "permit_id": self.permit_id,
            "tool": self.tool,
            "capability": self.capability,
            "args_digest": self.args_digest,
            "approval_id": self.approval_id,
            "grant_id": self.grant_id,
            "not_before": self.not_before,
            "valid_until": self.valid_until,
        }


@dataclass(frozen=True)
class PermitOutcome:
    """``consume_permit`` 的类型化结果（ok=True 才允许 tool.run）。"""

    ok: bool
    reason: str
    permit_id: str = ""
    consumed_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", sanitize_text(self.reason))
