"""Phase 12 Step 0 —— GUI 集成 pytest 测试（offscreen，不创建真实桌面粉）。

验证：QApplication 创建、FurinaWindow 创建、Frame 接收、consumer 调用、
AnimationRuntime tick 推进、present 调用、paint 发生、Qt 线程正确、无异常/崩溃。
**只验证程序化技术链路**；视觉质量属人工验收（见 docs/testing/）。
"""
from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from furina.config import load_config
from furina.assets.asset_manifest import AssetManifest
from furina.runtime import DesktopWorld, AssetManager, FurinaWindow
from furina.runtime.frame import FrameBody
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.world import Rect
from furina.core import EventBus, EventType
from furina.runtime.frontend import FrontendFrameConsumer, AnimationRuntime
from furina.runtime.micro import MicroScheduler
from furina.runtime.spatial import DesktopSpatialRuntime, SpatialIntentResolver
from furina.app import _render_tick


def _frame(activity, expression="neutral", gaze="NONE", posture="standing", motion_intent="MAINTAIN"):
    return RuntimeFrameBuilder().build(
        activity_name=activity,
        body=FrameBody(posture=posture, expression=expression, gaze=gaze,
                       micro_preferences=("BLINK", "BREATH")),
        motion_intent=motion_intent)


class _Boot:
    """组装一个可运行的 GUI 前端链。"""
    def __init__(self):
        self.cfg = load_config()
        self.app = QApplication.instance() or QApplication([])
        self.app.setQuitOnLastWindowClosed(True)
        self.bus = EventBus()
        self.world = DesktopWorld(1920, 1080)
        self.world.update_active_window(Rect(600, 200, 700, 600))
        self.assets = AssetManager(AssetManifest.load(self.cfg.model_manifest_path), self.cfg.assets_dir)
        from furina.interaction import InteractionEngine
        self.win = FurinaWindow(self.world, self.assets, InteractionEngine(self.bus))
        self.assets.set_reference_size(256, 360)
        self.win.apply_reference_size()
        self.win.show()

        self.consumer = FrontendFrameConsumer(self.bus)
        self.frame_runtime = AnimationRuntime(self.win.anim, self.assets, fps=30.0, bus=self.bus)
        self.micro = MicroScheduler(fps=30.0)
        self.spatial = DesktopSpatialRuntime(self.world, window=self.win)
        self.spatial.sync_from_window()
        self.resolver = SpatialIntentResolver()


@pytest.fixture(scope="module")
def boot():
    b = _Boot()
    yield b
    try:
        b.app.quit()
    except Exception:
        pass


@pytest.fixture(scope="module")
def drive(boot):
    """运行一次完整 GUI 驱动（Frame + render 循环 + paint），供各断言复用。"""
    return _drive(boot.app, boot, seconds=1.5, scene_ms=500)


def _drive(app, boot, seconds=1.5, scene_ms=600):
    """驱动 render 循环 + 场景切换，运行 seconds 秒后退出。"""
    m = {"paint": 0, "present": 0, "exceptions": 0}
    main = threading.get_ident()
    threads = {"present": None, "paint": None}

    orig_present = boot.win.present

    def wp(**kw):
        threads["present"] = threading.get_ident()
        m["present"] += 1
        return orig_present(**kw)

    boot.win.present = wp

    orig_paint = boot.win.paintEvent

    def wpe(ev):
        threads["paint"] = threading.get_ident()
        m["paint"] += 1
        return orig_paint(ev)

    boot.win.paintEvent = wpe

    scene = [0]
    scenes = [("idle", _frame("idle")), ("read", _frame("read", posture="seated")),
              ("sleep", _frame("sleep", posture="sleeping"))]

    def pub():
        _, f = scenes[scene[0] % len(scenes)]
        boot.bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=f, source="test")
        scene[0] += 1

    pt = QTimer(); pt.timeout.connect(pub); pt.start(int(scene_ms))

    def render():
        try:
            _render_tick(boot.win, boot.frame_runtime, boot.micro, boot.consumer,
                         boot.spatial, boot.resolver)
            boot.win.update()
        except Exception:
            m["exceptions"] += 1

    rt = QTimer(); rt.timeout.connect(render); rt.start(16)

    def finish():
        app.quit()

    QTimer.singleShot(int(seconds * 1000), finish)
    app.exec()
    return m, threads, main


def test_gui_qapplication_integration(boot, drive):
    """QApplication + Window + Frame + consumer + present + paint 全链跑通，无异常。"""
    m, threads, main = drive
    assert boot.consumer.frame_count > 0, "Frame 应被 consumer 接收"
    assert m["present"] > 0, "present() 应被调用"
    assert m["paint"] > 0, "paintEvent 应发生"
    assert m["exceptions"] == 0, f"不应有异常: {m['exceptions']}"


def test_gui_present_on_qt_thread(boot, drive):
    """present / paint 都在 Qt GUI 线程（与 QApplication 同线程）。"""
    m, threads, main = drive
    assert threads["present"] == main, "present 应在 GUI 线程"
    if threads["paint"] is not None:
        assert threads["paint"] == main, "paintEvent 应在 GUI 线程"


def test_gui_timer_advances_runtime(boot, drive):
    """Qt 定时器推进 AnimationRuntime：生命周期阶段合法且有实际推进。"""
    m, threads, main = drive
    st = boot.frame_runtime.stats
    assert boot.frame_runtime.phase in ("LOOP", "ENTRY", "TRANSITION", "EXIT", "PRE_HOLD", "REACT")
    # 非空验收：生命周期确实发生推进（transition/entry/loop/exit ≥1）
    assert st["transitions"] + st["entries"] + st["loops"] + st["exits"] >= 1, f"生命周期应推进: {st}"
    assert boot.frame_runtime._now > 0, "时钟应被定时器推进"
