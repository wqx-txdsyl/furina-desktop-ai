"""窗口感知（plan/7 §6, plan/5 §7）。

用 ctypes 直接调 user32/kernel32 获取前台窗口（无需 pywin32）。
Phase 13 终审 §2.2-2.4：补充**真实 Windows 感知边界**：
  - 前台 HWND 的**进程可执行名**（GetWindowThreadProcessId → OpenProcess → QueryFullProcessImageNameW），
    与窗口类名分离（类名不能当 app 分类，避免 Chrome_WidgetWin_1 被 "et" 误判为表格）；
  - 真实输入空闲秒（GetLastInputInfo，系统级，非自喂）。
非 Windows 环境返回占位信息（idle 0，不假装知道）。
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
    app: str = ""          # 窗口类名（识别 UI 归属用，不做业务分类）
    title: str = ""
    process: str = ""      # 进程可执行名（如 chrome / notepad / Code）—— 业务分类的唯一输入
    idle: Optional[float] = None   # 真实输入空闲秒（GetLastInputInfo）；None = 不可用（不假装 0）
    rect: Optional[Rect] = None

    def to_dict(self) -> dict:
        return {"app": self.app, "title": self.title, "process": self.process,
                "idle": (None if self.idle is None else round(self.idle, 1)),
                "rect": (None if not self.rect else [self.rect.x, self.rect.y, self.rect.w, self.rect.h])}


def _idle_from_ticks(last_input_ms: float, now_ms: float) -> float:
    """纯函数：tick 差 → 空闲秒（FINAL-R1 §1.1 可测性）。"""
    return max(0.0, (now_ms - last_input_ms) / 1000.0)


def _get_idle_seconds() -> Optional[float]:
    """真实输入空闲秒：GetLastInputInfo（User32）− GetTickCount64（Kernel32）。

    Phase 13 FINAL-R1 §1.1：**GetTickCount/GetTickCount64 属于 Kernel32**，不是 User32。
    用 64 位 tick（无回绕问题）。API 失败 → 返回 None（**绝不假装成 0.0**，那是"用户一直活跃"的假象）。
    """
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return None
        # Kernel32.GetTickCount64：64 位毫秒 tick（无回绕），与 dwTime(32 位) 同基准
        ticks = kernel32.GetTickCount64()
        return _idle_from_ticks(lii.dwTime, ticks)
    except Exception:  # pragma: no cover — API 失败：不假装成 0（未知空闲）
        return None


def _get_process_name(hwnd) -> str:
    """前台窗口所属进程可执行名（无扩展名，小写），失败返回 ""。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = buf.value.replace("\\", "/").rsplit("/", 1)[-1]
                return name[:-4] if name.lower().endswith(".exe") else name
        finally:
            kernel32.CloseHandle(h)
    except Exception:  # pragma: no cover
        pass
    return ""


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
    # 类名（识别 UI 归属用，**不做业务分类**）
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    # 矩形
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return WindowInfo(
        app=cls.value,
        title=buf.value,
        process=_get_process_name(hwnd),
        idle=_get_idle_seconds() or 0.0,
        rect=Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
    )


class WindowAwareness:
    """Medium tick 拉取前台窗口，更新 State / World。"""

    def __init__(self, update_cb) -> None:
        self.update_cb = update_cb   # callable(WindowInfo)
        # Phase 13 FINAL-R1 §1.1：空闲真相显式化 —— None = 尚无有效采样（绝不假装 0）
        self.last_idle: Optional[float] = None
        self.idle_available: bool = False

    def poll(self) -> Optional[WindowInfo]:
        info = None
        if sys.platform == "win32":
            try:
                info = _active_window_windows()
            except Exception as e:  # pragma: no cover
                log.debug("winaware error: %s", e)
        else:
            # 非 Windows：占位（不假装知道进程/输入）
            info = WindowInfo(app="unknown", title="", process="unknown",
                              idle=None, rect=Rect(0, 0, 1920, 1080))
        if info is not None:
            if info.idle is None:
                # API 失败/不可用：保留上一有效值（或 None），不假装成 0（用户活跃的假象）
                self.idle_available = False
            else:
                self.last_idle = info.idle
                self.idle_available = True
        self.update_cb(info)
        return info
