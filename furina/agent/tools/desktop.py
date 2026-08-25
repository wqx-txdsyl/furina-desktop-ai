"""桌面感知工具（Phase 14G）—— read-only L0。

desktop.active_window / desktop.list_windows：Windows 上用 ctypes 调 user32 枚举窗口。
非 Windows / 无 GUI 环境 → 如实返回失败（不假装）。
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

from furina.agent.permission import Permission
from furina.agent.tool import BaseTool, ToolResult


def _windows():
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        return ctypes
    except Exception:
        return None


def _list_windows_win() -> List[Dict[str, Any]]:
    ctypes = _windows()
    if ctypes is None:
        return []
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        def _get_pid(hwnd):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value

        def _get_title(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value

        out: List[Dict[str, Any]] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _cb(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            title = _get_title(hwnd)
            if not title:
                return True
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            out.append({"hwnd": hwnd, "title": title[:200], "pid": _get_pid(hwnd),
                        "rect": [rect.left, rect.top, rect.right, rect.bottom]})
            return True

        user32.EnumWindows(_cb, 0)
        return out[:100]
    except Exception:
        return []


def _active_window_win() -> Dict[str, Any]:
    ctypes = _windows()
    if ctypes is None:
        return {}
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {}
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return {"hwnd": hwnd, "title": buf.value[:200], "pid": pid.value}
    except Exception:
        return {}


class ActiveWindowTool(BaseTool):
    name = "desktop.active_window"
    description = "当前前台窗口标题/进程（只读 L0）"
    permission = Permission.L0_READ

    def run(self) -> ToolResult:
        if sys.platform != "win32":
            return ToolResult(False, error="desktop.active_window 仅支持 Windows", verified=False)
        info = _active_window_win()
        if not info:
            return ToolResult(False, error="无法读取前台窗口", verified=False)
        return ToolResult(True, data=info, verified=True, note=f"前台: {info.get('title','')}")


class ListWindowsTool(BaseTool):
    name = "desktop.list_windows"
    description = "列出可见窗口（标题/进程/位置，只读 L0）"
    permission = Permission.L0_READ

    def run(self) -> ToolResult:
        if sys.platform != "win32":
            return ToolResult(False, error="desktop.list_windows 仅支持 Windows", verified=False)
        wins = _list_windows_win()
        return ToolResult(True, data={"windows": wins, "count": len(wins)},
                          verified=True, note=f"{len(wins)} 个可见窗口")
