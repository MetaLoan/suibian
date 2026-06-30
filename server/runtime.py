"""打包(PyInstaller)与开发两种环境下的路径 / 内置二进制解析。"""
import os
import sys
import shutil
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """只读资源目录：打包后是解包临时目录(_MEIPASS)，开发时是项目根。"""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """可写数据目录：打包后是 exe 所在目录，开发时是项目根。"""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bin_path(name: str) -> str:
    """解析外部可执行文件(yt-dlp/ffmpeg/ffprobe)：优先内置 bin/，否则系统 PATH。"""
    exe = name + (".exe" if os.name == "nt" else "")
    if FROZEN:
        p = resource_dir() / "bin" / exe
        if p.exists():
            return str(p)
    return shutil.which(name) or shutil.which(exe) or name
