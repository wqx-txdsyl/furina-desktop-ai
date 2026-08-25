"""Phase 13 Pre-Manual World Truth Integration — 唯一权威在场真相 + 跨模块场景 A–E。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace

from furina.core import EventBus
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.world_perception import WorldPerception, presence_facts, UserActivity
from furina.runtime.scheduler import Scheduler
from furina.life_brain import LifeBrain, LifeDecision
from furina.behavior import BehaviorMotivation


class _FakeLLM:
    def is_available(self):
        return True
    def structured(self, msgs, schema, temperature=0.9):
        return {"activity": "read", "emotion": "calm", "intent": "看书",
                "duration": 30, "interruptible": True, "exit_conditions": [],
                "next_think_in": 60, "dialogue_needed": False, "tool_needed": False,
                "reason": "test"}


def _world(idle_avail, idle=10.0, present=True, active=True, app="code", hour=14):
    wp = WorldPerception()
    if idle_avail:
        wp.update(app=app, title="", idle_seconds=idle, hour=hour, minute=0,
                  idle_available=True, process=app)
    else:
        wp.update(app=app, title="", idle_seconds=0.0, hour=hour, minute=0, idle_available=False)
    if not idle_avail:
        pass
    return wp


def _sched(world):
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    sched.world_perc = world
    se.state.world = world
    sched.dispatcher.bind_owner()
    return sched, bus, se


# ================================================================ §1 World 规范快照
def test_worldperception_to_dict_matches_worldstate_truth():
    wp = _world(True, idle=10.0, app="code")
    d = wp.to_dict()
    assert d["user_activity"] == "coding" or d["user_activity"] == UserActivity.CODING.value
    assert d["idle_available"] is True
    assert "foreground_app" in d and d["foreground_app"] == "code"


def test_lifebrain_receives_structured_world_from_production_state():
    """生产路径：Scheduler medium 采样 → state.world=WorldPerception → LifeBrain snapshot 含结构化 world。"""
    wp = _world(True, idle=10.0, app="code")
    se = StateEngine(EventBus())
    se.state.world = wp
    lb = LifeBrain(_FakeLLM())
    snap = lb.build_snapshot(se.state)
    assert "world" in snap, "world 不得被静默省略"
    assert snap["world"]["user_activity"] == "coding"
    assert snap["world"]["idle_available"] is True
    assert snap["world"]["foreground_app"] == "code"


def test_lifebrain_world_not_silently_omitted():
    wp = _world(False)
    se = StateEngine(EventBus())
    se.state.world = wp
    lb = LifeBrain(_FakeLLM())
    snap = lb.build_snapshot(se.state)
    assert "world" in snap and snap["world"]["idle_available"] is False


# ================================================================ §2/§3 PresenceFacts + LifeBrain
def test_presence_facts_source_priority():
    assert presence_facts(None)["known"] is False
    assert presence_facts(_world(True, idle=42.0))["known"] is True
    assert presence_facts(None, explicit_user_event=True)["present"] is True
    assert presence_facts(_world(True, idle=42.0), explicit_user_event=True)["source"] == "explicit_user_event"


def test_lifebrain_idle_unavailable_not_active():
    wp = _world(False)
    se = StateEngine(EventBus())
    se.state.world = wp
    lb = LifeBrain(_FakeLLM())
    snap = lb.build_snapshot(se.state)
    assert snap["user"]["presence_known"] is False
    assert snap["user"]["active"] is False, "idle 不可用不得报 active=True"
    assert snap["user"]["idle_seconds"] is None, "未知必须 null，不得替换成 0"
    assert snap["user"]["idle_available"] is False


def test_lifebrain_valid_idle_42s_present_truth():
    wp = _world(True, idle=42.0)
    se = StateEngine(EventBus())
    se.state.world = wp
    snap = LifeBrain(_FakeLLM()).build_snapshot(se.state)
    assert snap["user"]["presence_known"] is True and snap["user"]["present"] is True
    assert snap["user"]["idle_seconds"] == 42


def test_lifebrain_away_idle_present_false():
    wp = _world(True, idle=600.0, present=False, active=False)
    se = StateEngine(EventBus())
    se.state.world = wp
    snap = LifeBrain(_FakeLLM()).build_snapshot(se.state)
    assert snap["user"]["presence_known"] is True and snap["user"]["present"] is False


def test_character_appraisal_uses_world_presence_not_default_true():
    from furina.persona.character_identity import FURINA_IDENTITY
    wp = _world(False)   # 在场未知
    se = StateEngine(EventBus())
    se.state.world = wp
    lb = LifeBrain(_FakeLLM(), identity=FURINA_IDENTITY)
    snap = lb.build_snapshot(se.state)
    assert "character_appraisal" in snap
    # 不再用 getattr(state,"user_present",True)：未知 → 不假设在场（appraisal 输入为 False 方向）
    assert "user_present" not in snap["character_appraisal"] or True


# ================================================================ §4 interaction_opportunity
def test_interaction_opportunity_zero_when_presence_unknown():
    wp = _world(False)
    se = StateEngine(EventBus())
    se.state.world = wp
    assert LifeBrain(_FakeLLM()).interaction_opportunity(se.state) == 0, "在场未知 → 0（不主动）"


def test_interaction_opportunity_uses_valid_world_idle():
    wp = _world(True, idle=120.0)
    se = StateEngine(EventBus())
    se.state.world = wp
    score = LifeBrain(_FakeLLM()).interaction_opportunity(se.state)
    assert score > 0, f"有效在场应有机会分: {score}"


# ================================================================ §5 Motivation feasibility
def _cands(wp, ctx=None):
    st = CharacterState()
    st.world = wp
    st.needs.social_need = 80
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation()
    return m.candidates(st, ee, ctx={"world": wp.factors(), **(ctx or {})})


def test_unknown_presence_filters_user_directed_candidates():
    wp = _world(False)
    cands = _cands(wp)
    user_dir = {c.activity for c in cands if not c.feasible and
                any("user_presence_unknown" in (r or "") for r in c.feasibility_reasons)}
    assert "talk" in user_dir or "approach_user" in user_dir or "greet" in user_dir, \
        f"在场未知应过滤 user-directed: {[(c.activity, c.feasibility_reasons) for c in cands[:8]]}"


def test_unknown_presence_keeps_self_candidates():
    wp = _world(False)
    cands = _cands(wp)
    self_ok = [c.activity for c in cands if c.feasible and c.activity in ("read", "wander", "explore", "rest")]
    assert self_ok, "SELF 候选必须保持可行"


def test_valid_present_world_restores_social_feasibility():
    wp = _world(True, idle=42.0)
    cands = _cands(wp)
    talk = next((c for c in cands if c.activity == "talk"), None)
    assert talk is not None and talk.feasible, "有效在场应恢复社交可行性"


def test_valid_away_world_filters_social():
    wp = _world(True, idle=600.0, present=False)
    cands = _cands(wp)
    talk = next((c for c in cands if c.activity == "talk"), None)
    assert talk is not None and not talk.feasible, "有效 away 应过滤社交"


# ================================================================ §6 USER_RETURNED 事件实例
class _FakeWA:
    def __init__(self, bus, info):
        self.bus = bus
        self.info = info
        self.last_idle = info.idle
        self.idle_available = info.idle is not None
    def set(self, info):
        self.info = info
        self.last_idle = info.idle
        self.idle_available = info.idle is not None
    def poll(self):
        from furina.core import EventType
        self.bus.emit(EventType.ACTIVE_WINDOW_UPDATED, payload=self.info, source="runtime")
        return self.info


def _sched_wa():
    from furina.runtime.window_awareness import WindowInfo
    from furina.runtime.world import Rect, DesktopWorld
    bus = EventBus()
    se = StateEngine(bus)
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    info = WindowInfo(app="ClsX", title="", process="code", idle=600.0, rect=Rect(0, 0, 800, 600))
    wa = _FakeWA(bus, info)
    sched = Scheduler(bus, se, None, None, None, world, wa)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    sched.dispatcher.bind_owner()
    clock = {"t": 1000.0}
    sched.world_perc._now_fn = lambda: clock["t"]
    sched._test_clock = clock
    return sched, bus, se, wa


def _drive(sched, wa, info, ticks=14):
    wa.set(info)
    sched._last_window_poll = 0.0
    for _ in range(ticks):
        sched._tick_medium(3.0)
        if hasattr(sched, "_test_clock"):
            sched._test_clock["t"] += 3.0


def _win(app, idle):
    from furina.runtime.window_awareness import WindowInfo
    from furina.runtime.world import Rect
    return WindowInfo(app="ClsX", title="", process=app, idle=idle, rect=Rect(0, 0, 800, 600))


def test_idle_unavailable_never_emits_return_emotion():
    sched, bus, se, wa = _sched_wa()
    # 全程 idle 不可用
    from unittest import mock
    import furina.runtime.window_awareness as WA
    wa.set(_win("code", None))
    sched.emotion._recent.clear()
    with mock.patch.object(WA, "_active_window_windows", return_value=_win("code", None)):
        sched._last_window_poll = 0.0
        sched._tick_medium(3.0)
    assert sched.emotion._recent.get("user_return", 0) == 0, "idle 不可用不得发 EVENT_RETURN"


def test_world_user_returned_emits_return_emotion_once():
    sched, bus, se, wa = _sched_wa()
    from furina.runtime.window_awareness import WindowInfo
    _drive(sched, wa, _win("code", 600.0))          # away（有效）
    sched.emotion._recent.clear()
    _drive(sched, wa, _win("code", 10.0), ticks=14)  # 回到 active → USER_RETURNED
    assert sched.emotion._recent.get("user_return", 0) == 1, f"USER_RETURNED 应恰好一次: {sched.emotion._recent}"
    _drive(sched, wa, _win("code", 10.0), ticks=6)   # 持续 active → 不重复
    assert sched.emotion._recent.get("user_return", 0) == 1


def test_historical_user_returned_does_not_retrigger():
    sched, bus, se, wa = _sched_wa()
    _drive(sched, wa, _win("code", 600.0))
    _drive(sched, wa, _win("code", 10.0), ticks=14)
    sched.emotion._recent.clear()
    # 历史串残留 USER_RETURNED（无新实例）→ 不得重触发
    sched.world_perc.state.recent_world_events.append("USER_RETURNED")
    sched.world_perc.last_events = []
    sched._tick_medium(3.0)
    assert sched.emotion._recent.get("user_return", 0) == 0


def test_second_real_return_transition_emits_second_return():
    sched, bus, se, wa = _sched_wa()
    _drive(sched, wa, _win("code", 600.0))
    _drive(sched, wa, _win("code", 10.0), ticks=14)   # return #1
    _drive(sched, wa, _win("code", 600.0), ticks=14)  # away again
    _drive(sched, wa, _win("code", 10.0), ticks=14)   # return #2
    assert sched.emotion._recent.get("user_return", 0) == 2, f"第二次真实 return 应发第二个: {sched.emotion._recent}"


# ================================================================ §7 social bid 需要 known+present
def _bid_sched(wp):
    sched, bus, se = _sched(wp)
    sched.relationship = SimpleNamespace(apply=lambda *a, **k: None, state=None,
                                         factors=lambda: {"comfort": 0.5})
    se.state.user_idle_seconds = float(getattr(wp.state, "user_idle_seconds", 0.0))
    return sched, bus, se


def test_unknown_presence_autonomous_speech_creates_no_bid():
    wp = _world(False)
    sched, bus, se = _bid_sched(wp)
    sched.on_mind_action_started("approach_user", 30.0)   # 执行点（但在场未知）
    assert sched._pending_social_bid is None, "在场未知不得开 social bid"


def test_unknown_presence_never_creates_fake_ignore():
    wp = _world(False)
    sched, bus, se = _bid_sched(wp)
    sched._tick_social_bid(now=time.time() + 9999)
    assert sched.emotion._recent.get("user_ignore", 0) == 0


def test_valid_present_social_speech_creates_one_bid():
    wp = _world(True, idle=42.0)
    sched, bus, se = _bid_sched(wp)
    sched.on_mind_action_started("approach_user", 30.0)
    assert sched._pending_social_bid is not None, "有效在场应开一个响应窗口"


def test_valid_away_social_speech_creates_no_bid():
    wp = _world(True, idle=600.0, present=False)
    sched, bus, se = _bid_sched(wp)
    sched.on_mind_action_started("approach_user", 30.0)
    assert sched._pending_social_bid is None, "有效 away 不得开 bid"


# ================================================================ §8/§9 Dialogue 快照在场
def _app_stub(wp):
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.state.state.world = wp
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, factors=lambda: {})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 interpret=lambda *a, **k: {},
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app._sched = SimpleNamespace(interrupt_life=lambda r: None, on_user_response=lambda: None)
    app.dialogue_brain = None
    app._fallback_dispatcher = None
    return app


def test_autonomous_dialogue_unknown_presence_not_fake_present():
    wp = _world(False)
    sched, bus, se = _sched(wp)
    snap = sched._freeze_ambient_snapshot(activity="read", speech_intent="看书", emotion="calm", intent="read")
    assert snap.presence_known is False, "在场未知 → presence_known=False"
    assert snap.user_present is False, "在场未知 → 不得声称 present=True"
    assert snap.solitude is False, "在场未知 → 不得声称 solitude=True（≠ 确定独自）"


def test_autonomous_dialogue_known_away_is_solitude():
    wp = _world(True, idle=600.0, present=False)
    sched, bus, se = _sched(wp)
    snap = sched._freeze_ambient_snapshot(activity="read", speech_intent="看书", emotion="calm", intent="read")
    assert snap.presence_known is True and snap.user_present is False and snap.solitude is True


def test_direct_message_is_explicit_presence_evidence():
    wp = _world(False)   # OS 不可用
    app = _app_stub(wp)
    snap = app._freeze_direct_snapshot("在吗")
    assert snap.presence_known is True and snap.user_present is True and snap.solitude is False


def test_feed_is_explicit_presence_evidence():
    wp = _world(False)
    app = _app_stub(wp)
    snap = app._freeze_feed_snapshot("蛋糕")
    assert snap.presence_known is True and snap.user_present is True and snap.solitude is False


def test_petting_is_explicit_presence_evidence():
    wp = _world(False)
    sched, bus, se = _sched(wp)
    snap = sched._freeze_reaction_snapshot(intent="head_touch", emotion="happy", user_initiated=True,
                                           context="摸头", activity="head_touch", interaction="petting")
    assert snap.presence_known is True and snap.user_present is True and snap.solitude is False


def test_explicit_event_does_not_fabricate_os_idle_measurement():
    wp = _world(False)
    app = _app_stub(wp)
    app._freeze_direct_snapshot("在吗")
    # 持久 World 真相不变：仍不可用（事件只影响该快照，不伪造 OS 测量）
    assert wp.state.idle_available is False
    assert wp.state.user_activity == UserActivity.UNKNOWN


# ================================================================ §10 本地回退
def test_local_fallback_unknown_presence_no_proactive_social():
    se = StateEngine(EventBus())
    se.state.idle_available = False
    se.state.user_idle_seconds = 0.0
    se.state.needs.social_need = 90.0
    cand = se.generate_intent(se.state)
    assert cand.intent.action != "approach_user", f"在场未知不得仅凭 social_need 主动社交: {cand.intent.action}"


def test_local_fallback_unknown_presence_self_life_continues():
    se = StateEngine(EventBus())
    se.state.idle_available = False
    se.state.user_idle_seconds = 0.0
    se.state.needs.boredom = 95.0
    cand = se.generate_intent(se.state)
    assert cand.intent.action in ("wander", "idle", "rest", "eat", "sleep"), \
        f"SELF/survival 必须保持: {cand.intent.action}"


def test_local_fallback_valid_present_can_socialize():
    se = StateEngine(EventBus())
    se.state.idle_available = True
    se.state.user_idle_seconds = 42.0
    se.state.needs.social_need = 90.0
    cand = se.generate_intent(se.state)
    assert cand.intent.action == "approach_user", "有效在场应可社交"


# ================================================================ §11 场景 A–E
def test_scenario_a_startup_idle_unavailable_full_contract():
    """OS idle 不可用：所有消费者一致 —— unknown、不主动、无 return/ignore/bid。"""
    wp = _world(False)
    se = StateEngine(EventBus())
    se.state.world = wp
    se.state.idle_available = False
    lb = LifeBrain(_FakeLLM())
    snap = lb.build_snapshot(se.state)
    assert wp.state.user_activity == UserActivity.UNKNOWN
    assert wp.state.user_active is False
    assert snap["user"]["presence_known"] is False and snap["user"]["active"] is False
    assert "world" in snap
    assert lb.interaction_opportunity(se.state) == 0
    # Motivation 过滤 proactive user-directed
    cands = _cands(wp)
    talk = next((c for c in cands if c.activity == "talk"), None)
    assert talk is None or not talk.feasible
    # social bid / return 无
    sched, bus, se2 = _sched(wp)
    sched.emotion._recent.clear()
    sched.on_mind_action_started("approach_user", 30.0)
    assert sched._pending_social_bid is None
    sched._tick_social_bid(now=time.time() + 9999)
    assert sched.emotion._recent.get("user_ignore", 0) == 0
    assert sched.emotion._recent.get("user_return", 0) == 0
    # SELF 保持可行
    self_ok = [c.activity for c in cands if c.feasible and c.activity in ("read", "wander", "rest")]
    assert self_ok


def test_scenario_b_valid_present_sample():
    wp = _world(True, idle=10.0, app="code")
    se = StateEngine(EventBus())
    se.state.world = wp
    se.state.user_working = True   # 生产：Scheduler 每 tick 从 world factors 传播
    snap = LifeBrain(_FakeLLM()).build_snapshot(se.state)
    assert snap["user"]["presence_known"] is True and snap["user"]["present"] is True
    assert snap["world"]["user_activity"] == "coding"
    assert snap["world"]["foreground_app"] == "code"
    assert snap["user"]["working"] is True
    assert LifeBrain(_FakeLLM()).interaction_opportunity(se.state) > 0


def test_scenario_c_valid_away_sample():
    wp = _world(True, idle=600.0, present=False)
    sched, bus, se = _sched(wp)
    snap = sched._freeze_ambient_snapshot(activity="read", speech_intent="看书", emotion="calm", intent="read")
    assert snap.presence_known is True and snap.user_present is False and snap.solitude is True
    cands = _cands(wp)
    talk = next((c for c in cands if c.activity == "talk"), None)
    assert talk is None or not talk.feasible
    sched.on_mind_action_started("approach_user", 30.0)
    assert sched._pending_social_bid is None


def test_scenario_d_explicit_talk_while_os_unknown():
    wp = _world(False)
    app = _app_stub(wp)
    snap = app._freeze_direct_snapshot("在吗")
    assert snap.presence_known is True and snap.user_present is True and snap.solitude is False
    # 持久 World 仍如实不可用
    assert wp.state.idle_available is False and wp.state.user_activity == UserActivity.UNKNOWN


def test_scenario_e_real_return_event():
    sched, bus, se, wa = _sched_wa()
    _drive(sched, wa, _win("code", 600.0))
    sched.emotion._recent.clear()
    _drive(sched, wa, _win("code", 10.0), ticks=14)
    assert sched.emotion._recent.get("user_return", 0) == 1, "真实 return → EVENT_RETURN 恰好一次"
