"""Phase 16D — Permission & Approval Boundary（一等异步审批通道）。

位于既有同步 L0–L3 PermissionManager **之上**；effective permission =
WorkContract scope ∩ PermissionManager L0–L3 ∩ explicit approval ∩ backend
capability（四层交集，任何一层不得放宽另一层）。

- ``models``：ApprovalRequest（审批身份绑定 contract_hash + audit/operation 双摘要）/
  ApprovalDecisionKind / ApprovalResolution / AuthorizationGrant（**Patch 3：绑定
  contract_id+contract_hash，全链携带；Contract A 的 grant 不覆盖 Contract B**）/
  ApprovalEvent（递归不可变）+ ToolPermit（绑定 gate/契约/run_id，窗口有界，
  **授权来源互斥：免审批/approval/grant**）+ PermitOutcome + EvidenceContext
  （**Patch 3：严格不可变 typed USER 证据上下文，exact-equality 身份**）+
  VerifiedUserEvidence（不再公开自铸）+ sanitize/redact/freeze 工具；
- ``broker``：ApprovalBroker（状态所有者——exactly-once 决议、超时、撤销、会话
  grant、**Patch 3：单锁原子消费（全部校验后单点提交）**、**Patch 4：来源精确绑定
  （approval 全身份维度 + grant.matches 覆盖真实操作）**、redacted 域事件；owner
  只在构造时绑定；approve_session/grant 消费**只接受本 broker 签发的 nonce**（Patch
  4：原始 lev_* 事件 id 不得绕过 nonce 生命周期），**event→context→nonce 原子绑定、
  一次事件一次授权**，消费时刻重查可信 USER 记录并要求 **typed context 完全相等**）
  + PermitIssuer（**Patch 3：permit 签发器——内部绑定唯一 gate_id + expected
  contract_id/hash，仅决策面（owner 线程）``create_permit_issuer`` 创建；公开
  GateSeal/issue_permit 已删除，producer 面零签发能力**）；
- ``gate``：ApprovalGate（四层交集唯一判定器；契约绑定与 gate_id 来自 PermitIssuer；
  risk 以可信 PM 结果为下界；拒绝/等待/消费失败零 tool call）。

边界（任务书 §6）：不替换/削弱 PermissionManager；无 UI/Hermes/verifier/C7 写入；
无 C1–C7 schema / DB 迁移；无任何持久化行为。
"""
from .broker import ApprovalBroker, PermitIssuer
from .gate import ApprovalGate, GateResult, GateVerdict
from .models import (
    APPROVAL_EVENT_TYPES,
    MAX_EVIDENCE_NONCE_TTL_SECONDS,
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
    EvidenceContext,
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
    "MAX_EVIDENCE_NONCE_TTL_SECONDS",
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
    "EvidenceContext",
    "GateResult",
    "GateVerdict",
    "PermitIssuer",
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
