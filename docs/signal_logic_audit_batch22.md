All four files read. Here is the full Batch 22 audit.

File: docs/signal_logic_audit_batch22.md
text
# Signal Logic Audit — Batch 22

**Date:** 2026-03-18
**Scope:** `app/core/analytics_integration.py`, `app/core/eod_reporter.py`,
           `app/core/health_server.py`, `app/core/__main__.py` (trivial)
**Total Findings:** 16 (0 Critical, 4 High, 7 Medium, 5 Low)

---

## 🔴 Criticals (0)

Clean. No critical findings in this batch.

---

## 🟡 Highs (4)

---

### 22.H-1 — `AnalyticsIntegration.process_signal()` returns `1` (hardcoded int) when `_TRACKER_AVAILABLE = False`:

```python
if not _TRACKER_AVAILABLE or _tracker is None:
    return 1  # fallback: always allow in no-op mode
The return value is used by scanner.py as a signal_id. A hardcoded 1 means every no-op signal gets signal_id = 1, not None. The caller in scanner.py checks if signal_id: — 1 is truthy, so the signal proceeds. But signal_id = 1 is also a valid real ID in Postgres (the first auto-increment). If the tracker is temporarily unavailable and comes back online, a deferred call using signal_id = 1 will corrupt or overwrite the real signal with id=1 in the DB. The comment says "always allow in no-op mode" — but it should return None, not 1, to indicate the signal was not persisted. The caller should handle None gracefully.

Fix:

python
if not _TRACKER_AVAILABLE or _tracker is None:
    return None   # not persisted — caller must check
Then in scanner.py:

python
signal_id = analytics.process_signal(signal_data)
if signal_id is not None:
    ...
22.H-2 — AnalyticsIntegration.check_scheduled_tasks() uses datetime.now() (no timezone) for its hour/minute checks:
python
now = datetime.now()
if now.hour == 9 and now.minute == 30 and not self.daily_reset_done:
Railway containers run in UTC. datetime.now() on Railway returns UTC time. Market open is 9:30 AM ET = 13:30 UTC (14:30 UTC during EDT). The daily reset fires 4 hours late in winter (never during EDT, wrong hour). The EOD summary fires at midnight UTC (8 PM ET) instead of 4:05 PM ET. Both scheduled tasks have been silently misfiring since deployment.

Fix: Use datetime.now(ZoneInfo("America/New_York")) consistently:

python
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo("America/New_York"))
22.H-3 — eod_reporter.run_eod_report() calls get_session_status() and then get_eod_report() — two separate DB checkouts — for the EOD block. scanner.py also calls get_session_status() immediately before calling run_eod_report() (in the same EOD block), and the result is used only for open_positions display. The session dict is not passed into run_eod_report(), forcing a redundant second checkout inside the reporter. This is the same pattern fixed by Phase 1.29 (FIX #9) in the scan cycle — but not applied to the EOD path.
Fix: Add an optional session parameter to run_eod_report():

python
def run_eod_report(session_date=None, session=None):
    if session is None:
        session = get_session_status()
    ...
Then in scanner.py:

python
session = get_session_status()
# ... use session for open_positions display ...
run_eod_report(current_day, session=session)
22.H-4 — health_server.start_health_server() is called at module load in scanner.py (start_health_server() at the top of scanner.py, before start_scanner_loop()). If PORT env var is set to a port that is already in use (e.g., Railway redeploy before the old process has released the port), HTTPServer(("0.0.0.0", port), _HealthHandler) raises OSError: [Errno 98] Address already in use. This exception propagates out of start_health_server(), which propagates out of the module-level call in scanner.py, which crashes the entire import of scanner.py. Railway sees an import error and does not start the process. The fix is already noted in Batch 20 (20.L-16) — wrapping in try/except — but the root cause is also the missing SO_REUSEADDR socket option.
Fix: Add allow_reuse_address = True to the server:

python
class _HealthServer(HTTPServer):
    allow_reuse_address = True

server = _HealthServer(("0.0.0.0", port), _HealthHandler)
And wrap the module-level call in scanner.py in try/except (per 20.L-16).

🟠 Mediums (7)
ID	File	Issue
22.M-5	analytics_integration.py	AnalyticsIntegration.__init__() accepts db_connection but immediately ignores it — comment says "kept for API compatibility". scanner.py passes analytics_conn (the raw psycopg2 connection from Batch 20.H-2) into the constructor. If analytics_conn is ever closed or recycled, the AnalyticsIntegration instance holds a dead reference it never uses. The parameter should either be removed with a deprecation comment, or used to override _tracker's internal connection.
22.M-6	analytics_integration.py	get_today_stats() accesses _tracker.session_signals directly — a private attribute of SignalTracker. If SignalTracker renames or restructures session_signals, this breaks silently (KeyError or AttributeError on len()). Should use a public API: _tracker.get_funnel_stats() already returns unique_tickers if SignalTracker exposes it.
22.M-7	analytics_integration.py	check_scheduled_tasks() has a midnight flag reset: if now.hour == 0 and now.minute == 0: self.daily_reset_done = False. This only fires for exactly one minute (when now.minute == 0). If the scanner loop is sleeping (e.g., 600-second after-hours sleep), midnight may be skipped entirely — the next check happens at 00:10. daily_reset_done stays True until the next exact-minute match. On the new trading day, market open reset never fires. Should use a date-based flag: if now.date() != self._last_reset_date.
22.M-8	eod_reporter.py	run_eod_report() calls signal_tracker.get_discord_eod_summary(session_date) and signal_tracker.get_daily_summary(session_date) — both pass session_date (a YYYY-MM-DD string). If SignalTracker's methods filter by date using this string, the results depend on the DB timezone interpretation of session_date. On UTC Railway Postgres, DATE(saved_at) = '2026-03-18' compares UTC-stored timestamps — a 4:05 PM ET trade (20:05 UTC) is on date 2026-03-18 in UTC, which is correct. But a 3:59 PM ET trade on March 18 during DST is 19:59 UTC = still 2026-03-18. Safe, but should be documented.
22.M-9	eod_reporter.py	send_daily_summary() is imported at module level (top-level from app.notifications.discord_helpers import send_daily_summary, send_simple_message). If discord_helpers.py is absent or broken, the eod_reporter module fails to import entirely — scanner.py's from app.core.eod_reporter import run_eod_report at EOD raises ImportError. This kills the EOD block. The import should be deferred inside run_eod_report() matching the pattern used throughout the codebase.
22.M-10	health_server.py	_last_heartbeat is a module-level global mutated inside health_heartbeat() via global _last_heartbeat. The _lock is used correctly to protect the write in health_heartbeat() and the read in _build_response(). However, _last_heartbeat is initialized at module import time with time.monotonic() — before start_health_server() is called. On Railway, if the module is imported but start_health_server() is never called (edge case), the heartbeat age clock starts at import time. Low risk (the module is always called), but _start_time and _last_heartbeat should be set inside start_health_server() rather than at import time.
22.M-11	health_server.py	start_health_server() can be called multiple times (e.g., if scanner.py calls it at module level AND start_scanner_loop() calls it again via some future refactor). Each call creates a new HTTPServer and a new thread. The second call would fail with OSError: Address already in use (mitigated by 22.H-4's fix) or silently create a second server on the same port. No guard against double-start. Add a module-level _server_started flag.
🟢 Lows (5)
ID	File	Issue
22.L-12	analytics_integration.py	Module-level logging.warning() fires at import if SignalTracker is unavailable. Correct level, but the message "SignalTracker unavailable: %s — running in no-op mode" does not include the traceback. For an ImportError, the module name is useful but the full traceback is suppressed. Use logger.warning(..., exc_info=True) or at minimum log the module path.
22.L-13	analytics_integration.py	arm_signal() method signature accepts confirmation_type: str = "retest" but sniper.py never calls analytics.arm_signal() directly — it calls signal_tracker.record_signal_armed() via arm_signal.py. This method is dead code in the current call graph.
22.L-14	eod_reporter.py	run_eod_report() logs logger.info(f"[EOD-REPORTER] Generating EOD report for {session_date}") but the final success log "✅ All EOD reports complete" uses logger.info(). If any section raises and is caught, the "complete" message fires even though parts failed. Should distinguish "completed with errors" vs "fully clean".
22.L-15	health_server.py	_HealthHandler.do_GET() only handles /health and / — any other path returns a 404 with {"error": "not found"} but without a Content-Type: application/json header. Minor HTTP spec violation for Railway's health probe (which only hits /health), but breaks curl/browser inspection.
22.L-16	health_server.py	The staleness thresholds (_MARKET_HOURS_STALE = 5 * 60, _OFF_HOURS_STALE = 10 * 60) are module-level constants with no config.py entry. If Railway's health probe timeout is adjusted, these must be manually synchronized. Should be in config.py as HEALTH_STALE_MARKET_SECONDS and HEALTH_STALE_OFF_HOURS_SECONDS.
Priority Fix Order
22.H-2 — check_scheduled_tasks() uses datetime.now() (UTC on Railway) — daily reset fires 4h late, EOD summary fires at 8 PM ET instead of 4:05 PM ET — both misfiring in production since deployment

22.H-4 — Missing SO_REUSEADDR on health server — Railway redeploy on port collision kills the entire import chain

22.H-1 — process_signal() returns 1 instead of None in no-op mode — risk of corrupting real signal_id=1 DB record

22.H-3 — Redundant get_session_status() DB checkout in EOD reporter — same pattern fixed by Phase 1.29 but not applied to EOD path

22.M-9 — Module-level send_daily_summary import in eod_reporter.py — absent discord_helpers kills entire EOD block

22.M-7 — Midnight flag reset via exact-minute check — skipped during 600s after-hours sleep, new day reset never fires
