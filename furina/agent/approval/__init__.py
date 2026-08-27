"""Phase 16D — Permission & Approval Boundary（一等异步审批通道）。

位于既有同步 L0–L3 PermissionManager **之上**；effective permission =
WorkContract scope ∩ PermissionManager L0–L3 ∩ explicit approval ∩ backend
capability（四层交集，任何一层不得放宽另一层）。

- ``models``：ApprovalRequest / ApprovalDecisionKind / ApprovalResolution /
  AuthorizationGrant / ApprovalEvent + 参数 redaction；
- ``broker``：ApprovalBroker（状态所有者——exactly-once 决议、超时、撤销、
  会话 grant、redacted 域事件；decision 面只允许 owner 线程）；
- ``gate``：ApprovalGate（四层交集唯一判定器；拒绝/等待零 tool call）。

边界（任务书 §6）：不替换/削弱 PermissionManager；无 UI/Hermes/verifier/C7 写入；
无 C1–C7 schema / DB 迁移；无任何持久化行为。
"""
from .broker import ApprovalBroker
from .gate import ApprovalGate, GateResult, GateVerdict
from .models import (
    APPROVAL_EVENT_TYPES,
    USER_EVENT_ID_PATTERN,
    ApprovalDecisionKind,
    ApprovalEvent,
    ApprovalRequest,
    ApprovalResolution,
    ApprovalState,
    ApprovalStateError,
    AuthorizationGrant,
    ResolutionStatus,
    redact_args,
)

__all__ = [
    "APPROVAL_EVENT_TYPES",
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
    "ResolutionStatus",
    "redact_args",
]
