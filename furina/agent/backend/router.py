"""Phase 16B — 确定性技术 router（受 WorkContract 约束；backend-neutral）。

路由只允许使用（任务书 §4）：
1. WorkContract 中的显式 user/backend 约束（``allowed_backends``）；
2. 允许 backend 集合（registry 已注册集 ∩ 技术策略 allow_backends，**只收窄不放宽**）；
3. 必需能力（``allowed_capabilities`` ⊆ backend 显式能力集合）；
4. 当前未过期健康（registry 缓存的 BackendHealth.effective；未 probe → fail-closed）；
5. permission/workspace/budget 兼容（workspace_scoped + 显式预算上限；approval 归 16D）；
6. 技术策略配置的确定性 tie-break（preferred 顺序 + backend_id 字典序兜底）。

**禁止**：Persona / 情绪 / 关系 / willingness / intimacy / LLM 一律不得进入路由输入面。
无兼容 backend → 类型化机制级拒绝（RouteDecision.refusal_*），**零 submit 调用**。

``dispatch()`` 是唯一 submit 路径：先 route，拒绝则绝不 submit；submit 抛异常 →
fail-soft 类型化失败（failure_code="submit_error"），**绝不静默换到另一个 backend**。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from furina.agent.work_contract import WorkContract

from .models import BackendRunHandle
from .protocol import ExecutionBackend
from .registry import ExecutionBackendRegistry

#: 候选否决原因（机器可读；detail 按确定性顺序拼接）。
_CAPABILITY_MISMATCH = "capability_mismatch"
_NOT_PROBED = "not_probed"
_STALE_HEALTH = "stale_health"
_UNHEALTHY = "unhealthy"
_WORKSPACE_INCOMPATIBLE = "workspace_incompatible"
_BUDGET_INCOMPATIBLE = "budget_incompatible"


@dataclass(frozen=True)
class RoutingPolicy:
    """技术策略（确定性 tie-break 与系统级允许集；只收窄，不越权）。"""

    #: 确定性偏好顺序（technical policy 配置；未列出的 backend 排在末尾按 id 字典序）。
    preferred_backend_ids: Tuple[str, ...] = ()
    #: 系统级允许集（空 = 不额外限制）；与契约 allowed_backends 取交集，**绝不放宽契约**。
    allow_backends: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        prefs = []
        for v in self.preferred_backend_ids:
            if not isinstance(v, str) or not v.strip():
                raise ValueError("preferred_backend_ids 条目必须是非空 str")
            prefs.append(v.strip())
        if len(prefs) != len(set(prefs)):
            raise ValueError("preferred_backend_ids 存在重复条目")
        object.__setattr__(self, "preferred_backend_ids", tuple(prefs))
        allow = []
        for v in self.allow_backends:
            if not isinstance(v, str) or not v.strip():
                raise ValueError("allow_backends 条目必须是非空 str")
            allow.append(v.strip())
        object.__setattr__(self, "allow_backends", tuple(sorted(set(allow))))


@dataclass(frozen=True)
class RouteDecision:
    """路由结果：选中 backend（ok=True）或类型化机制级拒绝（ok=False，零 submit）。"""

    ok: bool
    backend_id: str = ""
    refusal_code: str = ""
    refusal_detail: str = ""
    #: 按确定性顺序考虑过的候选 id（诊断用；拒绝时非空）。
    candidates: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchResult:
    """dispatch 结果：run handle（ok=True）或类型化失败（拒绝 / submit 异常）。

    - 拒绝：``decision.ok=False``，零 submit；
    - submit 异常：``failure_code="submit_error"``，**不 fallback 到其他 backend**。
    """

    ok: bool
    decision: RouteDecision
    handle: Optional[BackendRunHandle] = None
    failure_code: str = ""
    failure_detail: str = ""


class TechnicalRouter:
    """确定性技术路由（无 LLM / 无主观输入；WorkContract 是唯一路由输入面）。"""

    def __init__(self, registry: ExecutionBackendRegistry,
                 policy: Optional[RoutingPolicy] = None) -> None:
        if not isinstance(registry, ExecutionBackendRegistry):
            raise TypeError("TechnicalRouter 需要 ExecutionBackendRegistry")
        self.registry = registry
        self.policy = policy or RoutingPolicy()

    # -- 候选确定性排序 ---------------------------------------------------------
    def _ordered_candidates(self, contract_allowed: Tuple[str, ...]) -> Tuple[str, ...]:
        """候选顺序：契约允许 ∩ registry；preferred 顺序优先，其余按 backend_id 字典序。"""
        prefs = {bid: i for i, bid in enumerate(self.policy.preferred_backend_ids)}
        fallback = len(self.policy.preferred_backend_ids)
        registered = set(self.registry.list_ids())
        # 契约显式约束先行：绝不容许契约外 backend 进入候选（不可被策略放宽）。
        allowed = [bid for bid in contract_allowed if bid in registered]
        # 系统级允许集只收窄（交集）。
        if self.policy.allow_backends:
            allowed = [bid for bid in allowed if bid in set(self.policy.allow_backends)]
        return tuple(sorted(allowed, key=lambda bid: (prefs.get(bid, fallback), bid)))

    # -- 单候选否决 -------------------------------------------------------------
    def _candidate_refusal(self, backend: ExecutionBackend, contract: WorkContract) -> Optional[str]:
        """返回首个否决原因（None = 通过全部机制门）。确定性顺序固定。"""
        caps = backend.capabilities
        if not caps.satisfies(contract.allowed_capabilities):
            return _CAPABILITY_MISMATCH
        health = self.registry.health_of(backend.descriptor.backend_id)
        if health is None:
            return _NOT_PROBED
        if health.is_stale():
            return _STALE_HEALTH
        if not health.is_effective():
            return _UNHEALTHY
        ws = contract.workspace_scope
        if (ws.read_roots or ws.write_roots) and not caps.workspace_scoped:
            return _WORKSPACE_INCOMPATIBLE
        if (caps.max_cost_limit is not None
                and contract.budget.cost_limit.amount > caps.max_cost_limit):
            return _BUDGET_INCOMPATIBLE
        if (caps.max_duration_seconds is not None
                and contract.budget.max_duration_seconds > caps.max_duration_seconds):
            return _BUDGET_INCOMPATIBLE
        return None

    # -- 路由 -------------------------------------------------------------------
    def route(self, contract: WorkContract) -> RouteDecision:
        """确定性选 backend；无兼容 → 类型化拒绝（调用方/submit 侧零 submit 保证在 dispatch）。"""
        contract_allowed = tuple(contract.allowed_backends)
        candidates = self._ordered_candidates(contract_allowed)
        reasons: Dict[str, str] = {}
        for bid in candidates:
            backend = self.registry.get_required(bid)
            reason = self._candidate_refusal(backend, contract)
            if reason is None:
                return RouteDecision(ok=True, backend_id=bid, candidates=candidates)
            reasons[bid] = reason
        # 类型化机制级拒绝
        detail_parts = []
        unknown = [bid for bid in contract_allowed if bid not in self.registry]
        if unknown:
            detail_parts.append(f"未注册: {','.join(unknown)}")
        policy_blocked = [bid for bid in contract_allowed
                          if bid in self.registry and self.policy.allow_backends
                          and bid not in set(self.policy.allow_backends)]
        if policy_blocked:
            detail_parts.append(f"策略收窄拒绝: {','.join(policy_blocked)}")
        for bid in candidates:
            detail_parts.append(f"{bid}:{reasons[bid]}")
        if not candidates and unknown:
            code = "no_registered_backend"
        else:
            code = "no_compatible_backend"
        return RouteDecision(ok=False, refusal_code=code,
                             refusal_detail="; ".join(detail_parts),
                             candidates=candidates)

    # -- 唯一 submit 路径 ---------------------------------------------------------
    def dispatch(self, contract: WorkContract) -> DispatchResult:
        """route → submit。拒绝 → 零 submit；submit 异常 → fail-soft 类型化失败，不 fallback。"""
        decision = self.route(contract)
        if not decision.ok:
            return DispatchResult(ok=False, decision=decision)
        backend = self.registry.get_required(decision.backend_id)
        try:
            handle = backend.submit(contract.to_backend_projection())
        except Exception as exc:  # fail-soft：类型化失败，绝不静默换 backend
            return DispatchResult(
                ok=False, decision=decision,
                failure_code="submit_error",
                failure_detail=f"{type(exc).__name__}: {exc}")
        return DispatchResult(ok=True, decision=decision, handle=handle)
