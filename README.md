# Closetape Desktop for Windows

Windows desktop edition of Closetape ClipMaker. It runs the processing backend locally and uses the computer's CPU, RAM and disk. No Render account or remote backend is required.

## Features
- Desktop window using WebView2.
- Twitch VOD download with yt-dlp.
- Audio peak analysis and MP4/ZIP export with FFmpeg.
- Local files saved in `%LOCALAPPDATA%\\Closetape\\jobs`.
- One active processing task at a time.

## Download the Windows build
1. Open the repository's **Actions** tab.
2. Select **Build Closetape for Windows**.
3. Open the latest successful run.
4. Download the `Closetape-Windows` artifact.
5. Extract the ZIP and launch `Closetape.exe`.

The GitHub Actions workflow downloads and bundles FFmpeg, FFprobe and yt-dlp. WebView2 Runtime is normally available on modern Windows 10/11. If the app cannot open, install Microsoft's Evergreen WebView2 Runtime.

## Local development
Requirements: Windows 10/11 x64, Python 3.11, FFmpeg, FFprobe and yt-dlp in the `tools\\` folder.

```powershell
py -m pip install -r requirements.txt
$env:CLOSETAPE_BIN_DIR="$PWD\\tools"
py desktop_app.py
```

## Important notes
- The first download can take a while and requires free disk space.
- Processing speed depends on the computer; long VODs may take a long time.
- The current moment finder uses audio loudness peaks. It is not semantic AI highlight recognition.
- Speech recognition is optional and is not bundled in this first Windows build.
- Use only VODs you are allowed to download and edit. The app does not ask for Twitch passwords or cookies.
- This is an early build. Test with a short public VOD before processing a multi-hour stream.
