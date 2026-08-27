"""Phase 16D — Permission & Approval Boundary（一等异步审批通道）。

位于既有同步 L0–L3 PermissionManager **之上**；effective permission =
WorkContract scope ∩ PermissionManager L0–L3 ∩ explicit approval ∩ backend
capability（四层交集，任何一层不得放宽另一层）。

- ``models``：ApprovalRequest（审批身份绑定 contract hash + 规范化参数摘要）/
  ApprovalDecisionKind / ApprovalResolution / AuthorizationGrant（写目标强制
  write_roots）/ ApprovalEvent（递归不可变）+ ToolPermit/PermitOutcome（工具边界
  原子消费）+ VerifiedUserEvidence（可信入口验证的 canonical USER 证据）+
  sanitize/redact/freeze 工具；
- ``broker``：ApprovalBroker（状态所有者——exactly-once 决议、超时、撤销、会话
  grant、permit 原子消费、redacted 域事件；owner 只在构造时绑定，decision 面
  仅 owner 线程；approve_session/grant 强制可信 USER 证据）；
- ``gate``：ApprovalGate（四层交集唯一判定器；契约必须经 16A 完整 hash 校验；
  risk 以可信 PM 结果为下界；拒绝/等待/消费失败零 tool call）。

边界（任务书 §6）：不替换/削弱 PermissionManager；无 UI/Hermes/verifier/C7 写入；
无 C1–C7 schema / DB 迁移；无任何持久化行为。
"""
from .broker import ApprovalBroker
from .gate import ApprovalGate, GateResult, GateVerdict
from .models import (
    APPROVAL_EVENT_TYPES,
    MAX_PERMIT_TTL_SECONDS,
    READ_ONLY_TOOLS,
    USER_EVENT_ID_PATTERN,
    ApprovalDecisionKind,
    ApprovalEvent,
    ApprovalRequest,
    ApprovalResolution,
    ApprovalState,
    ApprovalStateError,
    AuthorizationGrant,
    PermitOutcome,
    ResolutionStatus,
    ToolPermit,
    VerifiedUserEvidence,
    canonical_args_digest,
    classify_step_paths,
    redact_args,
    sanitize_text,
    sanitize_tree,
)

__all__ = [
    "APPROVAL_EVENT_TYPES",
    "MAX_PERMIT_TTL_SECONDS",
    "READ_ONLY_TOOLS",
    "USER_EVENT_ID_PATTERN",
    "ApprovalBroker",
    "ApprovalDecisionKind",
    "ApprovalEvent",
    "ApprovalGate",
    "ApprovalRequest",
    "ApprovalResolution",
    "ApprovalState",
    "ApprovalStateError",
    "AuthorizationGrant",
    "GateResult",
    "GateVerdict",
    "PermitOutcome",
    "ResolutionStatus",
    "ToolPermit",
    "VerifiedUserEvidence",
    "canonical_args_digest",
    "classify_step_paths",
    "redact_args",
    "sanitize_text",
    "sanitize_tree",
]
