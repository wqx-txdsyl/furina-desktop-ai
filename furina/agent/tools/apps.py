"""应用启动工具（legacy-plan/5 §10-11）。

用 subprocess 启动本机应用（记事本/浏览器/编辑器等）。
Phase 13 终审 §10.4：`app.launch` 必须**可观察验证** —— Popen 成功不等于应用真的起来了；
Windows 上在有限超时内轮询 tasklist 确认进程出现，未观察到 → verified=False（绝不假装成功）。
Phase 13 终审 §10.7：启动应用是副作用动作 → 权限档位 L1_LOW_WRITE（不再是只读 L0）。
"""
from __future__ import annotations

import subprocess
import sys
import time
from typing import Any, Dict

from ..permission import Permission
from ..tool import BaseTool, ToolResult

# 常见别名 → 可执行名
_APPS = {
    "notepad": "notepad", "记事本": "notepad",
    "code": "code", "vscode": "code",
    "chrome": "chrome", "浏览器": "chrome", "msedge": "msedge",
    "calc": "calc", "计算器": "calc", "calculator": "calc",
    "写字板": "write", "cmd": "cmd", "explorer": "explorer",
}

_LAUNCH_VERIFY_TRIES = 15
_LAUNCH_VERIFY_INTERVAL = 0.2   # 最多 ~3s 可观察验证窗口

# FINAL-R1 §6：应用可观察身份别名 —— 启动名 ≠ 最终可观察进程名。
# 例：`calc` 在 Windows 11 上实际进程是 Calculator.exe（UWP/WindowsApps），
# 而"calc.exe"作为 tasklist 过滤名可能观察不到 → 必须按真实身份验证。
_OBSERVABLE_ALIASES = {
    "calc": ("calc.exe", "calculator.exe", "calculatorapp.exe"),
    "chrome": ("chrome.exe",),
    "msedge": ("msedge.exe",),
    "notepad": ("notepad.exe", "notepad++.exe"),
    "code": ("code.exe", "Code.exe", "Microsoft VS Code.exe"),
    "explorer": ("explorer.exe",),
    "write": ("write.exe", "wordpad.exe"),
    "cmd": ("cmd.exe",),
    "winword": ("winword.exe",),
    "excel": ("excel.exe",),
    "powerpnt": ("powerpnt.exe",),
}


def _observe_process(exe: str) -> bool:
    """可观察验证：进程是否真实出现（Windows tasklist；非 Windows 无法观察 → False）。

    按应用的真实可观察身份（别名列表）匹配，绝不假设启动名 == 最终进程名。
    """
    if sys.platform != "win32":
        return False
    names = _OBSERVABLE_ALIASES.get(exe, (f"{exe}.exe",))
    for _ in range(_LAUNCH_VERIFY_TRIES):
        try:
            for name in names:
                r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}"],
                                   capture_output=True, text=True, timeout=1.0)
                if name.lower() in (r.stdout or "").lower():
                    return True
        except Exception:
            return False
        time.sleep(_LAUNCH_VERIFY_INTERVAL)
    return False


class LaunchTool(BaseTool):
    name = "app.launch"
    description = "启动一个本机应用"
    permission = Permission.L1_LOW_WRITE   # 启动应用 = 副作用动作（§10.7）
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    def run(self, name: str) -> ToolResult:
        key = (name or "").strip().lower()
        exe = _APPS.get(key) or _APPS.get(name or "")
        if not exe:
            return ToolResult(False, error=f"未知应用: {name}", verified=False)
        try:
            # 启动；用 shell 让系统解析可执行/别名（Window 下 notepad/code 在 PATH 中）
            subprocess.Popen([exe], shell=True)
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        # §10.4：可观察验证（Popen 成功 ≠ 启动成功）
        if _observe_process(exe):
            return ToolResult(True, data={"launched": name, "process": exe},
                              verified=True, note=f"已启动并确认进程 {exe}")
        return ToolResult(True, data={"launched": name, "process": exe},
                          verified=False, note=f"Popen 成功但未观察到进程 {exe}（不假装启动成功）")
