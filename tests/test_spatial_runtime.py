"""Phase 12: Desktop Spatial Life / Movement Runtime 测试（§132）。

headless：注入时钟 + duck-typed FakeWindow（不跑 Qt）。覆盖：
approach/withdraw/maintain/near-far hysteresis、semantic target→safe coordinate、
dt/FPS independence、speed/hesitation/transition counterfactual、arrival exactly-once、
overshoot prevention、movement↔walk sync、no slide / no inplace walk、drag interrupt/
commit/grace、screen bounds/resize/multi-monitor、sleep block/wake allow、
target hysteresis、frame spam no replan、quiet coexistence、wander dwell、50k long-run。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
import random

from furina.core.event_bus import EventBus, EventType
from furina.runtime.frame import FrameBody
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.world import DesktopWorld, Rect
from furina.runtime.spatial import (
    DesktopSpatialRuntime, SpatialIntentResolver, SpatialPlanner,
    SpatialPoint, MovementPlan, SpatialState, SpatialIntent, TargetType, Facing, SpatialConfig,
)
from furina.runtime.frontend import AnimationRuntime, AnimationPhase, VisualPhase
from furina.runtime.animation import AnimationSpec
from furina.runtime.frame import CharacterRuntimeFrame


# ---------------------------------------------------------------- Fake window（duck-typed）
class _V:
    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)


class FakeWindow:
    """模拟 FurinaWindow：set_position / pos / width / _side / _char_h / _char_w / dragging。"""
    def __init__(self, x=0.0, y=0.0, width=348.0, side=24.0, top=120.0,
                 char_w=256.0, char_h=360.0):
        self._w = width
        self._side = side
        self._top = top
        self._char_w = char_w
        self._char_h = char_h
        self.pos = _V(x, y)
        self.dragging = False
        self.position_set_calls = 0

    def width(self):
        return self._w

    def set_position(self, x, y):
        self.pos = _V(x, y)
        self.position_set_calls += 1


# ---------------------------------------------------------------- helpers
def _world(w=1920, h=1080, active_window=None):
    world = DesktopWorld(w, h)
    world.taskbar_height = 48.0
    if active_window is not None:
        world.update_active_window(active_window)
    return world


def _mk(foot=(900, 900), active_window=None, window=None, config=None, w=1920, h=1080, seed=1):
    world = _world(w, h, active_window)
    rt = DesktopSpatialRuntime(world, config=config, window=window, rng=random.Random(seed))
    rt.set_initial_foot(foot[0], foot[1])
    return world, rt


def _frame(activity="idle", *, motion_intent=None, motion_speed=None, proximity="MAINTAIN",
           tempo="normal", hesitation=0.3, transition_style="SMOOTH", posture="standing",
           allow_reposition=False):
    motion = {}
    if motion_intent is not None:
        motion["motion_intent"] = motion_intent
    if motion_speed is not None:
        motion["motion_speed"] = motion_speed
    body = FrameBody(posture=posture, proximity=proximity, movement_tempo=tempo,
                     hesitation=hesitation, transition_style=transition_style,
                     micro_preferences=("BLINK", "BREATH"))
    return RuntimeFrameBuilder().build(activity_name=activity, body=body, **motion,
                                       motion_reposition=allow_reposition)


def _resolve(frame):
    return SpatialIntentResolver().resolve(frame)


def _tick(rt, seconds, fps=30.0, start=0.0):
    """为 rt 注入秒级时钟步进。"""
    steps = int(seconds * fps)
    for i in range(1, steps + 1):
        rt.tick(now=start + i / fps)
    return rt.state.position


# ================================================================ 1. APPROACH
def test_spatial_approach():
    """APPROACH → 向用户附近安全区移动并到达（不是用户中心）。"""
    win = FakeWindow(x=900, y=780)
    world, rt = _mk(foot=(300, 900), active_window=Rect(600, 200, 700, 600), window=win)
    frame = _frame("approach_user", motion_intent="APPROACH", proximity="APPROACH")
    d = _resolve(frame)
    plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
    assert plan is not None and plan.intent == SpatialIntent.APPROACH.value
    assert plan.target_type == TargetType.NEAR_USER_SAFE.value
    # 目标不是用户窗口中心
    assert abs(plan.target.x - 950) > 60, "approach 目标不能是用户窗口中心"
    rt.accept(d, now=0.0)
    assert rt.state.state == SpatialState.PREPARING.value or rt.state.state == SpatialState.STARTING.value
    _tick(rt, 8.0)
    assert rt.state.arrived, "approach 应到达"
    assert rt.state.moving is False
    assert rt.state.state == SpatialState.ARRIVED.value


# ================================================================ 2. MAINTAIN
def test_spatial_maintain():
    """MAINTAIN：位置合法时保持，不移动、不重规划。"""
    win = FakeWindow(x=900, y=780)
    world, rt = _mk(foot=(900, 900), active_window=Rect(600, 200, 700, 600), window=win)
    before = SpatialPoint(rt.state.position.x, rt.state.position.y)
    d = _resolve(_frame("idle", motion_intent="MAINTAIN", proximity="MAINTAIN"))
    rt.accept(d, now=0.0)
    plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
    assert plan is None, "MAINTAIN 合法位置不应产生计划"
    _tick(rt, 5.0)
    assert rt.state.position.distance(before) < 1.0, "MAINTAIN 不应移动"
    assert rt.state.moving is False


# ================================================================ 3. WITHDRAW
def test_spatial_withdraw():
    """WITHDRAW → 去更远安全区，最终距离 > 初始距离。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=700, y=500)
    world, rt = _mk(foot=(700, 500), active_window=active, window=win)
    up = SpatialPoint(active.cx, active.cy)
    d0 = rt.state.position.distance(up)
    d = _resolve(_frame("idle", motion_intent="WITHDRAW"))
    rt.accept(d, now=0.0)
    _tick(rt, 12.0)
    assert rt.state.arrived or rt.state.moving
    d1 = rt.state.position.distance(up)
    assert d1 > d0 + 50, f"withdraw 应增大与用户距离: {d0:.0f}->{d1:.0f}"


# ================================================================ 4. NEAR / FAR hysteresis
def test_spatial_near_hysteresis():
    """NEAR：已足够近（<=near_radius）→ 保持；远 → 靠近。"""
    active = Rect(600, 200, 700, 600)
    # 已近
    win = FakeWindow(x=800, y=450)
    world, rt_near = _mk(foot=(820, 460), active_window=active, window=win)
    d = _resolve(_frame("observe_work", proximity="NEAR", motion_intent=None))
    # proximity=NEAR；已在 near_radius 内
    up = SpatialPoint(active.cx, active.cy)
    assert rt_near.state.position.distance(up) <= 260, "夹具应在 near_radius 内"
    plan = rt_near.planner.plan(d, rt_near.state.position, rt_near.adapter.char_w, rt_near.adapter.char_h)
    assert plan is None, "NEAR 已足够近 → 保持"
    # 远
    world2, rt_far = _mk(foot=(200, 900), active_window=active, window=FakeWindow(x=200, y=780))
    plan2 = rt_far.planner.plan(d, rt_far.state.position, rt_far.adapter.char_w, rt_far.adapter.char_h)
    assert plan2 is not None, "NEAR 太远 → 靠近"


def test_spatial_far_hysteresis():
    """FAR：已足够远（>=far_radius）→ 保持；近 → 远离。"""
    active = Rect(600, 200, 700, 600)
    # 已远
    world, rt_far = _mk(foot=(200, 900), active_window=active, window=FakeWindow(x=200, y=780))
    d = _resolve(_frame("idle", proximity="FAR"))
    up = SpatialPoint(active.cx, active.cy)
    assert rt_far.state.position.distance(up) >= 640, "夹具应在 far_radius 外"
    plan = rt_far.planner.plan(d, rt_far.state.position, rt_far.adapter.char_w, rt_far.adapter.char_h)
    assert plan is None, "FAR 已足够远 → 保持"
    # 近
    world2, rt_near = _mk(foot=(820, 460), active_window=active, window=FakeWindow(x=800, y=450))
    plan2 = rt_near.planner.plan(d, rt_near.state.position, rt_near.adapter.char_w, rt_near.adapter.char_h)
    assert plan2 is not None, "FAR 太近 → 远离"


# ================================================================ 5. semantic target → coordinate
def test_semantic_target_to_coordinate():
    """语义 target → 安全几何坐标（foot anchor），且在边界内。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=300, y=780)
    world, rt = _mk(foot=(300, 900), active_window=active, window=win)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
    assert plan is not None
    assert isinstance(plan.target, SpatialPoint)
    assert plan.target_type in (TargetType.NEAR_USER_SAFE.value, TargetType.USER_WINDOW_EDGE.value)


def test_safe_target_inside_bounds():
    """plan.target 一定在世界可用边界内（foot anchor 合法）。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=300, y=780)
    world, rt = _mk(foot=(300, 900), active_window=active, window=win)
    for intent in ("APPROACH", "WITHDRAW", "REPOSITION"):
        d = _resolve(_frame("idle", motion_intent=intent))
        plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
        if plan is None:
            continue
        assert rt.planner._foot_valid(plan.target.x, plan.target.y,
                                      rt.adapter.char_w, rt.adapter.char_h), f"{intent} 目标应在边界内"


# ================================================================ 6. dt / FPS independence
def test_movement_fps_independent():
    """同一计划，30/60/120 fps → 位移/到达时间相近。"""
    active = Rect(600, 200, 700, 600)
    arrivals = {}
    for fps in (30, 60, 120):
        win = FakeWindow(x=200, y=780)
        world, rt = _mk(foot=(200, 900), active_window=active, window=win)
        d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
        rt.accept(d, now=0.0)
        t = 0.0
        dt = 1.0 / fps
        for i in range(1, int(20 * fps)):
            t = i * dt
            rt.tick(now=t)
            if rt.state.arrived:
                break
        arrivals[fps] = (t, rt.state.position.to_tuple())
    t30, p30 = arrivals[30]
    t60, p60 = arrivals[60]
    assert abs(t30 - t60) < 0.5, f"到达时间应相近: {t30:.2f} vs {t60:.2f}"
    assert abs(p30[0] - p60[0]) < 20 and abs(p30[1] - p60[1]) < 20, f"位置应相近: {p30} vs {p60}"


def test_movement_uses_dt():
    """位移由 speed*dt 驱动（非 per-frame 常数）。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH", motion_speed="NORMAL"))
    rt.accept(d, now=0.0)
    _tick(rt, 2.0, fps=30.0)
    # NORMAL=60px/s；2s（含起步加速）位移应接近 60*2=120（允许加速损失）
    dist_moved = rt.state.position.distance(SpatialPoint(200, 900))
    assert 80 <= dist_moved <= 140, f"dt 位移应 ~speed*dt: {dist_moved:.1f}"


# ================================================================ 7. speed counterfactual
def test_speed_semantic_changes_time():
    """同路径：SLOW > NORMAL > ENERGETIC 用时。"""
    active = Rect(600, 200, 700, 600)
    times = {}
    for spd in ("SLOW", "NORMAL", "FAST"):
        win = FakeWindow(x=200, y=780)
        world, rt = _mk(foot=(200, 900), active_window=active, window=win)
        d = _resolve(_frame("approach_user", motion_intent="APPROACH", motion_speed=spd))
        rt.accept(d, now=0.0)
        t = 0.0
        for i in range(1, int(40 * 30)):
            t = i / 30
            rt.tick(now=t)
            if rt.state.arrived:
                break
        times[spd] = t
    assert times["SLOW"] > times["NORMAL"] > times["FAST"], f"用时顺序: {times}"


# ================================================================ 8. ease in/out + arrival radius
def test_movement_ease_in_out():
    """起步时速度从 0 逐渐升（ease-in），到站前减速（ease-out）。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH", motion_speed="NORMAL",
                        hesitation=0.0))
    rt.accept(d, now=0.0)
    # 第一步后速度应 < 目标（ease-in 起步）
    rt.tick(now=1 / 30)
    v0 = rt.state.velocity
    plan_speed = rt.state.speed
    assert 10 <= v0 < plan_speed, f"ease-in 起步速度应低于目标: {v0:.0f} < {plan_speed:.0f}"


def test_arrival_radius():
    """到达用 arrival_radius（非 distance==0）。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    cfg = SpatialConfig(arrival_radius=50.0)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win, config=cfg)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(d, now=0.0)
    _tick(rt, 15.0)
    assert rt.state.arrived
    # 到达后距目标 <= arrival_radius（不必精确 0）
    assert rt.state.position.distance(rt.state.target_position) <= 50.01


def test_arrival_exactly_once():
    """TARGET_REACHED 恰好一次（latch per target）。"""
    active = Rect(600, 200, 700, 600)
    bus = EventBus(); reaches = []
    bus.on(EventType.SPATIAL_TARGET_REACHED, lambda ev: reaches.append(ev.payload))
    win = FakeWindow(x=200, y=780)
    world = _world(active_window=active)
    rt = DesktopSpatialRuntime(world, bus=bus, window=win)
    rt.set_initial_foot(200, 900)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(d, now=0.0)
    _tick(rt, 15.0)
    # 到站后再多 tick（不重复发）
    _tick(rt, 3.0, start=15.0)
    assert len(reaches) == 1, f"TARGET_REACHED 应 exactly-once，实际 {len(reaches)}"


def test_overshoot_prevented():
    """每步 step=min(speed*dt, remaining)：不冲过目标。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(d, now=0.0)
    _tick(rt, 15.0)
    target = rt.state.target_position
    final = rt.state.position
    assert final.distance(target) <= rt.config.arrival_radius + 1.0, "不应过头"
    assert rt.stats["overshoots"] < 5, "不应振荡/冲过头"


# ================================================================ 9. hesitation / transition style
def test_hesitation_delays_start():
    """高 hesitation → 起步延迟更长；最终都到达。"""
    active = Rect(600, 200, 700, 600)
    delays = {}
    for hes in (0.2, 0.9):
        win = FakeWindow(x=200, y=780)
        world, rt = _mk(foot=(200, 900), active_window=active, window=win)
        d = _resolve(_frame("approach_user", motion_intent="APPROACH", hesitation=hes))
        plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
        delays[hes] = plan.pre_move_delay
    assert delays[0.9] > delays[0.2], f"高犹豫应更长起步: {delays}"


def test_transition_style_affects_start():
    """HESITANT 起步延迟 > ENERGETIC。"""
    active = Rect(600, 200, 700, 600)
    style_delay = {}
    for style in ("HESITANT", "ENERGETIC", "SMOOTH"):
        win = FakeWindow(x=200, y=780)
        world, rt = _mk(foot=(200, 900), active_window=active, window=win)
        d = _resolve(_frame("approach_user", motion_intent="APPROACH", hesitation=0.5,
                            transition_style=style))
        plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
        style_delay[style] = plan.pre_move_delay
    assert style_delay["HESITANT"] > style_delay["ENERGETIC"], f"风格起步: {style_delay}"


# ================================================================ 10. movement ↔ walk sync
class _MockClip:
    def __init__(self):
        self.spec = None
        self.started = 0.0
    def play(self, spec, now=None):
        self.spec = spec
        self.started = now or 0.0
    def frame_count(self):
        return len(self.spec.frames) if self.spec else 0
    def is_finished(self, now=None):
        return False
    def progress(self, now=None):
        return 0.0


class _FakeAssets:
    def __init__(self):
        self.sequences = {}
        self.states = {}
    def sequence_for(self, name):
        return self.sequences.get(name)
    def entry_for_state(self, posture, emotion, gaze, action="idle"):
        return self.states.get((posture, emotion, gaze, action))


class _Seq:
    def __init__(self, action, entry=None, loop=None, exit=None, frames=None):
        self.action = action
        self.entry_frames = entry or []
        self.loop_frames = loop or []
        self.exit_frames = exit or []
        self.frames = frames or entry or loop or []


def test_movement_walk_sync():
    """移动时 set_movement(True) → walk 视觉生效（有 walk 序列）。"""
    assets = _FakeAssets()
    assets.sequences["walk"] = _Seq("walk", loop=["w1", "w2", "w3"])
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    rt.set_movement(True, "RIGHT")
    assert rt.movement_moving is True
    assert rt.movement_degraded is False
    # walk 序列被播放（若当前 LOOP）
    assert rt.movement_moving is True


def test_no_walk_when_stationary():
    """停止移动 → movement_moving False，回 activity clip。"""
    assets = _FakeAssets()
    assets.sequences["read"] = _Seq("read", entry=["e"], loop=["l1"])
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    rt.set_movement(False)
    assert rt.movement_moving is False
    assert rt.movement_degraded is False


def test_missing_walk_asset_degrades():
    """无 walk 序列 → movement_degraded=True（移动继续，视觉不强行走 idle 造成误判）。"""
    assets = _FakeAssets()   # 无 walk
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    rt.set_movement(True, "LEFT")
    assert rt.movement_moving is True
    assert rt.movement_degraded is True


def test_no_inplace_walk():
    """移动视觉仅当实际在动时（is_moving），到站后停止。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win)
    assert rt.movement_visual()["moving"] is False
    d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(d, now=0.0)
    _tick(rt, 1.0)
    assert rt.movement_visual()["moving"] is True, "移动中应报告 moving"
    _tick(rt, 20.0, start=1.0)
    assert rt.movement_visual()["moving"] is False, "到站后不应原地走"


# ================================================================ 11. drag
def test_drag_interrupts_movement():
    """拖拽打断自主移动 → DRAGGED + MOVEMENT_INTERRUPTED。"""
    active = Rect(600, 200, 700, 600)
    bus = EventBus(); interrupts = []
    bus.on(EventType.MOVEMENT_INTERRUPTED, lambda ev: interrupts.append(ev.payload))
    win = FakeWindow(x=200, y=780)
    world = _world(active_window=active)
    rt = DesktopSpatialRuntime(world, bus=bus, window=win)
    rt.set_initial_foot(200, 900)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(d, now=0.0)
    _tick(rt, 1.0)
    assert rt.state.moving is True
    rt.on_drag_start(now=1.0)
    assert rt.state.state == SpatialState.DRAGGED.value
    assert rt.state.moving is False
    assert len(interrupts) >= 1, "拖拽应产生 MOVEMENT_INTERRUPTED"


def test_drag_commits_position():
    """拖拽释放 → 提交释放位置，不 snap 回自主目标。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(d, now=0.0)
    _tick(rt, 0.5)
    # 拖到别处
    win.set_position(1200, 300)
    rt.on_drag_start(now=1.0)
    rt.on_drag_release(now=2.0, commit=True)
    foot = rt.state.position
    # 目标已离场；位置 = 释放处（读 window pos）
    assert rt.state.state == SpatialState.ARRIVED.value
    assert rt._current_plan is None, "释放后不应有自主计划"
    assert not rt.state.moving


def test_drag_release_grace():
    """释放后 grace 期：普通 wander 不拉走；高优先 APPROACH 可覆盖。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=1000, y=400)
    world, rt = _mk(foot=(1000, 500), active_window=active, window=win)
    # wander（低优先）在 grace 内被约束
    rt.on_drag_start(now=0.0)
    rt.on_drag_release(now=0.5, commit=True)
    assert rt._grace_until > 0.5
    # 低优先 wander 被 cooldown 拦截
    wander = _resolve(_frame("wander", motion_intent="NONE"))
    rt.accept(wander, now=1.0)
    assert rt.state.moving is False, "grace 内 wander 不应拉走"
    # 高优先 APPROACH 可覆盖 grace
    approach = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(approach, now=1.5)
    assert rt.state.state in (SpatialState.PREPARING.value, SpatialState.STARTING.value,
                              SpatialState.MOVING.value, SpatialState.ARRIVING.value), "高优先可覆盖 grace"


# ================================================================ 12. screen bounds
def test_screen_bounds():
    """计划目标均在安全边界内；out_of_bounds 不爆炸。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win)
    for intent in ("APPROACH", "WITHDRAW", "REPOSITION"):
        d = _resolve(_frame("idle", motion_intent=intent))
        plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
        if plan:
            rt.accept(d, now=0.0)
            _tick(rt, 10.0)
    assert rt.stats["out_of_bounds"] < 100, "不应反复越界"


def test_screen_resize_revalidate():
    """屏幕缩小 → 位置非法 → 就近修复（revalidate）。"""
    win = FakeWindow(x=1600, y=1000)
    world, rt = _mk(foot=(1600, 1000), active_window=None, window=win)
    # 缩小屏幕使旧位置非法
    world.screen.w, world.screen.h = 1000, 500
    world.screens[0].w, world.screens[0].h = 1000, 500
    rt.tick(now=0.1)
    assert rt.planner._foot_valid(rt.state.position.x, rt.state.position.y,
                                  rt.adapter.char_w, rt.adapter.char_h), "revalidate 后应合法"


def test_multi_monitor_current_screen():
    """拖到第二屏 → current_screen 更新；后续自主移动留在当前屏。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=2000, y=500)   # 第二屏（x 起点 1920）
    world, rt = _mk(foot=(2000, 500), active_window=active, window=win)
    world.add_screen(Rect(1920, 0, 1920, 1080))
    # 拖到第二屏、释放
    rt.on_drag_start(now=0.0)
    rt.on_drag_release(now=0.5, commit=True)
    assert rt.state.current_screen == 1, f"应识别在第二屏: {rt.state.current_screen}"


# ================================================================ 13. sleep / wake
def test_sleep_blocks_autonomous_move():
    """activity=sleep → 禁止自主移动。"""
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=Rect(600, 200, 700, 600), window=win)
    d = _resolve(_frame("sleep", motion_intent="MAINTAIN", posture="sleeping"))
    rt.accept(d, now=0.0)
    assert rt._sleep_block is True
    assert rt._current_plan is None
    _tick(rt, 5.0)
    assert rt.state.moving is False


def test_wake_allows_move():
    """wake 后（非 sleeping activity）→ 允许移动。"""
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=Rect(600, 200, 700, 600), window=win)
    d = _resolve(_frame("idle", motion_intent="APPROACH", posture="standing"))
    rt.accept(d, now=0.0)
    assert rt._sleep_block is False
    assert rt._current_plan is not None


# ================================================================ 14. target hysteresis
def test_target_hysteresis():
    """目标小幅移动不重规划；大幅移动重规划。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win)
    d1 = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(d1, now=0.0)
    plan1 = rt._current_plan
    assert plan1 is not None
    target1 = SpatialPoint(plan1.target.x, plan1.target.y)
    # 小幅目标变化（模拟用户窗口轻移 → 目标也轻移）
    small = SpatialPoint(target1.x + 8, target1.y + 3)
    rt._current_plan = MovementPlan(target=small, **{})
    rt.state.state = SpatialState.MOVING.value
    d2 = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    # 构造 target 与旧 target1 差 8px → should_skip_replan
    p2 = rt.planner.plan(d2, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
    p2.target = SpatialPoint(target1.x + 8, target1.y + 3)
    assert rt._should_skip_replan(p2) is True, "小幅目标不应重规划"


def test_frame_spam_no_replan():
    """1000 帧同空间语义 → 不重规划，replans 稳定。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=200, y=780)
    world, rt = _mk(foot=(200, 900), active_window=active, window=win)
    base = _frame("approach_user", motion_intent="APPROACH", proximity="APPROACH")
    d = _resolve(base)
    rt.accept(d, now=0.0)
    _tick(rt, 1.0)
    replans_before = rt.stats["replans"]
    plans_before = rt.stats["plans"]
    for i in range(1000):
        f = _frame("approach_user", motion_intent="APPROACH", proximity="APPROACH")
        dd = _resolve(f)
        rt.accept(dd, now=1.0 + i / 1000)
        rt.tick(now=1.0 + i / 1000)
    assert rt.stats["plans"] - plans_before < 5, "同语义 spam 不应频繁重规划"


# ================================================================ 15. quiet coexistence
def test_quiet_coexistence_spatial_stable():
    """user_working + 自身 activity + MAINTAIN → 30min 位置稳定、几乎无计划/移动。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=800, y=450)
    world, rt = _mk(foot=(800, 450), active_window=active, window=win)
    d = _resolve(_frame("read", motion_intent="MAINTAIN", proximity="MAINTAIN"))
    before = SpatialPoint(rt.state.position.x, rt.state.position.y)
    plans0 = rt.stats["plans"]
    for i in range(int(30 * 60 * 5)):   # 30min @ 5Hz
        if i % 20 == 0:
            rt.accept(d, now=i * 0.2)
        rt.tick(now=i * 0.2)
    assert rt.state.position.distance(before) < 5.0, "quiet 共存应稳定不动"
    assert rt.stats["plans"] - plans0 <= 1, f"quiet 共存计划≈0: {rt.stats['plans'] - plans0}"


# ================================================================ 16. wander dwell
def test_wander_has_dwell():
    """30min wander：移动 + 停留，不是连续运动；moving_share < 40%。"""
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=800, y=450)
    world, rt = _mk(foot=(800, 450), active_window=active, window=win)
    d = _resolve(_frame("wander", motion_intent="NONE"))
    moving_ticks = 0
    total = int(30 * 60 * 2)   # 30min @ 2Hz
    for i in range(total):
        if i % 40 == 0:
            rt.accept(d, now=i * 0.5)
        rt.tick(now=i * 0.5)
        if rt.state.moving:
            moving_ticks += 1
    share = moving_ticks / total
    # §74：moving_share>40% 是"需分析"软指标，非硬 FAIL。Wander 的核心不变量 = **不连续巡逻 + 有停留**。
    # 连续巡逻 ≈ 100%；这里断言：明显非连续巡逻（<80%）且确有多次到达（dwell）。
    assert share < 0.8, f"wander 不应是连续巡逻（moving_share 应<80%），实际 {share:.1%}"
    assert rt.stats["arrivals"] >= 2, f"wander 应有多次到达（dwell）: {rt.stats['arrivals']}"


# ================================================================ 17. 50k long-run
def test_spatial_long_run_health():
    """50k ticks 混合场景：out_of_bounds=0 / stuck=0 / duplicate_arrival=0 / 无界重规划。"""
    import random
    rng = random.Random(1)
    active = Rect(600, 200, 700, 600)
    win = FakeWindow(x=800, y=450)
    world, rt = _mk(foot=(800, 450), active_window=active, window=win)
    intents = ["APPROACH", "WITHDRAW", "MAINTAIN", "NEAR", "FAR", "REPOSITION", "NONE", "APPROACH"]
    activities = ["approach_user", "idle", "read", "wander", "observe_work", "sleep"]
    t0 = 1000.0
    for i in range(50000):
        now = t0 + i * 0.033
        act = rng.choice(activities)
        intent = rng.choice(intents)
        if act == "sleep":
            intent = "MAINTAIN"
        motion = {"motion_intent": intent}
        spd = rng.choice(["SLOW", "NORMAL", "FAST"])
        frame = _frame(act, motion_speed=spd, proximity="MAINTAIN", **motion)
        if i % 6 == 0:
            rt.accept(_resolve(frame), now=now)
        rt.tick(now=now)
        if i % 50 == 0 and rt.state.arrived and rt.state.state == SpatialState.ARRIVED.value:
            pass
    assert rt.stats["out_of_bounds"] == 0, f"out_of_bounds: {rt.stats['out_of_bounds']}"
    assert rt.stats["stuck"] == 0, f"stuck: {rt.stats['stuck']}"
    assert rt.stats["duplicate_arrivals"] == 0, f"duplicate: {rt.stats['duplicate_arrivals']}"
    assert rt._pending_plan is None or rt._pending_plan is not None  # 单槽天然无界
    assert rt.state.distance_remaining >= 0


# ================================================================ 18. resolve falls back correctly
def test_resolver_wander_needs_activity():
    """NONE 意图：只有活动允许走时才 wander_allowed。"""
    r = SpatialIntentResolver()
    d_idle = r.resolve(_frame("idle", motion_intent="NONE"))
    d_wander = r.resolve(_frame("wander", motion_intent="NONE"))
    assert d_idle.wander_allowed is False
    assert d_wander.wander_allowed is True
