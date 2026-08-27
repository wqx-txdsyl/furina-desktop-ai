# -*- coding: utf-8 -*-
"""Phase 16D — Permission & Approval Boundary 测试（含 Reviewer Patch 1/2 否证测试）。

任务书 §7 十二项最低锁定（1–12）+ 额外锁定（two-layer invariant / owner 守卫 /
approve_session 多次放行 / wait_for_resolution 类型化）。

Reviewer Patch 1 否证（P1…P9）：risk 不可降级 / write_roots 强制 / 审批身份完整
绑定 / 可信 USER 证据 / get-or-create 原子 / grant 时间窗 / 载荷不可变+防御复制 /
permit 封闭撤销 TOCTOU / 16A hash 校验契约。

Reviewer Patch 2 否证（P2A…P2E，锁定实测反例）：
A. 任意 producer 不可签发 permit：broker 公开 issue_permit 已删除/封门（无 seal 或
   非本 broker seal 一律 ApprovalStateError）；无 approval/grant 来源的 permit 也
   绑定 gate_id+contract_id+content_hash+run_id；
B. consume_permit 必填真实 tool/capability/原始 args，内部重算 operation digest；
   缺身份 TypeError / 换 tool/args/capability 一律拒绝；
C. audit digest 与 operation digest 分离：password/token 不同值 → operation digest
   不同（audit 因脱敏碰撞）；default=repr 删除，非 JSON 类型 fail-closed；
D. VerifiedUserEvidence 不得公开自铸：手工对象/跨 broker nonce/无关真实事件一律
   拒绝；验证绑定 event_id 与 approval_id/contract_hash/tool/scope/decision；
E. Gate 绑定可信组合根 expected contract_id/content_hash：自签扩权新 WorkContract
   拒绝；content_hash 只作完整性校验，授权真实性来自 expected 绑定；
   伪造 permit 全变体（短窗口伪造 / 已知 ID 篡改字段与时间窗 / 超长窗口）拒绝。
"""
from __future__ import annotations

import dataclasses
import json
import threading
import time
from typing import Any, Dict, Mapping, Optional, Tuple

import pytest

from furina.agent.approval import (
    ApprovalBroker,
    ApprovalDecisionKind,
    ApprovalGate,
    ApprovalState,
    ApprovalStateError,
    AuthorizationGrant,
    GateSeal,
    GateVerdict,
    PermitOutcome,
    ResolutionStatus,
    ToolPermit,
    VerifiedUserEvidence,
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
    "fs.open_path": "cap.filesystem",
    "doc.create": "cap.documents",
    "doc.write": "cap.documents",
}

#: 可信入口 USER 事件"台账"（模拟 C6 查询）：事件必须**真实存在**且**属于该操作
#: 上下文**（contract_id + tool）才算数——格式合法 ≠ 真实性，真实但无关的事件也拒绝。
_TRUSTED_USER_EVENTS: Dict[str, Dict[str, str]] = {
    "lev_1756000000000_deadbeef": {"contract_id": "wc_16d_test", "tool": "fs.write_text"},
}


def _trusted_verifier(user_event_id: str, context: Optional[Mapping] = None) -> bool:
    """模拟可信入口验证器：查台账 + 校验操作上下文绑定。"""
    entry = _TRUSTED_USER_EVENTS.get(user_event_id)
    if entry is None:
        return False
    ctx = dict(context or {})
    for key, expected in entry.items():
        if key == "tool":
            actual = ctx.get("tool") or ctx.get("tool_pattern")
        else:
            actual = ctx.get(key)
        if actual != expected:
            return False
    return True


def _make_broker(**kw) -> ApprovalBroker:
    """构造 owner=当前线程 + 可信证据验证器的 broker（测试即可信组合根）。"""
    kw.setdefault("owner_thread_id", threading.get_ident())
    kw.setdefault("user_evidence_verifier", _trusted_verifier)
    return ApprovalBroker(**kw)


def _make_pair(contract: Optional[WorkContract] = None, *, broker_kw: Optional[Dict] = None,
               gate_kw: Optional[Dict] = None) -> Tuple[ApprovalBroker, ApprovalGate, WorkContract]:
    """可信组合根：GateSeal + broker + 绑定该契约的 gate（含 permit_ttl 透传）。"""
    c = contract if contract is not None else _contract()
    seal = GateSeal()
    broker = _make_broker(gate_seal=seal, **(broker_kw or {}))
    gate = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker, gate_seal=seal,
                        expected_contract_id=c.contract_id,
                        expected_content_hash=c.content_hash, **(gate_kw or {}))
    return broker, gate, c


class FakeClock:
    """可推进时钟（timeout / expiry 测试确定性推进）。"""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._t = float(start)

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _contract(*, allowed_capabilities: Tuple[str, ...] = ("cap.filesystem",),
              policy_kind: str = "approval_required_each_step",
              read_roots: Tuple[str, ...] = ("C:/ws/docs",),
              write_roots: Tuple[str, ...] = ("C:/ws/work",),
              contract_id: str = "wc_16d_test", **kw) -> WorkContract:
    ws = WorkspaceScope(read_roots=tuple(read_roots), write_roots=tuple(write_roots))
    return WorkContract(
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


def _projection(**kw) -> Dict[str, Any]:
    """经 16A 校验的 backend 投影（可被 from_dict 完整 hash 复核）。"""
    return dict(_contract(**kw).to_backend_projection())


def _grant_ws() -> WorkspaceScope:
    return WorkspaceScope(read_roots=("C:/ws/docs",), write_roots=("C:/ws/work",))


def _create_grant(broker: ApprovalBroker, contract: Optional[WorkContract] = None, *,
                  capability: str = "cap.filesystem", tool_pattern: str = "fs.write_text",
                  workspace_scope: Optional[WorkspaceScope] = None, **kw) -> AuthorizationGrant:
    """可信入口验证下的 grant 创建（绑定 wc_16d_test 上下文）。"""
    c = contract if contract is not None else _contract()
    kw.setdefault("expiry", broker.now() + 3600)
    return broker.create_grant(
        user_evidence="lev_1756000000000_deadbeef",
        capability=capability, tool_pattern=tool_pattern,
        workspace_scope=workspace_scope if workspace_scope is not None else _grant_ws(),
        contract_id=c.contract_id, contract_hash=c.content_hash, **kw)


class _Harness:
    """真实工具边界模拟：gate ALLOW 后必须以**真实** tool/capability/args 经
    broker.consume_permit 原子复核成功才调用工具（tool_calls 计数 = 真实执行次数）。"""

    def __init__(self, gate: ApprovalGate, broker: ApprovalBroker) -> None:
        self.gate = gate
        self.broker = broker
        self.tool_calls = 0
        self.last_permit_outcome: Optional[PermitOutcome] = None

    def run_step(self, *, tool: str, args: Dict[str, Any], contract,
                 pm_decision: PermissionDecision, backend_capability_ids: Tuple[str, ...],
                 run_id: str = "run_1", wait_for_approval: bool = True, **kw):
        result = self.gate.check_step(
            tool=tool, args=args, contract=contract, pm_decision=pm_decision,
            backend_capability_ids=backend_capability_ids, run_id=run_id,
            wait_for_approval=wait_for_approval, **kw)
        if result.verdict == GateVerdict.ALLOW:
            assert result.permit is not None, "ALLOW 必须携带 permit（工具边界原子消费）"
            outcome = self.broker.consume_permit(
                result.permit, tool=tool, capability=_SNAPSHOT.get(tool, ""), args=args)
            self.last_permit_outcome = outcome
            if outcome.ok:
                self.tool_calls += 1
        return result


# ================================================================ 1. L0/L1 语义保留
def test_01_l0_l1_existing_semantics_preserved():
    c = _contract(policy_kind="approval_required_on_risk_level")   # 阈值默认 L2
    broker, gate, _ = _make_pair(c)
    caps = ("cap.filesystem",)
    # L0 只读：PM 自动放行 → ALLOW，无需任何新审批，不产生请求
    r = gate.check_step(tool="fs.read_file", args={"path": "C:/ws/docs/a.md"},
                        contract=c,
                        pm_decision=PermissionDecision(True, "auto", Permission.L0_READ),
                        backend_capability_ids=caps)
    assert r.verdict == GateVerdict.ALLOW
    assert broker.matching_request(contract_id=c.contract_id, run_id="", tool="fs.read_file",
                                   requested_scope=("C:/ws/docs/a.md",)) is None
    # L1 低风险写入：显式任务授权放行 → ALLOW（无需新审批）
    r2 = gate.check_step(tool="fs.write_text", args={"path": "C:/ws/work/out.md", "content": "x"},
                         contract=c,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         backend_capability_ids=caps)
    assert r2.verdict == GateVerdict.ALLOW
    # PM 拒绝时 gate 绝不放行（PM 未被 16D 削弱）
    r3 = gate.check_step(tool="fs.read_file", args={"path": "C:/ws/docs/a.md"},
                         contract=c,
                         pm_decision=PermissionDecision(False, "no-authorization",
                                                        Permission.L0_READ),
                         backend_capability_ids=caps)
    assert r3.verdict == GateVerdict.DENY_PERMISSION


# ================================================================ 2. L2/L3 需要既有授权 + 新审批
def test_02_l2_l3_require_existing_authorization_and_new_approval():
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)
    harness = _Harness(gate, broker)
    caps = ("cap.filesystem",)
    kw = dict(tool="fs.delete", args={"path": "C:/ws/work/x"}, contract=c,
              backend_capability_ids=caps, run_id="run_2")
    # (a) 既有授权缺失（PM 拒绝）→ DENY_PERMISSION，不产生审批请求
    r = harness.run_step(pm_decision=PermissionDecision(False, "no-authorization",
                                                       Permission.L2_HIGH_RISK),
                         wait_for_approval=False, **kw)
    assert r.verdict == GateVerdict.DENY_PERMISSION and r.approval is None
    assert broker.events == []
    # (b) 既有授权在但无审批 → APPROVAL_PENDING（异步通道建立，等待用户决议）
    pm_ok = PermissionDecision(True, "task_authorization:t", Permission.L2_HIGH_RISK)
    r2 = harness.run_step(pm_decision=pm_ok, wait_for_approval=False, **kw)
    assert r2.verdict == GateVerdict.APPROVAL_PENDING and r2.approval is not None
    assert broker.state_of(r2.approval.approval_id) == ApprovalState.PENDING
    assert broker.events[0].etype == "approval.requested"
    # (c) deny → 类型化拒绝；重检同一请求（不新建），零 tool call
    broker.resolve(r2.approval.approval_id, ApprovalDecisionKind.DENY, reason="user 拒绝")
    r3 = harness.run_step(pm_decision=pm_ok, **kw)
    assert r3.verdict == GateVerdict.DENY_APPROVAL
    assert broker.matching_request(contract_id=c.contract_id, run_id="run_2", tool="fs.delete",
                                   requested_scope=("C:/ws/work/x",)).approval_id == \
        r2.approval.approval_id
    # (d) approve_once → ALLOW 且只消费一次
    kw2 = dict(tool="fs.move", args={"path": "C:/ws/work/a", "dest": "C:/ws/work/b"},
               contract=c, backend_capability_ids=caps, run_id="run_2")
    r4 = harness.run_step(pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                          wait_for_approval=False, **kw2)
    assert r4.verdict == GateVerdict.APPROVAL_PENDING
    broker.resolve(r4.approval.approval_id, ApprovalDecisionKind.APPROVE_ONCE, reason="user ok")
    r5 = harness.run_step(pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE), **kw2)
    assert r5.verdict == GateVerdict.ALLOW and r5.permit is not None
    assert harness.last_permit_outcome.ok
    assert harness.tool_calls == 1


# ================================================================ 3. 越契约 inner request 工具执行前拒绝
def test_03_inner_request_broader_than_contract_denied_before_tool():
    c_doc = _contract(policy_kind="approval_required_each_step",
                      allowed_capabilities=("cap.documents",))
    broker1, gate1, _ = _make_pair(c_doc)
    harness1 = _Harness(gate1, broker1)
    c2 = _contract(policy_kind="approval_required_each_step")
    broker2, gate2, _ = _make_pair(c2)
    harness2 = _Harness(gate2, broker2)
    # 契约只允许 cap.documents；fs.delete 属于 cap.filesystem → 越契约
    r = harness1.run_step(tool="fs.delete", args={"path": "C:/ws/work/x"}, contract=c_doc,
                          pm_decision=PermissionDecision(True, "task_authorization:t",
                                                         Permission.L2_HIGH_RISK),
                          backend_capability_ids=("cap.filesystem",))
    assert r.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    assert harness1.tool_calls == 0
    assert broker1.events == [], "越契约的请求不得产生任何审批请求（工具执行前拒绝）"
    # 路径越出 workspace → 同样工具执行前拒绝
    r2 = harness2.run_step(tool="fs.write_text", args={"path": "C:/outside/x.md", "content": "x"},
                           contract=c2,
                           pm_decision=PermissionDecision(True, "task_authorization:t",
                                                          Permission.L1_LOW_WRITE),
                           backend_capability_ids=("cap.filesystem",))
    assert r2.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    assert harness2.tool_calls == 0


# ================================================================ 4. approve_once 恰好消费一次
def test_04_approve_once_consumed_exactly_once():
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)
    harness = _Harness(gate, broker)
    kw = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "hi"},
              contract=c,
              pm_decision=PermissionDecision(True, "task_authorization:t",
                                             Permission.L1_LOW_WRITE),
              backend_capability_ids=("cap.filesystem",), run_id="run_1")
    r = harness.run_step(wait_for_approval=False, **kw)
    assert r.verdict == GateVerdict.APPROVAL_PENDING
    aid = r.approval.approval_id
    broker.resolve(aid, ApprovalDecisionKind.APPROVE_ONCE, reason="user ok")
    r2 = harness.run_step(**kw)
    assert r2.verdict == GateVerdict.ALLOW and r2.permit is not None
    assert r2.approval.approval_id == aid
    assert harness.tool_calls == 1
    assert harness.last_permit_outcome.ok
    assert broker.is_consumed(aid)   # 消费发生在真实工具边界（permit 原子完成）
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
    broker = _make_broker(clock=clock)
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
    broker = _make_broker(clock=clock)
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
    c = _contract(policy_kind="approval_required_each_step")
    broker2, gate2, _ = _make_pair(c)
    harness = _Harness(gate2, broker2)
    start = time.time()
    r = harness.run_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                         contract=c,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         backend_capability_ids=("cap.filesystem",), run_id="run_t",
                         request_timeout_seconds=0.05)
    assert r.verdict == GateVerdict.DENY_TIMEOUT
    assert harness.tool_calls == 0
    assert time.time() - start < 5.0, "超时必须在有限时间内返回"


# ================================================================ 7. 持久/会话授权必须 canonical USER provenance
def test_07_canonical_user_provenance_required_for_grant():
    broker = _make_broker()
    ws = _grant_ws()
    for bad in ("llm_suggested", "backend_native", "inferred_intent", "adapter_default", ""):
        with pytest.raises(ApprovalStateError):
            broker.create_grant(user_evidence=bad, capability="cap.filesystem",
                                tool_pattern="fs.write_text", workspace_scope=ws,
                                expiry=broker.now() + 3600)
    g = _create_grant(broker)
    assert g.grant_id.startswith("gr_")
    assert g.user_event_id == "lev_1756000000000_deadbeef"
    # 非 owner 线程（backend/executor 身份）不得创建授权：owner 构造期绑定后不可抢占
    non_owner = _make_broker(owner_thread_id=0xDEAD)
    with pytest.raises(ApprovalStateError):
        non_owner.create_grant(user_evidence="lev_1756000000000_deadbeef",
                               capability="cap.filesystem", tool_pattern="fs.write_text",
                               workspace_scope=ws, expiry=non_owner.now() + 3600)
    # 未绑定 owner（构造期即锁定）也不得创建授权
    unbound = ApprovalBroker(user_evidence_verifier=_trusted_verifier)
    with pytest.raises(ApprovalStateError):
        unbound.create_grant(user_evidence="lev_1756000000000_deadbeef",
                             capability="cap.filesystem", tool_pattern="fs.write_text",
                             workspace_scope=ws, expiry=unbound.now() + 3600)


# ================================================================ 8. grant scope/expiry/revocation enforced
def test_08_grant_scope_expiry_revocation_enforced():
    c = _contract(policy_kind="pre_approved_scoped")
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    caps = ("cap.filesystem",)
    step = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                contract=c, pm_decision=pm, backend_capability_ids=caps)
    ws = _grant_ws()

    # (a) 覆盖 → ALLOW（零审批请求）
    broker, gate, _ = _make_pair(c)
    harness = _Harness(gate, broker)
    _create_grant(broker, c)
    r = harness.run_step(**step)
    assert r.verdict == GateVerdict.ALLOW and r.grant is not None
    assert harness.tool_calls == 1

    # (b) grant scope 强制：写入点在 grant 更窄 write root 之外 → 不覆盖 → pre_approved 拒绝
    broker_b, gate_b, _ = _make_pair(c)
    harness_b = _Harness(gate_b, broker_b)
    ws_narrow = WorkspaceScope(read_roots=("C:/ws/docs",), write_roots=("C:/ws/work/sub",))
    _create_grant(broker_b, c, workspace_scope=ws_narrow)
    r2 = harness_b.run_step(**step)
    assert r2.verdict == GateVerdict.DENY_APPROVAL
    assert harness_b.tool_calls == 0

    # (c) revocation：撤销后下一工具边界前拒绝（零新 tool call）
    broker_c, gate_c, _ = _make_pair(c)
    harness_c = _Harness(gate_c, broker_c)
    grant_c = _create_grant(broker_c, c)
    assert harness_c.run_step(**step).verdict == GateVerdict.ALLOW
    assert harness_c.tool_calls == 1
    broker_c.revoke_grant(grant_c.grant_id, reason="user revoked")
    r3 = harness_c.run_step(**step)
    assert r3.verdict == GateVerdict.DENY_GRANT_INACTIVE
    assert harness_c.tool_calls == 1

    # (d) expiry：过期 grant 非激活 → DENY_GRANT_INACTIVE
    clock = FakeClock()
    seal = GateSeal()
    broker_d = _make_broker(clock=clock, gate_seal=seal)
    gate_d = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker_d, gate_seal=seal,
                          expected_contract_id=c.contract_id,
                          expected_content_hash=c.content_hash)
    broker_d.create_grant(user_evidence="lev_1756000000000_deadbeef",
                          capability="cap.filesystem", tool_pattern="fs.write_text",
                          workspace_scope=ws, expiry=clock() + 10,
                          contract_id=c.contract_id, contract_hash=c.content_hash)
    clock.advance(11)
    r4 = gate_d.check_step(**step)
    assert r4.verdict == GateVerdict.DENY_GRANT_INACTIVE

    # (e) grant 比契约宽（read root 越界）→ DENY_GRANT_SCOPE fail-closed
    broker_e, gate_e, _ = _make_pair(c)
    ws_broad = WorkspaceScope(read_roots=("C:/ws/docs", "C:/extra"),
                              write_roots=("C:/ws/work",))
    _create_grant(broker_e, c, workspace_scope=ws_broad)
    r5 = gate_e.check_step(**step)
    assert r5.verdict == GateVerdict.DENY_GRANT_SCOPE


# ================================================================ 9. backend 无法合成永久 grant
def test_09_backend_cannot_synthesize_permanent_grant():
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    # gate 的审批路径（approve_once）绝不产生任何 grant
    r = gate.check_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                        contract=c, pm_decision=pm,
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
        _create_grant(broker, c, expiry=broker.now() + 86400 * 366)
    # backend/LLM 文本无法作为决议来源（非 owner 决议 → ApprovalStateError）
    non_owner = _make_broker(owner_thread_id=0xDEAD)
    with pytest.raises(ApprovalStateError):
        non_owner.resolve("apv_000000000000", ApprovalDecisionKind.APPROVE_ONCE)


# ================================================================ 10. 等待中取消 → 解阻且零 tool call
def test_10_cancellation_while_waiting_unblocks_and_no_tool():
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)   # main = owner（canonical USER 决策入口，构造期绑定）
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    harness = _Harness(gate, broker)
    box: Dict[str, Any] = {}

    def executor() -> None:
        box["result"] = harness.run_step(
            tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
            contract=c, pm_decision=pm, backend_capability_ids=("cap.filesystem",),
            run_id="run_c")

    t = threading.Thread(target=executor, daemon=True)
    t.start()
    req = None
    deadline = time.time() + 5
    while time.time() < deadline:
        req = broker.matching_request(contract_id=c.contract_id, run_id="run_c",
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
    broker = _make_broker()
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
    ev_blob = json.dumps([e.to_payload() for e in broker.events], sort_keys=True)
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
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)
    caps = ("cap.filesystem",)
    # 审批放行无法覆盖 PermissionManager 拒绝
    r = gate.check_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                        contract=c,
                        pm_decision=PermissionDecision(False, "no-authorization",
                                                       Permission.L1_LOW_WRITE),
                        backend_capability_ids=caps, run_id="r1", wait_for_approval=False)
    assert r.verdict == GateVerdict.DENY_PERMISSION and r.approval is None
    # 审批放行无法覆盖 backend capability 层
    r2 = gate.check_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                         contract=c,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         backend_capability_ids=("cap.documents",), run_id="r2",
                         wait_for_approval=False)
    assert r2.verdict == GateVerdict.DENY_CAPABILITY and r2.approval is None
    # 审批放行无法覆盖契约 scope（路径）
    r3 = gate.check_step(tool="fs.write_text", args={"path": "C:/outside/x.md", "content": "x"},
                         contract=c,
                         pm_decision=PermissionDecision(True, "task_authorization:t",
                                                        Permission.L1_LOW_WRITE),
                         backend_capability_ids=caps, run_id="r3", wait_for_approval=False)
    assert r3.verdict == GateVerdict.DENY_CONTRACT_SCOPE and r3.approval is None


# ================================================================ 额外：owner 线程变更守卫
def test_owner_thread_mutation_guard():
    broker = _make_broker(clock=FakeClock(), owner_thread_id=999)   # owner ≠ 当前线程
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
        broker.create_grant(user_evidence="lev_1756000000000_deadbeef",
                            capability="cap.filesystem", tool_pattern="fs.write_text",
                            workspace_scope=ws, expiry=broker.now() + 60)
    with pytest.raises(ApprovalStateError):
        broker.revoke_grant("gr_000000000000")


# ================================================================ 额外：approve_session 多次放行 + 撤销
def test_approve_session_repeated_allow_and_revoke():
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)
    harness = _Harness(gate, broker)
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    kw = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
              contract=c, pm_decision=pm, backend_capability_ids=("cap.filesystem",),
              run_id="run_s")
    r = harness.run_step(wait_for_approval=False, **kw)
    assert r.verdict == GateVerdict.APPROVAL_PENDING
    broker.resolve(r.approval.approval_id, ApprovalDecisionKind.APPROVE_SESSION,
                   reason="user ok", user_evidence="lev_1756000000000_deadbeef")
    assert harness.run_step(**kw).verdict == GateVerdict.ALLOW
    assert harness.run_step(**kw).verdict == GateVerdict.ALLOW
    assert harness.tool_calls == 2
    broker.revoke(r.approval.approval_id, reason="revoke session")
    assert harness.run_step(**kw).verdict == GateVerdict.DENY_REVOKED
    assert harness.tool_calls == 2, "撤销后零新 tool call"


# ================================================================ 额外：wait_for_resolution 返回类型化 resolution
def test_wait_for_resolution_returns_typed_resolution_after_decision():
    broker = _make_broker()
    req = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                capability="cap.filesystem", args={},
                                risk_level=Permission.L1_LOW_WRITE, requested_scope=(),
                                expires_at=broker.now() + 60)
    broker.resolve(req.approval_id, ApprovalDecisionKind.DENY, reason="no")
    res = broker.wait_for_resolution(req.approval_id, timeout=1.0)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.decision == ApprovalDecisionKind.DENY
    assert res.ok is False


# ================================================================ P1. risk 不得被调用方降级
def test_patch1_risk_cannot_be_downgraded_by_caller():
    c = _contract(policy_kind="approval_required_on_risk_level")
    broker, gate, _ = _make_pair(c)   # 阈值默认 L2
    pm_l2 = PermissionDecision(True, "task_authorization:t", Permission.L2_HIGH_RISK)
    kw = dict(tool="fs.delete", args={"path": "C:/ws/work/x"}, contract=c,
              backend_capability_ids=("cap.filesystem",), run_id="run_p1")
    # 反例锁定：PM 结果 L2 + 调用方声称 L0（降级）→ 仍必须审批
    r = gate.check_step(pm_decision=pm_l2, risk_level=Permission.L0_READ,
                        wait_for_approval=False, **kw)
    assert r.verdict == GateVerdict.APPROVAL_PENDING, "调用方不得把可信 PM 的 L2 降级为免审批"
    # 调用方不传 risk → 同样必须审批（PM 结果为下界）
    r2 = gate.check_step(pm_decision=pm_l2, wait_for_approval=False, **kw)
    assert r2.verdict == GateVerdict.APPROVAL_PENDING
    # L3 同理硬性必须审批
    pm_l3 = PermissionDecision(True, "task_authorization:t", Permission.L3_SENSITIVE)
    r3 = gate.check_step(pm_decision=pm_l3, risk_level=Permission.L0_READ,
                         wait_for_approval=False, **kw)
    assert r3.verdict == GateVerdict.APPROVAL_PENDING
    # 阈值调到 L3 也拦不住 L2（L2/L3 硬性必须审批，不受 threshold 豁免）
    _, gate_l3, _ = _make_pair(c, gate_kw={"risk_threshold": Permission.L3_SENSITIVE})
    r4 = gate_l3.check_step(pm_decision=pm_l2, risk_level=Permission.L0_READ,
                            wait_for_approval=False, **kw)
    assert r4.verdict == GateVerdict.APPROVAL_PENDING
    # 无任何风险信号（PM level 缺失 + 调用方未声明）→ fail-closed 拒绝，不建请求
    seal = GateSeal()
    broker_fresh = _make_broker(gate_seal=seal)
    gate_fresh = ApprovalGate(capability_snapshot=_SNAPSHOT, broker=broker_fresh,
                              gate_seal=seal, expected_contract_id=c.contract_id,
                              expected_content_hash=c.content_hash)
    r5 = gate_fresh.check_step(pm_decision=PermissionDecision(True, "auto"),
                               wait_for_approval=False, **kw)
    assert r5.verdict == GateVerdict.DENY_APPROVAL and r5.approval is None
    assert broker_fresh.events == []


# ================================================================ P2. 写操作只能命中 write_roots
def test_patch2_write_ops_only_hit_write_roots():
    c = _contract(policy_kind="approval_required_each_step")  # read=docs, write=work
    broker, gate, _ = _make_pair(c)
    harness = _Harness(gate, broker)
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    # 反例锁定：fs.write_text 落在 read root → 契约层拒绝（read_roots 不授予写权限）
    r = harness.run_step(tool="fs.write_text", args={"path": "C:/ws/docs/a.md", "content": "x"},
                         contract=c, pm_decision=pm, backend_capability_ids=("cap.filesystem",))
    assert r.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    assert harness.tool_calls == 0 and broker.events == []
    # 非只读白名单工具（fs.open_path）落在 read root → 同样按写目标拒绝
    r2 = harness.run_step(tool="fs.open_path", args={"path": "C:/ws/docs/a.md"},
                          contract=c, pm_decision=pm, backend_capability_ids=("cap.filesystem",))
    assert r2.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    # 只读工具落在 read root → 正常（读语义保留；on_risk 阈值 L2 下 L0 免审批）
    c_or = _contract(policy_kind="approval_required_on_risk_level")
    broker_or, gate_or, _ = _make_pair(c_or)
    harness_or = _Harness(gate_or, broker_or)
    r3 = harness_or.run_step(tool="fs.read_file", args={"path": "C:/ws/docs/a.md"},
                             contract=c_or,
                             pm_decision=PermissionDecision(True, "auto", Permission.L0_READ),
                             backend_capability_ids=("cap.filesystem",))
    assert r3.verdict == GateVerdict.ALLOW and harness_or.tool_calls == 1
    # grant 层同样强制：grant 只有 read_roots 覆盖写点、write_roots 为空 → 不覆盖
    c_pre = _contract(policy_kind="pre_approved_scoped")
    broker_g, gate_g, _ = _make_pair(c_pre)
    harness_g = _Harness(gate_g, broker_g)
    _create_grant(broker_g, c_pre, workspace_scope=WorkspaceScope(
        read_roots=("C:/ws/docs", "C:/ws/work"), write_roots=()))
    r4 = harness_g.run_step(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
                            contract=c_pre, pm_decision=pm,
                            backend_capability_ids=("cap.filesystem",))
    assert r4.verdict == GateVerdict.DENY_APPROVAL, "grant read_roots 不得授予写权限"
    assert harness_g.tool_calls == 0


# ================================================================ P3. 审批身份绑定完整操作
def test_patch3_approval_identity_binds_full_operation():
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)
    harness = _Harness(gate, broker)
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    base = dict(contract=c, pm_decision=pm, backend_capability_ids=("cap.filesystem",),
                run_id="run_p3", wait_for_approval=False)
    # 操作 A：写 o.md / content=hello
    ra = harness.run_step(tool="fs.write_text",
                          args={"path": "C:/ws/work/o.md", "content": "hello"}, **base)
    assert ra.verdict == GateVerdict.APPROVAL_PENDING
    broker.resolve(ra.approval.approval_id, ApprovalDecisionKind.APPROVE_ONCE)
    # 反例锁定：操作 B 同 tool 同路径但 content=evil（不同参数摘要）→ 不得复用 A 的批准
    rb = harness.run_step(tool="fs.write_text",
                          args={"path": "C:/ws/work/o.md", "content": "evil"}, **base)
    assert rb.verdict == GateVerdict.APPROVAL_PENDING, "不同操作（参数摘要不同）不得复用审批"
    assert rb.approval.approval_id != ra.approval.approval_id
    assert harness.tool_calls == 0, "B 未获批准前零 tool call"
    requested = [e for e in broker.events if e.etype == "approval.requested"]
    assert len(requested) == 2, "A 与 B 是两个独立审批请求"
    assert ra.approval.operation_digest != rb.approval.operation_digest
    # 相同操作重复检查 → 复用同一请求（身份稳定）
    ra2 = harness.run_step(tool="fs.write_text",
                           args={"path": "C:/ws/work/o.md", "content": "hello"}, **base)
    assert ra2.approval.approval_id == ra.approval.approval_id
    # 不同契约（不同 contract hash）→ 同样不得复用
    c_other = _contract(policy_kind="approval_required_each_step", contract_id="wc_16d_other")
    broker2, gate2, _ = _make_pair(c_other)
    rc = gate2.check_step(tool="fs.write_text",
                          args={"path": "C:/ws/work/o.md", "content": "hello"},
                          contract=c_other, pm_decision=pm,
                          backend_capability_ids=("cap.filesystem",),
                          run_id="run_p3b", wait_for_approval=False)
    assert rc.verdict == GateVerdict.APPROVAL_PENDING
    assert rc.approval.approval_id != ra.approval.approval_id
    assert rc.approval.contract_hash != ra.approval.contract_hash


# ================================================================ P2C. 双摘要：敏感值不同 → operation digest 不同
def test_patch3b_operation_digest_differs_for_different_secrets():
    broker = _make_broker()
    # 同一 tool/路径，仅敏感值不同（redacted 后 audit 摘要碰撞，但 operation 摘要不同）
    req_a = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                  capability="cap.filesystem",
                                  args={"path": "C:/ws/work/o.md", "password": "AAA"},
                                  risk_level=Permission.L1_LOW_WRITE,
                                  requested_scope=("C:/ws/work/o.md",),
                                  expires_at=broker.now() + 60)
    req_b = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                  capability="cap.filesystem",
                                  args={"path": "C:/ws/work/o.md", "password": "BBB"},
                                  risk_level=Permission.L1_LOW_WRITE,
                                  requested_scope=("C:/ws/work/o.md",),
                                  expires_at=broker.now() + 60)
    assert req_a.operation_digest != req_b.operation_digest, \
        "不同敏感值必须产生不同操作身份（approve_once 不得跨秘密复用）"
    assert req_a.audit_args_digest == req_b.audit_args_digest, \
        "audit 摘要基于 redacted args（脱敏碰撞属预期；故不作操作身份）"
    # token 同形不同值同样区分
    req_t1 = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                   capability="cap.filesystem",
                                   args={"path": "C:/ws/work/o.md", "token": "tok_A"},
                                   risk_level=Permission.L1_LOW_WRITE,
                                   requested_scope=("C:/ws/work/o.md",),
                                   expires_at=broker.now() + 60)
    req_t2 = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                   capability="cap.filesystem",
                                   args={"path": "C:/ws/work/o.md", "token": "tok_B"},
                                   risk_level=Permission.L1_LOW_WRITE,
                                   requested_scope=("C:/ws/work/o.md",),
                                   expires_at=broker.now() + 60)
    assert req_t1.operation_digest != req_t2.operation_digest
    # 非 JSON 类型（set）→ 严格 JSON 域 fail-closed（default=repr 已删除）
    with pytest.raises(ApprovalStateError):
        broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                              capability="cap.filesystem",
                              args={"path": "C:/ws/work/o.md", "bad": {"set_member"}},
                              risk_level=Permission.L1_LOW_WRITE,
                              requested_scope=("C:/ws/work/o.md",),
                              expires_at=broker.now() + 60)
    # gate 层非 JSON 参数 → 类型化拒绝（不抛错）
    c = _contract(policy_kind="approval_required_each_step")
    _, gate, _ = _make_pair(c)
    r = gate.check_step(tool="fs.write_text",
                        args={"path": "C:/ws/work/o.md", "bad": {"set_member"}},
                        contract=c,
                        pm_decision=PermissionDecision(True, "task_authorization:t",
                                                       Permission.L1_LOW_WRITE),
                        backend_capability_ids=("cap.filesystem",),
                        run_id="run_nonjson", wait_for_approval=False)
    assert r.verdict == GateVerdict.DENY_CONTRACT_SCOPE


# ================================================================ P4. 可信入口验证的 canonical USER 证据
def test_patch4_verified_user_evidence_required():
    ws = _grant_ws()
    c = _contract(policy_kind="approval_required_each_step")
    # (a) 未配置可信验证器 → 格式正则不算真实性证明 → 一律 fail-closed
    no_verifier = _make_broker(user_evidence_verifier=None)
    with pytest.raises(ApprovalStateError):
        no_verifier.create_grant(user_evidence="lev_1756000000000_deadbeef",
                                 capability="cap.filesystem", tool_pattern="fs.write_text",
                                 workspace_scope=ws, expiry=no_verifier.now() + 3600)
    req = no_verifier.create_request(contract_id="wc_16d_test", run_id="run_1",
                                     tool="fs.write_text", capability="cap.filesystem",
                                     args={}, risk_level=Permission.L1_LOW_WRITE,
                                     requested_scope=("C:/ws/work/o.md",),
                                     expires_at=no_verifier.now() + 60)
    with pytest.raises(ApprovalStateError):
        no_verifier.resolve(req.approval_id, ApprovalDecisionKind.APPROVE_SESSION)
    with pytest.raises(ApprovalStateError):
        no_verifier.resolve(req.approval_id, ApprovalDecisionKind.APPROVE_SESSION,
                            user_evidence="lev_1756000000000_deadbeef")
    # (b) 形态合法但台账中不存在（验证器返回 False）→ 不是真实性证明
    reject_all = _make_broker(user_evidence_verifier=lambda uid, ctx: False)
    with pytest.raises(ApprovalStateError):
        reject_all.create_grant(user_evidence="lev_1756000000000_deadbeef",
                                capability="cap.filesystem", tool_pattern="fs.write_text",
                                workspace_scope=ws, expiry=reject_all.now() + 3600)
    # (c) opaque nonce：request_user_evidence 返回内部句柄；消费时重查可信记录
    broker, gate, _ = _make_pair(c)
    nonce = broker.request_user_evidence(
        "lev_1756000000000_deadbeef",
        context={"decision": "grant", "contract_id": c.contract_id, "tool": "fs.write_text"})
    assert nonce.startswith("uev_")
    g = broker.create_grant(user_evidence=nonce, capability="cap.filesystem",
                            tool_pattern="fs.write_text", workspace_scope=ws,
                            expiry=broker.now() + 3600,
                            contract_id=c.contract_id, contract_hash=c.content_hash)
    assert g.user_event_id == "lev_1756000000000_deadbeef"
    # 手工构造 VerifiedUserEvidence（不得公开自铸）→ 一律拒绝
    forged_obj = VerifiedUserEvidence(user_event_id="lev_1756000000000_deadbeef",
                                      verified_at=broker.now(), verified_by="trusted_entry")
    with pytest.raises(ApprovalStateError):
        broker.create_grant(user_evidence=forged_obj, capability="cap.filesystem",
                            tool_pattern="fs.write_text", workspace_scope=ws,
                            expiry=broker.now() + 3600,
                            contract_id=c.contract_id, contract_hash=c.content_hash)
    # 跨 broker：他处签发的 nonce（同 source 同形态）在本 broker 消费 → 拒绝
    other_broker = _make_broker()
    other_nonce = other_broker.request_user_evidence(
        "lev_1756000000000_deadbeef",
        context={"decision": "grant", "contract_id": c.contract_id, "tool": "fs.write_text"})
    with pytest.raises(ApprovalStateError):
        broker.create_grant(user_evidence=other_nonce, capability="cap.filesystem",
                            tool_pattern="fs.write_text", workspace_scope=ws,
                            expiry=broker.now() + 3600,
                            contract_id=c.contract_id, contract_hash=c.content_hash)
    # (d) approve_session：消费时刻绑定请求操作上下文；决议事件记录 user_event_id
    req2 = broker.create_request(contract_id="wc_16d_test", run_id="run_2",
                                 tool="fs.write_text", capability="cap.filesystem",
                                 args={}, risk_level=Permission.L1_LOW_WRITE,
                                 requested_scope=("C:/ws/work/o.md",),
                                 expires_at=broker.now() + 60)
    res = broker.resolve(req2.approval_id, ApprovalDecisionKind.APPROVE_SESSION,
                         user_evidence="lev_1756000000000_deadbeef")
    assert res.ok and res.status == ResolutionStatus.RESOLVED
    decided = [e for e in broker.events if e.etype == "approval.decided"
               and e.approval_id == req2.approval_id][0]
    assert decided.to_payload()["user_event_id"] == "lev_1756000000000_deadbeef"
    # (e) 无关真实事件拒绝：事件真实存在但属于 fs.write_text；用于 fs.delete 操作 → 拒绝
    req_del = broker.create_request(contract_id="wc_16d_test", run_id="run_3",
                                    tool="fs.delete", capability="cap.filesystem",
                                    args={"path": "C:/ws/work/x"},
                                    risk_level=Permission.L2_HIGH_RISK,
                                    requested_scope=("C:/ws/work/x",),
                                    expires_at=broker.now() + 60)
    with pytest.raises(ApprovalStateError):
        broker.resolve(req_del.approval_id, ApprovalDecisionKind.APPROVE_SESSION,
                       user_evidence="lev_1756000000000_deadbeef")
    with pytest.raises(ApprovalStateError):
        _create_grant(broker, c, tool_pattern="fs.delete")
    # (f) backend 不得抢占 owner：无运行期改绑 API；owner 固定为构造值
    assert not hasattr(broker, "bind_owner"), "构造期唯一绑定点；first-come 抢占向量已删除"
    assert broker.owner_thread_id == threading.get_ident()


# ================================================================ P5. get-or-create 原子化
def test_patch5_get_or_create_request_atomic_under_concurrency():
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)
    pm = PermissionDecision(True, "task_authorization:t", Permission.L2_HIGH_RISK)
    results: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        r = gate.check_step(tool="fs.delete", args={"path": "C:/ws/work/x"}, contract=c,
                            pm_decision=pm, backend_capability_ids=("cap.filesystem",),
                            run_id="run_p5", wait_for_approval=False)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(results) == 8 and not any(t.is_alive() for t in threads)
    assert all(r.verdict == GateVerdict.APPROVAL_PENDING for r in results)
    ids = {r.approval.approval_id for r in results}
    assert len(ids) == 1, "并发同一步只能产生一个请求（原子 get-or-create）"
    requested = [e for e in broker.events if e.etype == "approval.requested"]
    assert len(requested) == 1


# ================================================================ P6. grant 有效窗口
def test_patch6_grant_temporal_bounds():
    clock = FakeClock()
    broker = _make_broker(clock=clock)
    ws = _grant_ws()
    now = clock()
    c = _contract(policy_kind="pre_approved_scoped")
    # 反例锁定：未来签发拒绝
    with pytest.raises(ApprovalStateError, match="未来签发"):
        broker.create_grant(user_evidence="lev_1756000000000_deadbeef",
                            capability="cap.filesystem", tool_pattern="fs.write_text",
                            workspace_scope=ws, issued_at=now + 10, expiry=now + 3600,
                            contract_id=c.contract_id, contract_hash=c.content_hash)
    # 反例锁定：已过期新 grant 拒绝
    with pytest.raises(ApprovalStateError, match="已过期"):
        broker.create_grant(user_evidence="lev_1756000000000_deadbeef",
                            capability="cap.filesystem", tool_pattern="fs.write_text",
                            workspace_scope=ws, expiry=now - 1,
                            contract_id=c.contract_id, contract_hash=c.content_hash)
    # 有效窗口：issued_at <= now < expiry
    g = broker.create_grant(user_evidence="lev_1756000000000_deadbeef",
                            capability="cap.filesystem", tool_pattern="fs.write_text",
                            workspace_scope=ws, issued_at=now - 5, expiry=now + 100,
                            contract_id=c.contract_id, contract_hash=c.content_hash)
    assert broker.grant_state(g.grant_id)["active"] is True
    # now < issued_at → 未生效（不激活）
    assert broker.grant_state(g.grant_id, now=g.issued_at - 1)["active"] is False
    assert broker.covering_grant(tool="fs.write_text", capability="cap.filesystem",
                                 paths=("C:/ws/work/o.md",), write_paths=("C:/ws/work/o.md",),
                                 now=g.issued_at - 1) is None
    # now >= expiry → 过期
    clock.advance(106)
    assert broker.grant_state(g.grant_id)["active"] is False


# ================================================================ P7. 载荷递归不可变 + 导出防御复制 + 文本限长脱敏
def test_patch7_payloads_immutable_and_exports_defensive():
    broker = _make_broker()
    args = {"path": "C:/ws/work/o.md", "meta": {"note": "hi", "inner": ["a", "b"]}}
    req = broker.create_request(contract_id="wc_1", run_id="run_1", tool="fs.write_text",
                                capability="cap.filesystem", args=args,
                                reason="说明 password=hunter2 " + "X" * 5000,
                                risk_level=Permission.L1_LOW_WRITE,
                                requested_scope=("C:/ws/work/o.md",),
                                expires_at=broker.now() + 60)
    # 存储递归不可变：嵌套 dict/list 均冻结（MappingProxyType/tuple）
    with pytest.raises(TypeError):
        req.args_redacted["meta"]["note"] = "mutated"      # type: ignore[index]
    with pytest.raises(TypeError):
        req.args_redacted["path"] = "C:/evil"              # type: ignore[index]
    inner = req.args_redacted["meta"]
    assert isinstance(inner["inner"], tuple), "嵌套 list 冻结为 tuple"
    # 导出防御复制：修改导出副本不影响存储与后续导出
    audit1 = req.to_audit_dict()
    audit1["args_redacted"]["meta"]["note"] = "mutated"
    audit2 = req.to_audit_dict()
    assert audit2["args_redacted"]["meta"]["note"] == "hi"
    # 可见文本统一限长 + 脱敏：reason 不含秘密且长度有界
    assert "hunter2" not in req.reason
    assert "[REDACTED]" in req.reason
    assert len(req.reason) <= 500 + len("...[truncated]")
    # 事件载荷同样冻结 + 防御复制
    ev = broker.events[0]
    assert ev.etype == "approval.requested"
    with pytest.raises(TypeError):
        ev.payload["approval_id"] = "apv_forge"            # type: ignore[index]
    copy1 = ev.to_payload()
    copy1["approval_id"] = "apv_forge"
    assert ev.to_payload()["approval_id"] == req.approval_id
    # 嵌套事件值同样不可变
    with pytest.raises(TypeError):
        ev.payload["args_redacted"]["meta"]["note"] = "x"  # type: ignore[index]
    # reason 经决议进入 detail 时同样被 sanitize（限长）
    broker.resolve(req.approval_id, ApprovalDecisionKind.DENY,
                   reason="Y" * 5000 + " token=leak")
    decided = [e for e in broker.events if e.etype == "approval.decided"][0]
    payload = decided.to_payload()
    assert len(payload["detail"]) <= 500 + len("...[truncated]")
    assert "leak" not in payload["detail"]


# ================================================================ P8. permit 封闭 ALLOW→tool.run 撤销 TOCTOU
def test_patch8_permit_closes_revocation_toctou():
    ws = _grant_ws()
    # (a) grant 路径：ALLOW 后、tool.run 前撤销 grant → permit 消费失败 → 零 tool call
    c_pre = _contract(policy_kind="pre_approved_scoped")
    broker, gate, _ = _make_pair(c_pre)
    grant = _create_grant(broker, c_pre)
    kw = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
              contract=c_pre,
              pm_decision=PermissionDecision(True, "task_authorization:t",
                                             Permission.L1_LOW_WRITE),
              backend_capability_ids=("cap.filesystem",))
    r = gate.check_step(**kw)
    assert r.verdict == GateVerdict.ALLOW and r.permit is not None
    broker.revoke_grant(grant.grant_id, reason="user revoked in between")   # TOCTOU 窗口内撤销
    outcome = broker.consume_permit(r.permit, tool="fs.write_text",
                                    capability="cap.filesystem",
                                    args={"path": "C:/ws/work/o.md", "content": "x"})
    assert not outcome.ok, "撤销必须在该工具边界前生效（permit 复核失败）"
    # (b) approve_session 路径：ALLOW 后撤销决议 → permit 消费失败
    c_each = _contract(policy_kind="approval_required_each_step")
    broker_b, gate_b, _ = _make_pair(c_each)
    kw_b = dict(kw, contract=c_each, run_id="run_p8")
    rb = gate_b.check_step(wait_for_approval=False, **kw_b)
    broker_b.resolve(rb.approval.approval_id, ApprovalDecisionKind.APPROVE_SESSION,
                     user_evidence="lev_1756000000000_deadbeef")
    rb2 = gate_b.check_step(**kw_b)
    assert rb2.verdict == GateVerdict.ALLOW and rb2.permit is not None
    broker_b.revoke(rb2.approval.approval_id, reason="revoke in between")
    assert not broker_b.consume_permit(rb2.permit, tool="fs.write_text",
                                       capability="cap.filesystem",
                                       args={"path": "C:/ws/work/o.md", "content": "x"}).ok
    # (c) approve_once：permit 消费即原子标记；同审批第二个 permit 消费失败
    broker_c, gate_c, _ = _make_pair(c_each)
    kw_c = dict(kw, contract=c_each, run_id="run_p8c")
    rc = gate_c.check_step(wait_for_approval=False, **kw_c)
    broker_c.resolve(rc.approval.approval_id, ApprovalDecisionKind.APPROVE_ONCE)
    rc2 = gate_c.check_step(**kw_c)
    rc3 = gate_c.check_step(**kw_c)   # 同一 approve_once 的第二个 permit
    assert rc2.verdict == GateVerdict.ALLOW and rc3.verdict == GateVerdict.ALLOW
    args_x = {"path": "C:/ws/work/o.md", "content": "x"}
    assert broker_c.consume_permit(rc2.permit, tool="fs.write_text",
                                   capability="cap.filesystem", args=args_x).ok
    assert not broker_c.consume_permit(rc3.permit, tool="fs.write_text",
                                       capability="cap.filesystem", args=args_x).ok
    assert broker_c.is_consumed(rc.approval.approval_id)
    # (d) 伪造/篡改 permit 全变体 → 拒绝
    args_r = {"path": "C:/ws/docs/a.md"}
    c_or = _contract(policy_kind="approval_required_on_risk_level")
    broker_d, gate_d, _ = _make_pair(c_or)
    kw_d = dict(tool="fs.read_file", args=args_r, contract=c_or,
                pm_decision=PermissionDecision(True, "auto", Permission.L0_READ),
                backend_capability_ids=("cap.filesystem",))
    rd = gate_d.check_step(**kw_d)
    assert rd.verdict == GateVerdict.ALLOW and rd.permit is not None
    # d1 短合法窗口但非本 broker 签发（随机 permit_id）→ 拒绝
    forged = ToolPermit(
        permit_id="pmt_" + "0" * 12, gate_id=rd.permit.gate_id, tool="fs.read_file",
        capability="cap.filesystem", operation_digest=broker_d.operation_digest(args_r),
        contract_id=c_or.contract_id, contract_hash=c_or.content_hash, run_id="",
        not_before=0.0, valid_until=100.0)
    assert not broker_d.consume_permit(forged, tool="fs.read_file",
                                       capability="cap.filesystem", args=args_r).ok
    # d2 已知 ID 篡改任意字段（tool）→ 拒绝
    tampered_tool = dataclasses.replace(rd.permit, tool="fs.write_text")
    assert not broker_d.consume_permit(tampered_tool, tool="fs.write_text",
                                       capability="cap.filesystem", args=args_r).ok
    # d3 已知 ID 篡改时间窗（valid_until 偏移，仍在 TTL 内）→ 拒绝
    tampered_window = dataclasses.replace(rd.permit, valid_until=rd.permit.valid_until - 1)
    assert not broker_d.consume_permit(tampered_window, tool="fs.read_file",
                                       capability="cap.filesystem", args=args_r).ok
    # d4 超长 ToolPermit 窗口构造拒绝（> MAX_PERMIT_TTL_SECONDS）
    with pytest.raises(ApprovalStateError, match="超长"):
        ToolPermit(permit_id="pmt_" + "1" * 12, gate_id="gate_" + "1" * 8,
                   tool="fs.read_file", capability="cap.filesystem",
                   operation_digest=broker_d.operation_digest(args_r),
                   contract_id=c_or.contract_id, contract_hash=c_or.content_hash, run_id="",
                   not_before=0.0, valid_until=1e12)
    # (e) 身份复核：同 permit 换真实 tool/args/capability → 拒绝（禁止自证）
    assert broker_d.consume_permit(rd.permit, tool="fs.write_text",
                                   capability="cap.filesystem", args=args_r).ok is False
    assert broker_d.consume_permit(rd.permit, tool="fs.read_file",
                                   capability="cap.documents", args=args_r).ok is False
    assert broker_d.consume_permit(rd.permit, tool="fs.read_file",
                                   capability="cap.filesystem",
                                   args={"path": "C:/ws/docs/OTHER.md"}).ok is False
    # 真实身份 → 成功（permit 此时仍有效）
    assert broker_d.consume_permit(rd.permit, tool="fs.read_file",
                                   capability="cap.filesystem", args=args_r).ok
    # (f) permit TTL：超窗消费失败
    clock = FakeClock()
    broker_f, gate_f, _ = _make_pair(c_or, broker_kw={"clock": clock},
                                     gate_kw={"permit_ttl_seconds": 5})
    rf = gate_f.check_step(**kw_d)
    assert rf.verdict == GateVerdict.ALLOW
    clock.advance(6)
    assert not broker_f.consume_permit(rf.permit, tool="fs.read_file",
                                       capability="cap.filesystem", args=args_r).ok


# ================================================================ P2A. 任意 producer 不可签发 permit
def test_patch8b_issue_permit_requires_gate_seal():
    c = _contract(policy_kind="approval_required_on_risk_level")
    broker, gate, _ = _make_pair(c)
    args_r = {"path": "C:/ws/docs/a.md"}
    # 无 seal（broker 构造时未注入）→ 一律不可签发
    no_seal = _make_broker()
    with pytest.raises(ApprovalStateError):
        no_seal.issue_permit(GateSeal(), gate_id="gate_" + "f" * 8, tool="fs.read_file",
                             capability="cap.filesystem", args=args_r, run_id="r",
                             contract_id=c.contract_id, contract_hash=c.content_hash)
    # 错误 seal 对象（非本 broker 持有）→ 一律不可签发（对象身份校验）
    with pytest.raises(ApprovalStateError):
        broker.issue_permit(GateSeal(), gate_id="gate_" + "f" * 8, tool="fs.read_file",
                            capability="cap.filesystem", args=args_r, run_id="r",
                            contract_id=c.contract_id, contract_hash=c.content_hash)
    # 公开 issue 路径只能经 Gate 的 ALLOW 判定出现（无 approval/grant 来源的 permit
    # 同样绑定 gate_id + contract_id + content_hash + run_id）
    r = gate.check_step(tool="fs.read_file", args=args_r, contract=c,
                        pm_decision=PermissionDecision(True, "auto", Permission.L0_READ),
                        backend_capability_ids=("cap.filesystem",), run_id="run_ok")
    assert r.verdict == GateVerdict.ALLOW and r.permit is not None
    assert r.permit.gate_id == gate.gate_id
    assert r.permit.contract_id == c.contract_id
    assert r.permit.contract_hash == c.content_hash
    assert r.permit.run_id == "run_ok"
    # 未经四层 Gate 判定而手工构造的 permit（gate_id 任意）→ 消费必拒
    raw_forged = ToolPermit(permit_id="pmt_" + "9" * 12, gate_id="gate_" + "9" * 8,
                            tool="fs.read_file", capability="cap.filesystem",
                            operation_digest=broker.operation_digest(args_r),
                            contract_id=c.contract_id, contract_hash=c.content_hash,
                            run_id="run_ok", not_before=0.0, valid_until=100.0)
    assert not broker.consume_permit(raw_forged, tool="fs.read_file",
                                     capability="cap.filesystem", args=args_r).ok


# ================================================================ P2B. consume_permit 必填真实身份
def test_patch8c_consume_permit_requires_real_identity():
    c = _contract(policy_kind="approval_required_on_risk_level")
    broker, gate, _ = _make_pair(c)
    args_r = {"path": "C:/ws/docs/a.md"}
    r = gate.check_step(tool="fs.read_file", args=args_r, contract=c,
                        pm_decision=PermissionDecision(True, "auto", Permission.L0_READ),
                        backend_capability_ids=("cap.filesystem",), run_id="run_id")
    assert r.verdict == GateVerdict.ALLOW and r.permit is not None
    # 缺真实 identity（tool/capability/args 任一缺失）→ TypeError（必填）
    with pytest.raises(TypeError):
        broker.consume_permit(r.permit)                                          # type: ignore[call-arg]
    with pytest.raises(TypeError):
        broker.consume_permit(r.permit, tool="fs.read_file", capability="cap.filesystem")
    # 禁止调用方传 permit 自身字段完成自证：伪造的 operation_digest（取自 permit）
    # 无法在 consume 中作为"身份"——consume 只接受原始 args 并内部重算
    assert broker.consume_permit(r.permit, tool="fs.read_file", capability="cap.filesystem",
                                 args=args_r).ok
    # 内部重算一致性：permit.operation_digest == broker 对原始 args 的 HMAC
    assert r.permit.operation_digest == broker.operation_digest(args_r)


# ================================================================ P9. gate 只接受可信绑定 + 16A 完整 hash 校验的契约
def test_patch9_gate_requires_bound_hash_verified_contract():
    c = _contract(policy_kind="approval_required_each_step")
    broker, gate, _ = _make_pair(c)
    harness = _Harness(gate, broker)
    pm = PermissionDecision(True, "task_authorization:t", Permission.L1_LOW_WRITE)
    caps = ("cap.filesystem",)
    kw = dict(tool="fs.write_text", args={"path": "C:/ws/work/o.md", "content": "x"},
              pm_decision=pm, backend_capability_ids=caps, wait_for_approval=False)
    # 反例锁定 1：篡改投影（拓宽 write_roots，hash 不变）→ 拒绝，零请求零 tool call
    tampered = _projection(policy_kind="approval_required_each_step")
    tampered["workspace_scope"] = {"read_roots": ["C:/ws/docs"],
                                   "write_roots": ["C:/ws/work", "C:/outside"]}
    r = harness.run_step(contract=tampered, **kw)
    assert r.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    assert harness.tool_calls == 0 and broker.events == []
    # 反例锁定 2：去掉 content_hash（from_dict 从不重新签名）→ 拒绝
    no_hash = _projection(policy_kind="approval_required_each_step")
    del no_hash["content_hash"]
    r2 = harness.run_step(contract=no_hash, **kw)
    assert r2.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    # 反例锁定 3：任意手拼 projection（自由字段）→ 拒绝
    r3 = harness.run_step(contract={"contract_id": "wc_forge", "allowed_capabilities": ["cap.filesystem"],
                                    "workspace_scope": {"read_roots": ["C:/"], "write_roots": ["C:/"]}},
                          **kw)
    assert r3.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    # 反例锁定 4（Patch 2 fix 5）：**自签但范围更宽**的新 WorkContract（同 id 新 hash）
    # → 拒绝（content_hash 只作完整性校验；授权真实性来自 expected 绑定）
    c_wide = _contract(policy_kind="approval_required_each_step",
                       write_roots=("C:/ws/work", "C:/outside"))
    assert c_wide.contract_id == c.contract_id and c_wide.content_hash != c.content_hash
    r4 = harness.run_step(contract=c_wide, **kw)
    assert r4.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    # 反例锁定 5：非契约类型 → 拒绝
    r5 = harness.run_step(contract="wc_16d_test", **kw)   # type: ignore[arg-type]
    assert r5.verdict == GateVerdict.DENY_CONTRACT_SCOPE
    assert harness.tool_calls == 0
    # 合法路径：WorkContract 实例（构造即校验 hash）与经 from_dict 复核的投影均可用
    r6 = harness.run_step(contract=c, **dict(kw, run_id="run_p9a"))
    assert r6.verdict == GateVerdict.APPROVAL_PENDING
    r7 = harness.run_step(contract=_projection(policy_kind="approval_required_each_step"),
                          **dict(kw, run_id="run_p9b"))
    assert r7.verdict == GateVerdict.APPROVAL_PENDING
