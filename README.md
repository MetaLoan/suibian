# TK 矩阵账号视频全量备份工具

一个本地可视化小工具，用 `yt-dlp` 把 TikTok 矩阵账号的视频全量备份到本地。
浏览器界面管理多账号、实时进度条、增量去重（重复运行只下新视频）。

## 依赖

- `python3`、`yt-dlp`、`ffmpeg`（已确认安装）

## 启动

```bash
./run.sh
```

首次会自动建虚拟环境并装依赖，然后打开 <http://127.0.0.1:8848>。
换端口：`PORT=9000 ./run.sh`

## 用法

1. 右侧「添加账号」：
   - **名称**：作为本地文件夹名（`downloads/<名称>/`）
   - **URL**：账号主页 `https://www.tiktok.com/@用户名`（会抓该号全部视频），或单条视频链接
   - **Cookie**（可选）：从浏览器导出的 `cookies.txt`（Netscape 格式）粘贴进去，用于下载私密/受限内容
   - **额外参数**（可选）：透传给 yt-dlp，例如 `--playlist-end 50`、`--datebefore 20250101`
2. 点「▶ 全部备份」或单个账号的「▶ 备份此号」
3. 实时看进度 / 日志，「📁 打开目录」直接到 Finder

## 机制

- **增量去重**：每个账号一份 `--download-archive`（`data/archive/<id>.txt`），已下过的视频 ID 不再下载，可天天跑只补新视频。
- **存储**：`downloads/<账号名>/<视频ID>.mp4`，只存视频文件。
- **多账号**：顺序处理，避免触发风控；停止后当前账号的已下文件保留。

## 导出 Cookie

浏览器装「Get cookies.txt LOCALLY」之类扩展，登录 TikTok 后导出 `cookies.txt`，把内容粘贴到对应账号的 Cookie 框即可。

## 目录

```
server/app.py     后端（FastAPI + yt-dlp 驱动 + SSE）
web/index.html    前端单页
data/accounts.json  账号配置
data/archive/     去重记录
data/cookies/     各账号 cookie
downloads/        视频输出
```
