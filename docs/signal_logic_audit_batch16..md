# Signal Logic Audit — Batch 16

**Date:** 2026-03-18
**Scope:** `app/data/ws_feed.py`, `app/data/ws_quote_feed.py`, `app/data/unusual_options.py`
**Note:** `sql_safe.py` was not present in the repository — skipped.
**Total Findings:** 20 (1 Critical, 6 High, 8 Medium, 5 Low)

---

## 🔴 Criticals (1)

---

### 16.C-1 — `_on_tick()` Gate 3 condition code check is broken — `condition` is extracted once as a scalar, then checked again as a list — the list branch is dead code and scalar conditions are never checked against `INVALID_TRADE_CONDITIONS`
**File:** `ws_feed.py`

```python
condition = msg.get("c", 0)
if isinstance(condition, list):
    condition = condition if condition else 0   # ← scalar extracted here
if isinstance(condition, list):                    # ← this branch is DEAD
    if any(c in INVALID_TRADE_CONDITIONS for c in condition):
        return
    condition = condition if condition else 0
if condition in INVALID_TRADE_CONDITIONS:          # ← scalar check: works
    return
After the first if isinstance(condition, list) block, condition is always a scalar. The second if isinstance(condition, list) block is unreachable — it was intended to handle multi-code lists (EODHD sometimes sends "c": [12, 37]) but is never entered. As a result, multi-condition ticks are never filtered — a tick with "c": [12, 37] has condition reduced to 12 by the first block, which happens to be in INVALID_TRADE_CONDITIONS and is caught. But a tick with "c": [37, 99] gets condition = 37, which is also caught. The real risk is "c": [99, 37] — code 99 is unknown, so condition = 99, which is NOT in INVALID_TRADE_CONDITIONS, so the Form T / odd-lot tick passes through. The dead second block was supposed to check all codes in the list, not just the first.

Fix:

python
condition = msg.get("c", 0)
if isinstance(condition, list):
    if any(c in INVALID_TRADE_CONDITIONS for c in condition):
        return
    condition = condition if condition else 0
if condition in INVALID_TRADE_CONDITIONS:
    return
🟡 Highs (6)
16.H-2 — _on_tick() spike filter compares price against cur["close"] but cur["close"] is 0.0 for a brand-new bar — division by zero on the very first tick of a new bar after minute rollover
File: ws_feed.py

python
if cur is not None:
    deviation = abs(price - cur["close"]) / cur["close"]
When a minute rolls over, a new bar is created with "close": price — the price of the first tick. On the next tick within that same minute, cur["close"] equals that first tick's price and the math is fine. However, consider a recovery scenario: a bar is manually injected via store_bars() with a close of 0.0 (malformed REST fallback), then a real tick arrives. cur["close"] == 0.0 → ZeroDivisionError. The exception propagates up through the with _lock: block, which does NOT auto-release on exception in Python — the lock is released, but _open_bars and _pending are left in a partially-modified state depending on where the error occurred.

Fix: Guard against zero close:

python
if cur is not None and cur["close"] > 0:
    deviation = abs(price - cur["close"]) / cur["close"]
    if deviation > SPIKE_THRESHOLD:
        return
16.H-3 — _flush_open() calls data_manager.store_bars() for every open bar every FLUSH_INTERVAL seconds — with 30 tickers at 10s intervals that is 180 DB upserts/minute during market hours, consuming pool connections
File: ws_feed.py

python
def _flush_open():
    for ticker, bar in snapshot.items():
        if bar["datetime"].date() == today_et:
            data_manager.store_bars(ticker, [bar], quiet=True)
Each store_bars() call checks out and returns a DB connection (pool checkout + return). With 30 tickers, FLUSH_INTERVAL=10, and store_bars() taking ~5ms: 30 checkouts × 6 per minute = 180 pool operations/minute for in-flight bars that the scanner reads directly from _open_bars in memory. The DB write is documented as "just for durability" — but it is generating more pool pressure than the actual scanner. The pool has POOL_MAX=15 shared with the scanner and signal generator.

Fix: Batch all open bars into a single store_bars() call per flush cycle instead of one call per ticker:

python
all_open_bars = [(ticker, bar) for ticker, bar in snapshot.items() if bar["datetime"].date() == today_et]
for ticker, bar in all_open_bars:
    # batch upsert in a single connection
Or accept a dict of {ticker: [bar]} in store_bars() to do one connection checkout for all tickers.

16.H-4 — _ws_run() reads _all_tickers under _sub_lock correctly but clears _subscribed under a separate _sub_lock acquire — two separate lock sections creates a TOCTOU window where a concurrent subscribe_tickers() call adds to _subscribed between the two locked sections
File: ws_feed.py

python
with _sub_lock:
    _subscribed.clear()           # section 1

with _sub_lock:
    master = list(_all_tickers)   # section 2
await _do_subscribe(ws, master)
Between _subscribed.clear() and master = list(_all_tickers), a concurrent subscribe_tickers() call from the main thread could add ticker "X" to _all_tickers and to _subscribed (via _do_subscribe). Then on reconnect, master includes "X" (correctly), but _subscribed was cleared in section 1 and then re-populated in the concurrent call — creating a state where _subscribed has "X" but _do_subscribe(ws, master) sees "X" not in _subscribed (because it was cleared after the concurrent add) and sends a duplicate subscribe. Same pattern exists in ws_quote_feed.py.

Fix: Combine into a single lock section:

python
with _sub_lock:
    _subscribed.clear()
    master = list(_all_tickers)
await _do_subscribe(ws, master)
16.H-5 — _is_cached() in UnusualOptionsDetector compares tz-aware datetime.now(ET) against datetime.fromisoformat(cached_time_str) — raises TypeError if the stored timestamp is tz-aware
File: unusual_options.py

python
def _is_cached(self, ticker: str) -> bool:
    cached_time = datetime.fromisoformat(self.cache[ticker]['data']['timestamp'])
    age_seconds = (datetime.now(ET) - cached_time).total_seconds()
result['timestamp'] is set to datetime.now(ET).isoformat(), which produces an ISO string with UTC offset (e.g., "2026-03-18T09:35:00-04:00"). datetime.fromisoformat() on Python 3.11+ parses this as a tz-aware datetime. datetime.now(ET) is also tz-aware. The subtraction works on Python 3.11+. However on Python 3.10 (Railway default image), fromisoformat() does not handle the UTC offset — it raises ValueError: Invalid isoformat string. This means the cache check always raises, is swallowed by no try/except, and crashes check_whale_activity() for every call after the first.

Fix: Use a monotonic float timestamp for cache comparison instead of ISO string:

python
self.cache[ticker] = {'data': result, 'fetched_at': time.monotonic()}
# In _is_cached:
age_seconds = time.monotonic() - self.cache[ticker]['fetched_at']
16.H-6 — _cache_result() stores datetime.now(ET) object in self.cache[ticker]['timestamp'] but _is_cached() reads from self.cache[ticker]['data']['timestamp'] — two different keys, _cache_result timestamp is never read
File: unusual_options.py

python
def _cache_result(self, ticker, result):
    self.cache[ticker] = {
        'data': result,
        'timestamp': datetime.now(ET)   # ← stored here, never read
    }

def _is_cached(self, ticker):
    cached_time = datetime.fromisoformat(
        self.cache[ticker]['data']['timestamp']   # ← reads from result dict, not cache dict
    )
_is_cached() reads self.cache[ticker]['data']['timestamp'] (the ISO string inside the result dict). _cache_result() writes the datetime object to self.cache[ticker]['timestamp'] (the outer cache dict). These are two different fields — the outer 'timestamp' key is never used. The cache age check is correct in intent but always reads the result's own timestamp (which is also datetime.now(ET).isoformat()), so it works by coincidence. The self.cache[ticker]['timestamp'] key is dead.

Fix: Remove the dead outer 'timestamp' key from _cache_result() and standardize on reading from result['timestamp'] (or better, use 16.H-5's fix and use time.monotonic()).

16.H-7 — get_whale_alerts() calls check_whale_activity() for both CALL and PUT on every ticker — with a 30-ticker watchlist that is 60 API calls per scan cycle, each hitting the cache independently
File: unusual_options.py

python
for ticker in tickers:
    call_data = self.check_whale_activity(ticker, 'CALL')
    put_data  = self.check_whale_activity(ticker, 'PUT')
The cache key is ticker — not (ticker, direction). So the second call check_whale_activity(ticker, 'PUT') always returns the cached CALL result (because _is_cached(ticker) returns True after the CALL). The direction parameter is completely ignored on cache hits. The PUT result is always a copy of the CALL result with direction='CALL'. Every PUT whale alert in the system is actually a CALL result.

Fix: Use (ticker, direction) as the cache key:

python
cache_key = f"{ticker}_{direction}"
if self._is_cached(cache_key):
    return self.cache[cache_key]['data']
🟠 Mediums (8)
ID	File	Issue
16.M-8	ws_feed.py	_fetch_bar_rest() parses row["datetime"] with datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S"). EODHD REST intraday returns ET-naive datetimes in this format — consistent with the rest of the codebase. However, the returned bar dict has no tzinfo, so it is a naive datetime that gets mixed into _open_bars alongside other naive ET bars. The source: rest key is present, but there's no check to ensure the REST bar's datetime matches today — a stale REST bar from yesterday could be returned as the "current" bar during reconnect. Add a date check: if bar["datetime"].date() != datetime.now(ET).date(): return None.
16.M-9	ws_feed.py	get_current_bar_with_fallback() checks if _connected: return None after get_current_bar() returns None — meaning if WS is connected but has no bar for a ticker yet (new subscription, pre-market), it returns None immediately without trying REST. This is correct behavior by design but should be documented. The comment currently says "3-tier priority" but tier 2 is only entered when _connected=False.
16.M-10	ws_feed.py	_flush_open() guards bar["datetime"].date() == today_et — but bar["datetime"] is a naive ET datetime. On Railway (UTC server), datetime.now(ET).date() returns the correct ET date. However, if the server clock is wrong or a bar was built from a tick with a corrupted timestamp, bar["datetime"].date() could mismatch and bars are silently dropped. The guard is correct but completely silent — no log on skipped bars.
16.M-11	ws_quote_feed.py	_handle_server_msg() returns "ignore" for messages that have neither status_code nor status key — but _ws_run() calls this only when "status_code" in msg or "status" in msg. So "ignore" is an unreachable return value. The function also resets consecutive_500s[0] = 0 on any non-500/non-fatal action (including "ok"), but the reset happens in the outer loop, not inside _handle_server_msg(). The two reset paths are inconsistent: once inside the message handler for 200, once outside for everything else.
16.M-12	ws_quote_feed.py	_on_quote() stores ts as a naive ET datetime (datetime.fromtimestamp(..., tz=ET).replace(tzinfo=None)). Consistent with the codebase convention, but get_quote() returns this as timestamp key. Consumers comparing this timestamp to datetime.now(ET) (tz-aware) will get TypeError. Should either return tz-aware or document as naive ET.
16.M-13	unusual_options.py	All four internal scoring methods (_detect_large_orders, _analyze_options_flow, _detect_sweeps, _check_dark_pool_activity) return 0.0 hardcoded with print() spam. With a 30-ticker watchlist, get_whale_alerts() generates 120 print() lines per call (4 methods × 30 tickers × CALL + PUT). During market hours this floods the Railway log. These print() calls inside stub methods must be removed.
16.M-14	unusual_options.py	uoa_detector = UnusualOptionsDetector() singleton at module scope prints 3 lines at import time and runs __init__ including cache setup. Same import-time side-effect pattern flagged across all batches.
16.M-15	ws_feed.py	_rest_hits is a module-level global incremented without a lock in _fetch_bar_rest(). In a race scenario where two tickers both trigger REST failover simultaneously (both WS-disconnected cache misses), two threads call _fetch_bar_rest() concurrently. _rest_hits += 1 is not atomic in Python (though CPython's GIL makes it safe in practice). More importantly, get_current_bar_with_fallback() reads _rest_hits + 1 in the log message before incrementing — the printed count is always 1 behind.
🟢 Lows (5)
ID	File	Issue
16.L-16	ws_feed.py	_backfill_active flag and set_backfill_complete() are kept "for backwards compat, no longer used in flush logic." Remove both — dead state that adds confusion.
16.L-17	ws_feed.py	SPIKE_THRESHOLD = 0.10 (10%) is too permissive for normal equity price moves within a single 1-minute tick. A 10% intra-minute spike is an extreme event. Most production systems use 2-3% for mid-caps. Consider 0.03 (3%) as the default, configurable via config.
16.L-18	unusual_options.py	UnusualOptionsDetector is entirely stub code — all four scoring methods return 0.0. The module is safe to import but adds no value to the running system. It should either be completed or excluded from production import paths to avoid the 120-line print flood (16.M-13).
16.L-19	ws_quote_feed.py	RECONNECT_DELAY_MIN = 2 is defined but never referenced — _ws_run() uses min(2 ** attempt, RECONNECT_DELAY_MAX) directly, hardcoding the base as 2. Should use RECONNECT_DELAY_MIN for consistency.
16.L-20	All files	All print() calls should be logger.*. Same pattern flagged in batches 8–15.
Priority Fix Order
16.C-1 — Gate 3 dead code: multi-condition ticks with unknown leading code bypass trade filter — bad ticks enter bar state

16.H-7 — Cache key is ticker not (ticker, direction) — every PUT whale alert returns CALL data; PUT direction is never evaluated

16.H-2 — cur["close"] == 0.0 → ZeroDivisionError inside _lock → lock released but bar state corrupted

16.H-4 — Two-section _sub_lock acquire on reconnect → TOCTOU window → duplicate subscribe messages

16.H-5 + 16.H-6 — _is_cached() raises ValueError on Python 3.10 for tz-aware ISO strings + dead outer timestamp key

16.H-3 — 180 pool checkouts/minute from _flush_open() — batch all open bars into single connection per cycle

16.M-13 — Remove print() from all stub scoring methods — 120 lines/call flood Railway logs




