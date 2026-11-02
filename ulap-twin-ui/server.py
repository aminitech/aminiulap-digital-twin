#!/usr/bin/env python3
"""twin-web: serve the three.js twin viewer with its data from twin-api.

The frontend of the three-tier Amini Cloud demo (twin-web -> twin-api -> Postgres).
Standard library only.

It serves the viewer's static files, except `data.js`: that one is built on each
request from twin-api's `/api/twin`, so the viewer draws whatever is in the
database. `/api/*` is passed through to twin-api, so the browser only ever
talks to this app; twin-api stays on the project's private network.

    TWIN_API_URL      where twin-api is, for example http://twin-api:8080.
                      Defaults to APP_URL_TWIN_API, which Amini Cloud sets for
                      an app named twin-api in the same project.
    PORT              where to listen (default 8080), on all addresses.

The bundled data.js (licence-restricted geoportal footprints) is never served
and is left out of the container image.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = {
    "/": "index.html",
    "/index.html": "index.html",
    "/scene.html": "scene.html",
    "/app.js": "app.js",
    "/scene.js": "scene.js",
    "/anime.min.js": "anime.min.js",
    "/three.min.js": "three.min.js",
    "/OrbitControls.js": "OrbitControls.js",
    "/BufferGeometryUtils.js": "BufferGeometryUtils.js",
    "/twin-status.js": "twin-status.js",
    "/icon-white.svg": "icon-white.svg",
    "/wordmark-white.svg": "wordmark-white.svg",
}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
STATUS_TAG = b'<script src="twin-status.js"></script>\n</body>'
API_TIMEOUT = 5
MAX_BODY = 1024
# The outside address may keep its route prefix (/r/<app-id>/<port>/); serve the same files under it.
ROUTE_PREFIX = re.compile(r"^/r/[0-9a-f-]{36}/\d+(?=/)")


def api_base() -> str:
    return (os.environ.get("TWIN_API_URL") or os.environ.get("APP_URL_TWIN_API") or "http://127.0.0.1:8081").rstrip("/")


def log(msg: str, **fields) -> None:
    print(json.dumps({"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                      "level": fields.pop("level", "info"), "service": "twin-web", "msg": msg, **fields}),
          flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "twin-web"
    sys_version = ""

    def log_message(self, *args) -> None:
        pass

    def _path(self) -> str:
        return ROUTE_PREFIX.sub("", self.path.split("?")[0], count=1)

    def _start(self) -> None:
        self.t0 = time.monotonic()
        self.request_id = uuid.uuid4().hex
        self.status = 500

    def _done(self) -> None:
        log("request", method=self.command, path=self.path.split("?")[0], status=self.status,
            duration_ms=round((time.monotonic() - self.t0) * 1000, 1), request_id=self.request_id)

    def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Request-Id", self.request_id)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
        self.status = status

    def _api(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
        req = urllib.request.Request(api_base() + path, data=body, method=method, headers={
            "X-Request-Id": self.request_id, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def _api_down(self, err: Exception) -> None:
        log("twin-api unreachable", level="error", error=type(err).__name__, request_id=self.request_id)

    def do_GET(self) -> None:
        self._start()
        try:
            path = self._path()
            if path == "/healthz":
                return self._send(200, b'{"status":"ok"}', "application/json")
            if path == "/readyz":
                try:
                    status, _ = self._api("GET", "/readyz")
                except (urllib.error.URLError, OSError) as err:
                    self._api_down(err)
                    status = 503
                return self._send(200 if status == 200 else 503,
                                  json.dumps({"twin_api": "ready" if status == 200 else "not ready"}).encode(),
                                  "application/json")
            if path == "/data.js":
                return self.data_js()
            if path.startswith("/api/"):
                try:
                    status, body = self._api("GET", path)
                except (urllib.error.URLError, OSError) as err:
                    self._api_down(err)
                    return self._send(502, b'{"error":"twin-api is not reachable"}', "application/json")
                return self._send(status, body, "application/json")
            name = STATIC.get(path)
            if not name:
                return self._send(404, b"not found", "text/plain")
            body = (HERE / name).read_bytes()
            if name.endswith(".html"):
                body = body.replace(b"</body>", STATUS_TAG, 1)
            cache = "no-store" if name.endswith(".html") else "public, max-age=300"
            self._send(200, body, TYPES[Path(name).suffix], cache)
        finally:
            self._done()

    def do_POST(self) -> None:
        self._start()
        try:
            if self._path() != "/api/views":
                return self._send(404, b'{"error":"not found"}', "application/json")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._send(400, b'{"error":"bad Content-Length"}', "application/json")
            if length > MAX_BODY:
                return self._send(413, b'{"error":"body too large"}', "application/json")
            try:
                status, body = self._api("POST", "/api/views", self.rfile.read(length))
            except (urllib.error.URLError, OSError) as err:
                self._api_down(err)
                return self._send(502, b'{"error":"twin-api is not reachable"}', "application/json")
            self._send(status, body, "application/json")
        finally:
            self._done()

    def data_js(self) -> None:
        """The viewer's data, from Postgres via twin-api. A clear error if it is unreachable."""
        t0 = time.monotonic()
        try:
            status, body = self._api("GET", "/api/twin")
            if status != 200:
                raise RuntimeError(f"twin-api answered {status}")
            twin = json.loads(body)
            source = {"ok": True, "api": "twin-api", "store": twin.get("source"),
                      "buildings": len(twin["buildings"]), "towers": len(twin["towers"]),
                      "fetch_ms": round((time.monotonic() - t0) * 1000), "request_id": self.request_id,
                      "provenance": (twin.get("provenance") or {}).get("buildings", {}).get("licence")}
        except (urllib.error.URLError, OSError, RuntimeError, ValueError, KeyError) as err:
            self._api_down(err)
            twin = {"towers": [], "buildings": []}
            source = {"ok": False, "error": "twin-api is not reachable", "request_id": self.request_id}
        js = ("window.TWIN_DATA = " + json.dumps({"towers": twin["towers"], "buildings": twin["buildings"]},
                                                 separators=(",", ":"))
              + ";\nwindow.TWIN_SOURCE = " + json.dumps(source) + ";\n")
        self._send(200, js.encode(), TYPES[".js"])


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    log("listening", port=port, twin_api=api_base())
    try:
        ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
