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

额外锁定：信封字段校验 / reducer backend_id+run_id+contract_id 身份绑定 / sequence 与
processed_count 观测 / 信封载荷防御复制 / 背压分类含工具生命周期边界。

Reviewer Patch 1 否证（test_patch1a–1g）：
- VERIFIED 在 16E 阶段 fail-closed（VB(verified) 一律 unauthorized_verification，
  provenance 不得冒充 authority；全状态全事件扫描 VERIFIED 不可达）；
- normalizer/reducer 精确身份绑定（BackendEvent/Mapping 身份不一致拒绝、reducer
  实际检查 backend_id、构造要求非空 backend_id）；
- event_id→canonical fingerprint（同 id 同内容 duplicate / 同 id 不同内容
  event_id_conflict / 非法事件不烧毁 id 可重放）；
- fallback event_id 纳入 sequence（两次相同 tool.started/completed 是两次事件；
  只有上游稳定 event_id 才强重投幂等）；
- payload 秘密值形态脱敏（message/stdout/error/list 内 Bearer/authorization/
  password/token/secret/api_key 形态）+ max_payload_bytes type-is-int 严格校验；
- approval.requested/resolved 绑定 approval_id（deny/timeout 后同 id approve 不得
  恢复 RUNNING；不相关 id 不得改变状态）；
- TOOL_STARTED/TOOL_COMPLETED 不可丢、不可合并（critical）；只有 TOOL_PROGRESS/
  token delta 可 drop/coalesce。
"""
from __future__ import annotations

import json
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
    sanitize_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

BACKEND = "native"
CONTRACT = "wc_16e_test_001"
RUN = "run_16e_001"


# ================================================================ 工具
def _mk(kind: EventKind, event_id: str, sequence: int = 0,
        payload: Optional[Mapping[str, Any]] = None,
        backend_id: str = BACKEND, contract_id: str = CONTRACT,
        run_id: str = RUN, max_payload_bytes: int = 4096) -> NormalizedEvent:
    """直接构造 canonical 信封（绕过 normalizer，供 reducer 表测试）。"""
    return NormalizedEvent(
        event_id=event_id, backend_id=backend_id, contract_id=contract_id,
        run_id=run_id, sequence=sequence, occurred_at=1000.0, received_at=1000.0,
        kind=kind, payload=payload or {}, provenance="test",
        max_payload_bytes=max_payload_bytes,
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


def _drive(r: WorkExecutionReducer, state: WorkExecutionState) -> Optional[str]:
    """按 _PATH_TO 驱动 reducer 到指定 primary 状态（含 outcome 依赖事件）。

    审批路径自动把 approval_id 注入 resolution 事件；返回路径中最后一个
    approval.requested 的审批身份（BLOCKED 路径即已消费的旧请求 id；无审批
    路径返回 None）。
    """
    tokens = _PATH_TO[state]
    pending: Optional[str] = None
    for i, tok in enumerate(tokens):
        if tok in _SPECIAL_TOKENS:
            kind, payload = _SPECIAL_TOKENS[tok]
            payload = dict(payload)
            if kind is EventKind.APPROVAL_RESOLVED:
                payload["approval_id"] = pending
        else:
            kind = map_kind(tok)
            payload = {}
        ev = NormalizedEvent(
            event_id=f"s{i}_{state.value}", backend_id=BACKEND, contract_id=CONTRACT,
            run_id=RUN, sequence=i, occurred_at=1000.0, received_at=1000.0,
            kind=kind, payload=payload, provenance="test",
        )
        res = r.reduce(ev)
        assert res.applied, f"驱动到 {state.value} 失败 at {tok}: {res.diagnostic}"
        if kind is EventKind.APPROVAL_REQUESTED:
            pending = payload.get("approval_id") or ev.event_id
    assert r.view.primary is state, f"驱动到 {state.value} 失败：实际 {r.view.primary}"
    return pending


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
    """§7.1：approval.resolved outcome 分支（approve/deny/timeout，绑定 approval_id）。"""
    # WAITING_PERMISSION: approve → RUNNING；deny/timeout → BLOCKED_APPROVAL
    for outcome, target in (("approve", WorkExecutionState.RUNNING),
                            ("deny", WorkExecutionState.BLOCKED_APPROVAL),
                            ("timeout", WorkExecutionState.BLOCKED_APPROVAL)):
        r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        ap = _drive(r, WorkExecutionState.WAITING_PERMISSION)
        res = r.reduce(_mk(EventKind.APPROVAL_RESOLVED, "ap1",
                           payload={"outcome": outcome, "approval_id": ap}))
        assert res.applied and res.view.primary is target, outcome
    # BLOCKED_APPROVAL：已消费的旧 approval_id 的 approve 不得恢复 RUNNING
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    spent = _drive(r, WorkExecutionState.BLOCKED_APPROVAL)
    res = r.reduce(_mk(EventKind.APPROVAL_RESOLVED, "ap2",
                       payload={"outcome": "approve", "approval_id": spent}))
    assert not res.applied
    assert res.diagnostic.startswith("approval_id_mismatch:")
    assert r.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    # 恢复路径：新 approval.requested（新 id）→ approve → RUNNING
    res = r.reduce(_mk(EventKind.APPROVAL_REQUESTED, "ap3",
                       payload={"approval_id": "ap_new"}))
    assert res.applied and r.view.primary is WorkExecutionState.WAITING_PERMISSION
    res = r.reduce(_mk(EventKind.APPROVAL_RESOLVED, "ap4",
                       payload={"outcome": "approve", "approval_id": "ap_new"}))
    assert res.applied and r.view.primary is WorkExecutionState.RUNNING


def test_01c_outcome_dependent_verification_boundary():
    """§7.1：verification.boundary 分支（16F 预留通道；verified 在 16E fail-closed）。"""
    # BDU: start → VERIFYING；repair → REPAIRING
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.BACKEND_DONE_UNVERIFIED)
    res = r.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "vb1", payload={"outcome": "start"}))
    assert res.applied and res.view.primary is WorkExecutionState.VERIFYING
    # VERIFYING: verified → fail-closed 拒绝（零变更）；failed → FAILED
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r2, WorkExecutionState.VERIFYING)
    res2 = r2.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "vb2",
                         payload={"outcome": "verified"}))
    assert not res2.applied
    assert res2.diagnostic.startswith("unauthorized_verification:")
    assert r2.view.primary is WorkExecutionState.VERIFYING
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
    # VERIFIED 在 16E 阶段不可由公开事件抵达：VB(verified) fail-closed（16F 建立
    # 真实 verifier authority 后由注入的权威通道开放）
    r3 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r3, WorkExecutionState.VERIFYING)
    res3 = r3.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "v1", payload={"outcome": "verified"}))
    assert not res3.applied
    assert res3.diagnostic.startswith("unauthorized_verification:")
    assert r3.view.primary is WorkExecutionState.VERIFYING


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
    """§7.6：审批路径与取消路径完整走通（approval_id 精确绑定）。"""
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "a1", "type": "queued"},
        {"event_id": "a2", "type": "running"},
        {"event_id": "a3", "type": "waiting_for_approval",
         "payload": {"approval_id": "ap_a", "command": "fs.rm"}},
    ])
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    _feed(n, r, [{"event_id": "a4", "type": "approval.resolved",
                  "payload": {"decision": "approve", "approval_id": "ap_a"}}])
    assert r.view.primary is WorkExecutionState.RUNNING
    # 拒绝 → BLOCKED_APPROVAL → 新请求（新 approval_id）→ 批准 → RUNNING
    n2, r2 = _fresh()
    _feed(n2, r2, [
        {"event_id": "b1", "type": "queued"},
        {"event_id": "b2", "type": "running"},
        {"event_id": "b3", "type": "waiting_for_approval", "payload": {"approval_id": "ap_b"}},
        {"event_id": "b4", "type": "approval.resolved",
         "payload": {"decision": "deny", "approval_id": "ap_b"}},
    ])
    assert r2.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    _feed(n2, r2, [
        {"event_id": "b5", "type": "waiting_for_approval", "payload": {"approval_id": "ap_b2"}},
        {"event_id": "b6", "type": "approval.resolved",
         "payload": {"decision": "approve", "approval_id": "ap_b2"}},
    ])
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
                EventKind.RUN_STARTED, EventKind.PROTOCOL_ERROR,
                EventKind.TOOL_STARTED, EventKind.TOOL_COMPLETED}
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
    assert _mk(EventKind.TOOL_STARTED, "x5").critical is True      # 生命周期边界
    assert _mk(EventKind.TOOL_COMPLETED, "x6").critical is True
    assert _mk(EventKind.TOOL_PROGRESS, "x3").critical is False
    assert _mk(EventKind.TOOL_PROGRESS, "x4").terminal is False
    # 背压策略：critical 永不丢弃；压力下只丢 droppable；coalescible 可合并
    for k in critical:
        assert EventBackpressurePolicy.never_droppable(k)
        assert not EventBackpressurePolicy.drop_allowed(k, under_pressure=True)
    assert EventBackpressurePolicy.drop_allowed(EventKind.TOOL_PROGRESS, under_pressure=True)
    assert not EventBackpressurePolicy.drop_allowed(EventKind.TOOL_PROGRESS, under_pressure=False)
    assert not EventBackpressurePolicy.drop_allowed(EventKind.BACKEND_COMPLETED, under_pressure=True)
    assert not EventBackpressurePolicy.coalesce_allowed(EventKind.TOOL_STARTED)
    assert not EventBackpressurePolicy.coalesce_allowed(EventKind.TOOL_COMPLETED)
    assert EventBackpressurePolicy.coalesce_allowed(EventKind.UNKNOWN_EVENT)
    assert EventBackpressurePolicy.coalesce_allowed(EventKind.TRANSPORT_RECONNECTED)
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
        {"event_id": "z6", "type": "waiting_for_approval", "payload": {"approval_id": "z_ap"}},
        {"event_id": "z7", "type": "approval.resolved",
         "payload": {"decision": "approve", "approval_id": "z_ap"}},
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
        {"event_id": "r6", "type": "waiting_for_approval", "payload": {"approval_id": "r_ap"}},
        {"event_id": "r7", "type": "approval.resolved",
         "payload": {"decision": "approve", "approval_id": "r_ap"}},
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
    """reducer 身份绑定：backend_id / run_id / contract_id 不匹配 → WorkExecutionError。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    with pytest.raises(WorkExecutionError, match="backend_id"):
        r.reduce(_mk(EventKind.RUN_ACCEPTED, "x0", backend_id="backend_other"))
    with pytest.raises(WorkExecutionError, match="run_id"):
        r.reduce(_mk(EventKind.RUN_ACCEPTED, "x1", run_id="run_other"))
    with pytest.raises(WorkExecutionError, match="contract_id"):
        r.reduce(_mk(EventKind.RUN_ACCEPTED, "x2", contract_id="wc_other"))
    with pytest.raises(WorkExecutionError, match="NormalizedEvent"):
        r.reduce({"type": "queued"})     # type: ignore[arg-type] —— 未归一不得直接入状态机
    # 构造必须绑定非空 backend_id（不得留空绕过绑定）
    with pytest.raises(WorkExecutionError, match="backend_id"):
        WorkExecutionReducer(RUN, CONTRACT, backend_id="")


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
    assert d["terminal"] is False and d["critical"] is True    # 派生字段（工具边界 critical）
    ev2 = _mk(EventKind.BACKEND_COMPLETED, "e2")
    d2 = ev2.to_dict()
    assert d2["terminal"] is True and d2["critical"] is True    # 终态派生为 critical
    with pytest.raises(TypeError):
        d["kind"] = "hacked"      # type: ignore[index]
    assert ev.kind is EventKind.TOOL_STARTED                   # 内部不受影响


# ================================================================ Reviewer Patch 1 否证
# B1. VERIFIED 在 16E 阶段 fail-closed（无 verifier authority）
def test_patch1a_verified_fail_closed():
    """reviewer B1：公开 reducer 对 VERIFICATION_BOUNDARY(verified) 一律 fail-closed。

    provenance 字符串（"verifier.trusted"）不得冒充 authority；VERIFIED 在 16E
    阶段无任何公开可达路径（16F 建立真实 verifier 后由注入权威通道开放）。
    """
    # VERIFYING + verified：即使 provenance 自称 verifier 也拒绝且零变更
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.VERIFYING)
    before = r.view
    res = r.reduce(NormalizedEvent(
        event_id="v_claim", backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN,
        sequence=99, occurred_at=1000.0, received_at=1000.0,
        kind=EventKind.VERIFICATION_BOUNDARY,
        payload={"outcome": "verified"}, provenance="verifier.trusted"))
    assert not res.applied
    assert res.diagnostic.startswith("unauthorized_verification:")
    assert res.view is before and res.view.primary is WorkExecutionState.VERIFYING
    # 各状态出发（含 BDU/VERIFYING/REPAIRING）一律拒绝
    for src in (WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                WorkExecutionState.VERIFYING, WorkExecutionState.REPAIRING,
                WorkExecutionState.RUNNING):
        r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        _drive(r2, src)
        res2 = r2.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, f"v_{src.value}",
                             payload={"outcome": "verified"}))
        assert not res2.applied
        assert res2.diagnostic.startswith("unauthorized_verification:")
        assert r2.view.primary is src
    # 全事件扫描：任何可达状态喂任何 EventKind，primary 永不成为 VERIFIED
    for src in (WorkExecutionState.IDLE, WorkExecutionState.STARTING,
                WorkExecutionState.RUNNING, WorkExecutionState.WAITING_PERMISSION,
                WorkExecutionState.BLOCKED_APPROVAL, WorkExecutionState.CANCELLING,
                WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                WorkExecutionState.VERIFYING, WorkExecutionState.REPAIRING,
                WorkExecutionState.CANCELLED, WorkExecutionState.FAILED,
                WorkExecutionState.UNKNOWN):
        r3 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        _drive(r3, src)
        for k in EventKind:
            r3.reduce(_mk(k, f"scan_{src.value}_{k.value}"))
            assert r3.view.primary is not WorkExecutionState.VERIFIED, \
                f"{src.value.value} --{k.value}--> 竟抵达 VERIFIED"


# B2. normalizer/reducer 精确身份绑定
def test_patch1b_identity_binding_rejected():
    """reviewer B2：normalizer/reducer 精确绑定 backend_id/run_id/contract_id。

    BackendEvent 身份不一致必须拒绝；Mapping 携带身份字段不一致必须拒绝（不得
    静默改绑）；reducer 实际检查 backend_id（此前只查 run/contract）。
    """
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    # BackendEvent 身份不一致 → 拒绝
    with pytest.raises(EventNormalizationError, match="backend_id"):
        n.normalize(BackendEvent(backend_id="other_backend", run_id=RUN,
                                 event_type="running", payload={}))
    with pytest.raises(EventNormalizationError, match="run_id"):
        n.normalize(BackendEvent(backend_id=BACKEND, run_id="run_other",
                                 event_type="running", payload={}))
    # Mapping 携带身份字段但不一致 → 拒绝（backend/contract/run 各自 + 别名键）
    for key in ("backend_id", "backendId"):
        with pytest.raises(EventNormalizationError, match="backend_id"):
            n.normalize({"event_id": "x1", "type": "running", key: "other_backend"})
    with pytest.raises(EventNormalizationError, match="contract_id"):
        n.normalize({"event_id": "x2", "type": "running", "contractId": "wc_other"})
    with pytest.raises(EventNormalizationError, match="run_id"):
        n.normalize({"event_id": "x3", "type": "running", "run_id": "run_other"})
    # 非 str 身份字段 → 拒绝（身份不得以非 str 携带）
    with pytest.raises(EventNormalizationError, match="backend_id"):
        n.normalize({"event_id": "x4", "type": "running", "backend_id": 123})
    # 一致的身份字段 → 合法接受（不误伤）
    ev = n.normalize({"event_id": "x5", "type": "running",
                      "backend_id": BACKEND, "contract_id": CONTRACT, "run_id": RUN})
    assert ev.kind is EventKind.RUN_STARTED
    assert ev.backend_id == BACKEND and ev.run_id == RUN
    # reducer 实际检查 backend_id
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    with pytest.raises(WorkExecutionError, match="backend_id"):
        r.reduce(_mk(EventKind.RUN_ACCEPTED, "b1", backend_id="other_backend"))


# B3. event_id → canonical fingerprint 去重
def test_patch1c_event_id_fingerprint_duplicate_conflict_replay():
    """reviewer B3：_seen 为 event_id→canonical fingerprint。

    同 id 同内容 = duplicate；同 id 不同内容 = event_id_conflict（零变更）；
    **非法事件不提前烧毁 id**——先非法后满足前置条件的同事件可重放。
    """
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "e1", "type": "queued"},
        {"event_id": "e2", "type": "running"},
    ])
    assert r.view.primary is WorkExecutionState.RUNNING
    # 同 id 同内容（重投）→ duplicate
    res = r.reduce(n.normalize({"event_id": "e2", "type": "running"}))
    assert not res.applied and res.diagnostic.startswith("duplicate_event:")
    # 同 id 不同内容 → event_id_conflict（不静默当 duplicate，也不改状态）
    before = r.view
    res = r.reduce(n.normalize({"event_id": "e2", "type": "failed", "payload": {"x": 1}}))
    assert not res.applied and res.diagnostic.startswith("event_id_conflict:")
    assert r.view is before and r.view.primary is WorkExecutionState.RUNNING
    # 非法事件不烧毁 id：IDLE 中 tool.started 非法 → 驱动到 RUNNING 后同事件重放可应用
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    ev = _mk(EventKind.TOOL_STARTED, "tool_x", payload={"tool": "fs.read_file"})
    res = r2.reduce(ev)
    assert not res.applied and res.diagnostic.startswith("illegal_transition:")
    _drive(r2, WorkExecutionState.RUNNING)
    res = r2.reduce(ev)     # 前置条件满足后同一事件重放 → 应用
    assert res.applied
    assert r2.view.state is WorkExecutionState.TOOL_RUNNING
    assert r2.view.active_tool == "fs.read_file"
    # 应用后再重投 → duplicate
    res = r2.reduce(ev)
    assert not res.applied and res.diagnostic.startswith("duplicate_event:")
    # 被拒事件不进入 _seen：同一被拒事件再次评估仍按原判据（不变成 duplicate）
    r3 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r3, WorkExecutionState.BACKEND_DONE_UNVERIFIED)
    ev_r = _mk(EventKind.RUN_STARTED, "r3x")   # BDU 中非法
    res = r3.reduce(ev_r)
    assert not res.applied and res.diagnostic.startswith("illegal_transition:")
    res = r3.reduce(ev_r)
    assert not res.applied and res.diagnostic.startswith("illegal_transition:")


# B4. fallback event_id 纳入 sequence
def test_patch1d_fallback_event_id_sequence_distinct():
    """reviewer B4：fallback event_id 纳入 sequence——两次相同 tool.started/
    tool.completed 是两次**事件**（不得被内容寻址误去重）；只有上游稳定 event_id
    才声明强重投幂等。"""
    # 两次完整工具会话：完全相同的内容必须各自成事件且全部应用
    n, r = _fresh()
    double_session = [
        {"type": "queued"},
        {"type": "running"},
        {"type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"type": "tool.completed"},
        {"type": "tool.started", "payload": {"tool": "fs.read_file"}},   # 完全相同
        {"type": "tool.completed"},
    ]
    evs = [n.normalize(raw) for raw in double_session]
    ids = [ev.event_id for ev in evs]
    assert ids[2] != ids[3], "相同内容的两次 tool.started 必须是两次事件"
    assert ids[3] != ids[4] and ids[4] != ids[5], "两次 tool.completed 也必须是两次事件"
    assert len(set(ids)) == len(ids), "fallback id 必须互不相同"
    for ev in evs:
        res = r.reduce(ev)
        assert res.applied, f"{ev.kind.value} 未被应用: {res.diagnostic}"
    assert r.view.primary is WorkExecutionState.RUNNING
    assert r.view.processed_count == len(evs)
    # 背靠背相同 started：第二次是真实的第二次事件（tool_already_active），
    # **不是** duplicate（此前内容寻址会把它误折叠成 duplicate）
    n2, r2 = _fresh()
    back_to_back = [
        {"type": "queued"},
        {"type": "running"},
        {"type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"type": "tool.completed"},
        {"type": "tool.completed"},
    ]
    reses = _feed(n2, r2, back_to_back)
    assert not reses[3].applied and reses[3].diagnostic.endswith("tool_already_active")
    assert not reses[5].applied and reses[5].diagnostic.endswith("no_active_tool")
    assert r2.view.processed_count == 4
    # 上游稳定 event_id → 强重投幂等（duplicate）
    n3, r3 = _fresh()
    _feed(n3, r3, [
        {"event_id": "s0", "type": "queued"},
        {"event_id": "s1", "type": "running"},
        {"event_id": "s2", "type": "tool.started", "payload": {"tool": "fs.read_file"}},
    ])
    res = r3.reduce(n3.normalize({"event_id": "s2", "type": "tool.started",
                                  "payload": {"tool": "fs.read_file"}}))
    assert not res.applied and res.diagnostic.startswith("duplicate_event:")
    # fallback 流在同一输入流位置重复归一 → 同一 id（确定性；fresh normalizer 补序一致）
    n4 = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    evs2 = [n4.normalize(raw) for raw in double_session]
    assert [ev.event_id for ev in evs2] == ids


# B5. payload 秘密值形态脱敏 + 预算严格校验
def test_patch1e_secret_value_redaction_and_budget_validation():
    """reviewer B5：payload 同时做敏感键与秘密**值**形态脱敏（message/stdout/
    error/list 内 Bearer/authorization/password/token/secret/api_key 形态不得
    泄漏）；max_payload_bytes 必须 type-is-int、非 bool、有限合理正值。"""
    ev = _mk(EventKind.TOOL_PROGRESS, "v1", payload={
        "message": "Authorization: Bearer abc.def-ghi_123",
        "stdout": "password=hunter2 token=abc123 secret: s3cr3t",
        "error": "api_key: sk-1234567890",
        "list": ["Bearer xyz", "client_secret='csec'", '{"access_token":"atk_9"}'],
        "ok_note": "the token count is 42 and author is furina",
    })
    blob = json.dumps(_plain(ev.payload), ensure_ascii=False, sort_keys=True)
    for leak in ("abc.def-ghi_123", "hunter2", "abc123", "s3cr3t",
                 "sk-1234567890", "xyz", "csec", "atk_9"):
        assert leak not in blob, f"秘密值形态泄漏: {leak!r}"
    assert "[REDACTED]" in blob
    assert "the token count is 42 and author is furina" in blob   # 自然语言不误伤
    # 键名形态：header 风格键同样脱敏
    ev2 = _mk(EventKind.TOOL_STARTED, "v2", payload={
        "headers": {"x-api-key": "k_123", "X-Authorization": "secret-token"}})
    p2 = _plain(ev2.payload)
    assert p2["headers"]["x-api-key"] == "[REDACTED]"
    assert p2["headers"]["X-Authorization"] == "[REDACTED]"
    # max_payload_bytes 严格校验（信封构造 + sanitize_payload 双入口）
    for bad in (True, False, 0, -5, 1.5, "4096", None, (1 << 20) + 1):
        with pytest.raises(EventNormalizationError, match="max_payload_bytes"):
            _mk(EventKind.TOOL_PROGRESS, "v3", payload={"x": 1},
                max_payload_bytes=bad)
    with pytest.raises(EventNormalizationError, match="max_payload_bytes"):
        sanitize_payload({"x": 1}, max_bytes=0.5)
    # 合法边界值可用
    _mk(EventKind.TOOL_PROGRESS, "v4", payload={"x": 1}, max_payload_bytes=1)
    _mk(EventKind.TOOL_PROGRESS, "v5", payload={"x": 1}, max_payload_bytes=1 << 20)


# B6. approval.requested/resolved 必须绑定 approval_id
def test_patch1f_approval_id_binding():
    """reviewer B6：approval.resolved 只能作用于当前挂起的 approval_id。

    deny/timeout 后同 approval_id 的 approve 不得恢复 RUNNING；不相关
    approval_id 不得改变状态；恢复必须经新的 approval.requested（新 id）。
    """
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "q1", "type": "queued"},
        {"event_id": "q2", "type": "running"},
        {"event_id": "q3", "type": "waiting_for_approval",
         "payload": {"approval_id": "ap_1", "command": "fs.rm"}},
    ])
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 不相关 approval_id → 零状态变更
    before = r.view
    res = r.reduce(n.normalize({"event_id": "q4", "type": "approval.resolved",
                                "payload": {"decision": "approve",
                                            "approval_id": "ap_other"}}))
    assert not res.applied and res.diagnostic.startswith("approval_id_mismatch:")
    assert r.view is before and r.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 缺 approval_id → 回退事件自身 event_id 也不匹配挂起身份 → 拒绝
    res = r.reduce(n.normalize({"event_id": "q5", "type": "approval.resolved",
                                "payload": {"decision": "approve"}}))
    assert not res.applied and res.diagnostic.startswith("approval_id_mismatch:")
    # 畸形 outcome（未知）→ 拒绝但**不消费**挂起请求；随后合法 approve 仍可用
    res = r.reduce(n.normalize({"event_id": "q5b", "type": "approval.resolved",
                                "payload": {"decision": "maybe", "approval_id": "ap_1"}}))
    assert not res.applied and res.diagnostic.startswith("illegal_transition:")
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 匹配 approval_id + approve → RUNNING（合法消费，一次性）
    res = r.reduce(n.normalize({"event_id": "q6", "type": "approval.resolved",
                                "payload": {"decision": "approve",
                                            "approval_id": "ap_1"}}))
    assert res.applied and r.view.primary is WorkExecutionState.RUNNING
    # deny 后同 approval_id 的 approve 不得恢复 RUNNING
    n2, r2 = _fresh()
    _feed(n2, r2, [
        {"event_id": "d1", "type": "queued"},
        {"event_id": "d2", "type": "running"},
        {"event_id": "d3", "type": "waiting_for_approval", "payload": {"approval_id": "ap_2"}},
        {"event_id": "d4", "type": "approval.resolved",
         "payload": {"decision": "deny", "approval_id": "ap_2"}},
    ])
    assert r2.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    res = r2.reduce(n2.normalize({"event_id": "d5", "type": "approval.resolved",
                                  "payload": {"decision": "approve",
                                              "approval_id": "ap_2"}}))
    assert not res.applied and res.diagnostic.startswith("approval_id_mismatch:")
    assert r2.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    # timeout 同理：同 approval_id 的 approve 不得恢复
    n3, r3 = _fresh()
    _feed(n3, r3, [
        {"event_id": "t1", "type": "queued"},
        {"event_id": "t2", "type": "running"},
        {"event_id": "t3", "type": "waiting_for_approval", "payload": {"approval_id": "ap_3"}},
        {"event_id": "t4", "type": "approval.resolved",
         "payload": {"decision": "timeout", "approval_id": "ap_3"}},
    ])
    assert r3.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    res = r3.reduce(n3.normalize({"event_id": "t5", "type": "approval.resolved",
                                  "payload": {"decision": "approve",
                                              "approval_id": "ap_3"}}))
    assert not res.applied and r3.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    # 恢复路径：BLOCKED 中必须出现新 approval.requested（新 id）→ approve 才恢复
    res = r3.reduce(n3.normalize({"event_id": "t6", "type": "waiting_for_approval",
                                  "payload": {"approval_id": "ap_4"}}))
    assert res.applied and r3.view.primary is WorkExecutionState.WAITING_PERMISSION
    res = r3.reduce(n3.normalize({"event_id": "t7", "type": "approval.resolved",
                                  "payload": {"decision": "approve",
                                              "approval_id": "ap_4"}}))
    assert res.applied and r3.view.primary is WorkExecutionState.RUNNING


# B7. TOOL_STARTED/TOOL_COMPLETED 不可丢、不可合并
def test_patch1g_tool_boundary_not_droppable_not_coalescible():
    """reviewer B7：TOOL_STARTED/TOOL_COMPLETED 是不可丢、不可合并的生命周期边界；
    只有 TOOL_PROGRESS/token delta 可 drop/coalesce。"""
    for k in (EventKind.TOOL_STARTED, EventKind.TOOL_COMPLETED):
        assert classify_priority(k) is EventPriority.CRITICAL
        assert EventBackpressurePolicy.never_droppable(k)
        assert not EventBackpressurePolicy.drop_allowed(k, under_pressure=True)
        assert not EventBackpressurePolicy.coalesce_allowed(k)
    # TOOL_PROGRESS 是唯一可丢弃的 token 类；reconnect/unknown 仅可合并
    assert EventBackpressurePolicy.drop_allowed(EventKind.TOOL_PROGRESS, under_pressure=True)
    assert not EventBackpressurePolicy.drop_allowed(EventKind.TOOL_PROGRESS, under_pressure=False)
    for k in (EventKind.TRANSPORT_RECONNECTED, EventKind.UNKNOWN_EVENT):
        assert not EventBackpressurePolicy.drop_allowed(k, under_pressure=True)
        assert EventBackpressurePolicy.coalesce_allowed(k)
