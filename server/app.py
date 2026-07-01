"""
TK 矩阵账号视频全量备份工具 — 后端
- 用子进程驱动 yt-dlp
- SSE 实时推送进度 / 日志
- --download-archive 实现增量去重
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server import compose
from server.runtime import resource_dir, app_dir, bin_path

APP = app_dir()                 # 可写数据根（打包后 = exe 所在目录）
WEB = resource_dir() / "web"    # 只读前端资源
DATA = APP / "data"
ARCHIVE_DIR = DATA / "archive"
COOKIE_DIR = DATA / "cookies"
DOWNLOAD_DIR = APP / "downloads"
OUTPUT_DIR = APP / "outputs"
KEYFRAME_DIR = DATA / "tmp" / "keyframe"
ACCOUNTS_FILE = DATA / "accounts.json"

for d in (DATA, ARCHIVE_DIR, COOKIE_DIR, DOWNLOAD_DIR, OUTPUT_DIR, KEYFRAME_DIR):
    d.mkdir(parents=True, exist_ok=True)

YTDLP = bin_path("yt-dlp")
_FFMPEG_BIN = bin_path("ffmpeg")
FFMPEG_DIR = str(Path(_FFMPEG_BIN).parent) if Path(_FFMPEG_BIN).exists() else None

app = FastAPI(title="TK Backup")
# 本地工具，允许跨源（便于在嵌入式预览面板里也能访问后端）
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------- 账号存储 -----------------------------
def load_accounts() -> list[dict]:
    if ACCOUNTS_FILE.exists():
        return json.loads(ACCOUNTS_FILE.read_text("utf-8"))
    return []


def save_accounts(accounts: list[dict]) -> None:
    ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), "utf-8")


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w\-.@]+", "_", s.strip())
    return s.strip("_") or "account"


# ----------------------------- 运行时状态 -----------------------------
class Hub:
    """SSE 广播中心 + 备份任务状态机"""

    def __init__(self):
        self.subscribers: set[asyncio.Queue] = set()
        self.running = False
        self.stop_flag = False
        self.queue: list[str] = []          # 待处理账号 id
        self.current: str | None = None     # 当前账号 id
        self.proc: asyncio.subprocess.Process | None = None
        self.stats: dict[str, dict] = {}    # account_id -> {downloaded, item, total, pct, state, last}

    async def publish(self, event: dict):
        event.setdefault("ts", time.time())
        dead = []
        for q in self.subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.subscribers.discard(q)

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "current": self.current,
            "queue": list(self.queue),
            "stats": self.stats,
        }


hub = Hub()


# ----------------------------- yt-dlp 解析 -----------------------------
# status|id|percent|speed|eta|title
PROG_RE = re.compile(r"^PROG\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*?)\|(.*)$")
ITEM_RE = re.compile(r"Downloading item (\d+) of (\d+)")
ARCHIVED_RE = re.compile(r"has already been (recorded in the archive|downloaded)")


def build_cmd(acc: dict) -> list[str]:
    folder = safe_name(acc["name"])
    out_path = DOWNLOAD_DIR / folder
    archive = ARCHIVE_DIR / f"{acc['id']}.txt"
    cmd = [
        YTDLP,
        acc["url"],
        "--paths", str(out_path),
        "-o", "%(id)s.%(ext)s",
        "--download-archive", str(archive),
        "--no-overwrites",
        "--ignore-errors",
        "--no-warnings",
        "--newline",                     # 进度逐行输出，便于解析
        "--progress-template",
        "PROG|%(progress.status)s|%(info.id)s|%(progress._percent_str)s|"
        "%(progress._speed_str)s|%(progress._eta_str)s|%(info.title).50s",
    ]
    if FFMPEG_DIR:                       # 让 yt-dlp 用到（内置的）ffmpeg
        cmd += ["--ffmpeg-location", FFMPEG_DIR]
    cookie = COOKIE_DIR / f"{acc['id']}.txt"
    if cookie.exists() and cookie.stat().st_size > 0:
        cmd += ["--cookies", str(cookie)]
    extra = (acc.get("extra_args") or "").strip()
    if extra:
        cmd += extra.split()
    return cmd


async def run_account(acc: dict):
    aid = acc["id"]
    st = hub.stats.setdefault(aid, {})
    st.update({"state": "running", "item": 0, "total": 0, "pct": "", "last": "", "downloaded_session": 0})
    seen_done: set[str] = set()
    await hub.publish({"type": "account_start", "id": aid, "name": acc["name"]})

    cmd = build_cmd(acc)
    await hub.publish({"type": "log", "id": aid, "line": "$ " + " ".join(cmd)})

    hub.proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert hub.proc.stdout
    async for raw in hub.proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if not line:
            continue

        m = PROG_RE.match(line)
        if m:
            status, vid, pct, speed, eta, title = (g.strip() for g in m.groups())
            if status == "finished":
                if vid and vid not in seen_done:
                    seen_done.add(vid)
                    st["downloaded_session"] = st.get("downloaded_session", 0) + 1
                    st["last"] = title
                    await hub.publish({"type": "done_one", "id": aid, "vid": vid,
                                       "title": title or vid,
                                       "count": st["downloaded_session"]})
            else:
                st.update({"pct": pct, "speed": speed, "eta": eta, "current_vid": vid})
                await hub.publish({"type": "progress", "id": aid, "vid": vid,
                                   "pct": pct, "speed": speed, "eta": eta,
                                   "item": st.get("item", 0), "total": st.get("total", 0)})
            continue

        m = ITEM_RE.search(line)
        if m:
            st["item"], st["total"] = int(m.group(1)), int(m.group(2))
            await hub.publish({"type": "item", "id": aid,
                               "item": st["item"], "total": st["total"]})
            continue

        if ARCHIVED_RE.search(line):
            await hub.publish({"type": "skip", "id": aid})
            continue

        # 其它日志（错误 / 提示）
        await hub.publish({"type": "log", "id": aid, "line": line})

    code = await hub.proc.wait()
    hub.proc = None
    st["state"] = "stopped" if hub.stop_flag else ("error" if code else "done")
    await hub.publish({"type": "account_end", "id": aid, "code": code,
                       "downloaded": st.get("downloaded_session", 0), "state": st["state"]})


async def worker():
    hub.running = True
    hub.stop_flag = False
    await hub.publish({"type": "run_start"})
    try:
        while hub.queue and not hub.stop_flag:
            aid = hub.queue.pop(0)
            acc = next((a for a in load_accounts() if a["id"] == aid), None)
            if not acc:
                continue
            hub.current = aid
            await hub.publish({"type": "state", **hub.snapshot()})
            try:
                await run_account(acc)
            except Exception as e:  # noqa
                await hub.publish({"type": "log", "id": aid, "line": f"[内部错误] {e}"})
    finally:
        hub.running = False
        hub.current = None
        await hub.publish({"type": "run_end", **hub.snapshot()})


# ----------------------------- 数据模型 -----------------------------
class AccountIn(BaseModel):
    name: str
    url: str
    cookies: str | None = None
    extra_args: str | None = None


class StartIn(BaseModel):
    ids: list[str] | None = None


class ComposeIn(BaseModel):
    count: int = 1
    sources: list[str] | None = None
    upload_sec: float | None = None
    clip_sec: float | None = None
    layout: str = "vstack"
    keyframe_id: str | None = None
    kf_opacity: float = 50
    kf_w1: float = 28          # 中间图宽度占输出宽度的百分比
    kf_w2: float = 28
    bg_mode: str = "black"
    cap_prefix: str | None = None
    cap_highlight: str | None = None
    gen_label: str | None = None
    out_w: int = 1080
    out_h: int = 1920
    kf_radius: float = 0


class PickIn(BaseModel):
    sources: list[str] | None = None
    radius: float = 0


# ----------------------------- API -----------------------------
@app.get("/api/accounts")
def api_accounts():
    accounts = load_accounts()
    for a in accounts:
        a["has_cookie"] = (COOKIE_DIR / f"{a['id']}.txt").exists()
        a["archived"] = count_archive(a["id"])
        a["files"] = count_files(a["name"])
    return accounts


def count_archive(aid: str) -> int:
    p = ARCHIVE_DIR / f"{aid}.txt"
    if not p.exists():
        return 0
    return sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))


def count_files(name: str) -> int:
    folder = DOWNLOAD_DIR / safe_name(name)
    if not folder.exists():
        return 0
    return sum(1 for f in folder.iterdir() if f.is_file() and not f.name.endswith(".part"))


@app.post("/api/accounts")
def api_add(acc: AccountIn):
    if not acc.url.strip():
        raise HTTPException(400, "URL 不能为空")
    accounts = load_accounts()
    aid = uuid.uuid4().hex[:8]
    rec = {"id": aid, "name": acc.name.strip() or acc.url.strip(),
           "url": acc.url.strip(), "extra_args": (acc.extra_args or "").strip()}
    accounts.append(rec)
    save_accounts(accounts)
    if acc.cookies and acc.cookies.strip():
        (COOKIE_DIR / f"{aid}.txt").write_text(acc.cookies, "utf-8")
    return rec


@app.put("/api/accounts/{aid}")
def api_update(aid: str, acc: AccountIn):
    accounts = load_accounts()
    rec = next((a for a in accounts if a["id"] == aid), None)
    if not rec:
        raise HTTPException(404, "账号不存在")
    rec["name"] = acc.name.strip() or rec["name"]
    rec["url"] = acc.url.strip() or rec["url"]
    rec["extra_args"] = (acc.extra_args or "").strip()
    save_accounts(accounts)
    if acc.cookies is not None:
        cookie_path = COOKIE_DIR / f"{aid}.txt"
        if acc.cookies.strip():
            cookie_path.write_text(acc.cookies, "utf-8")
        elif cookie_path.exists():
            cookie_path.unlink()
    return rec


@app.delete("/api/accounts/{aid}")
def api_delete(aid: str):
    accounts = load_accounts()
    accounts = [a for a in accounts if a["id"] != aid]
    save_accounts(accounts)
    for p in (COOKIE_DIR / f"{aid}.txt", ARCHIVE_DIR / f"{aid}.txt"):
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.post("/api/backup/start")
async def api_start(body: StartIn):
    if hub.running:
        raise HTTPException(409, "已有备份任务在运行")
    accounts = load_accounts()
    ids = body.ids or [a["id"] for a in accounts]
    ids = [i for i in ids if any(a["id"] == i for a in accounts)]
    if not ids:
        raise HTTPException(400, "没有可备份的账号")
    hub.queue = ids
    for i in ids:
        hub.stats.setdefault(i, {})["state"] = "queued"
    asyncio.create_task(worker())
    return {"ok": True, "queued": ids}


def _kill_tree(proc):
    """结束子进程及其所有子孙进程（Windows 下 yt-dlp.exe 会再 fork 子进程）。"""
    if proc is None or proc.returncode is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        pass


@app.post("/api/backup/stop")
async def api_stop():
    hub.stop_flag = True
    hub.queue = []
    _kill_tree(hub.proc)
    return {"ok": True}


@app.get("/api/state")
def api_state():
    return hub.snapshot()


@app.get("/api/events")
async def api_events(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    hub.subscribers.add(q)

    async def gen():
        # 首包：当前快照
        yield f"data: {json.dumps({'type': 'state', **hub.snapshot()})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            hub.subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/open")
def api_open(name: str):
    """在 Finder 中打开账号的下载目录"""
    folder = DOWNLOAD_DIR / safe_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        os.system(f'open "{folder}"')
    elif os.name == "nt":
        os.startfile(str(folder))  # type: ignore[attr-defined]
    else:
        os.system(f'xdg-open "{folder}"')
    return {"ok": True, "path": str(folder)}


# ----------------------------- 二次创作 -----------------------------
@app.get("/api/library")
def api_library(source: str | None = None):
    srcs = [source] if source else None
    return {"count": len(compose.library(srcs))}


@app.get("/api/sources")
def api_sources():
    return compose.sources()


@app.get("/api/outputs")
def api_outputs():
    return compose.list_outputs()


@app.post("/api/compose")
async def api_compose(body: ComposeIn):
    if not compose.library(body.sources):
        raise HTTPException(400, "该账号下没有视频，请先备份或换个取材范围")
    n = max(1, min(body.count, 20))
    results = []
    await hub.publish({"type": "compose_start", "count": n})
    for i in range(n):
        try:
            r = await asyncio.to_thread(
                compose.make_one, i, body.sources,
                body.upload_sec, body.clip_sec, body.layout, body.keyframe_id,
                body.kf_opacity,
                kf_w1=body.kf_w1, kf_w2=body.kf_w2, bg_mode=body.bg_mode,
                cap_prefix=body.cap_prefix, cap_highlight=body.cap_highlight,
                gen_label=body.gen_label,
                out_w=body.out_w, out_h=body.out_h, kf_radius=body.kf_radius)
            results.append(r)
            await hub.publish({"type": "compose_done", **r, "index": i, "total": n})
        except Exception as e:  # noqa
            await hub.publish({"type": "log", "id": "compose", "line": f"[合成失败] {e}"})
    await hub.publish({"type": "compose_end", "made": len(results)})
    return {"ok": True, "results": results}


@app.post("/api/keyframe/pick")
async def api_keyframe_pick(body: PickIn):
    try:
        r = await asyncio.to_thread(compose.pick_keyframe, body.sources, body.radius)
    except Exception as e:  # noqa
        raise HTTPException(400, str(e))
    return {**r, "url": f"/keyframe/{r['id']}.png"}


@app.post("/api/keyframe/upload")
async def api_keyframe_upload(file: UploadFile = File(...), radius: float = 0):
    tmp = KEYFRAME_DIR / f"up_{file.filename}"
    data = await file.read()
    tmp.write_bytes(data)
    try:
        r = await asyncio.to_thread(compose.frame_uploaded, tmp, radius)
    except Exception as e:  # noqa
        raise HTTPException(400, f"图片处理失败: {e}")
    finally:
        tmp.unlink(missing_ok=True)
    return {**r, "url": f"/keyframe/{r['id']}.png"}


@app.delete("/api/outputs/{name}")
def api_delete_output(name: str):
    p = OUTPUT_DIR / Path(name).name
    if p.exists() and p.suffix == ".mp4":
        p.unlink()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
app.mount("/keyframe", StaticFiles(directory=KEYFRAME_DIR), name="keyframe")
app.mount("/", StaticFiles(directory=WEB), name="web")
