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

from PIL import Image, ImageOps, ImageFilter, ImageDraw, ImageFont

from server.runtime import app_dir, bin_path

APP = app_dir()
DOWNLOAD_DIR = APP / "downloads"
OUTPUT_DIR = APP / "outputs"
TMP = APP / "data" / "tmp"
KEYFRAME_DIR = TMP / "keyframe"
FFMPEG = bin_path("ffmpeg")
FFPROBE = bin_path("ffprobe")

# 画布
W, H = 1080, 1920
HALF = H // 2          # 960，上下各一半
CLIP_SEC = 5           # 第二幕默认时长
UPLOAD_SEC = 2.5       # 第一幕默认「上传」时长
FPS = 30
KF_INNER_W = 288       # 关键帧内容宽度，+ 边框 6*2 = 300


def _new_id() -> str:
    return f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "C:/Windows/Fonts/arialbd.ttf",          # Windows 加粗
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
]


def load_font(size: int):
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    return ImageFont.load_default()


def library(sources: list[str] | None = None) -> list[Path]:
    """视频库 = downloads 下 mp4；sources 给定时只取这些账号文件夹"""
    if sources:
        files: list[Path] = []
        for s in sources:
            base = DOWNLOAD_DIR / s
            if base.is_dir():
                files += [p for p in base.rglob("*.mp4") if p.is_file()]
        return files
    return [p for p in DOWNLOAD_DIR.rglob("*.mp4") if p.is_file()]


def sources() -> list[dict]:
    """downloads 下每个含视频的账号文件夹及其数量"""
    if not DOWNLOAD_DIR.exists():
        return []
    out = []
    for d in sorted(DOWNLOAD_DIR.iterdir()):
        if d.is_dir():
            c = sum(1 for _ in d.rglob("*.mp4"))
            if c:
                out.append({"name": d.name, "count": c})
    return out


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


def has_audio(path: Path) -> bool:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def render_upload_frames(framed_path: Path, out_dir: Path,
                         upload_sec: float = UPLOAD_SEC) -> int:
    """第一幕：黑底 + 居中关键帧 + 0→100% 进度条，逐帧渲染。返回帧数。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    kf = Image.open(framed_path).convert("RGBA")
    fw, fh = kf.size
    cx, cy = W // 2, H // 2
    fx, fy = cx - fw // 2, cy - fh // 2

    bar_w, bar_h = 460, 16
    bx, by = (W - bar_w) // 2, cy + fh // 2 + 64
    font = load_font(46)
    cap_font = load_font(42)

    # 顶部 meme 标题（静态），@OKBOX 用绿色高亮
    cap_a, cap_b = "When I Upload My Girl On ", "@OKBOX"
    cy_cap = fy - 96

    n = max(1, int(round(FPS * upload_sec)))
    for i in range(n):
        prog = min(1.0, (i + 1) / n)
        pct = int(round(prog * 100))
        canvas = Image.new("RGB", (W, H), (8, 9, 13))
        canvas.paste(kf, (fx, fy), kf)
        d = ImageDraw.Draw(canvas)

        wa = d.textlength(cap_a, font=cap_font)
        wb = d.textlength(cap_b, font=cap_font)
        sx = cx - (wa + wb) / 2
        d.text((sx, cy_cap), cap_a, font=cap_font, fill=(255, 255, 255))
        d.text((sx + wa, cy_cap), cap_b, font=cap_font, fill=(25, 211, 162))

        label = f"AI Generating  {pct}%"
        tw = d.textlength(label, font=font)
        d.text((cx - tw / 2, by - 70), label, font=font, fill=(255, 255, 255))

        d.rounded_rectangle([bx, by, bx + bar_w, by + bar_h],
                            radius=bar_h // 2, fill=(40, 44, 60))
        fwid = int(bar_w * prog)
        if fwid > 2:
            d.rounded_rectangle([bx, by, bx + fwid, by + bar_h],
                                radius=bar_h // 2, fill=(25, 211, 162))
        canvas.save(out_dir / f"f_{i:04d}.png")
    return n


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


def build_segments(vids: list[Path], target: float,
                   dur_cache: dict | None = None) -> list[tuple[Path, float, float]]:
    """为一个画面拼出总时长 target 的片段序列 [(视频, 起点, 取多少秒)]。
    单个视频不够 target 就再随机接其他视频，直到凑满。"""
    cache = dur_cache if dur_cache is not None else {}

    def dur(v):
        if v not in cache:
            cache[v] = duration(v)
        return cache[v]

    segs: list[tuple[Path, float, float]] = []
    remaining = target
    guard = 0
    while remaining > 0.1 and guard < 300:
        guard += 1
        v = random.choice(vids)
        d = dur(v)
        if d <= 0.3:
            continue
        take = min(d, remaining)
        start = random.uniform(0, d - take) if d - take > 0.05 else 0.0
        segs.append((v, round(start, 2), round(take, 2)))
        remaining -= take
    if not segs:
        segs.append((random.choice(vids), 0.0, round(target, 2)))
    return segs


def pick_keyframe(sources: list[str] | None = None) -> dict:
    """随机抽一帧（随机视频 ~50% 处），描边存为预览，返回 id 供合成使用。"""
    vids = library(sources)
    if not vids:
        raise RuntimeError("没有可取材的视频")
    KEYFRAME_DIR.mkdir(parents=True, exist_ok=True)
    kf_src = random.choice(vids)
    kdur = duration(kf_src)
    ts = kdur * 0.5 if kdur > 0 else 0
    kid = _new_id()
    raw = KEYFRAME_DIR / f"raw_{kid}.jpg"
    subprocess.run(
        [FFMPEG, "-y", "-ss", f"{ts:.2f}", "-i", str(kf_src),
         "-frames:v", "1", "-q:v", "2", str(raw)],
        capture_output=True, text=True,
    )
    if not raw.exists():
        raise RuntimeError("抽帧失败")
    frame_image(raw, KEYFRAME_DIR / f"{kid}.png")
    raw.unlink(missing_ok=True)
    return {"id": kid, "from": kf_src.parent.name + "/" + kf_src.name}


def frame_uploaded(src_path: Path) -> dict:
    """把用户上传的图片描边存为关键帧，返回 id。"""
    KEYFRAME_DIR.mkdir(parents=True, exist_ok=True)
    kid = _new_id()
    frame_image(src_path, KEYFRAME_DIR / f"{kid}.png")
    return {"id": kid, "from": "(上传)"}


def make_one(idx: int = 0, sources: list[str] | None = None,
             upload_sec: float | None = None, clip_sec: float | None = None,
             layout: str = "vstack", keyframe_id: str | None = None) -> dict:
    upload_sec = min(max(float(upload_sec or UPLOAD_SEC), 0.5), 15)
    clip_sec = min(max(float(clip_sec or CLIP_SEC), 1), 60)
    layout = "hstack" if layout == "hstack" else "vstack"

    vids = library(sources)
    if not vids:
        raise RuntimeError("该账号下没有视频，请先备份或换个取材范围")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(time.time() * 1000)}_{idx}"
    dur_cache: dict = {}

    # 1) 关键帧：自定义（抽取/上传）或随机
    raw_kf = None
    if keyframe_id:
        framed = KEYFRAME_DIR / f"{keyframe_id}.png"
        if not framed.exists():
            raise RuntimeError("指定的关键帧不存在，请重新抽取或上传")
        kf_from = "(自定义)"
        cleanup_framed = False
    else:
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
        kf_from = kf_src.parent.name + "/" + kf_src.name
        cleanup_framed = True

    # 第一幕：上传进度（PIL 逐帧 → 视频）
    p1dir = TMP / f"p1_{stamp}"
    render_upload_frames(framed, p1dir, upload_sec)
    phase1 = TMP / f"phase1_{stamp}.mp4"
    r = subprocess.run(
        [FFMPEG, "-y", "-framerate", str(FPS), "-i", str(p1dir / "f_%04d.png"),
         "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", str(phase1)],
        capture_output=True, text=True,
    )
    if not phase1.exists() or phase1.stat().st_size == 0:
        raise RuntimeError("第一幕渲染失败: " + r.stderr[-400:])

    # 第二幕素材：两个画面各凑满 clip_sec（不够就接其他视频）
    seg_a = build_segments(vids, clip_sec, dur_cache)   # 上 / 左
    seg_b = build_segments(vids, clip_sec, dur_cache)   # 下 / 右

    if layout == "hstack":
        pw, ph, stackf = W // 2, H, "hstack=inputs=2"
    else:
        pw, ph, stackf = W, HALF, "vstack=inputs=2"
    scale = (f"scale={pw}:{ph}:force_original_aspect_ratio=increase,"
             f"crop={pw}:{ph},setsar=1,fps={FPS}")

    out = OUTPUT_DIR / f"remix_{stamp}.mp4"
    cmd = [FFMPEG, "-y", "-i", str(phase1)]              # input 0 = 第一幕
    fc: list[str] = []
    i = 1
    a_idx, b_idx = [], []
    for v, s, t in seg_a:
        cmd += ["-ss", f"{s:.2f}", "-t", f"{t:.2f}", "-i", str(v)]
        a_idx.append(i); i += 1
    for v, s, t in seg_b:
        cmd += ["-ss", f"{s:.2f}", "-t", f"{t:.2f}", "-i", str(v)]
        b_idx.append(i); i += 1
    kf_input = i
    cmd += ["-loop", "1", "-t", f"{clip_sec:.2f}", "-i", str(framed)]; i += 1

    # 两个画面各自缩放→拼接成 clip_sec 长
    for k, j in enumerate(a_idx):
        fc.append(f"[{j}:v]{scale}[a{k}]")
    fc.append("".join(f"[a{k}]" for k in range(len(a_idx)))
              + f"concat=n={len(a_idx)}:v=1:a=0[pa]")
    for k, j in enumerate(b_idx):
        fc.append(f"[{j}:v]{scale}[b{k}]")
    fc.append("".join(f"[b{k}]" for k in range(len(b_idx)))
              + f"concat=n={len(b_idx)}:v=1:a=0[pb]")
    fc.append(f"[pa][pb]{stackf}[stg]")
    fc.append("[stg]fade=t=in:st=0:d=0.4[stf]")
    fc.append(f"[stf][{kf_input}:v]overlay=(W-w)/2:(H-h)/2,"
              f"format=yuv420p,fps={FPS}[p2]")
    fc.append(f"[0:v]format=yuv420p,setsar=1,fps={FPS}[p1]")
    fc.append("[p1][p2]concat=n=2:v=1:a=0[v]")

    # 音频：第一幕静音 + 第二幕上/左画面各段原声拼接（全部有音轨时）
    use_audio = all(has_audio(v) for v, _, _ in seg_a)
    if use_audio:
        sil = i
        cmd += ["-f", "lavfi", "-t", f"{upload_sec:.2f}",
                "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]; i += 1
        afmt = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
        for k, j in enumerate(a_idx):
            fc.append(f"[{j}:a]{afmt},asetpts=PTS-STARTPTS[aa{k}]")
        fc.append("".join(f"[aa{k}]" for k in range(len(a_idx)))
                  + f"concat=n={len(a_idx)}:v=0:a=1[a2]")
        fc.append(f"[{sil}:a]{afmt},asetpts=PTS-STARTPTS[a1]")
        fc.append("[a1][a2]concat=n=2:v=0:a=1[a]")

    cmd += ["-filter_complex", ";".join(fc), "-map", "[v]"]
    if use_audio:
        cmd += ["-map", "[a]", "-c:a", "aac"]
    cmd += ["-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", str(out)]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("合成失败: " + r.stderr[-400:])

    # 清理临时文件（自定义关键帧保留，供批量复用）
    if raw_kf:
        raw_kf.unlink(missing_ok=True)
    if cleanup_framed:
        framed.unlink(missing_ok=True)
    phase1.unlink(missing_ok=True)
    for f in p1dir.glob("*.png"):
        f.unlink(missing_ok=True)
    p1dir.rmdir()

    def label(segs):
        names = []
        for v, _, _ in segs:
            n = v.parent.name + "/" + v.name
            if n not in names:
                names.append(n)
        return names

    return {
        "file": out.name,
        "keyframe_from": kf_from,
        "layout": layout,
        "top": label(seg_a),
        "bottom": label(seg_b),
        "ts": time.time(),
    }


def list_outputs() -> list[dict]:
    if not OUTPUT_DIR.exists():
        return []
    files = sorted(OUTPUT_DIR.glob("remix_*.mp4"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"file": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime}
            for f in files]
