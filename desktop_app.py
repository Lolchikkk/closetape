import os, sys, socket, threading, time
from pathlib import Path

def resource_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name

def main():
    appdata = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Closetape"
    appdata.mkdir(parents=True, exist_ok=True)
    os.environ["DATA_DIR"] = str(appdata / "jobs")
    os.environ["CLOSETAPE_DESKTOP"] = "1"
    tools_dir = resource_path("tools")
    if tools_dir.exists():
        os.environ["CLOSETAPE_BIN_DIR"] = str(tools_dir)
        os.environ["PATH"] = str(tools_dir) + os.pathsep + os.environ.get("PATH", "")

    import uvicorn
    import webview
    from backend.main import app

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    webview.create_window("Closetape", f"http://127.0.0.1:{port}", width=1180, height=820, min_size=(820, 620), background_color="#090b10")
    try:
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=5)

if __name__ == "__main__":
    main()
