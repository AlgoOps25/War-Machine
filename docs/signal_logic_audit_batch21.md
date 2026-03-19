# Signal Logic Audit — Batch 21

**Date:** 2026-03-18
**Scope:** `app/core/thread_safe_state.py`, `app/core/arm_signal.py`,
           `app/core/armed_signal_store.py`, `app/core/watch_signal_store.py`
**Total Findings:** 19 (1 Critical, 4 High, 8 Medium, 6 Low)

---

## 🔴 Criticals (1)

---

### 21.C-1 — `ThreadSafeState` uses a double-checked locking (DCL) singleton pattern with a class-level `_lock` and `_instance`. This is correct in Python 3 for thread safety at creation time. However, `_initialize()` is called **inside** `__new__` after the instance is assigned to `cls._instance` — meaning any thread that enters `__new__` and passes the outer `if cls._instance is None` check, then blocks on `with cls._lock`, will wait. The thread that holds the lock sets `cls._instance` and calls `_initialize()`. If `_initialize()` raises an exception (e.g., `threading.Lock()` fails, which is possible under OS thread exhaustion), `cls._instance` is already set to a **partially initialized object** — every subsequent call to `ThreadSafeState()` returns the broken partial instance without re-initializing. The singleton is poisoned for the rest of the process lifetime.

**File:** `thread_safe_state.py` → `__new__()` / `_initialize()`

```python
cls._instance = super().__new__(cls)
cls._instance._initialize()           # if this raises, _instance is a broken shell
Fix: Only assign cls._instance after _initialize() succeeds:

python
instance = super().__new__(cls)
instance._initialize()        # if this raises, _instance remains None
cls._instance = instance      # only set after clean init
🟡 Highs (4)
21.H-2 — arm_signal.py imports from app.core.sniper_log import log_proposed_trade at function entry. sniper_log.py was deleted (confirmed by sniper.py Batch 19 stub: app.core.sniper_log not found — using stub). In arm_signal.py this import is NOT wrapped in a try/except — it is a hard import. When sniper_log.py is absent, arm_signal() raises ModuleNotFoundError at call time, killing the arm attempt silently (the caller in sniper.py does not wrap arm_ticker() in a try/except). Every signal that passes all gates is silently dropped at the arming stage.
File: arm_signal.py → function body, line ~14

python
from app.core.sniper_log import log_proposed_trade   # hard import — no try/except
Fix: Wrap with fallback stub, matching the pattern in sniper.py:

python
try:
    from app.core.sniper_log import log_proposed_trade
except ImportError:
    def log_proposed_trade(*args, **kwargs): pass
21.H-3 — arm_signal.py imports from app.screening.screener_integration import get_ticker_screener_metadata as a hard import — also no try/except. screener_integration is wrapped with a stub in sniper.py (Batch 19 confirmed the module missing). In arm_signal.py it is a hard import, so the same silent kill applies: any arm_ticker() call on a system where screener_integration is absent raises ModuleNotFoundError before reaching position_manager.open_position().
File: arm_signal.py → function body, line ~13

python
from app.screening.screener_integration import get_ticker_screener_metadata  # hard import
Fix:

python
try:
    from app.screening.screener_integration import get_ticker_screener_metadata
except ImportError:
    def get_ticker_screener_metadata(ticker):
        return {'qualified': False, 'score': 0, 'rvol': 0.0, 'tier': None}
21.H-4 — _cleanup_stale_armed_signals() in armed_signal_store.py calls position_manager.get_open_positions() to build open_position_ids, then does a DB query for all rows in armed_signals_persist, and deletes those whose position_id is not in the open set. This function is called inside _load_armed_signals_from_db(), which is called from _maybe_load_armed_signals(), which is called from process_ticker() — in the hot scan loop. get_open_positions() is itself a DB query (pool checkout). This means every call to _maybe_load_armed_signals() that runs on the first cycle triggers: DB checkout #1 (get_open_positions) + DB checkout #2 (select all armed rows) + DB checkout #3 (delete stale). Three pool checkouts for a cleanup function, called at scan startup. The _state.is_armed_loaded() gate prevents re-runs after the first load — but the first load happens at the most expensive moment: OR open, 50 tickers, 5-second scan interval.
Fix: Move _cleanup_stale_armed_signals() out of _load_armed_signals_from_db() and into the EOD cleanup block in scanner.py, where it can run once at market close with no scan-cycle pressure. At startup load, trust the saved_at date filter to exclude stale entries.

21.H-5 — watch_signal_store.py defines _strip_tz() locally. armed_signal_store.py has no _strip_tz() but _load_armed_signals_from_db() returns raw datetime objects from the DB without timezone stripping. sniper.py imports _strip_tz from utils.time_helpers and uses it when resolving breakout_bar_dt from the watch state. Inconsistent timezone handling: watch signals are stripped on load; armed signals are not. If the DB returns timezone-aware datetimes for armed signals (PostgreSQL TIMESTAMP WITH TIME ZONE behavior), comparisons with naive datetimes in sniper.py will raise TypeError: can't compare offset-naive and offset-aware datetimes.
Fix: Both store modules should import and apply _strip_tz from utils.time_helpers on all datetime fields during load. Add _strip_tz to armed_signal_store._load_armed_signals_from_db() for all datetime-typed columns, consistent with watch_signal_store.

🟠 Mediums (8)
ID	File	Issue
21.M-6	thread_safe_state.py	_last_dashboard_check and _last_alert_check are initialized with datetime.now() (no timezone). Every other datetime in the system uses _now_et() (Eastern). If update_last_dashboard_check() is called with a tz-aware ET datetime, comparing it to the naive initial value will raise TypeError. The initialization should use datetime.now(ZoneInfo("America/New_York")).
21.M-7	thread_safe_state.py	_validation_call_tracker grows unbounded during the session — one entry per unique signal_id. Never cleared except by explicit clear_validation_call_tracker() call, which is not called anywhere in sniper.py or scanner.py. After a full trading day, the tracker holds hundreds of stale entries. Should auto-prune on EOD clear or cap at a max size.
21.M-8	thread_safe_state.py	The singleton _state is created at module load with _state = ThreadSafeState(). In Railway, module-level code runs at import time. If threading.Lock() raises (OS thread exhaustion), the module fails to import. No fallback. Low risk but same pattern as 20.L-16 — should be wrapped.
21.M-9	arm_signal.py	The Phase 4 alert check block at the bottom imports performance_monitor and send_simple_message but then does nothing — # alert_manager not available; skip and pass. This is a dead code block that runs two deferred imports on every arm_ticker() call and discards them. Remove the entire try/except block.
21.M-10	arm_signal.py	greeks_data construction in the else (non-production-helpers) branch calls get_cached_greeks(ticker, direction) — this is a second Greeks fetch. The OPTIONS_PRE_GATE block in sniper.py already fetched and cached Greeks earlier in the pipeline. The call in arm_signal.py fetches from cache (not live), so it is not an extra API hit — but it is redundant data retrieval. The Greeks data from the pre-gate should be passed into arm_ticker() as a parameter rather than re-fetched here.
21.M-11	armed_signal_store.py	_ensure_armed_db() is called on every _maybe_load_armed_signals() call — this runs CREATE TABLE IF NOT EXISTS against the DB on startup. On PostgreSQL, DDL inside a transaction that is then committed is fine, but CREATE TABLE IF NOT EXISTS still acquires a lock. On Railway's managed Postgres, schema DDL at boot is acceptable but should be idempotent and logged at INFO level. Currently it prints nothing on success.
21.M-12	watch_signal_store.py	_cleanup_stale_watches() uses cutoff_time = _now_et() - timedelta(minutes=MAX_WATCH_BARS * 5) — MAX_WATCH_BARS = 12, so cutoff is 60 minutes ago. This means a BOS watch that fires at 9:32 AM and is never confirmed will be cleaned up by 10:32 AM. But _cleanup_stale_watches() is only called inside _load_watches_from_db(), which is called once per session via _maybe_load_armed_signals(). Stale watches from the previous session are cleaned on first startup load, but intraday stale watches (BOS at 9:32, no FVG by 9:44, watch entry survives in DB until next restart) are never cleaned mid-session.
21.M-13	watch_signal_store.py	send_bos_watch_alert() calls send_simple_message() — this fires to the main Discord channel. BOS watch alerts are high-frequency (every breakout detection). At OR open with 30 tickers and 5-second scans, 3–5 BOS events per minute is normal. No rate limit, no deduplification at the Discord layer. A 30-ticker scan cycle could fire 30 Discord messages in 2.5 minutes if all tickers trigger BOS simultaneously on a gap day. Should use a per-ticker cooldown or the WATCH_CHANNEL_WEBHOOK if one is configured.
🟢 Lows (6)
ID	File	Issue
21.L-14	thread_safe_state.py	Module-level print("[THREAD-SAFE-STATE] ✅ Module initialized...") fires at every import. Same issue flagged across all batches. Replace with logger.debug() or remove.
21.L-15	arm_signal.py	PRODUCTION_HELPERS_ENABLED is set as a local variable inside arm_ticker() — defined and immediately used for a one-time branch, then discarded. There is no benefit to a variable here vs. a direct try/except around the call. Minor readability issue.
21.L-16	arm_signal.py	mtf_convergence_count = None is set before the if mtf_result check. If mtf_result is None (no MTF data), mtf_convergence_count stays None and is passed to send_options_signal_alert(mtf_convergence=None). The alert formatter needs to handle None gracefully — no defensive check here, relies on downstream robustness. Low risk but should be documented.
21.L-17	armed_signal_store.py	_now_et() defined locally. Same three-definition issue as scanner.py (20.L-20) and sniper.py. Import from utils.time_helpers.
21.L-18	watch_signal_store.py	_now_et() and _strip_tz() both defined locally in watch_signal_store.py. _strip_tz is also defined in utils/time_helpers.py. Import from canonical location.
21.L-19	watch_signal_store.py	MAX_WATCH_BARS = 12 is defined as a module-level constant mirrored from sniper.py — the comment says "mirrored from sniper". Two sources of truth. If sniper.py changes the watch window to 15 bars, watch_signal_store.py stale cleanup cutoff stays at 12 bars. Should be imported from utils/config.py as a single constant.
Priority Fix Order
21.H-2 — Hard import of deleted sniper_log.py in arm_signal.py — every armed signal is silently dropped at the arming stage if the module is absent

21.H-3 — Hard import of screener_integration in arm_signal.py — same silent kill

21.C-1 — Singleton poisoning if _initialize() raises — broken _state object for entire process lifetime

21.H-4 — Triple DB checkout inside startup scan cycle during OR open — pool pressure at worst possible moment

21.H-5 — Timezone-naive/aware mismatch on armed signal datetime fields — TypeError risk in sniper.py comparisons

21.M-9 — Dead code Phase 4 block in arm_ticker() imports two modules and does nothing — remove

21.L-19 — MAX_WATCH_BARS duplicated constant — move to config.py

