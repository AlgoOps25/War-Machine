Full Batch 37 audit below.

File: docs/signal_logic_audit_batch37.md
text
# Signal Logic Audit — Batch 37

**Date:** 2026-03-18
**Scope:** `app/core/analytics_integration.py` (9 KB)
           `app/core/eod_reporter.py` (4 KB)
           `app/core/watch_signal_store.py` (7.6 KB)
           `app/core/health_server.py` (4.5 KB)
**Total Findings:** 20 (0 Critical, 3 High, 9 Medium, 8 Low)

---

## `analytics_integration.py`

Clean delegation wrapper. The module-level `try/except` import guard
for `signal_tracker` is the correct pattern for optional dependencies.
The `_TRACKER_AVAILABLE` flag gates every public method properly.

---

## 🔴 Criticals (0)

---

## 🟡 Highs (3)

---

### 37.H-1 — **`check_scheduled_tasks()` uses `datetime.now()` (tz-naive, local machine time) instead of `datetime.now(ET)`.** The market-open reset fires at `now.hour == 9 and now.minute == 30` and the EOD report fires at `now.hour == 16 and now.minute == 5`. On Railway, the server TZ is UTC. `datetime.now()` returns UTC time. The daily reset therefore fires at 9:30 UTC — **5:30 AM ET** — before any market data exists. The EOD report fires at 16:05 UTC — **12:05 PM ET** — mid-session, while trading is still active. The signal tracker cache is cleared at 12:05 ET, wiping all in-flight session signals mid-day. The `EOD` summary is sent to Discord at 12:05 PM, showing partial-day data labelled as the final EOD report. Fix: `datetime.now(ET)` throughout `check_scheduled_tasks()`, identical to the `eod_reporter.py` pattern directly below.

---

### 37.H-2 — **`get_today_stats()` accesses `_tracker.session_signals` directly** — a private instance dict of `SignalTracker`:

```python
"unique_tickers": len(_tracker.session_signals),
session_signals is not part of SignalTracker's public API. If 35.H-1 is fixed (keying session_signals by (ticker, event_id) tuples instead of just ticker), len(_tracker.session_signals) would return the total number of in-flight signal events, not the count of unique tickers. This stat would silently misreport after that fix. Should use len(set(k[0] for k in _tracker.session_signals)) after the fix, or expose a get_unique_ticker_count() method on SignalTracker.

37.H-3 — process_signal() fallback returns 1 in no-op mode:
python
if not _TRACKER_AVAILABLE or _tracker is None:
    return 1  # fallback: always allow in no-op mode
The return value 1 is used by scanner.py as a truthy check: if signal_id: send_discord_alert(signal_data). Returning 1 means every signal fires a Discord alert even when analytics are completely unavailable. On a Railway cold start where signal_tracker fails to initialize (DB down), every signal generates a Discord alert but nothing is recorded — the Discord channel floods with untracked signals with no corresponding analytics. The no-op return should be None and callers should gate on signal_id is not None rather than truthy int, or the no-op should still allow signals but be explicit about the degraded mode.

🟠 Mediums (5) — analytics_integration.py
ID	Issue
37.M-4	process_signal() extracts confidence = float(signal_data.get("confidence", signal_data.get("confirmation_score", 0.7))). The float() cast around a dict .get() will raise ValueError if the value is a non-numeric string (e.g., "HIGH"). Should wrap in try/except ValueError with a fallback to 0.7. Same risk for entry, stop, t1, t2 fields.
37.M-5	check_scheduled_tasks() sets self.daily_reset_done = True after the 9:30 reset. The reset for daily_reset_done back to False fires at midnight (now.hour == 0 and now.minute == 0). If check_scheduled_tasks() is not called during the midnight minute (e.g., scanner is down 00:00–00:01), daily_reset_done stays True all night and the 9:30 reset never fires the next morning. The flag should be reset when session_date changes rather than at a specific minute.
37.M-6	check_scheduled_tasks() calls _tracker.clear_session_cache() at 9:30. But clear_session_cache() (from signal_analytics.py) only clears the in-memory session_signals dict — it does not clear the or_cache, alerts_sent, or sr_cache in opening_range.py. The OR detector has its own clear_cache() method. Both caches need to be cleared at session open. check_scheduled_tasks() should also call or_detector.clear_cache().
37.M-7	The EOD summary fires at now.hour == 16 and now.minute == 5. check_scheduled_tasks() is called "once per minute" per the docstring. If the scanner skips one call (busy cycle, e.g., scanning 50 tickers at 16:04–16:06), the 16:05 window is missed and eod_report_done stays False. The next call at 16:06 has now.minute == 6 — the condition never triggers again. EOD report is silently skipped. Should use a range: now.hour == 16 and 5 <= now.minute <= 10 and not self.eod_report_done.
37.M-8	get_today_stats() returns "win_rate": 0.0 and "total_profit": 0.0 hardcoded. These are the stats most relevant to a trading system dashboard, yet they're always zero. Should delegate to position_manager.get_session_pnl() or risk_manager.get_session_status() for real values.
eod_reporter.py
Well-structured, uses logger throughout, proper try/except isolation
per report section. The deferred from app.signals.signal_analytics import signal_tracker import inside the function body correctly avoids circular
imports at module level. This is the best-written file in app/core/ so far.

🟠 Mediums (2) — eod_reporter.py
ID	Issue
37.M-9	run_eod_report() calls get_session_status() and get_eod_report() from risk_manager. Neither is guarded against the case where risk_manager hasn't been initialized (cold start / DB pool not ready). Both are top-level imports at module head: from app.risk.risk_manager import get_session_status, get_eod_report. If risk_manager fails to import (e.g., position_manager DB init error on startup), eod_reporter.py itself fails to import, and scanner.py loses EOD reporting entirely with a silent ImportError. The risk_manager imports should be deferred inside run_eod_report() with a try/except ImportError guard matching the pattern used for signal_analytics.
37.M-10	run_eod_report() calls signal_tracker.clear_session_cache() at EOD. As noted in 37.M-6, this does not clear the OR detector cache. run_eod_report() is a better place to orchestrate this since it's the canonical EOD orchestrator. Should also call or_detector.clear_cache() here.
watch_signal_store.py
Structurally identical to armed_signal_store.py — same _maybe_load /
_ensure_db / _cleanup_stale / _load_from_db pattern. The
time-based stale cleanup (vs the position-API-based cleanup in
armed_signal_store) is actually safer — it's purely local and cannot
wipe everything on an API outage (no 36.M-11 equivalent).

🔴 Criticals (0) — watch_signal_store.py
🟠 Mediums (2) — watch_signal_store.py
ID	Issue
37.M-11	_cleanup_stale_watches() deletes watches where breakout_bar_dt < cutoff_time. cutoff_time = _now_et() - timedelta(minutes=60) (12 bars × 5 min). breakout_bar_dt is stored tz-naive (via _strip_tz() on load). On Postgres, CURRENT_TIMESTAMP in the INSERT stores tz-aware UTC. When the cleanup query compares a tz-aware UTC timestamp with a tz-naive ET cutoff_time, Postgres raises TypeError: can't compare offset-naive and offset-aware datetimes. SQLite is unaffected (treats both as strings). This query is broken on Railway Postgres and silently catches the exception — stale watches are never cleaned up and accumulate indefinitely. Fix: use _now_et() (tz-aware) as cutoff_time and ensure breakout_bar_dt is stored tz-aware in _persist_watch().
37.M-12	Same as 36.M-10 for armed_signal_store: _persist_watch() does not call _ensure_watch_db() before inserting. On first arm before _maybe_load_watches() runs, watching_signals_persist may not exist.
health_server.py
The cleanest, most focused file in the entire codebase audited so far.
The time.monotonic() choice for heartbeat timing is exactly right —
immune to system clock changes and DST transitions. The dual
threshold (5 min market hours / 10 min off-hours) is well-designed.
The daemon thread ensures clean process exit.

🔴 Criticals (0) — health_server.py
🟡 Highs (0) — health_server.py
🟠 Mediums (0) — health_server.py
🟢 Lows (8)
ID	Issue
37.L-13	analytics_integration.py: check_scheduled_tasks() has no logger — uses implicit module-level logging. Should use logger = logging.getLogger(__name__) at module level, consistent with eod_reporter.py.
37.L-14	analytics_integration.py: monitor_active_signals() is a pass placeholder. If any caller checks the return value (e.g., if self.analytics_integration.monitor_active_signals(fetcher): ...), it gets None which is falsy. Should return None explicitly and add a # no-op comment to clarify intent.
37.L-15	analytics_integration.py: eod_ml_done flag is set in __init__ and reset at 9:30 but never set to True anywhere — no ML task fires at EOD. Dead flag. Should be removed or implemented.
37.L-16	eod_reporter.py: print(full_summary) on the full daily summary (potentially 50+ lines) uses print() rather than logger.info(). On Railway, print() is unbuffered and captured but loses log-level filtering. Should be logger.info(full_summary).
37.L-17	watch_signal_store.py: _strip_tz() checks hasattr(dt, "tzinfo") and dt.tzinfo to detect tz-awareness. All datetime objects have tzinfo as an attribute — the hasattr check is always True. The effective check is just if dt.tzinfo. This works correctly but the hasattr is misleading dead code.
37.L-18	watch_signal_store.py: send_bos_watch_alert() catches Exception on send_simple_message() and prints the error. This is correct. However, the print before the try — print(f"[WATCH] 📡 {ticker} ...") — fires regardless of whether the Discord send succeeds. The log will show a successful-looking alert line even if Discord delivery failed. Should move the success print inside the try after send_simple_message().
37.L-19	health_server.py: _HealthHandler.do_GET() returns b'{"error": "not found"}' for 404 but does not set Content-Type: application/json before end_headers(). Most HTTP clients will treat the body as plain text. Should add self.send_header("Content-Type", "application/json") for the 404 path.
37.L-20	health_server.py: start_health_server() logs "Health server listening on :{port}" via print(..., flush=True). Should use logger.info() for consistency. The flush=True is correct for Railway startup sequencing but logging handlers are also flushed on logger.info().
Priority Fix Order (Batch 37)
Rank	ID	Fix
1	37.H-1	check_scheduled_tasks() → datetime.now(ET) — prevents mid-session cache wipe and premature EOD report
2	37.M-11	_cleanup_stale_watches() tz-aware comparison on Postgres — stale watches never cleaned on Railway
3	37.H-3	process_signal() no-op return 1 → None; update caller gate to is not None
4	37.M-7	EOD report trigger — use minute range 5 <= now.minute <= 10 to tolerate a missed call
5	37.M-9	Defer risk_manager imports inside run_eod_report() with ImportError guard
6	37.M-6 / 37.M-10	Add or_detector.clear_cache() to both session-open reset and EOD orchestrator
7	37.M-12	_persist_watch() — lazy _ensure_watch_db() guard before first INSERT
8	37.H-2	get_today_stats() — add session_signals access guard for post-35.H-1 fix

**37.H-1 is the most operationally damaging finding in this batch.** `datetime.now()` on Railway UTC means the signal tracker session cache is wiped at 12:05 PM ET every day mid-session — every in-flight signal from the morning loses its state, `record_validation_result()` starts warning "No GENERATED signal found" for every ticker, and the EOD Discord report fires 4 hours early with partial data. It's a one-word fix: `ET` as the tz argument. It's also the easiest high-severity fix in the entire audit.

`health_server.py` is the standout — zero highs, zero mediums, eight Lows that are all cosmetic. It's the reference pattern for focused, single-responsibility modules in War Machine.

