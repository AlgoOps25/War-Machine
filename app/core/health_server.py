"""
Health Server - Lightweight HTTP /health endpoint for Railway

C5 FIX (MAR 10, 2026):
  Previously the scanner had no HTTP health endpoint at all. Railway's
  health-check probe never got a meaningful signal, so a silently-dead
  scanner (WS disconnected, DB pool exhausted, etc.) would keep Railway
  thinking the service was healthy and never trigger a restart.

  This module exposes a tiny HTTP server on PORT (env var, default 8080)
  with a single GET /health route:
    - 200  { "status": "ok",      "uptime_s": N, "last_heartbeat_age_s": N }
    - 503  { "status": "stalled", "uptime_s": N, "last_heartbeat_age_s": N }

  Staleness thresholds:
    - During market hours (09:30-16:00 ET weekdays): 5 min
    - Outside market hours: 10 min (after-hours loop sleeps 600s)

  The scanner loop calls health_heartbeat() at the top of each cycle.
  If the scanner is alive and looping, /health stays green.

Usage (scanner.py already wires this):
    from app.core.health_server import start_health_server, health_heartbeat
    start_health_server()          # call once at startup
    # inside main loop:
    health_heartbeat()             # call each cycle

FIX #54 (2026-03-27):
  Added _started guard to start_health_server().
  scanner.py calls start_health_server() at module level (before imports)
  for Railway probe timing. __main__.py also called it.  Two calls on
  different code paths would both attempt to bind the same PORT, causing
  'OSError: [Errno 98] Address already in use' on Railway.
  Guard makes the second call a no-op.

AUDIT 2026-03-27:
  _build_response() previously called _is_market_hours() twice per request
  (once for threshold, once for the response body field). Refactored to
  call once and reuse the result.

AUDIT 2026-03-31 (Session 16):
  BUG-HS-1: Added blank line between import logging and logger assignment
            for visual consistency with rest of app/core files.
  BUG-HS-2: Added 'from __future__ import annotations' so union type syntax
            (int | None, threading.Thread | None) is safe on Python < 3.10.
            Railway runs 3.11 so no runtime risk, but makes the file
            forward/backward compatible and consistent with eod_reporter.py.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, time as dtime
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

_start_time = time.monotonic()
_last_heartbeat: float = time.monotonic()   # updated by scanner loop
_lock = threading.Lock()

# FIX #54: guard against double-call (scanner module-level + __main__.py)
_started = False
_started_lock = threading.Lock()

# Staleness thresholds (seconds)
_MARKET_HOURS_STALE = 5  * 60   # 5 min during RTH
_OFF_HOURS_STALE    = 10 * 60   # 10 min outside RTH


def health_heartbeat() -> None:
    """Call this at the top of every scanner loop cycle to signal liveness."""
    global _last_heartbeat
    with _lock:
        _last_heartbeat = time.monotonic()


def _is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 30) <= t <= dtime(16, 0)


def _build_response() -> tuple[int, dict]:
    """
    Returns (http_status_code, body_dict).
    200 = alive and heartbeat fresh
    503 = heartbeat stale (scanner loop has stopped cycling)
    """
    with _lock:
        last_hb = _last_heartbeat

    age_s     = time.monotonic() - last_hb
    uptime_s  = int(time.monotonic() - _start_time)
    in_market = _is_market_hours()   # call once, reuse below
    threshold = _MARKET_HOURS_STALE if in_market else _OFF_HOURS_STALE

    body = {
        "status":               "ok" if age_s <= threshold else "stalled",
        "uptime_s":             uptime_s,
        "last_heartbeat_age_s": round(age_s, 1),
        "threshold_s":          threshold,
        "market_hours":         in_market,
        "timestamp":            datetime.now(ET).isoformat(),
    }
    status_code = 200 if age_s <= threshold else 503
    return status_code, body


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler — only serves GET /health and GET /."""

    def do_GET(self):  # noqa: N802
        if self.path not in ("/health", "/"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "not found"}')
            return

        status_code, body = _build_response()
        payload = json.dumps(body).encode()

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):  # noqa: N802
        # Suppress per-request access logs — Railway captures stdout
        pass


def start_health_server(port: int | None = None) -> threading.Thread | None:
    """
    Start the health HTTP server in a background daemon thread.

    Port is read from the PORT environment variable (Railway sets this
    automatically).  Falls back to 8080 if PORT is not set.

    Returns the Thread object (daemon=True, joins on process exit),
    or None if the server was already started (FIX #54 guard).
    """
    global _started
    with _started_lock:
        if _started:
            logger.debug("[HEALTH] start_health_server() called again — already running, skipping")
            return None
        _started = True

    if port is None:
        port = int(os.environ.get("PORT", 8080))

    server = HTTPServer(("0.0.0.0", port), _HealthHandler)

    def _serve():
        logger.info(f"[HEALTH] Health server listening on :{port} (GET /health)")
        server.serve_forever()

    t = threading.Thread(target=_serve, daemon=True, name="health_server")
    t.start()

    # Seed the heartbeat so /health returns 200 immediately at startup
    health_heartbeat()

    return t
