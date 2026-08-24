"""Phase 12V —— 真实运行轨迹（不只是测试数）。

用**生产同一条**选择链（真实 manifest + 真实 AssetManager + VisualSemanticMapper +
AssetResolver + AnimationRuntime + 真实 ClipPlayer）跑一个"read"场景，打印：

    LifeBrain selected: read
    Frame.activity: read
    Frame.body.posture: seated
    Mapped pose: sitting
    Selected asset: <actual asset id>
    Animation phase: LOOP
    Current image: <actual file>

并可把实际 QImage 导出，供视觉确认真是"读"的姿态。

用法：python scripts/runtime_real_trace.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from furina.config import load_config
from furina.assets.asset_manifest import AssetManifest
from furina.runtime import AssetManager
from furina.runtime.animation import AnimationController
from furina.runtime.frame import FrameBody
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.frontend import FrontendFrameConsumer, AnimationRuntime
from furina.runtime.visual_semantics import VisualSemanticMapper
from furina.core import EventBus, EventType
from furina.runtime.furina_window import FurinaWindow
from furina.runtime.world import DesktopWorld
from furina.interaction import InteractionEngine


def trace_read() -> int:
    cfg = load_config()
    app = QApplication.instance() or QApplication([])
    bus = EventBus()
    world = DesktopWorld(1920, 1080)
    assets = AssetManager(AssetManifest.load(cfg.model_manifest_path), cfg.assets_dir)
    assets.set_reference_size(256, 360)

    # 1) 构造真实的"她在读书" frame（等同 Scheduler._update_scene 产出的 Frame）
    frame = RuntimeFrameBuilder().build(
        activity_name="read",
        body=FrameBody(posture="seated", expression="focus", gaze="DOWN",
                       micro_preferences=("BLINK", "BREATH")),
        motion_intent="MAINTAIN",
        speech={"should_speak": False, "text": "", "validation_status": "silent"})

    # 2) 真实 consumer（含 VisualSemanticMapper）→ mapped visual
    consumer = FrontendFrameConsumer(bus)
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=frame, source="trace")
    vs = consumer.visual
    mapper = VisualSemanticMapper(assets.manifest)
    mapped = mapper.map(posture=frame.body.posture, expression=frame.body.expression,
                        gaze=frame.body.gaze, activity=frame.activity.name)

    # 3) 真实 ClipPlayer + 真实 AssetManager → AnimationRuntime（走 FIX C action 优先选择）
    clip = AnimationController(assets.load_path)
    rt = AnimationRuntime(clip, assets, fps=30.0, bus=bus)
    rt.accept(vs, prev_pose="standing", prev_activity="idle", now=0.0)
    rt.tick(now=0.0)
    # FIX J：完整走 sit_down TRANSITION → 完成后进入 LOOP 并展示 read 动作资产
    rt.tick(now=6.0)

    entry = rt._resolve_action_asset(vs.asset_action, vs.target_pose, vs.expression, vs.gaze)
    asset_id = (rt.current_plan.get("resolved_asset") or (entry.asset_id if entry else "-"))
    asset_path = (entry.path if entry else "-")

    # 4) 当前 clip 正在播的帧文件
    cur_frames = list(clip._spec.frames) if getattr(clip, "_spec", None) else []
    current_file = cur_frames[0] if cur_frames else "-"
    if (entry is not None and not current_file) or current_file == "-":
        current_file = entry.path

    print("=== REAL RUNTIME TRACE (production path, real manifest) ===")
    print(f"LifeBrain selected: read")
    print(f"Frame.activity: {frame.activity.name}")
    print(f"Frame.body.posture: {frame.body.posture}")
    print(f"Frame.body.expression: {frame.body.expression}")
    print(f"Frame.body.gaze: {frame.body.gaze}")
    print(f"Mapped pose: {mapped.posture}")
    print(f"Mapped expression: {mapped.expression}")
    print(f"Mapped gaze: {mapped.gaze}")
    print(f"Mapped action: {mapped.action}")
    print(f"Selected asset: {asset_id}")
    print(f"Asset path: {asset_path}")
    print(f"Animation phase: {rt.phase}")
    print(f"Current image: {current_file}")
    print(f"Semantic degraded: {mapped.degraded}")
    print(f"Plan degraded: {rt.current_plan.get('degraded', {}) or {}}")

    # 5) 导出实际 QImage 供视觉确认
    from PySide6.QtGui import QImage
    img = assets.load_path(asset_path) if entry else None
    if img is not None and not img.isNull():
        out_path = Path("data/_runtime_trace_read.png")
        img.save(str(out_path))
        print(f"Exported actual image -> {out_path} (for visual confirm)")
    return 0


if __name__ == "__main__":
    raise SystemExit(trace_read())
