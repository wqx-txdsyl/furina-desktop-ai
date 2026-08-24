"""Phase 13 SpatialProxyWindow —— 无素材的桌面"身体"（透明方框）。

由 DesktopSpatialRuntime 真实驱动（approach/maintain/withdraw/wander/drag）。
它不画任何角色 PNG，只显示文字 + 移动箭头；body semantic 变化直接反映在文字上。
拖拽经真实 spatial 链：drag start → interrupted → DRAGGED → move → release → commit → grace。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QMouseEvent
from PySide6.QtWidgets import QWidget

from furina.core import get_logger

log = get_logger("runtime.proxy")


class SpatialProxyWindow(QWidget):
    """透明方框角色代理。坐标语义与 FurinaWindow 对齐（供 PositionAdapter 使用）。"""

    CH_W = 256.0
    CH_H = 360.0
    SIDE = 12.0
    TOP = 40.0

    def __init__(self, world=None, on_drag_start=None, on_drag_release=None,
                 on_drag_move=None) -> None:
        super().__init__()
        self.world = world
        # PositionAdapter 需要的字段
        self._char_w = self.CH_W
        self._char_h = self.CH_H
        self._side = self.SIDE
        self._top = self.TOP
        self.pos: "QPointFLike" = _Vec(100.0, 100.0)     # 角色世界坐标（pos 语义）
        self.dragging = False
        self._drag_offset = QPointF(0.0, 0.0)
        self.on_drag_start = on_drag_start
        self.on_drag_release = on_drag_release
        self.on_drag_move = on_drag_move
        # 显示字段
        self._activity = "idle"
        self._posture = "UPRIGHT"
        self._expression = "NEUTRAL"
        self._gaze = "FRONT"
        self._spatial_state = "IDLE"
        self._moving_dir = ""
        self._facing = "FRONT"

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(180, 74)
        self._apply_window_pos(self.pos.x, self.pos.y)

    def _apply_window_pos(self, x: float, y: float) -> None:
        self.move(int(x - self._side), int(y - self._top))
        # QWidget 自带 width()/height()；这里不覆写（避免自引用）

    def set_position(self, x: float, y: float) -> None:
        self.pos = _Vec(float(x), float(y))
        self._apply_window_pos(self.pos.x, self.pos.y)

    # -------------------------------------------------- 状态显示
    def update_semantic(self, *, activity: str, posture: str, expression: str, gaze: str,
                        spatial_state: str, moving: bool, facing: str) -> None:
        self._activity = activity
        self._posture = posture.upper()
        self._expression = expression.upper()
        self._gaze = gaze.upper()
        self._spatial_state = spatial_state
        self._facing = facing
        self._moving_dir = ("→" if facing == "RIGHT" else "←" if facing == "LEFT" else "")
        self.update()

    # -------------------------------------------------- paint
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setPen(QColor(140, 170, 230, 200))
        p.setBrush(QColor(30, 40, 70, 170))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor(255, 255, 255, 255))
        p.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        p.drawText(QRectF(10, 6, self.width() - 20, 20), Qt.AlignLeft,
                   f"FURINA {self._moving_dir}")
        p.setFont(QFont("Microsoft YaHei", 8))
        p.setPen(QColor(180, 200, 240, 240))
        p.drawText(QRectF(10, 26, self.width() - 20, 16), Qt.AlignLeft,
                   f"{self._posture} | {self._expression} | {self._gaze}")
        p.drawText(QRectF(10, 42, self.width() - 20, 16), Qt.AlignLeft,
                   f"act={self._activity}  spatial={self._spatial_state}")
        p.setPen(QColor(120, 220, 170, 220))
        p.drawText(QRectF(10, 58, self.width() - 20, 12), Qt.AlignLeft,
                   f"{'MOVING ' + self._moving_dir if self._moving_dir else 'STILL'}")
        p.end()

    # -------------------------------------------------- drag（真实 spatial 链）
    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton:
            self.dragging = True
            g = ev.globalPosition()
            self._drag_offset = QPointF(g.x() - self.x(), g.y() - self.y())
            if self.on_drag_start:
                self.on_drag_start()
            ev.accept()

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if self.dragging:
            g = ev.globalPosition()
            wx = g.x() - self._drag_offset.x()
            wy = g.y() - self._drag_offset.y()
            self.set_position(wx + self._side, wy + self._top)
            if self.on_drag_move:
                self.on_drag_move()
        ev.accept()

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton:
            self.dragging = False
            if self.on_drag_release:
                self.on_drag_release()
            ev.accept()

    # -------------------------------------------------- 供 InputRouter 之类（简化为 whole）
    def _local_rect(self) -> QRectF:
        return QRectF((self.width() - self.CH_W) / 2, self._top, self.CH_W, self.CH_H)


class _Vec:
    """pos 语义的轻量向量（pos.x / pos.y）。"""
    def __init__(self, x: float, y: float):
        self.x = float(x)
        self.y = float(y)
