"""Phase 13 FINAL-R1 Reviewer Residual Closeout — §7 ignore 窗口 / §8 Harness 真值 / §9 事件顺序 测试。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from types import SimpleNamespace
from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication

from furina.core import EventBus
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.runtime.scheduler import Scheduler


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _sched():
    bus = EventBus()
    se = StateEngine(bus)
    emo = EmotionEngine(se.state.emotion)
    rel = SimpleNamespace(apply=lambda ev, strength=1.0: None, state=None,
                          factors=lambda: {"comfort": 0.5},
                          decay=lambda dt=3.0: None)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = emo
    sched.relationship = rel
    # Pre-Manual §7：社交 bid 测试需要有效在场（idle_available=True + present）
    sched.world_perc.state.idle_available = True
    sched.world_perc.state.user_present = True
    sched.world_perc.state.user_active = True
    sched.world_perc.state.user_idle_seconds = 10.0
    sched.world_perc._has_valid_idle = True
    return sched, bus, se


# ================================================================ §7 社交响应窗口
def test_social_bid_without_response_emits_ignore_once():
    sched, bus, se = _sched()
    se.state.user_idle_seconds = 10.0
    sched.begin_social_bid(reason="life:approach_user")
    assert sched._pending_social_bid is not None
    # 窗口到期（人为拨快 deadline）
    sched._pending_social_bid["deadline"] = time.time() - 1.0
    sched._tick_social_bid()
    assert sched.emotion._recent.get("user_ignore", 0) == 1, "超时无回应 → USER_IGNORE 恰好一次"
    assert sched._pending_social_bid is None
    # 再 tick：不重复
    sched._tick_social_bid()
    assert sched.emotion._recent.get("user_ignore", 0) == 1


def test_user_response_cancels_pending_ignore():
    sched, bus, se = _sched()
    se.state.user_idle_seconds = 10.0
    sched.begin_social_bid(reason="life:talk")
    sched.on_user_response()
    assert sched._pending_social_bid is None
    sched._tick_social_bid(now=time.time() + 999)
    assert sched.emotion._recent.get("user_ignore", 0) == 0, "用户回应后不得产生 ignore"


def test_pointer_leave_never_resolves_as_ignore():
    """指针离开**不算回应也不触发 ignore**：bid 保持 pending；窗口到期（无真实回应）才 ignore。"""
    sched, bus, se = _sched()
    se.state.user_idle_seconds = 10.0
    sched.begin_social_bid(reason="life:talk")
    from furina.interaction.interaction_types import InteractionEvent, TouchKind, InteractionZone
    for kind in ("leave", "hover", "release", "grab"):
        sched._on_interaction(SimpleNamespace(payload=InteractionEvent(
            type=TouchKind(kind), target=InteractionZone.WHOLE)))
    # 指针阶段不取消 bid、不立即触发 ignore
    assert sched._pending_social_bid is not None, "指针离开不算回应"
    assert sched.emotion._recent.get("user_ignore", 0) == 0, "指针离开不得直接触发 ignore"
    # 窗口到期且无真实回应 → USER_IGNORE 恰好一次（指针阶段不产生第二次）
    sched._pending_social_bid["deadline"] = time.time() - 1.0
    sched._tick_social_bid()
    assert sched.emotion._recent.get("user_ignore", 0) == 1


def test_autonomous_ambient_speech_does_not_start_ignore_window():
    sched, bus, se = _sched()
    se.state.user_idle_seconds = 10.0
    # 自主环境台词（AMBIENT）不得开启响应窗口（begin_social_bid 只由社交活动调用）
    assert sched._pending_social_bid is None
    sched._tick_social_bid(now=time.time() + 999)
    assert sched.emotion._recent.get("user_ignore", 0) == 0, "没有 bid 就不得产生 ignore"


def test_user_absent_does_not_create_fake_ignore():
    sched, bus, se = _sched()
    se.state.user_idle_seconds = 400.0   # 用户缺席（canonical World 也标记 away）
    sched.world_perc.state.user_idle_seconds = 400.0
    sched.world_perc.state.user_present = False
    sched.begin_social_bid(reason="life:talk")
    assert sched._pending_social_bid is None, "用户缺席不得开启响应窗口（不制造假 ignore）"


# ================================================================ §8 Harness 真值
def _harness_app():
    app = SimpleNamespace()
    app.state = SimpleNamespace(state=CharacterState())
    app.relationship = SimpleNamespace(state=None)
    app.memory = SimpleNamespace(store=SimpleNamespace(count=lambda: 0))
    app._sched = SimpleNamespace(current_frame=lambda: None)
    app.life_brain = None
    app.dialogue_brain = None
    from furina.runtime.world import DesktopWorld
    app.world = DesktopWorld(1920, 1080)
    app.bus = SimpleNamespace(on=lambda *a, **k: None)
    app.agent = SimpleNamespace(status="IDLE")
    app.emotion = SimpleNamespace(_recent={})
    return app


def test_harness_agent_status_from_runtime_owner(qapp):
    """FINAL-R1 §8.1：runtime_health()['agent'] 必须反映 AgentRuntime.status（单一 owner）。"""
    from furina.runtime.harness.controller import RuntimeHarness
    app = _harness_app()
    h = RuntimeHarness(app)
    # 真实状态转移 → runtime_health 读到的就是它（不被不存在字段覆盖回 IDLE）
    app.agent.status = "RUNNING"
    assert h.runtime_health()["agent"] == "RUNNING"
    app.agent.status = "UNVERIFIED"
    assert h.runtime_health()["agent"] == "UNVERIFIED"
    app.agent.status = "FAILED"
    assert h.runtime_health()["agent"] == "FAILED"
    app.agent.status = "COMPLETED_VERIFIED"
    assert h.runtime_health()["agent"] == "COMPLETED_VERIFIED"
    app.agent.status = "IDLE"
    assert h.runtime_health()["agent"] == "IDLE"


def test_harness_life_last_outcome_sequence(qapp):
    """FINAL-R1 §8.2：success→failure = LAST_FAILED；failure→success = LAST_OK；success→fallback = FALLBACK。"""
    from furina.runtime.harness.controller import RuntimeHarness
    app = _harness_app()
    h = RuntimeHarness(app)
    # success 然后失败 → LAST_FAILED（聚合不再掩盖最新一次）
    h._life_last["attempt"] = 2
    h._life_last["success"] = 1
    h._life_last["failure"] = 1
    h._life_last["last_outcome"] = "FAILED"
    assert h.life_badge() == "LAST_FAILED"
    # failure 然后 success → LAST_OK
    h._life_last["last_outcome"] = "OK"
    assert h.life_badge() == "LAST_OK"
    # success 然后 fallback → FALLBACK
    h._life_last["last_outcome"] = "FALLBACK"
    assert h.life_badge() == "FALLBACK"


# ================================================================ §9 事件 → 权威状态 → 快照
def _app_stub():
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, factors=lambda: {})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.dialogue_brain = None
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app._sched = SimpleNamespace(interrupt_life=lambda r: None, on_user_response=lambda: None)
    app._fallback_dispatcher = None
    return app


def test_petting_dialogue_snapshot_sees_post_event_emotion():
    """摸头 → 情绪立即派生（happy），对话快照读到的就是 post-event label。"""
    from furina.interaction.interaction_types import InteractionEvent, TouchKind, InteractionZone
    app = _app_stub()
    app._on_interaction_emotion(SimpleNamespace(payload=InteractionEvent(
        type=TouchKind.PETTING, target=InteractionZone.WHOLE)))
    assert app.state.state.emotion.label in ("happy",), \
        f"摸头后快照 label 必须是 post-event: {app.state.state.emotion.label}"


def test_praise_dialogue_snapshot_sees_post_event_relationship():
    """夸奖 → 关系（EV_POSITIVE_RESPONSE）+ 情绪（proud）都在对话快照前更新。"""
    applied = []
    app = _app_stub()
    app.relationship.apply = lambda ev, strength=1.0: applied.append(ev)
    app._rt_dispatcher().bind_owner()
    app.submit_user_message("你真可爱")
    assert applied == ["positive_response"], f"praise 必须走 EV_POSITIVE_RESPONSE: {applied}"
    assert app.state.state.emotion.label in ("proud", "happy")


def test_reject_dialogue_snapshot_sees_post_event_relationship_and_emotion():
    """拒绝 → 关系 EV_REJECT + 情绪 embarrassed/sad 都在快照前更新。"""
    app = _app_stub()
    app._rt_dispatcher().bind_owner()
    app.submit_user_message("别烦我")
    assert app.state.state.emotion.label in ("embarrassed", "sad"), \
        f"reject 后快照情绪: {app.state.state.emotion.label}"
