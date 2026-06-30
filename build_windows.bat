@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0

echo ============================================
echo   TK 矩阵备份 - Windows 一键打包
echo ============================================

echo [1/4] 创建虚拟环境并安装依赖...
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail

echo [2/4] 下载内置 yt-dlp ...
if not exist bin mkdir bin
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile bin/yt-dlp.exe"
if errorlevel 1 goto fail

echo [3/4] 下载内置 ffmpeg ...
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile ffmpeg.zip; Expand-Archive ffmpeg.zip -DestinationPath ffmpeg_extract -Force; $d=(Get-ChildItem ffmpeg_extract -Recurse -Filter ffmpeg.exe | Select-Object -First 1).DirectoryName; Copy-Item \"$d/ffmpeg.exe\" bin/ffmpeg.exe -Force; Copy-Item \"$d/ffprobe.exe\" bin/ffprobe.exe -Force"
if errorlevel 1 goto fail

echo [4/4] 打包 ...
pyinstaller desktop.spec --noconfirm
if errorlevel 1 goto fail

echo.
echo ============================================
echo   完成！exe 在  dist\TK-Backup.exe
echo   双击即可运行（首次启动稍慢，自动开浏览器）
echo ============================================
pause
exit /b 0

:fail
echo.
echo 打包失败，请把上面的报错发给我。
pause
exit /b 1
