"""Phase 12 —— Spatial Ownership Migration 验证（§132/§14/§15）。

确认：Scheduler 不再拥有/操作像素空间状态与窗口移动；SpatialRuntime 是自主移动唯一 owner。
"""
from __future__ import annotations

import warnings

from furina.core.event_bus import EventBus
from furina.runtime.scheduler import Scheduler
from furina.runtime.world import DesktopWorld


def _mk_scheduler():
    bus = EventBus()
    world = DesktopWorld(1920, 1080)
    sched = Scheduler(bus, None, None, None, None, world, None)
    return sched, world


def test_scheduler_has_no_window_movement():
    """Scheduler 不再调用 window.set_position（像素空间移动已迁出）。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert "window.set_position(" not in src, "Scheduler 不应调用 set_position"
    assert ".set_position(" not in src.replace("set_pose_semantics", ""), "Scheduler 不应移动窗口"


def test_scheduler_has_no_spatial_pixel_state():
    """Scheduler 不再保存 _move_target / _walk_visible 等像素状态（作为实例属性）。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert "self._move_target" not in src, "Scheduler 不应再保存 _move_target"
    assert "self._walk_visible" not in src, "Scheduler 不应再保存 _walk_visible"


def test_scheduler_step_does_not_move_window():
    """调用 sched.step() 不应改变窗口位置（无自主移动副作用）。"""
    sched, world = _mk_scheduler()
    win = _FakeWin(world)
    sched.window = win
    x0, y0 = win.pos.x, win.pos.y
    sched.step(dt=1 / 60)
    assert (win.pos.x, win.pos.y) == (x0, y0), "step() 不应移动窗口"


def test_scheduler_legacy_move_is_deprecated_noop():
    """_move_step / _maybe_walk_to_window 为 deprecated no-op（DeprecationWarning + 不产生副作用）。"""
    sched, world = _mk_scheduler()
    win = _FakeWin(world)
    sched.window = win
    x0, y0 = win.pos.x, win.pos.y
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        sched._move_step()
        sched._maybe_walk_to_window()
    assert any(issubclass(x.category, DeprecationWarning) for x in w), "应产生 DeprecationWarning"
    assert (win.pos.x, win.pos.y) == (x0, y0), "no-op 不应移动窗口"
    assert sched.__dict__.get("_move_target") is None, "不应残留 _move_target"

    # 行为：即使误设 false，也不移动
    sched._move_target = (9999, 9999)   # 注入旧属性（不应再被消费）
    sched.step(dt=1 / 60)
    assert (win.pos.x, win.pos.y) == (x0, y0), "旧 _move_target 不应再被消费"


def test_scheduler_no_spatial_geometry_mutation():
    """Scheduler 不再直接把 life.macro 改成 RESTING（到达≠决定休息）。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    # 旧逻辑是 `_maybe_walk_to_window` 里 `life.macro = RESTING`；该段已删除。
    assert "life.macro = st.MacroState.RESTING" not in src or "_maybe_walk_to_window" not in src


class _FakeWin:
    def __init__(self, world):
        self.pos = type("P", (), {"x": 100.0, "y": 100.0})()
        self.dragging = False

    def set_position(self, x, y):
        self.pos = type("P", (), {"x": float(x), "y": float(y)})()
