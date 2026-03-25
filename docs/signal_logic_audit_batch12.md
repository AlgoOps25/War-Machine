# Signal Logic Audit — Batch 12

**Date:** 2026-03-18
**Scope:** `app/analytics/cooldown_tracker.py`, `app/analytics/performance_monitor.py`, `app/analytics/grade_gate_tracker.py`
**Total Findings:** 17 (2 Critical, 5 High, 6 Medium, 4 Low)

---

## 🔴 Criticals (2)

---

### 12.C-1 — `_maybe_load_cooldowns()` has the same TOCTOU race as 9.C-5 — flag set before DB load completes
**File:** `cooldown_tracker.py`

```python
def _maybe_load_cooldowns():
    global _cooldowns_loaded, _cooldown_cache
    if _cooldowns_loaded:
        return
    _cooldowns_loaded = True          # ← flag set BEFORE load
    _ensure_cooldown_table()
    _cooldown_cache.update(_load_cooldowns_from_db())
Two threads entering simultaneously both see _cooldowns_loaded = False. Thread A sets the flag to True and begins loading. Thread B sees True and returns immediately — but Thread A hasn't populated _cooldown_cache yet. Thread B calls is_on_cooldown() against an empty cache and returns False for every ticker, allowing duplicate signals to fire for any tickers currently on cooldown. This is the exact same pattern as 9.C-5 (armed_signal_store.py).

Fix: Use a load lock, set the flag only after the load completes:

python
_load_lock = threading.Lock()

def _maybe_load_cooldowns():
    global _cooldowns_loaded, _cooldown_cache
    with _load_lock:
        if _cooldowns_loaded:
            return
        _ensure_cooldown_table()
        _cooldown_cache.update(_load_cooldowns_from_db())
        _cooldowns_loaded = True  # set AFTER load completes
12.C-2 — _cleanup_expired_cooldowns() compares tz-aware ET datetime against naive DB timestamp — always deletes nothing on Postgres
File: cooldown_tracker.py

python
now = datetime.now(ZoneInfo("America/New_York"))
...
cur.execute(f"DELETE FROM signal_cooldowns WHERE expires_at < {p}", (now,))
expires_at is written by set_cooldown() as a tz-aware ET datetime. On SQLite this is stored as a string like "2026-03-18 14:30:00-04:00". On Postgres TIMESTAMP (without TZ) columns, psycopg2 strips the timezone on write, storing "2026-03-18 14:30:00" (naive). The DELETE WHERE expires_at < now_et comparison then pits a naive DB timestamp against a tz-aware Python object — Postgres raises cannot compare timestamp without time zone to timestamp with time zone, the except swallows it, and no expired cooldowns are ever cleaned up on Railway. Tickers stay in cooldown indefinitely until a manual clear_all_cooldowns().

Fix: Strip timezone before both writing and comparing:

python
now = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
And in set_cooldown():

python
expires_at = (now + timedelta(minutes=COOLDOWN_SAME_DIRECTION_MINUTES)).replace(tzinfo=None)
🟡 Highs (5)
12.H-3 — is_on_cooldown() deletes from _cooldown_cache and DB inside a read call — not thread-safe
File: cooldown_tracker.py

python
def is_on_cooldown(ticker, direction):
    ...
    if now >= cooldown["expires_at"]:
        del _cooldown_cache[ticker]         # ← mutates dict during read
        _remove_cooldown_from_db(ticker)    # ← DB write during read
        return False, None
_cooldown_cache is a plain dict. If two threads call is_on_cooldown() for the same expired ticker simultaneously, both see now >= expires_at, both call del _cooldown_cache[ticker] — the second del raises KeyError. The bare try/except in callers may swallow this, but it will also skip the cooldown check entirely for that ticker, allowing a duplicate signal.

Fix: Use _cooldown_cache.pop(ticker, None) instead of del. Wrap the expiry block in a lock or use a thread-safe data structure.

12.H-4 — performance_monitor._session is a module-level mutable dict — not thread-safe under concurrent signal callbacks
File: performance_monitor.py

python
_session: Dict = {
    'signals_generated': 0,
    ...
}

def record_signal_generated():
    _session['signals_generated'] += 1
_session counters are incremented from multiple threads (scanner loop, _fire_and_forget callbacks, Discord alert threads). Python's GIL protects individual bytecode operations but += on a dict value is a read-modify-write — not atomic. Under rapid concurrent calls, counts can be silently under-incremented. With a 30-ticker scan loop at 5s intervals, this is a realistic concurrency scenario.

Fix: Use threading.Lock() around all _session mutations, or replace integer counters with threading.atomic or collections.Counter protected by a lock.

12.H-5 — _check_risk_alerts() in performance_monitor has its own loss limit (-3%) duplicating position_manager's circuit breaker — two sources of truth
File: performance_monitor.py

python
_MAX_DAILY_LOSS_PCT = -3.0

def _check_risk_alerts(send_fn) -> bool:
    if _session['total_pnl_pct'] < _MAX_DAILY_LOSS_PCT:
        alerts.append(...)
    return _session['total_pnl_pct'] < _MAX_DAILY_LOSS_PCT
position_manager.check_circuit_breaker() uses config.MAX_DAILY_LOSS_PCT (default 3.0%). This module hardcodes -3.0% independently. If config.MAX_DAILY_LOSS_PCT is ever changed (e.g., to 2.0% for a conservative session), performance_monitor will still alert/halt at 3.0% — the two systems will disagree on when to stop trading. Additionally, _session['total_pnl_pct'] is tracked in percentage points using record_trade_outcome(pnl_pct) which is never called anywhere in the codebase (see 12.H-6 below).

Fix: Read the limit from config: _MAX_DAILY_LOSS_PCT = -getattr(config, "MAX_DAILY_LOSS_PCT", 3.0). Remove the independent halt logic — delegate halt decisions to position_manager.check_circuit_breaker().

12.H-6 — record_trade_outcome() in performance_monitor is never called — P&L tracking is dead
File: performance_monitor.py

performance_monitor.record_trade_outcome(pnl_pct) is defined and drives wins, losses, total_pnl_pct, peak_pnl_pct, and max_drawdown_pct. However, a search of the codebase shows it is never called from position_manager.close_position(), sniper.py, or anywhere else. The PerformanceMonitor.get_daily_stats() always returns wins=0, losses=0, total_pnl_pct=0.0. The drawdown alert in _check_risk_alerts() never fires because max_drawdown_pct never exceeds 0. The Phase 4 performance dashboard prints zeros all day.

Fix: Call performance_monitor.record_trade_outcome(pnl_pct) from position_manager.close_position() after computing final_pnl. Convert dollar P&L to percentage: pnl_pct = final_pnl / position_manager.session_starting_balance * 100.

12.H-7 — _ensure_table() and _ensure_cooldown_table() are called at module import time — DB connections on every Railway cold start before env validation
File: cooldown_tracker.py, performance_monitor.py, grade_gate_tracker.py

All three modules call their DB init function at module scope:

python
_ensure_cooldown_table()   # cooldown_tracker.py — module level
_ensure_table()            # performance_monitor.py — module level
_ensure_table()            # grade_gate_tracker.py — module level
Same pattern as 9.C-3 and 10.H-10. These run at import time before validate_required_env_vars(), causing cryptic psycopg2 errors if DATABASE_URL is missing. They also bind DB connections during test imports.

Fix: Move all _ensure_* calls into the first function that actually needs the table (lazy init), or gate them behind a _initialized flag checked at first use.

🟠 Mediums (6)
ID	File	Issue
12.M-8	cooldown_tracker.py	_ensure_cooldown_table() uses a bare conn.cursor() without dict_cursor — fine for DDL, but the cursor is never explicitly closed. On Postgres, unclosed cursors hold server-side resources. Use with conn.cursor() as cursor: or explicitly call cursor.close().
12.M-9	cooldown_tracker.py	is_on_cooldown() for a reversal scenario clears the cooldown (del + _remove_cooldown_from_db) when time_left <= COOLDOWN_OPPOSITE_DIRECTION_MINUTES. This means a reversal is allowed 15 minutes after the original signal — but only if the reversal is checked exactly when time_left crosses 15. If the scanner misses that exact cycle (e.g., restart), the next check at 14 minutes will still see the cooldown and block the reversal. The reversal window is effectively 1 cycle wide, not 15 minutes.
12.M-10	performance_monitor.py	_dashboard_cycle_counter and _alert_cycle_counter are module-level globals incremented from check_performance_dashboard() and check_performance_alerts(). After a Railway redeploy mid-session, both counters reset to 0. The dashboard and alert checks will fire immediately on the first cycle post-restart instead of waiting the intended 5-minute / 100-second interval. Minor, but produces log noise.
12.M-11	performance_monitor.py	_consecutive_losses is declared as a global in _check_risk_alerts() but is never incremented or read. The _MAX_CONSECUTIVE_LOSS = 3 threshold and the consecutive-loss alert path are entirely dead code.
12.M-12	grade_gate_tracker.py	record_gate_rejection() contains dead code: label = 'passed' if False else 'rejected'. The variable label is assigned but never used. Remove it.
12.M-13	cooldown_tracker.py	CooldownTracker.__init__() accepts cooldown_minutes parameter but never uses it — the module-level COOLDOWN_SAME_DIRECTION_MINUTES constant is always used instead. The legacy shim silently ignores any custom cooldown duration passed by old callers.
🟢 Lows (4)
ID	File	Issue
12.L-14	performance_monitor.py	print("[PERF-MONITOR] ✅ Initialized ...") fires at module import. Combined with 12.H-7, this means every test import prints to stdout. Move to a lazily-called initialize() function.
12.L-15	grade_gate_tracker.py	Same: print("[GRADE-GATE-TRACKER] ✅ Initialized ...") fires at import.
12.L-16	cooldown_tracker.py	_load_cooldowns_from_db() calls _cleanup_expired_cooldowns() as its first step. _cleanup_expired_cooldowns() opens its own DB connection, then _load_cooldowns_from_db() opens a second. Two pooled checkouts for one startup operation. Combine into a single connection.
12.L-17	All three files	All print() calls should be logger.*. Same pattern flagged in batches 8–11.
Priority Fix Order
12.C-2 — tz-aware vs naive comparison on Postgres — expired cooldowns never cleaned up on Railway

12.C-1 — TOCTOU race in _maybe_load_cooldowns() — duplicate signals during concurrent startup

12.H-6 — record_trade_outcome() never called — Phase 4 P&L dashboard always shows zeros

12.H-3 — del _cooldown_cache[ticker] inside read path — KeyError under concurrent access

12.H-5 — Hardcoded -3.0% loss limit duplicates position_manager circuit breaker

12.H-7 — DB init at import time across all three modules — blocks env validation on startup

12.M-11 — _consecutive_losses never incremented — consecutive-loss alert is dead code