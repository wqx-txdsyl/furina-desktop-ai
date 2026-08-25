"""Phase 13 Final Residual Closure 专项测试（Step 0）。

覆盖 3 个 reviewer-locked residual：

0.1 Recent activity clock domain —— `_on_execute` 记录 recent 结束时刻必须与
    `_grounded_fact_recovery` 的 freshness 比较处于**同一 monotonic clock domain**；
    测试走 production recording path（真实 `_on_execute` → `_freeze_direct_snapshot` →
    `_grounded_fact_recovery`），patch monotonic 证明 fresh / stale 判定。

0.2 Stale / missing recent 不得伪造过去事实 —— 不存在 authoritative recent truth 时
    禁止"刚才我在 X"（X=current 也是伪造）；允许明确说明没有可靠 recent 记录再补 current，
    或返回空。

0.3 Direct foreground active-set —— `_direct_active` 派生为 bool(_active_direct_turns)；
    grace 只在 active set 从 non-empty → empty 时建立；5 个真实 DirectDialogueQueue 回合
    重叠时前 4 个 terminal 后 foreground 仍 direct-owned，最后一个 terminal 才进入 grace。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace
from unittest import mock

from furina.core import EventBus, EventType


class _FakeMemory:
    """最小 memory 替身：只提供 _freeze_direct_snapshot 需要的只读接口。"""

    def retrieve(self, query="", limit=3):
        return []

    def interpret(self, mem_objs, context=""):
        return {}


def _make_app():
    """真实 Furina 实例外壳（生产方法 `_on_execute` / `_freeze_direct_snapshot` 原样调用）。"""
    from furina.app import Furina
    app = object.__new__(Furina)
    app._sched = None
    app.agent = None
    app.relationship = None
    app.memory = _FakeMemory()
    app.state = SimpleNamespace(state=SimpleNamespace(
        life=SimpleNamespace(macro=None, activity="", reason=""),
        intent=SimpleNamespace(action="", emotion="", priority=0.0),
        emotion=SimpleNamespace(label="calm"),
        user_idle_seconds=0.0))
    return app


def _make_sched():
    from furina.runtime.scheduler import Scheduler
    from furina.state import StateEngine
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.dispatcher.bind_owner()   # 测试线程 = owner
    return sched, bus


# ================================================================ 0.1 clock domain
def test_residual_01_recent_recorded_in_monotonic_domain():
    """0.1：production `_on_execute` 用 monotonic 记录 recent 结束时刻（同一 clock domain）。"""
    from furina.app import RECENT_ACTIVITY_FRESHNESS_SECONDS
    app = _make_app()
    app._on_execute(SimpleNamespace(action="read", source="mind", payload={},
                                    reason="r", priority=0.5))
    mono = 1000.0
    wall = 1_800_000_000.0
    with mock.patch("furina.app.time.monotonic", return_value=mono), \
         mock.patch("furina.app.time.time", return_value=wall):
        app._on_execute(SimpleNamespace(action="explore", source="mind", payload={},
                                        reason="r", priority=0.5))
    assert app._current_activity_truth == "explore"
    assert app._recent_activity == "read", "activity 变化应记录 recent"
    # recent_finished_at 必须落在 monotonic 时钟（==patch 值），而不是 epoch wall（否则接近 wall）
    assert app._recent_activity_finished_at == mono, \
        f"recent_finished_at 必须是 monotonic: {app._recent_activity_finished_at} != {mono}"
    # wall-clock 单独另存（不得混用做 freshness 差）
    assert app._recent_activity_finished_wall == wall
    assert RECENT_ACTIVITY_FRESHNESS_SECONDS > 0


def test_residual_01_fresh_and_stale_via_production_path():
    """0.1 + 0.2：production path（_on_execute → _freeze_direct_snapshot → recovery）。

    fresh recent=explore/current=read → "刚才"+explore；
    stale recent=explore/current=read → 不得声称"刚才在 explore/read"，可说明 current=read；
    current query → "现在"+read。
    """
    from furina.app import RECENT_ACTIVITY_FRESHNESS_SECONDS
    app = _make_app()
    # production recording：explore → read（recent=explore, current=read）
    app._on_execute(SimpleNamespace(action="explore", source="mind", payload={},
                                    reason="r", priority=0.5))
    with mock.patch("furina.app.time.monotonic", return_value=1000.0):
        app._on_execute(SimpleNamespace(action="read", source="mind", payload={},
                                        reason="r", priority=0.5))
    assert app._recent_activity == "explore" and app._current_activity_truth == "read"
    res = {"hard_issues": ["ungrounded_activity"], "soft_issues": []}

    # fresh：冻结 + 恢复都在 recent_finished_at 之后 5s（< freshness）→ "刚才"+explore
    with mock.patch("furina.app.time.monotonic", return_value=1005.0):
        snap = app._freeze_direct_snapshot("刚才你在干嘛？")
    assert snap.recent_activity == "explore" and snap.activity == "read"
    with mock.patch("furina.app.time.monotonic", return_value=1005.0):
        r_fresh = app._grounded_fact_recovery(snap, res)
    assert "刚才" in r_fresh and "四处走走" in r_fresh, f"fresh recent → 刚才+explore: {r_fresh}"

    # stale：冻结 + 恢复时刻超过 freshness（+180s）→ 不得伪造过去事实
    stale_t = 1000.0 + RECENT_ACTIVITY_FRESHNESS_SECONDS + 60.0
    with mock.patch("furina.app.time.monotonic", return_value=stale_t):
        snap_stale = app._freeze_direct_snapshot("刚才你在干嘛？")
    with mock.patch("furina.app.time.monotonic", return_value=stale_t):
        r_stale = app._grounded_fact_recovery(snap_stale, res)
    assert "四处走走" not in r_stale, f"stale recent 不得声称刚才在 explore: {r_stale}"
    assert "刚才我在看书" not in r_stale, f"不得把 current 冒充为过去事实: {r_stale}"
    assert "看书" in r_stale, "可说明 current=read"
    assert "刚才那段我没有可靠记录" in r_stale, "应明确说明没有可靠 recent 记录"

    # current query → "现在"+read
    with mock.patch("furina.app.time.monotonic", return_value=1005.0):
        snap_now = app._freeze_direct_snapshot("你现在在干嘛？")
    with mock.patch("furina.app.time.monotonic", return_value=1005.0):
        r_now = app._grounded_fact_recovery(snap_now, res)
    assert "现在" in r_now and "看书" in r_now and "刚才" not in r_now, f"现在→current: {r_now}"


def test_residual_02_missing_recent_no_past_claim():
    """0.2：recent 完全缺失（只有一个 activity，从未变化）→ 不得声称"刚才我在 X"。"""
    app = _make_app()
    with mock.patch("furina.app.time.monotonic", return_value=1000.0):
        app._on_execute(SimpleNamespace(action="read", source="mind", payload={},
                                        reason="r", priority=0.5))
    assert getattr(app, "_recent_activity", "") == "", "无 activity 变化 → 无 recent truth"
    res = {"hard_issues": ["ungrounded_activity"], "soft_issues": []}
    with mock.patch("furina.app.time.monotonic", return_value=1005.0):
        snap = app._freeze_direct_snapshot("刚才你在干嘛？")
    with mock.patch("furina.app.time.monotonic", return_value=1005.0):
        r = app._grounded_fact_recovery(snap, res)
    assert "刚才我在" not in r, f"不得伪造刚才事实: {r}"
    assert "看书" in r, "可说明 current=read"


# ================================================================ 0.3 active set
def test_residual_03_active_set_semantics():
    """0.3：turn-based active set —— 任一回合 terminal 时若其它回合活跃则不开 grace。"""
    sched, bus = _make_sched()
    for tid in (1, 2, 3):
        bus.emit(EventType.DIRECT_TURN_TRACE,
                 payload={"phase": "GENERATION_STARTED", "status": "GENERATING",
                          "turn_id": tid}, source="test")
    assert sched._active_direct_turns == {1, 2, 3}
    assert sched._direct_active is True
    grace_before = sched._direct_grace_until

    # turn1 REPLIED → 仍 active（turn2/3 活跃）→ 不开 grace
    bus.emit(EventType.DIRECT_TURN_TRACE,
             payload={"phase": "REPLIED", "status": "REPLIED", "turn_id": 1}, source="test")
    assert sched._active_direct_turns == {2, 3}
    assert sched._direct_active is True, "其它回合活跃时 direct 仍 active"
    assert sched._direct_grace_until == grace_before, "不得在其它回合活跃时重开 grace"

    # turn2 FAILED → 仍 active（turn3 活跃）
    bus.emit(EventType.DIRECT_TURN_TRACE,
             payload={"phase": "FAILED", "status": "FAILED", "turn_id": 2}, source="test")
    assert sched._active_direct_turns == {3}
    assert sched._direct_active is True
    assert sched._direct_grace_until == grace_before

    # turn3 REPLIED → active set 空 → 才建立 grace
    bus.emit(EventType.DIRECT_TURN_TRACE,
             payload={"phase": "REPLIED", "status": "REPLIED", "turn_id": 3}, source="test")
    assert sched._active_direct_turns == set()
    assert sched._direct_active is False
    assert sched._direct_grace_until > time.monotonic(), "最后一个 terminal 才进入 grace"
    assert sched.dispatcher.violations() == []


def test_residual_03_five_real_queue_turns_grace_only_at_end():
    """0.3 reviewer-locked：5 个真实 DirectDialogueQueue 回合重叠。

    前 4 个 terminal 时 foreground 仍 direct-owned（ambient_allowed=False）；
    最后一个 terminal 后 active set == empty、grace > now；dispatcher violations == []。
    """
    from furina.runtime.dialogue_queue import DirectDialogueQueue
    sched, bus = _make_sched()
    q = DirectDialogueQueue(bus=bus, timeout=10.0)

    def _processor(turn, snapshot):
        time.sleep(0.02)
        if turn.turn_id == 5:
            time.sleep(0.5)   # 最后一个回合慢 → 前 4 个 terminal 时它仍在 GENERATING
        return {"speech": f"reply-{turn.turn_id}"}

    q.set_processor(_processor)
    snap = SimpleNamespace(user_text="x", activity="read", channel="DIRECT_USER_TURN")
    for i in range(5):
        q.submit(snap, user_text=f"turn-{i}")

    # 等待前 4 个回合到达 terminal（期间 owner 持续 drain worker trace）
    deadline = time.monotonic() + 6.0
    done = 0
    while time.monotonic() < deadline:
        sched.drain_apply()
        outcomes = q.recent_outcomes(10)
        done = sum(1 for o in outcomes
                   if o["status"] in ("REPLIED", "FAILED", "CANCELLED"))
        if done >= 4:
            break
        time.sleep(0.01)
    sched.drain_apply()
    # 前 4 个 terminal 后：第 5 个仍 queued/generating → foreground 仍 direct-owned
    assert q.pending() >= 1, "第 5 个回合必须仍活跃"
    assert sched._direct_active is True, "前 4 个 terminal 后 direct 仍 active"
    assert sched._ambient_allowed() is False, "仍有活跃 direct 回合时 ambient 禁入"

    # 等待最后一个 terminal
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        sched.drain_apply()
        if q.wait_idle(0.05):
            break
        time.sleep(0.01)
    sched.drain_apply()
    assert q.pending() == 0
    assert sched._active_direct_turns == set()
    assert sched._direct_active is False
    assert sched._direct_grace_until > time.monotonic(), "最后一个 terminal 后进入 grace"
    assert sched.dispatcher.violations() == [], f"violations: {sched.dispatcher.violations()}"
    # 终态语义不变（FIFO 顺序；recent_outcomes 返回新→旧）
    outcomes = q.recent_outcomes(10)
    replied = [o["turn_id"] for o in outcomes if o["status"] == "REPLIED"]
    assert sorted(replied) == [1, 2, 3, 4, 5], f"FIFO 顺序: {replied}"
    assert replied[0] == 5 and replied[-1] == 1, "最近终态在最前"


def test_residual_03_worker_terminal_without_tracked_active_legacy():
    """0.3 兼容：legacy/合成直发终态（无先前 active 相位）→ 视为 direct 结束，开 grace。"""
    sched, bus = _make_sched()
    bus.emit(EventType.DIRECT_TURN_TRACE,
             payload={"phase": "REPLIED", "status": "REPLIED", "turn_id": 1}, source="test")
    assert sched._active_direct_turns == set()
    assert sched._direct_active is False
    assert sched._direct_grace_until > time.monotonic()
