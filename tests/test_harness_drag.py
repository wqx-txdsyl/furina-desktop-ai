"""Phase 13 Pre-Manual Blocker Repair R1 — B2 Harness Proxy Drag（DRAG-L1..L9）。

契约（评审基线 0402e7f）：
  - Harness 与生产 FurinaWindow 同一 drag semantic：press → SpatialRuntime.on_drag_start
    （drag_active=True, DRAGGED, 自主移动停）→ move（proxy 跟随鼠标，runtime 不争坐标）
    → release（on_drag_release(commit=True) → 新位置成为 foot truth + manual_position_grace，无 snap-back）。
  - DRAG-L9：真实 launch_harness wiring（不是 new 一个测试专用正确 proxy）。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random
import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from furina.runtime.world import DesktopWorld
from furina.runtime.harness.proxy import SpatialProxyWindow
from furina.runtime.spatial import (DesktopSpatialRuntime, SpatialIntentResolver,
                                    SpatialState)
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.frame import FrameBody


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _mk_drag(active_window=None):
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    if active_window is not None:
        world.update_active_window(active_window)
    proxy = SpatialProxyWindow(world=world)
    spatial = DesktopSpatialRuntime(world, window=proxy, rng=random.Random(1))
    spatial.set_initial_foot(900.0, 900.0)
    # 生产 wiring（与 RuntimeHarness 注入分支同一语义）
    proxy.on_drag_start = lambda: spatial.on_drag_start(time.monotonic())
    proxy.on_drag_move = lambda: spatial.on_drag_move(time.monotonic())
    proxy.on_drag_release = lambda: spatial.on_drag_release(time.monotonic(), commit=True)
    proxy.show()
    QApplication.processEvents()
    return world, proxy, spatial


def _press(proxy, qapp):
    QTest.mousePress(proxy, Qt.LeftButton, pos=QPoint(90, 37))
    QApplication.processEvents()


def _frame(activity="wander", *, motion_intent="MAINTAIN", proximity="MAINTAIN"):
    body = FrameBody(posture="standing", proximity=proximity, movement_tempo="normal",
                     hesitation=0.3, transition_style="SMOOTH",
                     micro_preferences=("BLINK", "BREATH"))
    return RuntimeFrameBuilder().build(activity_name=activity, body=body,
                                       motion_intent=motion_intent)


def _resolve(frame):
    return SpatialIntentResolver().resolve(frame)


# ================================================================ DRAG-L1
def test_drag_l1_press_enters_dragged_state(qapp):
    """L1：QTest mouse press → drag_active=True、state=DRAGGED、自主移动停。"""
    world, proxy, spatial = _mk_drag()
    spatial.accept(_resolve(_frame("wander")), now=0.0)   # 先有自主移动
    QTest.mousePress(proxy, Qt.LeftButton)
    QApplication.processEvents()
    assert proxy.dragging is True
    assert spatial.state.drag_active is True, "press 必须进入 drag_active"
    assert spatial.state.state == SpatialState.DRAGGED.value
    assert spatial.state.moving is False, "拖拽期间自主移动必须停"


# ================================================================ DRAG-L2
def test_drag_l2_press_move_changes_proxy_position(qapp):
    """L2：press + move → proxy 实际位置变化（跟随鼠标）。"""
    world, proxy, spatial = _mk_drag()
    before = (proxy.pos.x, proxy.pos.y)
    QTest.mousePress(proxy, Qt.LeftButton)
    QTest.mouseMove(proxy, QPoint(120, 60))     # 明显移动
    QApplication.processEvents()
    after = (proxy.pos.x, proxy.pos.y)
    assert after != before, f"proxy 必须跟随鼠标移动: {before} -> {after}"
    assert spatial.state.drag_active is True


# ================================================================ DRAG-L3
def test_drag_l3_tick_does_not_override_mouse_position(qapp):
    """L3：拖动时 spatial.tick 不覆盖鼠标坐标（drag_active → tick 早退）。"""
    world, proxy, spatial = _mk_drag()
    QTest.mousePress(proxy, Qt.LeftButton)
    QTest.mouseMove(proxy, QPoint(150, 80))
    QApplication.processEvents()
    held = (proxy.pos.x, proxy.pos.y)
    # 拖动期间喂自主计划 + tick —— 不得移动 proxy
    spatial.accept(_resolve(_frame("wander")), now=time.monotonic())
    spatial.tick(now=time.monotonic() + 1.0)
    QApplication.processEvents()
    assert (proxy.pos.x, proxy.pos.y) == held, "拖动期间 spatial.tick 不得覆盖鼠标坐标"
    assert spatial.state.drag_active is True


# ================================================================ DRAG-L4
def test_drag_l4_release_ends_drag_and_counts(qapp):
    """L4：release → drag_active=False、drag_releases +1。"""
    world, proxy, spatial = _mk_drag()
    QTest.mousePress(proxy, Qt.LeftButton)
    QTest.mouseMove(proxy, QPoint(140, 70))
    QApplication.processEvents()
    n0 = spatial.stats["drag_releases"]
    QTest.mouseRelease(proxy, Qt.LeftButton)
    QApplication.processEvents()
    assert spatial.state.drag_active is False
    assert spatial.stats["drag_releases"] == n0 + 1
    assert proxy.dragging is False


# ================================================================ DRAG-L5
def test_drag_l5_release_commits_new_foot_truth(qapp):
    """L5：release 后 spatial.state.position == 新的 foot truth（从 proxy 位置读取）。"""
    world, proxy, spatial = _mk_drag()
    QTest.mousePress(proxy, Qt.LeftButton)
    QTest.mouseMove(proxy, QPoint(160, 90))
    QApplication.processEvents()
    QTest.mouseRelease(proxy, Qt.LeftButton)
    QApplication.processEvents()
    foot = spatial.adapter.pos_to_foot(proxy.pos.x, proxy.pos.y)
    assert abs(spatial.state.position.x - foot.x) < 0.5, \
        f"release 后位置必须等于新 foot truth: {spatial.state.position} vs {foot}"
    assert abs(spatial.state.position.y - foot.y) < 0.5


# ================================================================ DRAG-L6
def test_drag_l6_release_then_tick_no_snap_back(qapp):
    """L6：release 后立即 tick 不 snap-back（grace 内保持新位置）。"""
    world, proxy, spatial = _mk_drag()
    QTest.mousePress(proxy, Qt.LeftButton)
    QTest.mouseMove(proxy, QPoint(170, 95))
    QApplication.processEvents()
    QTest.mouseRelease(proxy, Qt.LeftButton)
    QApplication.processEvents()
    committed = (spatial.state.position.x, spatial.state.position.y)
    assert spatial.state.state == SpatialState.ARRIVED.value
    # 立即 tick（grace 内）→ 不 snap 回旧自主目标
    spatial.tick(now=time.monotonic() + 1.0)
    QApplication.processEvents()
    assert (spatial.state.position.x, spatial.state.position.y) == committed, "不得 snap-back"


# ================================================================ DRAG-L7
def test_drag_l7_wander_does_not_steal_during_grace(qapp):
    """L7：manual_position_grace 内普通 wander 不抢控制。"""
    world, proxy, spatial = _mk_drag()
    QTest.mousePress(proxy, Qt.LeftButton)
    QTest.mouseMove(proxy, QPoint(130, 75))
    QApplication.processEvents()
    QTest.mouseRelease(proxy, Qt.LeftButton)
    QApplication.processEvents()
    committed = (spatial.state.position.x, spatial.state.position.y)
    # grace 内喂普通自主 wander（低优先）→ 被 cooldown/grace 丢弃
    spatial.accept(_resolve(_frame("wander")), now=time.monotonic() + 2.0)
    spatial.tick(now=time.monotonic() + 2.5)
    QApplication.processEvents()
    assert (spatial.state.position.x, spatial.state.position.y) == committed, \
        "grace 内 wander 不得抢控制"


# ================================================================ DRAG-L8
def test_drag_l8_life_intent_can_interrupt_grace(qapp):
    """L8：高优先生命空间事件（APPROACH）可按既有契约打断 grace（保持 SpatialConfig 语义）。"""
    from furina.runtime.world import Rect
    world, proxy, spatial = _mk_drag(active_window=Rect(600, 200, 700, 600))
    _press(proxy, qapp)
    QTest.mouseMove(proxy, QPoint(120, 70))
    QApplication.processEvents()
    QTest.mouseRelease(proxy, Qt.LeftButton)
    QApplication.processEvents()
    committed = (spatial.state.position.x, spatial.state.position.y)
    assert spatial.state.state == SpatialState.ARRIVED.value
    # grace 内高优先生命意图（APPROACH=SP_LIFE）不受普通 cooldown 限制 → 可发起
    now0 = time.monotonic() + 2.0
    spatial.accept(_resolve(_frame("approach_user", motion_intent="APPROACH",
                                   proximity="APPROACH")), now=now0)
    assert spatial.state.state != SpatialState.ARRIVED.value, \
        "APPROACH 必须开始（高优先打断 grace）"
    # 跨过 prepare/hesitation 延迟后必须真正移动（10 × 0.5s）
    for i in range(1, 11):
        spatial.tick(now=now0 + i * 0.5)
        QApplication.processEvents()
    moved = (spatial.state.position.x, spatial.state.position.y) != committed
    assert moved, "APPROACH 应移动（高优先打断 grace）"


# ================================================================ DRAG-L9
def test_drag_l9_launch_harness_proxy_wiring(qapp):
    """L9：**真实 launch_harness wiring** —— 不是 new 一个测试专用正确 proxy。

    防止"类本身写对了，但生产 wiring 漏了"：launch_harness 先创建无回调的 proxy 再注入
    RuntimeHarness，后者必须补齐 on_drag_start/move/release → 生产 SpatialRuntime 链。
    """
    from furina.config import AppConfig, LLMProfile
    from furina.app import launch_harness
    tmp = Path(tempfile.mkdtemp())
    cfg = AppConfig(root_dir=tmp, zhipu_api_key="", agnes_api_key="",
                    llm=LLMProfile(api_key=""))
    furina = launch_harness(cfg)
    try:
        proxy = furina._harness.proxy
        spatial = furina._harness.spatial
        # wiring 必须存在（注入分支补齐，而非自建分支才接线）
        assert proxy.on_drag_start is not None and proxy.on_drag_move is not None \
            and proxy.on_drag_release is not None, "launch_harness 注入的 proxy 必须接线"
        # 真实 mouse press → 生产 SpatialRuntime 进入 DRAGGED
        pre_drag_proxy = (proxy.pos.x, proxy.pos.y)
        _press(proxy, qapp)
        assert spatial.state.drag_active is True
        assert spatial.state.state == SpatialState.DRAGGED.value
        # 移到**世界安全区内**的落点（foot 在 bounds 内，避免边界 clamp 干扰 snap-back 断言）
        QTest.mouseMove(proxy, QPoint(90, -283))
        QApplication.processEvents()
        QTest.mouseRelease(proxy, Qt.LeftButton)
        QApplication.processEvents()
        assert spatial.state.drag_active is False
        assert spatial.stats["drag_releases"] == 1
        assert spatial.state.state in (SpatialState.ARRIVED.value, SpatialState.IDLE.value)
        # 不 snap-back：release + 立即 tick 后，proxy 不得回到拖前位置（旧自主目标）
        committed_proxy = (proxy.pos.x, proxy.pos.y)
        assert committed_proxy != pre_drag_proxy, "拖拽必须真实移动 proxy"
        spatial.tick(now=time.monotonic() + 1.0)
        QApplication.processEvents()
        assert (proxy.pos.x, proxy.pos.y) == committed_proxy, "release 后不得 snap-back 到旧目标"
    finally:
        try:
            furina._timer.stop()
        except Exception:
            pass
        for w in (furina._harness.proxy, furina._harness.panel):
            try:
                w.close()
            except Exception:
                pass
