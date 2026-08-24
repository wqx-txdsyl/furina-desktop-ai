"""PyInstaller 冻结运行入口。

源码直接 `python main.py`；打 exe 后入口改为本文件，保证 frozen 下素材/持久化路径正确。

冻结环境约定（onedir 打包，PyInstaller 6.x）：
- 只读素材随 exe 打包在 `sys._MEIPASS/data`（onedir 是 `_internal/data`）。
- 持久化状态（DB/记忆）应在用户可写目录，不落在打包目录里（可能只读/被覆盖）。
部署：首次运行把打包的 data/ 只读素材结构复制到持久目录；之后以该目录为 root。
若 exe 旁已有 `data/assets/manifest.json`（用户自备素材），则直接用 exe 旁目录。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _bundled_data() -> Path:
    """打包进 exe 的只读 data（PyInstaller 6 在 _internal；onefile 在 _MEIPASS 根）。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        # onedir: _MEIPASS = <dist>/FurinaDesktop/_internal → data 在其下
        return base / "data"
    return Path(sys.executable).resolve().parent / "data"


def _user_data_dir() -> Path:
    """持久化根：用户可写、跨启动保留。优先 exe 旁 data；否则 %APPDATA%/Furina。"""
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Furina"


def main() -> int:
    bundled = _bundled_data()
    # 1) exe 旁已有 data/（用户自备/替换素材）→ 直接用它作为 root
    exe_data = Path(sys.executable).resolve().parent / "data"
    if exe_data.exists() and (exe_data / "assets" / "manifest.json").exists():
        os.environ["FURINA_ROOT"] = str(exe_data.parent)  # root = exe_dir（data/ 是 root/data）
    else:
        # 2) 用持久用户目录；首次把打包的 data/ 只读素材复制过去
        root = _user_data_dir()
        root.mkdir(parents=True, exist_ok=True)
        target = root / "data" / "assets"
        if bundled.exists() and not target.exists():
            shutil.copytree(bundled, root / "data", dirs_exist_ok=True)
        os.environ["FURINA_ROOT"] = str(root)

    from furina.app import run
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
