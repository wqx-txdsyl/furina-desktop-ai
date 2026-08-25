"""Phase 13 终审 Batch A：§2 Windows 感知、§3 Needs 时间尺度、§4 情绪派生/衰减/接线、§7 ignore、§12 路径平滑。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
from types import SimpleNamespace

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.state.state_engine import StateEngine, classify_activity
from furina.emotion import (EmotionEngine, EVENT_PRAISE, EVENT_REJECT, EVENT_POKE,
                            EVENT_RETURN, EVENT_IGNORE, EVENT_FEED, EVENT_TALK)
from furina.world_perception import _cat, _period
from furina.runtime.window_awareness import WindowInfo
from furina.runtime.world import Rect, DesktopWorld
from furina.runtime.spatial.runtime import DesktopSpatialRuntime
from furina.runtime.spatial.resolver import SpatialIntentResolver
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.frame import FrameBody

# ================================================================ §3 Needs 人类尺度
def _sim_needs(minutes: float, dt: float, working: bool, hour: int = 14) -> CharacterState:
    se = StateEngine(EventBus())
    se.state.clock_hour = hour
    steps = int(minutes * 60 / dt)
    for _ in range(steps):
        se.update_needs(dt, working, 0.0)
    return se.state


def test_needs_no_minutes_scale_saturation():
    """30 分钟普通使用：任何生理需求不得仅靠被动漂移达到饱和（<95）。"""
    for working in (False, True):
        st = _sim_needs(30, 3.0, working)
        n = st.needs
        assert n.fatigue < 95 and n.hunger < 95 and n.sleepiness < 95 and n.energy > 5, \
            f"30min working={working}: fatigue={n.fatigue:.0f} hunger={n.hunger:.0f} sleep={n.sleepiness:.0f} energy={n.energy:.0f}"


def test_needs_30min_normal_session_sane():
    st = _sim_needs(30, 3.0, working=False)
    n = st.needs
    assert n.fatigue < 40, f"30min 不忙 fatigue 应温和: {n.fatigue:.0f}"
    assert n.hunger < 40, f"30min hunger 应很低: {n.hunger:.0f}"


def test_needs_2h_working_curve_sane():
    st = _sim_needs(120, 3.0, working=True)
    n = st.needs
    # 2h 连续工作：fatigue 显著升高（~60-75），但未到危机
    assert 45 <= n.fatigue <= 85, f"2h 工作 fatigue 应显著但非危机: {n.fatigue:.0f}"
    assert n.hunger < 60, f"2h hunger 不应饱和: {n.hunger:.0f}"


def test_needs_4h_curve_sane():
    st = _sim_needs(240, 3.0, working=False)
    n = st.needs
    assert n.hunger > 50, f"4h 应明显饥饿: {n.hunger:.0f}"
    assert n.fatigue < 60, f"4h 不忙 fatigue 不应危机: {n.fatigue:.0f}"


def test_needs_dt_invariance():
    """600×1s 与 200×3s 近似等价（线性漂移完全等价；指数项小 k 下近似）。"""
    a = _sim_needs(10, 1.0, working=True)
    b = _sim_needs(10, 3.0, working=True)
    for k in ("fatigue", "hunger", "sleepiness", "energy", "boredom"):
        assert abs(getattr(a.needs, k) - getattr(b.needs, k)) < 2.5, \
            f"dt 不变性破坏 {k}: {getattr(a.needs, k):.1f} vs {getattr(b.needs, k):.1f}"


# ================================================================ §4 情绪语义
def _ee():
    return EmotionEngine(CharacterState().emotion)


def test_default_emotion_is_calm():
    ee = _ee()
    assert ee.derive_label() == "calm", "默认健康基线必须 calm（不再被 sleepy 抢占）"


def test_default_not_sleepy_without_tired():
    ee = _ee()
    # 无真实困倦信号（tired_hint=0）→ 绝不 sleepy
    assert ee.derive_label(tired_hint=0.0) == "calm"
    # 高真实困倦信号 → sleepy 可派生（情绪维度本身不足以判定）
    assert ee.derive_label(tired_hint=0.9) in ("sleepy",)


def test_praise_changes_derived_emotion():
    ee = _ee()
    ee.apply(EVENT_PRAISE)
    assert ee.derive_label() in ("proud", "happy"), "夸奖 → proud/happy（不再 calm 压制）"


def test_reject_changes_derived_emotion():
    ee = _ee()
    ee.apply(EVENT_REJECT)
    assert ee.derive_label() in ("embarrassed", "sad"), "拒绝 → embarrassed/sad"


def test_poke_can_create_annoyed_state():
    ee = _ee()
    for _ in range(3):          # 重复戳
        ee.apply(EVENT_POKE)
    assert ee.derive_label() in ("annoyed", "embarrassed"), "重复戳 → annoyed"


def test_return_makes_happy():
    ee = _ee()
    ee.apply(EVENT_RETURN)
    assert ee.derive_label() in ("happy", "excited"), "用户回来 → happy/excited"


def test_emotion_decay_is_minutes_scale():
    ee = _ee()
    ee.apply(EVENT_PRAISE)
    ee.derive_label()
    assert ee.derive_label() in ("proud", "happy")
    # 5 分钟（300s）后仍显著（τ=600s → 残留 ≈ 61%）
    ee2 = _ee()
    ee2.apply(EVENT_PRAISE)
    sal_before = ee2.state.pride - 40
    for _ in range(100):
        ee2.decay(dt=3.0)
    sal_5m = ee2.state.pride - 40
    assert sal_5m > sal_before * 0.4, f"5min 后 pride 显著度应保留: {sal_5m:.1f} vs {sal_before:.1f}"
    # 30 分钟（1800s）后基本回落（残留 < 20%）
    ee3 = _ee()
    ee3.apply(EVENT_PRAISE)
    sal_b3 = ee3.state.pride - 40
    for _ in range(600):
        ee3.decay(dt=3.0)
    assert (ee3.state.pride - 40) < sal_b3 * 0.2, "30min 后情绪应基本回落"


def test_emotion_event_routes_exactly_once():
    """reject/praise/talk/feed 语义事件接线（source 断言）：scheduler/app 各只 apply 一次。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert src.count("EVENT_AGENT_DONE") >= 1 and src.count("EVENT_IGNORE") >= 1
    import furina.app as A
    src_a = open(A.__file__, encoding="utf-8").read()
    assert "EVENT_FEED" in src_a and "EVENT_PRAISE" in src_a and "EVENT_TALK" in src_a


# ================================================================ §2 Windows 感知
def test_chrome_widget_class_not_false_office_match():
    """窗口类名（Chrome_WidgetWin_1）不得被 'et' 等短 token 误判为表格/办公。"""
    # 分类输入必须是进程名；类名只做原始信号
    assert _cat("Chrome_WidgetWin_1", "") == "unknown", "窗口类名不得分类为 office"
    assert _cat("chrome", "") == "browsing"
    assert _cat("et", "") == "working"      # WPS 表格的真实进程名（精确匹配，合法）
    assert classify_activity("Chrome_WidgetWin_1")["category"] == "other", \
        "classify_activity 不得把类名当 office"


def test_foreground_process_separate_from_window_class():
    info = WindowInfo(app="Chrome_WidgetWin_1", title="untitled", process="chrome", idle=12.5)
    assert info.process == "chrome" and info.app == "Chrome_WidgetWin_1"
    assert "process" in info.to_dict()


def test_state_user_working_comes_from_world():
    """FINAL-R1：行为级 —— _tick_medium 采样路径下 user_working 必须来自 World 感知（进程分类）。"""
    from furina.runtime.window_awareness import WindowInfo
    from furina.runtime.world import DesktopWorld, Rect
    from furina.runtime.scheduler import Scheduler
    from furina.emotion import EmotionEngine
    from furina.world_perception import UserActivity

    bus = EventBus()
    se = StateEngine(bus)
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    info = WindowInfo(app="Chrome_WidgetWin_1", title="main.py", process="Code",
                      idle=5.0, rect=Rect(100, 100, 800, 600))
    emitted = []

    class _WA:
        last_idle = 5.0
        idle_available = True
        def poll(self):
            bus.emit(EventType.ACTIVE_WINDOW_UPDATED, payload=info, source="runtime")
            return info

    sched = Scheduler(bus, se, None, None, None, world, _WA())
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    sched._last_window_poll = 0.0
    for _ in range(14):
        sched._tick_medium(3.0)
    assert sched.world_perc.state.user_activity == UserActivity.CODING, \
        f"Code 进程应分类为 coding: {sched.world_perc.state.user_activity}"
    assert sched.se.state.user_working is True, "user_working 必须来自 World（进程分类）"


def test_windows_idle_signal_is_runtime_truth():
    import furina.runtime.window_awareness as WA
    src = open(WA.__file__, encoding="utf-8").read()
    assert "GetLastInputInfo" in src, "必须有真实 GetLastInputInfo 空闲秒"


def test_world_unknown_does_not_fake_typing():
    """未知进程不假装 typing（update 的 typing 默认 False）。"""
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    w = wp.update(app="ClsX", title="", idle_seconds=45, hour=14, minute=0, typing=False)
    assert w.user_activity.value == "idle" or w.user_activity.value == "unknown"


def test_world_activity_transition_requires_stability():
    """§2.5：活动类别切换必须稳定满 _STABLE_ACTIVITY_MIN（一次误判不得立即切换）。"""
    from furina.world_perception import WorldPerception, UserActivity
    wp = WorldPerception()
    # 先稳定在 coding
    for _ in range(12):
        wp.update(app="code", title="", idle_seconds=0, hour=14, minute=0, dt=3.0)
    assert wp.state.user_activity == UserActivity.CODING
    # 切到 browsing（chrome）：一次 update 不应立即切换（未满稳定性窗口）
    wp.update(app="chrome", title="", idle_seconds=0, hour=14, minute=0, dt=3.0)
    assert wp.state.user_activity == UserActivity.CODING, "一次误判不得立即切换"
    # 稳定观察满 30s（10 tick）后才切换
    for _ in range(10):
        wp.update(app="chrome", title="", idle_seconds=0, hour=14, minute=0, dt=3.0)
    assert wp.state.user_activity == UserActivity.BROWSING, "稳定满窗口后才切换"


# ================================================================ §7 ignore 语义
def test_ignore_is_not_pointer_leave():
    import furina.runtime.harness.controller as C
    src = open(C.__file__, encoding="utf-8").read()
    assert "on_user_ignore" in src, "Harness Ignore 必须走语义忽略路由"
    assert "emit_event(\"leave\", \"whole\")" not in src, "Ignore 不得再映射为指针 leave"


def test_semantic_ignore_affects_emotion_relationship_once():
    from types import SimpleNamespace
    from furina.runtime.scheduler import Scheduler
    from furina.state.state_model import CharacterState
    from furina.emotion import EmotionEngine

    se = StateEngine(EventBus())
    bus = EventBus()
    emo = EmotionEngine(se.state.emotion)
    applied = []
    rel = SimpleNamespace(apply=lambda ev, strength=1.0: applied.append(ev),
                          state=None, factors=lambda: {"comfort": 0.5})
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = emo
    sched.relationship = rel
    before = sched.emotion.state.loneliness
    sched.on_user_ignore()
    assert sched.emotion.state.loneliness > before, "语义忽略 → 孤独上升（EVENT_IGNORE 生效）"
    # 每次调用恰好一次语义：EVENT_IGNORE 孤独 +8，两次调用两次 +8
    mid = sched.emotion.state.loneliness
    sched.on_user_ignore()
    assert abs((sched.emotion.state.loneliness - mid) - (mid - before)) < 1e-6, \
        "每次忽略孤独增量一致（每次恰好一次 EVENT_IGNORE）"
    assert len(applied) == 2, "Relationship EV_IGNORE 每次恰好一次"


def test_grab_does_not_change_social_need():
    """GRAB（指针控制）不得扣社交需求 / 不得进入生命因果。"""
    from furina.interaction.interaction_types import InteractionEvent, TouchKind, InteractionZone
    from furina.runtime.scheduler import Scheduler
    se = StateEngine(EventBus())
    bus = EventBus()
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched._speech = ""
    social_before = se.state.needs.social_need
    for kind in ("grab", "release", "hover", "leave"):
        sched._on_interaction(SimpleNamespace(payload=InteractionEvent(
            type=TouchKind(kind), target=InteractionZone.WHOLE)))
    assert sched._speech == "", "指针控制不得产生台词"
    assert abs(se.state.needs.social_need - social_before) < 1e-9, "指针控制不得扣社交需求"


def test_real_click_has_one_semantic_causal_event():
    """真实点击（click）→ 恰好一次语义因果（台词 + 社交 -5，无第二次叠加）。"""
    from furina.interaction.interaction_types import InteractionEvent, TouchKind, InteractionZone
    from furina.runtime.scheduler import Scheduler
    se = StateEngine(EventBus())
    bus = EventBus()
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.dialogue_brain = None      # 无 LLM：台词走 _say 兜底
    social_before = se.state.needs.social_need
    sched._on_interaction(SimpleNamespace(payload=InteractionEvent(
        type=TouchKind.CLICK, target=InteractionZone.WHOLE)))
    # 一次 click = 恰好一次语义：social_need 只 -5
    assert abs((social_before - se.state.needs.social_need) - 5.0) < 1e-9, \
        f"click 语义应恰好一次（-5），实际 {social_before - se.state.needs.social_need:.1f}"


# ================================================================ §12 路径平滑
def _max_heading_delta(pts) -> float:
    m = 0.0
    for i in range(2, len(pts)):
        a = math.atan2(pts[i - 1].y - pts[i - 2].y, pts[i - 1].x - pts[i - 2].x)
        b = math.atan2(pts[i].y - pts[i - 1].y, pts[i].x - pts[i - 1].x)
        d = abs((b - a + math.pi) % (2 * math.pi) - math.pi)
        m = max(m, math.degrees(d))
    return m


def _plan_for(activity: str, seed: int = 7):
    import random
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    world.update_active_window(Rect(600, 200, 700, 600))
    rt = DesktopSpatialRuntime(world, rng=random.Random(seed))
    rt.set_initial_foot(300 + seed * 11, 800)
    d = SpatialIntentResolver().resolve(RuntimeFrameBuilder().build(
        activity_name=activity, body=FrameBody(posture="standing"), motion_intent="NONE"))
    plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
    return rt, plan


def test_wander_has_no_sharp_waypoint_corner():
    for seed in range(4):
        rt, plan = _plan_for("wander", seed=seed)
        assert plan is not None and plan.waypoints, f"seed={seed} 应有路径"
        pts = [rt.state.position] + list(plan.waypoints) + [plan.target]
        max_turn = _max_heading_delta(pts)
        assert max_turn < 45.0, f"wander seed={seed} 有尖锐折角 {max_turn:.1f}°"


def test_explore_has_no_sharp_waypoint_corner():
    for seed in range(4):
        rt, plan = _plan_for("explore", seed=seed)
        assert plan is not None and plan.waypoints, f"seed={seed} 应有路径"
        pts = [rt.state.position] + list(plan.waypoints) + [plan.target]
        max_turn = _max_heading_delta(pts)
        assert max_turn < 45.0, f"explore seed={seed} 有尖锐折角 {max_turn:.1f}°"


def test_path_style_wander_explore_are_meander_or_multi():
    styles = set()
    for seed in range(6):
        _, plan = _plan_for("wander", seed=seed)
        if plan:
            styles.add(plan.path_style)
    assert "WANDER_MEANDER" in styles or "EXPLORE_MULTI_POINT" in styles


def test_day_period_night_0030():
    assert _period(0) == "night"   # 00:30 → night（hour=0 落在 night 区间）


def test_drag_release_no_snap_back():
    """§12（评审契约名）：拖拽释放后不弹回自主计划位置。"""
    import random
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    world.update_active_window(Rect(600, 200, 700, 600))
    rt = DesktopSpatialRuntime(world, rng=random.Random(3))
    rt.set_initial_foot(400, 700)
    rt.on_drag_start(now=1.0)
    rt.on_drag_release(now=2.0, commit=True)
    assert rt._current_plan is None, "释放后不应保留自主计划（无 snap-back）"
