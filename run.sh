#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "首次运行，创建虚拟环境..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

# 自动更新 yt-dlp（可选，注释掉可加快启动）
# ./.venv/bin/pip install -q -U yt-dlp 2>/dev/null || true

PORT="${PORT:-8848}"
echo "============================================"
echo "  TK 矩阵备份  →  http://127.0.0.1:$PORT"
echo "  下载目录: $(pwd)/downloads"
echo "============================================"
exec ./.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port "$PORT"
