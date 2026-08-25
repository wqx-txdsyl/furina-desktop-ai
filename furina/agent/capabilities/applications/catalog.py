"""Application Catalog（Phase 14F）—— Windows 应用发现/解析/启动/验证。

- 发现来源：已知 safe aliases、PATH executables、Start Menu shortcuts、App Paths registry、
  常见 Office installed paths；
- **未知 app → 不猜 executable**（reviewer-locked：XYZABC → unable，绝不启动 notepad）；
- 禁止 shell 执行用户任意字符串（只 launch 解析后的 target）；
- launch：resolve → execute → observe real process/window → verified；
  target 存在但不能 verify → UNVERIFIED（不得 COMPLETED）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from furina.agent.permission import Permission
from furina.agent.tool import BaseTool, ToolResult

_LAUNCH_VERIFY_TRIES = 15
_LAUNCH_VERIFY_INTERVAL = 0.2


@dataclass
class ApplicationRecord:
    app_id: str
    display_name: str
    aliases: List[str] = field(default_factory=list)
    launch_target: str = ""
    process_names: List[str] = field(default_factory=list)
    source: str = ""            # alias / PATH / start_menu / app_paths / office_paths
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {"app_id": self.app_id, "display_name": self.display_name,
                "aliases": list(self.aliases), "launch_target": self.launch_target,
                "process_names": list(self.process_names), "source": self.source,
                "confidence": round(self.confidence, 2)}


# 已知 safe aliases（仅解析入口，真实 target 必须被 discover 到）
_KNOWN_ALIASES = {
    "notepad": ("记事本", "notepad", "笔记本"),
    "word": ("word", "winword", "微软word", "office word"),
    "excel": ("excel", "office excel"),
    "powerpoint": ("powerpoint", "ppt", "powerpnt"),
    "vscode": ("vscode", "vs code", "visual studio code", "代码"),
    "chrome": ("chrome", "google chrome", "浏览器", "谷歌浏览器"),
    "edge": ("edge", "msedge", "microsoft edge"),
    "wechat": ("wechat", "微信", "weixin"),
    "dingtalk": ("dingtalk", "钉钉"),
    "spotify": ("spotify", "声田"),
    "calc": ("calc", "计算器", "calculator"),
    "explorer": ("explorer", "文件资源管理器", "资源管理器"),
}

_APP_PATHS_KEYS = {
    "word": ("Winword.exe", "WINWORD.EXE"),
    "excel": ("Excel.exe", "EXCEL.EXE"),
    "powerpoint": ("PowerPnt.exe", "POWERPNT.EXE"),
    "vscode": ("Code.exe",),
    "chrome": ("chrome.exe",),
    "edge": ("msedge.exe",),
    "wechat": ("WeChat.exe", "Weixin.exe"),
    "dingtalk": ("DingTalk.exe",),
    "spotify": ("Spotify.exe",),
}

_OFFICE_ROOT_CANDIDATES = [
    r"C:\Program Files\Microsoft Office",
    r"C:\Program Files (x86)\Microsoft Office",
    r"C:\Program Files\Microsoft Office\root\Office16",
    r"C:\Program Files (x86)\Microsoft Office\root\Office16",
]


class ApplicationCatalog:
    """应用目录：resolve(名称) → ApplicationRecord | None（只返回真实 discover 到的 target）。"""

    def __init__(self) -> None:
        self._records: Dict[str, ApplicationRecord] = {}
        self._load()

    # -------------------------------------------------- discovery
    def _load(self) -> None:
        self._discover_aliases()
        if sys.platform == "win32":
            self._discover_start_menu()
            self._discover_app_paths()
            self._discover_office_paths()

    def _add(self, rec: ApplicationRecord) -> None:
        self._records[rec.app_id] = rec

    def _discover_aliases(self) -> None:
        """PATH 可执行名（真实存在才记录）。"""
        for app_id, aliases in _KNOWN_ALIASES.items():
            target = _which_exe(app_id)
            if target:
                self._add(ApplicationRecord(
                    app_id=app_id, display_name=app_id, aliases=list(aliases),
                    launch_target=target, process_names=[_exe_name(target)],
                    source="PATH", confidence=0.9))

    def _discover_start_menu(self) -> None:
        dirs = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        wanted = {
            "word": ("Word", "WINWORD"),
            "excel": ("Excel",),
            "powerpoint": ("PowerPoint", "POWERPNT"),
            "vscode": ("Visual Studio Code",),
            "chrome": ("Chrome",),
            "edge": ("Edge",),
            "wechat": ("微信", "WeChat"),
            "dingtalk": ("钉钉", "DingTalk"),
            "spotify": ("Spotify",),
        }
        found: Dict[str, str] = {}
        for d in dirs:
            if not d.is_dir():
                continue
            for lnk in d.rglob("*.lnk"):
                name = lnk.stem
                for app_id, keys in wanted.items():
                    if app_id in found:
                        continue
                    if any(k.lower() in name.lower() for k in keys):
                        found[app_id] = str(lnk)
        for app_id, lnk in found.items():
            rec = self._records.get(app_id)
            if rec is None:
                self._add(ApplicationRecord(
                    app_id=app_id, display_name=app_id,
                    aliases=list(_KNOWN_ALIASES.get(app_id, [])),
                    launch_target=lnk, process_names=_default_process_names(app_id),
                    source="start_menu", confidence=0.8))
            elif rec.source in ("PATH", "app_paths"):
                rec.source = "start_menu"   # start menu 更稳（含快捷方式语义）
                rec.launch_target = lnk

    def _discover_app_paths(self) -> None:
        import winreg
        for app_id, exes in _APP_PATHS_KEYS.items():
            if app_id in self._records:
                continue
            for exe in exes:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                        target, _ = winreg.QueryValueEx(k, "")
                    if target and os.path.exists(target):
                        self._add(ApplicationRecord(
                            app_id=app_id, display_name=app_id,
                            aliases=list(_KNOWN_ALIASES.get(app_id, [])),
                            launch_target=target, process_names=[_exe_name(target)],
                            source="app_paths", confidence=0.85))
                        break
                except OSError:
                    pass
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                        target, _ = winreg.QueryValueEx(k, "")
                    if target and os.path.exists(target):
                        self._add(ApplicationRecord(
                            app_id=app_id, display_name=app_id,
                            aliases=list(_KNOWN_ALIASES.get(app_id, [])),
                            launch_target=target, process_names=[_exe_name(target)],
                            source="app_paths", confidence=0.85))
                        break
                except OSError:
                    pass

    def _discover_office_paths(self) -> None:
        for app_id in ("word", "excel", "powerpoint"):
            if app_id in self._records:
                continue
            for root in _OFFICE_ROOT_CANDIDATES:
                r = Path(root)
                exe_name = {"word": "WINWORD.EXE", "excel": "EXCEL.EXE",
                            "powerpoint": "POWERPNT.EXE"}[app_id]
                cand = r / exe_name
                if cand.is_file():
                    self._add(ApplicationRecord(
                        app_id=app_id, display_name=app_id,
                        aliases=list(_KNOWN_ALIASES.get(app_id, [])),
                        launch_target=str(cand), process_names=[exe_name],
                        source="office_paths", confidence=0.7))
                    break

    # -------------------------------------------------- resolve
    def resolve(self, name: str) -> Optional[ApplicationRecord]:
        """名称/别名 → record；**未知 → None（绝不猜 executable）**。"""
        key = (name or "").strip().lower()
        if not key:
            return None
        # 直接 app_id
        if key in self._records:
            return self._records[key]
        # 别名模糊匹配（完整别名命中才收；避免"浏览器"误配）
        for app_id, rec in self._records.items():
            for alias in rec.aliases:
                if alias.lower() == key:
                    return rec
        return None

    def search(self, keyword: str, limit: int = 10) -> List[ApplicationRecord]:
        kw = (keyword or "").lower()
        out = []
        for rec in self._records.values():
            if kw in rec.app_id.lower() or any(kw in a.lower() for a in rec.aliases) \
                    or kw in rec.display_name.lower():
                out.append(rec)
        return out[:limit]

    def all_records(self) -> List[ApplicationRecord]:
        return list(self._records.values())

    def launch(self, name: str, *, timeout: float = 4.0) -> ToolResult:
        """resolve → execute → observe real process → verified。"""
        rec = self.resolve(name)
        if rec is None:
            return ToolResult(False, error=f"未知应用: {name}（不猜 executable）", verified=False)
        try:
            # 只 launch 解析后的 target（start menu .lnk 用 start 语义；exe 直接 Popen）
            if rec.launch_target.lower().endswith(".lnk"):
                subprocess.Popen(["cmd", "/c", "start", "", rec.launch_target], shell=True)
            else:
                subprocess.Popen([rec.launch_target], shell=True)
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        if _observe_process(rec.process_names, timeout=timeout):
            return ToolResult(True, data={"app": rec.app_id, "target": rec.launch_target,
                                          "process": rec.process_names[0]},
                              verified=True, note=f"已启动并确认进程 {rec.process_names[0]}")
        # target 存在但观察不到进程 → UNVERIFIED（不得 COMPLETED）
        return ToolResult(True, data={"app": rec.app_id, "target": rec.launch_target},
                          verified=False, note=f"启动命令已执行但未观察到进程（UNVERIFIED）")


# ================================================================ helpers
def _which_exe(name: str) -> str:
    """PATH 中查找可执行文件（真实存在才返回）。"""
    if sys.platform != "win32":
        import shutil
        return shutil.which(name) or ""
    exts = os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(";")
    for d in os.environ.get("PATH", "").split(";"):
        if not d:
            continue
        p = Path(d) / f"{name}.exe"
        if p.is_file():
            return str(p)
        for ext in exts:
            p2 = Path(d) / (name + ext.lower())
            if p2.is_file():
                return str(p2)
    return ""


def _exe_name(target: str) -> str:
    return os.path.basename(target)


def _default_process_names(app_id: str) -> List[str]:
    m = {
        "word": ["WINWORD.EXE"], "excel": ["EXCEL.EXE"], "powerpoint": ["POWERPNT.EXE"],
        "vscode": ["Code.exe"], "chrome": ["chrome.exe"], "edge": ["msedge.exe"],
        "wechat": ["WeChat.exe", "Weixin.exe"], "dingtalk": ["DingTalk.exe"],
        "spotify": ["Spotify.exe"], "notepad": ["notepad.exe"], "calc": ["calc.exe"],
        "explorer": ["explorer.exe"],
    }
    return m.get(app_id, [f"{app_id}.exe"])


def _observe_process(names: List[str], timeout: float = 4.0) -> bool:
    """可观察验证：进程是否真实出现（Windows tasklist；非 Windows → False）。"""
    if sys.platform != "win32":
        return False
    names = names or []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for name in names:
            try:
                r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}"],
                                   capture_output=True, text=True, timeout=1.0)
                if name.lower() in (r.stdout or "").lower():
                    return True
            except Exception:
                return False
        time.sleep(_LAUNCH_VERIFY_INTERVAL)
    return False


class LaunchFromCatalogTool(BaseTool):
    name = "app.launch"
    description = "通过 ApplicationCatalog 启动应用（解析真实 target；未知应用不猜）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    def __init__(self, catalog: Optional[ApplicationCatalog] = None) -> None:
        self.catalog = catalog or ApplicationCatalog()

    def run(self, name: str) -> ToolResult:
        return self.catalog.launch(name)
