"""Phase 12 自动验收（§133）—— 桌面空间生命层各维度 PASS/FAIL。

headless：注入时钟 + duck-typed FakeWindow（不跑 Qt，不挂真桌面）。
逐项输出 Approach / Withdraw / Maintain / Speed / Hesitation / Drag / Bounds /
Hysteresis / Quiet / Wander / FPS / 50k 的结果（PASS / FAIL）。

用法：
    python scripts/spatial_validation.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from furina.core.event_bus import EventBus, EventType
from furina.runtime.frame import FrameBody
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.world import DesktopWorld, Rect
from furina.runtime.spatial import (
    DesktopSpatialRuntime, SpatialIntentResolver, SpatialPoint, SpatialState,
    SpatialConfig, TargetType, SpatialIntent,
)


class _V:
    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)


class FakeWindow:
    def __init__(self, x=0.0, y=0.0, width=348.0, side=24.0, top=120.0, char_w=256.0, char_h=360.0):
        self._w = width; self._side = side; self._top = top
        self._char_w = char_w; self._char_h = char_h
        self.pos = _V(x, y)
        self.dragging = False
    def width(self):
        return self._w
    def set_position(self, x, y):
        self.pos = _V(x, y)


def _world(w=1920, h=1080, aw=None):
    world = DesktopWorld(w, h)
    world.taskbar_height = 48.0
    if aw is not None:
        world.update_active_window(aw)
    return world


def _frame(activity="idle", *, motion_intent=None, speed="NORMAL", proximity="MAINTAIN",
           tempo="normal", hesitation=0.3, transition_style="SMOOTH", posture="standing", speech=""):
    kw = {}
    if motion_intent is not None:
        kw["motion_intent"] = motion_intent
    body = FrameBody(posture=posture, proximity=proximity, movement_tempo=tempo,
                     hesitation=hesitation, transition_style=transition_style,
                     micro_preferences=("BLINK", "BREATH"))
    return RuntimeFrameBuilder().build(activity_name=activity, body=body,
                                       motion_speed=speed, speech={
                                           "should_speak": bool(speech), "text": speech,
                                           "validation_status": "valid" if speech else "silent"}, **kw)


def _resolve(frame):
    return SpatialIntentResolver().resolve(frame)


def _tick(rt, seconds, fps=30.0, start=0.0):
    for i in range(1, int(seconds * fps) + 1):
        rt.tick(now=start + i / fps)
    return rt.state.position


@dataclass
class _Case:
    name: str
    passed: bool
    detail: str


def main() -> int:
    cases: list[_Case] = []
    active = Rect(600, 200, 700, 600)

    # ---- Approach ----
    win = FakeWindow(x=300, y=780)
    rt = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt.set_initial_foot(300, 900)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH", proximity="APPROACH", speed="FAST"))
    rt.accept(d, now=0.0)
    pos = _tick(rt, 10.0)
    ok = rt.state.arrived and rt.state.target_type == TargetType.NEAR_USER_SAFE.value
    cases.append(_Case("Approach", ok, f"state={rt.state.state} target={rt.state.target_position}"))

    # ---- Maintain ----
    win = FakeWindow(x=820, y=450)
    rt = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt.set_initial_foot(820, 450)
    d = _resolve(_frame("idle", motion_intent="MAINTAIN", proximity="MAINTAIN"))
    rt.accept(d, now=0.0)
    before = rt.state.position.to_tuple()
    _tick(rt, 5.0)
    ok = rt.state.moving is False and rt.state.position.distance(SpatialPoint(*before)) < 1.0
    cases.append(_Case("Maintain", ok, "stays"))

    # ---- Withdraw ----
    win = FakeWindow(x=700, y=500)
    rt = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt.set_initial_foot(700, 500)
    up = SpatialPoint(active.cx, active.cy)
    d0 = rt.state.position.distance(up)
    d = _resolve(_frame("idle", motion_intent="WITHDRAW"))
    rt.accept(d, now=0.0)
    _tick(rt, 15.0)
    d1 = rt.state.position.distance(up)
    cases.append(_Case("Withdraw", d1 > d0 + 50, f"dist {d0:.0f}->{d1:.0f}"))

    # ---- Speed counterfactual ----
    times = {}
    for spd in ("SLOW", "NORMAL", "FAST"):
        win = FakeWindow(x=200, y=780)
        rt = DesktopSpatialRuntime(_world(aw=active), window=win)
        rt.set_initial_foot(200, 900)
        d = _resolve(_frame("approach_user", motion_intent="APPROACH", speed=spd))
        rt.accept(d, now=0.0)
        t = 0.0
        for i in range(1, int(60 * 30)):
            t = i / 30
            rt.tick(now=t)
            if rt.state.arrived:
                break
        times[spd] = t
    ok = times["SLOW"] > times["NORMAL"] > times["FAST"]
    cases.append(_Case("Speed", ok, f"slow={times['SLOW']:.1f}s normal={times['NORMAL']:.1f}s fast={times['FAST']:.1f}s"))

    # ---- Hesitation ----
    delays = {}
    for hes in (0.2, 0.9):
        win = FakeWindow(x=200, y=780)
        rt = DesktopSpatialRuntime(_world(aw=active), window=win)
        rt.set_initial_foot(200, 900)
        d = _resolve(_frame("approach_user", motion_intent="APPROACH", hesitation=hes))
        plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
        delays[hes] = plan.pre_move_delay
    ok = delays[0.9] > delays[0.2]
    cases.append(_Case("Hesitation", ok, f"h=.2→{delays[0.2]:.2f}s h=.9→{delays[0.9]:.2f}s"))

    # ---- Drag ----
    win = FakeWindow(x=200, y=780)
    rt = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt.set_initial_foot(200, 900)
    d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
    rt.accept(d, now=0.0)
    _tick(rt, 1.0)
    rt.on_drag_start(now=1.0)
    was_dragged = rt.state.state == SpatialState.DRAGGED.value and rt.state.moving is False
    win.set_position(1300, 300)
    rt.on_drag_release(now=2.0, commit=True)
    no_snap = rt._current_plan is None and rt.state.state == SpatialState.ARRIVED.value
    grace = rt._grace_until > 2.0
    cases.append(_Case("Drag", was_dragged and no_snap and grace,
                       f"dragged={was_dragged} no_snap={no_snap} grace={grace}"))

    # ---- Bounds ----
    win = FakeWindow(x=200, y=780)
    rt = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt.set_initial_foot(200, 900)
    for intent in ("APPROACH", "WITHDRAW", "REPOSITION"):
        d = _resolve(_frame("idle", motion_intent=intent))
        plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
        if plan:
            rt.accept(d, now=0.0)
            _tick(rt, 10.0)
    ok = rt.stats["out_of_bounds"] < 20
    cases.append(_Case("Bounds", ok, f"out_of_bounds={rt.stats['out_of_bounds']}"))

    # ---- Hysteresis (NEAR / FAR / target) ----
    win = FakeWindow(x=820, y=450)
    rt_ne = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt_ne.set_initial_foot(820, 450)
    d = _resolve(_frame("observe_work", proximity="NEAR"))
    near_stay = rt_ne.planner.plan(d, rt_ne.state.position, rt_ne.adapter.char_w, rt_ne.adapter.char_h) is None
    win2 = FakeWindow(x=200, y=780)
    rt_fa = DesktopSpatialRuntime(_world(aw=active), window=win2)
    rt_fa.set_initial_foot(200, 900)
    df = _resolve(_frame("idle", proximity="FAR"))
    far_stay = rt_fa.planner.plan(df, rt_fa.state.position, rt_fa.adapter.char_w, rt_fa.adapter.char_h) is None
    cases.append(_Case("Hysteresis", near_stay and far_stay, f"near_stay={near_stay} far_stay={far_stay}"))

    # ---- Quiet coexistence ----
    win = FakeWindow(x=800, y=450)
    rt = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt.set_initial_foot(800, 450)
    d = _resolve(_frame("read", motion_intent="MAINTAIN", proximity="MAINTAIN"))
    p0 = rt.state.position.to_tuple()
    for i in range(int(30 * 60 * 5)):
        if i % 20 == 0:
            rt.accept(d, now=i * 0.2)
        rt.tick(now=i * 0.2)
    drift = rt.state.position.distance(SpatialPoint(*p0))
    cases.append(_Case("Quiet", drift < 5.0, f"30min drift={drift:.1f}px plans={rt.stats['plans']}"))

    # ---- Wander dwell ----
    win = FakeWindow(x=800, y=450)
    rt = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt.set_initial_foot(800, 450)
    d = _resolve(_frame("wander", motion_intent="NONE"))
    moving = 0
    total = int(30 * 60 * 2)
    for i in range(total):
        if i % 40 == 0:
            rt.accept(d, now=i * 0.5)
        rt.tick(now=i * 0.5)
        if rt.state.moving:
            moving += 1
    share = moving / total
    cases.append(_Case("Wander", share < 0.4 and rt.stats["arrivals"] >= 1,
                       f"moving_share={share:.1%} arrivals={rt.stats['arrivals']}"))

    # ---- 50k long-run ----
    import random
    rng = random.Random(1)
    win = FakeWindow(x=800, y=450)
    rt = DesktopSpatialRuntime(_world(aw=active), window=win)
    rt.set_initial_foot(800, 450)
    for i in range(50000):
        now = 1000.0 + i * 0.033
        act = rng.choice(["approach_user", "idle", "read", "wander", "observe_work", "sleep"])
        intent = rng.choice(["APPROACH", "WITHDRAW", "MAINTAIN", "NEAR", "FAR", "REPOSITION", "NONE", "APPROACH"])
        if act == "sleep":
            intent = "MAINTAIN"
        f = _frame(act, motion_intent=intent, speed=rng.choice(["SLOW", "NORMAL", "FAST"]))
        if i % 6 == 0:
            rt.accept(_resolve(f), now=now)
        rt.tick(now=now)
    ok = (rt.stats["out_of_bounds"] == 0 and rt.stats["stuck"] == 0
          and rt.stats["duplicate_arrivals"] == 0)
    cases.append(_Case("50k", ok,
                       f"oob={rt.stats['out_of_bounds']} stuck={rt.stats['stuck']} "
                       f"dup={rt.stats['duplicate_arrivals']} plans={rt.stats['plans']}"))

    # ---- FPS independence ----
    arr = {}
    for fps in (30, 60, 120):
        win = FakeWindow(x=200, y=780)
        rt = DesktopSpatialRuntime(_world(aw=active), window=win)
        rt.set_initial_foot(200, 900)
        d = _resolve(_frame("approach_user", motion_intent="APPROACH"))
        rt.accept(d, now=0.0)
        t = 0.0
        for i in range(1, int(20 * fps)):
            t = i / fps
            rt.tick(now=t)
            if rt.state.arrived:
                break
        arr[fps] = (t, rt.state.position.to_tuple())
    ok = abs(arr[30][0] - arr[60][0]) < 0.5
    cases.append(_Case("FPS", ok, f"t30={arr[30][0]:.2f}s t60={arr[60][0]:.2f}s t120={arr[120][0]:.2f}s"))

    # ---- print ----
    print("=== Phase 12 Spatial Validation ===")
    all_ok = True
    for c in cases:
        all_ok = all_ok and c.passed
        print(f"  {c.name:<12} {'PASS' if c.passed else 'FAIL'}  | {c.detail}")
    print("\n  OVERALL:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
