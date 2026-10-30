"""Tiny persistent dev-server stand-in for sandbox tests.

Serves files from cwd over HTTP and, like Next.js, emits compiler log
events when files change: 'Compiled successfully' normally, or a
failure marker when a file contains SYNTAX_ERROR. Used to exercise
real log-offset HMR detection without a fixed-sleep strategy.
"""
import http.server
import os
import threading
import time
from pathlib import Path

ROOT = Path.cwd()
_state = {"mtime": 0.0, "bad": False}


def _scan():
    latest, bad = 0.0, False
    for path in ROOT.rglob("*"):
        if path.is_file() and "node_modules" not in path.parts:
            latest = max(latest, path.stat().st_mtime)
            if "SYNTAX_ERROR" in path.read_text(errors="ignore"):
                bad = True
    return latest, bad


def _watch():
    _state["mtime"], _state["bad"] = _scan()
    while True:
        time.sleep(0.05)
        latest, bad = _scan()
        if latest != _state["mtime"]:
            _state["mtime"], _state["bad"] = latest, bad
            print("Failed to compile: SYNTAX_ERROR" if bad else "Compiled successfully",
                  flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        target = ROOT / "page.txt"
        body = target.read_bytes() if target.exists() else b"visorqa-fixture"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=_watch, daemon=True).start()
    print("Ready in 1ms", flush=True)
    http.server.HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
