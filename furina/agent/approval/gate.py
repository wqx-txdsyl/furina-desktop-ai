"""Phase 16D — ApprovalGate：四层交集（two-layer invariant）的唯一判定器。

effective permission = WorkContract scope ∩ PermissionManager L0–L3 ∩ explicit
approval ∩ backend capability；**任何一层都不得放宽另一层**，判定顺序固定：

1. WorkContract scope：只接受**经 16A 完整 content_hash 校验**的 WorkContract /
   transport 投影（``WorkContract.from_dict`` 全量 exact-mapping + 摘要复核；
   任意手拼 projection 字段一律 DENY_CONTRACT_SCOPE，零 tool call、零请求）。
   tool→capability ∈ 契约 allowed_capabilities；全部路径 ∈ 契约 workspace，
   **写目标必须落入 write_roots（read_roots 不授予写权限）**——越契约的
   "inner request" 在工具执行**之前**类型化拒绝，且不产生任何审批请求；
2. backend capability：capability ∈ backend 显式能力集合；
3. PermissionManager L0–L3：``pm_decision.granted`` 必须为 True（审批放行无法覆盖
   PM 拒绝）；**risk 以可信 PM 结果为下界**——effective risk = max(调用方声明,
   pm_decision.level)，调用方不得降级；L2/L3 一律必须审批；无任何风险信号时
   fail-closed 要求审批；
4. explicit approval：按契约 approval_policy —— session grant（必须**严格窄于**
   契约，且写目标落入 grant write_roots，否则 DENY_GRANT_SCOPE fail-closed）或
   审批决议（approve_once 经 permit 在真实工具边界恰好消费一次 /
   approve_session）放行；deny / timeout / revoke / cancel → 类型化拒绝。

gate **只判定，永不执行工具**；ALLOW 一律携带 :class:`ToolPermit`，调用方必须在
真实工具边界 ``broker.consume_permit(permit)`` **原子消费/复核**成功后才调用
``tool.run``——拒绝 / 超时 / 撤销 / 取消 / 消费失败即零 tool call（ALLOW 与
tool.run 之间的撤销 TOCTOU 被封闭）。

无状态：capability_snapshot（tool→capability，与 Native 冻结快照同形）与
ApprovalBroker 构造注入；审批请求由 gate 经 broker **原子 get-or-create**
（完整审批身份：contract hash / capability / tool / scope / risk / policy /
规范化参数摘要——不同操作不得复用），决议由 owner（canonical USER 决策入口，
构造期绑定）在 broker 上完成。
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple, Union

from furina.agent.agent_runtime import AgentRuntime
from furina.agent.permission import Permission, PermissionDecision
from furina.agent.work_contract import WorkContract, WorkContractValidationError, WorkspaceScope

from .broker import ApprovalBroker
from .models import (
    ApprovalRequest,
    ApprovalState,
    ApprovalStateError,
    ToolPermit,
    AuthorizationGrant,
    canonical_args_digest,
    classify_step_paths,
    redact_args,
    sanitize_text,
)

__all__ = ["ApprovalGate", "GateResult", "GateVerdict"]


class GateVerdict(str, enum.Enum):
    """gate 判定结果（ALLOW 之外均为类型化拒绝，零 tool call）。"""

    ALLOW = "allow"
    APPROVAL_PENDING = "approval_pending"            # 审批请求已发出，等待用户决议
    DENY_PERMISSION = "deny_permission"              # PermissionManager L0–L3 未授权
    DENY_CONTRACT_SCOPE = "deny_contract_scope"      # 契约未通过 16A hash 校验 / scope 越界
    DENY_CAPABILITY = "deny_capability"              # backend 能力不符
    DENY_APPROVAL = "deny_approval"                  # 审批被拒 / pre_approved 无覆盖 grant
    DENY_TIMEOUT = "deny_timeout"                    # 审批超时（fail-closed）
    DENY_REVOKED = "deny_revoked"                    # 审批被撤销
    DENY_CANCELLED = "deny_cancelled"                # 等待被取消（解阻，零 tool call）
    DENY_GRANT_SCOPE = "deny_grant_scope"            # grant 比契约宽（fail-closed）
    DENY_GRANT_INACTIVE = "deny_grant_inactive"      # 匹配 grant 已过期/已撤销/未生效
    DENY_ALREADY_CONSUMED = "deny_already_consumed"  # approve_once 已被消费


@dataclass(frozen=True)
class GateResult:
    """四层判定结果。verdict=ALLOW 且 ``consume_permit(permit)`` 成功是调用方执行
    tool.run 的唯一条件（permit 在真实工具边界原子消费/复核）。"""

    verdict: GateVerdict
    detail: str
    approval: Optional[ApprovalRequest] = None
    grant: Optional[AuthorizationGrant] = None
    permit: Optional[ToolPermit] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", sanitize_text(self.detail))


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

    # -------------------------------------------------- 契约信任基座（16A hash 校验）
    @staticmethod
    def _verified_contract(contract: Union[WorkContract, Mapping[str, Any]]) -> WorkContract:
        """只接受经 16A 完整 content_hash 校验的契约。

        - :class:`WorkContract` 实例：构造/from_dict/from_transport_json 已验证摘要；
        - Mapping 投影：强制走 ``WorkContract.from_dict``（exact-mapping + schema
          marker + content_hash 存在且与内容一致，**从不重新签名**）——手拼/篡改的
          projection 字段在此被拒绝。任何失败抛 :class:`WorkContractValidationError`
          （调用方 fail-closed 折为 DENY_CONTRACT_SCOPE）。
        """
        if isinstance(contract, WorkContract):
            return contract
        if isinstance(contract, Mapping):
            return WorkContract.from_dict(dict(contract))
        raise WorkContractValidationError(
            f"gate 只接受 WorkContract 或可经 from_dict 完整 hash 校验的投影，"
            f"得到 {type(contract).__name__}")

    # -------------------------------------------------- 四层判定
    def check_step(self, *, tool: str, args: Optional[Mapping[str, Any]],
                   contract: Union[WorkContract, Mapping[str, Any]],
                   pm_decision: PermissionDecision,
                   backend_capability_ids: Tuple[str, ...], run_id: str = "",
                   risk_level: Optional[Permission] = None, wait_for_approval: bool = True,
                   request_timeout_seconds: Optional[float] = None) -> GateResult:
        """在工具执行**之前**判定四层交集；ALLOW 携带 permit（工具边界原子消费）。"""
        now = self._broker.now()
        # ---- 契约事实（必须通过 16A 完整 hash 校验；失败 → fail-closed）----
        try:
            verified = self._verified_contract(contract)
        except (WorkContractValidationError, TypeError, ValueError, KeyError) as exc:
            return GateResult(
                GateVerdict.DENY_CONTRACT_SCOPE,
                f"契约未通过 16A 完整 hash 校验（不信任任意 projection 字段）: {exc}")
        allowed_caps = frozenset(verified.allowed_capabilities)
        ws = verified.workspace_scope
        policy_kind = verified.approval_policy.policy_kind
        contract_id = verified.contract_id
        contract_hash = verified.content_hash

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
        # 写目标分类（保守 fail-closed：非只读白名单工具的全部路径均按写目标校验）
        write_paths, _read_paths = classify_step_paths(tool, paths)
        for p in paths:
            if not ws.contains_path(p):
                return GateResult(GateVerdict.DENY_CONTRACT_SCOPE,
                                  f"路径越出契约 workspace: {p!r}")
        for p in write_paths:
            if not ws.contains_path(p, writable=True):
                return GateResult(
                    GateVerdict.DENY_CONTRACT_SCOPE,
                    f"写目标 '{p}' 不在契约 write_roots 内（read_roots 不授予写权限）")

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
        # risk 以可信 PM 结果为下界：effective = max(caller, PM)；调用方不得降级。
        pm_level = pm_decision.level if isinstance(pm_decision.level, Permission) else None
        caller_risk = risk_level if isinstance(risk_level, Permission) else None
        signals = [s for s in (pm_level, caller_risk) if s is not None]
        if signals:
            eff_risk = max(signals)   # int enum：取更高级别（不可降级）
        else:
            eff_risk = None           # 无任何风险信号 → 无法证明低风险 → fail-closed

        # 4a. session grant（必须严格窄于契约，否则 fail-closed；写目标须入 grant write_roots）
        grant = self._broker.covering_grant(tool=tool, capability=cap, paths=paths,
                                            write_paths=write_paths, now=now)
        if grant is not None:
            if not self._grant_within_contract(grant, allowed_caps, ws):
                return GateResult(
                    GateVerdict.DENY_GRANT_SCOPE,
                    f"grant '{grant.grant_id}' 比契约宽（capability/workspace 越界，fail-closed）")
            permit = self._broker.issue_permit(
                tool=tool, capability=cap,
                args_digest=canonical_args_digest(redact_args(args)),
                grant_id=grant.grant_id)
            return GateResult(GateVerdict.ALLOW, "session grant 覆盖", grant=grant, permit=permit)
        if self._broker.matching_grants(tool=tool, capability=cap, paths=paths,
                                        write_paths=write_paths):
            return GateResult(GateVerdict.DENY_GRANT_INACTIVE,
                              "匹配 grant 已过期/已撤销/未生效（issued_at <= now < expiry 不满足）"
                              "或写目标越出 grant write_roots")

        # 4b. 是否需要审批（risk 下界 + L2/L3 硬性必须审批）
        required, why = self._approval_required(policy_kind, eff_risk)
        if required is False:
            permit = self._broker.issue_permit(
                tool=tool, capability=cap,
                args_digest=canonical_args_digest(redact_args(args)))
            return GateResult(GateVerdict.ALLOW, f"无需审批（{why}）", permit=permit)
        if required is None:
            return GateResult(GateVerdict.DENY_APPROVAL, why)

        # 4c. 原子 get-or-create：并发同一步（完整审批身份）只产生一个请求；
        #     完整身份 = contract hash + capability + tool + scope + risk + policy + args 摘要
        args_digest = canonical_args_digest(redact_args(args))
        req, _created = self._broker.get_or_create_request(
            contract_id=contract_id, contract_hash=contract_hash, run_id=run_id,
            tool=tool, capability=cap, args=args, reason=why, risk_level=eff_risk,
            requested_scope=paths, provenance="executor", policy_kind=policy_kind,
            expires_at=self._request_expiry(now, request_timeout_seconds),
        )
        st = self._broker.state_of(req.approval_id)
        if st == ApprovalState.PENDING:
            if not wait_for_approval:
                return GateResult(GateVerdict.APPROVAL_PENDING, "等待用户决议（异步通道）",
                                  approval=req)
            self._broker.wait_for_resolution(req.approval_id,
                                             timeout=max(0.0, req.expires_at - now))
        return self._verdict_for(req, tool=tool, capability=cap, args_digest=args_digest)

    def _request_expiry(self, now: float, request_timeout_seconds: Optional[float]) -> float:
        window = self._wait_cap if request_timeout_seconds is None else float(request_timeout_seconds)
        if (isinstance(request_timeout_seconds, bool)
                or not isinstance(window, (int, float))
                or not math.isfinite(float(window)) or window <= 0):
            raise ApprovalStateError(
                f"request_timeout_seconds 必须有限正数，得到 {request_timeout_seconds!r}")
        return now + window

    # -------------------------------------------------- 判定映射
    def _verdict_for(self, request: ApprovalRequest, *, tool: str, capability: str,
                     args_digest: str) -> GateResult:
        """终态映射；ALLOW 一律签发 permit（approve_once 的消费移至工具边界原子完成）。"""
        st = self._broker.state_of(request.approval_id)
        if st == ApprovalState.APPROVED_ONCE:
            if self._broker.is_consumed(request.approval_id):
                return GateResult(GateVerdict.DENY_ALREADY_CONSUMED,
                                  "approve_once 已被消费（exactly once）", approval=request)
            permit = self._broker.issue_permit(
                tool=tool, capability=capability, args_digest=args_digest,
                approval_id=request.approval_id)
            return GateResult(GateVerdict.ALLOW, "approve_once 放行（permit 于工具边界消费）",
                              approval=request, permit=permit)
        if st == ApprovalState.APPROVED_SESSION:
            permit = self._broker.issue_permit(
                tool=tool, capability=capability, args_digest=args_digest,
                approval_id=request.approval_id)
            return GateResult(GateVerdict.ALLOW, "approve_session 放行", approval=request,
                              permit=permit)
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
                           risk: Optional[Permission]) -> Tuple[Optional[bool], str]:
        """返回 (True 需审批 / False 无需 / None 无法确定→fail-closed, 原因)。

        - **L2/L3 硬性必须审批**（无论 policy_kind / risk_threshold 如何设置）；
        - 无任何风险信号（PM level 与调用方均未给出）→ 无法证明低于阈值 →
          fail-closed 要求审批。
        """
        if risk is None:
            return None, "无风险信号（PM level 与调用方声明均缺失）→ 无法证明低风险（fail-closed）"
        if risk.value >= Permission.L2_HIGH_RISK.value:
            return True, f"风险等级 {risk.name} ≥ L2（可信 PM 结果为下界，硬性必须审批）"
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
        """grant 必须严格窄于契约：capability ∈ allowed_caps；workspace ⊆ 契约 workspace
        （write_roots 以可写语义校验——read_roots 不授予写权限）。"""
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
