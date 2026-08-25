"""素材管理器（legacy-plan/7 §29-31）。

负责 load / cache / unload / preload / stream；不靠文件名猜语义。
按语义 resolve；并为角色生成 whale-girl 式**淡 drop-shadow**（沿 alpha 剪影）。
"""
from __future__ import annotations

from pathlib import Path
from io import BytesIO
from typing import Dict, Optional

from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import QRectF

from PIL import Image, ImageFilter

from furina.assets.asset_manifest import AssetEntry, AssetManifest, AssetQuery, AssetResolver
from furina.core import get_logger
from .world import Vec2

log = get_logger("runtime.assets")


def _pil_to_qimg(im) -> Optional[QImage]:
    """PIL RGBA → QImage（PIL save 到 BytesIO 是支持的）。"""
    try:
        buf = BytesIO()
        im.save(buf, "PNG")
        return QImage.fromData(buf.getvalue())
    except Exception:
        return None


def _make_drop_shadow(img_path: str, blur: float = 6.0, alpha: float = 0.25) -> Optional[QImage]:
    """whale-girl 式 drop-shadow：沿角色 alpha 剪影的柔和黑影（黑 25%、模糊 6px）。

    等价 CSS filter: drop-shadow(0 4px 6px rgba(0,0,0,.25))。紧贴轮廓、很淡，不产生鬼影/描边。
    """
    try:
        im = Image.open(img_path).convert("RGBA")
    except Exception:
        return None
    mask = im.split()[3]
    if blur > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(blur))
    a = mask.point(lambda x: int(x * alpha))
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    shadow.putalpha(a)
    return _pil_to_qimg(shadow)


class AssetManager:
    """按语义 resolve 素材，并提供角色 drop-shadow 与缓存。"""

    def __init__(self, manifest: AssetManifest, base_dir: Path) -> None:
        self.manifest = manifest
        self.base_dir = base_dir
        self.resolver = AssetResolver(manifest)
        self._cache: Dict[str, QImage] = {}
        self._shadow_cache: Dict[str, QImage] = {}
        self.fallback: Optional[QImage] = None

    def set_manifest(self, manifest: AssetManifest) -> None:
        """更换 manifest，并同步重建 resolver（避免引用旧的空 manifest）。"""
        self.manifest = manifest
        self.resolver = AssetResolver(manifest)
        self._cache.clear()
        self._shadow_cache.clear()

    # -------------------------------------------------- 图片加载
    def load(self, entry: AssetEntry) -> Optional[QImage]:
        if entry.asset_id in self._cache:
            return self._cache[entry.asset_id]
        if not entry.path:
            return None
        img = QImage(str(self.base_dir / entry.path))
        if img.isNull():
            log.warning("素材加载失败: %s", entry.path)
            return None
        self._cache[entry.asset_id] = img
        return img

    def load_path(self, path: str) -> Optional[QImage]:
        """按相对素材目录的路径加载（供动画控制器按帧取图）。"""
        img = QImage(str(self.base_dir / path))
        return img if not img.isNull() else None

    def preload(self, entries) -> None:
        for e in entries:
            self.load(e)

    # -------------------------------------------------- 按状态取当前帧
    def entry_for_state(self, posture: str, emotion: str, gaze: str = "front",
                        action: str = "idle") -> Optional[AssetEntry]:
        q = AssetQuery(posture=posture, emotion=emotion, gaze=gaze, action=action)
        return self.resolver.resolve(q)

    def frame_for_state(self, posture: str, emotion: str, gaze: str = "front",
                        action: str = "idle") -> Optional[QImage]:
        entry = self.entry_for_state(posture, emotion, gaze, action)
        if entry is None:
            return self.fallback
        img = self.load(entry)
        if img is None and self.fallback is not None:
            return self.fallback
        return img

    def sequence_for(self, name: str) -> Optional[AssetEntry]:
        """按名字取多帧序列资产（action=name 且 kind=sequence）。"""
        for e in self.manifest.entries:
            if e.kind == "sequence" and e.action == name:
                return e
        return None

    # -------------------------------------------------- 沿轮廓的淡 drop-shadow（whale-girl 式）
    def shadow_for(self, entry: Optional[AssetEntry]) -> Optional[QImage]:
        """沿角色 alpha 的柔和 drop-shadow（黑 25%、模糊 6px），让角色浮于屏幕之上。"""
        if entry is None or not entry.path:
            return None
        if entry.asset_id in self._shadow_cache:
            return self._shadow_cache[entry.asset_id]
        path = self.base_dir / entry.path
        if not path.exists():
            return None
        shadow = _make_drop_shadow(str(path))
        if shadow is not None:
            self._shadow_cache[entry.asset_id] = shadow
        return shadow

    # -------------------------------------------------- 包围盒（逻辑像素）
    def body_rect(self, pos: Vec2, scale: float = 1.0) -> QRectF:
        base_w = self._ref_w * scale
        base_h = self._ref_h * scale
        return QRectF(pos.x, pos.y, base_w, base_h)

    def set_reference_size(self, w: float, h: float) -> None:
        """设定参考角色尺寸（默认按屏幕高度的比例，legacy-plan/7 §35）。"""
        self._ref_w = w
        self._ref_h = h

    @property
    def reference_size(self) -> tuple:
        return (getattr(self, "_ref_w", 256), getattr(self, "_ref_h", 360))
