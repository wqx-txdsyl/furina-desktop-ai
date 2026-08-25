"""桌面世界（legacy-plan/7 §3-6, §36）。

角色存在于桌面坐标系 (logical pixel)，多显示器/DPI 用 logical pixel。
世界提供边界、表面(桌面/任务栏/窗口边缘/屏幕边缘)。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


class Surface(str, enum.Enum):
    DESKTOP = "desktop"
    TASKBAR = "taskbar"
    WINDOW_EDGE = "window_edge"
    SCREEN_EDGE = "screen_edge"


@dataclass
class Vec2:
    x: float = 0.0
    y: float = 0.0


@dataclass
class Rect:
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


class DesktopWorld:
    """逻辑坐标系世界；物理像素由 Qt/DPI 换算。

    坐标约定：逻辑像素。多显示器支持预留 bounds 列表（legacy-plan/7 §4）。
    """

    def __init__(self, screen_w: float, screen_h: float) -> None:
        self.screen = Rect(0, 0, screen_w, screen_h)
        self.bounds = [Rect(0, 0, screen_w, screen_h)]   # 主屏；多屏追加
        self.screens = [Rect(0, 0, screen_w, screen_h)]  # 多显示器屏幕矩形列表
        self.taskbar_height = 48.0
        self.safe_margin = 12.0
        self.surface = Surface.DESKTOP
        self.character_scale = 1.0
        self.active_window_rect: Optional[Rect] = Rect()

    # ---- 约束角色位置
    def clamp(self, pos: Vec2, char_w: float, char_h: float) -> Vec2:
        margin = self.safe_margin
        x = max(margin, min(pos.x, self.screen.w - char_w - margin))
        # 底部给任务栏留白
        y = max(margin, min(pos.y, self.screen.h - self.taskbar_height - char_h - margin))
        return Vec2(x, y)

    # ---- 当前活动窗口矩形
    def update_active_window(self, rect: Optional[Rect]) -> None:
        self.active_window_rect = rect or Rect()

    def window_edge_target(self) -> Optional[Vec2]:
        """若窗口在屏幕内，返回“站到窗口下方边缘”的目标点。"""
        r = self.active_window_rect
        if r is None or r.w <= 0:
            return None
        screen = self.current_screen_for_point(r.cx, r.cy)
        return Vec2(r.cx, min(screen.y + screen.h - self.taskbar_height - 80, r.y + r.h + 12))

    # ============================================================ 空间几何 helper（Phase 12）
    # 纯几何（无 Qt / 无后端语义）。坐标一律 logical pixel。
    def add_screen(self, rect: Rect) -> None:
        """追加一个显示器（多屏基础支持，§89）。"""
        self.screens.append(rect)
        self.bounds = list(self.screens)

    def set_screens(self, rects: list) -> None:
        self.screens = list(rects or [self.screen])
        self.bounds = list(self.screens)

    def current_screen_for_point(self, x: float, y: float) -> Rect:
        """点所在屏幕；不在任何屏内 → 主屏。"""
        for s in self.screens:
            if s.x <= x < s.x + s.w and s.y <= y < s.y + s.h:
                return s
        return self.screens[0]

    def screen_index_for_point(self, x: float, y: float) -> int:
        for i, s in enumerate(self.screens):
            if s.x <= x < s.x + s.w and s.y <= y < s.y + s.h:
                return i
        return 0

    def available_bounds(self, screen: Optional[Rect] = None) -> Rect:
        """可用区域：去掉任务栏与安全边距。返回 Rect（左上角为安全原点）。"""
        s = screen or self.current_screen_for_point(self.screen.cx, self.screen.cy)
        m = self.safe_margin
        x = s.x + m
        y = s.y + m
        w = max(0.0, s.w - 2 * m)
        h = max(0.0, s.h - self.taskbar_height - 2 * m)
        return Rect(x, y, w, h)

    def safe_zone(self, char_w: float, char_h: float, screen: Optional[Rect] = None) -> Rect:
        """角色**左上角**可安全放置的区域（把角色自身 + 边缘余量考虑进去）。"""
        avail = self.available_bounds(screen)
        return Rect(avail.x, avail.y, max(0.0, avail.w - char_w), max(0.0, avail.h - char_h))

    def is_valid_position(self, x: float, y: float, char_w: float, char_h: float,
                          screen: Optional[Rect] = None) -> bool:
        """某点（角色左上角）是否是合法安全位置。"""
        sz = self.safe_zone(char_w, char_h, screen)
        return sz.x <= x <= sz.x + sz.w and sz.y <= y <= sz.y + sz.h

    def nearest_safe_point(self, x: float, y: float, char_w: float, char_h: float,
                           screen: Optional[Rect] = None) -> Vec2:
        """把点夹到最近的安全位置（几何修复，§91）。"""
        sz = self.safe_zone(char_w, char_h, screen)
        nx = max(sz.x, min(x, sz.x + sz.w))
        ny = max(sz.y, min(y, sz.y + sz.h))
        return Vec2(nx, ny)

    def window_edge_candidates(self, char_w: float, char_h: float,
                               screen: Optional[Rect] = None) -> list:
        """活动窗口附近的安全候选（bottom-edge / side / safe corner），以角色左上角位置表示。

        供 APPROACH / NEAR 用，语义目标是"用户附近安全区"，**不是**贴窗口中心（§25/§43）。
        """
        r = self.active_window_rect
        if r is None or r.w <= 0:
            return []
        screen = screen or self.current_screen_for_point(r.cx, r.cy)
        avail = self.available_bounds(screen)
        candidates = []
        # 1) 下方边缘（正文下方，不挡正文）
        bottom = min(avail.y + avail.h - char_h, r.y + r.h + 12)
        if bottom > avail.y:
            candidates.append(Vec2(r.cx - char_w / 2, bottom))
        # 2) 左侧（外侧，不挡按钮）
        left = max(avail.x, r.x - self.safe_margin * 2 - char_w)
        mid_y = max(avail.y, min(avail.y + avail.h - char_h, r.y + r.h * 0.3))
        if left > avail.x:
            candidates.append(Vec2(left, mid_y))
        # 3) 右侧
        right = min(avail.x + avail.w - char_w, r.x + r.w + self.safe_margin * 2)
        if right > avail.x:
            candidates.append(Vec2(right, mid_y))
        return candidates
