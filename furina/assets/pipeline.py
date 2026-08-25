"""素材生成管线（legacy-plan/2 §十）。

Base Reference → Prompt Template → Pose Spec → Image Generation →
Consistency Check → Background Removal → Crop/Scale → Asset Metadata → Asset Library。

骨架提供 Prompt 模板与编排结构；实际生成需显式调用 ``generate_batch``。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from furina.core import get_logger
from .agnes_client import AgnesClient, ImageGenerateOptions
from .asset_manifest import AssetEntry, AssetManifest, naming_for
from .qc import QCEngine, QCResult

log = get_logger("assets.pipeline")

BASE_PROMPT = ("chibi Genshin Impact Furina, white and light-blue hair, blue top-hat with feather, blue and white dress, "
               "consistent character identity, isolated character, full body, "
               "FLAT CEL-SHADED 2D game sprite style, clean bold single-color outlines, flat solid colors, "
               "cel shading only, NO gradients, NO soft painterly shading, NO dramatic lighting, crisp clean anime sprite, "
               "match the provided reference image exactly")

# 生活姿态提示（legacy-plan/0：重心/行为/身体状态，避免“展示立绘感”）
POSTURE_HINT = {
    "standing": "standing naturally, relaxed weight, slight casual stance, hands at ease, NOT a rigid showcase pose",
    "sitting": "sitting with legs dangling and knees bent, torso leaning slightly forward, casual relaxed posture, weight settled",
    "lying": "lying down lounging on a flat surface, one arm under head, relaxed body, casual, not a pose",
    "sleeping": "sleeping, eyes closed, relaxed curled comfortable posture, peaceful, no pillow",
    "crouching": "crouching down, knees bent, casual",
    "leaning": "leaning against a surface, relaxed casual gesture",
}

GAZE_HINT = {
    "user": "looking toward the viewer/user, eyes on you",
    "screen": "looking forward at a screen, slight downward tilt, focused",
    "left": "eyes looking to the left",
    "right": "eyes looking to the right",
    "up": "eyes looking up, thoughtful",
    "down": "eyes looking down, shy or contemplative",
    "front": "looking straight ahead",
}


def prompt_for(posture: str, emotion: str, gaze: str, action: str, prop: Optional[str] = None) -> str:
    """legacy-plan/2 §23：一致性与“生活化姿态”要求放在同一条 prompt。

    强调自然重心/行为/视线，避免“游戏展示立绘”。用 img2img 以基座图为身份锚点。
    """
    parts = [BASE_PROMPT]
    parts.append(POSTURE_HINT.get(posture, f"posture: {posture}, natural relaxed"))
    parts.append(f"expression: {emotion}")
    parts.append(GAZE_HINT.get(gaze, f"gaze: {gaze}"))
    parts.append(f"action: {action}")
    if prop:
        parts.append(f"holding/with prop: {prop}")
    # 背景必须是纯色、无场景道具，否则泛洪抠不干净（生活化只体现在身体姿态/视线）
    parts.append("isolated single character on a plain uniform flat pale solid background (light gray/cream), "
                 "NO room, NO desk, NO furniture, NO plants, NO monitor, NO bed, NO pillow, NO other objects, "
                 "no props, no cast shadow, NO background gradient, character only, full body visible, "
                 "flat cel-shaded, clean crisp, consistent style")
    return ", ".join(parts)


@dataclass
class AssetSpec:
    posture: str
    emotion: str
    gaze: str = "front"
    action: str = "idle"
    variant: int = 1
    prop: Optional[str] = None
    size: str = "1K"
    ratio: str = "1:1"
    # 四层素材架构（任务书 §3-13）：base_pose / expression / gaze / micro / action / transition / prop
    role: str = "base_pose"
    tags: List[str] = field(default_factory=list)


class AssetPipeline:
    """把一张基座图工程化为一套可被行为系统调用的素材。"""

    def __init__(self, base_image: Path, agnes: AgnesClient, out_dir: Path,
                 qc: Optional[QCEngine] = None) -> None:
        self.base_image = base_image
        self.agnes = agnes
        self.out_dir = out_dir
        self.qc = qc or QCEngine()

    def _base_data_uri(self) -> str:
        data = self.base_image.read_bytes()
        return f"data:image/png;base64,{base64.b64encode(data).decode()}"

    def _decode_result(self, result) -> bytes:
        """优先取 b64，否则下载 url（自包含 + 兜底）。"""
        import httpx as _httpx
        if result.b64:
            return base64.b64decode(result.b64)
        if result.url:
            r = _httpx.get(result.url, timeout=120)
            r.raise_for_status()
            return r.content
        raise RuntimeError("Agnes 未返回可用图像数据")

    def _image_path(self, spec: AssetSpec, variant: int) -> str:
        return f"poses/{naming_for(spec.posture, spec.emotion, spec.gaze, spec.action, variant)}.png"

    def generate_one(self, spec: AssetSpec, variant: int = 1) -> AssetEntry:
        """基于基座图做图生图，保存 PNG 并写入 manifest 字段。"""
        prompt = prompt_for(spec.posture, spec.emotion, spec.gaze, spec.action, spec.prop)
        log.info("生成素材: %s", prompt[:60])
        result = self.agnes.generate_image(ImageGenerateOptions(
            prompt=prompt, size=spec.size, ratio=spec.ratio,
            image=[self._base_data_uri()], return_base64=True))
        data = self._decode_result(result)
        out_file = self.out_dir / self._image_path(spec, variant)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(data)
        # 背景移除 + 裁剪（legacy-plan/2 §24 管线一步），可能改变尺寸/alpha
        try:
            from .postprocess import remove_background_and_crop
            remove_background_and_crop(out_file)
        except Exception as e:  # pragma: no cover - 后处理失败不阻断主流程
            log.warning("背景移除失败 %s: %s", out_file.name, e)
        qc_res: QCResult = self.qc.run_automatic(out_file)
        return AssetEntry(
            asset_id=naming_for(spec.posture, spec.emotion, spec.gaze, spec.action, variant),
            posture=spec.posture, emotion=spec.emotion, gaze=spec.gaze,
            direction="front", action=spec.action, kind="frame",
            path=str(out_file.relative_to(self.out_dir)),
            quality_score=qc_res.total,
            anchors={"head": [0.5, 0.2], "body": [0.5, 0.5], "hand": [0.7, 0.45]},
            role=spec.role, tags=list(spec.tags),
        )

    def generate_batch(self, specs: List[AssetSpec], manifest: AssetManifest,
                       dry_run: bool = True) -> List[AssetEntry]:
        """批量生成并累积到 manifest。

        同一语义组合(姿态/表情/视线/动作)复用同一文件名(变体递增)，
        避免相同 asset_id 相互覆盖。default dry_run=True 只计算不调用 API。
        """
        # 已存在语义组合的变体计数（含 manifest 已有 + 本批新生成）
        used: Dict[str, int] = {}
        for e in manifest.entries:
            key = (e.posture, e.emotion, e.gaze, e.action)
            used[key] = used.get(key, 0) + 1

        new_entries: List[AssetEntry] = []
        for spec in specs:
            key = (spec.posture, spec.emotion, spec.gaze, spec.action)
            used[key] = used.get(key, 0) + 1
            variant = used[key]
            asset_id = naming_for(spec.posture, spec.emotion, spec.gaze, spec.action, variant)
            if dry_run:
                log.info("[dry-run] %s", asset_id)
                continue
            entry = self.generate_one(spec, variant)
            new_entries.append(entry)
            manifest.entries.append(entry)
        return new_entries
