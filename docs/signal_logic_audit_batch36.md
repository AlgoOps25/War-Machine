Full Batch 36 audit — arm_signal.py and armed_signal_store.py, the two smallest app/core/ action files. The three heavyweights (scanner.py, sniper.py, thread_safe_state.py) are deferred to Batches 37–39.

File: docs/signal_logic_audit_batch36.md
text
# Signal Logic Audit — Batch 36

**Date:** 2026-03-18
**Scope:** `app/core/` — directory inventory + audit of
           `arm_signal.py` (8 KB) and `armed_signal_store.py` (8.4 KB)
           Remaining files deferred to Batches 37–39
**Total Findings:** 19 (0 Critical, 4 High, 9 Medium, 6 Low)

---

## `app/core/` Directory Inventory

| File | Size | Batch |
|------|------|-------|
| `__init__.py` | 22 B | Skip |
| `__main__.py` | 177 B | Skip |
| `analytics_integration.py` | 9 KB | 37 |
| `arm_signal.py` | 8 KB | ✅ This batch |
| `armed_signal_store.py` | 8.4 KB | ✅ This batch |
| `eod_reporter.py` | 4 KB | 37 |
| `health_server.py` | 4.5 KB | 37 |
| `watch_signal_store.py` | 7.6 KB | 37 |
| `thread_safe_state.py` | 10.8 KB | 38 |
| `scanner.py` | 39 KB | 38 |
| `sniper.py` | 65 KB | 39 |

---

## `arm_signal.py`

The entire function is one long `arm_ticker()` procedure with all
imports deferred inside the function body to break circular imports.
The pattern is pragmatic but has well-defined risks.

---

## 🔴 Criticals (0)

The primary safety gate — `if position_id == -1: return` before any
Discord alert or persistence — is correctly placed. No position is
persisted or alerted without a confirmed open. No criticals.

---

## 🟡 Highs (4)

---

### 36.H-1 — **All imports inside `arm_ticker()` run on every single call.** Python caches module imports after the first load (O(1) dict lookup in `sys.modules`), so this is not a performance bug in isolation. However, `arm_ticker()` imports **14 modules** on every call:

```python
from app.risk.position_manager import position_manager
from app.core.thread_safe_state import get_state
from app.core.armed_signal_store import _persist_armed_signal
from app.screening.screener_integration import get_ticker_screener_metadata
from app.notifications.discord_helpers import send_options_signal_alert
from app.core.sniper_log import log_proposed_trade
# ... + 8 more conditional imports
The circular import problem this solves is real, but the consequence is that any ImportError or AttributeError in any of these 14 modules causes arm_ticker() to raise silently at the point of failure — and the caller has no try/except around arm_ticker(). A broken discord_helpers import would cause the entire arming path to crash after position_manager.open_position() has already been called. The position would be open in the broker with no armed signal state persisted, no cooldown set, and no Discord alert sent. The only guarded import is _send_alert_safe (wrapped in try/except ImportError). The position_manager.open_position() call must be wrapped so that any subsequent failure can trigger an emergency close. At minimum, wrap the post-open block in try/except that calls position_manager.close_position(position_id) on failure.

36.H-2 — The signal_tracker.record_trade_executed() call (Mar 16 fix) correctly records the TRADED stage. But it has no guard for the 35.H-1 issue — if session_signals[ticker]['stage'] != 'ARMED', record_trade_executed() returns -1 and logs a warning. In arm_signal.py the call is wrapped in try/except Exception which swallows the -1 return silently. More critically: record_signal_generated() and record_validation_result() are never called from arm_signal.py. Those calls live somewhere else in the pipeline (presumably sniper.py or scanner.py). If those upstream calls failed silently (e.g., due to 35.M-4's broken Postgres cursor type check), session_signals[ticker] never reaches 'ARMED' stage, and record_trade_executed() here also fails silently. The entire analytics chain from GENERATED → TRADED is only as strong as the weakest upstream call — and 35.M-4 means every step fails on Railway.
36.H-3 — metadata = metadata or get_ticker_screener_metadata(ticker) is called unconditionally before position_manager.open_position(), even though metadata is only used post-open (for Discord alert parameters: rvol, score, qualified). If get_ticker_screener_metadata() is slow (DB query + screening calculation), it adds latency to every arming path before the position is opened. For a 0DTE breakout where timing matters, a 200ms metadata fetch between signal detection and order submission is consequential. Should reorder: open position first, then fetch metadata for the alert.
36.H-4 — arm_ticker() has no timeout or deadline check. Between signal detection in sniper.py and arm_ticker() being called, bars may have advanced. There is no check whether entry_price is still the current price before submitting to position_manager. A signal detected at 10:00:00 that takes 500ms to pass validation and reach arm_ticker() by 10:00:00.5 could open a position at a price that has moved 0.3–0.5% beyond the intended entry. For a $200 stock at 0.3% slippage on 100 shares, that's a $60 implicit loss on entry. Should pass a max_slippage_pct guard into position_manager.open_position() or verify current_price - entry_price delta before calling.
🟠 Mediums (5) — arm_signal.py
ID	Issue
36.M-5	production_helpers import pattern: try: from utils.production_helpers import _send_alert_safe; PRODUCTION_HELPERS_ENABLED = True except ImportError: PRODUCTION_HELPERS_ENABLED = False. If production_helpers exists but _send_alert_safe is not defined in it (e.g., after a refactor), ImportError is not raised — AttributeError is raised instead and is not caught. PRODUCTION_HELPERS_ENABLED stays False, the else branch runs, and the full send_options_signal_alert() call fires directly — possibly duplicating the alert if production_helpers was partially loaded. Should catch both ImportError and AttributeError.
36.M-6	The else branch (direct send_options_signal_alert()) includes a full get_cached_greeks() lookup that the _send_alert_safe path does not. This means the production Railway path (where production_helpers exists) fires alerts without Greeks data while the local/fallback path includes Greeks. The two code paths are functionally divergent. Greeks data should be fetched before the branch and passed to both paths.
36.M-7	_set_cooldown(ticker, direction, signal_type) is called after the Discord alert. If the Discord alert raises an unhandled exception (e.g., network timeout not wrapped in try/except), _set_cooldown is never called. The ticker has an open position but no cooldown — the scanner could immediately detect a second signal on the same ticker and attempt to arm again before the first position's entry bar closes. Should call _set_cooldown immediately after position_id > 0 is confirmed, before any alert logic.
36.M-8	The "Phase 4 alert check" block at the bottom imports performance_monitor and send_simple_message then does nothing: # alert_manager not available; skip. This is dead code — two imports with no usage and a pass equivalent. Should be removed entirely or implemented.
36.M-9	log_proposed_trade(ticker, signal_type, direction, entry_price, confidence, grade) is called before position_manager.open_position(). If the position is rejected (position_id == -1), the proposed trade log still records it as a proposed entry. Downstream analysis of sniper_log will count rejected positions alongside accepted ones, inflating the "proposed trade" count. Should call log_proposed_trade only after position_id > 0 is confirmed, or add a status='REJECTED' parameter.
armed_signal_store.py
🔴 Criticals (0)
All DB functions use try/finally: return_conn(conn). ON CONFLICT (ticker) DO UPDATE correctly handles restarts where the same ticker re-arms. _USE_PG flag correctly branches the DATE(saved_at AT TIME ZONE ...) clause for Postgres vs SQLite. No criticals.

🟡 Highs (0) — armed_signal_store.py
The cleanest file in app/core/ so far. The use of sql_safe helpers (safe_execute, safe_query, safe_in_clause, get_placeholder) is the correct pattern — consistent with what Batch 26 identified as the gold standard.

🟠 Mediums (4) — armed_signal_store.py
ID	Issue
36.M-10	_ensure_armed_db() is called inside _maybe_load_armed_signals(). _maybe_load_armed_signals() is guarded by if _state.is_armed_loaded(): return — so _ensure_armed_db() only runs on first call. However, _persist_armed_signal() calls get_conn() directly without calling _ensure_armed_db() first. If _persist_armed_signal() is called before _maybe_load_armed_signals() (e.g., on the very first arm of the session before the scanner's startup _maybe_load runs), the table may not exist yet and the INSERT raises ProgrammingError: relation "armed_signals_persist" does not exist. Fix: add a lazy _ensure_armed_db() guard at the top of _persist_armed_signal() or ensure the table is always created at startup.
36.M-11	_cleanup_stale_armed_signals() calls position_manager.get_open_positions() to determine which position IDs are still live. If position_manager is unavailable (e.g., Tradier API down), get_open_positions() may raise or return an empty list. With an empty list, open_position_ids = set() — every armed signal is classified as stale and deleted from armed_signals_persist. On Tradier API reconnect, all active armed signals have been wiped from the DB and cannot be reloaded. Should add a guard: if not open_positions and len(rows) > 0: print warning; return rather than deleting everything when the API returns empty.
36.M-12	_load_armed_signals_from_db() calls _cleanup_stale_armed_signals() at the top before reading. This means every crash-restart sequence runs a cleanup pass before restoring state. If position_manager.get_open_positions() is slow on restart (Tradier auth latency), the cleanup blocks the entire armed signal reload. Should separate cleanup from load — run cleanup as a background/post-init task, not as a precondition of signal reload.
36.M-13	armed_signals_persist uses ticker TEXT PRIMARY KEY — one row per ticker. If a ticker has two concurrent positions (e.g., a partial position at 10:00 and a new entry at 11:30 after T1 hit and re-arm), ON CONFLICT DO UPDATE silently overwrites the first position's data with the second. The first position's stop/T1/T2 prices are lost from the persistence layer. The schema should include position_id in the primary key: PRIMARY KEY (ticker, position_id).
🟢 Lows (6)
ID	Issue
36.L-14	arm_signal.py: mode_label = " [OR]" if signal_type == "CFW6_OR" else " [INTRADAY]" — only two labels defined. A signal_type of "CFW6_BOS" or "RETEST" maps to " [INTRADAY]" which may not be accurate. Should map more signal types explicitly.
36.L-15	arm_signal.py: print(f"✅ {ticker} ARMED{mode_label}: ...") uses emoji directly in a print call. Railway log lines with emoji render inconsistently across log viewers (Railway dashboard, CloudWatch, Datadog). All print calls should be logger.info.
36.L-16	armed_signal_store.py: _now_et() is defined but only used nowhere in the file — it's a utility function defined for potential use but never called. Dead code. Should be removed or used in saved_at timestamp logic.
36.L-17	armed_signal_store.py: _cleanup_stale_armed_signals() defines p = get_placeholder(conn) but p is never used in that function — safe_in_clause and safe_execute handle parameterization internally. Dead variable.
36.L-18	armed_signal_store.py: Module-level _state = get_state() at line 15 runs get_state() on import. If thread_safe_state is not yet initialized when armed_signal_store is first imported, this could return a stale or uninitialized state object. get_state() presumably returns a singleton — verify that the singleton is guaranteed to be initialized before any armed_signal_store import.
36.L-19	arm_signal.py: The mtf_convergence_count block extracts len(mtf_result.get('timeframes', [])) but only if mtf_result.get('convergence') is truthy. If convergence=True but timeframes key is missing, len([]) = 0. A count of 0 MTF timeframes with convergence=True is contradictory — should validate timeframes list is non-empty before setting mtf_convergence_count.
Priority Fix Order (Batch 36)
Rank	ID	Fix
1	36.M-11	_cleanup_stale_armed_signals() empty-API guard — prevent wiping all armed signals on Tradier downtime
2	36.H-1	Wrap post-open_position() block in try/except with emergency close_position(position_id) on failure
3	36.M-7	Move _set_cooldown() to immediately after position_id > 0 — before any alert logic
4	36.H-3	Reorder: open position first, fetch screener metadata after
5	36.M-10	Add _ensure_armed_db() guard at top of _persist_armed_signal()
6	36.M-13	Change armed_signals_persist PK from ticker to (ticker, position_id)
7	36.M-12	Separate _cleanup_stale_armed_signals() from _load_armed_signals_from_db()
8	36.H-4	Add max_slippage_pct / current-price delta check before position open

**36.M-11 is the most dangerous finding in this batch** — a Tradier API outage during `_cleanup_stale_armed_signals()` returns an empty position list, causing the cleanup to delete every persisted armed signal from the DB. On reconnect, the system has no record of active positions and cannot monitor stops or T1/T2 targets for any of them. A single `if not open_positions and rows: return` guard prevents a catastrophic state wipe during API downtime.

**36.H-1** is the second priority — the 14-module deferred import chain means any broken downstream module after `open_position()` succeeds leaves a broker position open with no cooldown, no Discord alert, and no armed state. This is the "position orphan" scenario that's hardest to diagnose in production.
