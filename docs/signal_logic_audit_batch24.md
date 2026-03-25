Full Batch 24 audit below.

File: docs/signal_logic_audit_batch24.md
text
# Signal Logic Audit — Batch 24

**Date:** 2026-03-18
**Scope:** `app/analytics/cooldown_tracker.py`, `app/analytics/funnel_analytics.py`,
           `app/analytics/performance_monitor.py`
**Total Findings:** 19 (0 Critical, 5 High, 8 Medium, 6 Low)

---

## 🔴 Criticals (0)

Clean. No critical findings in this batch.

---

## 🟡 Highs (5)

---

### 24.H-1 — `cooldown_tracker.py` calls `return_conn(conn)` in `finally` blocks **without a `conn is not None` guard** in several functions (`_ensure_cooldown_table`, `_persist_cooldown`, `_remove_cooldown_from_db`, `_cleanup_expired_cooldowns`, `_load_cooldowns_from_db`, `clear_all_cooldowns`). If `get_conn()` raises an exception, `conn` is `None` and `return_conn(None)` is called. Whether this is safe depends entirely on `return_conn`'s implementation. In `db_connection.py` (Batch 17), `return_conn(None)` was confirmed to raise `AttributeError` — meaning the exception handler itself raises, masking the original exception with an unrelated `AttributeError`. All six functions are affected.

**Fix:** Add the guard to every `finally` block:
```python
finally:
    if conn:
        return_conn(conn)
This is the same pattern used correctly in armed_signal_store.py and watch_signal_store.py.

24.H-2 — cooldown_tracker._load_cooldowns_from_db() loads expires_at from DB as either a datetime or an ISO string (handled by datetime.fromisoformat()). On PostgreSQL, expires_at is stored as a TIMESTAMP column — psycopg2 returns it as a timezone-aware datetime if the column is TIMESTAMP WITH TIME ZONE, or as a naive datetime if TIMESTAMP (which is what the CREATE TABLE uses). The is_on_cooldown() function compares now >= cooldown["expires_at"] where now = datetime.now(ZoneInfo("America/New_York")) — a timezone-aware datetime. Comparing a tz-aware now against a tz-naive expires_at loaded from Postgres raises TypeError: can't compare offset-naive and offset-aware datetimes. This is the same timezone mismatch flagged in Batch 21 (21.H-5) — and it's in the hot path: every signal check goes through is_on_cooldown().
Fix: Normalize expires_at on load with _strip_tz() from utils.time_helpers, OR change the signal_cooldowns table column to TIMESTAMP WITH TIME ZONE and ensure psycopg2 returns aware datetimes. Consistent with the pattern, use _strip_tz() and compare with datetime.now() (naive) throughout.

24.H-3 — funnel_analytics.FunnelTracker._initialize_database() runs DDL (CREATE TABLE IF NOT EXISTS + two CREATE INDEX IF NOT EXISTS) at instantiation time — called at module load via funnel_tracker = FunnelTracker() (module-level singleton). This is three DB operations at import time. funnel_analytics.py is imported by scanner.py at the top level. On a cold Railway boot with a slow Postgres connection, this adds latency to the import chain before the health server even starts. Same pattern as ai_learning.py (23.C-1) — should be lazy-initialized or deferred until first record_stage() call.
24.H-4 — performance_monitor.py calls _ensure_table() at module level (not in a class __init__ — at the raw module scope, outside any function). This means _ensure_table() runs on every import of performance_monitor. Since _ensure_table() does get_conn() → CREATE TABLE IF NOT EXISTS → return_conn(), this is a DB pool checkout at import time. Every import of performance_monitor (e.g., from sniper.py, scanner.py, arm_signal.py) fires this, though Python's module cache ensures it runs only once per process. Still — DDL at module scope is the same category as 23.C-1 and 24.H-3.
24.H-5 — performance_monitor._session is a module-level mutable dict. All record_* functions mutate it with no thread lock (_session['signals_generated'] += 1, etc.). record_trade_outcome() mutates three keys in sequence:
python
_session['total_pnl_pct'] += pnl_pct
if _session['total_pnl_pct'] > _session['peak_pnl_pct']:
    _session['peak_pnl_pct'] = _session['total_pnl_pct']
drawdown = _session['peak_pnl_pct'] - _session['total_pnl_pct']
In Python, dict[key] += value is not atomic. If two threads call record_trade_outcome() simultaneously (possible once position_manager's close-position path is parallelized), the read-modify-write on total_pnl_pct races, peak_pnl_pct can be set from a stale total_pnl_pct, and max_drawdown_pct can be computed from an inconsistent state. The _consecutive_losses global in _check_risk_alerts() has the same issue. Add a module-level threading.Lock.

🟠 Mediums (8)
ID	File	Issue
24.M-6	cooldown_tracker.py	is_on_cooldown() deletes expired entries from _cooldown_cache and calls _remove_cooldown_from_db() lazily, one DB round-trip per expired ticker per check. For a 50-ticker scan cycle where 10 cooldowns expire between cycles, this is 10 individual DB DELETEs. Should batch-delete in _cleanup_expired_cooldowns() instead.
24.M-7	cooldown_tracker.py	set_cooldown() always uses COOLDOWN_SAME_DIRECTION_MINUTES (30 min) for expires_at, regardless of direction. An opposite-direction reversal allowed through is_on_cooldown() (time_left <= 15 min) then has its new cooldown set for 30 min from now. The reversal cooldown should be shorter (15 min), not the same as the original.
24.M-8	cooldown_tracker.py	CooldownTracker.__init__() accepts cooldown_minutes=15 but the module-level constant is COOLDOWN_SAME_DIRECTION_MINUTES=30. The instance is created as cooldown_tracker = CooldownTracker(cooldown_minutes=30) — matching the constant. But the class constructor parameter (15 default) and the module constant (30) are different defaults. Any old caller constructing CooldownTracker() without arguments gets a cooldown_minutes=15 instance that the class never actually uses (all calls delegate to module-level functions). The parameter is dead — document or remove it.
24.M-9	funnel_analytics.py	get_stage_conversion(), get_rejection_reasons(), and get_hourly_breakdown() each open a new DB connection per call. get_daily_report() calls get_stage_conversion() once per stage (7 stages) — 7 DB checkouts in sequence for a single report. Should pass a shared cursor/connection into the read methods or use a single query with GROUP BY stage.
24.M-10	funnel_analytics.py	record_stage() acquires a DB connection on every single funnel event — including high-frequency stages like SCREENED and BOS which fire for every ticker in every scan cycle. At 50 tickers × 2 stages × 12 scans/hour = 1,200 DB inserts per hour minimum. Each is a separate pool checkout + commit. Should buffer writes (e.g., batch INSERT every N events or on a timer) rather than one connection per event.
24.M-11	funnel_analytics.py	get_daily_report() uses self.STAGES.index(stage)-1 to get the previous stage name for the "X% of PREV" label. If stage == self.STAGES[0] ("SCREENED"), index - 1 = -1, which in Python returns the last element of the list ("FILLED"). The "prev_passed is not None" check prevents this from producing wrong output currently — but if the logic changes, SCREENED's line would read "X% of FILLED" which is wrong. Should use enumerate.
24.M-12	performance_monitor.py	_MAX_DAILY_LOSS_PCT, _MAX_DRAWDOWN_PCT, and _MAX_CONSECUTIVE_LOSS are module-level constants with no config.py entry. These are risk management thresholds — the most operationally critical constants in the system. They must be in config.py and overridable via env vars (e.g., MAX_DAILY_LOSS_PCT=-3.0). Hardcoded in an analytics module, they will be missed when tuning risk parameters.
24.M-13	performance_monitor.py	_check_risk_alerts() fires alerts on every call as long as the condition is true — there is no "already alerted" flag. check_performance_alerts() is called every 20 cycles (~100 seconds). Once daily P&L drops below -3%, Discord receives an alert every 100 seconds for the rest of the trading day. No cooldown on alert re-fire. Add a _halt_alerted flag set on first trigger, cleared at EOD reset.
🟢 Lows (6)
ID	File	Issue
24.L-14	cooldown_tracker.py	_cleanup_expired_cooldowns() uses datetime.now(ZoneInfo("America/New_York")) locally. _now_et() pattern is the same as every other module — import from utils.time_helpers.
24.L-15	cooldown_tracker.py	print(f"[COOLDOWN] {ticker} {direction.upper()} cooldown until...") in set_cooldown(). All other analytics modules use logger. Replace with logger.info().
24.L-16	funnel_analytics.py	print("[FUNNEL] Funnel analytics database initialized") at DDL init — fires on every Railway boot. Replace with logger.debug() or remove (DDL success does not need an INFO-level announcement).
24.L-17	funnel_analytics.py	The __main__ block at the bottom (if __name__ == "__main__":) inserts live records into the funnel_events table using the production DB connection. Running python -m app.analytics.funnel_analytics on Railway staging would pollute today's session data with test records. The test block should use a test session string (e.g., "TEST-2026-03-18") or be removed.
24.L-18	performance_monitor.py	print("[PERF-MONITOR] ✅ Initialized — Phase 4 performance tracking active") at module level fires on every import. Same issue across every batch. Replace with logger.debug() or remove.
24.L-19	performance_monitor.py	check_performance_dashboard() and check_performance_alerts() accept state as their first parameter but never use it. The state object (ThreadSafeState) is passed in from sniper.py but the functions only read/write module-level globals. The parameter is dead API surface — remove it or document that it is reserved for future use.
Priority Fix Order
24.H-1 — Missing conn is not None guards in 6 cooldown_tracker finally blocks — return_conn(None) raises AttributeError masking the original exception in the hot signal-check path

24.H-2 — Tz-aware vs tz-naive expires_at comparison in is_on_cooldown() — TypeError on every cooldown check after a Railway restart that loads from Postgres

24.M-13 — Risk alert re-fires every 100s indefinitely once threshold is breached — Discord flood for rest of trading day

24.H-5 — Unprotected _session dict mutations — thread-unsafe record_trade_outcome() and _consecutive_losses counter

24.M-12 — Risk thresholds (_MAX_DAILY_LOSS_PCT etc.) hardcoded — must be in config.py with env-var overrides

24.H-3 / 24.H-4 — DDL at module-level import in both funnel_analytics and performance_monitor — boot latency and connection pressure

24.M-10 — record_stage() one DB checkout per funnel event — 1,200+ checkouts/hour at normal scan cadence


