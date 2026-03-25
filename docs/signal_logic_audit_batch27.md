All three files read. Full Batch 27 audit below.

File: docs/signal_logic_audit_batch27.md
text
# Signal Logic Audit — Batch 27

**Date:** 2026-03-18
**Scope:** `app/data/candle_cache.py`, `app/data/database.py`,
           `app/data/unusual_options.py`
**Total Findings:** 20 (0 Critical, 4 High, 8 Medium, 8 Low)

---

## 🔴 Criticals (0)

`candle_cache.py` is the cleanest file in the analytics layer to date. The C4 and 1.22 fixes show deliberate hardening. `database.py` is a correct, well-documented shim. No criticals in this batch.

---

## 🟡 Highs (4)

---

### 27.H-1 — `candle_cache.CandleCache.__init__()` passes `self.db_path = "market_memory.db"` to every `get_conn(self.db_path)` call throughout the class. As established in **26.M-6**, `get_conn(sqlite_path)` silently ignores the argument on Postgres. On Railway production, `candle_cache` is reading from and writing to the main Postgres pool regardless of `self.db_path`. On local dev SQLite fallback, `get_conn("market_memory.db")` creates a second SQLite file (`market_memory.db`) separate from `war_machine.db` (the default). This means candle cache data and all other module data live in **different SQLite files** locally, making local testing non-representative of production. The `db_path` parameter is dead on Postgres and dangerous on SQLite. Remove it and use `get_conn()` with no argument everywhere in the class.

---

### 27.H-2 — `candle_cache.is_cache_fresh()` contains a tz-aware/naive datetime comparison identical to the bug flagged in **24.H-2** and **21.H-5**:

```python
age = datetime.now(ET) - last_bar.replace(tzinfo=ET) if last_bar.tzinfo is None \
      else datetime.now(ET) - last_bar
When last_bar is a naive datetime loaded from Postgres TIMESTAMP (not TIMESTAMP WITH TIME ZONE), last_bar.replace(tzinfo=ET) does not convert the naive time — it just stamps it with the ET timezone as if the wall clock value was already in ET. If the Postgres server stores timestamps in UTC (Railway default), this is wrong: a bar stored at 14:30:00 UTC stamped with ET tzinfo becomes 14:30:00 ET = 19:30 UTC — off by 5 hours. age will be computed as -5 hours, is_cache_fresh() returns True always (negative age ≤ 5 minutes is True), making the freshness gate a no-op. Candles that are hours stale appear fresh.

Fix: Strip tz info from both sides — use datetime.now() (naive) and last_bar.replace(tzinfo=None) consistently throughout.

27.H-3 — candle_cache.detect_cache_gaps() compares last_bar < now_et - timedelta(minutes=5) where last_bar comes from metadata["last_bar_time"] — loaded from get_cache_metadata() → Postgres → naive datetime from a TIMESTAMP column. now_et = datetime.now(ET) is tz-aware. This is the same tz-aware/naive TypeError as 24.H-2. If detect_cache_gaps() is called during startup backfill, it raises TypeError: can't compare offset-naive and offset-aware datetimes and returns an empty gap list — causing the startup to think the cache is complete and skip the backfill. The scanner starts with stale data.
27.H-4 — unusual_options.UnusualOptionsDetector._is_cached() calls:
python
cached_time = datetime.fromisoformat(self.cache[ticker]['data']['timestamp'])
age_seconds = (datetime.now(ET) - cached_time).total_seconds()
result['timestamp'] is set as datetime.now(ET).isoformat() — a tz-aware ISO string (e.g., "2026-03-18T09:30:00-04:00"). datetime.fromisoformat() on Python 3.7–3.10 does not parse timezone offset strings — it raises ValueError: Invalid isoformat string for any string containing a UTC offset. Python 3.11+ added full ISO 8601 support to fromisoformat(). Railway uses Python 3.10 or 3.11 depending on the build image. On 3.10, _is_cached() raises ValueError on every cache check, falls through to except-less caller, and the cache never hits — every call to check_whale_activity() re-runs the four sub-detectors. At 50 tickers × 2 directions = 100 calls per scan cycle, all 100 generate fresh log spam. The cache is completely non-functional on Python 3.10.

Fix: Store the timestamp as time.time() (float epoch) or use datetime.now(ET) directly as a datetime object in the cache dict (not serialized to ISO string). The ISO string is only needed for the output result dict returned to callers.

🟠 Mediums (8)
ID	File	Issue
27.M-5	candle_cache.py	cleanup_old_cache() uses (ticker, timeframe) NOT IN (SELECT DISTINCT ticker, timeframe FROM candle_cache) to prune orphaned metadata. This is a correlated NOT IN against a subquery that performs a full table scan of candle_cache. At 30 days × 390 bars/day × 50 tickers = ~585K rows, this is a slow maintenance operation. Should use NOT EXISTS or a LEFT JOIN ... WHERE IS NULL pattern, which Postgres can execute with an index. idx_candle_lookup on (ticker, timeframe, datetime DESC) is not used by DISTINCT ticker, timeframe. Add a partial index or run the prune in a batch by ticker.
27.M-6	candle_cache.py	cache_candles() uses cursor.executemany(upsert_sql, data) — correct and efficient. However, the dict_cursor is used for the upsert step (Step 1), which returns RealDictCursor on Postgres. executemany() works fine with RealDictCursor but the cursor is never actually used to fetch rows — it's just for executing. Using dict_cursor for writes is harmless but semantically incorrect (dict cursor is for fetchall() result parsing). Use conn.cursor() for write operations.
27.M-7	candle_cache.py	_parse_cache_rows() strips timezone info from all loaded datetimes: dt = dt.replace(tzinfo=None). This makes all cache output naive datetimes. But cache_candles() stores b["datetime"] directly from the input bars list — which may be tz-aware or tz-naive depending on the caller. The DB stores whatever it receives. On load, it normalizes to naive. This asymmetry means cache write ≠ cache read for tz-aware inputs. Should normalize to naive ET on write, not just on read.
27.M-8	candle_cache.py	get_cache_stats() runs 5 separate SELECT queries (total bars, unique tickers, date range, cache size, per-timeframe) in sequence, each opening its own cursor on the same shared connection. This could be reduced to 1–2 queries. Minor on its own, but get_cache_stats() is called in the startup health check and dashboard — unnecessary DB load at boot time.
27.M-9	candle_cache.py	aggregate_to_timeframe() is pure Python (no DB I/O) but is called with days=30 loading up to 585K bars into memory for aggregation for a single ticker. For a 50-ticker scan, if all tickers are aggregated on startup, this is ~29M bars resident in memory simultaneously. Should use the DB for aggregation (GROUP BY with time_bucket or DATE_TRUNC) rather than loading all 1m bars into Python for bucketing.
27.M-10	unusual_options.py	All four scoring sub-methods (_detect_large_orders, _analyze_options_flow, _detect_sweeps, _check_dark_pool_activity) return 0.0 with print() spam per call. check_whale_activity() is called for every ticker in every scan cycle (via scanner.py). At 50 tickers × 2 directions × 12 scans/hour = 1,200 calls/hour, each generating 4 print lines = 4,800 log lines/hour of "[UOA] AAPL whale detection: 0.0/10". This is pure noise that buries real log output. Remove the per-call debug prints from stub methods entirely or wrap in if logger.isEnabledFor(logging.DEBUG).
27.M-11	unusual_options.py	get_whale_alerts() calls check_whale_activity(ticker, 'CALL') then check_whale_activity(ticker, 'PUT') for each ticker. Since all sub-detectors return 0.0, all scores are 0.0 < 6.0 (min_score), so alerts is always empty. The function always returns []. If scanner.py gates on this result (e.g., if whale_alerts: boost_confidence()), the UOA confidence boost path is dead code in production — it has never fired. Should be documented as "stub — UOA not yet integrated" in scanner call sites.
27.M-12	database.py	get_db_connection() returns get_conn() — a pooled connection that the caller must return via close_db_connection(). Two legacy callers (train_from_analytics.py, scripts/generate_ml_training_data.py) use this API. If either script exits without calling close_db_connection(), the pool connection is leaked. The shim should use get_connection() context manager internally and document that callers should use with get_connection() as conn: directly.
🟢 Lows (8)
ID	File	Issue
27.L-13	candle_cache.py	print("[CACHE] ✅ Candle cache tables initialized") in _init_cache_tables() — fires on every instantiation including the module-level candle_cache = CandleCache(). Replace with logger.debug().
27.L-14	candle_cache.py	cleanup_old_cache() defaults to days_to_keep=30 — matches the startup backfill window. Good. But the docstring says "Phase 1.22 changes: Default changed from 60 to 30 days". The 60-day default is gone, but there is no scheduled call to cleanup_old_cache() visible in this file. Confirm sniper.py or a scheduled task calls it; if not, the cache grows unboundedly until manual intervention.
27.L-15	candle_cache.py	cache_candles() computes last_bar = max(b["datetime"] for b in bars) after committing, then calls last_bar.strftime('%m/%d %H:%M ET') in the log line. If any b["datetime"] is a tz-aware datetime, strftime() works fine — but the displayed "ET" suffix is hardcoded and doesn't reflect the actual timezone of the datetime object. Misleading if bars from a UTC source are passed in.
27.L-16	candle_cache.py	detect_cache_gaps() only detects end-of-range gaps (missing recent data). It does not detect interior gaps (e.g., a missing 30-minute window from 3 days ago due to an API timeout). The docstring says "Detect missing time ranges in cache" — plural — but only one gap type is returned. Document the limitation or implement interior gap detection.
27.L-17	unusual_options.py	UnusualOptionsDetector.__init__() prints 3 lines at instantiation ("[UOA] Unusual Options Detector initialized", whale threshold, cache TTL). Since uoa_detector = UnusualOptionsDetector() is at module level, these print on every import. Replace with logger.debug().
27.L-18	unusual_options.py	self.min_premium_whale = 100000, self.min_volume_ratio = 3.0 etc. are instance attributes set in __init__ but never used — all sub-detectors are stubs returning 0.0. These are configuration parameters for future real implementation; they should be in config.py as constants (not instance attributes) so they are configurable via env vars when the API integration is actually built.
27.L-19	unusual_options.py	_cache_result() stores 'timestamp': datetime.now(ET) as a datetime object in self.cache[ticker], but check_whale_activity() stores 'timestamp': datetime.now(ET).isoformat() (string) in result. So self.cache[ticker]['data']['timestamp'] is a string, but self.cache[ticker]['timestamp'] (the cache dict itself) is unused. _is_cached() reads self.cache[ticker]['data']['timestamp'] (the string). The two-level cache structure is confusing — self.cache[ticker] has both 'data' and 'timestamp' keys but only 'data' is ever read. The outer 'timestamp' key is dead.
27.L-20	database.py	__all__ exports both get_db_connection / close_db_connection (legacy) and the full db_connection API (get_conn, return_conn, etc.). This is correct for a compat shim. However, it means from app.data.database import * would expose get_conn and return_conn without the "prefer get_connection()" documentation from db_connection.py. The re-exports should be documented as "internal API — use get_connection() context manager".
UOA Integration Status
unusual_options.py is a complete stub with zero live data. All four scoring methods return 0.0. confidence_boost is always 0.0. Every call to check_whale_activity() produces 4 debug print lines and returns is_unusual=False. If this module is wired into the scanner signal path, it is contributing:

~4,800 log lines/hour of noise

Zero signal value

Correct behavior (boosts nothing) — but burns scan cycle time and log bandwidth

Until the Unusual Whales / EODHD options API integration is built, the UOA path should be gated with a feature flag (e.g., UOA_ENABLED = config.get("UOA_ENABLED", False)) so it can be imported without firing on every scan cycle.

Priority Fix Order
27.H-2 + 27.H-3 — tz-aware/naive comparison in is_cache_fresh() and detect_cache_gaps() — cache always appears fresh / gaps always missed → scanner starts with stale data on every Railway deploy

27.H-4 — datetime.fromisoformat() on tz-offset string fails on Python 3.10 → UOA cache never hits → 4,800 log lines/hour spam

27.H-1 — db_path parameter dead on Postgres, creates split SQLite files on local → remove

27.M-10 — 4 print lines per check_whale_activity() call at 1,200 calls/hour → remove or gate with DEBUG flag

27.M-9 — aggregate_to_timeframe() loads up to 585K rows per ticker into Python memory — use DB-side aggregation

**27.H-2 + 27.H-3 together** mean that on every Railway deploy the candle cache freshness check silently reports "fresh" (tz math error) while gap detection crashes on comparison (TypeError) and skips the backfill — the scanner starts with potentially 5-hour stale candles and no error message. The UOA stub situation (27.M-10 + 27.M-11) is the biggest log pollution issue found in the audit series — 4,800 zero-value print lines/hour is worse than all prior print-at-import findings combined.
