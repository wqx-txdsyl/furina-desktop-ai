# -*- coding: utf-8 -*-
"""Phase 16E — Backend Event Normalization 测试（backend-neutral 信封 + 工作域状态机）。

任务书 §7 十二项最低锁定：
1. 完整合法转移表（全部 14 个 WorkExecutionState + TOOL_RUNNING 子相位）；
2. 非法转移 fail-safe（typed diagnostic + 零状态变更）；
3. completed → BACKEND_DONE_UNVERIFIED，**永不 VERIFIED**（VERIFIED 只预留 16F）；
4. duplicate event_id 幂等 / 乱序不得回退终态；
5. 未知外部事件 typed 可观察但非权威（绝不产生成功转移）；
6. approval 与 cancellation 路径；
7. disconnect → UNKNOWN 策略边界（reconnect 不得复活）；
8. critical 事件分类（critical/coalescible/droppable + 背压策略纯声明）；
9. payload 脱敏与大小上限（秘密键 / 控制字符 / 限长 / 有界 + 载荷不可变）；
10. WorkExecutionState **零写入 C7/C6**（导入面无 cognition 依赖 + 真实 store 零行）；
11. Native 与 Hermes-shaped fixture 归一为相同语义；
12. 同一事件流重复重放结果完全一致（确定性）。

额外锁定：信封字段校验 / reducer run_id+contract_id 身份绑定 / sequence 与
processed_count 观测 / 信封载荷防御复制。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pytest

from furina.agent.backend import BackendEvent
from furina.agent.events import (
    LEGAL_TRANSITIONS,
    BackendEventNormalizer,
    EventBackpressurePolicy,
    EventKind,
    EventNormalizationError,
    EventPriority,
    NormalizedEvent,
    ReduceResult,
    WorkExecutionError,
    WorkExecutionReducer,
    WorkExecutionState,
    classify_priority,
    map_kind,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

BACKEND = "native"
CONTRACT = "wc_16e_test_001"
RUN = "run_16e_001"


# ================================================================ 工具
def _mk(kind: EventKind, event_id: str, sequence: int = 0,
        payload: Optional[Mapping[str, Any]] = None,
        backend_id: str = BACKEND, contract_id: str = CONTRACT,
        run_id: str = RUN) -> NormalizedEvent:
    """直接构造 canonical 信封（绕过 normalizer，供 reducer 表测试）。"""
    return NormalizedEvent(
        event_id=event_id, backend_id=backend_id, contract_id=contract_id,
        run_id=run_id, sequence=sequence, occurred_at=1000.0, received_at=1000.0,
        kind=kind, payload=payload or {}, provenance="test",
    )


def _plain(obj: Any) -> Any:
    """解冻：MappingProxyType → dict，tuple → list（便于断言）。"""
    if isinstance(obj, Mapping):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [_plain(v) for v in obj]
    return obj


def _fresh():
    """fresh normalizer + reducer（共享同一 run/契约身份）。"""
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    return n, r


def _feed(n: BackendEventNormalizer, r: WorkExecutionReducer,
          raws: Sequence[Mapping[str, Any]]) -> List[ReduceResult]:
    return [r.reduce(n.normalize(raw)) for raw in raws]


def _tokens(r: WorkExecutionReducer, *kinds: EventKind) -> List[ReduceResult]:
    """按 kind 顺序驱动给定 reducer（event_id 自动去重；sequence 递增）。"""
    out: List[ReduceResult] = []
    for i, k in enumerate(kinds):
        out.append(r.reduce(_mk(k, event_id=f"ev_{i}", sequence=i)))
    return out


def _drive(r: WorkExecutionReducer, state: WorkExecutionState) -> None:
    """按 _PATH_TO 驱动 reducer 到指定 primary 状态（含 outcome 依赖事件）。"""
    tokens = _PATH_TO[state]
    for i, tok in enumerate(tokens):
        ev = NormalizedEvent(
            event_id=f"s{i}_{state.value}", backend_id=BACKEND, contract_id=CONTRACT,
            run_id=RUN, sequence=i, occurred_at=1000.0, received_at=1000.0,
            kind=_SPECIAL_TOKENS[tok][0] if tok in _SPECIAL_TOKENS else map_kind(tok),
            payload=_SPECIAL_TOKENS[tok][1] if tok in _SPECIAL_TOKENS else {},
            provenance="test",
        )
        res = r.reduce(ev)
        assert res.applied, f"驱动到 {state.value} 失败 at {tok}: {res.diagnostic}"
    assert r.view.primary is state, f"驱动到 {state.value} 失败：实际 {r.view.primary}"


#: 各 primary 状态的驱动路径（token 词表）。
_PATH_TO: Dict[WorkExecutionState, Tuple[str, ...]] = {
    WorkExecutionState.IDLE: (),
    WorkExecutionState.STARTING: ("queued",),
    WorkExecutionState.RUNNING: ("queued", "running"),
    WorkExecutionState.WAITING_PERMISSION: ("queued", "running", "approval.requested"),
    WorkExecutionState.BLOCKED_APPROVAL: (
        "queued", "running", "approval.requested", "approval.resolved"),
    WorkExecutionState.CANCELLING: ("queued", "stop.requested"),
    WorkExecutionState.BACKEND_DONE_UNVERIFIED: ("queued", "running", "completed"),
    WorkExecutionState.VERIFYING: ("queued", "running", "completed", "vb.start"),
    WorkExecutionState.REPAIRING: ("queued", "running", "completed", "vb.start", "vb.repair"),
    WorkExecutionState.VERIFIED: (
        "queued", "running", "completed", "vb.start", "vb.verified"),
    WorkExecutionState.CANCELLED: ("queued", "running", "cancelled"),
    WorkExecutionState.FAILED: ("queued", "running", "failed"),
    WorkExecutionState.UNKNOWN: ("queued", "running", "transport.disconnected"),
}

#: 驱动路径用的特殊 token → (kind, payload)。
_SPECIAL_TOKENS = {
    "approval.resolved": (EventKind.APPROVAL_RESOLVED, {"outcome": "deny"}),
    "vb.start": (EventKind.VERIFICATION_BOUNDARY, {"outcome": "start"}),
    "vb.repair": (EventKind.VERIFICATION_BOUNDARY, {"outcome": "repair"}),
    "vb.verified": (EventKind.VERIFICATION_BOUNDARY, {"outcome": "verified"}),
}


def _drive_raw(token: str) -> Mapping[str, Any]:
    if token in _SPECIAL_TOKENS:
        kind, payload = _SPECIAL_TOKENS[token]
        return {"type": kind.value, "payload": dict(payload)}
    return {"type": token}


def _drive(r: WorkExecutionReducer, state: WorkExecutionState) -> None:
    """按 _PATH_TO 驱动 reducer 到指定 primary 状态（含 outcome 依赖事件）。"""
    tokens = _PATH_TO[state]
    for i, tok in enumerate(tokens):
        ev = NormalizedEvent(
            event_id=f"s{i}_{state.value}", backend_id=BACKEND, contract_id=CONTRACT,
            run_id=RUN, sequence=i, occurred_at=1000.0, received_at=1000.0,
            kind=_SPECIAL_TOKENS[tok][0] if tok in _SPECIAL_TOKENS else map_kind(tok),
            payload=_SPECIAL_TOKENS[tok][1] if tok in _SPECIAL_TOKENS else {},
            provenance="test",
        )
        res = r.reduce(ev)
        assert res.applied, f"驱动到 {state.value} 失败 at {tok}: {res.diagnostic}"
    assert r.view.primary is state, f"驱动到 {state.value} 失败：实际 {r.view.primary}"


# ================================================================ 1. 完整合法转移表
def test_01_full_legal_transition_table():
    """§7.1：逐行验证 LEGAL_TRANSITIONS（每个 (from, kind) → 期望 target）。"""
    for src, row in LEGAL_TRANSITIONS.items():
        for kind, target in row.items():
            r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
            _drive(r, src)
            res = r.reduce(_mk(kind, event_id=f"t_{src.value}_{kind.value}"))
            assert res.applied, f"{src.value} --{kind.value}--> 未应用: {res.diagnostic}"
            assert res.view.primary is target, \
                f"{src.value} --{kind.value}--> 期望 {target.value}，实际 {res.view.primary.value}"


def test_01b_outcome_dependent_approval_paths():
    """§7.1：approval.resolved outcome 分支（approve/deny/timeout）。"""
    # WAITING_PERMISSION: approve → RUNNING；deny/timeout → BLOCKED_APPROVAL
    for outcome, target in (("approve", WorkExecutionState.RUNNING),
                            ("deny", WorkExecutionState.BLOCKED_APPROVAL),
                            ("timeout", WorkExecutionState.BLOCKED_APPROVAL)):
        r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        _drive(r, WorkExecutionState.WAITING_PERMISSION)
        res = r.reduce(_mk(EventKind.APPROVAL_RESOLVED, "ap1", payload={"outcome": outcome}))
        assert res.applied and res.view.primary is target
    # BLOCKED_APPROVAL: approve → RUNNING；再次 deny → 保持 BLOCKED（合法自环）
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.BLOCKED_APPROVAL)
    res = r.reduce(_mk(EventKind.APPROVAL_RESOLVED, "ap2", payload={"outcome": "approve"}))
    assert res.applied and res.view.primary is WorkExecutionState.RUNNING
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r2, WorkExecutionState.BLOCKED_APPROVAL)
    res2 = r2.reduce(_mk(EventKind.APPROVAL_RESOLVED, "ap3", payload={"outcome": "deny"}))
    assert res2.applied and res2.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    assert res2.diagnostic == "approval_already_blocked"


def test_01c_outcome_dependent_verification_boundary():
    """§7.1：verification.boundary 分支（16F 预留通道）。"""
    # BDU: start → VERIFYING；repair → REPAIRING
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.BACKEND_DONE_UNVERIFIED)
    res = r.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "vb1", payload={"outcome": "start"}))
    assert res.applied and res.view.primary is WorkExecutionState.VERIFYING
    # VERIFYING: verified → VERIFIED；failed → FAILED；repair → REPAIRING
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r2, WorkExecutionState.VERIFYING)
    res2 = r2.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "vb2", payload={"outcome": "verified"}))
    assert res2.applied and res2.view.primary is WorkExecutionState.VERIFIED
    r3 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r3, WorkExecutionState.VERIFYING)
    res3 = r3.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "vb3", payload={"outcome": "failed"}))
    assert res3.applied and res3.view.primary is WorkExecutionState.FAILED
    # REPAIRING: start → VERIFYING（重验）；failed → FAILED
    r4 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r4, WorkExecutionState.REPAIRING)
    res4 = r4.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "vb4", payload={"outcome": "start"}))
    assert res4.applied and res4.view.primary is WorkExecutionState.VERIFYING


def test_01d_tool_running_subphase_transitions():
    """§7.1/§7.4：TOOL_RUNNING 子相位（primary 不丢失）。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.RUNNING)
    # tool.started → 子相位激活，primary 仍是 RUNNING
    res = r.reduce(_mk(EventKind.TOOL_STARTED, "t1", payload={"tool": "fs.read_file"}))
    assert res.applied
    assert res.view.state is WorkExecutionState.TOOL_RUNNING
    assert res.view.primary is WorkExecutionState.RUNNING
    assert res.view.tool_subphase is True and res.view.active_tool == "fs.read_file"
    # tool.progress → 子相位保持（tick）
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "t2"))
    assert res.applied and res.view.state is WorkExecutionState.TOOL_RUNNING
    assert res.view.primary is WorkExecutionState.RUNNING
    # tool.completed → 子相位退出，primary 恢复可见
    res = r.reduce(_mk(EventKind.TOOL_COMPLETED, "t3"))
    assert res.applied
    assert res.view.state is WorkExecutionState.RUNNING
    assert res.view.tool_subphase is False and res.view.active_tool == ""
    # primary 变化会清空子相位（completed 结束工具）
    r.reduce(_mk(EventKind.TOOL_STARTED, "t4", payload={"tool": "fs.write"}))
    assert r.view.state is WorkExecutionState.TOOL_RUNNING
    res = r.reduce(_mk(EventKind.BACKEND_COMPLETED, "t5"))
    assert res.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    assert res.view.tool_subphase is False and res.view.state is res.view.primary


# ================================================================ 2. 非法转移 fail-safe
def test_02_illegal_transition_fail_safe():
    """§7.2：非法转移返回 typed diagnostic 且零状态变更（快照完全不变）。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.IDLE)
    cases = [
        (WorkExecutionState.IDLE, EventKind.RUN_STARTED),
        (WorkExecutionState.IDLE, EventKind.BACKEND_COMPLETED),   # 未接受即完成
        (WorkExecutionState.IDLE, EventKind.TOOL_STARTED),        # 未运行即工具
        (WorkExecutionState.STARTING, EventKind.RUN_ACCEPTED),    # 重复接受
        (WorkExecutionState.STARTING, EventKind.TOOL_STARTED),
        (WorkExecutionState.RUNNING, EventKind.RUN_ACCEPTED),     # 已接受后再接受
        (WorkExecutionState.RUNNING, EventKind.VERIFICATION_BOUNDARY),  # 未完成即校验
        (WorkExecutionState.WAITING_PERMISSION, EventKind.TOOL_STARTED),
        (WorkExecutionState.WAITING_PERMISSION, EventKind.RUN_STARTED),
        (WorkExecutionState.BACKEND_DONE_UNVERIFIED, EventKind.BACKEND_FAILED),  # 完成后再失败
        (WorkExecutionState.BACKEND_DONE_UNVERIFIED, EventKind.RUN_STARTED),
        (WorkExecutionState.BACKEND_DONE_UNVERIFIED, EventKind.BACKEND_CANCELLED),
        (WorkExecutionState.CANCELLING, EventKind.BACKEND_COMPLETED),  # 停止中完成
        (WorkExecutionState.CANCELLING, EventKind.RUN_STARTED),
        (WorkExecutionState.VERIFYING, EventKind.BACKEND_COMPLETED),
        (WorkExecutionState.VERIFYING, EventKind.RUN_STARTED),
        (WorkExecutionState.REPAIRING, EventKind.TOOL_STARTED),
    ]
    for src, kind in cases:
        r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        _drive(r, src)
        before = r.view
        res = r.reduce(_mk(kind, event_id=f"il_{src.value}_{kind.value}"))
        assert not res.applied, f"{src.value} --{kind.value}--> 不应应用"
        assert res.diagnostic.startswith("illegal_transition:"), \
            f"{src.value} --{kind.value}--> diagnostic={res.diagnostic!r}"
        assert res.view is before
        assert res.view.primary is src
        assert res.view.processed_count == before.processed_count
        assert res.view.max_sequence == before.max_sequence


def test_02b_tool_subphase_illegal_cases():
    """§7.2：子相位内的非法序列（tool 未开始即完成 / 工具已激活再开始）。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.RUNNING)
    res = r.reduce(_mk(EventKind.TOOL_COMPLETED, "c1"))
    assert not res.applied and res.diagnostic.startswith("illegal_transition:")
    r.reduce(_mk(EventKind.TOOL_STARTED, "c2", payload={"tool": "fs.read_file"}))
    res = r.reduce(_mk(EventKind.TOOL_STARTED, "c3", payload={"tool": "fs.write"}))
    assert not res.applied and res.diagnostic.startswith("illegal_transition:")
    assert res.diagnostic.endswith("tool_already_active")
    assert r.view.active_tool == "fs.read_file"   # 未破坏既有子相位


# ================================================================ 3. completed 永不 VERIFIED
def test_03_completed_never_verified():
    """§7.3：backend completed → BACKEND_DONE_UNVERIFIED，全路径永不 VERIFIED。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    res = _tokens(
        r,
        EventKind.RUN_ACCEPTED, EventKind.RUN_STARTED,
        EventKind.TOOL_STARTED, EventKind.TOOL_COMPLETED, EventKind.BACKEND_COMPLETED)
    assert r.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    for step in res:
        assert step.view.primary is not WorkExecutionState.VERIFIED
    # 任何 backend 词表 token 都无法产生 VERIFIED / VERIFYING
    for tok in ("verified", "verification.boundary", "vb.verified", "verify.done"):
        assert map_kind(tok) is EventKind.UNKNOWN_EVENT, f"{tok!r} 不应映射为权威类型"
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r2, WorkExecutionState.BACKEND_DONE_UNVERIFIED)
    for i, tok in enumerate(("verified", "verification.boundary", "done")):
        ev = n.normalize({"event_id": f"nb{i}", "type": tok})
        assert ev.kind is EventKind.UNKNOWN_EVENT
        res2 = r2.reduce(ev)
        assert res2.applied and not res2.diagnostic
        assert r2.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED   # 未越权
    # VERIFIED 只经 16F 校验边界可达（16E 表内唯一路径）
    r3 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r3, WorkExecutionState.VERIFYING)
    res3 = r3.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "v1", payload={"outcome": "verified"}))
    assert res3.view.primary is WorkExecutionState.VERIFIED


# ================================================================ 4. duplicate / out-of-order
def test_04_duplicate_and_out_of_order():
    """§7.4：duplicate event_id 幂等；乱序不得回退终态。"""
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "e1", "type": "queued"},
        {"event_id": "e2", "type": "running"},
        {"event_id": "e3", "type": "completed"},      # 乱序：跳过 tool 事件
    ])
    assert r.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    # 乱序补投的 running（新 id、旧 seq）→ 非法转移，不破坏现有状态
    before = r.view
    res = r.reduce(n.normalize({"event_id": "e4", "type": "running", "sequence": 1}))
    assert not res.applied and res.diagnostic.startswith("illegal_transition:")
    assert r.view is before
    # duplicate event_id → 幂等 no-op（即使已是终态）
    for _ in range(2):
        res = r.reduce(n.normalize({"event_id": "e3", "type": "completed"}))
        assert not res.applied and res.diagnostic.startswith("duplicate_event:")
        assert r.view is before
    # 终态吸收：到达 FAILED 后，任何新事件（含 reconnect/progress）不得复活
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    n2 = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    _feed(n2, r2, [
        {"event_id": "f1", "type": "queued"},
        {"event_id": "f2", "type": "running"},
        {"event_id": "f3", "type": "failed"},
    ])
    assert r2.view.primary is WorkExecutionState.FAILED
    for i, tok in enumerate(("reconnected", "progress", "completed", "cancelled")):
        res = r2.reduce(n2.normalize({"event_id": f"late{i}", "type": tok}))
        assert not res.applied
        assert res.diagnostic.startswith("terminal_absorbing:")
        assert r2.view.primary is WorkExecutionState.FAILED
        assert r2.view.processed_count == 3     # 终态后零变更


# ================================================================ 5. 未知事件可观察非权威
def test_05_unknown_external_event_observable_non_authoritative():
    """§7.5：未知外部类型 → typed UNKNOWN_EVENT，可观察但绝不产生成功转移。"""
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    ev = n.normalize({"event_id": "u1", "type": "alien.protocol.v9", "payload": {"x": 1}})
    assert ev.kind is EventKind.UNKNOWN_EVENT
    assert ev.terminal is False and ev.critical is False
    # normalizer 绝不抛错（未知输入 fail-open 观察、fail-closed 权威）
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    res = r.reduce(ev)
    assert res.applied and res.diagnostic == ""
    assert r.view.primary is WorkExecutionState.IDLE          # 零转移
    assert r.view.processed_count == 1                         # 但可观察（已计数）
    # 未知事件在任意状态都是无状态变化的观察（含终态——不复活也不报错）
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r2, WorkExecutionState.FAILED)
    res2 = r2.reduce(ev)
    assert res2.applied and r2.view.primary is WorkExecutionState.FAILED
    # BackendEvent 占位形状同样归一为 UNKNOWN（词表外类型）
    be = BackendEvent(backend_id=BACKEND, run_id=RUN, event_type="no_such_kind", payload={})
    ev2 = n.normalize(be)
    assert ev2.kind is EventKind.UNKNOWN_EVENT


# ================================================================ 6. approval / cancellation
def test_06_approval_and_cancellation_paths():
    """§7.6：审批路径与取消路径完整走通。"""
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "a1", "type": "queued"},
        {"event_id": "a2", "type": "running"},
        {"event_id": "a3", "type": "waiting_for_approval", "payload": {"command": "fs.rm"}},
    ])
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    _feed(n, r, [{"event_id": "a4", "type": "approval.resolved", "payload": {"decision": "approve"}}])
    assert r.view.primary is WorkExecutionState.RUNNING
    # 拒绝 → BLOCKED_APPROVAL → 再批准 → RUNNING
    n2, r2 = _fresh()
    _feed(n2, r2, [
        {"event_id": "b1", "type": "queued"},
        {"event_id": "b2", "type": "running"},
        {"event_id": "b3", "type": "waiting_for_approval"},
        {"event_id": "b4", "type": "approval.resolved", "payload": {"decision": "deny"}},
    ])
    assert r2.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    _feed(n2, r2, [{"event_id": "b5", "type": "approval.resolved", "payload": {"decision": "approve"}}])
    assert r2.view.primary is WorkExecutionState.RUNNING
    # 取消路径：stop.requested → CANCELLING → cancelled → CANCELLED
    n3, r3 = _fresh()
    _feed(n3, r3, [
        {"event_id": "c1", "type": "queued"},
        {"event_id": "c2", "type": "running"},
        {"event_id": "c3", "type": "stop.requested"},
    ])
    assert r3.view.primary is WorkExecutionState.CANCELLING
    _feed(n3, r3, [{"event_id": "c4", "type": "cancelled"}])
    assert r3.view.primary is WorkExecutionState.CANCELLED
    assert r3.view.is_terminal
    # 停止中 backend 失败 → FAILED（终态如实落地）
    n4, r4 = _fresh()
    _feed(n4, r4, [
        {"event_id": "d1", "type": "queued"},
        {"event_id": "d2", "type": "running"},
        {"event_id": "d3", "type": "stopping"},
        {"event_id": "d4", "type": "failed"},
    ])
    assert r4.view.primary is WorkExecutionState.FAILED


# ================================================================ 7. disconnect → UNKNOWN
def test_07_disconnect_unknown_policy_boundary():
    """§7.7：断开 → UNKNOWN（吸收）；reconnect 不得复活终态/UNKNOWN。"""
    for src in (WorkExecutionState.RUNNING, WorkExecutionState.STARTING,
                WorkExecutionState.WAITING_PERMISSION,
                WorkExecutionState.BACKEND_DONE_UNVERIFIED):
        r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        _drive(r, src)
        res = r.reduce(_mk(EventKind.TRANSPORT_DISCONNECTED, f"dc_{src.value}"))
        assert res.applied and res.view.primary is WorkExecutionState.UNKNOWN
        # UNKNOWN 吸收：reconnect 不得把状态救回来
        res2 = r.reduce(_mk(EventKind.TRANSPORT_RECONNECTED, f"rc_{src.value}"))
        assert not res2.applied and res2.diagnostic.startswith("terminal_absorbing:")
        assert r.view.primary is WorkExecutionState.UNKNOWN
    # 终态后 disconnect 同样吸收（不改变终态）
    r3 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r3, WorkExecutionState.CANCELLED)
    res3 = r3.reduce(_mk(EventKind.TRANSPORT_DISCONNECTED, "dc3"))
    assert not res3.applied and res3.diagnostic.startswith("terminal_absorbing:")
    assert r3.view.primary is WorkExecutionState.CANCELLED
    # 运行中 reconnect 是合法无状态变化观察（非权威）
    r4 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r4, WorkExecutionState.RUNNING)
    res4 = r4.reduce(_mk(EventKind.TRANSPORT_RECONNECTED, "rc4"))
    assert res4.applied and res4.view.primary is WorkExecutionState.RUNNING


# ================================================================ 8. critical 分类
def test_08_critical_event_classification():
    """§7.8：critical/coalescible/droppable 分类 + 背压策略（纯声明）。"""
    critical = {EventKind.BACKEND_COMPLETED, EventKind.BACKEND_FAILED,
                EventKind.BACKEND_CANCELLED, EventKind.APPROVAL_REQUESTED,
                EventKind.APPROVAL_RESOLVED, EventKind.STOP_REQUESTED,
                EventKind.STOPPING, EventKind.TRANSPORT_DISCONNECTED,
                EventKind.VERIFICATION_BOUNDARY, EventKind.RUN_ACCEPTED,
                EventKind.RUN_STARTED, EventKind.PROTOCOL_ERROR}
    droppable = {EventKind.TOOL_PROGRESS}
    for k in EventKind:
        pri = classify_priority(k)
        if k in critical:
            assert pri is EventPriority.CRITICAL, k
        elif k in droppable:
            assert pri is EventPriority.DROPPABLE, k
        else:
            assert pri is EventPriority.COALESCIBLE, k
    # 信封 critical/terminal 派生字段
    assert _mk(EventKind.BACKEND_COMPLETED, "x1").critical is True
    assert _mk(EventKind.BACKEND_COMPLETED, "x2").terminal is True
    assert _mk(EventKind.TOOL_PROGRESS, "x3").critical is False
    assert _mk(EventKind.TOOL_PROGRESS, "x4").terminal is False
    # 背压策略：critical 永不丢弃；压力下只丢 droppable；coalescible 可合并
    for k in critical:
        assert EventBackpressurePolicy.never_droppable(k)
        assert not EventBackpressurePolicy.drop_allowed(k, under_pressure=True)
    assert EventBackpressurePolicy.drop_allowed(EventKind.TOOL_PROGRESS, under_pressure=True)
    assert not EventBackpressurePolicy.drop_allowed(EventKind.TOOL_PROGRESS, under_pressure=False)
    assert not EventBackpressurePolicy.drop_allowed(EventKind.BACKEND_COMPLETED, under_pressure=True)
    assert EventBackpressurePolicy.coalesce_allowed(EventKind.TOOL_STARTED)
    assert EventBackpressurePolicy.coalesce_allowed(EventKind.TOOL_COMPLETED)
    assert EventBackpressurePolicy.coalesce_allowed(EventKind.UNKNOWN_EVENT)
    assert not EventBackpressurePolicy.coalesce_allowed(EventKind.BACKEND_COMPLETED)


# ================================================================ 9. payload 脱敏与有界
def test_09_payload_redaction_and_bounded_size():
    """§7.9：秘密脱敏 / 控制字符 / 限长 / 大小上限 / 载荷不可变。"""
    ev = _mk(EventKind.TOOL_STARTED, "p1", payload={
        "tool": "web.request",
        "args": {
            "url": "https://example.com",
            "password": "hunter2",
            "api_key": "sk-abc123",
            "authorization": "Bearer xyz",
            "access_token": "tok_9",
            "client_secret": "s3cr3t",
            "token_count": 42,          # 非秘密键不得误伤
            "author": "furina",         # 含 auth 子串的键不得误伤
            "note": "ok\x00control\x1fchars",
            "long": "x" * 1000,
        },
    })
    p = _plain(ev.payload)
    assert p["args"]["password"] == "[REDACTED]"
    assert p["args"]["api_key"] == "[REDACTED]"
    assert p["args"]["authorization"] == "[REDACTED]"
    assert p["args"]["access_token"] == "[REDACTED]"
    assert p["args"]["client_secret"] == "[REDACTED]"
    assert p["args"]["token_count"] == 42
    assert p["args"]["author"] == "furina"
    assert p["args"]["url"] == "https://example.com"
    assert "control" in p["args"]["note"] and "\x00" not in p["args"]["note"]
    assert len(p["args"]["long"]) == 256          # 字符串限长
    # 超限载荷（大量中长字符串累积超过 byte 预算）→ 有界 _truncated，绝不放大
    big = {"items": ["y" * 250 for _ in range(300)]}
    ev2 = _mk(EventKind.TOOL_PROGRESS, "p2", payload=big)
    p2 = _plain(ev2.payload)
    assert p2.get("_truncated") is True
    assert p2.get("original_bytes", 0) > p2.get("byte_budget", 0)
    # 载荷不可变（递归冻结）
    with pytest.raises(TypeError):
        ev.payload["args"] = {}      # type: ignore[index]
    with pytest.raises(TypeError):
        ev.payload["args"]["url"] = "hacked"   # type: ignore[index]
    # 非 JSON-safe 对象被丢弃（不把任意 repr 泄入信封）
    ev3 = _mk(EventKind.TOOL_PROGRESS, "p3", payload={"blob": object()})
    assert "blob" not in _plain(ev3.payload)


# ================================================================ 10. C7/C6 零写入
def test_10a_events_package_imports_no_cognition_db():
    """§7.10a：导入 events 包不得拉入 furina.cognition（无 DB/schema 依赖）。"""
    code = ("import sys; import furina.agent.events; "
            "sys.exit(1 if 'furina.cognition' in sys.modules else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT),
                       capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, f"events 包导入不应依赖 furina.cognition: {r.stderr}"


def test_10b_no_workexecution_state_written_to_c7_c6(tmp_path):
    """§7.10b：跑完完整归一+归约会话后，真实 C6/C7 store 零行。"""
    import sqlite3

    from furina.cognition.hub import CognitionHub

    db_path = tmp_path / "cog.db"
    CognitionHub(db_path)   # 构造即建 schema（C6/C7 表存在但零行）
    # 完整会话：正常完成 / 审批 / 取消 / 失败 / 断开 / 校验边界 全部跑一遍
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    stream = [
        {"event_id": "z1", "type": "queued"},
        {"event_id": "z2", "type": "running"},
        {"event_id": "z3", "type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"event_id": "z4", "type": "tool.progress", "payload": {"delta": "..."}},
        {"event_id": "z5", "type": "tool.completed"},
        {"event_id": "z6", "type": "waiting_for_approval"},
        {"event_id": "z7", "type": "approval.resolved", "payload": {"decision": "approve"}},
        {"event_id": "z8", "type": "completed"},
    ]
    for raw in stream:
        r.reduce(n.normalize(raw))
    assert r.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    # 另跑一条失败与一条取消与一条断开
    for suffix, tokens in (("f", ("queued", "running", "failed")),
                           ("c", ("queued", "running", "cancelled")),
                           ("d", ("queued", "running", "transport.disconnected"))):
        n2 = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT,
                                    run_id=f"run_{suffix}")
        r2 = WorkExecutionReducer(f"run_{suffix}", CONTRACT, backend_id=BACKEND)
        for i, tok in enumerate(tokens):
            r2.reduce(n2.normalize({"event_id": f"{suffix}{i}", "type": tok}))
    conn = sqlite3.connect(db_path)
    try:
        life = conn.execute("SELECT COUNT(*) FROM life_events").fetchone()[0]
        tasks = conn.execute("SELECT COUNT(*) FROM agent_tasks").fetchone()[0]
        steps = conn.execute("SELECT COUNT(*) FROM agent_task_steps").fetchone()[0]
    finally:
        conn.close()
    assert life == 0, "16E 工作域事件不得写入 C6 life_events"
    assert tasks == 0, "16E 工作域状态不得写入 C7 agent_tasks"
    assert steps == 0, "16E 工作域状态不得写入 C7 agent_task_steps"


# ================================================================ 11. Native/Hermes 同语义
def test_11_native_and_hermes_shaped_same_semantics():
    """§7.11：Native 词表与 Hermes-shaped fixture 归一为相同语义。"""
    # Native 形状（backend 协议词表）
    native = [
        {"event_id": "n1", "type": "run.submitted"},
        {"event_id": "n2", "type": "run.started"},
        {"event_id": "n3", "type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"event_id": "n4", "type": "tool.completed"},
        {"event_id": "n5", "type": "backend.completed"},
    ]
    # Hermes-shaped fixture（_set_run_status 词表 + SSE 事件面）
    hermes = [
        {"event_id": "h1", "status": "queued"},
        {"event_id": "h2", "status": "running"},
        {"event_id": "h3", "type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"event_id": "h4", "type": "tool.completed"},
        {"event_id": "h5", "type": "run.completed", "payload": {"completed": True}},
    ]
    n1, r1 = _fresh()
    n2, r2 = _fresh()
    res1 = _feed(n1, r1, native)
    res2 = _feed(n2, r2, hermes)
    states1 = [(x.view.primary, x.view.state) for x in res1]
    states2 = [(x.view.primary, x.view.state) for x in res2]
    assert states1 == states2, f"Native/Hermes 语义不一致：{states1} vs {states2}"
    assert r1.view.primary is r2.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    # Hermes 审批 + SSE done 哨兵：done 为非权威帧标记，不得自造 completed
    n3, r3 = _fresh()
    _feed(n3, r3, [
        {"event_id": "q1", "status": "queued"},
        {"event_id": "q2", "status": "running"},
        {"event_id": "q3", "type": "approval.request", "payload": {"command": "fs.rm"}},
    ])
    assert r3.view.primary is WorkExecutionState.WAITING_PERMISSION
    ev_done = n3.normalize({"event_id": "q4", "type": "[DONE]"})
    assert ev_done.kind is EventKind.UNKNOWN_EVENT      # 哨兵非权威
    res = r3.reduce(ev_done)
    assert res.applied and r3.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 生产类型不得出现 Hermes 专属字段
    for k in ("_run_statuses", "_stopping_run_ids", "chatToolEventFromRunEvent"):
        assert not hasattr(res1[0].view, k)
        assert not hasattr(ev_done, k)
    assert EventKind.BACKEND_COMPLETED.value == "backend.completed"
    assert not any("hermes" in k.value for k in EventKind)


# ================================================================ 12. 重放确定性
def test_12_repeated_replay_deterministic():
    """§7.12：同一事件流重复重放（fresh reducer）结果完全一致；同 reducer 重投幂等。"""
    stream = [
        {"event_id": "r1", "type": "queued"},
        {"event_id": "r2", "type": "running"},
        {"event_id": "r3", "type": "tool.started", "payload": {"tool": "fs.organize"}},
        {"event_id": "r4", "type": "tool.progress", "payload": {"delta": "t"}},
        {"event_id": "r5", "type": "tool.completed"},
        {"event_id": "r6", "type": "waiting_for_approval"},
        {"event_id": "r7", "type": "approval.resolved", "payload": {"decision": "approve"}},
        {"event_id": "r8", "type": "backend.completed"},
    ]

    def _run_once():
        n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
        r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        outs = []
        for raw in stream:
            res = r.reduce(n.normalize(raw))
            outs.append((res.view.primary.value, res.view.state.value,
                         res.view.tool_subphase, res.view.active_tool,
                         res.view.max_sequence, res.view.processed_count,
                         res.applied, res.diagnostic))
        return outs, (r.view.primary.value, r.view.state.value, r.view.processed_count)

    runs = [_run_once() for _ in range(3)]
    for i in range(1, 3):
        assert runs[i][0] == runs[0][0], f"replay {i} 结果不一致"
        assert runs[i][1] == runs[0][1]
    # 同一 reducer 上重投整条流 → 全部 duplicate，状态与计数完全不变
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    for raw in stream:
        r.reduce(n.normalize(raw))
    before = r.view
    for raw in stream:
        res = r.reduce(n.normalize(raw))
        assert not res.applied and res.diagnostic.startswith("duplicate_event:")
    assert r.view is before
    assert r.view.processed_count == len(stream)


# ================================================================ 额外锁定
def test_13_envelope_validation_fail_closed():
    """信封字段校验：非法值一律 EventNormalizationError（fail-closed）。"""
    base = {
        "event_id": "e1", "backend_id": BACKEND, "contract_id": CONTRACT, "run_id": RUN,
        "sequence": 0, "occurred_at": 1.0, "received_at": 1.0, "kind": EventKind.RUN_STARTED,
    }
    NormalizedEvent(**base)     # 合法
    bad = [
        {**base, "event_id": "   "},
        {**base, "event_id": "bad\nid"},
        {**base, "backend_id": ""},
        {**base, "sequence": True},
        {**base, "sequence": -1},
        {**base, "sequence": 1.5},
        {**base, "occurred_at": float("nan")},
        {**base, "occurred_at": -3},
        {**base, "kind": "run.started"},          # 裸 str 不是 EventKind
        {**base, "contract_id": "x" * 300},
    ]
    for kw in bad:
        with pytest.raises(EventNormalizationError):
            NormalizedEvent(**kw)   # type: ignore[arg-type]


def test_14_reducer_identity_binding():
    """reducer 身份绑定：run_id / contract_id 不匹配 → WorkExecutionError。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    with pytest.raises(WorkExecutionError, match="run_id"):
        r.reduce(_mk(EventKind.RUN_ACCEPTED, "x1", run_id="run_other"))
    with pytest.raises(WorkExecutionError, match="contract_id"):
        r.reduce(_mk(EventKind.RUN_ACCEPTED, "x2", contract_id="wc_other"))
    with pytest.raises(WorkExecutionError, match="NormalizedEvent"):
        r.reduce({"type": "queued"})     # type: ignore[arg-type] —— 未归一不得直接入状态机


def test_15_sequence_and_processed_count_observation():
    """sequence / processed_count 观测：确定性进度，duplicate 不推进。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    assert r.view.max_sequence == -1 and r.view.processed_count == 0
    r.reduce(_mk(EventKind.RUN_ACCEPTED, "s1", sequence=5))
    assert r.view.max_sequence == 5 and r.view.processed_count == 1
    r.reduce(_mk(EventKind.RUN_ACCEPTED, "s1", sequence=5))   # duplicate
    assert r.view.max_sequence == 5 and r.view.processed_count == 1
    r.reduce(_mk(EventKind.RUN_STARTED, "s2", sequence=3))    # 乱序（更低 seq 但合法）
    assert r.view.max_sequence == 5 and r.view.processed_count == 2


def test_16_payload_defensive_export():
    """信封导出防御复制：to_dict 是独立快照，改动不影响内部。"""
    ev = _mk(EventKind.TOOL_STARTED, "e1", payload={"tool": "fs.read_file"})
    d = ev.to_dict()
    assert isinstance(d, MappingProxyType)
    assert d["kind"] == "tool.started"
    assert d["terminal"] is False and d["critical"] is False   # 派生字段（coalescible）
    ev2 = _mk(EventKind.BACKEND_COMPLETED, "e2")
    d2 = ev2.to_dict()
    assert d2["terminal"] is True and d2["critical"] is True    # 终态派生为 critical
    with pytest.raises(TypeError):
        d["kind"] = "hacked"      # type: ignore[index]
    assert ev.kind is EventKind.TOOL_STARTED                   # 内部不受影响
