"""渲染器：图层合成（plan/7 §13, §25）。

骨架：底层 base 图 + 可选微动作叠加（呼吸轻微偏移 / 眨眼）+ 说话气泡 + 调试轨迹。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QPointF
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPen


@dataclass
class RenderState:
    x: float = 0.0
    y: float = 0.0
    w: float = 256.0
    h: float = 360.0
    flipped: bool = False            # 朝向
    breathing_offset: float = 0.0    # 0..1
    blink: bool = False
    speech: str = ""
    debug: str = ""


class Renderer:
    """把状态合成到一张 QImage 上的简单引擎。"""

    def paint(self, base: Optional[QImage], state: RenderState) -> QImage:
        canvas_w = max(64, int(state.w) + 40)
        canvas_h = max(64, int(state.h) + 40)
        img = QImage(canvas_w, canvas_h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        if base is not None:
            # 保持长宽比，居中（letterbox），避免拉伸
            target = QRectF(20, 20 - state.breathing_offset * 3.0, state.w, state.h)
            self._draw_fitted(p, base, target)
        else:
            # 占位：半透明角色框
            box = QRectF(20, 20, state.w, state.h)
            p.setPen(QPen(QColor(80, 120, 220, 160), 2))
            p.setBrush(QColor(80, 120, 220, 60))
            p.drawRoundedRect(box, 24, 24)
            p.setPen(QColor(255, 255, 255, 220))
            p.drawText(box.adjusted(8, 8, -8, -8), Qt.AlignCenter, "Furina\n(placeholder)")
        # 说话气泡
        if state.speech:
            bubble = QRectF(20, 20 - 46, max(120, min(360, 14 * len(state.speech))), 40)
            p.setPen(QPen(QColor(255, 255, 255, 220), 1))
            p.setBrush(QColor(30, 30, 40, 220))
            p.drawRoundedRect(bubble, 10, 10)
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Microsoft YaHei", 10))
            p.drawText(bubble, Qt.AlignCenter, state.speech[:40])
        p.end()
        return img

    @staticmethod
    def _draw_fitted(p: QPainter, base: QImage, target: QRectF) -> None:
        """在 target 内按比例绘制 base，保持纵横比并居中。"""
        if base.width() <= 0 or base.height() <= 0:
            return
        scale = min(target.width() / base.width(), target.height() / base.height())
        w = base.width() * scale
        h = base.height() * scale
        x = target.x() + (target.width() - w) / 2
        y = target.y() + (target.height() - h) / 2
        p.drawImage(QRectF(x, y, w, h), base, base.rect())
