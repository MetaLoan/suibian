# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules

# 内置二进制（存在才打进去；Windows 构建时由脚本/CI 预先放到 bin/ ）
binaries = []
for f in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe",
          "yt-dlp", "ffmpeg", "ffprobe"):
    p = os.path.join("bin", f)
    if os.path.exists(p):
        binaries.append((p, "bin"))

hiddenimports = collect_submodules("uvicorn")

a = Analysis(
    ["desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=[("web", "web")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TK-Backup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
)
