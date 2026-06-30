"""打包入口：启动本地服务并自动打开浏览器。"""
import socket
import threading
import time
import webbrowser

import uvicorn

from server.app import app


def _free_port(preferred: int = 8848) -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", preferred))
        s.close()
        return preferred
    except OSError:
        s.close()
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.bind(("127.0.0.1", 0))
        port = s2.getsockname()[1]
        s2.close()
        return port


def main():
    port = _free_port(8848)
    url = f"http://127.0.0.1:{port}"

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    print("=" * 48)
    print(f"  TK 矩阵备份已启动 →  {url}")
    print("  关闭此窗口即退出程序。")
    print("=" * 48)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
