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

Reviewer Patch 2 否证（test_patch2a–2e）：
- Mapping 别名无歧义（身份字段所有已出现别名逐一校验等于绑定值；event_id/sequence/
  时间戳/kind/payload 多别名同时出现等值允许、冲突拒绝；显式出现但类型/范围非法
  不得当作缺失补值）；
- fallback event_id 每次到达唯一（arrival ordinal 独立递增；显式 sequence 后接缺
  sequence、重复显式 sequence、混合流均不得碰撞；fresh normalizer 重放确定性一致）；
- max_payload_bytes 是真实 UTF-8 byte 上限（len(encoded.encode("utf-8"))；truncation
  marker 自身不超预算；低于最小预算 fail-closed；original_bytes 记录真实 UTF-8 bytes）；
- approval_id 精确绑定（禁止 [:128] 静默截断；非法/超长/control-char 直接拒绝；
  WAITING 同 id 重投幂等观察、异 id typed conflict 零变更不覆盖 pending；
  BLOCKED 仍允许新合法请求；长 ID 第 129 字符不同不得互相批准）；
- tool lifecycle 身份配对（TOOL_STARTED 必须建立非空 active_tool；TOOL_PROGRESS/
  TOOL_COMPLETED 身份必须与 active_tool 一致，缺失/不同均 typed diagnostic 零变更；
  fs.read active 时 fs.delete completed 不得关闭子相位）。

Reviewer Patch 3 否证（test_patch3a–3i）：
- NormalizedEvent **API-immutable**：构造完成后普通赋值/删除任何内部字段（_kind/
  _backend_id/_payload/_terminal/_sequence/…）一律 AttributeError，原值不变；构造、
  to_dict、payload freeze、terminal/critical 派生语义不变（不宣称进程安全边界）；
- approval_id **明确 lexical contract**（以字母/数字开头、仅含 [A-Za-z0-9._:-]、
  总长 <=128）：内部空白/control-char 经 sanitizer 变成空格后同样词法非法拒绝，
  不接受内部空白/截断/别名冲突；
- outcome 别名一致性：outcome/decision/resolution/result 所有已出现别名规范化一致
  （approve≈approved≈allow≈granted 等价）；approve 与 deny/timeout 冲突 →
  outcome_conflict typed rejection 零状态变化；非 str/空/未知值 fail-closed；
  verification outcome 别名同样一致性检查（start vs failed 冲突拒绝），避免相邻
  first-key-wins；
- pending request 除 approval_id 外保存 canonical sanitized fingerprint：WAITING 中
  只有『同 approval_id + 同请求内容』才是幂等观察；同 id 但 tool/scope/args/其它
  payload 不同 → approval_request_conflict 零变更、不得覆盖 pending；resolution 后
  同时清除 pending id 与 fingerprint；
- TOOL_PROGRESS 语义精确化（取代 Patch 2 的"tick 也必须归因"）：payload 显式携带
  tool identity 时必须与 active_tool 精确匹配（不同/类型非法/别名冲突均拒绝）；
  payload 未携带任何工具身份时作为 generic stream/progress tick——RUNNING 中合法
  self-loop，不建立/不关闭/不改变 tool_subphase；message.delta/reasoning/
  reasoning.delta 无 tool 字段的真实 fixture 必须通过 reducer 且永远不能产生终态
  或 VERIFIED；TOOL_STARTED/TOOL_COMPLETED 仍必须有合法且匹配的工具身份（生命周期
  配对不放宽）；
- Typed BackendEvent payload exactness：payload None = 合法空 payload、Mapping =
  正常归一；list/str/int/任意对象等非 Mapping 显式载荷一律 EventNormalizationError，
  不静默替换为 {}（信封构造与 sanitize_payload 双入口同样 fail-closed）。

Reviewer Patch 4 否证（test_patch4a–4f）：
- **fallback event_id 不依赖 raw payload**（秘密低熵指纹修复）：fallback id 只由
  backend/run 身份、canonical kind、sequence 与独立递增的 arrival ordinal 派生，
  **绝不包含/散列 raw payload**（password AAA vs BBB 在同一位置 → 完全相同 id；
  同一 normalizer 连续两个相同事件因 arrival 不同而 id 不同；完整输入流重放确定；
  event_id/to_dict/provenance 中不存在原始秘密或其可公开枚举的普通摘要；"内容寻址"
  措辞已删除）；
- **lossy sanitization 身份碰撞修复**：payload 清洗是否丢失原始信息（秘密脱敏 /
  第 256 字符后截断 / 整体超预算截断 / 深度或非法值丢弃 / 控制字符替换 / bytes
  解码）由信封 ``lossy_payload`` 明确携带；event_id 去重与 approval request 幂等
  对 lossy 内容保守返回 typed ambiguous（event_id_ambiguous /
  approval_request_ambiguous，零状态变更）——同 approval_id 的 password AAA→BBB、
  仅第 257 字符不同都不得判定幂等；同 event_id 不同 secret-bearing payload 不得
  返回 duplicate_event；完全相同、非 lossy payload 重投仍保持现有幂等；失败后
  pending 不被覆盖、仍可由原 approval_id resolve；**绝不保存/导出 raw secret 或
  其普通未加密摘要**（选择保守方案 A：lossy 重投 ambiguous，不使用 keyed
  discriminator；不破坏 fresh normalizer/reducer 重放确定性）；
- **工具身份 lexical contract**：tool/tool_name/name/toolId 所有别名 strip 后必须
  规范化一致，且以字母/数字开头、仅含 [A-Za-z0-9._:-]、总长 <=128——内部空白
  （含 control-char 经 sanitizer 变为空格后）、斜杠、下划线开头及其它非法字符一律
  tool_identity_invalid（TOOL_STARTED/显式 TOOL_PROGRESS/TOOL_COMPLETED 共用同一
  规则）；app.launch/browser.open/fs.read_file/fs.write_text/doc.create/
  comm.send_message 正样本通过；generic message.delta/reasoning 无工具身份仍为
  合法 self-loop；非法事件失败后 tool_subphase/active_tool/processed_count 不变。
"""
from __future__ import annotations

import hashlib
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
            pending = _drive(r, src)
            payload = {}
            # WAITING_PERMISSION 中新的 APPROVAL_REQUESTED 必须是同 approval_id
            # 重投（幂等观察）——不同 id 是 approval_id_conflict 而非合法自环。
            if kind is EventKind.APPROVAL_REQUESTED and \
                    src is WorkExecutionState.WAITING_PERMISSION:
                payload = {"approval_id": pending}
            res = r.reduce(_mk(kind, event_id=f"t_{src.value}_{kind.value}", payload=payload))
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
    # tool.progress → 子相位保持（tick；工具身份必须与 active_tool 一致）
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "t2", payload={"tool": "fs.read_file"}))
    assert res.applied and res.view.state is WorkExecutionState.TOOL_RUNNING
    assert res.view.primary is WorkExecutionState.RUNNING
    # tool.completed（身份匹配）→ 子相位退出，primary 恢复可见
    res = r.reduce(_mk(EventKind.TOOL_COMPLETED, "t3", payload={"tool": "fs.read_file"}))
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
    steps = [
        _mk(EventKind.RUN_ACCEPTED, "ev_0", sequence=0),
        _mk(EventKind.RUN_STARTED, "ev_1", sequence=1),
        _mk(EventKind.TOOL_STARTED, "ev_2", sequence=2, payload={"tool": "fs.read_file"}),
        _mk(EventKind.TOOL_COMPLETED, "ev_3", sequence=3, payload={"tool": "fs.read_file"}),
        _mk(EventKind.BACKEND_COMPLETED, "ev_4", sequence=4),
    ]
    res = [r.reduce(ev) for ev in steps]
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
        {"event_id": "z4", "type": "tool.progress",
         "payload": {"tool": "fs.read_file", "delta": "..."}},
        {"event_id": "z5", "type": "tool.completed", "payload": {"tool": "fs.read_file"}},
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
        {"event_id": "n4", "type": "tool.completed", "payload": {"tool": "fs.read_file"}},
        {"event_id": "n5", "type": "backend.completed"},
    ]
    # Hermes-shaped fixture（_set_run_status 词表 + SSE 事件面）
    hermes = [
        {"event_id": "h1", "status": "queued"},
        {"event_id": "h2", "status": "running"},
        {"event_id": "h3", "type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"event_id": "h4", "type": "tool.completed", "payload": {"tool": "fs.read_file"}},
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
        {"event_id": "r4", "type": "tool.progress",
         "payload": {"tool": "fs.organize", "delta": "t"}},
        {"event_id": "r5", "type": "tool.completed", "payload": {"tool": "fs.organize"}},
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
    tool.completed 是两次**事件**（fallback id 每次到达唯一，不得被误去重）；
    只有上游稳定 event_id 才声明强重投幂等。"""
    # 两次完整工具会话：完全相同的内容必须各自成事件且全部应用
    n, r = _fresh()
    double_session = [
        {"type": "queued"},
        {"type": "running"},
        {"type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"type": "tool.completed", "payload": {"tool": "fs.read_file"}},
        {"type": "tool.started", "payload": {"tool": "fs.read_file"}},   # 完全相同
        {"type": "tool.completed", "payload": {"tool": "fs.read_file"}},
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
    # **不是** duplicate（fallback id 每次到达唯一，第二次是真实的新事件）
    n2, r2 = _fresh()
    back_to_back = [
        {"type": "queued"},
        {"type": "running"},
        {"type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"type": "tool.started", "payload": {"tool": "fs.read_file"}},
        {"type": "tool.completed", "payload": {"tool": "fs.read_file"}},
        {"type": "tool.completed", "payload": {"tool": "fs.read_file"}},
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
    # max_payload_bytes 严格校验（信封构造 + sanitize_payload 双入口）：
    # 低于最小预算（1/127）同样 fail-closed——不允许"声称允许 1 byte 却返回超预算 JSON"
    for bad in (True, False, 0, -5, 1.5, "4096", None, 1, 127, (1 << 20) + 1):
        with pytest.raises(EventNormalizationError, match="max_payload_bytes"):
            _mk(EventKind.TOOL_PROGRESS, "v3", payload={"x": 1},
                max_payload_bytes=bad)
    with pytest.raises(EventNormalizationError, match="max_payload_bytes"):
        sanitize_payload({"x": 1}, max_bytes=0.5)
    # 合法边界值可用（最小预算 128 与上限 1 MiB）
    _mk(EventKind.TOOL_PROGRESS, "v4", payload={"x": 1}, max_payload_bytes=128)
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


# ================================================================ Reviewer Patch 2 否证
# P2-1. Mapping 别名无歧义
def test_patch2a_mapping_alias_exactness():
    """reviewer P2-1：backend_id/backendId、contract_id/contractId、run_id/runId
    所有已出现别名都必须是合法 str 且等于绑定值（不得检查第一个后 break）；
    event_id/eventId/id、sequence/seq/number、时间、kind/status 同时出现时等值
    允许、冲突值拒绝；显式出现但类型/范围非法的 event_id/sequence/timestamp/
    payload 不得当作缺失自动补值。"""
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)

    # --- 身份别名：所有已出现别名逐一校验（不得第一个 break 后放过后面的不一致）---
    with pytest.raises(EventNormalizationError, match="backend_id"):
        n.normalize({"event_id": "a1", "type": "queued",
                     "backend_id": BACKEND, "backendId": "other_backend"})
    with pytest.raises(EventNormalizationError, match="contract_id"):
        n.normalize({"event_id": "a2", "type": "queued",
                     "contractId": "wc_other", "contract_id": CONTRACT})
    with pytest.raises(EventNormalizationError, match="run_id"):
        n.normalize({"event_id": "a3", "type": "queued",
                     "run_id": RUN, "runId": "run_other"})
    with pytest.raises(EventNormalizationError, match="backendId"):
        n.normalize({"event_id": "a4", "type": "queued",
                     "backend_id": BACKEND, "backendId": 123})
    # 全部别名一致且等于绑定 → 合法
    ev = n.normalize({"event_id": "a5", "type": "queued",
                      "backend_id": BACKEND, "backendId": BACKEND,
                      "contract_id": CONTRACT, "contractId": CONTRACT,
                      "run_id": RUN, "runId": RUN})
    assert ev.backend_id == BACKEND and ev.contract_id == CONTRACT and ev.run_id == RUN

    # --- event_id 别名：等值允许 / 冲突拒绝 / 显式非法不得补值 ---
    ev = n.normalize({"event_id": "b1", "eventId": "b1", "id": "b1", "type": "queued"})
    assert ev.event_id == "b1"
    with pytest.raises(EventNormalizationError, match="event_id"):
        n.normalize({"event_id": "b2", "id": "b2_other", "type": "queued"})
    with pytest.raises(EventNormalizationError, match="eventId"):
        n.normalize({"eventId": 7, "type": "queued"})          # 显式但非法类型 → 拒绝
    with pytest.raises(EventNormalizationError, match="event_id"):
        n.normalize({"event_id": "", "type": "queued"})        # 显式但空 → 拒绝（不补值）

    # --- sequence 别名 ---
    ev = n.normalize({"event_id": "c1", "type": "queued", "sequence": 5, "seq": 5})
    assert ev.sequence == 5
    with pytest.raises(EventNormalizationError, match="sequence"):
        n.normalize({"event_id": "c2", "type": "queued", "sequence": 5, "number": 6})
    with pytest.raises(EventNormalizationError, match="seq"):
        n.normalize({"event_id": "c3", "type": "queued", "seq": True})
    with pytest.raises(EventNormalizationError, match="sequence"):
        n.normalize({"event_id": "c4", "type": "queued", "sequence": -1})

    # --- 时间戳别名 ---
    ev = n.normalize({"event_id": "d1", "type": "queued", "occurred_at": 1.0,
                      "timestamp": 1.0})
    assert ev.occurred_at == 1.0
    with pytest.raises(EventNormalizationError, match="时间戳"):
        n.normalize({"event_id": "d2", "type": "queued", "occurred_at": 1.0, "ts": 2.0})
    with pytest.raises(EventNormalizationError, match="timestamp"):
        n.normalize({"event_id": "d3", "type": "queued", "timestamp": "2026-08-28"})
    with pytest.raises(EventNormalizationError, match="occurred_at"):
        n.normalize({"event_id": "d4", "type": "queued", "occurred_at": float("nan")})

    # --- kind/status 别名：等值允许 / 冲突拒绝 / 显式非法类型拒绝 ---
    ev = n.normalize({"event_id": "e1", "type": "queued", "status": "queued"})
    assert ev.kind is EventKind.RUN_ACCEPTED
    with pytest.raises(EventNormalizationError, match="kind"):
        n.normalize({"event_id": "e2", "type": "queued", "status": "running"})
    with pytest.raises(EventNormalizationError, match="kind"):
        n.normalize({"event_id": "e3", "type": "queued", "kind": 42})

    # --- payload 别名：等值允许 / 冲突拒绝 / 显式非法不得补值 ---
    ev = n.normalize({"event_id": "f1", "type": "queued",
                      "payload": {"a": 1}, "data": {"a": 1}})
    assert _plain(ev.payload) == {"a": 1}
    with pytest.raises(EventNormalizationError, match="payload"):
        n.normalize({"event_id": "f2", "type": "queued",
                     "payload": {"a": 1}, "data": {"a": 2}})
    with pytest.raises(EventNormalizationError, match="payload"):
        n.normalize({"event_id": "f3", "type": "queued", "payload": "not-a-mapping"})


# P2-2. fallback event_id 每次到达唯一
def test_patch2b_fallback_event_id_arrival_unique():
    """reviewer P2-2：fallback event_id 每次到达唯一（arrival ordinal 独立递增）。

    显式 sequence 后接缺 sequence（补序可能重复）、重复显式 sequence、混合流
    均不得碰撞；fresh normalizer 重放同一完整输入流仍须确定性一致。
    """
    stream = [
        {"event_id": "s0", "type": "queued"},
        {"event_id": "s1", "type": "running"},
        {"event_id": "s2", "type": "tool.started", "payload": {"tool": "fs.read_file"}},
        # --- 以下全部无显式 event_id（fallback 派生）---
        {"type": "tool.progress", "payload": {"tool": "fs.read_file", "delta": "x"},
         "sequence": 0},                       # 显式 sequence 0
        {"type": "tool.progress", "payload": {"tool": "fs.read_file", "delta": "x"}},
                                               # 缺 sequence → 补序也到 0
        {"type": "tool.progress", "payload": {"tool": "fs.read_file", "delta": "x"},
         "sequence": 0},                       # 重复显式 sequence 0
        {"type": "tool.progress", "payload": {"tool": "fs.read_file", "delta": "y"}},
                                               # 混合流（无显式）
        {"type": "tool.completed", "payload": {"tool": "fs.read_file"}},
    ]

    def _run():
        n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
        r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        outs = []
        for raw in stream:
            ev = n.normalize(raw)
            res = r.reduce(ev)
            outs.append((ev.event_id, ev.sequence, res.applied, res.diagnostic))
        return outs, r.view

    outs1, view1 = _run()
    ids = [o[0] for o in outs1]
    # 三个"同内容 + sequence 0"的 progress（显式/补序/重复显式）必须是**三次不同事件**
    assert ids[3] != ids[4] and ids[4] != ids[5] and ids[3] != ids[5]
    assert len(set(ids[3:7])) == 4, "fallback id 每次到达必须唯一（混合流亦不碰撞）"
    # 全部应用（progress 身份与 active_tool 匹配 → tick；completed 关闭子相位）
    for o in outs1[3:]:
        assert o[2], f"fallback 事件未被应用: {o[3]}"
    assert view1.primary is WorkExecutionState.RUNNING
    assert view1.processed_count == len(stream)
    # 确定性：fresh normalizer 重放同一完整输入流 → 同一 fallback id 序列
    outs2, _ = _run()
    assert [o[0] for o in outs2] == ids


# P2-3. max_payload_bytes 真实 UTF-8 上限
def test_patch2c_max_payload_bytes_utf8_bound():
    """reviewer P2-3：max_payload_bytes 是真实 UTF-8 byte 上限。

    使用 len(encoded.encode("utf-8"))——字符数 <= 预算但 UTF-8 字节超预算的载荷
    必须截断；truncation marker 自身也不得超过预算；低于最小预算 fail-closed
    （不得声称允许 1 byte 却返回超过 1 byte 的 JSON）；original_bytes 记录真实
    UTF-8 bytes。
    """
    from furina.agent.events.models import _MIN_PAYLOAD_BUDGET

    # 72 个字符但 136 个 UTF-8 字节（é 为 2 字节）：字符数 <= 128 而字节数 > 128
    tree = {"x": "\u00e9" * 64}
    p = sanitize_payload(tree, max_bytes=128)
    assert p["_truncated"] is True
    assert p["byte_budget"] == 128
    assert p["original_bytes"] == 136          # 真实 UTF-8 字节（不是字符数 72）
    marker_bytes = len(json.dumps(_plain(p), sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8"))
    assert marker_bytes <= 128                 # truncation marker 自身不超预算
    # 信封入口同样有界
    ev = _mk(EventKind.TOOL_PROGRESS, "m1", payload=tree, max_payload_bytes=128)
    pe = _plain(ev.payload)
    assert pe["_truncated"] is True and pe["original_bytes"] == 136
    # 纯 ASCII 超限（字符 == 字节）同样截断，original_bytes 与真实序列化字节一致
    p2 = sanitize_payload({"y": "z" * 300}, max_bytes=128)
    assert p2["_truncated"] is True
    expected2 = len(json.dumps({"y": "z" * 256}, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":")).encode("utf-8"))
    assert p2["original_bytes"] == expected2
    # 预算内载荷不截断（多字节字符按真实字节计，未超预算即放行）
    p3 = sanitize_payload({"x": "\u00e9"}, max_bytes=128)
    assert "_truncated" not in p3 and _plain(p3) == {"x": "\u00e9"}
    # 低于最小预算 fail-closed（1 byte 也不例外）
    for bad in (1, 127, _MIN_PAYLOAD_BUDGET - 1):
        with pytest.raises(EventNormalizationError, match="max_payload_bytes"):
            sanitize_payload({"x": 1}, max_bytes=bad)
        with pytest.raises(EventNormalizationError, match="max_payload_bytes"):
            _mk(EventKind.TOOL_PROGRESS, "m2", payload={"x": 1}, max_payload_bytes=bad)


# P2-4. approval_id 精确绑定
def test_patch2d_approval_id_exact_binding():
    """reviewer P2-4：approval_id 精确绑定——禁止 [:128] 静默截断；非法/超长/
    control-char ID 直接拒绝；WAITING_PERMISSION 同 id 重投幂等观察、异 id typed
    conflict 零变更不覆盖 pending；BLOCKED_APPROVAL 仍允许新合法请求；长 ID
    第 129 字符不同不得互相批准。"""
    # 长 ID 锁定：前 128 字符相同、第 129 字符不同的 resolved 不得批准挂起请求
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "a1", "type": "queued"},
        {"event_id": "a2", "type": "running"},
        {"event_id": "a3", "type": "waiting_for_approval",
         "payload": {"approval_id": "A" * 128}},
    ])
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    res = r.reduce(n.normalize({"event_id": "a4", "type": "approval.resolved",
                                "payload": {"decision": "approve",
                                            "approval_id": "A" * 128 + "x"}}))
    assert not res.applied and res.diagnostic.startswith("approval_id_invalid:")
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 精确匹配 → approve（合法消费）
    res = r.reduce(n.normalize({"event_id": "a5", "type": "approval.resolved",
                                "payload": {"decision": "approve",
                                            "approval_id": "A" * 128}}))
    assert res.applied and r.view.primary is WorkExecutionState.RUNNING
    # 非法/超长请求：拒绝且 pending 不建立（零变更）
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r2, WorkExecutionState.RUNNING)
    res = r2.reduce(_mk(EventKind.APPROVAL_REQUESTED, "b1",
                        payload={"approval_id": "B" * 129}))
    assert not res.applied and res.diagnostic.startswith("approval_id_invalid:")
    assert r2.view.primary is WorkExecutionState.RUNNING
    res = r2.reduce(_mk(EventKind.APPROVAL_REQUESTED, "b2",
                        payload={"approval_id": 123}))
    assert not res.applied and res.diagnostic.startswith("approval_id_invalid:")
    assert r2.view.primary is WorkExecutionState.RUNNING
    # 别名冲突（approval_id vs approvalId 不等）→ 拒绝
    res = r2.reduce(_mk(EventKind.APPROVAL_REQUESTED, "b3",
                        payload={"approval_id": "ap_1", "approvalId": "ap_2"}))
    assert not res.applied and res.diagnostic.startswith("approval_id_invalid:")
    assert r2.view.primary is WorkExecutionState.RUNNING
    # control-char 在信封层被确定性清洗（绝不静默截断/回退——绑定的是清洗后的值）
    ev_ctrl = _mk(EventKind.APPROVAL_REQUESTED, "b4",
                  payload={"approval_id": "ap\x00bad"})
    assert _plain(ev_ctrl.payload)["approval_id"] == "ap bad"
    # WAITING_PERMISSION：同 approval_id 重投 → 幂等观察（pending 不变）
    n3, r3 = _fresh()
    _feed(n3, r3, [
        {"event_id": "w1", "type": "queued"},
        {"event_id": "w2", "type": "running"},
        {"event_id": "w3", "type": "waiting_for_approval",
         "payload": {"approval_id": "ap_x"}},
    ])
    res = r3.reduce(n3.normalize({"event_id": "w3b", "type": "waiting_for_approval",
                                  "payload": {"approval_id": "ap_x"}}))
    assert res.applied and not res.diagnostic          # 幂等观察
    assert r3.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 不同 approval_id 请求 → typed conflict、零状态变化、**不得覆盖 pending**
    before = r3.view
    res = r3.reduce(n3.normalize({"event_id": "w4", "type": "waiting_for_approval",
                                  "payload": {"approval_id": "ap_y"}}))
    assert not res.applied and res.diagnostic.startswith("approval_id_conflict:")
    assert r3.view is before
    assert r3.view.primary is WorkExecutionState.WAITING_PERMISSION
    # pending 仍是 ap_x：以 ap_x approve 仍可恢复 RUNNING（未被 ap_y 覆盖）
    res = r3.reduce(n3.normalize({"event_id": "w5", "type": "approval.resolved",
                                  "payload": {"decision": "approve",
                                              "approval_id": "ap_x"}}))
    assert res.applied and r3.view.primary is WorkExecutionState.RUNNING
    # BLOCKED_APPROVAL：仍允许新合法 approval 请求（新 id → 重新挂起）
    n4, r4 = _fresh()
    _feed(n4, r4, [
        {"event_id": "d1", "type": "queued"},
        {"event_id": "d2", "type": "running"},
        {"event_id": "d3", "type": "waiting_for_approval",
         "payload": {"approval_id": "ap_1"}},
        {"event_id": "d4", "type": "approval.resolved",
         "payload": {"decision": "deny", "approval_id": "ap_1"}},
    ])
    assert r4.view.primary is WorkExecutionState.BLOCKED_APPROVAL
    res = r4.reduce(n4.normalize({"event_id": "d5", "type": "waiting_for_approval",
                                  "payload": {"approval_id": "ap_2"}}))
    assert res.applied and r4.view.primary is WorkExecutionState.WAITING_PERMISSION


# P2-5. tool lifecycle 身份配对
def test_patch2e_tool_lifecycle_identity_pairing():
    """reviewer P2-5：TOOL_STARTED 必须建立非空 active_tool；TOOL_PROGRESS/
    TOOL_COMPLETED 的工具身份必须与 active_tool 一致（缺失或不同均 typed
    diagnostic、零状态变化）；fs.read active 时 fs.delete completed 不得关闭
    子相位。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.RUNNING)
    # TOOL_STARTED 缺工具名 → 拒绝，子相位不建立
    res = r.reduce(_mk(EventKind.TOOL_STARTED, "s1"))
    assert not res.applied
    assert res.diagnostic.startswith("illegal_transition:")
    assert "tool_identity_invalid" in res.diagnostic
    assert r.view.tool_subphase is False and r.view.active_tool == ""
    # TOOL_STARTED 空工具名 → 拒绝
    res = r.reduce(_mk(EventKind.TOOL_STARTED, "s2", payload={"tool": "   "}))
    assert not res.applied and "tool_identity_invalid" in res.diagnostic
    assert r.view.tool_subphase is False
    # 合法 TOOL_STARTED → 建立非空 active_tool
    res = r.reduce(_mk(EventKind.TOOL_STARTED, "s3", payload={"tool": "fs.read_file"}))
    assert res.applied and r.view.tool_subphase is True
    assert r.view.active_tool == "fs.read_file"
    # TOOL_PROGRESS 无身份 → generic stream/progress tick（Reviewer Patch 3 取代
    # Patch 2 的"tick 也必须归因"：payload 未携带任何工具身份时在 RUNNING 中合法
    # self-loop，不建立/不关闭/不改变 tool_subphase）
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "s4"))
    assert res.applied and not res.diagnostic
    assert r.view.tool_subphase is True and r.view.active_tool == "fs.read_file"
    # TOOL_PROGRESS 不同身份（fs.delete）→ 拒绝（零变更）
    before = r.view
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "s5", payload={"tool": "fs.delete"}))
    assert not res.applied and "tool_identity_mismatch" in res.diagnostic
    assert r.view is before and r.view.active_tool == "fs.read_file"
    # TOOL_PROGRESS 匹配身份 → tick（应用）
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "s6", payload={"tool": "fs.read_file"}))
    assert res.applied and r.view.active_tool == "fs.read_file"
    # fs.read active 时 fs.delete completed → 拒绝，**不得关闭子相位**
    before = r.view
    res = r.reduce(_mk(EventKind.TOOL_COMPLETED, "s7", payload={"tool": "fs.delete"}))
    assert not res.applied and "tool_identity_mismatch" in res.diagnostic
    assert r.view is before and r.view.tool_subphase is True
    assert r.view.active_tool == "fs.read_file"
    # 匹配身份的 completed → 关闭子相位
    res = r.reduce(_mk(EventKind.TOOL_COMPLETED, "s8", payload={"tool": "fs.read_file"}))
    assert res.applied
    assert r.view.tool_subphase is False and r.view.active_tool == ""
    # 无活动工具时 TOOL_PROGRESS（带身份）→ 拒绝
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "s9", payload={"tool": "fs.read_file"}))
    assert not res.applied and "tool_identity_mismatch" in res.diagnostic
    # 超长工具名不得截断配对（129 字符的不同名不得被误认为同一工具）
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r2, WorkExecutionState.RUNNING)
    long_tool = "t" * 129
    res = r2.reduce(_mk(EventKind.TOOL_STARTED, "l1", payload={"tool": long_tool}))
    assert not res.applied and "tool_identity_invalid" in res.diagnostic
    assert r2.view.tool_subphase is False


# ================================================================ Reviewer Patch 3 否证
# P3-1. NormalizedEvent API-immutable
def test_patch3a_normalized_event_api_immutable():
    """reviewer P3-1：构造完成后普通赋值/删除任何内部字段一律 AttributeError，
    原值完全不变；构造、to_dict、payload freeze、terminal/critical 派生语义不变。

    只保证正常 API 无法修改——不把 Python immutability 宣称为进程安全边界。
    """
    ev = _mk(EventKind.TOOL_STARTED, "im1", payload={"tool": "fs.read_file"})

    def _snapshot():
        return (ev.event_id, ev.backend_id, ev.contract_id, ev.run_id, ev.sequence,
                ev.occurred_at, ev.received_at, ev.kind, _plain(ev.payload),
                ev.terminal, ev.critical, ev.provenance)

    original = _snapshot()
    # 全部 12 个 slots + 公共属性：赋值与删除都必须失败
    for name in ("_event_id", "_backend_id", "_contract_id", "_run_id", "_sequence",
                 "_occurred_at", "_received_at", "_kind", "_payload", "_terminal",
                 "_critical", "_provenance", "kind", "payload", "terminal"):
        with pytest.raises(AttributeError, match="不可变"):
            setattr(ev, name, "hacked")
        with pytest.raises(AttributeError, match="不可变"):
            delattr(ev, name)
    # 原值完全不变（含 payload 递归冻结）
    assert _snapshot() == original
    assert _plain(ev.payload) == {"tool": "fs.read_file"}
    with pytest.raises(TypeError):
        ev.payload["tool"] = "hacked"      # type: ignore[index]
    # 构造 / to_dict / 派生语义保持不变
    d = ev.to_dict()
    assert d["kind"] == "tool.started"
    assert d["terminal"] is False and d["critical"] is True    # 工具生命周期边界 critical
    ev2 = _mk(EventKind.BACKEND_COMPLETED, "im2")
    assert ev2.terminal is True and ev2.critical is True
    assert ev2.to_dict()["payload"] is not ev._payload          # 防御复制导出


# P3-2. approval_id 明确 lexical contract
def test_patch3b_approval_id_lexical_contract():
    """reviewer P3-2：approval_id 使用明确 lexical contract——内部空白/control-char
    经 sanitizer 变成空格后同样词法非法拒绝；不接受内部空白、截断或别名冲突。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.RUNNING)
    # 内部空白（含 control-char 清洗后 → 空格）→ approval_id_invalid、零变更、
    # pending 不建立
    for i, bad in enumerate(("ap bad", "ap\x00bad", "ap\tbad", "a b")):
        before = r.view
        res = r.reduce(_mk(EventKind.APPROVAL_REQUESTED, f"lx_{i}",
                           payload={"approval_id": bad}))
        assert not res.applied, bad
        assert res.diagnostic.startswith("approval_id_invalid:"), bad
        assert r.view is before
        assert r.view.primary is WorkExecutionState.RUNNING
    # 词法非法（非字母/数字开头、非法字符）→ 拒绝
    for i, bad in enumerate(("_ap", "-ap", "ap#1", "ap/bad")):
        before = r.view
        res = r.reduce(_mk(EventKind.APPROVAL_REQUESTED, f"lx2_{i}",
                           payload={"approval_id": bad}))
        assert not res.applied and res.diagnostic.startswith("approval_id_invalid:"), bad
        assert r.view is before
    # 合法 id 正常进入 WAITING（词法合同不误伤）
    res = r.reduce(_mk(EventKind.APPROVAL_REQUESTED, "lx3",
                       payload={"approval_id": "ap_good_1.x:y"}))
    assert res.applied and r.view.primary is WorkExecutionState.WAITING_PERMISSION
    # resolved 层同样拒绝内部空白 id（词法非法，不匹配任何挂起）
    res = r.reduce(_mk(EventKind.APPROVAL_RESOLVED, "lx4",
                       payload={"outcome": "approve", "approval_id": "ap bad"}))
    assert not res.applied and res.diagnostic.startswith("approval_id_invalid:")
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 经 normalizer 的 control-char：信封层清洗 \x00→空格，reducer 层词法拒绝
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r2, WorkExecutionState.RUNNING)
    ev = n.normalize({"event_id": "lx5", "type": "waiting_for_approval",
                      "payload": {"approval_id": "ap\x00bad"}})
    assert _plain(ev.payload)["approval_id"] == "ap bad"   # sanitizer 已清洗
    res = r2.reduce(ev)
    assert not res.applied and res.diagnostic.startswith("approval_id_invalid:")
    assert r2.view.primary is WorkExecutionState.RUNNING   # 零变更


# P3-3. outcome 别名一致性（approval + verification）
def test_patch3c_outcome_alias_consistency():
    """reviewer P3-3：outcome/decision/resolution/result 所有已出现别名必须规范化
    一致（approve≈approved≈allow≈granted 等价）；approve 与 deny/timeout 冲突 →
    outcome_conflict typed rejection 零状态变化；非 str/空/未知值 fail-closed；
    verification outcome 别名同样一致性检查（start vs failed 冲突拒绝），避免相邻
    first-key-wins。"""
    # approve + deny 冲突 → outcome_conflict、零变更、pending 保留
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    ap = _drive(r, WorkExecutionState.WAITING_PERMISSION)
    before = r.view
    res = r.reduce(_mk(EventKind.APPROVAL_RESOLVED, "oc1",
                       payload={"outcome": "approve", "decision": "deny",
                                "approval_id": ap}))
    assert not res.applied and res.diagnostic.startswith("outcome_conflict:")
    assert r.view is before
    # pending 未被消费：随后合法 approve 仍恢复 RUNNING
    res = r.reduce(_mk(EventKind.APPROVAL_RESOLVED, "oc2",
                       payload={"outcome": "approve", "approval_id": ap}))
    assert res.applied and r.view.primary is WorkExecutionState.RUNNING
    # approve ≈ approved ≈ allow（多别名等价合法消费）
    r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    ap2 = _drive(r2, WorkExecutionState.WAITING_PERMISSION)
    res = r2.reduce(_mk(EventKind.APPROVAL_RESOLVED, "oc3",
                        payload={"outcome": "approve", "decision": "approved",
                                 "resolution": "allow", "approval_id": ap2}))
    assert res.applied and r2.view.primary is WorkExecutionState.RUNNING
    # approve + timeout 冲突 → 拒绝（零变更）
    r3 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    ap3 = _drive(r3, WorkExecutionState.WAITING_PERMISSION)
    res = r3.reduce(_mk(EventKind.APPROVAL_RESOLVED, "oc4",
                        payload={"decision": "approve", "result": "timeout",
                                 "approval_id": ap3}))
    assert not res.applied and res.diagnostic.startswith("outcome_conflict:")
    assert r3.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 非 str / 空 / 未知值 → fail-closed（illegal_transition、零变更、pending 保留）
    for i, bad in enumerate((123, "", "banana")):
        r4 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        ap4 = _drive(r4, WorkExecutionState.WAITING_PERMISSION)
        res = r4.reduce(_mk(EventKind.APPROVAL_RESOLVED, f"oc5_{i}",
                            payload={"decision": bad, "approval_id": ap4}))
        assert not res.applied, bad
        assert res.diagnostic.startswith("illegal_transition:"), bad
        assert r4.view.primary is WorkExecutionState.WAITING_PERMISSION
    # verification boundary：start + failed 冲突 → outcome_conflict、零变更
    r5 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r5, WorkExecutionState.BACKEND_DONE_UNVERIFIED)
    res = r5.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "oc6",
                        payload={"outcome": "start", "phase": "failed"}))
    assert not res.applied and res.diagnostic.startswith("outcome_conflict:")
    assert r5.view.primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    # verification 多别名等价（phase=begin ≈ outcome=start）合法进入 VERIFYING
    r6 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r6, WorkExecutionState.BACKEND_DONE_UNVERIFIED)
    res = r6.reduce(_mk(EventKind.VERIFICATION_BOUNDARY, "oc7",
                        payload={"outcome": "start", "phase": "begin"}))
    assert res.applied and r6.view.primary is WorkExecutionState.VERIFYING


# P3-4. 同 approval_id + 同请求内容 = 幂等观察
def test_patch3d_pending_request_same_id_same_content_idempotent():
    """reviewer P3-4：WAITING 中只有『同 approval_id + 同请求内容』才是幂等观察；
    别名书写（approvalId）同内容同样幂等；幂等观察后原 id 仍可批准。"""
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "id1", "type": "queued"},
        {"event_id": "id2", "type": "running"},
        {"event_id": "id3", "type": "waiting_for_approval",
         "payload": {"approval_id": "ap_i", "command": "ls", "scope": "/tmp"}},
    ])
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    res = r.reduce(n.normalize({"event_id": "id4", "type": "waiting_for_approval",
                                "payload": {"approval_id": "ap_i", "command": "ls",
                                            "scope": "/tmp"}}))
    assert res.applied and not res.diagnostic     # 幂等观察
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    # 别名书写（approvalId）同内容同样幂等
    res = r.reduce(n.normalize({"event_id": "id5", "type": "waiting_for_approval",
                                "payload": {"approvalId": "ap_i", "command": "ls",
                                            "scope": "/tmp"}}))
    assert res.applied and not res.diagnostic
    # 幂等观察后仍可用原 id 批准（pending 未被任何重投破坏）
    res = r.reduce(n.normalize({"event_id": "id6", "type": "approval.resolved",
                                "payload": {"decision": "approve",
                                            "approval_id": "ap_i"}}))
    assert res.applied and r.view.primary is WorkExecutionState.RUNNING


# P3-5. 同 approval_id 不同请求内容 → conflict，不覆盖 pending
def test_patch3e_pending_request_content_conflict():
    """reviewer P3-5：同 approval_id 但 tool/scope/args/其它 payload 不同 →
    approval_request_conflict typed diagnostic、零变更、**不得覆盖 pending**。"""
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "cf1", "type": "queued"},
        {"event_id": "cf2", "type": "running"},
        {"event_id": "cf3", "type": "waiting_for_approval",
         "payload": {"approval_id": "ap_c", "tool": "fs.rm",
                     "args": {"path": "/a"}}},
    ])
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    before = r.view
    # tool 不同 → conflict
    res = r.reduce(n.normalize({"event_id": "cf4", "type": "waiting_for_approval",
                                "payload": {"approval_id": "ap_c", "tool": "fs.write",
                                            "args": {"path": "/a"}}}))
    assert not res.applied and res.diagnostic.startswith("approval_request_conflict:")
    assert r.view is before
    # args 不同（同 tool）→ conflict
    res = r.reduce(n.normalize({"event_id": "cf5", "type": "waiting_for_approval",
                                "payload": {"approval_id": "ap_c", "tool": "fs.rm",
                                            "args": {"path": "/b"}}}))
    assert not res.applied and res.diagnostic.startswith("approval_request_conflict:")
    assert r.view is before
    # scope 新增/不同 → conflict
    res = r.reduce(n.normalize({"event_id": "cf6", "type": "waiting_for_approval",
                                "payload": {"approval_id": "ap_c", "tool": "fs.rm",
                                            "args": {"path": "/a"}, "scope": "/etc"}}))
    assert not res.applied and res.diagnostic.startswith("approval_request_conflict:")
    assert r.view is before
    # pending 未被覆盖：以原请求（fs.rm /a）批准 → RUNNING
    res = r.reduce(n.normalize({"event_id": "cf7", "type": "approval.resolved",
                                "payload": {"decision": "approve",
                                            "approval_id": "ap_c"}}))
    assert res.applied and r.view.primary is WorkExecutionState.RUNNING


# P3-6. message.delta / reasoning 无 tool 身份 → RUNNING 合法 self-loop
def test_patch3f_generic_progress_self_loop_running():
    """reviewer P3-6：message.delta/reasoning/reasoning.delta 无 tool 字段的真实
    fixture 归一为 TOOL_PROGRESS 后必须通过 reducer（RUNNING 中合法 self-loop），
    且永远不能产生终态或 VERIFIED。"""
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "md0", "type": "queued"},
        {"event_id": "md1", "type": "running"},
    ])
    for i, tok in enumerate(("message.delta", "reasoning", "reasoning.delta")):
        ev = n.normalize({"event_id": f"md{i+2}", "type": tok,
                          "data": {"delta": f"tick{i}"}})
        assert ev.kind is EventKind.TOOL_PROGRESS, tok
        res = r.reduce(ev)
        assert res.applied and not res.diagnostic, tok
        assert r.view.primary is WorkExecutionState.RUNNING
        assert r.view.state is WorkExecutionState.RUNNING
        assert r.view.tool_subphase is False and r.view.active_tool == ""
        assert not r.view.is_terminal
        assert r.view.primary is not WorkExecutionState.VERIFIED
    # 终态后 generic progress → terminal_absorbing（不复活、不产生 VERIFIED）
    _feed(n, r, [{"event_id": "md9", "type": "failed"}])
    assert r.view.primary is WorkExecutionState.FAILED
    res = r.reduce(n.normalize({"event_id": "md10", "type": "message.delta",
                                "data": {"delta": "late"}}))
    assert not res.applied and res.diagnostic.startswith("terminal_absorbing:")
    assert r.view.primary is WorkExecutionState.FAILED


# P3-7. generic progress 不改变已激活 tool_subphase
def test_patch3g_generic_progress_keeps_tool_subphase():
    """reviewer P3-7：generic progress（payload 无工具身份）不建立、不关闭、不改变
    已激活的 tool_subphase/active_tool；只有匹配身份的 completed 才关闭子相位。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.RUNNING)
    res = r.reduce(_mk(EventKind.TOOL_STARTED, "kp1", payload={"tool": "fs.read_file"}))
    assert res.applied and r.view.tool_subphase is True
    assert r.view.active_tool == "fs.read_file"
    # generic tick 合法且保持子相位
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "kp2", payload={"delta": "x"}))
    assert res.applied and not res.diagnostic
    assert r.view.tool_subphase is True and r.view.active_tool == "fs.read_file"
    assert r.view.primary is WorkExecutionState.RUNNING
    assert r.view.state is WorkExecutionState.TOOL_RUNNING
    # 仍不关闭：匹配身份的 completed 才关闭
    res = r.reduce(_mk(EventKind.TOOL_COMPLETED, "kp3", payload={"tool": "fs.read_file"}))
    assert res.applied and r.view.tool_subphase is False
    assert r.view.active_tool == ""
    # 无活动工具时 generic tick 同样合法 self-loop（不建立子相位）
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "kp4", payload={"delta": "y"}))
    assert res.applied and not res.diagnostic
    assert r.view.tool_subphase is False and r.view.active_tool == ""


# P3-8. 显式错误/非法工具身份的 TOOL_PROGRESS 仍拒绝
def test_patch3h_explicit_wrong_tool_progress_rejected():
    """reviewer P3-8：payload 显式携带工具身份时——不同身份/类型非法/别名冲突——
    TOOL_PROGRESS 仍必须 typed rejection、零状态变化（generic tick 豁免只适用于
    未携带任何身份的情形）。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.RUNNING)
    r.reduce(_mk(EventKind.TOOL_STARTED, "wt1", payload={"tool": "fs.read_file"}))
    before = r.view
    # 显式不同身份 → mismatch
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "wt2", payload={"tool": "fs.delete"}))
    assert not res.applied and "tool_identity_mismatch" in res.diagnostic
    # 显式类型非法（非 str）→ invalid
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "wt3", payload={"tool": 123}))
    assert not res.applied and "tool_identity_invalid" in res.diagnostic
    # 显式别名冲突 → invalid
    res = r.reduce(_mk(EventKind.TOOL_PROGRESS, "wt4",
                       payload={"tool": "fs.read_file", "name": "fs.other"}))
    assert not res.applied and "tool_identity_invalid" in res.diagnostic
    # 零状态变化（快照对象与子相位均不变）
    assert r.view is before
    assert r.view.tool_subphase is True and r.view.active_tool == "fs.read_file"


# P3-9. Typed BackendEvent payload exactness
def test_patch3i_backend_event_payload_exactness():
    """reviewer P3-9：BackendEvent payload——None = 合法空 payload；Mapping = 正常
    归一；list/str/int/任意对象等非 Mapping 显式载荷一律 EventNormalizationError
    （不静默替换为 {}）。信封构造与 sanitize_payload 双入口同样 fail-closed。"""
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    # None → 合法空 payload
    ev = n.normalize(BackendEvent(backend_id=BACKEND, run_id=RUN, event_type="running",
                                  payload=None))
    assert ev.kind is EventKind.RUN_STARTED and _plain(ev.payload) == {}
    # Mapping → 正常归一
    ev2 = n.normalize(BackendEvent(backend_id=BACKEND, run_id=RUN,
                                   event_type="tool.started",
                                   payload={"tool": "fs.read_file"}))
    assert ev2.kind is EventKind.TOOL_STARTED
    assert _plain(ev2.payload) == {"tool": "fs.read_file"}
    # 非 Mapping 显式载荷 → EventNormalizationError（不静默替换为 {}）
    for bad in ([1, 2], "text", 42, 3.14, object()):
        with pytest.raises(EventNormalizationError, match="payload"):
            n.normalize(BackendEvent(backend_id=BACKEND, run_id=RUN,
                                     event_type="running", payload=bad))
    # 信封构造与 sanitize_payload 双入口同样 fail-closed
    with pytest.raises(EventNormalizationError, match="payload"):
        NormalizedEvent(event_id="px1", backend_id=BACKEND, contract_id=CONTRACT,
                        run_id=RUN, sequence=0, occurred_at=1.0, received_at=1.0,
                        kind=EventKind.TOOL_PROGRESS, payload=[])
    with pytest.raises(EventNormalizationError, match="payload"):
        sanitize_payload("not-a-mapping")
    with pytest.raises(EventNormalizationError, match="payload"):
        sanitize_payload([1, 2])
    assert _plain(sanitize_payload(None)) == {}     # None 合法空 payload


# ================================================================ Reviewer Patch 4 否证
# P4-1. fallback event_id 不依赖 raw payload（不散列秘密）
def test_patch4a_fallback_event_id_not_secret_derived():
    """reviewer P4-1：fallback event_id 绝不包含/散列/派生自 raw payload。

    相同位置（同 arrival/sequence/kind）秘密值不同（password AAA vs BBB）→
    fallback ID 完全一致；同一 normalizer 连续两个相同事件 → ID 因 arrival 不同
    而不同；完整输入流重放确定；event_id/to_dict/provenance 中不存在原始秘密或
    其可公开枚举的普通摘要（event_id 摘要只来自非敏感字段）。
    """

    def _run(secret: str):
        n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
        raws = [
            {"type": "queued"},
            {"type": "running"},
            {"type": "tool.started",
             "payload": {"tool": "fs.read_file", "password": secret}},
            {"type": "tool.progress",
             "payload": {"tool": "fs.read_file", "token": secret}},
        ]
        return [(n.normalize(raw), i + 1) for i, raw in enumerate(raws)]

    evs_a = _run("AAA")
    evs_b = _run("BBB")
    # 1. fallback ID 不因秘密值变化（同位置逐一相等——绝不散列 raw payload）
    assert [ev.event_id for ev, _ in evs_a] == [ev.event_id for ev, _ in evs_b]
    # 2. 同一 normalizer 连续两个相同事件 → arrival 不同 → ID 不同
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    e1 = n.normalize({"type": "tool.progress", "payload": {"password": "AAA"}})
    e2 = n.normalize({"type": "tool.progress", "payload": {"password": "AAA"}})
    assert e1.event_id != e2.event_id
    # 3. 完整输入流重放（fresh normalizer）→ 同一 id 序列（确定性）
    evs_c = _run("AAA")
    assert [ev.event_id for ev, _ in evs_c] == [ev.event_id for ev, _ in evs_a]
    # 4. event_id / to_dict / provenance 中不存在原始秘密或其普通摘要
    for ev, arrival in evs_a:
        assert "AAA" not in ev.event_id
        assert "AAA" not in ev.provenance
        exported = json.dumps(_plain(ev.to_dict()), ensure_ascii=False, sort_keys=True)
        assert "AAA" not in exported
        # event_id 摘要部分只来自非敏感字段（kind|arrival|sequence）——结构证明：
        # 任何 payload 内容（含秘密）都没有进入 event_id。
        expected = hashlib.sha256(
            f"{ev.kind.value}|{arrival}|{ev.sequence}".encode()).hexdigest()[:16]
        assert ev.event_id.endswith(expected)
        # 秘密的普通 SHA-256 摘要（或其前 16 位）也不得出现
        plain_digest = hashlib.sha256(b"AAA").hexdigest()
        assert plain_digest not in ev.event_id
        assert plain_digest[:16] not in ev.event_id
    assert _plain(evs_a[2][0].payload)["password"] == "[REDACTED]"


# P4-2a. 同 approval_id、不同 secret 字段 → 不得判定幂等
def test_patch4b_approval_lossy_secret_collision_not_idempotent():
    """reviewer P4-2a：同 approval_id、secret 字段不同（password AAA→BBB，都变为
    [REDACTED]）→ 不得判定幂等（approval_request_ambiguous 零变更）；失败后
    pending 不被覆盖，仍可由原 approval_id 正常 resolve；导出诊断无原始秘密。"""
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "b1", "type": "queued"},
        {"event_id": "b2", "type": "running"},
        {"event_id": "b3", "type": "waiting_for_approval",
         "payload": {"approval_id": "ap_b", "command": "fs.rm", "password": "AAA"}},
    ])
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    before = r.view
    res = r.reduce(n.normalize({"event_id": "b4", "type": "waiting_for_approval",
                                "payload": {"approval_id": "ap_b", "command": "fs.rm",
                                            "password": "BBB"}}))
    assert not res.applied
    assert res.diagnostic.startswith("approval_request_ambiguous:")
    assert "AAA" not in res.diagnostic and "BBB" not in res.diagnostic
    assert r.view is before
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    # pending 未被覆盖：仍可由原 approval_id resolve（合法消费）
    res = r.reduce(n.normalize({"event_id": "b5", "type": "approval.resolved",
                                "payload": {"decision": "approve",
                                            "approval_id": "ap_b"}}))
    assert res.applied and r.view.primary is WorkExecutionState.RUNNING
    # lossy 判据在信封上明确可观察（秘密键脱敏 → lossy）
    ev = n.normalize({"event_id": "b6", "type": "waiting_for_approval",
                      "payload": {"approval_id": "ap_b2", "password": "AAA"}})
    assert ev.lossy_payload is True
    assert "AAA" not in json.dumps(_plain(ev.to_dict()), ensure_ascii=False)


# P4-2b. 同 approval_id、仅第 257 字符不同 → 不得判定幂等
def test_patch4c_approval_lossy_truncation_collision_not_idempotent():
    """reviewer P4-2b：同 approval_id、字符串只在第 256 字符后不同（截断为同一
    前 256 字符）→ 不得判定幂等（approval_request_ambiguous 零变更、绝不覆盖
    pending）；原请求仍可由原 approval_id resolve。"""
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "c1", "type": "queued"},
        {"event_id": "c2", "type": "running"},
        {"event_id": "c3", "type": "waiting_for_approval",
         "payload": {"approval_id": "ap_c", "note": "x" * 256 + "A"}},
    ])
    assert r.view.primary is WorkExecutionState.WAITING_PERMISSION
    before = r.view
    res = r.reduce(n.normalize({"event_id": "c4", "type": "waiting_for_approval",
                                "payload": {"approval_id": "ap_c", "note": "x" * 256 + "B"}}))
    assert not res.applied and res.diagnostic.startswith("approval_request_ambiguous:")
    assert r.view is before
    # pending 未被覆盖：原 approval_id 仍可 approve
    res = r.reduce(n.normalize({"event_id": "c5", "type": "approval.resolved",
                                "payload": {"decision": "approve",
                                            "approval_id": "ap_c"}}))
    assert res.applied and r.view.primary is WorkExecutionState.RUNNING
    # 截断发生在信封层：两个不同 note 都只保留前 256 字符
    ev = n.normalize({"event_id": "c6", "type": "waiting_for_approval",
                      "payload": {"note": "y" * 300}})
    assert _plain(ev.payload)["note"] == "y" * 256
    assert ev.lossy_payload is True


# P4-3. 同 event_id、不同 secret-bearing payload → 不得 duplicate
def test_patch4d_event_id_lossy_dedup_not_duplicate():
    """reviewer P4-3：同 event_id、不同 secret-bearing payload → 不得返回
    duplicate_event（保守 event_id_ambiguous 零变更）；完全相同、非 lossy payload
    重投仍保持现有幂等（duplicate_event）；同 id 不同内容（非 lossy）仍为
    event_id_conflict。"""
    # 同 id 不同 secret（都 [REDACTED]）→ ambiguous，零变更
    n, r = _fresh()
    _feed(n, r, [
        {"event_id": "d1", "type": "queued"},
        {"event_id": "d2", "type": "running"},
        {"event_id": "dup", "type": "tool.started",
         "payload": {"tool": "fs.read_file", "password": "AAA"}},
    ])
    assert r.view.state is WorkExecutionState.TOOL_RUNNING
    before = r.view
    res = r.reduce(n.normalize({"event_id": "dup", "type": "tool.started",
                                "payload": {"tool": "fs.read_file",
                                            "password": "BBB"}}))
    assert not res.applied and res.diagnostic.startswith("event_id_ambiguous:")
    assert "AAA" not in res.diagnostic and "BBB" not in res.diagnostic
    assert r.view is before and r.view.active_tool == "fs.read_file"
    # 非 lossy 完全相同 payload 重投 → 仍 duplicate（现有幂等保持）
    n2, r2 = _fresh()
    _feed(n2, r2, [
        {"event_id": "e1", "type": "queued"},
        {"event_id": "e2", "type": "running"},
        {"event_id": "ok", "type": "tool.started", "payload": {"tool": "fs.read_file"}},
    ])
    res = r2.reduce(n2.normalize({"event_id": "ok", "type": "tool.started",
                                  "payload": {"tool": "fs.read_file"}}))
    assert not res.applied and res.diagnostic.startswith("duplicate_event:")
    # 同 id 不同内容（非 lossy）→ event_id_conflict（既有语义不变）
    res = r2.reduce(n2.normalize({"event_id": "ok", "type": "tool.started",
                                  "payload": {"tool": "fs.write_text"}}))
    assert not res.applied and res.diagnostic.startswith("event_id_conflict:")
    # lossy 事件的 event_id 不含原始秘密
    ev = n.normalize({"event_id": "dup", "type": "tool.started",
                      "payload": {"tool": "fs.read_file", "password": "AAA"}})
    assert ev.lossy_payload is True
    assert "AAA" not in ev.event_id


# P4-4. lossy 判据明确覆盖所有丢失路径
def test_patch4e_lossy_detection_covers_all_drop_paths():
    """reviewer P4-4：lossy 判据明确识别——秘密键脱敏 / 秘密值形态 / 字符串截断 /
    整体超预算截断 / 深度丢弃 / 非法值丢弃 / 控制字符替换全部为 lossy 并在信封上
    可观察；普通非 lossy JSON payload 为 False。"""
    assert _mk(EventKind.TOOL_PROGRESS, "f1", payload={"a": 1}).lossy_payload is False
    assert _mk(EventKind.TOOL_PROGRESS, "f2",
               payload={"tool": "fs.read_file"}).lossy_payload is False
    # 秘密键脱敏 → lossy
    assert _mk(EventKind.TOOL_PROGRESS, "f3",
               payload={"password": "x"}).lossy_payload is True
    assert _mk(EventKind.TOOL_PROGRESS, "f4",
               payload={"api_key": "sk-1"}).lossy_payload is True
    # 秘密值形态 → lossy
    assert _mk(EventKind.TOOL_PROGRESS, "f5",
               payload={"message": "Authorization: Bearer abc"}).lossy_payload is True
    # 字符串截断 → lossy
    assert _mk(EventKind.TOOL_PROGRESS, "f6",
               payload={"note": "x" * 300}).lossy_payload is True
    # 控制字符替换 → lossy
    assert _mk(EventKind.TOOL_PROGRESS, "f7",
               payload={"note": "ok\x00ctrl"}).lossy_payload is True
    # 整体超预算截断 → lossy（且信封出现 _truncated）
    big = {"items": ["y" * 250 for _ in range(300)]}
    ev = _mk(EventKind.TOOL_PROGRESS, "f8", payload=big)
    assert _plain(ev.payload).get("_truncated") is True
    assert ev.lossy_payload is True
    # 深度丢弃（>8 层的子键被丢）→ lossy
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": 1}}}}}}}}}}
    ev = _mk(EventKind.TOOL_PROGRESS, "f9", payload=deep)
    assert ev.lossy_payload is True
    # 非法值丢弃（object() → 整键丢弃）→ lossy
    assert _mk(EventKind.TOOL_PROGRESS, "f10",
               payload={"blob": object()}).lossy_payload is True
    # 非有限浮点 → lossy
    assert _mk(EventKind.TOOL_PROGRESS, "f11",
               payload={"x": float("nan")}).lossy_payload is True
    # to_dict 导出包含 lossy 布尔判据（不含任何秘密）
    d = _mk(EventKind.TOOL_PROGRESS, "f12",
            payload={"password": "AAA"}).to_dict()
    assert d["lossy_payload"] is True
    assert "AAA" not in json.dumps(_plain(d), ensure_ascii=False)


# P4-5. 工具身份 lexical contract
def test_patch4f_tool_identity_lexical_contract():
    """reviewer P4-5：tool/tool_name/name/toolId 明确词法规则——字母/数字开头、
    仅含 [A-Za-z0-9._:-]、总长 <=128；内部空白（control-char 经 sanitizer 变为
    空格后同样词法非法）、斜杠、下划线开头及其它非法字符拒绝；多别名冲突拒绝；
    TOOL_STARTED/显式 TOOL_PROGRESS/TOOL_COMPLETED 共用同一规则；真实工具名
    正样本通过；generic message.delta/reasoning 无工具身份继续合法；非法事件
    失败后 tool_subphase/active_tool/processed_count 不变。"""
    r = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r, WorkExecutionState.RUNNING)
    before = r.view
    # 1. control-char 经 normalizer 清洗为空格 → 词法非法（fs.read\x00file）
    n = BackendEventNormalizer(backend_id=BACKEND, contract_id=CONTRACT, run_id=RUN)
    ev = n.normalize({"event_id": "t1", "type": "tool.started",
                      "payload": {"tool": "fs.read\x00file"}})
    assert _plain(ev.payload)["tool"] == "fs.read file"   # sanitizer 已清洗
    res = r.reduce(ev)
    assert not res.applied and "tool_identity_invalid" in res.diagnostic
    # 2. 内部空白 / 斜杠 / 下划线开头 → 拒绝
    for i, bad in enumerate(("fs.read file", "fs/read", "_fs.read")):
        res = r.reduce(_mk(EventKind.TOOL_STARTED, f"t2_{i}", payload={"tool": bad}))
        assert not res.applied and "tool_identity_invalid" in res.diagnostic, bad
    # 3. 多别名冲突（tool vs tool_name 不等）→ 拒绝
    res = r.reduce(_mk(EventKind.TOOL_STARTED, "t3",
                       payload={"tool": "fs.read_file", "tool_name": "fs.other"}))
    assert not res.applied and "tool_identity_invalid" in res.diagnostic
    # 4. 非法事件失败后 tool_subphase/active_tool/processed_count 不变
    assert r.view is before
    assert r.view.tool_subphase is False and r.view.active_tool == ""
    assert r.view.processed_count == before.processed_count
    # 5. 当前真实工具名正样本全部通过（TOOL_STARTED 建立 active_tool）
    for i, tool in enumerate(("app.launch", "browser.open", "fs.read_file",
                              "fs.write_text", "doc.create", "comm.send_message")):
        r2 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
        _drive(r2, WorkExecutionState.RUNNING)
        res = r2.reduce(_mk(EventKind.TOOL_STARTED, f"ok_{i}", payload={"tool": tool}))
        assert res.applied, tool
        assert r2.view.active_tool == tool
    # TOOL_PROGRESS / TOOL_COMPLETED 显式携带非法工具身份 → 同一规则拒绝
    r3 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r3, WorkExecutionState.RUNNING)
    r3.reduce(_mk(EventKind.TOOL_STARTED, "tp0", payload={"tool": "fs.read_file"}))
    res = r3.reduce(_mk(EventKind.TOOL_PROGRESS, "tp1", payload={"tool": "fs/read"}))
    assert not res.applied and "tool_identity_invalid" in res.diagnostic
    res = r3.reduce(_mk(EventKind.TOOL_COMPLETED, "tp2", payload={"tool": "fs.read file"}))
    assert not res.applied and "tool_identity_invalid" in res.diagnostic
    assert r3.view.tool_subphase is True and r3.view.active_tool == "fs.read_file"
    # 6. generic message.delta / reasoning 无工具身份 → 合法 self-loop（无回归）
    n4, r4 = _fresh()
    _feed(n4, r4, [
        {"event_id": "g1", "type": "queued"},
        {"event_id": "g2", "type": "running"},
    ])
    for i, tok in enumerate(("message.delta", "reasoning", "reasoning.delta")):
        ev2 = n4.normalize({"event_id": f"g{i+3}", "type": tok,
                            "data": {"delta": "tick"}})
        res = r4.reduce(ev2)
        assert res.applied and not res.diagnostic, tok
        assert r4.view.primary is WorkExecutionState.RUNNING
        assert r4.view.tool_subphase is False and r4.view.active_tool == ""
    # 别名（tool_name/name/toolId）等值合法通过、规范化后精确一致
    r5 = WorkExecutionReducer(RUN, CONTRACT, backend_id=BACKEND)
    _drive(r5, WorkExecutionState.RUNNING)
    res = r5.reduce(_mk(EventKind.TOOL_STARTED, "al1",
                        payload={"tool": "fs.read_file", "tool_name": "fs.read_file",
                                 "name": "fs.read_file", "toolId": "fs.read_file"}))
    assert res.applied and r5.view.active_tool == "fs.read_file"
