"""
二次创作合成模块
- 从视频库随机抽帧 + 上下两段 5 秒视频，合成竖屏 1080x1920 短片
- 中间贴一张关键帧（约 50% 位置），白色细边 + 阴影，居中
"""
import json
import random
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageOps, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = ROOT / "downloads"
OUTPUT_DIR = ROOT / "outputs"
TMP = ROOT / "data" / "tmp"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

# 画布
W, H = 1080, 1920
HALF = H // 2          # 960，上下各一半
CLIP_SEC = 5           # 每段时长
KF_INNER_W = 288       # 关键帧内容宽度，+ 边框 6*2 = 300


def library() -> list[Path]:
    """视频库 = downloads 下所有 mp4"""
    return [p for p in DOWNLOAD_DIR.rglob("*.mp4") if p.is_file()]


def duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def frame_image(src: Path, dst: Path,
                inner_w: int = KF_INNER_W, border: int = 6,
                shadow_blur: int = 14, shadow_offset: int = 10,
                shadow_alpha: int = 150) -> None:
    """给关键帧加白色细边 + 投影，输出居中可叠加的 RGBA PNG"""
    im = Image.open(src).convert("RGB")
    w, h = im.size
    inner_h = max(1, round(h * inner_w / w))
    im = im.resize((inner_w, inner_h))
    framed = ImageOps.expand(im, border=border, fill="white").convert("RGBA")
    fw, fh = framed.size

    margin = shadow_blur * 2 + shadow_offset
    canvas = Image.new("RGBA", (fw + 2 * margin, fh + 2 * margin), (0, 0, 0, 0))

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    rect = Image.new("RGBA", (fw, fh), (0, 0, 0, shadow_alpha))
    shadow.paste(rect, (margin + shadow_offset, margin + shadow_offset))
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    canvas = Image.alpha_composite(canvas, shadow)

    # 画框居中贴在画布中心 → 叠加时即以画框为中心
    canvas.alpha_composite(framed, (margin, margin))
    canvas.save(dst)


def pick_clips(vids: list[Path], n: int = 2) -> list[tuple[Path, float]]:
    """随机挑 n 段时长 >= CLIP_SEC 的视频；不够则重复使用"""
    pool = vids[:]
    random.shuffle(pool)
    chosen: list[tuple[Path, float]] = []
    for v in pool:
        d = duration(v)
        if d >= CLIP_SEC:
            chosen.append((v, d))
        if len(chosen) >= n:
            break
    if not chosen:                       # 库里全是短视频，退而求其次
        for v in pool:
            chosen.append((v, max(duration(v), CLIP_SEC)))
            if len(chosen) >= n:
                break
    while len(chosen) < n and chosen:    # 数量不足则重复
        chosen.append(random.choice(chosen))
    return chosen[:n]


def make_one(idx: int = 0) -> dict:
    vids = library()
    if not vids:
        raise RuntimeError("视频库为空，请先备份一些视频")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(time.time() * 1000)}_{idx}"

    # 1) 关键帧（随机视频 ~50% 处）
    kf_src = random.choice(vids)
    kdur = duration(kf_src)
    ts = kdur * 0.5 if kdur > 0 else 0
    raw_kf = TMP / f"kf_{stamp}.jpg"
    r = subprocess.run(
        [FFMPEG, "-y", "-ss", f"{ts:.2f}", "-i", str(kf_src),
         "-frames:v", "1", "-q:v", "2", str(raw_kf)],
        capture_output=True, text=True,
    )
    if not raw_kf.exists():
        raise RuntimeError("抽帧失败: " + r.stderr[-300:])
    framed = TMP / f"frame_{stamp}.png"
    frame_image(raw_kf, framed)

    # 2) 上下两段 5 秒
    clips = pick_clips(vids, 2)
    (top, tdur), (bot, bdur) = clips[0], clips[1]
    ts_top = random.uniform(0, max(0, tdur - CLIP_SEC))
    ts_bot = random.uniform(0, max(0, bdur - CLIP_SEC))

    out = OUTPUT_DIR / f"remix_{stamp}.mp4"
    fc = (
        f"[0:v]scale={W}:{HALF}:force_original_aspect_ratio=increase,"
        f"crop={W}:{HALF},setsar=1[t];"
        f"[1:v]scale={W}:{HALF}:force_original_aspect_ratio=increase,"
        f"crop={W}:{HALF},setsar=1[b];"
        f"[t][b]vstack=inputs=2[bg];"
        f"[bg][2:v]overlay=(W-w)/2:(H-h)/2[v]"
    )
    cmd = [
        FFMPEG, "-y",
        "-ss", f"{ts_top:.2f}", "-t", str(CLIP_SEC), "-i", str(top),
        "-ss", f"{ts_bot:.2f}", "-t", str(CLIP_SEC), "-i", str(bot),
        "-i", str(framed),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-t", str(CLIP_SEC), "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("合成失败: " + r.stderr[-400:])

    # 清理临时文件
    for p in (raw_kf, framed):
        p.unlink(missing_ok=True)

    return {
        "file": out.name,
        "keyframe_from": kf_src.parent.name + "/" + kf_src.name,
        "top": top.parent.name + "/" + top.name,
        "bottom": bot.parent.name + "/" + bot.name,
        "ts": time.time(),
    }


def list_outputs() -> list[dict]:
    if not OUTPUT_DIR.exists():
        return []
    files = sorted(OUTPUT_DIR.glob("remix_*.mp4"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"file": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime}
            for f in files]
