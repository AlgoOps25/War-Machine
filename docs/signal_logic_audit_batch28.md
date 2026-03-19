Both files read. Full Batch 28 audit below.

File: docs/signal_logic_audit_batch28.md
text
# Signal Logic Audit — Batch 28

**Date:** 2026-03-18
**Scope:** `app/data/ws_feed.py`, `app/data/ws_quote_feed.py`
**Total Findings:** 16 (0 Critical, 3 High, 7 Medium, 6 Low)

---

## 🔴 Criticals (0)

Both files are among the most mature in the codebase. The WebSocket reconnect logic, chunked subscription, dual-guard against double-start, REST failover, and 500-flood handling all show production-quality thinking. No criticals.

---

## 🟡 Highs (3)

---

### 28.H-1 — `ws_feed._on_tick()` Gate 3 (trade condition filter) has a **double-isinstance check with a logic gap**:

```python
condition = msg.get("c", 0)
if isinstance(condition, list):
    condition = condition if condition else 0   # ← flattened to int
if isinstance(condition, list):                    # ← this branch NEVER fires
    if any(c in INVALID_TRADE_CONDITIONS for c in condition):
        return
    condition = condition if condition else 0
if condition in INVALID_TRADE_CONDITIONS:
    return
After the first isinstance(condition, list) flattens it to an int, the second isinstance(condition, list) is always False. The any(c in INVALID_TRADE_CONDITIONS for c in condition) multi-code check never executes. EODHD actually sends "c" as a list of condition codes (e.g., [12, 37]), not a single int. The intent was to check if any code in a multi-code list is invalid — but that path is unreachable. A tick with conditions [12, 37] is flattened to condition = 12, checked individually, and rejected only for code 12. A tick with [37, 80] is flattened to condition = 37 and rejected for 37, but a tick with [80, 37] is flattened to condition = 80 and also caught. However, a tick with [0, 12] is flattened to condition = 0, passes all filters, and is accepted — a dark pool Form T report passes through as a valid bar tick. The fix is to check any() across the full list before flattening.

28.H-2 — ws_feed._flush_open() writes every open bar to the DB every FLUSH_INTERVAL seconds (10s). With 50 tickers at 10s flush = 6 upserts/ticker/minute = 300 DB writes/minute on top of all the closed-bar writes, scanner reads, signal inserts, and position checks. On the Railway hobby Postgres with POOL_MAX=15 and DB_SEMAPHORE_LIMIT=12 (FIX #7), each store_bars() call internally calls get_conn() which acquires a semaphore slot. 300 writes/minute = 5 writes/second. During the 9:30 burst when the semaphore gate is under maximum pressure (scanner backfill + monitor + scan), these 5/s background writes compete directly for the 12 semaphore slots. This is the same root cause as the 9:30 pool exhaustion crashes from FIX #7. The open-bar DB flush is for durability only — the scanner reads directly from _open_bars in memory. The flush interval should be increased to 60s (or open-bar flush dropped entirely), especially during the 9:30–9:35 burst window. Alternatively, batch all 50 tickers into a single store_bars() call per flush cycle rather than 50 individual calls.
28.H-3 — ws_feed._fetch_bar_rest() imports requests lazily (import requests inside the function). This is correct to avoid startup overhead. However, _fetch_bar_rest() is called inside with _rest_lock: context in get_current_bar_with_fallback():
python
with _rest_lock:
    cached = _rest_cache.get(ticker)
    if cached is not None and ...:
        return cached["bar"]

# ← lock released here ←

bar = _fetch_bar_rest(ticker)       # ← blocking HTTP call, up to 5s

with _rest_lock:
    _rest_cache[ticker] = {...}     # ← re-acquired here
Actually the lock is NOT held during _fetch_bar_rest() — it is released and re-acquired. This is correct. However: the cache check and the fetch are not atomic. Two threads calling get_current_bar_with_fallback("AAPL") simultaneously can both read cached=None, both call _fetch_bar_rest(), and both write to _rest_cache. This doubles REST API hits for the same ticker during the reconnect window. During a WS disconnect affecting 50 tickers with a 5s timeout, this could trigger up to 100 simultaneous blocking HTTP calls from 50 ticker × 2 concurrent scanner threads. At 5s timeout each, these block scanner threads for up to 5s — exactly during the reconnect window when timing is most critical. Fix: use a _rest_inflight set protected by _rest_lock to prevent concurrent duplicate fetches for the same ticker.

🟠 Mediums (7)
ID	File	Issue
28.M-4	ws_feed.py	_ws_run() builds the connection URL as f"{WS_BASE_URL}?api_token={config.EODHD_API_KEY}" and logs f"[WS] Connecting -> {WS_BASE_URL}" — correctly logging the base URL without the key. But _fetch_bar_rest() builds params = {"api_token": config.EODHD_API_KEY, ...} — also not logged in the URL. Good practice maintained. However, config.EODHD_API_KEY is accessed at call time, not module import. If the env var is missing (config.EODHD_API_KEY is empty string), the WS URL becomes wss://ws.eodhistoricaldata.com/ws/us?api_token= — EODHD returns a 401 which is treated as a non-500, non-200 by the quote feed's _handle_server_msg() and causes _ws_run() to exit. In ws_feed.py, the same 401 scenario just prints "[WS] Server msg: {msg}" and continues looping forever. Should check for empty API key at start_ws_feed() time and return early with a clear error rather than silently misbehaving on 401.
28.M-5	ws_feed.py	_on_tick() Gate 5 (spike filter) rejects ticks that deviate > 10% from cur["close"]. The spike filter is only active when cur is not None (open bar exists). The first tick of a new bar (when cur is None) creates the bar with whatever price arrives, with no spike check. A bad print as the first tick of a new minute sets open=high=low=close=bad_price. Gate 1 (basic bounds) blocks prices > $100K — but a realistic bad print of e.g. $250 on a $200 stock (25% spike) on the first tick of a minute passes all gates. The spike filter should compare against the previous closed bar's close if available when cur is None.
28.M-6	ws_feed.py	_ws_run() clears _subscribed with _sub_lock held: with _sub_lock: _subscribed.clear(). Then immediately after, acquires _sub_lock again to read _all_tickers: with _sub_lock: master = list(_all_tickers). Both could be done in a single lock acquisition. The gap between the two lock releases/acquisitions allows subscribe_tickers() (from main scanner thread) to modify _all_tickers between the two operations — adding a ticker that then gets skipped in _do_subscribe(ws, master) because it was appended after master snapshot was taken. The ticker ends up in _all_tickers but not in master — it won't be subscribed until the next reconnect. Fix: acquire _sub_lock once, clear _subscribed, snapshot _all_tickers, release.
28.M-7	ws_feed.py	get_current_bar_with_fallback() returns None when WS is connected but no open bar exists for the ticker (get_current_bar() returns None and _connected=True). Callers are documented to "fall back to DB last bar" in this case — but this means a freshly subscribed ticker during the first minute of a new scan cycle returns None from the primary data path with no REST fallback, even when the WS is healthy. The REST fallback should also fire when get_current_bar() is None and the ticker was subscribed more than FLUSH_INTERVAL seconds ago (i.e., we should have a bar by now).
28.M-8	ws_quote_feed.py	_handle_server_msg() takes consecutive_500s: list — a single-element list used as a mutable integer (consecutive_500s[0]). This is a common Python workaround for nonlocal mutation in pre-3.x closures, but _ws_run() is not a closure — consecutive_500s is a local variable in _ws_run() that is passed explicitly. A simple nonlocal counter or a class-level int would be cleaner. The list-as-mutable-int pattern creates confusion about why consecutive_500s is a list when auditing the code.
28.M-9	ws_quote_feed.py	_ws_run() resets attempt = 0 on a clean TCP connect but does not reset it after a hard 500 backoff completes. After one hard backoff (attempt incremented to 1), subsequent normal disconnects use exponential backoff starting from 2^1 = 2s instead of 2^0 = 2s — identical, fine. But after two hard backtracks, attempt = 2 and normal disconnect delay starts at 2^2 = 4s. After 4 hard backtracks, attempt = 4 and delay is 16s. The intent of the exponential backoff is to back off on repeated normal failures — not to accumulate delay from 500-triggered events that are server-side problems. attempt should only increment on network-level disconnect exceptions, not on server-500 hard backoffs.
28.M-10	ws_quote_feed.py	is_spread_acceptable() uses instantaneous spread (get_spread_pct()) rather than get_avg_spread_pct(). The docstring says "Uses the instantaneous spread (most conservative check)." For a high-frequency quote feed, instantaneous spread can spike momentarily during a print (e.g., a 0.5% spike lasting 50ms), blocking an otherwise valid entry. The sniper calling is_spread_acceptable() at signal fire time could hit a transient spike and reject a good trade. The averaged spread (get_avg_spread_pct()) is already computed over a 20-quote rolling window and would be more reliable. Consider offering use_avg=True parameter or defaulting to the average.
🟢 Lows (6)
ID	File	Issue
28.L-11	ws_feed.py	ENFORCE_RTH_ONLY = False is a module-level flag that is never wired to config.py. If pre/post market filtering is needed, it requires a code change + redeploy rather than an env var. Should be ENFORCE_RTH_ONLY = getattr(config, "ENFORCE_RTH_ONLY", False).
28.L-12	ws_feed.py	_rest_hits is a module-level global incremented with _rest_hits += 1 in _fetch_bar_rest() without a lock. This is a non-atomic read-modify-write on a plain int. On CPython, the GIL makes this safe in practice for simple integer increments — but it is technically undefined behavior for a multi-threaded module and should use threading.Lock() or threading.local() or itertools.count().
28.L-13	ws_feed.py	_backfill_active = True and set_backfill_complete() are kept "for backwards compat, no longer used in flush logic" per the docstring. Dead state. Should be removed to reduce cognitive load.
28.L-14	ws_feed.py	_flush_loop() catches all exceptions with except Exception as exc: print(f"[WS] Flush error: {exc}"). If data_manager raises a DB pool exhaustion error (which it does at 9:30), the flush loop suppresses it and continues. The pending bars remain in _pending (the clear() already ran before store_bars() — so they are lost). The clear() and store_bars() should be transactional: only clear _pending after successful store.
28.L-15	ws_quote_feed.py	_quotes and _spread_history are module-level globals with no TTL or eviction. A ticker that was subscribed during a premarket scan and then dropped from the active watchlist remains in _quotes and _spread_history indefinitely for the session. On a 250-ticker watchlist with 20-item deque, this is ~250 × 20 × 8 bytes ≈ 40KB — negligible. Low risk but document that clear_quotes() / clear_spread_history() are not implemented.
28.L-16	ws_quote_feed.py	_on_quote() rejects crossed markets (bid > ask) silently with no log. For a quote feed, crossed markets (even transient, sub-millisecond) can occur legitimately during fast markets. Logging every crossed-market rejection would be noise. But a counter _crossed_market_count would help diagnose feed quality issues. Low priority.
app/data/ Layer — Batch 27+28 Cross-File Finding
DB Write Storm at 9:30 (Systemic)
ws_feed._flush_open() (28.H-2) + candle_cache backfill writes (Batch 27) + data_manager backfill upserts all hit the DB simultaneously in the 9:30–9:35 window. The FIX #7 pool cap (15 connections, 12 semaphore slots) was set to prevent this but the open-bar flush loop (50 tickers × every 10s = 5 writes/second) was not accounted for in the FIX #7 budget. The actual concurrent DB connection budget at 9:30 is:

Source	Connections
Scanner (50 tickers)	2–4
Monitor open positions	1–2
Backfill threads	3–5
ws_feed _flush_open() (50 tickers)	up to 50
Candle cache writes	1–2
Total	57–63
50 individual store_bars() calls from _flush_open() each acquire a semaphore slot — they are the primary contributor to pool exhaustion that FIX #7 was supposed to fix. Batching all open-bar writes into a single connection call per flush cycle reduces this from 50 connections to 1.

Priority Fix Order
28.H-2 — _flush_open() fires 50 individual DB writes per cycle — the primary cause of 9:30 pool exhaustion that FIX #7 was targeted at but missed; batch into single connection call

28.H-1 — Trade condition filter dead code path — dark pool / Form T prints with multi-code [0, 12] pass the filter; check any() before flattening

28.L-14 — _flush_loop() clears _pending before store_bars() — lost bars on DB error; reverse the order

28.H-3 — Concurrent REST failover duplicate fetches during WS outage; add inflight set guard

28.M-5 — First tick of new minute bypasses spike filter; compare against previous bar's close

28.M-6 — _subscribed.clear() and _all_tickers snapshot not atomic; tickers added between the two lock acquisitions miss subscription on reconnect

**28.L-14 is a data-loss bug hiding as a Low** — `_pending.clear()` runs *before* `store_bars()`, so any DB error during the flush silently drops completed closed bars with no recovery path. That should arguably be elevated to High. **28.H-2** is the connection that ties everything together: after 28 batches, the 9:30 pool exhaustion crash that FIX #7 tried to solve was not a pool sizing problem — it was `_flush_open()` issuing 50 individual `get_conn()` calls per 10-second cycle, each consuming a semaphore slot, overwhelming the 12-slot gate from a single background thread.
