"""
PyInstaller entry point.
Runs `key-rotator serve` and opens the browser automatically.
"""
import sys
import os
import threading
import time
import webbrowser

# When bundled, add the _MEIPASS directory to sys.path so imports work
if getattr(sys, "frozen", False):
    sys.path.insert(0, sys._MEIPASS)

from rotator.cli import cli

def _open_browser(url: str, delay: float = 1.5) -> None:
    time.sleep(delay)
    webbrowser.open(url)

if __name__ == "__main__":
    # If launched by double-click (no args), default to `serve` and open browser
    if len(sys.argv) == 1:
        from rotator.server import get_or_create_token
        token = get_or_create_token()
        url = f"http://127.0.0.1:7821/?token={token}"
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
        sys.argv = ["key-rotator", "serve"]

    cli()
