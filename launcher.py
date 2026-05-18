"""Standalone entrypoint used by the PyInstaller bundle.

Boots the FastAPI server in-process via uvicorn and opens the default browser
on the local UI. This file lives at the repository root (outside the ``app``
package) so PyInstaller can pick it up as a single script entrypoint.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser

import uvicorn

from app import __version__
from app.main import app

logger = logging.getLogger(__name__)


def _open_browser(url: str, delay: float = 1.5) -> None:
    """Wait briefly for the server to accept connections, then open ``url``."""
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except webbrowser.Error:
        logger.debug("Could not open browser automatically; visit %s manually.", url)


def main() -> int:
    """Run the embedded uvicorn server until interrupted."""
    host = os.environ.get("DBG_HOST", "127.0.0.1")
    port = int(os.environ.get("DBG_PORT", "8765"))
    url = f"http://{host}:{port}"

    sys.stdout.write(f"[DeleteBackground {__version__}] starting on {url}\n")
    sys.stdout.flush()

    threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    try:
        uvicorn.run(app, host=host, port=port, log_config=None)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
