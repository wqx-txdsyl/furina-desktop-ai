"""Phase 16D — ApprovalGate：四层交集（two-layer invariant）的唯一判定器。

effective permission = WorkContract scope ∩ PermissionManager L0–L3 ∩ explicit
approval ∩ backend capability；**任何一层都不得放宽另一层**，判定顺序固定：

1. WorkContract scope：tool→capability ∈ 契约 allowed_capabilities，全部路径 ∈
   契约 workspace（越契约的 "inner request" 在工具执行**之前**类型化拒绝，且
   不产生任何审批请求）；
2. backend capability：capability ∈ backend 显式能力集合；
3. PermissionManager L0–L3：``pm_decision.granted`` 必须为 True（审批放行无法覆盖
   PM 拒绝）；
4. explicit approval：按契约 approval_policy —— session grant（必须**严格窄于**
   契约，否则 DENY_GRANT_SCOPE fail-closed）或审批决议（approve_once 恰好消费
   一次 / approve_session）放行；deny / timeout / revoke / cancel → 类型化拒绝。

gate **只判定，永不执行工具**；拒绝 / 等待一律返回 :class:`GateResult`
（verdict / detail / approval / grant / consumed），调用方仅在 ``ALLOW`` 时
调用 ``tool.run`` —— 拒绝 / 超时 / 撤销 / 取消即零 tool call。

无状态：capability_snapshot（tool→capability，与 Native 冻结快照同形）与
ApprovalBroker 构造注入；审批请求由 gate 经 broker 创建（producer 面），
决议由 owner（canonical USER 决策入口）在 broker 上完成。
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from furina.agent.agent_runtime import AgentRuntime
from furina.agent.permission import Permission, PermissionDecision
from furina.agent.work_contract import WorkspaceScope

from .broker import ApprovalBroker
from .models import ApprovalRequest, ApprovalState, ApprovalStateError, AuthorizationGrant

__all__ = ["ApprovalGate", "GateResult", "GateVerdict"]


class GateVerdict(str, enum.Enum):
    """gate 判定结果（ALLOW 之外均为类型化拒绝，零 tool call）。"""

    ALLOW = "allow"
    APPROVAL_PENDING = "approval_pending"            # 审批请求已发出，等待用户决议
    DENY_PERMISSION = "deny_permission"              # PermissionManager L0–L3 未授权
    DENY_CONTRACT_SCOPE = "deny_contract_scope"      # inner request 越出契约 scope
    DENY_CAPABILITY = "deny_capability"              # backend 能力不符
    DENY_APPROVAL = "deny_approval"                  # 审批被拒 / pre_approved 无覆盖 grant
    DENY_TIMEOUT = "deny_timeout"                    # 审批超时（fail-closed）
    DENY_REVOKED = "deny_revoked"                    # 审批被撤销
    DENY_CANCELLED = "deny_cancelled"                # 等待被取消（解阻，零 tool call）
    DENY_GRANT_SCOPE = "deny_grant_scope"            # grant 比契约宽（fail-closed）
    DENY_GRANT_INACTIVE = "deny_grant_inactive"      # 匹配 grant 已过期/已撤销
    DENY_ALREADY_CONSUMED = "deny_already_consumed"  # approve_once 已被消费


@dataclass(frozen=True)
class GateResult:
    """四层判定结果。verdict=ALLOW 是调用方执行 tool.run 的唯一条件。"""

    verdict: GateVerdict
    detail: str
    approval: Optional[ApprovalRequest] = None
    grant: Optional[AuthorizationGrant] = None
    consumed: bool = False


class ApprovalGate:
    """四层交集判定器（无状态；capability_snapshot / broker 构造注入）。"""

    def __init__(self, *, capability_snapshot: Mapping[str, str], broker: ApprovalBroker,
                 risk_threshold: Permission = Permission.L2_HIGH_RISK,
                 wait_cap_seconds: float = 300.0) -> None:
        if not isinstance(capability_snapshot, Mapping):
            raise TypeError("capability_snapshot 必须是 tool→capability Mapping")
        if not isinstance(broker, ApprovalBroker):
            raise TypeError("broker 必须是 ApprovalBroker")
        if isinstance(risk_threshold, bool) or not isinstance(risk_threshold, Permission):
            raise TypeError("risk_threshold 必须是 Permission")
        if (isinstance(wait_cap_seconds, bool) or not isinstance(wait_cap_seconds, (int, float))
                or not math.isfinite(float(wait_cap_seconds)) or wait_cap_seconds <= 0):
            raise ApprovalStateError(f"wait_cap_seconds 必须有限正数，得到 {wait_cap_seconds!r}")
        self._snapshot = dict(capability_snapshot)
        self._broker = broker
        self._risk_threshold = risk_threshold
        self._wait_cap = float(wait_cap_seconds)

    # -------------------------------------------------- 四层判定
    def check_step(self, *, tool: str, args: Optional[Mapping[str, Any]],
                   contract_projection: Mapping[str, Any], pm_decision: PermissionDecision,
                   backend_capability_ids: Tuple[str, ...], run_id: str = "",
                   risk_level: Optional[Permission] = None, wait_for_approval: bool = True,
                   request_timeout_seconds: Optional[float] = None) -> GateResult:
        """在工具执行**之前**判定四层交集；ALLOW 才允许调用 tool.run。"""
        now = self._broker.now()
        # ---- 契约事实（无法准确表达 → fail-closed）----
        try:
            allowed_caps = frozenset(contract_projection.get("allowed_capabilities") or ())
            ws_raw = contract_projection.get("workspace_scope") or {}
            ws = WorkspaceScope(
                read_roots=tuple(ws_raw.get("read_roots") or ()),
                write_roots=tuple(ws_raw.get("write_roots") or ()),
            )
            policy = contract_projection.get("approval_policy") or {}
            policy_kind = policy.get("policy_kind") if isinstance(policy, Mapping) else None
            contract_id = contract_projection.get("contract_id") or ""
        except Exception as exc:
            return GateResult(GateVerdict.DENY_CONTRACT_SCOPE,
                              f"契约投影无法解析（fail-closed）: {exc}")
        if not allowed_caps:
            return GateResult(GateVerdict.DENY_CONTRACT_SCOPE, "契约 allowed_capabilities 为空")

        # ---- 1. WorkContract scope（越契约的 inner request → 工具执行前拒绝，零请求）----
        cap = self._snapshot.get(tool)
        if cap is None:
            return GateResult(GateVerdict.DENY_CONTRACT_SCOPE,
                              f"tool '{tool}' 无法归属任何 capability")
        if cap not in allowed_caps:
            return GateResult(GateVerdict.DENY_CONTRACT_SCOPE,
                              f"tool '{tool}' 的 capability '{cap}' 超出契约 {sorted(allowed_caps)}")
        args = dict(args or {})
        paths = tuple(AgentRuntime._step_paths(tool, args))
        for p in paths:
            if not ws.contains_path(p):
                return GateResult(GateVerdict.DENY_CONTRACT_SCOPE,
                                  f"路径越出契约 workspace: {p!r}")

        # ---- 2. backend capability ----
        if not isinstance(backend_capability_ids, (tuple, list, set, frozenset)):
            return GateResult(GateVerdict.DENY_CAPABILITY, "backend_capability_ids 必须是集合")
        if cap not in set(backend_capability_ids):
            return GateResult(GateVerdict.DENY_CAPABILITY,
                              f"capability '{cap}' 不在 backend 能力 {sorted(backend_capability_ids)} 内")

        # ---- 3. PermissionManager L0–L3（审批不得覆盖 PM 拒绝）----
        if not isinstance(pm_decision, PermissionDecision):
            return GateResult(GateVerdict.DENY_PERMISSION, "pm_decision 必须是 PermissionDecision")
        if not pm_decision.granted:
            return GateResult(GateVerdict.DENY_PERMISSION,
                              f"PermissionManager 未授权: {pm_decision.reason or 'denied'}")

        # ---- 4. explicit approval ----
        risk = risk_level if isinstance(risk_level, Permission) else pm_decision.level
        eff_risk = risk if risk is not None else Permission.L1_LOW_WRITE

        # 4a. session grant（必须严格窄于契约，否则 fail-closed）
        grant = self._broker.covering_grant(tool=tool, capability=cap, paths=paths, now=now)
        if grant is not None:
            if not self._grant_within_contract(grant, allowed_caps, ws):
                return GateResult(
                    GateVerdict.DENY_GRANT_SCOPE,
                    f"grant '{grant.grant_id}' 比契约宽（capability/workspace 越界，fail-closed）")
            return GateResult(GateVerdict.ALLOW, "session grant 覆盖", grant=grant)
        if self._broker.matching_grants(tool=tool, capability=cap, paths=paths):
            return GateResult(GateVerdict.DENY_GRANT_INACTIVE, "匹配 grant 已过期或已撤销")

        # 4b. 是否需要审批（按契约 approval_policy）
        required, why = self._approval_required(policy_kind, eff_risk)
        if required is False:
            return GateResult(GateVerdict.ALLOW, f"无需审批（{why}）")
        if required is None:
            return GateResult(GateVerdict.DENY_APPROVAL, why)

        # 4c. 复用同一步既有请求（终态即重判；避免拒绝后新建请求）
        req = self._broker.matching_request(
            contract_id=contract_id, run_id=run_id, tool=tool, requested_scope=paths)
        if req is None:
            window = self._wait_cap if request_timeout_seconds is None else float(request_timeout_seconds)
            if (isinstance(window, bool) or not isinstance(window, (int, float))
                    or not math.isfinite(float(window)) or window <= 0):
                raise ApprovalStateError(f"request_timeout_seconds 必须有限正数，得到 {request_timeout_seconds!r}")
            req = self._broker.create_request(
                contract_id=contract_id, run_id=run_id, tool=tool, capability=cap,
                args=args, reason=why, risk_level=eff_risk, requested_scope=paths,
                expires_at=now + window, provenance="executor",
                policy_kind=policy_kind or "approval_required_each_step")
        st = self._broker.state_of(req.approval_id)
        if st == ApprovalState.PENDING:
            if not wait_for_approval:
                return GateResult(GateVerdict.APPROVAL_PENDING, "等待用户决议（异步通道）",
                                  approval=req)
            self._broker.wait_for_resolution(req.approval_id,
                                             timeout=max(0.0, req.expires_at - now))
        return self._verdict_for(req)

    # -------------------------------------------------- 判定映射
    def _verdict_for(self, request: ApprovalRequest) -> GateResult:
        st = self._broker.state_of(request.approval_id)
        if st == ApprovalState.APPROVED_ONCE:
            if self._broker.consume(request.approval_id):
                return GateResult(GateVerdict.ALLOW, "approve_once 消费放行",
                                  approval=request, consumed=True)
            return GateResult(GateVerdict.DENY_ALREADY_CONSUMED,
                              "approve_once 已被消费（exactly once）", approval=request)
        if st == ApprovalState.APPROVED_SESSION:
            return GateResult(GateVerdict.ALLOW, "approve_session 放行", approval=request)
        if st == ApprovalState.DENIED:
            return GateResult(GateVerdict.DENY_APPROVAL, "审批被拒", approval=request)
        if st == ApprovalState.TIMED_OUT:
            return GateResult(GateVerdict.DENY_TIMEOUT, "审批超时（fail-closed）", approval=request)
        if st == ApprovalState.REVOKED:
            return GateResult(GateVerdict.DENY_REVOKED, "审批被撤销", approval=request)
        if st == ApprovalState.CANCELLED:
            return GateResult(GateVerdict.DENY_CANCELLED, "等待被取消（解阻，零 tool call）",
                              approval=request)
        return GateResult(GateVerdict.DENY_TIMEOUT,
                          "观察窗口耗尽未见决议（fail-closed）", approval=request)

    def _approval_required(self, policy_kind: Optional[str],
                           risk: Permission) -> Tuple[Optional[bool], str]:
        """返回 (True 需审批 / False 无需 / None 无法确定→fail-closed, 原因)。"""
        if policy_kind == "approval_required_each_step":
            return True, "契约要求逐步审批"
        if policy_kind == "approval_required_on_risk_level":
            if risk.value >= self._risk_threshold.value:
                return True, f"风险等级 {risk.name} ≥ 阈值 {self._risk_threshold.name}（需审批）"
            return False, f"风险等级 {risk.name} < 阈值 {self._risk_threshold.name}（L0/L1 语义保留）"
        if policy_kind == "pre_approved_scoped":
            return None, "pre_approved_scoped 无覆盖 grant（fail-closed 拒绝）"
        return None, f"policy_kind 无法识别 {policy_kind!r}（fail-closed）"

    @staticmethod
    def _grant_within_contract(grant: AuthorizationGrant, allowed_caps: frozenset,
                               ws: WorkspaceScope) -> bool:
        """grant 必须严格窄于契约：capability ∈ allowed_caps；workspace ⊆ 契约 workspace。"""
        if grant.capability not in allowed_caps:
            return False
        gws = grant.workspace_scope
        for root in gws.read_roots:
            if not ws.contains_path(root):
                return False
        for root in gws.write_roots:
            if not ws.contains_path(root, writable=True):
                return False
        return True
