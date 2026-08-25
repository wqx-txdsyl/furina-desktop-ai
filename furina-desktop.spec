# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— 芙宁娜桌宠一键打包（M8）。

关键：PySide6 是带原生 Qt DLL 的库，必须走 PyInstaller 的 PySide hook（collect_qt data）。
不要用 collect_submodules('furina')（会拉进 tzdata/pywin32 等无关包）。
用法：
    pyinstaller furina-desktop.spec --clean --noconfirm
产物：dist/FurinaDesktop/FurinaDesktop.exe + _internal（含 data/ 素材 + 基座图）。
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

BLOCK_CIPHER = None

# 素材 / 身份锚点数据（data/ 整体打包，基座图已在 data/assets/reference/ 内）
datas = [
    ("data", "data"),
]

# PySide6：让 hook 收集 Qt DLL/插件；cv2/PIL/numpy/httpx/pydantic 走 hook。
hiddenimports = [
    "cv2", "PIL", "numpy", "httpx", "pydantic", "aiohttp",
    "dotenv",
]

a = Analysis(
    ["run_frozen.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "black",
              "PyQt5", "PyQt6", "PySide2", "shiboken2"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=BLOCK_CIPHER,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=BLOCK_CIPHER)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FurinaDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # PySide DLL 用 UPX 可能损坏，保守关掉
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
)

# 单文件模式：把 exe 放进 COLLECT（否则 EXE exclude_binaries 没有内容）。
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FurinaDesktop",
)
