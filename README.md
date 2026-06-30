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

## 二次创作（合成短片）

界面下方「🎬 二次创作」面板，从已备份的视频库随机合成竖屏短片，分两幕编排：

- **第一幕（约 2.5 秒）**：黑底，只有中间那张关键帧（随机视频 50% 处抽帧，**白色细边 + 阴影**，约 **300px 宽**），下方进度条 **Uploading 0→100%** 计数。
- **第二幕（5 秒）**：进度到 100% 后，随机取 **2 段视频各抽 5 秒**，上下叠加淡入铺满竖屏（1080×1920），关键帧继续居中。

成品存到 `outputs/`，界面里直接预览 / 下载。填「数量」可一次批量生成多个（每个都随机，互不相同）。

可自定义配置：

- **拼接方式**：上下拼 或 左右拼
- **第一幕时长**（0.5–15 秒）、**第二幕时长**（1–60 秒）
- **第二幕自动凑时长**：选定的视频不够长时，自动接其他视频片段直到凑满目标时长
- **中间关键帧**：默认每个成品随机抽帧；也可点「🎲 抽取/重抽」预览，不满意一直换，直到满意；或「📁 上传图片」用自己的图（都会自动描白边+阴影）

## 机制

- **增量去重**：每个账号一份 `--download-archive`（`data/archive/<id>.txt`），已下过的视频 ID 不再下载，可天天跑只补新视频。
- **存储**：`downloads/<账号名>/<视频ID>.mp4`，只存视频文件。
- **多账号**：顺序处理，避免触发风控；停止后当前账号的已下文件保留。

## 打包成 Windows 单文件 exe（零安装）

成品是一个 `TK-Backup.exe`，**双击即用**，yt-dlp 和 ffmpeg 已内置，目标电脑无需装任何东西。
> ⚠️ Windows 的 `.exe` 只能在 Windows 上构建，Mac 打不出来。两种方式任选其一：

### 方式 A：GitHub Actions 云端打包（无需 Windows 机器）

1. 把仓库推到 GitHub
2. 仓库页 → **Actions** → 选 **build-windows** → **Run workflow**（或打个 `v1.0` 的 tag 自动触发）
3. 跑完在该次运行的 **Artifacts** 里下载 `TK-Backup-windows`，解压得到 `TK-Backup.exe`

### 方式 B：在 Windows 上本地一键打包

把项目拷到 Windows，装好 [Python 3.12+](https://www.python.org/downloads/)，双击运行 **`build_windows.bat`**。
脚本自动建环境、下载内置 yt-dlp/ffmpeg、打包，产物在 `dist\TK-Backup.exe`。

### exe 运行说明

- 双击后弹出一个黑色命令行窗口（服务），并自动打开浏览器；**关掉窗口即退出**。
- `downloads/`、`outputs/`、`data/` 会生成在 **exe 同目录**下，放哪跑就存哪。
- 首次启动稍慢（自解压），之后正常。

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
