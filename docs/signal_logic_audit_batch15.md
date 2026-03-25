Here is the full Batch 15 audit. Ready to copy-paste.

File: docs/signal_logic_audit_batch15.md
text
# Signal Logic Audit — Batch 15

**Date:** 2026-03-18
**Scope:** `app/data/data_manager.py`
**Total Findings:** 18 (2 Critical, 6 High, 6 Medium, 4 Low)

---

## 🔴 Criticals (2)

---

### 15.C-1 — `initialize_database()` runs a destructive migration (DELETE all bars) on every startup if `db_version` table is empty — wipes all data on Railway after every pool reset
**File:** `data_manager.py`

```python
cursor.execute("SELECT version FROM db_version LIMIT 1")
row = cursor.fetchone()
current_version = (
    row if isinstance(row, (list, tuple)) else row["version"]
) if row else 0
if current_version < 2:
    cursor.execute("DELETE FROM intraday_bars")
    cursor.execute("DELETE FROM intraday_bars_5m")
    cursor.execute("DELETE FROM fetch_metadata")
    cursor.execute("DELETE FROM db_version")
    cursor.execute("INSERT INTO db_version (version) VALUES (2)")
On a fresh Postgres database (Railway first deploy, or after a DB reset), db_version is empty. current_version is 0, which is < 2, so the migration fires and deletes all bars. This is correct on first deploy. However, if a Railway incident causes the connection pool to be re-initialized and db_version table is somehow not visible (e.g., wrong schema, DB failover), this runs again and deletes all historical data with no backup. More critically: DataManager() is instantiated at module scope — data_manager = DataManager() — meaning initialize_database() runs on every import. If a transient DB error causes CREATE TABLE IF NOT EXISTS db_version to succeed but the SELECT version query returns nothing (e.g., transaction isolation edge case), the migration fires and deletes all bars mid-session.

Fix: Add a hard guard:

python
# Only migrate on first deploy — never in a running session
if current_version < 2 and total_bars == 0:
    # safe to migrate — no real data exists
Or better: bump to version 3 and make future migrations additive-only (never DELETE).

15.C-2 — startup_backfill_with_cache() computes age_minutes with a broken tz comparison — always evaluates as stale on Railway
File: data_manager.py

python
age_minutes = (
    now_et - last_cached.replace(
        tzinfo=ET if last_cached.tzinfo is None else None
    )
).total_seconds() / 60
The conditional is inverted. When last_cached.tzinfo is None (naive datetime — the common case on Postgres TIMESTAMP columns), it calls last_cached.replace(tzinfo=ET). But now_et is datetime.now(ET) (tz-aware). The subtraction of tz-aware - tz-aware works correctly here only by accident. However, when last_cached.tzinfo is not None (tz-aware, e.g., psycopg2 returns UTC-aware datetime on some column types), it calls last_cached.replace(tzinfo=None) — stripping TZ and then subtracting naive from tz-aware now_et, which raises TypeError: can't subtract offset-naive and offset-aware datetimes. This TypeError is swallowed by the outer except Exception as e — the entire ticker's cache logic is skipped, it falls through to a full API backfill for every ticker on every startup. The "API reduction: X%" stat in the summary will show 0% API savings even though the cache is populated.

Same broken pattern appears in background_cache_sync().

Fix: Normalize last_cached to ET-aware before comparison:

python
if last_cached.tzinfo is None:
    last_cached = last_cached.replace(tzinfo=ZoneInfo("UTC")).astimezone(ET)
age_minutes = (now_et - last_cached).total_seconds() / 60
🟡 Highs (6)
15.H-3 — _parse_bar_rows() strips timezone from all returned datetimes — same bug as 14.H-7, affects all session queries
File: data_manager.py

python
def _parse_bar_rows(self, rows) -> List[Dict]:
    ...
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)   # ← strips TZ unconditionally
Identical to candle_cache._parse_cache_rows() (14.H-7). On Railway, Postgres returns TIMESTAMP columns as naive UTC datetimes. After stripping TZ, get_today_session_bars() returns bars with naive UTC datetimes. materialize_5m_bars() uses these directly in bucket computation: dt.replace(minute=minute_floor). If the bar is 13:35 UTC (09:35 ET), the bucket key becomes 13:35 instead of 09:35, so the 5m bar appears to be in the 13:35 bucket rather than the 09:35 bucket. All 5m bar timestamps are off by 4 hours (5 hours during EST). Downstream signal generation using 5m bars sees all session bars as outside market hours.

Fix: Same as 14.H-7 — return tz-aware ET datetimes from _parse_bar_rows().

15.H-4 — materialize_5m_bars() calls get_today_session_bars() which queries the DB — then opens a second connection for the upsert — two pool checkouts per materialization
File: data_manager.py

python
def materialize_5m_bars(self, ticker: str):
    bars_1m = self.get_today_session_bars(ticker)   # checkout #1 + return
    ...
    conn = get_conn(self.db_path)                    # checkout #2
materialize_5m_bars() is called after every store_bars() call. In startup_backfill_today(), this means 2 pool checkouts × N tickers. For a 30-ticker watchlist that's 60 pool checkouts just for materialization. Given POOL_MAX=15 and a concurrent backfill, this contributes to pool exhaustion at 9:30 open.

Fix: Accept an optional bars_1m parameter so the caller can pass already-fetched bars:

python
def materialize_5m_bars(self, ticker: str, bars_1m: List[Dict] = None):
    if bars_1m is None:
        bars_1m = self.get_today_session_bars(ticker)
Then call materialize_5m_bars(ticker, bars) from store_bars() callers that already have the bars in hand.

15.H-5 — update_ticker() only fetches "yesterday's bars" when last_bar_date < today — skips weekends, resulting in Monday startup missing Friday's bars
File: data_manager.py

python
if last_bar_date < today_et:
    yesterday = today_et - timedelta(days=1)
    from_ts = int(datetime.combine(yesterday, dtime(4, 0)).replace(tzinfo=ET).timestamp())
    to_ts   = int(datetime.combine(yesterday, dtime(20, 0)).replace(tzinfo=ET).timestamp())
    label = f"yesterday's bars ({yesterday})"
On Monday morning, last_bar_date is Friday. yesterday is Sunday — a non-trading day. The fetch for Sunday returns zero bars. Friday's bars are never fetched. The scanner starts Monday with Thursday's data as the most recent historical bars, making PDH/PDL calculations and BOS detection use stale data. This is the Monday gap bug.

Fix: Fetch from last_bar_date + 1 day to today, not just a hardcoded "yesterday":

python
fetch_from_date = last_bar_date + timedelta(days=1)
from_ts = int(datetime.combine(fetch_from_date, dtime(4, 0)).replace(tzinfo=ET).timestamp())
to_ts   = int((today_midnight - timedelta(seconds=1)).timestamp())
15.H-6 — startup_backfill_with_cache() calls last_cached.replace(tzinfo=ET) to build from_ts for gap-fill — incorrect for UTC-stored timestamps on Postgres
File: data_manager.py

python
from_ts = int(last_cached.replace(tzinfo=ET).timestamp())
last_cached is the naive last_bar_time from cache metadata — stored as UTC on Postgres. Stamping it with ET and converting to a Unix timestamp produces a from_ts that is 4-5 hours too late. The gap-fill fetch starts 4 hours after where it should, missing hours of intraday bars. For example, a cache current to 18:30 UTC (14:30 ET) would produce a from_ts of 18:30 ET = 22:30 UTC, skipping the 14:30–22:30 UTC window entirely.

Fix: Treat stored naive datetimes as UTC, convert to ET for display only:

python
if last_cached.tzinfo is None:
    last_cached_utc = last_cached.replace(tzinfo=ZoneInfo("UTC"))
else:
    last_cached_utc = last_cached
from_ts = int(last_cached_utc.timestamp())
15.H-7 — get_vix_level() queries get_bars_from_memory("VIX", limit=1) then get_latest_bar("VIX") — two DB round-trips before the REST fallback
File: data_manager.py

python
def get_vix_level(self) -> Optional[float]:
    bars = self.get_bars_from_memory("VIX", limit=1)   # DB query #1
    if bars:
        return bars[-1]["close"]
    bar = self.get_latest_bar("VIX")                   # DB query #2
    if bar:
        return bar["close"]
    # REST fallback
get_bars_from_memory(ticker, limit=1) already queries ORDER BY datetime DESC LIMIT 1 from intraday_bars. get_latest_bar() does the same query. If the first returns nothing, the second will also return nothing — they query the same table with the same logic. The second call is always redundant. Additionally, get_bars_from_memory() with limit=1 checks the WS feed first via self._get_ws_bar(ticker) — but "VIX" is an index, not a traded ticker, so the WS feed will never have it. The VIX is unlikely to be in intraday_bars either unless explicitly scanned.

Fix: Remove the redundant second DB call. Go straight from get_bars_from_memory to the REST fallback.

15.H-8 — _get_ws_bar() does from ws_feed import is_connected, get_current_bar inside the function body — repeated dynamic import on every call
File: data_manager.py

python
def _get_ws_bar(self, ticker: str) -> Optional[Dict]:
    try:
        from ws_feed import is_connected, get_current_bar
        if is_connected():
            return get_current_bar(ticker)
    except ImportError:
        pass
This dynamic import runs inside a hot path — _get_ws_bar() is called from get_latest_bar(), get_bars_from_memory(), and bulk_fetch_live_snapshots(). While Python caches module imports in sys.modules, the from ... import attribute lookup still has overhead when called thousands of times per session (30 tickers × 5s scan cycle × 6.5hr session ≈ 140,400 calls). The ImportError catch also masks a real misconfiguration silently.

Fix: Import at module top-level with a guarded try/except, caching the result:

python
try:
    from ws_feed import is_connected as _ws_is_connected, get_current_bar as _ws_get_bar
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
🟠 Mediums (6)
ID	File	Issue
15.M-9	data_manager.py	store_bars() uses upsert_metadata_sql() which stores bar_count = len(bars) — the count of the current batch, not the cumulative total. After a gap-fill of 15 bars, fetch_metadata.bar_count becomes 15 regardless of how many bars were previously stored. This is the same additive bug fixed in candle_cache (C4 FIX) but never fixed here. get_database_stats() returns the correct count from COUNT(*), but fetch_metadata.bar_count is always wrong.
15.M-10	data_manager.py	cleanup_old_bars() uses datetime.now() without timezone — produces naive local time, not ET. On Railway (UTC server), this deletes bars older than 60 days UTC, which is correct for absolute time but inconsistent with the ET-naive timestamps stored in the DB. Should use datetime.now(ET).replace(tzinfo=None) for consistency.
15.M-11	data_manager.py	bulk_fetch_live_snapshots() has a logic error in the WS/API count summary: ws_count = len(result) - len([t for t in tickers_needing_api if t in result]). tickers_needing_api was already filtered to exclude WS tickers, so len(result) - api_count is not the WS count — it's the count of tickers that had WS data minus those also in tickers_needing_api, which is always 0. The log line always prints WS: 0.
15.M-12	data_manager.py	_fetch_range() validates required fields with [k for k in required if k not in bar or bar[k] is None]. The volume field check bar["volume"] is None is correct, but bar["volume"] = 0 passes the check and the comment says "Can be 0 legitimately." However, int(bar["volume"]) where bar["volume"] is a float string like "0.0" will raise ValueError. EODHD sometimes returns "volume": 0.0 (float) for index bars. Should be int(float(bar["volume"])).
15.M-13	data_manager.py	get_previous_day_ohlc() walks back up to 5 days. For a Monday call, it tries Saturday, Friday (returns data), done. But it makes a live EODHD /eod/ API call for each day in sequence. Saturday and Sunday calls hit the API unnecessarily. Should skip weekends explicitly: if target_date.weekday() >= 5: continue.
15.M-14	data_manager.py	background_cache_sync() has the same broken tz comparison as 15.C-2: age_minutes = (now_et - last_cached.replace(tzinfo=ET if last_cached.tzinfo is None else None)).total_seconds() / 60. Will raise TypeError and silently skip sync for all tickers when last_cached is tz-aware.
🟢 Lows (4)
ID	File	Issue
15.L-15	data_manager.py	data_manager = DataManager() singleton at module scope calls initialize_database() at import time — same pattern as every other module. Runs DDL and the version migration check on every import.
15.L-16	data_manager.py	clear_prev_day_cache() is marked DEPRECATED and is a pass. Remove the method entirely or raise DeprecationWarning. Dead methods in the public API add confusion.
15.L-17	data_manager.py	_logged_skip is a module-level set() defined but never populated or read anywhere in this file. It was likely used by a removed function. Dead code — remove.
15.L-18	data_manager.py	All print() calls should be logger.*. Same pattern flagged in batches 8–14.
Priority Fix Order
15.C-1 — Destructive migration guard — DELETE all bars can fire mid-session on transient DB errors

15.C-2 / 15.M-14 — Inverted tz conditional in startup_backfill_with_cache() and background_cache_sync() — TypeError silently falls through to full API backfill on every startup, defeating the cache entirely

15.H-3 — _parse_bar_rows() strips TZ → 5m bar timestamps off by 4-5 hours on Railway → all downstream signal generation uses wrong bar buckets

15.H-5 — Monday startup missing Friday bars — update_ticker() fetches "yesterday" (Sunday) instead of the true last trading day gap

15.H-6 — last_cached.replace(tzinfo=ET) on UTC-stored timestamp → gap-fill from_ts 4 hours too late → missing hours of intraday bars

15.H-4 — Double pool checkout per materialization — consolidate get_today_session_bars() + upsert into single connection

15.M-9 — upsert_metadata_sql() stores len(bars) (batch count) not cumulative total — fetch_metadata.bar_count always wrong
