# -*- coding: utf-8 -*-
"""Phase 16D — Permission & Approval Boundary 测试。

任务书 §7 十二项最低锁定：
1. L0/L1 existing semantics preserved
2. L2/L3 cannot run without the required existing authorization and new approval
3. inner request broader than contract denied before tool execution
4. approve-once consumed exactly once
5. duplicate/conflicting/late resolution idempotent
6. timeout denies and emits one terminal approval event
7. canonical user provenance required for durable/session grant
8. grant scope/expiry/revocation enforced
9. backend cannot synthesize permanent grant
10. cancellation while waiting unblocks and never executes tool
11. secrets/arguments redacted in user-visible/audit payloads
12. existing PermissionManager regression and C1–C7 unchanged

额外锁定：two-layer invariant（任何一层不得放宽另一层）、owner 线程变更守卫、
approve_session 多次放行与撤销。
"""
from __future__ import annotations

import dataclasses
import json
import threading
import time
from typing import Any, Dict, Optional, Tuple

import pytest

from furina.agent.approval import (
    ApprovalBroker,
    ApprovalDecisionKind,
    ApprovalGate,
    ApprovalState,
    ApprovalStateError,
    AuthorizationGrant,
    GateVerdict,
    ResolutionStatus,
)
from furina.agent.permission import Permission, PermissionDecision, PermissionManager
from furina.agent.work_contract import (
    ApprovalPolicyRef,
    CostBudget,
    ExecutionBudget,
    VerificationCriterion,
    VerificationStandard,
    WorkContract,
    WorkspaceScope,
)

#: 测试用 tool→capability 快照（与 Native 冻结快照同形）。
_SNAPSHOT = {
    "fs.read_file": "cap.filesystem",
    "fs.write_text": "cap.filesystem",
    "fs.move": "cap.filesystem",
    "fs.delete": "cap.filesystem",
    "doc.create": "cap.documents",
    "doc.write": "cap.documents",
}


class FakeClock:
    """可推进时钟（timeout / expiry 测试确定性推进）。"""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._t = float(start)

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _projection(*, allowed_capabilities: Tuple[str, ...] = ("cap.filesystem",),
                policy_kind: str = "approval_required_each_step",
                read_roots: Tuple[str, ...] = ("C:/ws/docs",),
                write_roots: Tuple[str, ...] = ("C:/ws/work",),
                contract_id: str = "wc_16d_test", **kw) -> Dict[str, Any]:
    ws = WorkspaceScope(read_roots=tuple(read_roots), write_roots=tuple(write_roots))
    contract = WorkContract(
        contract_id=contract_id, contract_version="1.0.0",
        canonical_user_request="测试请求", objective="测试目标",
        commitment_scope_included=("测试",),
        allowed_capabilities=tuple(allowed_capabilities),
        allowed_backends=("native",),
        workspace_scope=ws,
        budget=ExecutionBudget(
            max_duration_seconds=600.0,
            cost_limit=CostBudget(amount=5.0, currency="CNY"),
            max_attempts=3,
        ),
        verification_standard=VerificationStandard(
            criteria=(
                VerificationCriterion(
                    criterion_id="c01", kind="artifact_file_exists",
                    params={"path": str(write_roots[0]) + "/out.md"}),
            ),
        ),
        approval_policy=ApprovalPolicyRef(policy_id="p1", policy_kind=policy_kind, scope_note="t"),
        source_event_id="lev_1756000000000_deadbeef",
        **kw,
    )
    return dict(contract.to_backend_projection())


def _grant_ws() -> WorkspaceScope:
    return WorkspaceScope(read_roots=("C:/ws/docs",), write_roots=("C:/ws/work",))


class _Harness:
    """工具边界模拟：gate 判定 ALLOW 才调用工具（tool_calls 计数 = 真实执行次数）。"""

    def __init__(self, gate: ApprovalGate) -> None:
        self.gate = gate
        self.tool_calls = 0

    def run_step(self, *, tool: str, args: Dict[str, Any], projection,
                 pm_decision: PermissionDecision, backend_capability_ids: Tuple[str, ...],
                 run_id: str = "run_1", wait_for_approval: bool = True, **kw):
        result = self.gate.check_step(
            tool=tool, args=args, contract_projection=projection, pm_decision=pm_decision,
            backend_capability_ids=backend_capability_ids, run_id=run_id,
            wait_for_approval=wait_for_approval, **kw)
        if result.verdict == GateVerdict.ALLOW:
            self.tool_calls += 1
        return result


# ================================================================ 1. L0/L1 语义保留
def test_01_l0_l1_existing_semantics_preserved():
    broker = ApprovalBroker()
    broker.bind_owner()
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker)
    proj = _projection(policy_kind="approval_required_on_risk_level")   # 阈值默认 L2
    caps = ("cap.filesystem",)
    # L0 只读：PM 自动放行 → ALLOW，无需任何新审批，不产生请求
    r = gate.check_step(tool="fs.read_file", args={"path": "C:/ws/docs/a.md"},
                        contract_projection=proj,
                        pm_decision=PermissionDecision(True, "auto", Permission.L0_READ),
                        backend_capability_ids=caps)
    assert r.verdict == GateVerdict.ALLOW
    assert broker.matching_request(contract_id="wc_16d_test", run_id="", tool="fs.read_file",
                                   requested_scope=("C:/ws/docs/a.md",)) is None
    # L1 低风险写入：显式任务授权放行 → ALLOW（无需新审批）
    r2 = gate.check_step(tool="fs.write_text", args={"path": "C:/ws/work/out.md", "content": "x"},
                         contract_projection=proj,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         backend_capability_ids=caps)
    assert r2.verdict == GateVerdict.ALLOW
    # PM 拒绝时 gate 绝不放行（PM 未被 16D 削弱）
    r3 = gate.check_step(tool="fs.read_file", args={"path": "C:/ws/docs/a.md"},
                         contract_projection=proj,
                         pm_decision=PermissionDecision(False, "no-authorization",
                                                        Permission.L0_READ),
                         backend_capability_ids=caps)
    assert r3.verdict == GateVerdict.DENY_PERMISSION


# ================================================================ 2. L2/L3 需要既有授权 + 新审批
def test_02_l2_l3_require_existing_authorization_and_new_approval():
    broker = ApprovalBroker()
    broker.bind_owner()
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker)
    proj = _projection(policy_kind="approval_required_each_step")
    caps = ("cap.filesystem",)
    kw = dict(tool="fs.delete", args={"path": "C:/ws/work/x"}, contract_projection=proj,
              backend_capability_ids=caps, run_id="run_2")
    # (a) 既有授权缺失（PM 拒绝）→ DENY_PERMISSION，不产生审批请求
    r = gate.check_step(pm_decision=PermissionDecision(False, "no-authorization",
                                                       Permission.L2_HIGH_RISK),
                        wait_for_approval=False, **kw)
    assert r.verdict == GateVerdict.DENY_PERMISSION and r.approval is None
    assert broker.events == []
    # (b) 既有授权在但无审批 → APPROVAL_PENDING（异步通道建立，等待用户决议）
    pm_ok = PermissionDecision(True, "task_authorization:t", Permission.L2_HIGH_RISK)
    r2 = gate.check_step(pm_decision=pm_ok, wait_for_approval=False, **kw)
    assert r2.verdict == GateVerdict.APPROVAL_PENDING and r2.approval is not None
    assert broker.state_of(r2.approval.approval_id) == ApprovalState.PENDING
    assert broker.events[0].etype == "approval.requested"
    # (c) deny → 类型化拒绝；重检同一请求（不新建），零 tool call
    broker.resolve(r2.approval.approval_id, ApprovalDecisionKind.DENY, reason="user 拒绝")
    r3 = gate.check_step(pm_decision=pm_ok, **kw)
    assert r3.verdict == GateVerdict.DENY_APPROVAL
    assert broker.matching_request(contract_id="wc_16d_test", run_id="run_2", tool="fs.delete",
                                   requested_scope=("C:/ws/work/x",)).approval_id == \
        r2.approval.approval_id
    # (d) approve_once → ALLOW 且只消费一次
    kw2 = dict(tool="fs.move", args={"path": "C:/ws/work/a", "dest": "C:/ws/work/b"},
               contract_projection=proj, backend_capability_ids=caps, run_id="run_2")
    r4 = gate.check_step(pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         wait_for_approval=False, **kw2)
    assert r4.verdict == GateVerdict.APPROVAL_PENDING
    broker.resolve(r4.approval.approval_id, ApprovalDecisionKind.APPROVE_ONCE, reason="user ok")
    r5 = gate.check_step(pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE), **kw2)
    assert r5.verdict == GateVerdict.ALLOW and r5.consumed


# ================================================================ 3. 越契约 inner request 工具执行前拒绝
def test_03_inner_request_broader_than_contract_denied_before_tool():
    broker = ApprovalBroker()
    broker.bind_owner()
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker)
    harness = _Harness(gate)
    # 契约只允许 cap.documents；fs.delete 属于 cap.filesystem → 越契约
    proj = _projection(policy_kind="approval_required_each_step",
                       allowed_capabilities=("cap.documents",))
    r = harness.run_step(tool="fs.delete", args={"path": "C:/ws/work/x"}, projection=proj,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L2_HIGH_RISK),
                         backend_capability_ids=("cap.filesystem",))
    assert r.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    assert harness.tool_calls == 0
    assert broker.events == [], "越契约的请求不得产生任何审批请求（工具执行前拒绝）"
    # 路径越出 workspace → 同样工具执行前拒绝
    proj2 = _projection(policy_kind="approval_required_each_step")
    r2 = harness.run_step(tool="fs.write_text", args={"path": "C:/outside/x.md", "content": "x"},
                          projection=proj2,
                          pm_decision=PermissionDecision(True, "task_authorization:t",
                                                         Permission.L1_LOW_WRITE),
                          backend_capability_ids=("cap.filesystem",))
    assert r2.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    assert harness.tool_calls == 0


# ================================================================ 4. approve_once 恰好消费一次
def test_04_approve_once_consumed_exactly_once():
    broker = ApprovalBroker()
    broker.bind_owner()
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker)
    harness = _Harness(gate)
    proj = _projection(policy_kind="approval_required_each_step")
    kw = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "hi"},
              projection=proj,
              pm_decision=PermissionDecision(True, "task_authorization:t",
                                             Permission.L1_LOW_WRITE),
              backend_capability_ids=("cap.filesystem",), run_id="run_1")
    r = harness.run_step(wait_for_approval=False, **kw)
    assert r.verdict == GateVerdict.APPROVAL_PENDING
    aid = r.approval.approval_id
    broker.resolve(aid, ApprovalDecisionKind.APPROVE_ONCE, reason="user ok")
    r2 = harness.run_step(**kw)
    assert r2.verdict == GateVerdict.ALLOW and r2.consumed
    assert r2.approval.approval_id == aid
    assert harness.tool_calls == 1
    assert broker.is_consumed(aid)
    # 同一 approve_once 第二次 → 已被消费 → 拒绝（不新建、不再执行）
    r3 = harness.run_step(**kw)
    assert r3.verdict == GateVerdict.DENY_ALREADY_CONSUMED
    assert harness.tool_calls == 1
    decided = [e for e in broker.events if e.etype == "approval.decided"
               and e.approval_id == aid]
    assert len(decided) == 1, "approve_once 决议只发生一次"


# ================================================================ 5. 重复/冲突/迟到决议类型化
def test_05_duplicate_conflicting_late_resolution_typed():
    clock = FakeClock()
    broker = ApprovalBroker(clock=clock)
    broker.bind_owner()
    mk = dict(contract_id="wc_1", capability="cap.filesystem", args={"path": "C:/ws/work/o.md"},
              requested_scope=("C:/ws/work/o.md",))
    # 重复（相同决议）→ DUPLICATE 幂等 no-op
    req1 = broker.create_request(run_id="run_1", tool="fs.write_text",
                                 risk_level=Permission.L1_LOW_WRITE,
                                 expires_at=clock() + 100, **mk)
    r1 = broker.resolve(req1.approval_id, ApprovalDecisionKind.APPROVE_ONCE)
    assert (r1.ok, r1.status) == (True, ResolutionStatus.RESOLVED)
    r1d = broker.resolve(req1.approval_id, ApprovalDecisionKind.APPROVE_ONCE)
    assert (r1d.ok, r1d.status) == (True, ResolutionStatus.DUPLICATE)
    # 冲突（不同决议）→ CONFLICT 类型化拒绝
    r1c = broker.resolve(req1.approval_id, ApprovalDecisionKind.DENY)
    assert (r1c.ok, r1c.status) == (False, ResolutionStatus.CONFLICT)
    # late：先超时再决议 → LATE 类型化拒绝
    req2 = broker.create_request(run_id="run_2", tool="fs.write_text",
                                 risk_level=Permission.L1_LOW_WRITE,
                                 expires_at=clock() + 10, **mk)
    clock.advance(11)
    assert broker.state_of(req2.approval_id) == ApprovalState.TIMED_OUT
    late = broker.resolve(req2.approval_id, ApprovalDecisionKind.DENY)
    assert (late.ok, late.status) == (False, ResolutionStatus.LATE)
    # unknown → UNKNOWN
    unk = broker.resolve("apv_000000000000", ApprovalDecisionKind.DENY)
    assert (unk.ok, unk.status) == (False, ResolutionStatus.UNKNOWN)


# ================================================================ 6. 超时拒绝 + 恰好一个终态事件
def test_06_timeout_denies_and_emits_one_terminal_event():
    clock = FakeClock()
    broker = ApprovalBroker(clock=clock)
    broker.bind_owner()
    req = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                capability="cap.filesystem", args={},
                                risk_level=Permission.L1_LOW_WRITE, requested_scope=(),
                                expires_at=clock() + 3)
    assert broker.state_of(req.approval_id) == ApprovalState.PENDING
    clock.advance(4)
    assert broker.state_of(req.approval_id) == ApprovalState.TIMED_OUT
    to_events = [e for e in broker.events if e.etype == "approval.timed_out"
                 and e.approval_id == req.approval_id]
    assert len(to_events) == 1, "超时只发一个终态事件"
    broker.sweep_timeouts()
    assert len([e for e in broker.events if e.etype == "approval.timed_out"]) == 1
    # gate 层（真实时钟短窗口）：超时 → DENY_TIMEOUT，零 tool call
    broker2 = ApprovalBroker()
    broker2.bind_owner()
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker2)
    harness = _Harness(gate)
    proj = _projection(policy_kind="approval_required_each_step")
    start = time.time()
    r = harness.run_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                         projection=proj,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         backend_capability_ids=("cap.filesystem",), run_id="run_t",
                         request_timeout_seconds=0.05)
    assert r.verdict == GateVerdict.DENY_TIMEOUT
    assert harness.tool_calls == 0
    assert time.time() - start < 5.0, "超时必须在有限时间内返回"


# ================================================================ 7. 持久/会话授权必须 canonical USER provenance
def test_07_canonical_user_provenance_required_for_grant():
    broker = ApprovalBroker()
    broker.bind_owner()
    ws = _grant_ws()
    for bad in ("llm_suggested", "backend_native", "inferred_intent", "adapter_default", ""):
        with pytest.raises(ApprovalStateError):
            broker.create_grant(user_event_id=bad, capability="cap.filesystem",
                                tool_pattern="fs.write_text", workspace_scope=ws,
                                expiry=broker.now() + 3600)
    g = broker.create_grant(user_event_id="lev_1756000000000_deadbeef",
                            capability="cap.filesystem", tool_pattern="fs.write_text",
                            workspace_scope=ws, expiry=broker.now() + 3600)
    assert g.grant_id.startswith("gr_")
    assert g.user_event_id == "lev_1756000000000_deadbeef"
    # 非 owner 线程（backend/executor 身份）不得创建授权
    non_owner = ApprovalBroker()
    non_owner.bind_owner(thread_id=0xDEAD)
    with pytest.raises(ApprovalStateError):
        non_owner.create_grant(user_event_id="lev_1756000000000_deadbeef",
                               capability="cap.filesystem", tool_pattern="fs.write_text",
                               workspace_scope=ws, expiry=non_owner.now() + 3600)
    # 未绑定 owner 也不得创建授权
    unbound = ApprovalBroker()
    with pytest.raises(ApprovalStateError):
        unbound.create_grant(user_event_id="lev_1756000000000_deadbeef",
                             capability="cap.filesystem", tool_pattern="fs.write_text",
                             workspace_scope=ws, expiry=unbound.now() + 3600)


# ================================================================ 8. grant scope/expiry/revocation enforced
def test_08_grant_scope_expiry_revocation_enforced():
    proj = _projection(policy_kind="pre_approved_scoped")
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    caps = ("cap.filesystem",)
    step = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                projection=proj, pm_decision=pm, backend_capability_ids=caps)
    step_gate = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                     contract_projection=proj, pm_decision=pm, backend_capability_ids=caps)
    ws = _grant_ws()

    # (a) 覆盖 → ALLOW（零审批请求）
    broker = ApprovalBroker()
    broker.bind_owner()
    harness = _Harness(ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker))
    grant = broker.create_grant(user_event_id="lev_1756000000000_deadbeef",
                                capability="cap.filesystem", tool_pattern="fs.write_text",
                                workspace_scope=ws, expiry=broker.now() + 3600)
    r = harness.run_step(**step)
    assert r.verdict == GateVerdict.ALLOW and r.grant is not None
    assert harness.tool_calls == 1

    # (b) grant scope 强制：写入点在 grant 更窄 write root 之外 → 不覆盖 → pre_approved 拒绝
    broker_b = ApprovalBroker()
    broker_b.bind_owner()
    harness_b = _Harness(ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker_b))
    ws_narrow = WorkspaceScope(read_roots=("C:/ws/docs",), write_roots=("C:/ws/work/sub",))
    broker_b.create_grant(user_event_id="lev_1756000000000_deadbeef",
                          capability="cap.filesystem", tool_pattern="fs.write_text",
                          workspace_scope=ws_narrow, expiry=broker_b.now() + 3600)
    r2 = harness_b.run_step(**step)
    assert r2.verdict == GateVerdict.DENY_APPROVAL
    assert harness_b.tool_calls == 0

    # (c) revocation：撤销后下一工具边界前拒绝（零新 tool call）
    broker_c = ApprovalBroker()
    broker_c.bind_owner()
    harness_c = _Harness(ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker_c))
    grant_c = broker_c.create_grant(user_event_id="lev_1756000000000_deadbeef",
                                    capability="cap.filesystem", tool_pattern="fs.write_text",
                                    workspace_scope=ws, expiry=broker_c.now() + 3600)
    assert harness_c.run_step(**step).verdict == GateVerdict.ALLOW
    assert harness_c.tool_calls == 1
    broker_c.revoke_grant(grant_c.grant_id, reason="user revoked")
    r3 = harness_c.run_step(**step)
    assert r3.verdict == GateVerdict.DENY_GRANT_INACTIVE
    assert harness_c.tool_calls == 1

    # (d) expiry：过期 grant 非激活 → DENY_GRANT_INACTIVE
    clock = FakeClock()
    broker_d = ApprovalBroker(clock=clock)
    broker_d.bind_owner()
    gate_d = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker_d)
    broker_d.create_grant(user_event_id="lev_1756000000000_deadbeef",
                          capability="cap.filesystem", tool_pattern="fs.write_text",
                          workspace_scope=ws, expiry=clock() + 10)
    clock.advance(11)
    r4 = gate_d.check_step(**step_gate)
    assert r4.verdict == GateVerdict.DENY_GRANT_INACTIVE

    # (e) grant 比契约宽（read root 越界）→ DENY_GRANT_SCOPE fail-closed
    broker_e = ApprovalBroker()
    broker_e.bind_owner()
    gate_e = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker_e)
    ws_broad = WorkspaceScope(read_roots=("C:/ws/docs", "C:/extra"),
                              write_roots=("C:/ws/work",))
    broker_e.create_grant(user_event_id="lev_1756000000000_deadbeef",
                          capability="cap.filesystem", tool_pattern="fs.write_text",
                          workspace_scope=ws_broad, expiry=broker_e.now() + 3600)
    r5 = gate_e.check_step(**step_gate)
    assert r5.verdict == GateVerdict.DENY_GRANT_SCOPE


# ================================================================ 9. backend 无法合成永久 grant
def test_09_backend_cannot_synthesize_permanent_grant():
    broker = ApprovalBroker()
    broker.bind_owner()
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker)
    proj = _projection(policy_kind="approval_required_each_step")
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    # gate 的审批路径（approve_once）绝不产生任何 grant
    r = gate.check_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                        contract_projection=proj, pm_decision=pm,
                        backend_capability_ids=("cap.filesystem",), run_id="r1",
                        wait_for_approval=False)
    assert r.verdict == GateVerdict.APPROVAL_PENDING
    broker.resolve(r.approval.approval_id, ApprovalDecisionKind.APPROVE_ONCE)
    assert broker.list_grants() == []
    # 模型层无永久语义字段
    names = {f.name for f in dataclasses.fields(AuthorizationGrant)}
    assert not ({"permanent", "always_allow", "approved_forever"} & names)
    # 无界时长拒绝（有界 grant，无永久）
    ws = _grant_ws()
    with pytest.raises(ApprovalStateError):
        broker.create_grant(user_event_id="lev_1756000000000_deadbeef",
                            capability="cap.filesystem", tool_pattern="fs.write_text",
                            workspace_scope=ws, expiry=broker.now() + 86400 * 366)
    # backend/LLM 文本无法作为决议来源（非 owner 决议 → ApprovalStateError）
    non_owner = ApprovalBroker()
    non_owner.bind_owner(thread_id=0xDEAD)
    with pytest.raises(ApprovalStateError):
        non_owner.resolve("apv_000000000000", ApprovalDecisionKind.APPROVE_SESSION)


# ================================================================ 10. 等待中取消 → 解阻且零 tool call
def test_10_cancellation_while_waiting_unblocks_and_no_tool():
    broker = ApprovalBroker()
    broker.bind_owner()          # main = owner（canonical USER 决策入口）
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker)
    proj = _projection(policy_kind="approval_required_each_step")
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    harness = _Harness(gate)
    box: Dict[str, Any] = {}

    def executor() -> None:
        box["result"] = harness.run_step(
            tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
            projection=proj, pm_decision=pm, backend_capability_ids=("cap.filesystem",),
            run_id="run_c")

    t = threading.Thread(target=executor, daemon=True)
    t.start()
    req = None
    deadline = time.time() + 5
    while time.time() < deadline:
        req = broker.matching_request(contract_id="wc_16d_test", run_id="run_c",
                                      tool="fs.write_text",
                                      requested_scope=("C:/ws/work/o.md",))
        if req is not None:
            break
        time.sleep(0.01)
    assert req is not None, "executor 的审批请求必须出现"
    broker.cancel(req.approval_id, reason="user cancelled")
    t.join(timeout=5)
    assert not t.is_alive(), "等待中的 executor 必须被解阻"
    assert box["result"].verdict == GateVerdict.DENY_CANCELLED
    assert harness.tool_calls == 0, "取消后绝不执行工具"


# ================================================================ 11. 参数/秘密进入事件与日志前 redaction
def test_11_secrets_and_arguments_redacted_in_audit_payloads():
    broker = ApprovalBroker()
    broker.bind_owner()
    args = {"path": "C:/ws/work/o.md", "content": "hello",
            "password": "hunter2_super_secret", "access_token": "tok_abc123",
            "secret": "s3cr3t-value", "normal": "keep-me"}
    req = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                capability="cap.filesystem", args=args,
                                risk_level=Permission.L1_LOW_WRITE,
                                requested_scope=("C:/ws/work/o.md",),
                                expires_at=broker.now() + 60)
    audit = req.to_audit_dict()
    blob = json.dumps(audit, sort_keys=True)
    ev_blob = json.dumps([e.payload for e in broker.events], sort_keys=True)
    for secret in ("hunter2_super_secret", "tok_abc123", "s3cr3t-value"):
        assert secret not in blob and secret not in ev_blob
    assert "keep-me" in blob, "非敏感参数保留（不误伤）"
    assert audit["args_redacted"]["password"] == "[REDACTED]"
    assert audit["args_redacted"]["access_token"] == "[REDACTED]"
    assert audit["args_redacted"]["secret"] == "[REDACTED]"
    assert audit["args_redacted"]["normal"] == "keep-me"
    assert not hasattr(req, "args_raw"), "原始参数不进入审批域"
    assert not hasattr(req, "args"), "请求只携带 redacted 摘要"


# ================================================================ 12. PermissionManager 回归 + C1–C7 不变
def test_12_permission_manager_regression_and_c1_c7_unchanged():
    # PM 语义未被 16D 改动：L0/L1 自动放行、L2/L3 默认拒绝、显式任务授权放行
    pm = PermissionManager()
    ctx = pm.new_task_context(max_permission=Permission.L1_LOW_WRITE,
                              allowed_tools=("fs.write_text",), source="t")
    assert pm.check("t1", Permission.L0_READ, task_auth=ctx, tool="fs.write_text").granted
    assert pm.check("t2", Permission.L1_LOW_WRITE, task_auth=ctx, tool="fs.write_text").granted
    assert not pm.check("t3", Permission.L2_HIGH_RISK, task_auth=ctx,
                        tool="fs.write_text").granted
    assert not pm.check("t4", Permission.L2_HIGH_RISK, task_auth=None,
                        tool="fs.write_text").granted
    # C1–C7 / DB 不变（回归套件覆盖）：approval 包零 cognition/sqlite 依赖
    import inspect as _inspect
    import furina.agent.approval.broker as b
    import furina.agent.approval.gate as g
    import furina.agent.approval.models as m
    for mod in (m, b, g):
        src = _inspect.getsource(mod)
        for forbidden in ("furina.cognition", "sqlite", "shelve", "sqlalchemy", "dbapi"):
            assert forbidden not in src, f"{mod.__name__} 不得依赖 {forbidden}"


# ================================================================ 额外：two-layer invariant
def test_two_layer_invariant_no_layer_expands_another():
    broker = ApprovalBroker()
    broker.bind_owner()
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker)
    proj = _projection(policy_kind="approval_required_each_step")
    caps = ("cap.filesystem",)
    # 审批放行无法覆盖 PermissionManager 拒绝
    r = gate.check_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                        contract_projection=proj,
                        pm_decision=PermissionDecision(False, "no-authorization",
                                                       Permission.L1_LOW_WRITE),
                        backend_capability_ids=caps, run_id="r1", wait_for_approval=False)
    assert r.verdict == GateVerdict.DENY_PERMISSION and r.approval is None
    # 审批放行无法覆盖 backend capability 层
    r2 = gate.check_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                         contract_projection=proj,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         backend_capability_ids=("cap.documents",), run_id="r2",
                         wait_for_approval=False)
    assert r2.verdict == GateVerdict.DENY_CAPABILITY and r2.approval is None
    # 审批放行无法覆盖契约 scope（路径）
    r3 = gate.check_step(tool="fs.write_text", args={"path": "C:/outside/x.md", "content": "x"},
                         contract_projection=proj,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         backend_capability_ids=caps, run_id="r3", wait_for_approval=False)
    assert r3.verdict == GateVerdict.DENY_CONTRACT_SCOPE and r3.approval is None


# ================================================================ 额外：owner 线程变更守卫
def test_owner_thread_mutation_guard():
    broker = ApprovalBroker(clock=FakeClock())
    broker.bind_owner(thread_id=999)   # owner ≠ 当前线程
    req = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                capability="cap.filesystem", args={},
                                risk_level=Permission.L1_LOW_WRITE, requested_scope=(),
                                expires_at=broker.now() + 60)
    assert broker.state_of(req.approval_id) == ApprovalState.PENDING   # 读任意线程
    for mut in (lambda: broker.resolve(req.approval_id, ApprovalDecisionKind.APPROVE_ONCE),
                lambda: broker.cancel(req.approval_id),
                lambda: broker.revoke(req.approval_id)):
        with pytest.raises(ApprovalStateError):
            mut()
    ws = _grant_ws()
    with pytest.raises(ApprovalStateError):
        broker.create_grant(user_event_id="lev_1756000000000_deadbeef",
                            capability="cap.filesystem", tool_pattern="fs.write_text",
                            workspace_scope=ws, expiry=broker.now() + 60)
    with pytest.raises(ApprovalStateError):
        broker.revoke_grant("gr_000000000000")


# ================================================================ 额外：approve_session 多次放行 + 撤销
def test_approve_session_repeated_allow_and_revoke():
    broker = ApprovalBroker()
    broker.bind_owner()
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker)
    harness = _Harness(gate)
    proj = _projection(policy_kind="approval_required_each_step")
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    kw = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
              projection=proj, pm_decision=pm, backend_capability_ids=("cap.filesystem",),
              run_id="run_s")
    r = harness.run_step(wait_for_approval=False, **kw)
    assert r.verdict == GateVerdict.APPROVAL_PENDING
    broker.resolve(r.approval.approval_id, ApprovalDecisionKind.APPROVE_SESSION,
                   reason="user ok")
    assert harness.run_step(**kw).verdict == GateVerdict.ALLOW
    assert harness.run_step(**kw).verdict == GateVerdict.ALLOW
    assert harness.tool_calls == 2
    broker.revoke(r.approval.approval_id, reason="revoke session")
    assert harness.run_step(**kw).verdict == GateVerdict.DENY_REVOKED
    assert harness.tool_calls == 2, "撤销后零新 tool call"


# ================================================================ 额外：wait_for_resolution 返回类型化 resolution
def test_wait_for_resolution_returns_typed_resolution_after_decision():
    broker = ApprovalBroker()
    broker.bind_owner()
    req = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                capability="cap.filesystem", args={},
                                risk_level=Permission.L1_LOW_WRITE, requested_scope=(),
                                expires_at=broker.now() + 60)
    broker.resolve(req.approval_id, ApprovalDecisionKind.DENY, reason="no")
    res = broker.wait_for_resolution(req.approval_id, timeout=1.0)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.decision == ApprovalDecisionKind.DENY
    assert res.ok is False
