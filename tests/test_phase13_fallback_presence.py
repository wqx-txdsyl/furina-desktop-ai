"""Phase 13 Pre-Manual FINAL Fallback Presence Patch — fallback 模式在场真相（评审基线 e5ce9fb）。

§1 StateEngine 本地回退：presence_known 只由 idle_available 决定（不从未知状态下的陈旧
    数值 idle / user_working / window 重建）；attention 在不可用时一律 SELF。
§2/§3 BehaviorEngine（无 LifeBrain 的真实执行者）：idle_available=False ⇒ user-dependent
    fallback 行为（observe_user/talk_to_user/approach_user）不可选/不可延续/不可链入。
§4 行为测试 = 真实 EventBus + 生产等价 fallback 注册 + CharacterState.snapshot() + 捕获事件。
§5 Scheduler 真实 fallback 拓扑集成 F1–F4（life_brain=None）。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from contextlib import contextmanager
from unittest import mock

import pytest

from furina.core import EventBus, EventType
from furina.state import AttentionTarget, CharacterState
from furina.state.state_engine import StateEngine
from furina.behavior import BehaviorEngine, BehaviorDefinition
from furina.emotion import EmotionEngine
from furina.world_perception import presence_facts, UserActivity
from furina.runtime.scheduler import Scheduler

_USER_DEPENDENT = ("talk_to_user", "observe_user", "approach_user")
_SELF_LIFE = ("idle", "wander", "rest", "eat", "drink", "play", "sleep")


@contextmanager
def _fake_time(start: float = 1000.0, hour: int = 14):
    """确定性时钟：patch 全局 time.monotonic / time.localtime（本测试内所有模块一致）。

    生产决策链（Scheduler + BehaviorEngine）混用 time.monotonic() 与 now 参数，
    必须统一到假时钟才能断言 duration/近因/滞回 —— 不依赖真实等待。
    """
    clock = {"t": start}
    with mock.patch.object(time, "monotonic", lambda: clock["t"]), \
         mock.patch.object(time, "localtime",
                           lambda: time.struct_time((2024, 1, 1, hour, 0, 0, 0, 1, -1))):
        yield clock


# ================================================================ §1 StateEngine 本地回退
def test_state_fallback_unknown_retained_idle_42_no_social():
    """临时传感器失效：保留最后有效 idle=42，但 idle_available=False → 不得重建在场。"""
    se = StateEngine(EventBus())
    se.state.idle_available = False
    se.state.user_idle_seconds = 42.0
    se.state.needs.social_need = 90.0
    se.state.clock_hour = 14
    cand = se.generate_intent(se.state)
    assert cand.intent.action not in ("approach_user", "observe_user"), \
        f"陈旧数值 idle=42 不得重建在场: {cand.intent.action}"
    assert cand.intent.action in _SELF_LIFE, "SELF/survival 必须保持"


def test_state_fallback_unknown_retained_idle_600_no_social():
    """同上：保留 idle=600（曾经 away 的残留）也不得当作 known/away 之外的可社交。"""
    se = StateEngine(EventBus())
    se.state.idle_available = False
    se.state.user_idle_seconds = 600.0
    se.state.needs.social_need = 90.0
    se.state.clock_hour = 14
    cand = se.generate_intent(se.state)
    assert cand.intent.action not in ("approach_user", "observe_user"), \
        f"陈旧数值 idle=600 不得重建在场: {cand.intent.action}"
    assert cand.intent.action in _SELF_LIFE


def test_state_fallback_unknown_working_true_no_social():
    """user_working=True（window 上下文）不得把不可用测量转成已知在场。"""
    se = StateEngine(EventBus())
    se.state.idle_available = False
    se.state.user_idle_seconds = 42.0
    se.state.user_working = True
    se.state.needs.social_need = 90.0
    se.state.clock_hour = 14
    cand = se.generate_intent(se.state)
    assert cand.intent.action not in ("approach_user", "observe_user"), \
        f"user_working 不得转成在场: {cand.intent.action}"
    assert cand.intent.action in _SELF_LIFE


@pytest.mark.parametrize("retained_idle", [0.0, 10.0, 42.0, 300.0, 600.0])
def test_attention_unknown_retained_idle_is_self(retained_idle):
    """evaluate_attention：idle_available=False → SELF，无论保留数值是什么。"""
    se = StateEngine(EventBus())
    se.state.idle_available = False
    se.state.user_idle_seconds = retained_idle
    se.state.active_window_app = "code"
    se.evaluate_attention()
    assert se.state.attention.target == AttentionTarget.SELF, \
        f"不可用+保留 idle={retained_idle} 必须 SELF"


def test_attention_unknown_retained_idle_42_is_self():
    se = StateEngine(EventBus())
    se.state.idle_available = False
    se.state.user_idle_seconds = 42.0
    se.state.active_window_app = "code"
    se.evaluate_attention()
    assert se.state.attention.target == AttentionTarget.SELF


def test_attention_unknown_retained_idle_600_is_self():
    se = StateEngine(EventBus())
    se.state.idle_available = False
    se.state.user_idle_seconds = 600.0
    se.state.active_window_app = "code"
    se.evaluate_attention()
    assert se.state.attention.target == AttentionTarget.SELF


def test_state_fallback_valid_present_still_can_socialize():
    """有效在场（idle_available=True）→ 本地意图仍可社交（修复不是一刀切禁社交）。"""
    se = StateEngine(EventBus())
    se.state.idle_available = True
    se.state.user_idle_seconds = 42.0
    se.state.needs.social_need = 90.0
    se.state.clock_hour = 14
    cand = se.generate_intent(se.state)
    assert cand.intent.action == "approach_user"


# ================================================================ §4 BehaviorEngine（事件捕获）
def _register_prod_fallbacks(be: BehaviorEngine) -> None:
    """生产等价 fallback 注册（逐条复制 app._register_behaviors）。"""
    def util_idle(s): return 5.0
    def util_wander(s): return s.get("needs", {}).get("boredom", 0) * 0.5
    def util_observe(s): return 30.0 if s.get("user_working") else 10.0
    def util_rest(s):
        n = s.get("needs", {})
        return (n.get("fatigue", 0) + n.get("sleepiness", 0)) * 0.5
    def util_talk(s):
        n = s.get("needs", {})
        base = n.get("social_need", 0) * 0.6
        if s.get("user_working"):
            base -= 40        # 打扰成本
        return base
    def util_eat(s):
        return (s.get("needs", {}).get("hunger", 0) - 60) * 2 if s.get("needs", {}).get("hunger", 0) > 60 else -10
    def util_sleep(s):
        n = s.get("needs", {})
        hour = s.get("clock_hour", 0)
        late = (hour >= 23 or hour < 6)
        return (n.get("sleepiness", 0) + n.get("fatigue", 0)) * 0.7 + (30 if late else 0)
    def util_drink(s):
        return (s.get("needs", {}).get("hunger", 0) - 55) * 1.5 if s.get("needs", {}).get("hunger", 0) > 55 else -20
    def util_play(s):
        n = s.get("needs", {})
        u = n.get("playfulness", 0) * 0.6 + n.get("boredom", 0) * 0.3
        if s.get("user_working"):
            u -= 45     # 打扰成本
        return u

    for d in [
        BehaviorDefinition("idle", base_utility=5, priority=5, interruptible=True, tags=["micro"]),
        BehaviorDefinition("wander", utility_fn=util_wander, priority=4, cooldown=60, duration=12),
        BehaviorDefinition("observe_user", utility_fn=util_observe, priority=3, cooldown=45,
                           tags=["social"], chain_to="approach_user",
                           chain_if=lambda s: s.get("user_working") and s.get("user_idle", 0) < 5),
        BehaviorDefinition("rest", utility_fn=util_rest, priority=4, duration=30, cooldown=90),
        BehaviorDefinition("talk_to_user", utility_fn=util_talk, priority=3, cooldown=300, interruptible=True, tags=["social"]),
        BehaviorDefinition("eat", utility_fn=util_eat, priority=3, duration=10, cooldown=300,
                           chain_to="rest", chain_if=lambda s: s.get("needs", {}).get("hunger", 0) < 40),
        BehaviorDefinition("drink", utility_fn=util_drink, priority=3, duration=8, cooldown=240),
        BehaviorDefinition("play", utility_fn=util_play, priority=3, duration=12, cooldown=300, interruptible=True, tags=["social"]),
        BehaviorDefinition("sleep", utility_fn=util_sleep, priority=0, duration=240, cooldown=480, interruptible=True),
        BehaviorDefinition("approach_user", utility_fn=lambda s: 40 if s.get("user_working") else 0,
                           priority=2, duration=8, interruptible=True, tags=["social"]),
    ]:
        be.register(d)


def _be_factory():
    """真实 EventBus + 真实 BehaviorEngine + 生产等价注册 + 事件捕获。

    捕获 BEHAVIOR_STARTED / ACTION_REQUEST / BEHAVIOR_INTERRUPTED / BEHAVIOR_COMPLETED。
    """
    bus = EventBus()
    be = BehaviorEngine(bus)
    _register_prod_fallbacks(be)
    events: list = []
    for t in (EventType.BEHAVIOR_STARTED, EventType.ACTION_REQUEST,
              EventType.BEHAVIOR_INTERRUPTED, EventType.BEHAVIOR_COMPLETED):
        bus.on(t, lambda ev: events.append((ev.type, ev.payload)))
    return be, events


def _be_state(**kw) -> dict:
    """真实 CharacterState.snapshot()（生产快照路径，恒携带 idle_available 位）。"""
    se = StateEngine(EventBus())
    st = se.state
    st.idle_available = kw.get("idle_available", True)
    st.user_idle_seconds = kw.get("idle", 10.0)
    st.user_working = kw.get("user_working", False)
    st.clock_hour = kw.get("hour", 14)
    st.needs.social_need = kw.get("social_need", 40.0)
    st.needs.boredom = kw.get("boredom", 30.0)
    st.needs.fatigue = kw.get("fatigue", 5.0)
    st.needs.sleepiness = kw.get("sleepiness", 5.0)
    st.needs.playfulness = kw.get("playfulness", 30.0)
    st.needs.hunger = kw.get("hunger", 20.0)
    return st.snapshot()


def _action_requests(events) -> list:
    return [p for t, p in events if t == EventType.ACTION_REQUEST]


@pytest.mark.parametrize("retained_idle", [42.0, 600.0])
def test_behavior_fallback_unknown_no_talk_action_request(retained_idle):
    """在场未知（保留 42/600）→ 绝不发出 talk_to_user 的 ACTION_REQUEST（pre-fix 它会赢）。"""
    be, events = _be_factory()
    with _fake_time(1000.0):
        s = _be_state(idle_available=False, idle=retained_idle, user_working=False, social_need=90.0)
        be.step(s, now=1000.0)
    reqs = _action_requests(events)
    assert reqs, "必须发出某个行为请求"
    assert all(r.get("action") not in _USER_DEPENDENT for r in reqs), \
        f"未知(保留 idle={retained_idle})不得主动用户定向: {reqs}"


@pytest.mark.parametrize("retained_idle", [42.0, 600.0])
def test_behavior_fallback_unknown_no_observe_user_action_request(retained_idle):
    """在场未知 → 绝不发出 observe_user 的 ACTION_REQUEST。"""
    be, events = _be_factory()
    with _fake_time(1000.0):
        s = _be_state(idle_available=False, idle=retained_idle, user_working=False,
                      social_need=15.0, boredom=10.0, playfulness=0.0)
        be.step(s, now=1000.0)
    reqs = _action_requests(events)
    assert reqs, "必须发出某个行为请求"
    assert all(r.get("action") not in _USER_DEPENDENT for r in reqs), \
        f"未知(保留 idle={retained_idle})不得 observe: {reqs}"


@pytest.mark.parametrize("retained_idle", [42.0, 600.0])
def test_behavior_fallback_unknown_no_approach_action_request(retained_idle):
    """在场未知 → 绝不发出 approach_user 的 ACTION_REQUEST（pre-fix 它在 working 时赢）。"""
    be, events = _be_factory()
    with _fake_time(1000.0):
        s = _be_state(idle_available=False, idle=retained_idle, user_working=True, social_need=90.0)
        be.step(s, now=1000.0)
    reqs = _action_requests(events)
    assert reqs, "必须发出某个行为请求"
    assert all(r.get("action") not in _USER_DEPENDENT for r in reqs), \
        f"未知(保留 idle={retained_idle})不得 approach: {reqs}"


@pytest.mark.parametrize("retained_idle", [42.0, 600.0])
def test_behavior_fallback_unknown_keeps_self_behavior_available(retained_idle):
    """在场未知 → SELF 行为保持可选（wander 高分胜出），不是什么都不做。"""
    be, events = _be_factory()
    with _fake_time(1000.0):
        s = _be_state(idle_available=False, idle=retained_idle, user_working=False,
                      social_need=90.0, boredom=95.0)
        act = be.step(s, now=1000.0)
    reqs = _action_requests(events)
    assert reqs and reqs[0]["action"] == "wander", f"SELF 应继续: {reqs}"
    assert act == "wander"


def test_behavior_fallback_existing_social_stops_when_presence_becomes_unknown():
    """§3.2：已运行中的 user-dependent 行为在在场变未知时**立即中断**（不等 duration）。"""
    be, events = _be_factory()
    with _fake_time(1000.0) as clock:
        s0 = _be_state(idle_available=True, idle=10.0, user_working=False, social_need=90.0)
        act0 = be.step(s0, now=1000.0)
        assert act0 == "talk_to_user", f"有效在场应先起 talk_to_user: {act0}"
        # 传感器失效：保留 idle=42，时长(10s)远未到 → 必须立即中断
        clock["t"] = 1002.0
        s1 = _be_state(idle_available=False, idle=42.0, user_working=False, social_need=90.0)
        act1 = be.step(s1, now=1002.0)
    reqs = _action_requests(events)
    talks = [p for p in reqs if p.get("action") == "talk_to_user"]
    assert len(talks) == 1, f"talk_to_user 只允许出现一次（t0），未知阶段不得继续: {reqs}"
    intr = [p for t, p in events if t == EventType.BEHAVIOR_INTERRUPTED]
    assert any(p.get("action") == "talk_to_user" and "user_presence_unknown" in p.get("reason", "")
               for p in intr), f"必须中断 talk_to_user(user_presence_unknown): {intr}"
    assert act1 not in _USER_DEPENDENT, f"中断后应转 SELF: {act1}"


def test_behavior_fallback_unknown_does_not_chain_observe_to_approach():
    """§3.3：未知在场不得因 chain_if 读到旧字段而 observe_user→approach_user。"""
    be, events = _be_factory()
    with _fake_time(1000.0) as clock:
        # t0：有效在场 + 工作 → approach 预选（近因使它在 t1 被 observe 压过）
        s0 = _be_state(idle_available=True, idle=10.0, user_working=True, social_need=90.0)
        be.step(s0, now=1000.0)
        # t1：approach 时长到（complete）→ choose：observe(30) > approach(40-近因15) → observe 启动
        clock["t"] = 1010.0
        s1 = _be_state(idle_available=True, idle=2.0, user_working=True, social_need=10.0, boredom=10.0)
        act1 = be.step(s1, now=1010.0)
        assert act1 == "observe_user", f"链起点 observe_user 应启动: {act1}"
        # t2：observe 时长到 + 在场变未知（保留 42）→ 不得 complete→approach
        clock["t"] = 1016.0
        s2 = _be_state(idle_available=False, idle=42.0, user_working=True, social_need=10.0, boredom=10.0)
        act2 = be.step(s2, now=1016.0)
    reqs = _action_requests(events)
    approaches = [p for p in reqs if p.get("action") == "approach_user"]
    assert len(approaches) == 1, f"approach 只允许出现在有效在场阶段(t0)，未知阶段不得链入: {reqs}"
    intr = [p for t, p in events if t == EventType.BEHAVIOR_INTERRUPTED]
    assert any(p.get("action") == "observe_user" for p in intr), f"observe 应被中断: {intr}"
    assert act2 not in _USER_DEPENDENT, f"未知后应转 SELF: {act2}"


def test_behavior_fallback_valid_present_social_still_works():
    """有效在场恢复 → fallback 社交行为按既有 utility 重新可选（不是一刀切禁社交）。"""
    be, events = _be_factory()
    with _fake_time(1000.0):
        s = _be_state(idle_available=True, idle=42.0, user_working=False, social_need=90.0)
        act = be.step(s, now=1000.0)
    reqs = _action_requests(events)
    assert act == "talk_to_user"
    assert any(p.get("action") == "talk_to_user" for p in reqs), f"有效在场应恢复社交: {reqs}"


# ================================================================ §5 Scheduler fallback 集成 F1–F4
class _FallbackWA:
    """生产等价 WindowAwareness fake：poll() 发布 ACTIVE_WINDOW_UPDATED（真实事件路径）。"""

    def __init__(self, bus, info):
        self.bus = bus
        self.info = info
        self.idle_available = info.idle is not None
        self.last_idle = info.idle
        self.show_debug = False

    def set(self, info):
        self.info = info
        self.idle_available = info.idle is not None
        self.last_idle = info.idle

    def poll(self):
        self.bus.emit(EventType.ACTIVE_WINDOW_UPDATED, payload=self.info, source="runtime")
        return self.info


def _fallback_sched(initial_idle):
    """真实 fallback 拓扑：Scheduler + StateEngine + BehaviorEngine + Director + EventBus，
    life_brain=None（走 `se.generate_intent` + `be.step(snapshot)` 生产回退路径）。
    BehaviorEngine 绑定与 Scheduler 同一 bus（生产：App 注册到同一 EventBus）。"""
    from furina.director import Director
    from furina.runtime.window_awareness import WindowInfo
    from furina.runtime.world import Rect, DesktopWorld
    bus = EventBus()
    se = StateEngine(bus)
    be = BehaviorEngine(bus)
    _register_prod_fallbacks(be)
    director = Director(bus)
    executed: list = []
    director.set_executor(lambda req: executed.append((req.source, req.action)))
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    info = WindowInfo(app="ClsX", title="", process="code", idle=initial_idle,
                      rect=Rect(0, 0, 800, 600))
    wa = _FallbackWA(bus, info)
    sched = Scheduler(bus, se, be, director, None, world, wa)   # life_brain=None
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.dispatcher.bind_owner()
    se.state.needs.social_need = 90.0
    se.state.clock_hour = 14
    events: list = []
    for t in (EventType.BEHAVIOR_STARTED, EventType.ACTION_REQUEST,
              EventType.BEHAVIOR_INTERRUPTED, EventType.BEHAVIOR_COMPLETED):
        bus.on(t, lambda ev: events.append((ev.type, ev.payload)))
    return sched, bus, se, be, wa, executed, events


def _win(idle):
    from furina.runtime.window_awareness import WindowInfo
    from furina.runtime.world import Rect
    return WindowInfo(app="ClsX", title="", process="code", idle=idle, rect=Rect(0, 0, 800, 600))


def _drive(sched, wa, info, ticks: int = 5, clock=None) -> None:
    wa.set(info)
    sched._last_window_poll = 0.0
    for _ in range(ticks):
        sched._tick_medium(3.0)
        if clock is not None:
            clock["t"] += 3.0


def test_scheduler_f1_startup_unknown_no_proactive_social():
    """F1：启动即 idle 不可用（idle=0 占位、social_need=90、多 medium tick）→
    无任何 proactive 用户定向 ACTION_REQUEST；SELF/survival 生命继续。"""
    with _fake_time(1000.0) as clock:
        sched, bus, se, be, wa, executed, events = _fallback_sched(initial_idle=None)
        _drive(sched, wa, _win(None), ticks=6, clock=clock)
    pf = presence_facts(sched.world_perc)
    assert pf["known"] is False and pf["present"] is False, "启动未知：unknown ≠ 在场"
    assert sched.world_perc.state.user_activity == UserActivity.UNKNOWN
    reqs = _action_requests(events)
    assert reqs, "必须有 SELF 行为请求（生命继续）"
    assert all(r.get("action") not in _USER_DEPENDENT for r in reqs), \
        f"F1 启动未知不得主动用户定向: {reqs}"
    assert all(r.get("action") in _SELF_LIFE for r in reqs), f"SELF/survival 生命继续: {reqs}"
    assert se.state.intent.action not in ("approach_user", "observe_user"), \
        f"StateEngine 侧也不得主动: {se.state.intent.action}"
    assert se.state.attention.target == AttentionTarget.SELF


def test_scheduler_f2_sensor_failure_retained_active_idle_no_social():
    """F2：首个有效样本 idle=42 → 传感器失效（保留 42 但不可用）→
    canonical 未知、StateEngine 无 proactive social、BehaviorEngine 无 proactive ACTION_REQUEST、
    attention=SELF；已有 user-dependent 行为立即中断。"""
    with _fake_time(1000.0) as clock:
        sched, bus, se, be, wa, executed, events = _fallback_sched(initial_idle=42.0)
        _drive(sched, wa, _win(42.0), ticks=3, clock=clock)     # 有效样本阶段
        boundary = len(events)
        _drive(sched, wa, _win(None), ticks=6, clock=clock)     # 失效（保留 idle=42）
        post = events[boundary:]
    pf = presence_facts(sched.world_perc)
    assert pf["known"] is False and pf["present"] is False, "失效后 canonical 未知"
    assert se.state.user_idle_seconds == 42.0, "保留最后有效值（连续性/debug 数据）"
    assert se.state.attention.target == AttentionTarget.SELF, "attention 必须 SELF"
    assert se.state.intent.action not in ("approach_user", "observe_user"), \
        f"StateEngine 失效后无 proactive social: {se.state.intent.action}"
    post_reqs = [p for t, p in post if t == EventType.ACTION_REQUEST]
    assert all(r.get("action") not in _USER_DEPENDENT for r in post_reqs), \
        f"失效后 BehaviorEngine 无 proactive 用户定向: {post_reqs}"
    intr = [p for t, p in post if t == EventType.BEHAVIOR_INTERRUPTED]
    assert intr, f"失效后运行中的用户定向行为应中断: {[ (t, p) for t, p in post ]}"
    assert any(p.get("action") in _USER_DEPENDENT for p in intr)


def test_scheduler_f3_sensor_failure_retained_away_idle_unknown_not_away():
    """F3：首个有效 idle=600（曾经 away）→ 失效（保留 600）→ unknown，不是"测量到离开"；
    无 proactive social；SELF/survival 继续。"""
    with _fake_time(1000.0) as clock:
        sched, bus, se, be, wa, executed, events = _fallback_sched(initial_idle=600.0)
        _drive(sched, wa, _win(600.0), ticks=3, clock=clock)
        boundary = len(events)
        _drive(sched, wa, _win(None), ticks=6, clock=clock)
        post = events[boundary:]
    pf = presence_facts(sched.world_perc)
    assert pf["known"] is False, "失效后必须 unknown（不是 measured-away）"
    assert se.state.user_idle_seconds == 600.0, "保留最后有效值（连续性/debug 数据）"
    assert se.state.attention.target == AttentionTarget.SELF
    assert se.state.intent.action not in ("approach_user", "observe_user"), \
        f"StateEngine 失效后无 proactive social: {se.state.intent.action}"
    post_reqs = [p for t, p in post if t == EventType.ACTION_REQUEST]
    assert all(r.get("action") not in _USER_DEPENDENT for r in post_reqs), \
        f"失效后 BehaviorEngine 无 proactive 用户定向: {post_reqs}"
    # SELF 生命继续（失效阶段至少有一次 SELF 行为请求或中断后转入）
    self_reqs = [r for r in post_reqs if r.get("action") in _SELF_LIFE]
    assert self_reqs or any(t == EventType.BEHAVIOR_INTERRUPTED for t, _ in post), \
        f"失效阶段 SELF 生命应继续: {post}"


def test_scheduler_f4_valid_present_restored_social_eligible():
    """F4：失效 → 有效在场恢复（idle=42）→ fallback 社交行为重新可选（证明不是一刀切禁社交）。"""
    with _fake_time(1000.0) as clock:
        sched, bus, se, be, wa, executed, events = _fallback_sched(initial_idle=None)
        _drive(sched, wa, _win(None), ticks=3, clock=clock)     # unknown 阶段
        boundary = len(events)
        clock["t"] += 60.0                                       # 越过 SELF 行为滞回窗口
        _drive(sched, wa, _win(42.0), ticks=6, clock=clock)     # 有效在场恢复
        post = events[boundary:]
    pf = presence_facts(sched.world_perc)
    assert pf["known"] is True and pf["present"] is True, "恢复后 canonical 在场"
    post_reqs = [p for t, p in post if t == EventType.ACTION_REQUEST]
    assert any(r.get("action") in _USER_DEPENDENT for r in post_reqs), \
        f"有效在场应恢复 fallback 社交可行性（按既有 utility）: {post_reqs}"
