"""应用启动工具（plan/5 §10-11）。

用 subprocess 启动本机应用（记事本/浏览器/编辑器等）。
骨架只做“启动并确认进程”，不注入真实 UI（后续接 UI Automation）。
"""
from __future__ import annotations

import subprocess
from typing import Any, Dict

from ..permission import Permission
from ..tool import BaseTool, ToolResult

# 常见别名 → 可执行名
_APPS = {
    "notepad": "notepad", "记事本": "notepad",
    "code": "code", "vscode": "code",
    "chrome": "chrome", "浏览器": "chrome", "msedge": "msedge",
    "calc": "calc", "写字板": "write", "cmd": "cmd", "explorer": "explorer",
}


class LaunchTool(BaseTool):
    name = "app.launch"
    description = "启动一个本机应用"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    def run(self, name: str) -> ToolResult:
        key = (name or "").strip().lower()
        exe = _APPS.get(key) or _APPS.get(name or "")
        if not exe:
            return ToolResult(False, error=f"未知应用: {name}", verified=False)
        try:
            # 启动；用 shell 让系统解析可执行/别名（Window 下 notepad/code 在 PATH 中）
            subprocess.Popen([exe], shell=True)
            return ToolResult(True, data={"launched": name}, verified=True, note=f"已启动 {exe}")
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
