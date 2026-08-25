"""应用启动工具（legacy-plan/5 §10-11）。

Phase 14.1 §4：production `app.launch` **必须**经 `ApplicationCatalog` 解析真实 target
（alias/PATH/Start Menu/App Paths/Office 发现），不得以 `_APPS` 固定字典作为唯一 resolver。
- known safe aliases 保留为 Catalog seed 数据（_APPS 仅供说明/兼容查看，不再作唯一解析器）；
- 未知应用 → unable（绝不猜 executable，绝不启动 notepad）；
- 禁止 shell 执行用户任意字符串（只 launch 解析后的 target）。
Phase 13 终审 §10.4：可观察验证 —— Popen 成功 ≠ 启动成功（tasklist 轮询确认进程）。
"""
from __future__ import annotations

import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Union

from ..permission import Permission
from ..tool import BaseTool, ToolResult

# 已知 safe aliases（Catalog seed 说明；production resolver = ApplicationCatalog）
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


def _observe_process(exe: Union[str, List[str]]) -> bool:
    """可观察验证：进程是否真实出现（Windows tasklist；非 Windows 无法观察 → False）。

    兼容两种入参：str（按 _OBSERVABLE_ALIASES 解析）或 List[str]（显式进程名列表，
    ApplicationCatalog record.process_names 直接消费）。
    """
    if sys.platform != "win32":
        return False
    if isinstance(exe, str):
        names = _OBSERVABLE_ALIASES.get(exe, (f"{exe}.exe",))
    else:
        names = list(exe) or [f"{exe}.exe"]
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
    description = "启动一个本机应用（经 ApplicationCatalog 解析真实 target；未知应用不猜）"
    permission = Permission.L1_LOW_WRITE   # 启动应用 = 副作用动作（§10.7）
    schema = {"type": "object", "properties": {"name": {"type": "string"}},
              "required": ["name"]}

    def __init__(self, catalog=None) -> None:
        # Phase 14.1 §4：production resolver = ApplicationCatalog（真实发现 + 未知不猜）
        from furina.agent.capabilities.applications import ApplicationCatalog
        self.catalog = catalog or ApplicationCatalog()

    def run(self, name: str) -> ToolResult:
        rec = self.catalog.resolve(name)
        if rec is None:
            return ToolResult(False, error=f"未知应用: {name}（不猜 executable，不启动）",
                              verified=False)
        target = rec.launch_target
        try:
            # 只 launch 解析后的 target（.lnk 用 start 语义；exe 直接 Popen）；禁止 shell 任意字符串
            if str(target).lower().endswith(".lnk"):
                subprocess.Popen(["cmd", "/c", "start", "", target], shell=True)
            else:
                subprocess.Popen([target], shell=True)
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        # §10.4：可观察验证（Popen 成功 ≠ 启动成功）
        if _observe_process(rec.process_names or [_exe_name(target)]):
            return ToolResult(True, data={"launched": name, "target": target,
                                          "process": (rec.process_names or [_exe_name(target)])[0]},
                              verified=True, note=f"已启动并确认进程 {rec.app_id}")
        return ToolResult(True, data={"launched": name, "target": target},
                          verified=False, note=f"Popen 成功但未观察到进程（UNVERIFIED）")


def _exe_name(target: str) -> str:
    import os
    return os.path.basename(str(target))
