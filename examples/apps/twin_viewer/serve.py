#!/usr/bin/env python3
"""
Serve the three.js twin viewer (`ulap-twin-ui/`) locally.

    python examples/apps/twin_viewer/serve.py            # serve + open a browser
    python examples/apps/twin_viewer/serve.py --port 8080 --no-open

The viewer renders the real pilot data -- 576 building footprints at LiDAR
heights, the two towers, and an animated propagation visualisation -- in the
browser. It is plain HTML/JS with vendored three.js, so this needs **nothing but
the Python standard library**; the only reason it wants a server at all is that
browsers refuse module/asset loads from `file://`.
"""
from __future__ import annotations

import argparse
import http.server
import socket
import socketserver
import sys
import threading
import webbrowser
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = next(p for p in HERE.parents if (p / "ulap-twin-ui").is_dir())
UI_DIR = REPO_ROOT / "ulap-twin-ui"

BANNER = r"""
   ((o))                                        ((o))
    /|\        ~   ulap twin viewer   ~          /|\
   /_|_\           three.js  ·  local           /_|_\
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    """Static handler with sane MIME types and no request-log spam."""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".svg": "image/svg+xml",
        ".json": "application/json",
        ".glb": "model/gltf-binary",
        "": "application/octet-stream",
    }

    def log_message(self, fmt, *args):        # quiet by default
        if self.server.verbose:               # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    def end_headers(self):
        # Local dev: never cache, so an edit to scene.js shows up on reload.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    verbose = False


def free_port(preferred: int) -> int:
    """Return ``preferred`` if it is free, otherwise an OS-assigned port."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--page", default="index.html",
                    help="index.html (landing) or scene.html (3-D scene)")
    ap.add_argument("--no-open", action="store_true", help="do not launch a browser")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every request")
    args = ap.parse_args(argv)

    if not (UI_DIR / args.page).exists():
        print(f"error: {UI_DIR / args.page} not found", file=sys.stderr)
        print(f"       pages available: "
              f"{', '.join(sorted(p.name for p in UI_DIR.glob('*.html')))}",
              file=sys.stderr)
        return 1

    port = free_port(args.port)
    if port != args.port:
        print(f"port {args.port} is busy — using {port} instead")

    handler = partial(Handler, directory=str(UI_DIR))
    with Server((args.host, port), handler) as httpd:
        httpd.verbose = args.verbose
        url = f"http://{args.host}:{port}/{args.page}"
        print(BANNER)
        print(f"  serving : {UI_DIR}")
        print(f"  open    : {url}")
        print(f"  pages   : {', '.join(sorted(p.name for p in UI_DIR.glob('*.html')))}")
        print("  stop    : Ctrl-C\n")
        if not args.no_open:
            threading.Timer(0.6, webbrowser.open, args=(url,)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nbye ♥")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
