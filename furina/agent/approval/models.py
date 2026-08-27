"""Phase 16D — Permission & Approval Boundary 数据模型（typed approval channel）。

位置（任务书 §1/§4）：位于既有同步 L0–L3 PermissionManager **之上**的一等异步审批
通道。effective permission = WorkContract scope ∩ PermissionManager L0–L3 ∩
explicit approval decision/grant ∩ backend capability；**任何一层都不得放宽另一层**。

Reviewer Patch 1（保留）：审批身份绑定 contract_hash+args 摘要、写目标强制
write_roots、sanitize/freeze 载荷、有效窗口 issued_at<=now<expiry、grant 写语义。

Reviewer Patch 2（保留）：双摘要分离（audit=redacted SHA-256 可导出 / operation=
每 broker 随机密钥 HMAC over 原始 canonical args）；ToolPermit 绑定完整操作身份；
VerifiedUserEvidence 不得公开自铸。

Reviewer Patch 3 关键收紧（本文件）：

1. **GateSeal 删除**：不再以"broker/gate 普通属性中的 seal 对象"作为权限边界
   （Python 对象属性不构成安全隔离，不为此作任何声明）。permit 签发能力改为
   **独立的 PermitIssuer**（broker.py）：内部绑定唯一 gate_id + expected
   contract_id/content_hash，只能由 broker 决策面（owner 线程）
   ``create_permit_issuer`` 创建并注入 Gate——producer 可见对象（broker/gate 公开
   API）不再携带任何 permit 签发能力；
2. **AuthorizationGrant 绑定 contract_id + contract_hash**（必填、全链携带：
   create/list/match/cover/permit）。Contract A 的 grant 绝不覆盖 Contract B，
   即使 tool/capability/workspace 完全相同；
3. **EvidenceContext**：严格、不可变的 typed USER 证据上下文（exact-equality
   身份）。grant 侧绑定 decision/contract_id/hash/capability/tool_pattern/
   workspace/issued_at/expiry/scope_note；approve_session 侧绑定完整
   ApprovalRequest 身份（approval_id/contract_id/hash/run_id/tool/capability/
   requested_scope/risk_level/policy_kind/operation_digest）。nonce 消费要求
   stored context 与当前操作上下文**完全相等**（禁止忽略 stored context），
   且一次性 + 有界生命周期（``MAX_EVIDENCE_NONCE_TTL_SECONDS``），跨上下文
   重放一律拒绝；
4. **ToolPermit 授权来源互斥**：免审批（二者皆空）/ approval / grant 三者互斥，
   approval_id 与 grant_id 同时非空 → 构造拒绝；消费侧同样复核。

Reviewer Patch 4（本文件语义不变，收紧在 broker.py）：permit 消费要求授权来源与
**真实操作**完全一致（approval 全身份维度 + grant.matches 覆盖真实 tool/路径）；
canonical USER 事件生命周期改为 **nonce-only**（原始 lev_* 事件 id 不得绕过 nonce
直接消费；event→context→nonce 原子绑定，一次事件只产生一次授权结果）。

状态机与 owner 线程边界在 broker.py（owner 只在**构造时**绑定，backend 线程不得
抢占）；permit 的签发在 PermitIssuer（决策面创建）、消费在 broker 单锁内原子完成。
"""
from __future__ import annotations

import enum
import fnmatch
import hashlib
import hmac
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
    "MAX_EVIDENCE_NONCE_TTL_SECONDS",
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
    "EvidenceContext",
    "PermitOutcome",
    "ResolutionStatus",
    "ToolPermit",
    "VerifiedUserEvidence",
    "audit_args_digest",
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
_GATE_ID_PATTERN = re.compile(r"^gate_[0-9a-f]{8,32}$")
_CONTRACT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: canonical C6 USER 事件 id（与 WorkContract.source_event_id 同形）：USER provenance
#: 的**必要非充分**条件。真实性由 broker 构造时注入的可信入口验证器在**消费时刻**
#: 重新查询证明，且必须绑定具体操作上下文（approval_id/contract_hash/tool/scope/
#: decision）；backend 文本 / adapter 默认 / 推断意图 / LLM 输出无法通过。
USER_EVENT_ID_PATTERN = re.compile(r"^lev_\d{10,17}_[0-9a-f]{4,32}$")

#: broker 内部 opaque USER 证据 nonce（仅 broker 自己签发/解析）。
USER_EVIDENCE_NONCE_PATTERN = re.compile(r"^uev_[0-9a-f]{8,32}$")

_CAP_TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:\-/]{1,119}$")
_TOOL_PATTERN_PATTERN = re.compile(r"^[a-zA-Z0-9_.:*\-]{1,120}$")

#: permit TTL 上限——更长的"许可窗口"等于重新打开 ALLOW→tool.run 的撤销 TOCTOU。
MAX_PERMIT_TTL_SECONDS = 300.0

#: USER 证据 nonce 生命周期上限（Patch 3）：预验证到消费之间允许的最大间隔；
#: 超窗 nonce 一律拒绝（含取出即销毁的一次性语义，见 broker）。
MAX_EVIDENCE_NONCE_TTL_SECONDS = 300.0

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


def _canonical_json(args: Any) -> str:
    """严格 canonical JSON（sorted keys、紧凑分隔符、ASCII、**严格 JSON 域**）。

    ``default`` 兜底已删除（Patch 2）：set/Path/自定义对象等任何不可 JSON 化的值
    一律 :class:`ApprovalStateError` fail-closed——绝不 ``repr`` 化后当作可哈希身份
    或可审计摘要。
    """
    try:
        return json.dumps(
            args, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ApprovalStateError(f"参数不在严格 JSON 域内（拒绝 repr 兜底）: {exc}") from exc


def audit_args_digest(redacted_args: Any) -> str:
    """**audit digest**：SHA-256 over 严格 canonical **redacted** args。

    确定性（跨 broker 一致）、可导出、供审计；只覆盖已脱敏内容——脱敏后不同敏感
    值会碰撞，因此**不能**用作操作身份（操作身份见 broker.operation_digest）。
    """
    return hashlib.sha256(_canonical_json(thaw_tree(redacted_args)).encode("utf-8")).hexdigest()


def classify_step_paths(tool: str, paths: Tuple[str, ...]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """按工具语义切分 (write_paths, read_paths)。

    保守 fail-closed：tool ∉ READ_ONLY_TOOLS ⇒ **全部**路径视为写目标
    （必须落入 write_roots）。read_roots 不授予写权限。
    """
    if tool in READ_ONLY_TOOLS:
        return (), tuple(paths)
    return tuple(paths), ()


# ---------------------------------------------------------------------------
# VerifiedUserEvidence（不再公开自铸）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VerifiedUserEvidence:
    """**内部** canonical USER 事件证据记录（Patch 2：不得公开自铸）。

    - broker 不再公开铸造/返回本对象（public ``verify_user_evidence`` 已删除）；
    - 消费入口（``ApprovalBroker.create_grant`` / ``resolve(APPROVE_SESSION)``）
      只接受本 broker 签发的 opaque nonce（``uev_*``；**Patch 4：原始 event id
      不再接受，必须先经 request_user_evidence 绑定事件上下文**）；
      **手工构造本对象一律拒绝**——它只是内部形态遗留，供测试/文档引用。
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
# EvidenceContext（Patch 3：严格、不可变的 typed USER 证据上下文）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EvidenceContext:
    """canonical USER 证据的**类型化操作上下文**（exact-equality 身份）。

    - **grant 侧**（``decision="grant"``）至少绑定：contract_id / contract_hash /
      capability / tool_pattern / workspace（read+write roots）/ issued_at /
      expiry / scope_note；
    - **approve_session 侧**（``decision="approve_session"``）绑定**完整
      ApprovalRequest 身份**：approval_id / contract_id / contract_hash / run_id /
      tool / capability / requested_scope / risk_level / policy_kind /
      operation_digest；
    - ``request_user_evidence`` 以本对象为身份预验证并签发 nonce；消费
      （approve_session 决议 / create_grant）要求 stored context 与消费时刻从
      **真实操作记录派生**的 expected context **完全相等**（dataclass 逐字段
      equality）——任何一维变化（capability/expiry/workspace/scope_note/args
      摘要…）即拒绝；**禁止忽略 stored context**；
    - 不可变：构造时统一 normalize（strip/sanitize/float/tuple），此后无任何
      mutator；相等性即身份。
    """

    decision: str
    contract_id: str
    contract_hash: str
    # ---- grant 侧 ----
    capability: str = ""
    tool_pattern: str = ""
    workspace_read_roots: Tuple[str, ...] = ()
    workspace_write_roots: Tuple[str, ...] = ()
    issued_at: float = 0.0
    expiry: float = 0.0
    scope_note: str = ""
    # ---- approve_session 侧（完整 ApprovalRequest 身份）----
    approval_id: str = ""
    run_id: str = ""
    tool: str = ""
    requested_scope: Tuple[str, ...] = ()
    risk_level: str = ""
    policy_kind: str = ""
    operation_digest: str = ""

    def __post_init__(self) -> None:
        d = self.decision
        if not isinstance(d, str) or d.strip() not in ("approve_session", "grant"):
            raise ApprovalStateError(
                f"EvidenceContext.decision 必须 ∈ {{'approve_session', 'grant'}}，得到 {d!r}")
        object.__setattr__(self, "decision", d.strip())
        cid = self.contract_id
        if not isinstance(cid, str) or not cid.strip():
            raise ApprovalStateError(f"EvidenceContext.contract_id 必须是非空 str，得到 {cid!r}")
        object.__setattr__(self, "contract_id", sanitize_text(cid.strip()))
        ch = self.contract_hash
        if not isinstance(ch, str) or (ch and not _CONTRACT_HASH_PATTERN.match(ch)):
            # 空串仅用于"裸请求"（ApprovalRequest.contract_hash 可空）派生的
            # approve_session 上下文；grant 侧 create_grant 前置校验强制 64-hex。
            raise ApprovalStateError(
                f"EvidenceContext.contract_hash 必须是 64 位小写 hex 或空串，得到 {ch!r}")
        object.__setattr__(self, "contract_hash", ch)
        for fname in ("capability", "tool_pattern", "approval_id", "run_id", "tool",
                      "risk_level", "policy_kind"):
            v = getattr(self, fname)
            if not isinstance(v, str):
                raise ApprovalStateError(f"EvidenceContext.{fname} 必须是 str，得到 {v!r}")
            object.__setattr__(self, fname, sanitize_text(v.strip()))
        od = self.operation_digest
        if od:
            if not isinstance(od, str) or not _DIGEST_PATTERN.match(od):
                raise ApprovalStateError(
                    f"EvidenceContext.operation_digest 必须是 64 位小写 hex 或空串，得到 {od!r}")
        else:
            object.__setattr__(self, "operation_digest", "")
        for fname in ("workspace_read_roots", "workspace_write_roots", "requested_scope"):
            raw = getattr(self, fname)
            if not isinstance(raw, (tuple, list)):
                raise ApprovalStateError(f"EvidenceContext.{fname} 必须是序列，得到 {raw!r}")
            norm = []
            for p in raw:
                if not isinstance(p, str) or not p.strip():
                    raise ApprovalStateError(
                        f"EvidenceContext.{fname} 条目必须是非空 str，得到 {p!r}")
                norm.append(p.strip())
            object.__setattr__(self, fname, tuple(norm))
        for fname in ("issued_at", "expiry"):
            v = getattr(self, fname)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                raise ApprovalStateError(f"EvidenceContext.{fname} 必须是有限数值，得到 {v!r}")
            object.__setattr__(self, fname, float(v))
        if not isinstance(self.scope_note, str):
            raise ApprovalStateError("EvidenceContext.scope_note 必须是 str")
        object.__setattr__(self, "scope_note", sanitize_text(self.scope_note.strip()))

    def to_payload(self) -> Dict[str, Any]:
        """导出 plain dict（供可信入口验证器查询；lists 化的元组字段）。"""
        return {
            "decision": self.decision,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "capability": self.capability,
            "tool_pattern": self.tool_pattern,
            "workspace_read_roots": list(self.workspace_read_roots),
            "workspace_write_roots": list(self.workspace_write_roots),
            "issued_at": self.issued_at,
            "expiry": self.expiry,
            "scope_note": self.scope_note,
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "tool": self.tool,
            "requested_scope": list(self.requested_scope),
            "risk_level": self.risk_level,
            "policy_kind": self.policy_kind,
            "operation_digest": self.operation_digest,
        }


# ---------------------------------------------------------------------------
# ApprovalRequest
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ApprovalRequest:
    """一次异步审批请求（不可变；只存 redacted 参数摘要，原始参数不进入审批域）。

    **审批身份**：contract_id + contract_hash + run_id + tool + capability +
    requested_scope + risk_level + policy_kind + **operation_digest**（HMAC，见
    broker）——请求身份完整绑定被批准的操作；不同操作（含仅敏感值不同）不得复用。
    ``audit_args_digest`` 为可导出的 redacted 审计摘要（非操作身份）。
    """

    approval_id: str
    contract_id: str
    run_id: str
    tool: str
    capability: str
    #: normalized/redacted 参数摘要（由 broker 在 create 时 redact，永不存原始参数）。
    args_redacted: Mapping[str, Any]
    #: audit digest：SHA-256 over redacted canonical args（可导出审计身份）。
    audit_args_digest: str
    #: operation digest：broker 每实例随机密钥 HMAC over 原始 canonical args。
    #: 操作身份——不同敏感值产生不同值；不保存原文，亦不导出审计。
    operation_digest: str
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
        for fname in ("audit_args_digest", "operation_digest"):
            v = getattr(self, fname)
            if not isinstance(v, str) or not _DIGEST_PATTERN.match(v):
                raise ApprovalStateError(
                    f"ApprovalRequest.{fname} 必须是 64 位小写 hex，得到 {v!r}")
            object.__setattr__(self, fname, v)
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
        **防御复制**——返回全新 plain 对象图，修改不影响存储的不可变状态。
        ``operation_digest`` 为 HMAC（每 broker 密钥）不导出；审计摘要可导出。"""
        return {
            "approval_id": self.approval_id,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "run_id": self.run_id,
            "tool": self.tool,
            "capability": self.capability,
            "args_redacted": thaw_tree(self.args_redacted),
            "audit_args_digest": self.audit_args_digest,
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

    - **Patch 3：绑定 contract_id + contract_hash（必填）**——grant 只对**同一份
      契约内容**生效；create/list/match/cover/permit 全链携带。Contract A 的
      grant 绝不覆盖 Contract B（即使 tool/capability/workspace 完全相同），
      同 id 不同 hash 的换约内容同样不覆盖；
    - ``user_event_id`` 必须是 canonical C6 USER 事件 id（``lev_<ms>_<hex>``）**且**
      在 broker 消费时刻经可信入口验证器绑定具体操作上下文重新确认——格式正则只是
      必要条件，opaque nonce 只在本 broker 有效；backend 文本 / adapter 默认 /
      推断意图 / LLM 输出不可能通过；
    - ``capability`` 精确绑定；``tool_pattern`` 精确名或仅安全字符集的 glob；
    - ``workspace_scope`` 必须有至少一个根（无界 grant 拒绝）；**read_roots 不授予
      写权限**（``matches`` 对 write_paths 强制落入 write_roots）；
    - ``expiry`` 有限且 ≥ issued_at（**无永久 grant**）；有效窗口
      ``issued_at <= now < expiry``；``revoked_at`` 由 broker 记录。
    """

    grant_id: str
    user_event_id: str
    contract_id: str
    contract_hash: str
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
        cid = self.contract_id
        if not isinstance(cid, str) or not cid.strip():
            raise ApprovalStateError(
                f"grant.contract_id 必须是非空 str（grant 必须绑定契约，Patch 3），得到 {cid!r}")
        object.__setattr__(self, "contract_id", sanitize_text(cid.strip()))
        ch = self.contract_hash
        if not isinstance(ch, str) or not _CONTRACT_HASH_PATTERN.match(ch):
            raise ApprovalStateError(
                f"grant.contract_hash 必须是 64 位小写 hex（grant 必须绑定契约内容，"
                f"Patch 3），得到 {ch!r}")
        object.__setattr__(self, "contract_hash", ch)
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
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "capability": self.capability,
            "tool_pattern": self.tool_pattern,
            "workspace_scope": self.workspace_scope.to_dict(),
            "issued_at": self.issued_at,
            "expiry": self.expiry,
            "scope_note": self.scope_note,
        }


# ---------------------------------------------------------------------------
# ToolPermit（Gate ALLOW → tool.run 的原子消费凭证）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolPermit:
    """工具边界许可：**仅由四层 Gate** 在 ALLOW 时签发；真实工具边界
    ``gate.consume_permit`` 原子消费/复核。

    - 绑定完整操作身份：``gate_id``（签发本 permit 的 Gate 决议者）+ tool +
      capability + ``operation_digest``（broker 密钥 HMAC over 原始 args）+
      ``contract_id`` + ``content_hash`` + ``run_id``；
    - **授权来源互斥（Patch 3）**：免审批（approval_id 与 grant_id 均空）/
      approval（仅 approval_id）/ grant（仅 grant_id）三者互斥——approval_id 与
      grant_id 同时非空 → 构造拒绝，消费侧同锁复核；
    - 有效窗口有界：``not_before <= now < valid_until`` 且
      ``valid_until - not_before <= MAX_PERMIT_TTL_SECONDS``（超长窗口构造拒绝）；
    - 消费在 broker 单锁内**原子**完成（全部校验通过后单点提交）：approve_once
      恰好消费一次、approve_session 仍处 APPROVED_SESSION、grant 未撤销且
      ``issued_at <= now < expiry``——任一失败即零 tool call 且零状态变更。
    """

    permit_id: str
    gate_id: str
    tool: str
    capability: str
    operation_digest: str
    contract_id: str
    contract_hash: str
    run_id: str
    approval_id: str = ""
    grant_id: str = ""
    not_before: float = 0.0
    valid_until: float = 0.0

    def __post_init__(self) -> None:
        pid = self.permit_id
        if not isinstance(pid, str) or not PERMIT_ID_PATTERN.match(pid):
            raise ApprovalStateError(f"permit_id 必须匹配 pmt_<hex>，得到 {pid!r}")
        gid = self.gate_id
        if not isinstance(gid, str) or not _GATE_ID_PATTERN.match(gid):
            raise ApprovalStateError(f"gate_id 必须匹配 gate_<hex>，得到 {gid!r}")
        for fname in ("tool", "capability", "contract_id", "run_id"):
            v = getattr(self, fname)
            if not isinstance(v, str):
                raise ApprovalStateError(f"ToolPermit.{fname} 必须是 str，得到 {v!r}")
            object.__setattr__(self, fname, sanitize_text(v.strip()))
        if not self.contract_id:
            raise ApprovalStateError("ToolPermit.contract_id 必须非空（绑定契约身份）")
        if not isinstance(self.contract_hash, str) or not _CONTRACT_HASH_PATTERN.match(self.contract_hash):
            raise ApprovalStateError(f"ToolPermit.contract_hash 必须是 64 位小写 hex")
        if not isinstance(self.operation_digest, str) or not _DIGEST_PATTERN.match(self.operation_digest):
            raise ApprovalStateError(f"ToolPermit.operation_digest 必须是 64 位小写 hex")
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
        if self.valid_until - self.not_before > MAX_PERMIT_TTL_SECONDS:
            raise ApprovalStateError(
                f"ToolPermit 有效窗口超长：{self.valid_until - self.not_before}s > "
                f"上限 {MAX_PERMIT_TTL_SECONDS}s（长窗口=重新打开撤销 TOCTOU）")
        if self.approval_id and self.grant_id:
            raise ApprovalStateError(
                f"ToolPermit 授权来源互斥（Patch 3）：approval 与 grant 不得同时存在"
                f"（approval_id={self.approval_id!r}, grant_id={self.grant_id!r}）——"
                "来源只能是 免审批（均空）/ approval / grant 三者之一")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "permit_id": self.permit_id,
            "gate_id": self.gate_id,
            "tool": self.tool,
            "capability": self.capability,
            "operation_digest": self.operation_digest,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "run_id": self.run_id,
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
