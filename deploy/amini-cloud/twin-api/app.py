#!/usr/bin/env python3
"""twin-api: the Ulap twin's scene, served from Postgres.

The backend of the three-tier Amini Cloud demo (twin-web -> twin-api -> Postgres).

On start it creates its tables and loads seed.json (open data only) if they are
empty, under a Postgres advisory lock so two copies starting together cannot
both seed. Then it serves:

    GET  /healthz           the process is up
    GET  /readyz            Postgres answers
    GET  /api/twin          towers and buildings, in the shape ulap-twin-ui reads
    GET  /api/towers        the towers
    GET  /api/link-metrics  path gain and delay spread against distance
    GET  /api/stats         row counts, the database version, page views
    POST /api/views         record one page view (page name only, no personal data)

Configuration, all from the environment:

    DATABASE_URL  set by Amini Cloud when a database is attached to the app
    PORT          where to listen (default 8080), on all addresses

Logs are one JSON object per line on stdout. They never include the database
URL, request bodies or headers.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

SEED = Path(__file__).resolve().parent / "seed.json"
SEED_LOCK = 0x7477696E  # "twin"
MAX_BODY = 1024
PAGES = {"index", "scene"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS scene_meta (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS towers (
    id        serial PRIMARY KEY,
    name      text NOT NULL,
    code      text NOT NULL UNIQUE,
    structure text NOT NULL,
    height_m  double precision NOT NULL,
    lon       double precision NOT NULL,
    lat       double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS buildings (
    id       serial PRIMARY KEY,
    osm_id   bigint,
    height_m double precision NOT NULL,
    h_source text NOT NULL,
    ring     jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS link_metrics (
    distance_m      double precision PRIMARY KEY,
    path_gain_db    double precision NOT NULL,
    delay_spread_ns double precision NOT NULL,
    num_paths       integer NOT NULL
);
CREATE TABLE IF NOT EXISTS page_views (
    id   bigserial PRIMARY KEY,
    page text NOT NULL,
    at   timestamptz NOT NULL DEFAULT now()
);
"""


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": "twin-api",
            "msg": record.getMessage(),
        }
        out.update(getattr(record, "fields", {}))
        return json.dumps(out)


log = logging.getLogger("twin-api")
_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(JsonFormatter())
log.addHandler(_h)
log.setLevel(logging.INFO)


def info(msg: str, **fields) -> None:
    log.info(msg, extra={"fields": fields})


def migrate_and_seed(pool: ConnectionPool) -> None:
    """Create the tables and load the seed once. Safe to run on every start."""
    seed = json.loads(SEED.read_text())
    with pool.connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (SEED_LOCK,))
        conn.execute(SCHEMA)
        if conn.execute("SELECT count(*) FROM buildings").fetchone()[0]:
            info("seed skipped: tables already hold data")
            return
        conn.execute(
            "INSERT INTO scene_meta (key, value) VALUES ('provenance', %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (Jsonb(seed["provenance"]),))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO towers (name, code, structure, height_m, lon, lat) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (code) DO NOTHING",
                [(t["name"], t["code"], t["struct"], t["height"], t["lon"], t["lat"]) for t in seed["towers"]])
            cur.executemany(
                "INSERT INTO buildings (osm_id, height_m, h_source, ring) VALUES (%s, %s, %s, %s)",
                [(b["osm_id"], b["h"], b["h_source"], Jsonb(b["r"])) for b in seed["buildings"]])
            cur.executemany(
                "INSERT INTO link_metrics (distance_m, path_gain_db, delay_spread_ns, num_paths) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (distance_m) DO NOTHING",
                [(m["distance_m"], m["path_gain_dB"], m["delay_spread_ns"], int(m["num_paths"]))
                 for m in seed["link_metrics"]])
        info("seeded", towers=len(seed["towers"]), buildings=len(seed["buildings"]),
             link_metrics=len(seed["link_metrics"]))


def make_handler(pool: ConnectionPool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "twin-api"
        sys_version = ""

        def log_message(self, *args) -> None:  # replaced by the JSON line in _done
            pass

        def _send(self, status: int, body: dict | list) -> None:
            data = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Request-Id", self.request_id)
            self.end_headers()
            self.wfile.write(data)
            self.status = status

        def _start(self) -> None:
            self.t0 = time.monotonic()
            rid = self.headers.get("X-Request-Id", "")
            self.request_id = rid if rid and len(rid) <= 64 and rid.isascii() else uuid.uuid4().hex
            self.status = 500

        def _done(self) -> None:
            info("request", method=self.command, path=self.path.split("?")[0], status=self.status,
                 duration_ms=round((time.monotonic() - self.t0) * 1000, 1), request_id=self.request_id)

        def _db_error(self, err: Exception) -> None:
            log.error("database error", extra={"fields": {"error": type(err).__name__, "request_id": self.request_id}})
            self._send(503, {"error": "the database is not answering", "request_id": self.request_id})

        def do_GET(self) -> None:
            self._start()
            try:
                path = self.path.split("?")[0]
                if path == "/healthz":
                    return self._send(200, {"status": "ok"})
                routes = {
                    "/readyz": self.readyz,
                    "/api/twin": self.twin,
                    "/api/towers": self.towers,
                    "/api/link-metrics": self.link_metrics,
                    "/api/stats": self.stats,
                }
                if path not in routes:
                    return self._send(404, {"error": "not found"})
                try:
                    routes[path]()
                except psycopg.Error as err:
                    self._db_error(err)
            finally:
                self._done()

        def do_POST(self) -> None:
            self._start()
            try:
                if self.path.split("?")[0] != "/api/views":
                    return self._send(404, {"error": "not found"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._send(400, {"error": "bad Content-Length"})
                if length > MAX_BODY:
                    return self._send(413, {"error": "body too large"})
                try:
                    page = json.loads(self.rfile.read(length) or b"{}").get("page")
                except (ValueError, AttributeError):
                    return self._send(400, {"error": "body must be a JSON object"})
                if page not in PAGES:
                    return self._send(400, {"error": f"page must be one of {sorted(PAGES)}"})
                try:
                    with pool.connection() as conn:
                        n = conn.execute(
                            "WITH ins AS (INSERT INTO page_views (page) VALUES (%s) RETURNING 1) "
                            "SELECT count(*) + 1 FROM page_views", (page,)).fetchone()[0]
                    self._send(201, {"page": page, "views": n})
                except psycopg.Error as err:
                    self._db_error(err)
            finally:
                self._done()

        def readyz(self) -> None:
            with pool.connection(timeout=3) as conn:
                conn.execute("SELECT 1")
            self._send(200, {"status": "ready"})

        def towers(self) -> None:
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT name, code, structure, height_m, lon, lat FROM towers ORDER BY id").fetchall()
            self._send(200, [{"name": n, "code": c, "struct": s, "height": h, "lon": lo, "lat": la}
                             for n, c, s, h, lo, la in rows])

        def twin(self) -> None:
            with pool.connection() as conn:
                towers = conn.execute(
                    "SELECT name, code, structure, height_m, lon, lat FROM towers ORDER BY id").fetchall()
                buildings = conn.execute("SELECT height_m, ring FROM buildings ORDER BY id").fetchall()
                prov = conn.execute("SELECT value FROM scene_meta WHERE key = 'provenance'").fetchone()
            self._send(200, {
                "towers": [{"name": n, "code": c, "struct": s, "height": h, "lon": lo, "lat": la}
                           for n, c, s, h, lo, la in towers],
                "buildings": [{"h": h, "r": r} for h, r in buildings],
                "provenance": prov[0] if prov else None,
                "source": "postgres",
            })

        def link_metrics(self) -> None:
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT distance_m, path_gain_db, delay_spread_ns, num_paths FROM link_metrics "
                    "ORDER BY distance_m").fetchall()
            self._send(200, [{"distance_m": d, "path_gain_dB": g, "delay_spread_ns": s, "num_paths": p}
                             for d, g, s, p in rows])

        def stats(self) -> None:
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT (SELECT count(*) FROM towers), (SELECT count(*) FROM buildings), "
                    "(SELECT count(*) FROM link_metrics), (SELECT count(*) FROM page_views), "
                    "current_setting('server_version')").fetchone()
            self._send(200, {"towers": row[0], "buildings": row[1], "link_metrics": row[2],
                             "page_views": row[3], "postgres": row[4]})

    return Handler


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log.error("DATABASE_URL is not set: attach a database to this app, then redeploy")
        sys.exit(1)
    port = int(os.environ.get("PORT", "8080"))
    pool = ConnectionPool(dsn, min_size=1, max_size=8, timeout=5, open=False,
                          kwargs={"connect_timeout": 5, "application_name": "twin-api"})
    # Open the port first so the platform's start check passes while Postgres warms up;
    # /readyz reports 503 until the seed is in.
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(pool))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    info("listening", port=port)
    for attempt in range(1, 31):
        try:
            pool.open(wait=True, timeout=10)
            migrate_and_seed(pool)
            break
        except (psycopg.Error, PoolTimeout) as err:
            log.warning("database not ready, retrying", extra={"fields": {"attempt": attempt, "error": type(err).__name__}})
            time.sleep(min(2 * attempt, 10))
    else:
        log.error("gave up waiting for the database")
        sys.exit(1)
    info("ready")
    threading.Event().wait()


if __name__ == "__main__":
    main()
