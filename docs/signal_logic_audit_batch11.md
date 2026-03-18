# Signal Logic Audit — Batch 11

**Date:** 2026-03-18
**Scope:** `app/risk/vix_sizing.py`, `app/risk/dynamic_thresholds.py`
**Total Findings:** 18 (3 Critical, 5 High, 6 Medium, 4 Low)

---

## 🔴 Criticals (3)

---

### 11.C-1 — `_get_vix_with_cache()` has a TOCTOU race — cache can be read before the lock is re-acquired after the fetch
**File:** `vix_sizing.py`

```python
def _get_vix_with_cache() -> float:
    now = datetime.now()
    with _cache_lock:
        if _cached_vix is not None and ...:
            return _cached_vix   # ← lock released here

    vix = _fetch_vix_from_eodhd()   # ← runs WITHOUT the lock

    ...
    with _cache_lock:
        _cached_vix       = vix     # ← lock re-acquired here
        _cached_timestamp = now
Two threads entering simultaneously both see an expired cache, both call _fetch_vix_from_eodhd() concurrently, and both write back to _cached_vix. This results in two simultaneous EODHD API calls on every cache expiry — doubling API usage at the 5-minute boundary. During a high-volatility session with 30 tickers scanning every 5 seconds, the 5-minute boundary can cause a brief spike of 2× the API rate. More critically: _cached_timestamp = now is set to the Python datetime.now() captured before the fetch, not after. If the fetch takes 3 seconds, the effective TTL is VIX_CACHE_TTL - 3s = 297s instead of 300s — a minor drift, but compounded it can cause cache churn.

Fix: Use a double-checked locking pattern:

python
def _get_vix_with_cache() -> float:
    now = datetime.now(tz=ET)
    with _cache_lock:
        if _cached_vix is not None and _cached_timestamp is not None:
            if (now - _cached_timestamp).total_seconds() < VIX_CACHE_TTL:
                return _cached_vix
        # Fetch inside the lock to prevent double-fetch
        vix = _fetch_vix_from_eodhd()
        if vix is None:
            return _cached_vix if _cached_vix is not None else VIX_FALLBACK
        _cached_vix = vix
        _cached_timestamp = datetime.now(tz=ET)  # timestamp AFTER fetch
        return _cached_vix
11.C-2 — _get_winrate_adjustment() queries a trades table that does not exist — always silently returns 0.0
File: dynamic_thresholds.py

python
cursor.execute("""
    SELECT outcome FROM trades
    WHERE signal_type = ? AND grade = ?
    AND status = 'CLOSED'
    ORDER BY id DESC
    LIMIT 20
""", (signal_type, grade))
The War Machine schema uses a positions table (audited in Batch 10), not a trades table. There is no trades table, no signal_type column in positions, and no outcome column in positions (it uses pnl > 0 to determine WIN/LOSS). This query raises OperationalError: no such table: trades on every call. The bare except Exception swallows it silently and returns 0.00. The win-rate dynamic adjustment has never fired once in production. The threshold is always missing its win-rate component.

Fix: Rewrite against the actual schema:

python
cursor.execute("""
    SELECT pnl FROM positions
    WHERE grade = %s
    AND status = 'CLOSED'
    ORDER BY exit_time DESC
    LIMIT 20
""", (grade,))
rows = cursor.fetchall()
if len(rows) < 10:
    return 0.00
wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
winrate = wins / len(rows)
Note: signal_type filtering is not possible with the current schema — consider adding a signal_type column to positions if per-type win rate is needed.

11.C-3 — _get_recent_quality_adjustment() queries a proposed_trades table that does not exist — always silently returns 0.0
File: dynamic_thresholds.py

python
cursor.execute("""
    SELECT confidence FROM proposed_trades
    WHERE timestamp > ?
    ORDER BY timestamp DESC
    LIMIT 5
""", (two_hours_ago,))
There is no proposed_trades table in the War Machine schema. Same failure mode as 11.C-2 — OperationalError silently swallowed, quality adjustment always 0.0. The recent-quality component of the dynamic threshold has never been applied in production.

Fix: Replace with a query against ml_signals (which stores signal confidence and created_at):

python
cursor.execute("""
    SELECT confidence FROM ml_signals
    WHERE created_at > %s
    ORDER BY created_at DESC
    LIMIT 5
""", (two_hours_ago,))
Alternatively, use the watching_signals_persist table's confidence column if ml_signals isn't populated pre-trade.

🟡 Highs (5)
11.H-4 — _get_vix_with_cache() uses datetime.now() (no timezone) for cache TTL comparison — inconsistent with rest of module
File: vix_sizing.py

python
now = datetime.now()   # naive, no TZ
with _cache_lock:
    if (now - _cached_timestamp).total_seconds() < VIX_CACHE_TTL:
Every other function in this file uses datetime.now(tz=ET). _cached_timestamp is set to this same naive now. The comparison works, but: if _cached_timestamp is ever set from a tz-aware source (e.g., a future refactor), the subtraction will raise TypeError: can't subtract offset-naive and offset-aware datetimes. Also visible in get_vix_regime():

python
cache_age = (datetime.now() - _cached_timestamp).total_seconds()
Same inconsistency — naive vs rest of module.

Fix: Use datetime.now(tz=ET) consistently everywhere in this file.

11.H-5 — _get_vix_adjustment() uses data_manager.get_vix_level() — separate VIX source from vix_sizing.py's own EODHD fetch
File: dynamic_thresholds.py

dynamic_thresholds.py imports VIX from data_manager.get_vix_level(). vix_sizing.py fetches VIX from EODHD directly via _fetch_vix_from_eodhd(). These are two independent data sources with independent caches and independent staleness. It is possible for get_dynamic_threshold() to see VIX=18 (from data_manager, 5-min-old data) while evaluate_signal() sees VIX=22 (from vix_sizing, freshly fetched) — causing the threshold and the sizing multiplier to be computed on different VIX snapshots within the same signal evaluation call.

Fix: Replace _get_vix_adjustment() with a direct call to vix_sizing.get_vix_regime():

python
from app.risk.vix_sizing import get_vix_regime
def _get_vix_adjustment():
    try:
        regime = get_vix_regime()
        vix = regime["vix"]
        ...
    except Exception:
        return 0.00
This ensures both threshold and sizing use the same cached VIX snapshot.

11.H-6 — get_dynamic_threshold() calls four DB/network functions synchronously on every signal evaluation — latency spike in the OR window
File: dynamic_thresholds.py

get_dynamic_threshold() calls:

_get_time_of_day_adjustment() — pure Python, fast

_get_vix_adjustment() — data_manager.get_vix_level() (possible network/DB)

_get_winrate_adjustment() — DB query (currently broken, but fast-fails)

_get_recent_quality_adjustment() — DB query (currently broken, but fast-fails)

Once 11.C-2 and 11.C-3 are fixed, all four will run on every signal. In the OR window (9:30–9:40) with 30 tickers, this is 30 × 4 = 120 function calls per 5-second cycle, including 2 DB queries per ticker. At 5ms/query = 60 × 2 = 120ms of DB overhead per cycle, on top of the per-ticker scan time.

Fix: Cache get_dynamic_threshold() results with a short TTL (30–60 seconds). The threshold doesn't need to update on every tick — it changes on minute-scale market conditions. Use a module-level dict keyed by (signal_type, grade) with a shared TTL timestamp.

11.H-7 — _get_time_of_day_adjustment() has a gap — returns +0.05 for any time outside 9:30–16:00, including pre-market
File: dynamic_thresholds.py

python
else:
    return +0.05  # After hours: very strict
This fires for pre-market (before 9:30 AM ET) as well as after-hours. A pre-market signal evaluated at 9:28 AM would get a +0.05 strict penalty — the same as a 10 PM after-hours signal. In practice, pre-market signals shouldn't be opened at all (the RTH guard in position_manager.py blocks them), but the threshold is still computed and logged, creating misleading output. There's also a gap: 9:00–9:30 AM is pre-market, not after-hours — the label in the comment is wrong.

Fix: Add an explicit pre-market branch:

python
elif time(9, 0) <= now < time(9, 30):
    return +0.05  # Pre-market: strict (RTH guard will block anyway)
And rename the else comment from "After hours" to "After market close / overnight".

11.H-8 — _get_winrate_adjustment() uses SQLite placeholder ? hardcoded — breaks on Postgres
File: dynamic_thresholds.py

python
cursor.execute("""
    SELECT outcome FROM trades
    WHERE signal_type = ? AND grade = ?
    ...
""", (signal_type, grade))
The rest of the codebase uses ph() from db_connection to abstract ? (SQLite) vs %s (Postgres). This function hardcodes ?, which raises ProgrammingError on Postgres (Railway production). The function currently never reaches this code due to 11.C-2's missing table, but once fixed, it will fail on the first Railway deploy.

Fix: Use p = ph() and f"... WHERE signal_type = {p} AND grade = {p}" consistent with the rest of the codebase.

🟠 Mediums (6)
ID	File	Issue
11.M-9	vix_sizing.py	VIX_REGIMES uses (999, 0.30, "crisis") as the final catch-all. _calculate_vix_regime() iterates with if vix < threshold — a VIX of exactly 999 or above would fall through all conditions and return the last tuple's multiplier via the final return VIX_REGIMES[-1][1]. This is fine now, but the sentinel value of 999 is fragile. Use float("inf") instead.
11.M-10	vix_sizing.py	get_sizing_examples() hardcodes risk_tiers with "B+" and "B" grades that don't exist in config.POSITION_RISK or anywhere in the War Machine signal pipeline (which uses "A+", "A", "A-"). The diagnostic output will show nonsense risk percentages for grades that never fire.
11.M-11	dynamic_thresholds.py	get_threshold_stats() only returns time_of_day_adj and vix_adj — omitting winrate_adj and quality_adj. The monitoring/Discord snapshot is incomplete. Once 11.C-2 and 11.C-3 are fixed, all four adjustments should be included.
11.M-12	vix_sizing.py	_fetch_vix_from_eodhd() uses a mix of print() and logging.getLogger() depending on whether it's market hours. The after-hours path uses import logging as _log inside the function body — a deferred import on every after-hours call. Move the import to module level.
11.M-13	dynamic_thresholds.py	_get_vix_adjustment() returns -0.02 when VIX < 15 (low volatility = more lenient). This is counter-intuitive: low VIX should make signals more attractive (confirmed trend, lower noise), so a lower threshold makes sense directionally. But the docstring says "low volatility, be selective" which contradicts the -0.02 leniency. The comment is wrong — fix the docstring.
11.M-14	dynamic_thresholds.py	get_dynamic_threshold() clamps the final threshold to max(config.CONFIDENCE_ABSOLUTE_FLOOR, min(final_threshold, 0.85)). If all four adjustments are negative simultaneously (hot win streak + low VIX + morning + high quality), the threshold can drop below CONFIDENCE_ABSOLUTE_FLOOR. The floor prevents this. But the floor value itself is read from config with no fallback — if CONFIDENCE_ABSOLUTE_FLOOR is missing from config, this raises AttributeError and disables all signal evaluation. Add: floor = getattr(config, "CONFIDENCE_ABSOLUTE_FLOOR", 0.55).
🟢 Lows (4)
ID	File	Issue
11.L-15	vix_sizing.py	clear_cache() resets _cached_regime but _cached_regime is never written anywhere in the module — get_vix_regime() computes the regime on every call from _cached_vix without caching it separately. _cached_regime is dead state. Remove it.
11.L-16	vix_sizing.py	The if __name__ == "__main__" block at the bottom calls _is_market_hours_now() and get_vix_regime() — valid for manual testing. But get_sizing_examples() is also called, which will make a live EODHD API call using config.EODHD_API_KEY. Running python vix_sizing.py in a dev environment without a valid key will raise an unhandled exception instead of a clean error message. Add a try/except around the diagnostic block.
11.L-17	dynamic_thresholds.py	_get_winrate_adjustment() and _get_recent_quality_adjustment() both open a DB connection, but neither uses a context manager — they rely on try/finally: return_conn(conn). If dict_cursor(conn) raises before the query, conn is returned but cursor is leaked. Use with dict_cursor(conn) as cursor: if the driver supports it, or always assign cursor = None before the try block.
11.L-18	dynamic_thresholds.py	All print() calls should be logger.*. Same pattern flagged in batches 8, 9, and 10.
Priority Fix Order
11.C-2 — trades table doesn't exist — win-rate dynamic adjustment has never fired in production

11.C-3 — proposed_trades table doesn't exist — quality adjustment has never fired in production

11.H-5 — Two independent VIX sources — threshold and sizing computed on different VIX values

11.C-1 — TOCTOU race in VIX cache — double EODHD API calls on every cache expiry

11.H-8 — SQLite ? placeholder hardcoded — will break on Postgres once table is fixed

11.H-6 — get_dynamic_threshold() has no result cache — 4 DB/network calls per ticker per cycle

11.M-14 — CONFIDENCE_ABSOLUTE_FLOOR has no fallback — missing config key disables all signals