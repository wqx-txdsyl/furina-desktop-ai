"""Phase 12 Step 0 —— GUI Integration AUTO Gate（程序化验证，非视觉）。

验证真实链（offscreen，无需真实桌面）：
    QApplication →
    EventBus(CHARACTER_FRAME_UPDATED) →
    FrontendFrameConsumer →
    AnimationRuntime →
    FurinaWindow.present() →
    Qt timer →
    paintEvent

**只验证技术链**（§6/§7），**不声称/不评估视觉审美**（"自然/好看/无闪烁" 等由人工检查）。

用法：
    python scripts/gui_integration_smoke.py [--seconds 30] [--scene-ms 2500]
"""
from __future__ import annotations

import argparse
import threading
import time
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from furina.config import load_config
from furina.assets.asset_manifest import AssetManifest
from furina.runtime import DesktopWorld, AssetManager, FurinaWindow
from furina.runtime.frame import FrameBody
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.world import Rect
from furina.core import EventBus, EventType

from furina.runtime.frontend import FrontendFrameConsumer, AnimationRuntime, AnimationPhase
from furina.runtime.micro import MicroScheduler
from furina.runtime.spatial import DesktopSpatialRuntime, SpatialIntentResolver
from furina.app import _render_tick


def _frame(activity, *, motion_intent="NONE", speed="NORMAL", proximity="MAINTAIN",
           posture="standing", expression="neutral", gaze="NONE", speech="", tempo="normal"):
    return RuntimeFrameBuilder().build(
        activity_name=activity,
        body=FrameBody(posture=posture, expression=expression, gaze=gaze,
                       proximity=proximity, movement_tempo=tempo,
                       micro_preferences=("BLINK", "BREATH")),
        motion_intent=motion_intent, motion_speed=speed,
        speech={"should_speak": bool(speech), "text": speech,
                "validation_status": "valid" if speech else "silent"})


# ---------------------------------------------------------------- scenes
SCENES = [
    ("idle", _frame("idle", expression="neutral", gaze="NONE", posture="standing")),
    ("read", _frame("read", posture="seated", expression="focus", gaze="DOWN",
                    motion_intent="MAINTAIN", proximity="MAINTAIN")),
    ("embarrassed", _frame("seek_attention", proximity="APPROACH", expression="embarrassed",
                           gaze="SIDE", posture="standing", motion_intent="APPROACH")),
    ("proud", _frame("celebrate", posture="standing", expression="proud", gaze="USER")),
    ("sleep", _frame("sleep", posture="sleeping", expression="sleepy", gaze="NONE",
                     motion_intent="MAINTAIN", proximity="MAINTAIN")),
    ("wake", _frame("idle", posture="standing", expression="neutral", gaze="NONE",
                    motion_intent="APPROACH", proximity="APPROACH")),
    ("speech", _frame("talk", posture="standing", expression="happy", gaze="USER",
                      speech="今天也要加油哦！", motion_intent="MAINTAIN", proximity="NEAR")),
    ("silence", _frame("read", posture="seated", expression="neutral", gaze="DOWN",
                       motion_intent="MAINTAIN", proximity="MAINTAIN", speech="")),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--scene-ms", type=int, default=2500)
    args = ap.parse_args()

    cfg = load_config()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(True)

    bus = EventBus()
    world = DesktopWorld(1920, 1080)
    world.update_active_window(Rect(600, 200, 700, 600))   # 模拟用户窗口
    assets = AssetManager(AssetManifest.load(cfg.model_manifest_path), cfg.assets_dir)
    from furina.interaction import InteractionEngine
    win = FurinaWindow(world, assets, InteractionEngine(bus))
    assets.set_reference_size(256, 360)
    win.apply_reference_size()
    win.set_position(world.screen.w * 0.5, world.screen.h - 360 - 40)
    win.show()

    consumer = FrontendFrameConsumer(bus)
    frame_runtime = AnimationRuntime(win.anim, assets, fps=30.0, bus=bus)
    micro_sched = MicroScheduler(fps=30.0)
    spatial = DesktopSpatialRuntime(world, window=win)
    spatial.sync_from_window()
    resolver = SpatialIntentResolver()

    # ---- metrics / thread ids ----
    m = {"frames": 0, "consumer_calls": 0, "anim_ticks": 0, "present_calls": 0,
         "paint_calls": 0, "transitions": 0, "anim_completed": 0,
         "transition_active": 0, "loop_active": 0, "entry_active": 0,
         "exceptions": 0, "crash": 0}
    main_id = threading.get_ident()
    thread_ids = {"qapp": main_id}
    _counters = {"present": 0, "paint": 0}
    _threads = {"consumer": None, "present": None, "paint": None}

    # 记录消费者线程：bus 随事件同步调用（均在主线程），用 wildcard 记录一次
    def _track_thread(ev):
        if _threads["consumer"] is None:
            _threads["consumer"] = threading.get_ident()
    bus.on_any(_track_thread)

    _counters["present_init"] = 0
    _counters["paint_init"] = 0

    orig_present = win.present

    def wrapped_present(**kw):
        _threads["present"] = threading.get_ident()
        _counters["present"] += 1
        return orig_present(**kw)

    win.present = wrapped_present

    orig_paint = win.paintEvent

    def wrapped_paint(ev):
        _threads["paint"] = threading.get_ident()
        _counters["paint"] += 1
        return orig_paint(ev)

    win.paintEvent = wrapped_paint

    bus.on(EventType.ANIMATION_COMPLETED, lambda ev: m.__setitem__("anim_completed", m["anim_completed"] + 1))
    bus.on(EventType.TRANSITION_COMPLETED, lambda ev: m.__setitem__("transitions", m["transitions"] + 1))

    # ---- scene publisher ----
    scene_idx = [0]

    class _Publisher:
        def tick(self):
            act, frame = SCENES[scene_idx[0] % len(SCENES)]
            bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=frame, source="smoke")
            m["frames"] += 1
            scene_idx[0] = (scene_idx[0] + 1) % len(SCENES)

    pub = _Publisher()
    scene_timer = QTimer()
    scene_timer.timeout.connect(pub.tick)
    scene_timer.start(args.scene_ms)

    def render():
        try:
            _render_tick(win, frame_runtime, micro_sched, consumer, spatial, resolver)
            m["anim_ticks"] += 1
            ph = frame_runtime.phase
            if ph == AnimationPhase.TRANSITION:
                m["transition_active"] += 1
            elif ph == AnimationPhase.LOOP:
                m["loop_active"] += 1
            elif ph == AnimationPhase.ENTRY:
                m["entry_active"] += 1
            win.update()
        except Exception:
            m["exceptions"] += 1
            traceback.print_exc()
            m["crash"] += 1

    timer = QTimer()
    timer.timeout.connect(render)
    timer.start(16)

    def finish():
        m.update({
            "frames": m["frames"],
            "consumer_calls": consumer.frame_count,
            "present_calls": _counters["present"],
            "paint_calls": _counters["paint"],
        })
        thread_ids.update({"consumer": _threads["consumer"], "present": _threads["present"],
                           "paint": _threads["paint"]})
        app.quit()

    QTimer.singleShot(int(args.seconds * 1000), finish)
    app.exec()

    # ---- report（只报技术链，§7 禁止视觉断言）----
    same_thread = all(v == main_id for v in
                      (_threads["consumer"], _threads["present"], _threads["paint"]))
    print("=== GUI Integration AUTO Gate (programmatic) ===")
    for k in ("frames", "consumer_calls", "anim_ticks", "present_calls", "paint_calls",
              "entry_active", "transition_active", "loop_active", "transitions", "anim_completed",
              "exceptions", "crash"):
        print(f"  {k:<16} {m[k]}")
    print("  thread ids (qapp/consumer/present/paint):",
          main_id, _threads["consumer"], _threads["present"], _threads["paint"])
    print("  all Qt mutation on GUI thread:", "PASS" if same_thread else "FAIL (thread violation)")
    print("  exceptions:", m["exceptions"], "| crash:", m["crash"])
    result = (m["exceptions"] == 0 and m["crash"] == 0
              and m["present_calls"] > 0 and m["paint_calls"] > 0
              and m["anim_ticks"] > 0 and same_thread)
    print("  RESULT:", "PASS" if result else "FAIL")
    print("\nNOTE: This gate proves the programmatic pipeline runs. It does NOT judge "
          "visual quality (see scripts/manual_gui_phase12.py).")


if __name__ == "__main__":
    main()
