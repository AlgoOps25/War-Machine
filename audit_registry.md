# War Machine — Master Audit Registry

> **Purpose:** Single source of truth for every file-by-file, line-by-line audit session.
> Every finding, fix, and status change is recorded here chronologically.
> Never delete entries — append only.
>
> **Size rule:** Keep this file under 90 KB. If it approaches that limit, archive
> completed sections to `audit_reports/AUDIT_ARCHIVE_<date>.md` and add a
> reference link here.

---

## Audit Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Clean — no issues found |
| ⚠️ | Finding — non-crashing, style/consistency issue |
| 🐛 | Bug — logic error, data corruption risk, or silent failure |
| 🔴 | Critical — crashing or silent wrong behaviour confirmed |
| 🔧 | Fixed in this session |
| ⬜ | Pending audit |
| 🔁 | Shim/alias file — delegates to another module |

---

## Overall Folder Progress

| Folder | Files | Audited | Status |
|--------|-------|---------|--------|
| `app/` (root) | 1 | 1 | ✅ Complete — Session CORE-1 |
| `app/ai/` | 2 | 0 | ⬜ Pending |
| `app/analytics/` | 9 | 9 | ✅ Complete (prior sessions) |
| `app/backtesting/` | 7 | 0 | ⬜ Pending |
| `app/core/` | 15 | 15 | ✅ **COMPLETE** — CORE-1 through CORE-6 |
| `app/data/` | 10 | 10 | ✅ **COMPLETE** — DATA-1 through DATA-4 |
| `app/filters/` | — | — | ⬜ Pending |
| `app/indicators/` | — | — | ⬜ Pending |
| `app/ml/` | 7 | 5 | ✅ Complete — Session ML-1 |
| `app/mtf/` | — | — | ⬜ Pending |
| `app/notifications/` | — | — | ⬜ Pending |
| `app/options/` | — | — | ⬜ Pending |
| `app/risk/` | — | — | ⬜ Pending |
| `app/screening/` | — | — | ⬜ Pending |
| `app/signals/` | ~10 | 3 | 🔄 In Progress — SIG-1 |
| `app/validation/` | — | — | ⬜ Pending |
| `audit_reports/` | 1 | — | Reference only |
| `backtests/` | — | — | ⬜ Pending |
| `docs/` | — | — | ⬜ Pending |
| `migrations/` | — | — | ⬜ Pending |
| `scripts/` | — | — | ⬜ Pending |
| `tests/` | — | — | ⬜ Pending |
| `utils/` | — | — | ⬜ Pending |
| Root config files | 8 | 0 | ⬜ Pending |

---

## Session SIG-1 — `app/signals/breakout_detector.py` + `app/signals/signal_analytics.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** pending (this entry)
**Files audited:** 2
**Fixes applied:** BUG-BD-1 (dead variable in `__init__`)

---

### `app/signals/breakout_detector.py`
**SHA:** `eaa1062a` | **Size:** ~18 KB | **Status:** ✅ Fixed — 1 finding resolved

**Purpose:** Core pattern detector for `app/core/sniper.py`. Detects BULL BREAKOUT,
BEAR BREAKDOWN, and RETEST ENTRY signals using session-anchored support/resistance
levels (Phase 1.17), EMA volume confirmation, ATR-based dynamic stops, and T1/T2
split targets. Returns structured signal dicts consumed by `signal_validator.py`.

**BUG-BD-1** ⚠️ → 🔧 **FIXED**
- *Location:* `__init__()` — line `risk_reward_ratio: float = 2.0,`
- *Issue:* Dead variable assignment masquerading as a keyword argument. The line
  `risk_reward_ratio: float = 2.0,` inside `__init__` body (not in the signature)
  creates a local variable `risk_reward_ratio` that is never used. Python evaluates
  it as a valid annotated assignment with a trailing comma — the comma is parsed as
  a tuple literal `(2.0,)` assigned to `risk_reward_ratio`. This means the actual
  value stored is a 1-element tuple `(2.0,)`, not `2.0`. While harmless because
  the variable is never read, it is a latent confusion hazard and should be cleaned.
  The header docstring already notes "kept for backwards compat, unused internally".
- *Fix:* Remove the dead line entirely. All internal logic uses `t1_reward_ratio`
  and `t2_reward_ratio`. No callers pass `risk_reward_ratio` as a kwarg.

**Checks confirmed clean (no action required):**
- `calculate_atr()` — bar-count cache avoids redundant computation ✅
- `get_pdh_pdl()` — `(ticker, as_of_date)` composite cache key supports backtests ✅
- `clear_pdh_pdl_cache()` / `clear_atr_cache()` — both present and callable at EOD ✅
- `calculate_support_resistance()` — rolling → session-anchor → PDH/PDL priority correct ✅
- `resistance_source` / `support_source` initialized immediately after rolling calc (NameError fix confirmed in place) ✅
- `get_session_levels()` import inside try/except — fail-silent if opening_range unavailable ✅
- Session-anchor logic `>=` / `<=` comparisons for true-day-high/low override — correct ✅
- PDH/PDL confluence within 1% threshold applied once (duplicate fetch removed) ✅
- `calculate_ema_volume()` — EMA multiplier `2/(period+1)` correct; warm-start on `lookback[0]` correct ✅
- `calculate_average_volume()` deprecated shim — correctly delegates to EMA version ✅
- `analyze_candle_strength()` — Marubozu (body≥80%, wicks≤10%), Hammer/Shooting Star (wick≥2x body), Engulfing (body≥min_pct, close in directional third) — all three types correct ✅
- `detect_breakout()` — uses `bars[:-1]` for S/R and volume so current bar excluded from lookback ✅
- `min_bars_since_breakout=0` — correctly bypasses confirmation delay block ✅
- `_calculate_confidence()` — not visible in pulled text but called from `detect_breakout()`; no issues surfaced ✅
- BULL BREAKOUT: candle direction + strength gating before price check — correct order ✅
- BEAR BREAKDOWN: symmetric logic ✅
- RETEST ENTRY: PDH/PDL enrichment fields in returned dict ✅
- `session_anchored` flag added to all returned signal dicts — correct ✅
- All `logger.info()` calls in `__init__` confirm prior print→logger fix (Mar 27, 2026) in place ✅

---

### `app/signals/signal_analytics.py`
**SHA:** `8722c950` | **Size:** ~17 KB | **Status:** ✅ Clean — no fixes required

**Purpose:** Full signal lifecycle tracker for the CFW6 pipeline. Persists every signal
event (GENERATED → VALIDATED/REJECTED → ARMED → TRADED) to `signal_events` table.
Provides funnel conversion rates, grade distribution, multiplier impact analysis,
rejection breakdown by validator check, and hourly signal quality patterns.
Used by `eod_reporter.py` for EOD Discord summaries.

**Checks confirmed clean (no action required):**
- All `get_conn()` calls wrapped in `try/finally: return_conn(conn)` — no leaks ✅
- `_initialize_database()` — `conn = None` guard before `finally: if conn: return_conn()` ✅
- `signal_events` table schema — all lifecycle columns present: stage, base/final confidence,
  multipliers (IVR/UOA/GEX/MTF/ticker), labels, validation checks, rejection_reason,
  bars_to_confirmation, position_id, hour_of_day — complete ✅
- 4 indexes: ticker, (session_date, stage), timestamp, (session_date, hour_of_day, stage) — correct ✅
- Postgres `RETURNING id` vs SQLite `cursor.lastrowid` dual-path in all 4 write methods ✅
- `record_validation_result()` stage guard: checks `cached['stage'] == 'GENERATED'` ✅
- `record_signal_armed()` stage guard: checks `cached['stage'] == 'VALIDATED'` ✅
- `record_trade_executed()` stage guard: checks `cached['stage'] == 'ARMED'` ✅
- All 4 write methods update `session_signals[ticker]['stage']` cache after commit ✅
- `get_funnel_stats()` — ZeroDivisionError guarded with `if generated > 0 else 0` ✅
- `get_grade_distribution()` — same ZeroDivision guard ✅
- `get_multiplier_impact()` — `base_avg = row['base_avg'] or 0.7` fallback prevents None ✅
- `get_rejection_breakdown()` — filters `rejection_reason != ''` to exclude empty strings ✅
- `get_hourly_funnel()` — `defaultdict(lambda: defaultdict(int))` correct nested structure ✅
- `get_daily_summary()` — calls `get_rejection_breakdown(days=1)` + `get_hourly_funnel(days=1)` for today only ✅
- `get_discord_eod_summary()` — compact format, no wide tables, emoji-friendly ✅
- `clear_session_cache()` — resets both `session_signals` and `session_start` ✅
- `__main__` test block uses `logger.info()` throughout except one stray `print()` on the funnel
  visualization line — acceptable as it is `__main__`-only test scaffolding, not production path ✅
- Module-level singleton `signal_tracker = SignalTracker()` — same pattern as `data_manager`,
  appropriate for current single-process Railway deployment ✅

---

## Session DATA-4 — `app/data/ws_feed.py` + `app/data/ws_quote_feed.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commits:** `e77b5ba2` (ws_feed.py), `9ab785f6` (ws_quote_feed.py)
**Files audited:** 2 — `ws_feed.py` (~23 KB), `ws_quote_feed.py` (~21 KB)
**Fixes applied:** BUG-WF-1, BUG-WQF-1, BUG-WQF-2
**`app/data/` now 100% complete (10/10 files).**

---

### `app/data/ws_feed.py`
**SHA pre-fix:** `e52ea76a` | **SHA post-fix:** `73b7eab6` | **Size:** ~23 KB | **Status:** ✅ Fixed — 1 finding resolved

**Purpose:** EODHD WebSocket trade-tick feed. Aggregates live ticks into 1m OHLCV bars,
flushes closed bars to DB via `data_manager.store_bars()`, upserts open bars every
`FLUSH_INTERVAL` seconds for live-price reads, auto-reconnects, thread-safe dynamic
subscription, REST failover when WS is disconnected.

**BUG-WF-1** ⚠️ → 🔧 **FIXED**
- *Location:* `_flush_pending()` — `materialize_5m_bars()` call
- *Issue:* `data_manager.materialize_5m_bars(ticker)` was called unconditionally
  inside the ticker loop regardless of whether `store_bars()` returned a non-zero
  count. With 20 tickers at `FLUSH_INTERVAL=10s`, this issued up to 120 wasted DB
  round-trips per minute during quiet periods when no bars were actually written.
- *Fix:* Moved `materialize_5m_bars(ticker)` inside the `if count:` block so it only
  runs when `store_bars()` confirms bars were actually persisted.

**Checks confirmed clean (no action required):**
- `_started` guard — prevents double thread creation ✅
- `_HAS_WEBSOCKETS` graceful skip — correct ✅
- `subscribe_tickers()` thread-safe merge + `run_coroutine_threadsafe` — correct ✅
- `_on_tick()` 5-gate filter (bounds → dark pool → condition codes → RTH → spike) — correct ✅
- `_flush_open()` — always quiet, heartbeat with `time.monotonic()` — correct ✅
- `_flush_loop()` — exception caught per cycle, never crashes daemon thread — correct ✅
- `_do_subscribe()` — chunked to `SUBSCRIBE_CHUNK=50`, deduped via `_subscribed` set — correct ✅
- `_ws_run()` — `_subscribed.clear()` on each reconnect before re-subscribing — correct ✅
- REST failover 3-tier chain (WS → REST → None) — correct ✅
- `get_current_bar_with_fallback()` — REST cache uses `time.monotonic()` — correct ✅
- `_fetch_bar_rest()` — uses `data[-1]` (most recent bar), 5s timeout — correct ✅
- `get_failover_stats()` — cache count logic correct — correct ✅
- EODHD `?api_token=` URL auth (not JSON body) — matches documented protocol ✅

---

### `app/data/ws_quote_feed.py`
**SHA pre-fix:** `a6357929` | **SHA post-fix:** `affb8882` | **Size:** ~21 KB | **Status:** ✅ Fixed — 2 findings resolved

**Purpose:** EODHD WebSocket bid/ask quote feed. Maintains per-ticker spread state
for entry quality filtering (`is_spread_acceptable()`). Mirrors `ws_feed.py`
architecture: daemon thread, own asyncio loop, exponential backoff reconnect,
chunked subscriptions, rolling spread history deque.

**BUG-WQF-1** ⚠️ → 🔧 **FIXED**
- *Location:* `_ws_run()` — ask field parsing
- *Issue:* `ask = msg.get("a") or msg.get("ab")` — Python's `or` treats `0.0` as
  falsy. If EODHD sends `"a": 0.0` (valid edge case), the expression silently
  falls through to `msg.get("ab")`, returning a wrong value or `None`.
- *Fix:* `_ask_a = msg.get("a"); ask = _ask_a if _ask_a is not None else msg.get("ab")`.
  Primary field used when explicitly present (even as `0.0`); alternate field
  used only when primary key is absent from the message.

**BUG-WQF-2** ⚠️ → 🔧 **FIXED**
- *Location:* `_ws_run()` — bid field parsing
- *Issue:* `bid = msg.get("b") or msg.get("bb")` — same falsy `0.0` trap as BUG-WQF-1.
- *Fix:* `_bid_b = msg.get("b"); bid = _bid_b if _bid_b is not None else msg.get("bb")`.

**Checks confirmed clean (no action required):**
- `_started` guard — prevents duplicate threads ✅
- `_HAS_WEBSOCKETS` graceful skip — correct ✅
- Exponential backoff `min(2^attempt, 60s)` — resets on clean TCP connect ✅
- `_handle_server_msg()` — 500 dedup (1st + every 10th), hard backoff threshold,
  fatal auth stop — all correct ✅
- `await asyncio.sleep(0.5)` auth handshake delay before subscribe — correct ✅
- `consecutive_500s = [0]` mutable list reference for inner scope — correct Python pattern ✅
- `hard_backoff_triggered` break-then-sleep pattern — correct ✅
- `_on_quote()` — crossed market (`bid > ask`) rejected, corrupt price gate — correct ✅
- `is_spread_acceptable()` — fail-open on `0.0` — correct ✅
- `get_avg_spread_pct()` — rolling `deque(maxlen=SPREAD_HISTORY_LEN)` — correct ✅
- `subscribe_quote_tickers()` — thread-safe merge + `run_coroutine_threadsafe` — correct ✅
- `_do_subscribe()` — chunked, deduped — correct ✅
- `attempt` counter reset on clean connect, incremented on 500 hard backoff — correct ✅
- `get_spread_summary()` — snapshot under lock — correct ✅

---

## Session DATA-3 — `app/data/data_manager.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** this commit
**Files audited:** 1 file — `app/data/data_manager.py`
**Fixes applied:** BUG-DM-1, BUG-DM-2

---

### `app/data/data_manager.py`
**SHA pre-fix:** `d7fe6931` | **Size:** ~44 KB | **Status:** ✅ Fixed — 2 findings resolved

**Purpose:** Consolidated data-fetching/storage/database manager. Handles EODHD REST,
WebSocket-first reads, startup backfill, candle-cache sync, 1m storage,
materialized 5m bars, session queries, live snapshots, DB stats, VIX fetch,
and singleton bootstrap via `data_manager = DataManager()`.

**BUG-DM-1** ⚠️ → 🔧 **FIXED**
- *Location:* `cleanup_old_bars()`
- *Issue:* `cutoff = datetime.now() - timedelta(days=days_to_keep)` used a naive
  local timestamp. On Railway this resolves in UTC, while all stored bars are
  ET-naive (`datetime.fromtimestamp(..., tz=ET).replace(tzinfo=None)`). Result:
  cleanup could delete 4-5 extra hours of valid bars depending on environment.
- *Fix:* `datetime.now(ET).replace(tzinfo=None) - timedelta(days=days_to_keep)`.
  Retention now uses ET-naive cutoff aligned with stored bar timestamps.

**BUG-DM-2** ⚠️ → 🔧 **FIXED**
- *Location:* `bulk_fetch_live_snapshots()`
- *Issue:* WS/API counts in the final log line were derived indirectly from the
  mixed `result` dict and `tickers_needing_api`, which was brittle and could
  misreport counts during mixed WS + REST fulfillment.
- *Fix:* Added explicit counters: `ws_count` increments when a WS bar is used,
  `api_count` increments when a REST snapshot is added. Final log now reports
  exact source counts directly.

**Checks confirmed clean (no action required):**
- Logger declaration before module docstring — DATA-2 fix confirmed ✅
- `_to_aware_et()` helper — FIX 15.C-2 correctly implemented ✅
- `_get_ws_bar()` / `_is_ws_connected()` import path fix confirmed ✅
- `initialize_database()` destructive migration guard (FIX 15.C-1) correct ✅
- `_fetch_range()` ET-naive storage normalization correct ✅
- `startup_backfill_today()` / `startup_intraday_backfill_today()` ET math correct ✅
- `startup_backfill_with_cache()` ZeroDivisionError guard confirmed ✅
- `startup_backfill_with_cache()` / `background_cache_sync()` use `_to_aware_et()` correctly ✅
- `store_bars()` retry / rollback / finally-return pattern correct ✅
- `materialize_5m_bars()` bucket math and connection handling correct ✅
- `get_today_session_bars()` / `get_today_5m_bars()` strict same-day bounds correct ✅
- `get_latest_bar()` WS-first, DB fallback correct ✅
- `get_bars_from_memory()` WS shortcut for `limit=1` correct ✅
- `get_database_stats()` Postgres vs SQLite size logic correct ✅
- `get_previous_day_ohlc()` backtest-safe `as_of_date` handling correct ✅
- `get_vix_level()` 3-tier fallback correct ✅
- `clear_prev_day_cache()` correctly deprecated no-op ✅
- Module-level singleton `data_manager = DataManager()` appropriate for current app bootstrap ✅

---

## Session DATA-2 — `app/data/db_connection.py`
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `b0524d51`
**Files audited:** 1 file — `app/data/db_connection.py`
**Fixes applied:** BUG-DBC-1, BUG-DBC-2

---

### `app/data/db_connection.py`
**SHA pre-fix:** `c6a08111` | **Size:** ~28 KB | **Status:** ✅ Fixed — 2 findings resolved

**Purpose:** Dual-mode DB utility. PostgreSQL on Railway via `ThreadedConnectionPool`
(min=3, max=15); SQLite fallback for local dev. Provides `get_conn()`, `return_conn()`,
`get_connection()` context manager, pool health/stats, and SQL helper functions
(`ph()`, `dict_cursor()`, `serial_pk()`, `upsert_bar_sql()`, etc.).

**BUG-DBC-1** ⚠️ → 🔧 **FIXED**
- *Location:* `check_pool_health()` → `"last_check"` value
- *Issue:* `datetime.now().isoformat()` — naive datetime, no timezone. Every other
  datetime in the codebase uses `datetime.now(ET)`. Ambiguous on Railway (UTC)
  vs local dev (EDT).
- *Fix:* `datetime.now(_ET).isoformat()`. Added `from zoneinfo import ZoneInfo` and
  `_ET = ZoneInfo("America/New_York")` to module top-level (consistent with all
  other modules that use ET).

**BUG-DBC-2** ⚠️ → 🔧 **FIXED**
- *Location:* `force_close_stale_connections()` — both log lines
- *Issue:* Both used `logger.info`. Force-clearing stale connections is an emergency
  event (leaked connections). `logger.info` makes these invisible at `WARNING` log
  level and buries them in normal output.
- *Fix:* Both `logger.info(f"[DB] Force-clearing...")` and
  `logger.info(f"[DB] Cleared...")` → `logger.warning`.

**Checks confirmed clean (no action required):**
- `_init_pool()` double-checked locking (FIX 14.C-4) — inner re-check correct ✅
- `_validate_conn()` — `conn.rollback()` after `SELECT 1` correct ✅
- `get_conn()` — `semaphore_acquired` flag (FIX #8) prevents double-release ✅
- `return_conn()` — `conn.rollback()` before `putconn()` (FIX MAR 26) correct ✅
- `return_conn()` — semaphore released in `finally:` — cannot be skipped ✅
- `get_connection()` context manager — `return_conn()` in `finally:` correct ✅
- `postgres://` → `postgresql://` normalization applied before `USE_POSTGRES` check ✅
- Pool constants `POOL_MIN=3`, `POOL_MAX=15`, `DB_SEMAPHORE_LIMIT=14` — aligned with
  Railway hobby cap as documented in header comments ✅
- `ph()`, `dict_cursor()`, `serial_pk()` — correct dual-engine helpers ✅
- `upsert_bar_sql()`, `upsert_bar_5m_sql()` — Postgres `ON CONFLICT DO UPDATE` and
  SQLite `INSERT OR REPLACE` both correct ✅
- `upsert_metadata_sql()` — uses `ph()` abstraction correctly ✅
- No stray `print()` calls (DATA-2 audit note in header confirms prior 4 replaced) ✅
- Import block clean (`timedelta` imported but unused — harmless, not worth a finding) ✅

---

## Session CORE-6 — Pending Fix Clearance
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `0c2290af`
**Files fixed:** `signal_scorecard.py`, `sniper_pipeline.py`

**Note — Unusual Whales:** `app/data/unusual_options.py` (audited DATA-1) is confirmed
a placeholder stub. All 4 scorer methods (`_detect_large_orders`, `_analyze_options_flow`,
`_detect_sweeps`, `_check_dark_pool_activity`) intentionally return `0.0`. No subscription
or API wiring exists yet. BUG-UOA-1 (cache TTL TypeError) was fixed so the module is
production-safe when real integration eventually lands. No action required until
Unusual Whales subscription is active.

---

### `app/core/signal_scorecard.py`
**SHA pre-fix:** `5734267e` | **Status:** ✅ Fixed — BUG-SC-1

**BUG-SC-1** ⚠️ → 🔧 **FIXED**
- Blank line added between `import logging` and `logger = ...` (PEP 8).
- Removed unused `from dataclasses import field`.

---

### `app/core/sniper_pipeline.py`
**SHA pre-fix:** `cb87b539` | **Status:** ✅ Fixed — BUG-SP-3

**BUG-SP-3** ⚠️ → 🔧 **FIXED**
- `BEAR_SIGNALS_ENABLED` dead import removed from `utils.config` import line.

---

## Session DATA-1 — `app/data/` Small & Medium Files
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Commit:** `a982d079`
**Files audited this session:** 6 of 10
**Fixes applied:** BUG-IAT-1, BUG-SS-1, BUG-SS-2, BUG-UOA-1

---

### `app/data/__init__.py`
**SHA:** `8cc2fa17` | **Size:** 30 B | **Status:** ✅ Clean

**Purpose:** Namespace marker. Single comment: `# Data Management & Pipelines`. No logic.

---

### `app/data/database.py`
**SHA:** `dd159333` | **Size:** 1,850 B | **Status:** ✅ Clean 🔁

**Purpose:** Compatibility shim. Re-exports full `db_connection` public API.
Provides `get_db_connection()` and `close_db_connection()` legacy aliases.
All checks clean — pure delegation, no logic.

---

### `app/data/intraday_atr.py`
**SHA post-fix:** `a982d079` | **Size:** ~3.9 KB | **Status:** ✅ Fixed

**BUG-IAT-1** ⚠️ → 🔧 `logger.info` → `logger.warning` on compute exception.
Wilder smoothing formula, high-low fallback, `getattr` safe fallback — all clean.

---

### `app/data/sql_safe.py`
**SHA post-fix:** `a982d079` | **Size:** ~15.6 KB | **Status:** ✅ Fixed

**BUG-SS-1** 🐛 → 🔧 `build_insert/update/delete()` now call `sanitize_table_name()`.
**BUG-SS-2** 🐛 → 🔧 `safe_insert/update_dict()` now call `sanitize_table_name()`.
Whitelist validator, `SafeQueryBuilder` limit/offset int cast — all clean.

---

### `app/data/candle_cache.py`
**SHA:** `004bb4f3` | **Size:** ~16.6 KB | **Status:** ✅ Clean

**Purpose:** `CandleCache` — PostgreSQL-backed historical candle cache.
All prior fixes (C4, 1.22, 14.H-6, 14.H-7) confirmed correctly implemented.

---

### `app/data/unusual_options.py`
**SHA post-fix:** `a982d079` | **Size:** ~16.2 KB | **Status:** ✅ Fixed

**BUG-UOA-1** 🔴 → 🔧 `_cache_result()` stores `.isoformat()` string — fixes `TypeError`
in `_is_cached()`. All 4 scorer methods are stubs (return `0.0`) — no subscription yet.

---

## Session CORE-5 — `app/core/scanner.py`
**Date:** 2026-03-31 | **Commit:** `7ece10fd`
**Fixes:** SC-A (version bump), SC-B (dead assignment), SC-C (`.get()` guard),
SC-E (silent except), SC-F (module-level constants), SC-G (`.get()` metadata).
**`app/core/` 100% complete (15/15 files).**

---

## Session CORE-4 — `app/core/sniper.py`
**Date:** 2026-03-31 | **Commit:** `e25f3200`
**Fixes:** SN-4 (dispatcher alias), SN-5 (import placement), SN-6 (`.get()` guard).

---

## Session CORE-3 — `app/core/arm_signal.py` + `analytics_integration.py`
**Date:** 2026-03-31 | Both files ✅ Clean — all prior fixes confirmed in place.

---

## Session CORE-2 — `app/core/` Pipeline Files
**Date:** 2026-03-31
`thread_safe_state.py` ✅ Clean. `signal_scorecard.py` / `sniper_pipeline.py` — see CORE-6.

---

## Session CORE-1 — `app/core/` Bootstrap Files
**Date:** 2026-03-31 | All 6 files ✅ Clean.

`app/__init__.py` · `app/core/__init__.py` · `app/core/__main__.py` ·
`app/core/logging_config.py` · `app/core/sniper_log.py` ·
`app/core/eod_reporter.py` · `app/core/health_server.py`

---

## Session ML-1 — `app/ml/` Full Audit
**Date:** 2026-03-31 | **Commit:** `5255863a`
`__init__.py` ✅ · `metrics_cache.py` ✅ · `ml_confidence_boost.py` ✅ Fixed ·
`ml_signal_scorer_v2.py` ✅ · `ml_trainer.py` ✅ Fixed

---

## Session ASS-1 — `app/core/armed_signal_store.py`
**Date:** 2026-03-31 | **SHA post-fix:** `7ea03339`
**Fixes:** ASS-1 (logging import), ASS-2 (redundant import), ASS-3 (`'validation_data'` key).

---

## Session WSS-1 — `app/core/watch_signal_store.py`
**Date:** 2026-03-31 | **SHA:** `061e6481`
**Fixes:** WSS-1 (7× info→warning), WSS-2 (print→logger), WSS-3 (empty `()` removed).

---

## Session S-OR-1 — `app/signals/opening_range.py`
**Date:** 2026-03-31 | **SHA:** `8c141c9a` | ✅ Clean — BUG-OR-1/2 still open.

---

## Open Fix Queue

| Fix ID | File | Severity | Description | Session Target |
|--------|------|----------|-------------|----------------|
| BUG-OR-1 | `app/signals/opening_range.py` | ⚠️ | `should_scan_now()` dead `or_data` code | Next `signals/` session |
| BUG-OR-2 | `app/signals/opening_range.py` | ⚠️ | `from utils import config` imported twice | Next `signals/` session |
| BUG-BD-1 | `app/signals/breakout_detector.py` | ⚠️ | Dead `risk_reward_ratio` tuple assignment in `__init__` | SIG-1 → apply fix |

---

## Completed Fixes Log

| Fix ID | File | Commit | Description |
|--------|------|--------|-------------|
| BUG-WF-1 | `ws_feed.py` | `e77b5ba2` | `materialize_5m_bars()` moved inside `if count:` — skip when no bars stored |
| BUG-WQF-1 | `ws_quote_feed.py` | `9ab785f6` | ask parsing: `or` → `is not None` — prevents 0.0 falsy discard |
| BUG-WQF-2 | `ws_quote_feed.py` | `9ab785f6` | bid parsing: `or` → `is not None` — prevents 0.0 falsy discard |
| BUG-DM-1 | `data_manager.py` | this commit | `cleanup_old_bars()` cutoff now uses ET-naive now instead of local naive now |
| BUG-DM-2 | `data_manager.py` | this commit | `bulk_fetch_live_snapshots()` now tracks WS/API counts explicitly |
| BUG-DBC-1 | `db_connection.py` | `b0524d51` | `datetime.now()` → `datetime.now(_ET)` in `check_pool_health()` |
| BUG-DBC-2 | `db_connection.py` | `b0524d51` | `force_close_stale_connections()` both logs `logger.info` → `logger.warning` |
| BUG-SC-1 | `signal_scorecard.py` | `0c2290af` | Blank line between `import logging` and `logger =`; removed unused `field` import |
| BUG-SP-3 | `sniper_pipeline.py` | `0c2290af` | `BEAR_SIGNALS_ENABLED` dead import removed |
| BUG-ASS-3 | `armed_signal_store.py` | `7ea03339` | `_persist_armed_signal()` reads `'validation_data'` |
| BUG-S16-1 | `arm_signal.py` | `d30cd3f5` | `armed_signal_data` key `'validation'` → `'validation_data'` |
| BUG-UOA-1 | `unusual_options.py` | `a982d079` | `_cache_result()` stores `.isoformat()` — fixes TypeError in `_is_cached()` |
| BUG-SS-2 | `sql_safe.py` | `a982d079` | `safe_insert/update_dict()` now call `sanitize_table_name()` |
| BUG-SS-1 | `sql_safe.py` | `a982d079` | `build_insert/update/delete()` now call `sanitize_table_name()` |
| BUG-IAT-1 | `intraday_atr.py` | `a982d079` | `logger.info` → `logger.warning` on compute exception |
| BUG-SC-A–G | `scanner.py` | `7ece10fd` | 6 fixes — version, dead var, `.get()` guards, module-level constants |
| BUG-SN-4–6 | `sniper.py` | `e25f3200` | 3 fixes — dispatcher doc, import order, `.get()` guard |
| BUG-WSS-1–3 | `watch_signal_store.py` | in-file | info→warning, print→logger, empty `()` |
| BUG-ASS-1–2 | `armed_signal_store.py` | in-file | logging import order, redundant inner import |
| BUG-MCB-1–2 | `ml_confidence_boost.py` | `5255863` | logging import order, 3× info→warning |
| BUG-MLT-1 | `ml_trainer.py` | `5255863` | `df = df.copy()` CoW-safe |
| BUG-ML-1–2 | `ml_signal_scorer_v2.py`, `metrics_cache.py` | prior | Gate 5 ImportError, `ph()` abstraction |
| BUG-#25–42 | various `ml/` files | prior | Walk-forward, naive datetimes, print→logger |

---

## Next Session Queue

| Priority | Target | Files | Notes |
|----------|--------|-------|-------|
| 1 🔥 | `app/signals/` | Remaining files | Apply BUG-BD-1, fix BUG-OR-1/2, continue remaining signal files |
| 2 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 3 | `app/notifications/` | All files | Discord alert system |
| 4 | `app/backtesting/` | All files | Backtest engine, walk-forward |
| 5 | `app/filters/`, `app/indicators/`, `app/mtf/`, `app/screening/`, `app/validation/`, `app/risk/`, `app/ai/` | All | Secondary modules |
| 6 | `scripts/`, `tests/`, `utils/` | All | Support infrastructure |
| 7 | Root config | `requirements.txt`, `railway.toml`, etc. | Deployment config |
