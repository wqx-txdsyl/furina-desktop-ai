"""Phase 12V —— 人工视觉验收演示（§20）。

每个 scene 进入时打印：
    EXPECTED: activity / visual_pose / asset_action
    ACTUAL:   frame -> mapped -> asset_id -> phase

只控制 FurinaWindow；用户窗口目标用**模拟几何**（不操作其它软件）。顺序控制 ~2-4 分钟。
**本脚本不评估视觉质量**；请按 docs/FURINA_PHASE12V_REPORT.md 的 checklist 人工确认。

用法：python scripts/manual_gui_phase12.py
"""
from __future__ import annotations

import sys
import time

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


def _frame(activity, *, posture, expression, gaze, motion_intent="NONE", proximity="MAINTAIN",
           tempo="normal"):
    return RuntimeFrameBuilder().build(
        activity_name=activity,
        body=FrameBody(posture=posture, expression=expression, gaze=gaze,
                       proximity=proximity, movement_tempo=tempo,
                       micro_preferences=("BLINK", "BREATH")),
        motion_intent=motion_intent)


# (name, frame, aw_rect, duration_s)
SCENES = [
    ("1 idle+breath", _frame("idle", posture="relaxed", expression="neutral", gaze="NONE"),
     Rect(600, 200, 700, 600), 4),
    ("2 standing loop", _frame("idle", posture="relaxed", expression="neutral", gaze="AROUND"),
     Rect(600, 200, 700, 600), 4),
    ("3 read", _frame("read", posture="seated", expression="focus", gaze="DOWN", motion_intent="MAINTAIN"),
     Rect(600, 200, 700, 600), 5),
    ("4 proud", _frame("celebrate", posture="upright", expression="proud", gaze="USER"),
     Rect(600, 200, 700, 600), 4),
    ("5 embarrassed+side", _frame("seek_attention", posture="upright", expression="embarrassed",
                                  gaze="SIDE", proximity="APPROACH", motion_intent="APPROACH"),
     Rect(600, 200, 700, 600), 4),
    ("6 eat", _frame("eat", posture="upright", expression="happy", gaze="DOWN"),
     Rect(600, 200, 700, 600), 3),
    ("7 play", _frame("play", posture="upright", expression="playful", gaze="DOWN"),
     Rect(600, 200, 700, 600), 3),
    ("8 think", _frame("think", posture="relaxed", expression="thoughtful", gaze="NONE"),
     Rect(600, 200, 700, 600), 3),
    ("9 sleep", _frame("sleep", posture="sleeping", expression="sleepy", gaze="NONE", motion_intent="MAINTAIN"),
     Rect(600, 200, 700, 600), 4),
    ("10 wake", _frame("idle", posture="upright", expression="neutral", gaze="USER",
                       proximity="APPROACH", motion_intent="APPROACH"),
     Rect(600, 200, 700, 600), 3),
    ("11 walk LEFT", _frame("wander", posture="upright", expression="neutral", gaze="left",
                            proximity="WITHDRAW", motion_intent="WITHDRAW"), Rect(1500, 200, 400, 400), 5),
    ("12 walk RIGHT", _frame("approach_user", posture="upright", expression="happy", gaze="user",
                             proximity="APPROACH", motion_intent="APPROACH"), Rect(300, 200, 400, 400), 5),
]


def main() -> int:
    cfg = load_config()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(True)

    bus = EventBus()
    world = DesktopWorld(1920, 1080)
    assets = AssetManager(AssetManifest.load(cfg.model_manifest_path), cfg.assets_dir)
    from furina.interaction import InteractionEngine
    win = FurinaWindow(world, assets, InteractionEngine(bus))
    assets.set_reference_size(256, 360)
    win.apply_reference_size()
    win.set_position(world.screen.w * 0.5, world.screen.h - 360 - 40)
    win.show_debug = True   # §19 显示 mapped/asset 调试叠层

    consumer = FrontendFrameConsumer(bus)
    frame_runtime = AnimationRuntime(win.anim, assets, fps=30.0, bus=bus)
    micro_sched = MicroScheduler(fps=30.0)
    spatial = DesktopSpatialRuntime(world, window=win)
    spatial.sync_from_window()
    resolver = SpatialIntentResolver()
    win.on_drag_start = lambda: spatial.on_drag_start(time.monotonic())
    win.on_drag_release = lambda: spatial.on_drag_release(time.monotonic(), commit=True)
    win.on_drag_pose = lambda active: frame_runtime.set_drag_override(active)

    state = {"scene": 0, "entered": False, "t": 0.0}

    def print_expect_actual(idx):
        if idx >= len(SCENES):
            return
        name, frame, aw, dur = SCENES[idx]
        vs = consumer.visual
        if aw is not None:
            world.update_active_window(aw)
        bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=frame, source="manual")
        # 等一个渲染 tick 后读 mapped/asset
        _render_tick(win, frame_runtime, micro_sched, consumer, spatial, resolver)
        mapped = frame_runtime.current_plan or {}
        entry = assets.entry_for_state(vs.target_pose, vs.expression, vs.gaze, vs.asset_action)
        asset_id = entry.asset_id if entry else "-"
        print(f"\n--- SCENE {name} ({dur}s) ---")
        print(f"  EXPECTED: activity={name.split()[1] if ' ' in name else name} "
              f"visual_pose={vs.target_pose} asset_action={vs.asset_action}")
        print(f"  ACTUAL: frame.activity={vs.activity} mapped={vs.target_pose}/{vs.expression}/{vs.gaze}/{vs.asset_action} "
              f"asset_id={asset_id} phase={frame_runtime.phase}")
        state["entered"] = True

    def render():
        try:
            if state["entered"]:
                _render_tick(win, frame_runtime, micro_sched, consumer, spatial, resolver)
                win.update()
        except Exception:
            pass

    def scene_controller():
        state["t"] += 1.0
        n = len(SCENES)
        if state["scene"] >= n:
            if not state.get("drag_prompted"):
                state["drag_prompted"] = True
                print("\n--- SCENE 13 drag ---\n  请直接拖拽芙宁娜。预期：被拎起姿态(或 DEGRADED_DRAG_VISUAL)，自主移动不抢鼠标。")
            return
        if not state["entered"]:
            return
        _, _, _, dur = SCENES[state["scene"]]
        if state["t"] >= dur:
            state["t"] = 0.0
            state["scene"] += 1
            state["entered"] = False
            if state["scene"] < n:
                print_expect_actual(state["scene"])

    print_expect_actual(0)
    rt = QTimer(); rt.timeout.connect(render); rt.start(16)
    sc = QTimer(); sc.timeout.connect(scene_controller); sc.start(1000)

    def quit():
        app.quit()
    win.on_command = quit
    print("\n运行中……（右键菜单可用；看完关闭窗口结束）\n")
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
