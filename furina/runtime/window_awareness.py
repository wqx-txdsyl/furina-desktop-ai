"""窗口感知（plan/7 §6, plan/5 §7）。

用 ctypes 直接调 user32 获取前台窗口（无需 pywin32）。
非 Windows 环境返回占位信息。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from furina.core import get_logger
from .world import Rect

log = get_logger("runtime.winaware")


@dataclass
class WindowInfo:
    app: str = ""
    title: str = ""
    rect: Optional[Rect] = None

    def to_dict(self) -> dict:
        return {"app": self.app, "title": self.title,
                "rect": (None if not self.rect else [self.rect.x, self.rect.y, self.rect.w, self.rect.h])}


def _active_window_windows() -> Optional[WindowInfo]:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    # 标题
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    # 类名（可推断应用）
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    # 矩形
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return WindowInfo(
        app=cls.value,
        title=buf.value,
        rect=Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
    )


class WindowAwareness:
    """Medium tick 拉取前台窗口，更新 State / World。"""

    def __init__(self, update_cb) -> None:
        self.update_cb = update_cb   # callable(WindowInfo)

    def poll(self) -> Optional[WindowInfo]:
        info = None
        if sys.platform == "win32":
            try:
                info = _active_window_windows()
            except Exception as e:  # pragma: no cover
                log.debug("winaware error: %s", e)
        else:
            info = WindowInfo(app="unknown", title="", rect=Rect(0, 0, 1920, 1080))
        self.update_cb(info)
        return info
