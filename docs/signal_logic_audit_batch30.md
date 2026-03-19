Full Batch 30 audit below.

File: docs/signal_logic_audit_batch30.md
text
# Signal Logic Audit — Batch 30

**Date:** 2026-03-18
**Scope:** `app/analytics/` — directory inventory + deep audit of
           `cooldown_tracker.py` and `explosive_mover_tracker.py`
**Files in layer:** 10 (auditing 2 this batch, 8 remaining across Batches 31–32)
**Total Findings:** 19 (0 Critical, 4 High, 8 Medium, 7 Low)

---

## Layer Inventory

| File | Size | Notes |
|------|------|-------|
| `__init__.py` | 1.2 KB | Thin re-exports |
| `ab_test.py` | 3.3 KB | A/B test utilities |
| `ab_test_framework.py` | 9.8 KB | Full framework — next batch |
| `cooldown_tracker.py` | 9.8 KB | ✅ This batch |
| `explosive_mover_tracker.py` | 15.4 KB | ✅ This batch |
| `explosive_tracker.py` | 0.8 KB | Stub shim — next batch |
| `funnel_analytics.py` | 13.9 KB | Next batch |
| `funnel_tracker.py` | 4.1 KB | Next batch |
| `grade_gate_tracker.py` | 7.9 KB | Next batch |
| `performance_monitor.py` | 12.6 KB | Next batch |

---

## `cooldown_tracker.py`

---

## 🔴 Criticals (0)

The DB-backed persistence pattern with in-memory cache-first + lazy load is sound. Connection lifecycle follows `get_conn()` / `return_conn()` with `try/finally` in every helper. No criticals.

---

## 🟡 Highs (2)

---

### 30.H-1 — `is_on_cooldown()` has a **tz-aware vs naive datetime comparison** that will raise `TypeError` on Railway Postgres:

```python
now = datetime.now(ZoneInfo("America/New_York"))  # ← tz-AWARE
if now >= cooldown["expires_at"]:                  # ← naive if loaded from DB
_load_cooldowns_from_db() parses expires_at as:

python
row["expires_at"] if isinstance(row["expires_at"], datetime)
else datetime.fromisoformat(str(row["expires_at"]))
On Postgres, TIMESTAMP columns return naive datetime objects (no tzinfo). datetime.fromisoformat(str(...)) on a naive Postgres timestamp also produces a naive datetime. So cooldown["expires_at"] is naive. now is tz-aware (ET). now >= cooldown["expires_at"] raises TypeError: can't compare offset-naive and offset-aware datetimes. This error is raised inside is_on_cooldown() which has no try/except — it propagates to the sniper, which would crash or skip the cooldown check entirely depending on the caller's error handling. The fix is to strip now of tzinfo before comparison: now = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None) — consistently with the rest of the codebase's ET-naive convention.

This same tz mismatch occurs in set_cooldown() (stores now + timedelta(...) where now is tz-aware into expires_at), get_active_cooldowns() (compares now < c["expires_at"] where cache has tz-aware values from set_cooldown() but DB-loaded values are naive), and _cleanup_expired_cooldowns() (passes tz-aware now as DB parameter — Postgres will handle the comparison correctly, but SQLite will compare string representations and fail silently).

30.H-2 — _maybe_load_cooldowns() is not thread-safe:
python
def _maybe_load_cooldowns():
    global _cooldowns_loaded, _cooldown_cache
    if _cooldowns_loaded:
        return
    _cooldowns_loaded = True           # ← set True BEFORE load completes
    _ensure_cooldown_table()
    _cooldown_cache.update(_load_cooldowns_from_db())
Two threads calling is_on_cooldown() simultaneously on first access both see _cooldowns_loaded = False. Thread A sets _cooldowns_loaded = True and begins _load_cooldowns_from_db(). Thread B checks, sees True, and returns immediately — with _cooldown_cache still empty. Thread B then sees no cooldowns for any ticker and fires a duplicate signal. The scanner and sniper run on separate threads — this race is plausible at market open when both are initializing. Fix: protect with a threading.Lock() using double-checked locking pattern.

🟠 Mediums (4) — cooldown_tracker.py
ID	Issue
30.M-3	_remove_cooldown_from_db() is called from is_on_cooldown() when an expired cooldown is found in the cache. This means a DB write fires on every cooldown check for a ticker once its cooldown expires, not just when a new signal sets a cooldown. With 50 tickers being checked every scan cycle, expired-but-cached cooldowns trigger 50 individual DELETE statements per cycle until the cache entries age out. Should only persist the removal on explicit clear_cooldown() and let natural cache TTL expire the entry.
30.M-4	CooldownTracker.__init__() takes cooldown_minutes: int = 15 but this value is never used — all actual timing is controlled by module-level constants COOLDOWN_SAME_DIRECTION_MINUTES = 30 and COOLDOWN_OPPOSITE_DIRECTION_MINUTES = 15. The cooldown_tracker = CooldownTracker(cooldown_minutes=COOLDOWN_SAME_DIRECTION_MINUTES) singleton passes 30 but it has no effect. Any caller creating CooldownTracker(cooldown_minutes=5) for a tighter cooldown would see no change.
30.M-5	_ensure_cooldown_table() uses bare conn.cursor() without dict_cursor(). It then calls conn.cursor().execute(...) — creating a fresh cursor each call rather than reusing one. On Postgres, each conn.cursor() is lightweight, but combined with the missing return_conn(conn) path on success (only the finally block protects), this is a minor resource pattern inconsistency with the rest of the codebase.
30.M-6	clear_all_cooldowns() resets _cooldowns_loaded = False. The next call to _maybe_load_cooldowns() will reload from DB — but the DB was just cleared. This means clearing all cooldowns triggers an unnecessary DB read immediately after the write. Should keep _cooldowns_loaded = True after a clear (cache is now authoritative: empty).
🟢 Lows (3) — cooldown_tracker.py
ID	Issue
30.L-7	get_active_cooldowns() computes minutes_remaining as int((...).total_seconds() / 60). For a cooldown expiring in 89 seconds, this returns 1 minute — technically correct (floor), but when displayed in print_cooldown_summary() as "1m", it could mean anywhere from 1 to 119 seconds. Consider math.ceil() to avoid showing "1m" when 89 seconds remain.
30.L-8	print_cooldown_summary() prints nothing when there are no active cooldowns (if not active: return). During a quiet session this is fine. But it means a caller who explicitly requests a summary (e.g., EOD report) gets no output and no confirmation of empty state. Should print "[COOLDOWN] No active cooldowns".
30.L-9	The ZoneInfo("America/New_York") object is instantiated fresh on every call to is_on_cooldown(), set_cooldown(), get_active_cooldowns(), and _cleanup_expired_cooldowns(). Python's zoneinfo module caches these internally, so it's not expensive — but it's inconsistent with the rest of the codebase which defines ET = ZoneInfo("America/New_York") once at module level.
explosive_mover_tracker.py
🟡 Highs (2) — explosive_mover_tracker.py
30.H-10 — _ensure_explosive_override_table(), track_explosive_override(), update_override_outcome(), get_daily_override_stats(), and get_threshold_optimization_data() all call conn.close() instead of return_conn(conn). This is pool-bypassing connection disposal — identical to the pattern fixed in FIX #4 for data_manager.py. On Postgres with db_connection.py's pool, conn.close() closes the underlying TCP socket rather than returning the connection to the pool. Every call to any function in this file permanently consumes one pool slot. After 12 calls (the DB_SEMAPHORE_LIMIT), the pool is exhausted. Given track_explosive_override() is called on every explosive override signal and get_daily_override_stats() is called periodically, this is an active pool drain. All conn.close() calls must be replaced with try/finally: return_conn(conn).
30.H-11 — get_daily_override_stats() and get_threshold_optimization_data() use SQLite-style ? placeholders hardcoded in the query strings:
python
cursor.execute(
    "SELECT COUNT(*) FROM explosive_mover_overrides WHERE DATE(timestamp) = ?",
    (today,)
)
On Postgres, the placeholder must be %s. The ph() helper from db_connection.py returns the correct placeholder for the active backend. These functions never call ph() — they hardcode ?. On Railway Postgres, every get_daily_override_stats() call raises psycopg2.errors.SyntaxError: syntax error at or near "$1" (or similar) and returns {}. The entire explosive override reporting layer is silently broken on production. Fix: use ph() consistently.

🟠 Mediums (4) — explosive_mover_tracker.py
ID	Issue
30.M-12	_ensure_explosive_override_table() is called at module import time (line after the function definition: _ensure_explosive_override_table()). Unlike cooldown_tracker.py's lazy _maybe_load_cooldowns(), this fires a DB connection + DDL statement on every import. On Railway cold start, if Postgres is not yet accepting connections, the import itself raises an exception, causing an ImportError in anything that imports explosive_mover_tracker. Should be deferred to first use (same lazy pattern as cooldown_tracker).
30.M-13	update_override_outcome() executes ORDER BY timestamp DESC LIMIT 1 inside an UPDATE statement. This is valid PostgreSQL but invalid SQLite (UPDATE ... ORDER BY ... LIMIT is not standard SQL). On SQLite (local dev), this raises OperationalError. On Postgres (Railway), it works. The codebase runs SQLite locally and Postgres on Railway — this function silently fails in all local testing. Fix: use a subquery WHERE id = (SELECT id FROM ... ORDER BY timestamp DESC LIMIT 1).
30.M-14	track_explosive_override() updates _daily_stats before the DB insert. If the DB insert fails (pool exhaustion, connection error), _daily_stats['total_overrides'] has already been incremented and _override_signals[ticker] has already been set. The session-level in-memory stats are now out of sync with the DB. The override appears tracked in memory but has no DB record. update_override_outcome() will try to update a row that doesn't exist and silently do nothing. Reverse the order: update DB first, update in-memory state only on success.
30.M-15	get_threshold_optimization_data() uses DATE(timestamp) >= ? for date filtering. On Postgres, DATE(timestamp) with a ? placeholder is the SQLite syntax issue (30.H-11), but additionally DATE() is a function that re-evaluates on every row — on a large explosive_mover_overrides table this prevents index use on the timestamp column. Should use timestamp >= ? with a full datetime boundary for index-eligible range scans.
🟢 Lows (4) — explosive_mover_tracker.py
ID	Issue
30.L-16	_daily_stats['total_score'] and _daily_stats['total_rvol'] are accumulated in memory for average calculation, but print_explosive_override_summary() calls get_daily_override_stats() which queries the DB for AVG(score). The in-memory totals are never used for the summary. Dead accumulation.
30.L-17	ExplosiveMoverTracker.record_override() (legacy shim) passes direction="unknown", regime_type="UNKNOWN", entry_price=0.0, grade="N/A", confidence=0.0 — placeholder values that will pollute the DB and skew analytics if any legacy caller still uses record_override(). The shim should log a deprecation warning.
30.L-18	_override_signals is a session-level dict keyed by ticker. If the same ticker fires two explosive overrides in the same session, the second call overwrites the first in _override_signals. The first override's entry is lost from the in-memory dict. The DB keeps both rows (INSERT, not UPSERT), so DB analytics are correct — but update_override_outcome() checks if ticker not in _override_signals: return which means the first trade's outcome can never be updated if the ticker fires twice.
30.L-19	print_explosive_override_summary() guards if not stats or stats['total_overrides'] == 0: return — silently does nothing. Same pattern as cooldown_tracker.print_cooldown_summary(). Should print a minimal "No explosive overrides today" line so EOD report callers get confirmation of empty state.
Priority Fix Order
30.H-10 — conn.close() throughout explosive_mover_tracker.py drains the DB pool; replace all with try/finally: return_conn(conn) — active production risk

30.H-11 — Hardcoded ? placeholders in get_daily_override_stats() and get_threshold_optimization_data() crash silently on Railway Postgres; replace with ph()

30.H-1 — tz-aware vs naive datetime comparison in is_on_cooldown() raises TypeError on every cooldown check after DB reload; use ET-naive now consistently

30.H-2 — _maybe_load_cooldowns() race condition between scanner and sniper threads at startup; add threading.Lock() guard

30.M-12 — _ensure_explosive_override_table() at module import time; defer to first use

30.M-14 — In-memory stats updated before DB insert; reverse order for consistency

30.M-13 — UPDATE ... ORDER BY ... LIMIT breaks local SQLite testing; rewrite as subquery

**30.H-10 is the most urgent fix in this batch** — `conn.close()` is a pool drain that FIX #4 was explicitly designed to prevent across `data_manager.py`, but `explosive_mover_tracker.py` was written after FIX #4 and didn't inherit the pattern. Every explosive override signal or stats query permanently discards a connection. After 12 such calls the semaphore blocks everything.
