"""Phase 16D — Permission & Approval Boundary（一等异步审批通道）。

位于既有同步 L0–L3 PermissionManager **之上**；effective permission =
WorkContract scope ∩ PermissionManager L0–L3 ∩ explicit approval ∩ backend
capability（四层交集，任何一层不得放宽另一层）。

- ``models``：ApprovalRequest（审批身份绑定 contract_hash + audit/operation 双摘要）/
  ApprovalDecisionKind / ApprovalResolution / AuthorizationGrant（写目标强制
  write_roots）/ ApprovalEvent（递归不可变）+ ToolPermit（绑定 gate/契约/run_id，
  窗口有界）+ PermitOutcome + GateSeal（Gate 签发凭证）+ VerifiedUserEvidence
  （不再公开自铸）+ sanitize/redact/freeze 工具；
- ``broker``：ApprovalBroker（状态所有者——exactly-once 决议、超时、撤销、会话
  grant、**seal 门控 permit 生产 + 单锁原子消费**、redacted 域事件；owner 只在
  构造时绑定；approve_session/grant 消费时刻重查可信 USER 记录并绑定操作上下文）；
- ``gate``：ApprovalGate（四层交集唯一判定器；契约必须匹配可信组合根绑定的
  expected contract_id/content_hash 且经 16A 完整 hash 校验；risk 以可信 PM
  结果为下界；拒绝/等待/消费失败零 tool call）。

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
    GateSeal,
    PermitOutcome,
    ResolutionStatus,
    ToolPermit,
    VerifiedUserEvidence,
    audit_args_digest,
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
    "GateSeal",
    "GateVerdict",
    "PermitOutcome",
    "ResolutionStatus",
    "ToolPermit",
    "VerifiedUserEvidence",
    "audit_args_digest",
    "classify_step_paths",
    "redact_args",
    "sanitize_text",
    "sanitize_tree",
]
