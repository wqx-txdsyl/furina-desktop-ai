# -*- coding: utf-8 -*-
"""Phase 16B — ExecutionBackend protocol & registry 测试。

任务书 §7 十二项最低锁定：
1. duplicate backend IDs rejected
2. installed-but-unhealthy is not routable
3. stale health is not treated as healthy
4. required capability mismatch produces zero submit
5. explicit allowed backend constraint cannot be widened
6. deterministic tie-break repeatability
7. Persona/relationship changes do not affect technical routing
8. backend exception is fail-soft typed failure, not another backend's silent execution
9. Native adapter preserves existing result semantics
10. registry snapshots are immutable/caller-safe
11. no install/uninstall side effects
12. Phase 15 cognition/store contracts unchanged（回归套件执行 + 导入面无 DB 依赖守卫）
"""
from __future__ import annotations

import inspect
import subprocess
import sys
import time
from pathlib import Path

import pytest

from furina.agent import AgentRuntime, PermissionManager, ToolRegistry
from furina.agent.backend import (
    PROTOCOL_VERSION,
    BackendCapabilities,
    BackendCapabilityError,
    BackendDescriptor,
    BackendError,
    BackendHealth,
    BackendRegistrationError,
    BackendRunHandle,
    BackendUnknownError,
    ExecutionBackend,
    ExecutionBackendRegistry,
    NativeAgentRuntimeBackend,
    RoutingPolicy,
    TechnicalRouter,
)
from furina.agent.planner import AgentPlan, AgentStep, Planner
from furina.agent.tools import ALL_TOOLS
from furina.agent.work_contract import (
    ApprovalPolicyRef,
    CostBudget,
    ExecutionBudget,
    VerificationCriterion,
    VerificationStandard,
    WorkContract,
    WorkspaceScope,
)
from furina.core import EventBus

REPO_ROOT = Path(__file__).resolve().parents[3]


# ================================================================ 契约构造
def _contract(workspace_root: Path, **overrides):
    work = workspace_root / "work"
    kw = dict(
        contract_id="wc_16b_test_001",
        contract_version="1.0.0",
        canonical_user_request="把下载目录里的文件按类型整理到分类目录",
        objective="在 write_root 内完成整理并可通过判据校验",
        commitment_scope_included=("整理下载文件",),
        allowed_capabilities=("cap.filesystem",),
        allowed_backends=("native",),
        workspace_scope=WorkspaceScope(
            read_roots=(str(workspace_root / "docs"),),
            write_roots=(str(work),),
        ),
        budget=ExecutionBudget(
            max_duration_seconds=600.0,
            cost_limit=CostBudget(amount=5.0, currency="CNY"),
            max_attempts=3,
        ),
        verification_standard=VerificationStandard(
            criteria=(
                VerificationCriterion(
                    criterion_id="out_exists",
                    kind="artifact_file_exists",
                    params={"path": str(work / "out.md")},
                ),
            ),
        ),
        approval_policy=ApprovalPolicyRef(
            policy_id="policy_scoped_v1",
            policy_kind="pre_approved_scoped",
            scope_note="仅限 write_root 内写入",
        ),
        source_event_id="lev_1756000000000_deadbeef",
    )
    kw.update(overrides)
    return WorkContract(**kw)


# ================================================================ 假 backend（spy + 可配置）
_UNSET = object()


class _FakeBackend(ExecutionBackend):
    """可配置健康/能力/异常/返回值的可 spy backend（注册不是执行：probe_calls 由显式 probe 驱动）。"""

    def __init__(self, backend_id, *, capability_ids=("cap.filesystem",),
                 supports_events=False, supports_stop=False, supports_resolve_approval=False,
                 max_cost_limit=None, max_duration_seconds=None, workspace_scoped=True,
                 probe_health=None, submit_error=None, submit_return=_UNSET,
                 protocol_version=PROTOCOL_VERSION):
        self._descriptor = BackendDescriptor(backend_id=backend_id, display_name=f"fake:{backend_id}",
                                             protocol_version=protocol_version)
        self._caps = BackendCapabilities(
            capability_ids=capability_ids,
            supports_events=supports_events, supports_stop=supports_stop,
            supports_resolve_approval=supports_resolve_approval,
            max_cost_limit=max_cost_limit, max_duration_seconds=max_duration_seconds,
            workspace_scoped=workspace_scoped,
        )
        self._probe_health = probe_health
        self._submit_error = submit_error
        self._submit_return = submit_return
        self.probe_calls = 0
        self.submit_calls = 0

    @property
    def descriptor(self):
        return self._descriptor

    @property
    def capabilities(self):
        return self._caps

    def probe(self):
        self.probe_calls += 1
        if self._probe_health is not None:
            return self._probe_health
        now = time.time()
        return BackendHealth(installed=True, reachable=True, healthy=True,
                             checked_at=now, reason="", expiry=now + 3600)

    def submit(self, projection, *, run_id=None):
        self.submit_calls += 1
        if self._submit_error is not None:
            raise self._submit_error
        if self._submit_return is not _UNSET:
            return self._submit_return
        return BackendRunHandle(self._descriptor.backend_id, f"run_{self.submit_calls}",
                                projection.get("contract_id", ""))


class _BrokenMetadataBackend(ExecutionBackend):
    """descriptor/capabilities 读取即抛 AttributeError 的坏实现（不得泄漏给 register 调用方）。"""

    @property
    def descriptor(self):
        raise AttributeError("broken descriptor")

    @property
    def capabilities(self):
        raise AttributeError("broken capabilities")

    def probe(self):  # pragma: no cover - 注册即拒，不会走到
        raise AssertionError("unreachable")

    def submit(self, projection, *, run_id=None):  # pragma: no cover
        raise AssertionError("unreachable")


def _ready(registry, backend):
    """注册 + 显式 probe（注册不是执行：两步分开，与 router 的只读消费一致）。"""
    registry.register(backend)
    registry.probe(backend.descriptor.backend_id)
    return backend


def _fresh_health(*, healthy=True, installed=True, reachable=True, expiry_delta=3600.0,
                  reason=""):
    now = time.time()
    return BackendHealth(installed=installed, reachable=reachable, healthy=healthy,
                         checked_at=now, reason=reason, expiry=now + expiry_delta)


# ================================================================ 1. duplicate backend IDs rejected
def test_01_duplicate_backend_id_rejected():
    reg = ExecutionBackendRegistry()
    b1 = _FakeBackend("dup_backend")
    reg.register(b1)
    with pytest.raises(BackendRegistrationError):
        reg.register(_FakeBackend("dup_backend"))       # 同 id 不同实例
    with pytest.raises(BackendRegistrationError):
        reg.register(b1)                                 # 同 id 同实例
    with pytest.raises(BackendRegistrationError):
        reg.register(object())                           # 非 ExecutionBackend


# ================================================================ 2. installed-but-unhealthy is not routable
def test_02_installed_but_unhealthy_not_routable(tmp_path):
    reg = ExecutionBackendRegistry()
    backend = _FakeBackend("native",
                           probe_health=_fresh_health(healthy=False, reason="probe_failed"))
    _ready(reg, backend)
    router = TechnicalRouter(reg)
    contract = _contract(tmp_path, allowed_backends=("native",))
    dec = router.route(contract)
    assert not dec.ok and dec.refusal_code == "no_compatible_backend"
    assert "unhealthy" in dec.refusal_detail
    # 未 probe 的已注册 backend 同样不可路由（registration != healthy，fail-closed）
    reg2 = ExecutionBackendRegistry()
    reg2.register(_FakeBackend("native"))
    dec2 = TechnicalRouter(reg2).route(_contract(tmp_path, allowed_backends=("native",)))
    assert not dec2.ok and "not_probed" in dec2.refusal_detail


# ================================================================ 3. stale health is not treated as healthy
def test_03_stale_health_not_routable(tmp_path):
    now = time.time()
    stale = BackendHealth(installed=True, reachable=True, healthy=True,
                          checked_at=now - 120.0, reason="", expiry=now - 60.0)
    assert stale.is_stale() and not stale.is_effective()
    reg = ExecutionBackendRegistry()
    backend = _FakeBackend("native", probe_health=stale)
    _ready(reg, backend)
    dec = TechnicalRouter(reg).route(_contract(tmp_path, allowed_backends=("native",)))
    assert not dec.ok and "stale_health" in dec.refusal_detail


# ================================================================ 4. required capability mismatch produces zero submit
def test_04_capability_mismatch_zero_submit(tmp_path):
    reg = ExecutionBackendRegistry()
    backend = _FakeBackend("native", capability_ids=("cap.filesystem",))
    _ready(reg, backend)
    router = TechnicalRouter(reg)
    contract = _contract(tmp_path, allowed_backends=("native",),
                         allowed_capabilities=("cap.documents", "cap.communication"))
    dec = router.route(contract)
    assert not dec.ok and "capability_mismatch" in dec.refusal_detail
    out = router.dispatch(contract)
    assert not out.ok and out.decision.refusal_code == "no_compatible_backend"
    assert backend.submit_calls == 0, "能力不匹配 → 零 submit"


# ================================================================ 5. explicit allowed backend constraint cannot be widened
def test_05_allowed_backend_constraint_not_widened(tmp_path):
    reg = ExecutionBackendRegistry()
    b1 = _ready(reg, _FakeBackend("b1"))
    b2 = _ready(reg, _FakeBackend("b2"))
    # 契约只允许 b1；策略偏好/允许集里有 b2 → 仍必须只考虑 b1（策略不得放宽契约）
    router = TechnicalRouter(reg, RoutingPolicy(preferred_backend_ids=("b2",),
                                                allow_backends=("b1", "b2")))
    dec = router.route(_contract(tmp_path, allowed_backends=("b1",)))
    assert dec.ok and dec.backend_id == "b1"
    # 契约只允许 b1 且 b1 不健康；b2 健康 → 拒绝而不是静默落到契约外的 b2
    reg2 = ExecutionBackendRegistry()
    _ready(reg2, _FakeBackend("b1", probe_health=_fresh_health(healthy=False, reason="down")))
    b2h = _ready(reg2, _FakeBackend("b2"))
    dec2 = TechnicalRouter(reg2).route(_contract(tmp_path, allowed_backends=("b1",)))
    assert not dec2.ok and b2h.submit_calls == 0 and dec2.candidates == ("b1",)
    # 策略允许集只能收窄：契约允许 b1+b2，策略只允许 b1 → 选 b1
    dec3 = TechnicalRouter(reg, RoutingPolicy(allow_backends=("b1",))).route(
        _contract(tmp_path, allowed_backends=("b1", "b2")))
    assert dec3.ok and dec3.backend_id == "b1"


# ================================================================ 6. deterministic tie-break repeatability
def test_06_deterministic_tie_break(tmp_path):
    reg = ExecutionBackendRegistry()
    _ready(reg, _FakeBackend("b1"))
    _ready(reg, _FakeBackend("b2"))
    _ready(reg, _FakeBackend("b0"))
    contract = _contract(tmp_path, allowed_backends=("b1", "b2", "b0"))
    # 显式偏好顺序：多次路由结果完全一致
    router = TechnicalRouter(reg, RoutingPolicy(preferred_backend_ids=("b2", "b0")))
    first = router.route(contract)
    assert first.ok and first.backend_id == "b2"
    for _ in range(5):
        assert router.route(contract).backend_id == "b2"
    # 无偏好 → backend_id 字典序兜底（b0 < b1 < b2），同样可重复
    router2 = TechnicalRouter(reg)
    assert router2.route(contract).backend_id == "b0"
    assert all(router2.route(contract).backend_id == "b0" for _ in range(5))
    # 候选顺序也是确定性的
    assert router2.route(contract).candidates == ("b0", "b1", "b2")


# ================================================================ 7. Persona/relationship changes do not affect routing
def test_07_persona_relationship_do_not_affect_routing(tmp_path):
    reg = ExecutionBackendRegistry()
    _ready(reg, _FakeBackend("b1"))
    _ready(reg, _FakeBackend("b2"))
    router = TechnicalRouter(reg, RoutingPolicy(preferred_backend_ids=("b2",)))
    # 路由相关字段完全一致；仅 canonical request / objective 文本带 persona/情绪色彩
    neutral = _contract(tmp_path, contract_id="wc_16b_neutral_01",
                        allowed_backends=("b1", "b2"),
                        canonical_user_request="把下载目录里的文件按类型整理到分类目录",
                        objective="在 write_root 内完成整理并可通过判据校验")
    persona = _contract(tmp_path, contract_id="wc_16b_persona_02",
                        allowed_backends=("b1", "b2"),
                        canonical_user_request="芙宁娜今天心情很好，想帮我把下载目录里的文件整理一下",
                        objective="芙宁娜很乐意整理文件，用户很信任她，希望按类型分类")
    d1, d2 = router.route(neutral), router.route(persona)
    assert d1.ok and d2.ok and d1.backend_id == d2.backend_id == "b2"
    # 路由输入面结构保证：route 只接受 contract，没有任何 persona/emotion/relationship 参数
    params = list(inspect.signature(TechnicalRouter.route).parameters)
    assert params == ["self", "contract"]


# ================================================================ 8. backend exception -> fail-soft typed failure, no silent fallback
def test_08_submit_exception_failsoft_no_fallback(tmp_path):
    reg = ExecutionBackendRegistry()
    b1 = _ready(reg, _FakeBackend("b1", submit_error=RuntimeError("boom")))
    b2 = _ready(reg, _FakeBackend("b2"))
    router = TechnicalRouter(reg, RoutingPolicy(preferred_backend_ids=("b1",)))
    contract = _contract(tmp_path, allowed_backends=("b1", "b2"))
    out = router.dispatch(contract)
    assert not out.ok
    assert out.failure_code == "submit_error"
    assert "RuntimeError" in out.failure_detail
    assert b1.submit_calls == 1
    assert b2.submit_calls == 0, "submit 异常绝不静默换到另一个 backend"


# ================================================================ 9. Native adapter preserves existing result semantics
def _make_runtime(planner_steps, extra_tools=None):
    bus = EventBus()
    tools = ToolRegistry()
    for c in ALL_TOOLS:
        tools.register(c())
    for t in extra_tools or []:
        tools.register(t)
    perm = PermissionManager()   # 生产默认：on_confirm=None → L2/L3 拒绝（不削弱权限）
    records = []
    agent = AgentRuntime(bus, tools, perm,
                         planner_factory=lambda t: _FixedPlanner(t, planner_steps),
                         task_history=lambda rec: records.append(rec))
    return tools, agent, records


class _FixedPlanner(Planner):
    def __init__(self, tools, steps):
        super().__init__(tools)
        self._steps = steps

    def build_plan(self, user_request, context=None):
        return AgentPlan(goal=user_request, steps=self._steps)


def test_09_native_adapter_preserves_completed_semantics(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    steps = [AgentStep(tool="doc.create",
                       args={"path": str(work / "hello.md"), "content": "Hello Furina"})]
    tools, agent, records = _make_runtime(steps)
    from furina.agent.capabilities import build_capability_registry
    capreg = build_capability_registry(tools)
    backend = NativeAgentRuntimeBackend(agent, capability_registry=capreg)
    assert "cap.documents" in backend.capabilities.capability_ids  # 派生自 available 能力
    health = backend.probe()
    assert health.installed and health.reachable and health.healthy

    reg = ExecutionBackendRegistry()
    _ready(reg, backend)
    router = TechnicalRouter(reg)
    contract = _contract(tmp_path, allowed_backends=("native",),
                         allowed_capabilities=("cap.documents", "cap.filesystem"))
    out = router.dispatch(contract)
    assert out.ok, out.decision
    handle = out.handle
    assert handle.backend_id == "native" and handle.correlation == contract.contract_id
    result = backend.last_result(handle.run_id)
    assert result["status"] == "completed"
    assert result["task_id"] == handle.run_id, "run_id = AgentRuntime stable task_id"
    rec = result["task_record"]
    assert rec["status"] == "COMPLETED_VERIFIED" and rec["verified"] is True
    assert (work / "hello.md").read_text(encoding="utf-8") == "Hello Furina"
    assert records and records[-1]["status"] == "COMPLETED_VERIFIED", "task_record 回调原样保留"


def test_09b_native_adapter_preserves_permission_semantics(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    # fs.organize 是 L2：默认任务上下文（L0/L1）必须拒绝 —— adapter 不得伪造授权
    steps = [AgentStep(tool="fs.organize", args={"base": str(work), "dry_run": True})]
    tools, agent, records = _make_runtime(steps)
    from furina.agent.capabilities import build_capability_registry
    backend = NativeAgentRuntimeBackend(agent,
                                        capability_registry=build_capability_registry(tools))
    reg = ExecutionBackendRegistry()
    _ready(reg, backend)
    contract = _contract(tmp_path, allowed_backends=("native",))
    out = TechnicalRouter(reg).dispatch(contract)
    assert out.ok, "路由与 submit 本身成功（L2 否决发生在 AgentRuntime 权限层）"
    result = backend.last_result(out.handle.run_id)
    assert result["status"] == "failed"
    assert result["reason"] == "permission_denied"
    assert result["task_record"]["status"] == "FAILED"
    # 能力门控：Native 未声明 events/stop/resolve_approval → 全部类型化拒绝
    with pytest.raises(BackendCapabilityError):
        backend.events(out.handle)
    with pytest.raises(BackendCapabilityError):
        backend.stop(out.handle)
    with pytest.raises(BackendCapabilityError):
        backend.resolve_approval("policy_scoped_v1")


# ================================================================ 10. registry snapshots are immutable/caller-safe
def test_10_registry_snapshot_immutable_caller_safe(tmp_path):
    reg = ExecutionBackendRegistry()
    b1 = _FakeBackend("b1")
    reg.register(b1)
    snap = reg.snapshot()
    with pytest.raises(TypeError):
        snap["evil"] = b1                      # MappingProxyType 拒绝写入
    snap2 = dict(snap)                          # 调用方复制后乱改也不影响 registry
    snap2.clear()
    assert reg.get("b1") is b1
    reg.register(_FakeBackend("b2"))            # 后续注册不影响旧快照
    assert set(snap) == {"b1"} and len(snap) == 1
    assert reg.list_ids() == ("b1", "b2")
    hs = reg.health_snapshot()
    with pytest.raises(TypeError):
        hs["x"] = 1


# ================================================================ 11. no install/uninstall side effects
def test_11_no_install_uninstall_side_effects():
    reg = ExecutionBackendRegistry()
    for name in ("install", "uninstall", "upgrade", "remove"):
        assert not hasattr(reg, name), f"registry 不得暴露 {name}（安装/卸载是禁止面）"
    backend = _FakeBackend("b1")
    reg.register(backend)
    assert backend.probe_calls == 0 and backend.submit_calls == 0, "注册不是执行（零副作用）"
    assert reg.health_of("b1") is None, "注册不建立健康事实（fail-closed）"


def test_11b_backend_package_imports_no_cognition_db(tmp_path):
    """导入 backend 包不得拉入 furina.cognition（无 DB/schema 依赖）。"""
    code = ("import sys; import furina.agent.backend; "
            "sys.exit(1 if 'furina.cognition' in sys.modules else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"backend 包导入不应依赖 furina.cognition: {r.stderr}"


# ================================================================ 额外：健康/拒绝零 submit / 确定性细节
def test_extra_no_registered_backend_typed_refusal(tmp_path):
    reg = ExecutionBackendRegistry()
    router = TechnicalRouter(reg)
    dec = router.route(_contract(tmp_path, allowed_backends=("ghost", "hermes")))
    assert not dec.ok and dec.refusal_code == "no_registered_backend"
    out = router.dispatch(_contract(tmp_path, allowed_backends=("ghost",)))
    assert not out.ok and out.failure_code == "" and out.handle is None


def test_extra_policy_narrows_and_preference_does_not_bypass_contract(tmp_path):
    reg = ExecutionBackendRegistry()
    b1 = _ready(reg, _FakeBackend("b1"))
    b2 = _ready(reg, _FakeBackend("b2"))
    # 策略偏好指向契约外的 b2 → 仍选契约内的 b1（偏好不越过契约约束）
    router = TechnicalRouter(reg, RoutingPolicy(preferred_backend_ids=("b2",)))
    dec = router.route(_contract(tmp_path, allowed_backends=("b1",)))
    assert dec.ok and dec.backend_id == "b1" and b2.submit_calls == 0


def test_extra_budget_and_workspace_incompatibility(tmp_path):
    reg = ExecutionBackendRegistry()
    _ready(reg, _FakeBackend("budget_backend", max_cost_limit=1.0))
    _ready(reg, _FakeBackend("ws_backend", workspace_scoped=False))
    contract_budget = _contract(tmp_path, allowed_backends=("budget_backend",))
    dec = TechnicalRouter(reg).route(contract_budget)
    assert not dec.ok and "budget_incompatible" in dec.refusal_detail
    contract_ws = _contract(tmp_path, allowed_backends=("ws_backend",))
    dec2 = TechnicalRouter(reg).route(contract_ws)
    assert not dec2.ok and "workspace_incompatible" in dec2.refusal_detail


# ================================================================ Reviewer Patch 1 否证测试
def _native_backend(tools, agent, steps=None, extra_tools=None):
    from furina.agent.capabilities import build_capability_registry
    capreg = build_capability_registry(tools)
    backend = NativeAgentRuntimeBackend(agent, capability_registry=capreg)
    reg = ExecutionBackendRegistry()
    _ready(reg, backend)
    return backend, TechnicalRouter(reg)


def test_p1_02b_out_of_scope_path_fail_closed(tmp_path):
    """写路径越出 workspace write root → submit 前 fail-closed，零执行（文件不存在）。"""
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    steps = [AgentStep(tool="doc.create",
                       args={"path": str(outside / "evil.md"), "content": "x"})]
    tools, agent, _ = _make_runtime(steps)
    backend, router = _native_backend(tools, agent)
    contract = _contract(tmp_path, allowed_backends=("native",),
                         allowed_capabilities=("cap.documents", "cap.filesystem"))
    out = router.dispatch(contract)
    assert not out.ok and out.failure_code == "scope_violation"
    assert "越界" in out.failure_detail and "write" in out.failure_detail
    assert not (outside / "evil.md").exists(), "越界路径绝不执行"
    assert backend.last_result("") is None  # 无任何 run 产生
    # 只读工具读越界同样拒绝（read scope）
    steps2 = [AgentStep(tool="fs.read_file", args={"path": str(outside / "secret.txt")})]
    tools2, agent2, _ = _make_runtime(steps2)
    _, router2 = _native_backend(tools2, agent2)
    out2 = router2.dispatch(_contract(tmp_path, allowed_backends=("native",),
                                      allowed_capabilities=("cap.filesystem",)))
    assert not out2.ok and out2.failure_code == "scope_violation" and "read" in out2.failure_detail


def test_p1_02c_over_permission_capability_fail_closed(tmp_path):
    """计划使用契约 allowed_capabilities 之外的 capability 工具 → submit 前 fail-closed。"""
    work = tmp_path / "work"
    work.mkdir()
    steps = [AgentStep(tool="doc.create",
                       args={"path": str(work / "a.md"), "content": "x"})]
    tools, agent, _ = _make_runtime(steps)
    _, router = _native_backend(tools, agent)
    contract = _contract(tmp_path, allowed_backends=("native",),
                         allowed_capabilities=("cap.filesystem",))  # 不含 cap.documents
    out = router.dispatch(contract)
    assert not out.ok and out.failure_code == "scope_violation"
    assert "越权 capability" in out.failure_detail
    assert not (work / "a.md").exists()
    # 工具无法归属任何 capability → scope 无法准确表达 → fail-closed
    from furina.agent.tool import BaseTool

    class _OrphanTool(BaseTool):
        name = "custom.gadget"
        description = "无 capability 归属的工具"

    tools2, agent2, _ = _make_runtime(
        [AgentStep(tool="custom.gadget", args={})], extra_tools=[_OrphanTool()])
    _, router2 = _native_backend(tools2, agent2)
    out2 = router2.dispatch(_contract(tmp_path, allowed_backends=("native",),
                                      allowed_capabilities=("cap.filesystem",)))
    assert not out2.ok and out2.failure_code == "scope_violation"
    assert "无法归属" in out2.failure_detail


def test_p1_02d_legal_scope_positive(tmp_path):
    """合法范围正例：工具 ∈ allowed_capabilities 且路径 ∈ workspace → submit 成功。"""
    work = tmp_path / "work"
    work.mkdir()
    steps = [AgentStep(tool="doc.create",
                       args={"path": str(work / "ok.md"), "content": "Hello"})]
    tools, agent, records = _make_runtime(steps)
    backend, router = _native_backend(tools, agent)
    contract = _contract(tmp_path, allowed_backends=("native",),
                         allowed_capabilities=("cap.documents",))
    out = router.dispatch(contract)
    assert out.ok, out.decision
    result = backend.last_result(out.handle.run_id)
    assert result["status"] == "completed"
    assert (work / "ok.md").read_text(encoding="utf-8") == "Hello"
    assert records and records[-1]["status"] == "COMPLETED_VERIFIED"


def test_p1_04b_native_capabilities_real(tmp_path):
    """Native 能力声明必须真实：未实现的能力一律 False；TTL 必须有限正数。"""
    tools, agent, _ = _make_runtime([])
    from furina.agent.capabilities import build_capability_registry
    capreg = build_capability_registry(tools)
    backend = NativeAgentRuntimeBackend(agent, capability_registry=capreg)
    caps = backend.capabilities
    assert caps.supports_events is False
    assert caps.supports_stop is False
    assert caps.supports_resolve_approval is False
    assert caps.workspace_scoped is True, "真正执行 scope → 才可为 true"
    # capability_ids 恰为 available 能力派生（无虚假声明）
    expected = tuple(sorted(c.capability_id for c in capreg.all() if c.available))
    assert caps.capability_ids == expected
    with pytest.raises(BackendCapabilityError):
        backend.events(BackendRunHandle("native", "r", ""))
    with pytest.raises(BackendCapabilityError):
        backend.stop(BackendRunHandle("native", "r", ""))
    with pytest.raises(BackendCapabilityError):
        backend.resolve_approval("x")
    # probe TTL 必须有限正数
    for bad in (0, -5, True, float("nan"), float("inf")):
        with pytest.raises(BackendError):
            NativeAgentRuntimeBackend(agent, capability_registry=capreg,
                                      probe_ttl_seconds=bad)


def test_p1_04c_fake_runtime_rejected(tmp_path):
    """假 runtime / 缺失或伪 capability_registry → 构造即类型化拒绝。"""
    from furina.agent.capabilities import build_capability_registry
    tools, agent, _ = _make_runtime([])
    capreg = build_capability_registry(tools)
    with pytest.raises(BackendError, match="runtime"):
        NativeAgentRuntimeBackend(object(), capability_registry=capreg)   # 假 runtime
    with pytest.raises(BackendError, match="runtime"):
        NativeAgentRuntimeBackend(None, capability_registry=capreg)
    with pytest.raises(BackendError, match="capability_registry"):
        NativeAgentRuntimeBackend(agent, capability_registry=None)        # 缺 scope 依据
    with pytest.raises(BackendError, match="capability_registry"):
        NativeAgentRuntimeBackend(agent, capability_registry=object())    # 伪 registry


def test_p1_03b_capability_strict_validation():
    """BackendCapabilities：bool 不得充当 int；NaN/Inf/非正上限一律拒绝。"""
    with pytest.raises(BackendError):
        BackendCapabilities(max_concurrent_runs=True)          # bool 冒充 int
    with pytest.raises(BackendError):
        BackendCapabilities(max_concurrent_runs=0)
    for bad in (float("nan"), float("inf"), 0, -1.0, True):
        with pytest.raises(BackendError):
            BackendCapabilities(max_cost_limit=bad)
        with pytest.raises(BackendError):
            BackendCapabilities(max_duration_seconds=bad)


def test_p1_03c_health_strict_validation():
    """BackendHealth：时间必须有限且时序合法；到达 expiry 即 stale。"""
    now = time.time()
    with pytest.raises(BackendError):
        BackendHealth(installed=True, reachable=True, healthy=True,
                      checked_at=float("nan"), expiry=now + 10)
    with pytest.raises(BackendError):
        BackendHealth(installed=True, reachable=True, healthy=True,
                      checked_at=now, expiry=float("inf"))
    with pytest.raises(BackendError):
        BackendHealth(installed=True, reachable=True, healthy=True,
                      checked_at=now + 100, expiry=now)         # 时序非法
    with pytest.raises(BackendError):
        BackendHealth(installed=True, reachable=True, healthy=True,
                      checked_at=True, expiry=now + 10)         # bool 冒充数值
    # 到达 expiry 即 stale（== expiry 边界）
    boundary = BackendHealth(installed=True, reachable=True, healthy=True,
                             checked_at=now - 10, expiry=now)
    assert boundary.is_stale(now) and not boundary.is_effective(now)
    # healthy=True 必须 installed ∧ reachable
    with pytest.raises(BackendError):
        BackendHealth(installed=False, reachable=True, healthy=True,
                      checked_at=now, expiry=now + 10)


def test_p1_04d_protocol_mismatch_rejected():
    """protocol_version 不兼容 → 注册类型化拒绝（不进入 registry）。"""
    reg = ExecutionBackendRegistry()
    with pytest.raises(BackendRegistrationError, match="protocol_version"):
        reg.register(_FakeBackend("legacy_backend", protocol_version="9.9.9"))
    assert "legacy_backend" not in reg


def test_p1_04e_set_health_type_checked():
    """set_health 只接受 BackendHealth；未知 backend → BackendUnknownError。"""
    reg = ExecutionBackendRegistry()
    _ready(reg, _FakeBackend("b1"))
    _ready_health = reg.health_of("b1")
    with pytest.raises(BackendRegistrationError, match="BackendHealth"):
        reg.set_health("b1", {"healthy": True})
    with pytest.raises(BackendRegistrationError, match="BackendHealth"):
        reg.set_health("b1", None)
    with pytest.raises(BackendUnknownError):
        reg.set_health("ghost", _fresh_health())
    # 坏健康值不得进入/覆盖路由输入面：probe 建立的既有健康事实原样保留
    assert reg.health_of("b1") is _ready_health


def test_p1_04f_bad_metadata_no_attr_leak():
    """坏 descriptor/capabilities 实现 → 注册折为 BackendRegistrationError，不泄漏 AttributeError。"""
    reg = ExecutionBackendRegistry()
    with pytest.raises(BackendRegistrationError):
        reg.register(_BrokenMetadataBackend())
    assert len(reg) == 0


def test_p1_05b_dispatch_invalid_handle_zero_fallback(tmp_path):
    """submit 返回 None / 错 backend handle → 类型化失败，零 fallback。"""
    contract = _contract(tmp_path, allowed_backends=("b1", "b2"))
    reg = ExecutionBackendRegistry()
    b1 = _ready(reg, _FakeBackend("b1", submit_return=None))
    b2 = _ready(reg, _FakeBackend("b2"))
    router = TechnicalRouter(reg, RoutingPolicy(preferred_backend_ids=("b1",)))
    out = router.dispatch(contract)
    assert not out.ok and out.failure_code == "invalid_run_handle"
    assert "BackendRunHandle" in out.failure_detail
    assert b1.submit_calls == 1 and b2.submit_calls == 0, "非法返回零 fallback"
    # 错 backend_id 的 handle
    reg2 = ExecutionBackendRegistry()
    wrong = _ready(reg2, _FakeBackend("b1",
                                      submit_return=BackendRunHandle("b2", "run_x", "")))
    b2b = _ready(reg2, _FakeBackend("b2"))
    router2 = TechnicalRouter(reg2, RoutingPolicy(preferred_backend_ids=("b1",)))
    out2 = router2.dispatch(contract)
    assert not out2.ok and out2.failure_code == "run_handle_backend_mismatch"
    assert wrong.submit_calls == 1 and b2b.submit_calls == 0
