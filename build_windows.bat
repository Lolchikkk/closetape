@echo off
setlocal
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist tools mkdir tools
if not exist tools\ffmpeg.exe (
  echo Downloading FFmpeg is handled by the GitHub Actions workflow.
  echo For a local build, put ffmpeg.exe and ffprobe.exe into the tools folder.
  pause
  exit /b 1
)
if not exist tools\ffprobe.exe (
  echo Missing tools\ffprobe.exe
  pause
  exit /b 1
)
python -m PyInstaller --noconfirm --clean --onedir --windowed --name Closetape --add-data "index.html;." --add-data "backend;backend" --add-binary "tools\ffmpeg.exe;tools" --add-binary "tools\ffprobe.exe;tools" desktop_app.py
echo Build complete: dist\Closetape\Closetape.exe
pause
