"""动画控制器（plan/7 §19-23）。

- 帧序列播放：frames + fps + loop + interruptible + priority（与 AssetEntry 对齐）。
- 跨帧过渡：两个姿态间按 t 混合（crossfade），做出“站→坐”等流动过渡。
- 微动作叠加：呼吸轻微缩放/眨眼等作为 Idle overlay（plan/7 §25）。

本层只管“怎么动”，不管“为何选哪些帧”（由 Behavior/State 决定）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QColor

from furina.assets.asset_manifest import AssetEntry
from furina.core import get_logger

log = get_logger("runtime.anim")


@dataclass
class AnimationSpec:
    frames: List[str]                 # 帧文件路径（相对素材目录）
    fps: float = 12.0
    loop: bool = True
    interruptible: bool = True
    priority: int = 50
    # 可选：过渡到下一动画时 crossfade
    transition: float = 0.25


class AnimationController:
    """维护“当前动画 + 过渡”，按时间取当前应显示的帧。"""

    def __init__(self, load_img: Callable[[str], Optional[QImage]]) -> None:
        self._load_img = load_img
        self._spec: Optional[AnimationSpec] = None
        self._started: float = 0.0
        self._frame_idx: int = 0
        # 过渡
        self._from_img: Optional[QImage] = None
        self._to_img: Optional[QImage] = None
        self._fade_start = 0.0
        self._fade_dur = 0.0

    # -------------------------------------------------- 查询
    @property
    def active(self) -> bool:
        return self._spec is not None

    def frame_count(self) -> int:
        return len(self._spec.frames) if self._spec else 0

    def current_frame_index(self, now: float | None = None) -> int:
        if not self._spec:
            return 0
        n = self.frame_count()
        if n <= 1:
            return 0
        now = time.monotonic() if now is None else now
        frac = (now - self._started) * self._spec.fps
        idx = int(frac)
        if self._spec.loop:
            return idx % n
        return min(n - 1, idx)

    def progress(self, now: float | None = None) -> float:
        """当前 clip 进度 0..1（非 loop 到底=1.0）。"""
        if not self._spec:
            return 0.0
        n = self.frame_count()
        if n <= 1:
            return 1.0
        now = time.monotonic() if now is None else now
        frac = (now - self._started) * self._spec.fps
        if self._spec.loop:
            return (frac % n) / n
        # 非 loop：进度按帧截止（到底=1.0），不必等 frac 完美整除
        idx = int(frac)
        if idx >= n - 1:
            return 1.0
        return max(0.0, idx / n)

    def is_finished(self, now: float | None = None) -> bool:
        """非 loop clip 是否播完（底到末帧）：loop 永不 finished。"""
        if not self._spec:
            return False
        if self._spec.loop:
            return False
        now = time.monotonic() if now is None else now
        return self.progress(now) >= 1.0

    # -------------------------------------------------- 控制
    def play(self, spec: AnimationSpec, now: float | None = None) -> None:
        self._spec = spec
        self._started = time.monotonic() if now is None else now
        self._frame_idx = 0

    def crossfade(self, from_img: Optional[QImage], to_img: Optional[QImage],
                  duration: float = 0.25, now: float | None = None) -> None:
        self._from_img = from_img
        self._to_img = to_img
        self._fade_dur = max(0.01, duration)
        self._fade_start = time.monotonic() if now is None else now

    def stop(self) -> None:
        self._spec = None

    # -------------------------------------------------- 取当前帧（可含过渡混合 & 微动作）
    def frame(self, now: float | None = None, breath: float = 0.0) -> Optional[QImage]:
        if not self._spec:
            return None
        now = time.monotonic() if now is None else now
        idx = self.current_frame_index(now)
        path = self._spec.frames[min(idx, self.frame_count() - 1)]
        img = self._load_img(path)
        if img is None:
            return None
        # 过渡混合
        if self._from_img is not None and self._to_img is not None:
            t = min(1.0, (now - self._fade_start) / self._fade_dur)
            if t < 1.0:
                return _blend(self._from_img, self._to_img, t)
            self._from_img = None
            self._to_img = None
        # 呼吸：轻微上下缩放（微动作 overlay，plan/7 §25）
        if breath != 0.0:
            return _breath(img, breath)
        return img


def _blend(a: QImage, b: QImage, t: float) -> QImage:
    """crossfade 两图，保持 a 的尺寸；两图都按 a 的尺寸等比缩放+居中，避免错位/残影。"""
    w, h = a.width(), a.height()
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    target = QRectF(0, 0, w, h)
    p.setOpacity(1.0)
    _draw_fitted(p, a, target)
    p.setOpacity(t)
    _draw_fitted(p, b, target)
    p.end()
    return out


def _draw_fitted(p: QPainter, img: QImage, target: QRectF) -> None:
    """在 target 内按比例绘制 img，保持纵横比并居中。"""
    if img.width() <= 0 or img.height() <= 0:
        return
    scale = min(target.width() / img.width(), target.height() / img.height())
    w = img.width() * scale
    h = img.height() * scale
    x = target.x() + (target.width() - w) / 2
    y = target.y() + (target.height() - h) / 2
    p.drawImage(QRectF(x, y, w, h), img, img.rect())


def _breath(img: QImage, breath: float) -> QImage:
    """按 breath(0..1) 做明显呼吸：轻微缩放 + 竖向小幅往复（让静止帧“活着”）。"""
    w, h = img.width(), img.height()
    amp = 0.035                       # ±3.5% 缩放
    bob = (breath - 0.5) * 5.0        # ±2.5px 升降
    scale = 1.0 + (breath - 0.5) * amp
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    target = QRectF(0, 0, w * scale, h * scale)
    tx = (w - target.width()) / 2
    ty = (h - target.height()) / 2 + bob
    p.drawImage(QRectF(tx, ty, target.width(), target.height()), img, img.rect())
    p.end()
    return out
