"""自动更新：启动时查 GitHub 最新 Release，有新版就下载替换并重启。

仅在打包后的 Windows exe 下生效；开发/Mac 直接跳过。
仓库为公开仓，查询与下载均无需登录。
"""
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

from server.runtime import FROZEN
from server.version import __version__

REPO = "MetaLoan/suibian"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
_HEADERS = {"User-Agent": "TK-Backup-Updater", "Accept": "application/vnd.github+json"}
# 用 certifi 的 CA，避免依赖系统证书库（更新会执行下载的代码，必须校验证书）
_SSL = ssl.create_default_context(cafile=certifi.where())


def current_version() -> str:
    return __version__


def should_check() -> bool:
    """只在 Windows 打包版下自动更新（dev/Mac 跳过）。"""
    return FROZEN and os.name == "nt" and __version__ != "dev"


def _parse(v: str) -> tuple:
    parts = []
    for p in v.lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    try:
        return _parse(latest) > _parse(current)
    except Exception:
        return latest != current


def check_latest(timeout: float = 6.0) -> dict | None:
    """返回 {version, asset_url}；失败/无 exe 资产时返回 None。"""
    req = urllib.request.Request(API, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = data.get("tag_name") or ""
    asset = next((a for a in data.get("assets", [])
                  if a.get("name", "").lower().endswith(".exe")), None)
    if not tag or not asset:
        return None
    return {"version": tag, "asset_url": asset["browser_download_url"]}


def _download(url: str, dst: Path, timeout: float = 120.0):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r, open(dst, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def apply_update(asset_url: str) -> bool:
    """下载新 exe，写一个等待-替换-重启的 bat 并分离启动；调用方随后应退出本进程。"""
    exe = Path(sys.executable)
    d = exe.parent
    new_exe = d / (exe.stem + "-new" + exe.suffix)
    _download(asset_url, new_exe)
    if not new_exe.exists() or new_exe.stat().st_size == 0:
        return False

    bat = d / "_update.bat"
    bat.write_text(
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        ":retry\r\n"
        f'move /Y "{new_exe.name}" "{exe.name}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto retry\r\n"
        ")\r\n"
        f'start "" "{exe.name}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    import subprocess
    DETACHED = 0x00000008  # DETACHED_PROCESS
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(d),
                     creationflags=DETACHED, close_fds=True)
    return True


def maybe_update() -> bool:
    """检查并（如有新版）应用更新。返回 True 表示已启动更新、调用方应退出。"""
    if not should_check():
        return False
    try:
        info = check_latest()
    except Exception as e:  # 离线/超时等，直接照常启动
        print(f"[更新] 检查跳过：{e}")
        return False
    if not info or not is_newer(info["version"], __version__):
        return False
    print(f"[更新] 发现新版本 {info['version']}（当前 {__version__}），正在下载…")
    try:
        if apply_update(info["asset_url"]):
            print("[更新] 已下载，正在重启到新版本…")
            return True
    except Exception as e:
        print(f"[更新] 失败，将以当前版本启动：{e}")
    return False
