# Batch 54 — `app/core/` Audit

**Date:** 2026-03-27
**Auditor:** Perplexity / War Machine Audit System
**Files audited:** 15
**Issues found:** 3 (Issue #52, #53, #54)
**Fixes confirmed this batch:** Issue #51 CLOSED — `/health` endpoint confirmed implemented

---

## Scope

`app/core/` is the **operational brain** of War Machine. It contains the main scanner loop, the two-path signal engine (CFW6), the health server, state management, signal scoring, signal arming, and all EOD reporting. Every trade that War Machine executes flows through this directory.

### File Inventory

| File | Size | Role |
|---|---|---|
| `__init__.py` | 22 B | Package marker (empty) |
| `__main__.py` | 1.3 KB | `python -m app.core` entry point — boot order controller |
| `scanner.py` | 31.6 KB | Main loop — schedule, watchlist, position monitor, EOD |
| `sniper.py` | 29.4 KB | CFW6 strategy engine — OR + intraday BOS+FVG paths |
| `sniper_pipeline.py` | 14.7 KB | 13-gate signal pipeline (extracted from sniper.py) |
| `sniper_log.py` | 2.4 KB | Structured pre-arm trade logger |
| `arm_signal.py` | 8.2 KB | Signal arming — position open, Discord, persist, cooldown |
| `signal_scorecard.py` | 10.2 KB | 0–100 signal scorecard with 60-pt gate |
| `health_server.py` | 4.6 KB | Lightweight HTTP `/health` for Railway probes |
| `logging_config.py` | 3.6 KB | Centralised logging setup (call once at startup) |
| `thread_safe_state.py` | 10.8 KB | Thread-safe singleton state for armed/watch signals |
| `armed_signal_store.py` | 8.6 KB | DB persistence for armed signals (`armed_signals_persist`) |
| `watch_signal_store.py` | 9.3 KB | DB persistence for watch signals (`watching_signals_persist`) |
| `analytics_integration.py` | 9.5 KB | Thin delegation wrapper over `SignalTracker` |
| `eod_reporter.py` | 4.3 KB | EOD Discord report orchestrator |

---

## Boot Order (Critical)

The system only works correctly if modules are loaded in this exact sequence:

```
python -m app.core
  └── __main__.py
        1. setup_logging()         ← logging_config.py — MUST be first
        2. start_health_server()   ← health_server.py  — MUST be before scanner import
        3. import scanner          ← triggers module-level DB connect (~10s block)
        4. start_scanner_loop()    ← enters main loop
```

This order was hardened in Phase 1.38d. Previously health server started inside `start_scanner_loop()`, meaning Railway's `/health` probe returned nothing during the DB connect block, causing false-failed deploys.

**Note:** `scanner.py` itself also calls `start_health_server()` at its module level as a second layer of protection. This is intentional — if scanner is imported alone (e.g. in tests), the health server still binds. `health_server.py` is idempotent (it just starts another daemon thread — acceptable).

---

## File-by-File Documentation

---

### `__init__.py`

**Role:** Package marker only. Empty. Makes `app/core/` importable as `app.core.*`.

---

### `__main__.py`

**Role:** Entry point for `python -m app.core`. Controls the boot order.

**Key facts:**
- Called by the Railway start command `python -m app.core.scanner` — **NOTE:** The start command in `railway.toml` / `nixpacks.toml` is `python -m app.core.scanner`, which runs `scanner.py` directly as `__main__`, NOT this file. This file is only invoked by `python -m app.core` (without `.scanner`). These are two different entry paths.
- This distinction is important: if `python -m app.core` is used, the boot order (logging → health → scanner) is guaranteed by `__main__.py`. If `python -m app.core.scanner` is used, scanner.py's own module-level `start_health_server()` call handles health, but logging may not be configured before the first import-time log line fires. (**Issue #52**)
- `if __name__ == "__main__":` guard means this only runs when invoked as a module, not when imported.

---

### `scanner.py`

**Role:** The master process loop. Owns the schedule, watchlist, position monitoring, analytics polling, and EOD tasks.

**Version:** CFW6 Scanner v1.38d

#### Module-level startup (runs at import time)

```python
from app.core.health_server import start_health_server, health_heartbeat
start_health_server()   # ← runs IMMEDIATELY on import, before any init
```

This means `/health` is bound within milliseconds of the module being loaded. Railway sees a 200 response before any DB connect or WS init.

#### Market session timing

| Function | Returns |
|---|---|
| `is_premarket()` | True 04:00–09:29 ET |
| `is_market_hours()` | True 09:30–16:00 ET weekdays |
| `should_scan_now()` | True 09:30–16:00 ET weekdays |
| `_is_or_window()` | True 09:30–09:39 ET (OR formation) |

#### Adaptive scan interval (time-of-day)

| Window | Interval | Rationale |
|---|---|---|
| 09:30–09:40 | 5s | OR Formation — BOS building rapidly |
| 09:40–11:00 | 45s | Post-OR morning — active signals |
| 11:00–14:00 | 180s | Midday chop — low signal quality |
| 14:00–15:30 | 60s | Afternoon activity |
| 15:30–16:00 | 45s | Power hour |
| Outside market | 300s | Off-hours idle |

#### Adaptive watchlist size

| Window | Size | Rationale |
|---|---|---|
| 09:30–09:40 | 30 | Focus on explosive movers at open |
| 09:40–10:30 | 30 | Morning high-conviction window |
| 10:30–15:00 | 50 | Broadened mid-session scan |
| 15:00–16:00 | 35 | Power hour refocus |

#### Main loop phases

**Pre-market (04:00–09:29):**
- Builds watchlist via `get_watchlist_with_metadata(force_refresh=True)` once
- Subscribes WS + quote feeds for watchlist tickers + `[SPY, QQQ]` regime tickers
- Refreshes watchlist if `funnel.should_update()` triggers
- Sleeps 60s between checks

**Market hours (09:30–16:00):**
1. `health_heartbeat()` — keeps `/health` alive
2. Circuit breaker check — halts new scans on 3 consecutive losses
3. `send_regime_discord()` — regime channel update
4. Rebuild watchlist from funnel (no force refresh)
5. Subscribe any new tickers via `subscribe_and_prefetch_tickers()`
6. `analytics.monitor_active_signals()` + `analytics.check_scheduled_tasks()`
7. `monitor_open_positions()` — price-check open positions via WS bar
8. Per-ticker scan: `_run_ticker_with_timeout(process_ticker, ticker)` with 45s watchdog
9. Sleep `get_adaptive_scan_interval()` seconds

**After hours / EOD:**
- Runs once per day when first entering the closed block
- `run_eod_report()` → Discord trade summary + signal funnel
- AI learning optimization (`learning_engine.optimize_*()`)
- WS failover stats logged
- DB bar cleanup (keeps 60 days)
- Candle cache cleanup (keeps 30 days)
- Full daily reset: armed signals, watches, BOS alert dedup, PDH/PDL cache, funnel

#### Ticker watchdog

```python
TICKER_TIMEOUT_SECONDS = 45
_ticker_executor = ThreadPoolExecutor(max_workers=1)
```

Each ticker is processed in a `ThreadPoolExecutor` with a 45-second `Future.result(timeout=45)` hard deadline. If `process_ticker()` hangs on a network call or lock contention, the watchdog logs the timeout and moves to the next ticker. The executor is single-threaded (`max_workers=1`) — tickers are processed sequentially with the watchdog as a hang-guard, not for parallelism.

#### Redeploy mid-session recovery

If `is_market_hours()` is True on startup (indicating a mid-session redeploy):
1. Loads the pre-built watchlist from DB (`get_watchlist_with_metadata(force_refresh=False)`)
2. Retries 2× with 3s wait if watchlist is empty
3. Falls back to `EMERGENCY_FALLBACK` if still empty after retries
4. Subscribes recovered watchlist to WS feeds
5. Sets `premarket_built = True` so the scan loop starts immediately

#### Emergency fallback watchlist

```python
EMERGENCY_FALLBACK = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD"]
```

Used when all funnel paths fail. Always liquid, always WS-subscribed. Never produces high-quality signals but keeps the system alive.

#### Known notes from code

- **NOTE #32:** `_bos_watch_alerted` is cleared at EOD via `from app.core.sniper import _bos_watch_alerted; _bos_watch_alerted.clear()`. This is a direct access to a private module-level set — should be wrapped in a `clear_bos_alerts()` function long-term.
- **NOTE #33:** `_extract_premarket_metrics()` is defined but never called. Dead code — retained for potential future Discord pre-market summary.

---

### `sniper.py`

**Role:** CFW6 strategy engine. Implements `process_ticker()` — called once per ticker per scan cycle. Determines whether to issue a trade signal via two detection paths.

**Version:** CFW6 v1.38d

#### Two scanning paths

```
process_ticker(ticker)
  ├── PATH 1: OR-ANCHORED (CFW6_OR)
  │     compute_opening_range_from_bars()
  │     → detect_breakout_after_or()   (BOS above/below OR)
  │     → detect_fvg_after_break()     (FVG after BOS)
  │     → if FVG: _run_signal_pipeline() immediately
  │     → if no FVG: enter WATCH state (up to 12 bars)
  │     → secondary range fallback after 10:30 (get_secondary_range_levels)
  │
  └── PATH 2: INTRADAY BOS+FVG (CFW6_INTRADAY) [fallback if PATH 1 fails]
        scan_bos_fvg()              (BOS + FVG in single scan)
        → MTF priority FVG resolver (get_full_mtf_analysis)
        → _run_signal_pipeline()
        → VWAP RECLAIM fallback (detect_vwap_reclaim, or_high=0/or_low=0)
```

#### Watch state lifecycle

1. BOS detected, no FVG yet → store `watching_signal` in state + DB, send BOS watch Discord alert
2. On next scan cycle: `ticker_is_watching()` → True
3. `find_fvg_after_bos()` called with `breakout_idx` restored from DB if needed
4. FVG found → `_run_signal_pipeline()` → remove watch state
5. `bars_since > MAX_WATCH_BARS (12)` → expire watch, remove from state + DB

**DB restoration (restart recovery):** If `breakout_idx` is `None` (watch was loaded from DB after restart), sniper.py resolves it by scanning `bars_session` for the bar matching `breakout_bar_dt`. If the bar isn't found in today's session, the watch is discarded.

#### Regime filter + explosive override

- `REGIME_FILTER_ENABLED = True` (hardcoded)
- If regime is unfavorable AND ticker is classified as an explosive mover (`score >= 80`, `rvol >= 3.0x`), the regime filter is bypassed
- Non-explosives in bad regimes: skipped with a log line
- Explosive override is tracked via `track_explosive_override()`

#### Key module-level globals

| Variable | Type | Purpose |
|---|---|---|
| `_bos_watch_alerted` | `set` | Deduplicates BOS watch Discord alerts; cleared EOD |
| `_orb_classifications` | `dict` | Caches OR classification for each ticker; populated at 9:40 |
| `EXPLOSIVE_SCORE_THRESHOLD` | `80` | Screener score floor for explosive override |
| `EXPLOSIVE_RVOL_THRESHOLD` | `3.0` | RVOL floor for explosive override |
| `MAX_WATCH_BARS` | `12` | Max 5m bars to wait for FVG after BOS |
| `MIN_RVOL_TO_SIGNAL` | `config.RVOL_SIGNAL_GATE` | RVOL floor for signaling |

#### Optional module loading pattern

`sniper.py` imports 15+ optional modules with `try/except ImportError` guards and `logger.info()` on miss. This means the system degrades gracefully if any single filter/module is missing. Each guard creates a stub function or sets a `*_ENABLED = False` flag. Key enabled flags:

| Flag | Module | Impact if False |
|---|---|---|
| `ORB_TRACKER_ENABLED` | `app.signals.opening_range` | No OR detection — system falls back to INTRADAY_BOS only |
| `MTF_PRIORITY_ENABLED` | `app.mtf.mtf_fvg_priority` | Uses 5m FVG directly instead of cross-timeframe resolver |
| `SPY_EMA_CONTEXT_ENABLED` | `app.filters.market_regime_context` | No SPY regime context passed to pipeline |
| `MTF_BIAS_ENABLED` | `app.filters.mtf_bias` | No MTF bias engine |
| `VWAP_RECLAIM_ENABLED` | `app.signals.vwap_reclaim` | No VWAP reclaim fallback signals |
| `SD_ZONE_ENABLED` | `app.filters.sd_zone_confluence` | No S/D zone confluence |
| `PHASE_4_ENABLED` | `app.signals.signal_analytics` | No Phase 4 monitoring |

#### `_run_signal_pipeline` in sniper.py

This is a **thin dispatcher** that calls `sniper_pipeline._run_signal_pipeline`. The function signature in `sniper.py` is kept for backward compatibility so `scanner.py`'s import surface stays unchanged. FIX E (2026-03-26): removed stale `get_ticker_screener_metadata=` and `state=` kwargs that were causing dead-weight kwarg passing.

---

### `sniper_pipeline.py`

**Role:** The 13-gate signal pipeline. Takes a confirmed BOS+FVG signal and determines whether to arm it.

**Gates in order:**

| Gate # | Name | Action on fail |
|---|---|---|
| 1 | RVOL fetch | Sets `rvol = 1.0` on error |
| 2 | TIME gate | Drop if > 11:00 AM ET |
| 3 | RVOL floor | Drop if `rvol < RVOL_SIGNAL_GATE` |
| 4 | RVOL ceiling | Drop if `rvol >= RVOL_CEILING` |
| 5 | VWAP gate | Drop if price not above/below VWAP correctly |
| 6 | Dead zone | Drop if current time is in dead zone window |
| 7 | GEX pin zone | Drop if ticker is in a GEX pin zone |
| 8 | Cooldown | Drop if ticker is on cooldown for this direction |
| 9 | CFW6 confirmation | Drop if confirmation fails (skipped for INTRADAY/VWAP-reclaim) |
| 10 | MTF trend bias | Counter-trend dropped if `rvol < 1.8x` |
| 11a | SMC delta | Enrichment score (never blocks) |
| 11b | Liquidity sweep | Enrichment score (never blocks) |
| 11c | Order block retest | Enrichment score (never blocks) |
| 12 | SignalScorecard | Drop if score < 60 |
| 13 | Stop/targets | Drop if `compute_stop_and_targets()` returns `None` |
| 14 | `arm_ticker()` | Arms signal, fires Discord, persists to DB |

**Returns:**
- `True` — pipeline ran to completion, `arm_ticker()` called
- `False` — signal dropped at any gate

**`skip_cfw6_confirmation` parameter:** Set to `True` for `CFW6_INTRADAY` and VWAP-reclaim paths. These paths skip gate 9 and receive default `grade="A"`, `confidence_base=0.65`.

**MTF trend check (gate 10):** Resamples 1m bars to 15m to check trend alignment. If counter-trend and `rvol < 1.8x`, signal is dropped. If counter-trend but `rvol >= 1.8x`, signal proceeds with a warning log.

**Confidence derivation:**
```python
_confidence = min(0.85, max(0.60, _sc.score / 100.0))
```
Confidence is entirely derived from the scorecard score, clamped to [0.60, 0.85]. This replaced the old ad-hoc float arithmetic.

**Known issues:**
- `_resample_bars()` is duplicated in both `sniper.py` and `sniper_pipeline.py`. (**Issue #53**)

---

### `sniper_log.py`

**Role:** Writes a single structured `[PROPOSED-TRADE]` log line for every signal that reaches `arm_ticker()`, before `position_manager.open_position()` is called.

**Why it exists:** Fills a visibility gap — a signal can pass all scorecard gates but still be rejected by the risk manager (max positions, correlation, drawdown circuit-breaker). Without this log, there is no record of what was proposed.

**Grep key:** `[PROPOSED-TRADE]`

**Log format:**
```
[PROPOSED-TRADE] NVDA CFW6_OR BULL [OR] | Entry:$123.45 | Confidence:72.3% | Grade:A
```

**History:** Created 2026-03-26. `arm_signal.py` had been importing it via `from app.core.sniper_log import log_proposed_trade` but the file never existed, causing `ImportError` on every arm attempt and silently blocking all trade execution.

---

### `arm_signal.py`

**Role:** Final step of the signal pipeline. Called by `sniper_pipeline.py` after all gates pass. Performs 6 sequential steps:

1. **Hard-reject** — drop if `|entry - stop| < entry * 0.001` (tighter than 0.1%)
2. **`log_proposed_trade()`** — structured pre-arm log (sniper_log.py)
3. **Get screener metadata** — score/rvol/tier for Discord enrichment
4. **`position_manager.open_position()`** — risk-gated position open (returns `position_id`)
5. If `position_id == -1`: **return `None`** (risk rejected), no Discord alert
6. **`signal_tracker.record_trade_executed()`** — TRADED stage in signal_analytics
7. **`send_options_signal_alert()`** — Discord rich embed with all signal data
8. **Persist** — write to `armed_signals_persist` DB table
9. **`set_cooldown(ticker, direction, signal_type)`** — block re-entry for cooldown window
10. **Return `True`** (FIX G — explicit success return)

**Key design pattern:** Discord alert fires ONLY if `position_id > 0`. If the risk manager rejects the position (e.g. already at max positions), the signal is silently dropped with a log line. This prevents Discord spam for positions that were never actually opened.

**`vp_bias` parameter:** Passed to the Discord alert (FIX P3 — 2026-03-25). The fallback non-production-helpers path previously omitted this, causing VP bias data to be silently dropped from Discord alerts.

**All heavy imports are deferred** (`from app.risk.position_manager import ...` etc.) inside the function body. This prevents circular imports since `sniper_pipeline.py` imports `arm_signal.py` which would otherwise create import cycles with `position_manager`.

---

### `signal_scorecard.py`

**Role:** Replaces ad-hoc confidence float arithmetic with a structured 0–100 point scorecard. Every signal must score ≥ 60 to proceed to `arm_ticker()`.

#### Score breakdown (max 85 + ceiling penalty)

| Contributor | Max pts | Notes |
|---|---|---|
| Grade quality | 15 | A+=15, A=13, A-=11, B+=11, B=10. Intentionally flattened — B+ outperforms A+ at RVOL≥1.2x |
| IVR environment | 15 | IVR 20-50 = 15, IVR 50-80 = 10, no-data = 10 |
| GEX zone | 15 | neg_gex_zone = 15, pos = 8, no-data = 10 |
| MTF trend alignment | 15 | boost > 0.05 = 15, boost > 0 = 10, no-data = 8 |
| SMC enrichment | 10 | delta >= 0.05 = 10, > 0 = 7, else = 3 |
| VWAP gate pass | 5 | pass = 5, else = 0 (gate blocks before here) |
| Liquidity sweep | 5 | detected = 5, else = 0 |
| OB retest | 5 | detected = 5, else = 0 |
| SPY regime | 5 | STRONG aligned = 5, aligned = 3, else = 1 |
| **RVOL ceiling penalty** | -20 | RVOL >= 3.0x → deduct 20pts |

**Gate: score < 60 → signal dropped.** Gate was lowered from 72 to 60 after grid search validated B-grade setups at RVOL≥1.2x.

**Fallback scores (Phase 1.38c):** IVR/GEX/MTF fallbacks raised from 5→10/8→10/5→8 so missing enrichment data does not block valid signals. A signal with zero enrichment data scores: 10+10+8+8+7+5+0+0+1+0 = 49 + grade (10–15) = 59–64. Marginal at the 60-pt gate — needs at least one enrichment signal to reliably pass.

**FIX P2:** On any exception in `build_scorecard()`, returns `score = 59` (gate - 1) so a crash blocks the signal rather than passing through at exactly the gate boundary.

**Confidence-inversion warning:** A+ grade + RVOL < 1.2x triggers `_check_confidence_inversion()` warning. Grid search: A+ at low RVOL = 40% WR / -0.101 avg R.

---

### `health_server.py`

**Role:** Lightweight HTTP server providing the `/health` endpoint required by `railway.toml`'s `healthcheckPath`.

**Resolves Issue #51 (Batch 53):** Confirmed implemented. Issue #51 is CLOSED.

#### How it works

```python
start_health_server()   # binds PORT (default 8080) in daemon thread
health_heartbeat()      # called top of every scanner loop cycle
```

**Response logic:**
- `GET /health` → 200 `{"status": "ok", ...}` if heartbeat age ≤ threshold
- `GET /health` → 503 `{"status": "stalled", ...}` if heartbeat age > threshold
- `GET /` → same as `/health`
- All other paths → 404

**Staleness thresholds:**
- Market hours (09:30–16:00 ET weekdays): 5 min (`_MARKET_HOURS_STALE = 300s`)
- Off-hours: 10 min (`_OFF_HOURS_STALE = 600s`) — matches after-hours `time.sleep(600)` in scanner

**PORT binding:** Reads `PORT` env var (Railway sets this automatically). Falls back to 8080. Critical: Railway expects the app to bind the port it assigns via `PORT`. If the health server binds 8080 but Railway assigned 5000, health checks will never reach it. (**Issue #54**)

**Heartbeat seed:** `health_heartbeat()` is called once inside `start_health_server()` so `/health` returns 200 immediately at startup, even before the scanner loop's first cycle calls it.

**Access log suppression:** `log_message()` is overridden to do nothing, preventing Railway logs from being flooded with `GET /health HTTP/1.1 200` every 30 seconds.

---

### `logging_config.py`

**Role:** Centralised logging setup. Called once at startup in `__main__.py`.

**Key facts:**
- `_CONFIGURED = False` guard makes it idempotent — safe to call multiple times
- `LOG_LEVEL` env var overrides level (DEBUG/INFO/WARNING/ERROR). Default: INFO
- `LOG_FORMAT` env var overrides format. Default: `%(asctime)s [%(levelname)-5s] %(name)s: %(message)s`
- Single `StreamHandler(sys.stdout)` — Railway captures stdout for log viewer
- Clears any existing handlers before adding its own (prevents duplicate log lines from import-time `basicConfig()` calls)
- Quiets noisy third-party loggers to WARNING: `websocket`, `urllib3`, `httpx`, `requests`, `psycopg2`, `asyncio`

**Grep-friendly format example:**
```
09:31:42 [INFO ] app.core.scanner: [SCANNER] Cycle #1 | 30 tickers | 09:31:42 AM ET
```

---

### `thread_safe_state.py`

**Role:** Thread-safe singleton (`ThreadSafeState`) for all mutable global state in the system. Prevents race conditions from concurrent ticker processing.

**Singleton pattern:** Double-checked locking (`_instance` + `_lock`). Only one `ThreadSafeState` ever exists per process. `get_state()` always returns the same instance.

**State namespaces:**

| Namespace | Lock | Contents |
|---|---|---|
| `_armed_signals` | `_armed_lock` | Active armed positions: `{ticker: {position_id, direction, entry, stop, t1, t2, confidence, grade}}` |
| `_watching_signals` | `_watching_lock` | BOS-detected tickers waiting for FVG: `{ticker: {direction, breakout_idx, or_high, or_low, ...}}` |
| `_validator_stats` | `_validator_stats_lock` | Counts: tested/passed/filtered/boosted/penalized |
| `_validation_call_tracker` | `_validation_tracker_lock` | `{signal_id: call_count}` — prevents duplicate validation |
| `_last_dashboard_check` | `_monitoring_lock` | Timing for Phase 4 performance dashboard |
| `_last_alert_check` | `_monitoring_lock` | Timing for Phase 4 alert checks |

**Loaded flags:** `_armed_loaded` and `_watches_loaded` prevent double-loading from DB on concurrent startup. Both are reset on `clear_*()` calls at EOD.

**Convenience functions:** Module-level wrappers (`get_armed_signal()`, `set_armed_signal()`, etc.) delegate to the singleton for backward compatibility. New code should use `get_state()` directly.

---

### `armed_signal_store.py`

**Role:** DB persistence layer for armed signals. Owns the `armed_signals_persist` PostgreSQL table.

**Table schema:**
```sql
armed_signals_persist (
    ticker          TEXT PRIMARY KEY,
    position_id     INTEGER,
    direction       TEXT,
    entry_price     REAL,
    stop_price      REAL,
    t1              REAL,
    t2              REAL,
    confidence      REAL,
    grade           TEXT,
    signal_type     TEXT,
    validation_data TEXT,   -- JSON string
    saved_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

**Key functions:**

| Function | Purpose |
|---|---|
| `_ensure_armed_db()` | `CREATE TABLE IF NOT EXISTS` on first use |
| `_persist_armed_signal()` | `INSERT ... ON CONFLICT DO UPDATE` — upsert |
| `_remove_armed_from_db()` | DELETE single ticker |
| `_cleanup_stale_armed_signals()` | Remove armed signals whose `position_id` is no longer in open positions |
| `_load_armed_signals_from_db()` | Load today's armed signals after restart |
| `_maybe_load_armed_signals()` | Thread-safe once-per-session load (locked by `_armed_load_lock`) |
| `clear_armed_signals()` | Clear memory + `DELETE FROM armed_signals_persist` (EOD) |

**Postgres/SQLite dual support:** `get_placeholder(conn)` returns `%s` for Postgres and `?` for SQLite. Date filtering uses `AT TIME ZONE 'America/New_York'` for Postgres, raw `DATE(saved_at)` for SQLite.

**Stale cleanup logic:** `_cleanup_stale_armed_signals()` cross-references `position_manager.get_open_positions()` before loading. Any armed signal whose `position_id` is not in the open positions list is deleted. This prevents ghost armed signals after a position is closed during a crash-restart cycle.

---

### `watch_signal_store.py`

**Role:** DB persistence layer for watch signals. Owns the `watching_signals_persist` table.

**Table schema:**
```sql
watching_signals_persist (
    ticker          TEXT PRIMARY KEY,
    direction       TEXT,
    breakout_bar_dt TIMESTAMP,
    or_high         REAL,
    or_low          REAL,
    signal_type     TEXT,
    saved_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

**NOTE:** `breakout_idx` is NOT stored in the DB. It is stored as `NULL` in memory after DB load and resolved by scanning `bars_session` for the bar matching `breakout_bar_dt`. This resolution happens in `sniper.py`'s watch path.

**Stale cleanup:** `_cleanup_stale_watches()` deletes watches older than `MAX_WATCH_BARS * 5 = 60 minutes`. Called before every DB load. Prevents accumulation of watches from days prior.

**FIX I (2026-03-26):** Added `_watch_load_lock` to `_maybe_load_watches()`. Without the lock, two threads could both see `is_watches_loaded() == False` at startup and both execute `_load_watches_from_db()`, duplicating watch state.

**Extra public API functions** (`add_watching_signal`, `remove_watching_signal`, `get_watching_signals`, `is_watching`) appear to call `_state.add_watching_signal()` and `_state.is_watching()` — **these methods do not exist on `ThreadSafeState`**. This is a latent bug that would crash if these functions are called. (**Issue #53 — watch_signal_store public API mismatch**)

---

### `analytics_integration.py`

**Role:** Thin delegation wrapper over `SignalTracker` (`signal_analytics.py`). `scanner.py` uses this as its only analytics entry point.

**Public API:**

| Method | Delegates to |
|---|---|
| `process_signal()` | `signal_tracker.record_signal_generated()` |
| `validate_signal()` | `signal_tracker.record_validation_result()` |
| `arm_signal()` | `signal_tracker.record_signal_armed()` |
| `record_trade()` | `signal_tracker.record_trade_executed()` |
| `monitor_active_signals()` | No-op placeholder |
| `check_scheduled_tasks()` | Time-based: 9:30 reset + 16:05 EOD summary |
| `get_today_stats()` | `signal_tracker.get_funnel_stats()` |

**`db_connection` parameter:** Accepted for API compatibility but ignored. `SignalTracker` manages its own pooled connection internally.

**FIX #35:** `check_scheduled_tasks()` was using `datetime.now()` (UTC on Railway). Fixed to `datetime.now(ZoneInfo("America/New_York"))`. Without this fix, the 9:30 AM market open reset was firing at 2:30 PM ET.

**No-op mode:** If `signal_analytics.py` fails to import, `_TRACKER_AVAILABLE = False` and all methods return `None` or `-1`. The system continues running without analytics.

---

### `eod_reporter.py`

**Role:** Single-function EOD report orchestrator. Called by `scanner.py` once per day when market closes.

**`run_eod_report(session_date=None)` does:**
1. `get_session_status()` → trade P&L stats
2. `send_daily_summary()` → rich Discord embed (trades/wins/losses/WR/P&L)
3. `get_eod_report()` → top performers plain-text → `send_simple_message()`
4. `signal_tracker.get_discord_eod_summary()` → signal funnel block → Discord
5. `signal_tracker.get_daily_summary()` → full summary → `logger.info()`
6. `signal_tracker.clear_session_cache()` → clear for next day

**Can be run standalone:** `python -m app.core.eod_reporter [YYYY-MM-DD]` for manual report generation.

**FIX #36 (Mar 19 2026):** Removed redundant `print()` calls — `logger.info()` already routes to stdout which Railway captures.

---

## Issues Found This Batch

### ✅ Issue #51 CLOSED — `/health` endpoint confirmed implemented

`health_server.py` fully implements the `/health` endpoint using Python stdlib `http.server`. It binds `PORT` (Railway env var), serves GET /health with liveness-based 200/503, and seeds the heartbeat at startup. Issue #51 from Batch 53 is resolved.

---

### Issue #52 — LOW — Entry point ambiguity: `python -m app.core.scanner` vs `python -m app.core`

**Files:** `railway.toml`, `nixpacks.toml`, `app/core/__main__.py`

**Problem:** The Railway start command is `python -m app.core.scanner`. This invokes `scanner.py` directly as `__main__`, bypassing `app/core/__main__.py` entirely. `__main__.py`'s boot order guarantee (logging → health → scanner) only applies to `python -m app.core`.

When `python -m app.core.scanner` is used:
- `setup_logging()` is **never called** — logging relies on whatever `basicConfig()` was called by import-time code
- `start_health_server()` IS called at scanner.py module level (so health is fine)
- Log format may be inconsistent depending on import order

**Fix required:** Either:
- Change start command to `python -m app.core` (uses `__main__.py`'s guaranteed boot order), OR
- Add `setup_logging()` call at the top of `scanner.py` before any other import

**Status:** ⚠️ Open

---

### Issue #53 — LOW — `_resample_bars()` duplicated in `sniper.py` and `sniper_pipeline.py`

**Files:** `app/core/sniper.py` (line ~90), `app/core/sniper_pipeline.py` (line ~55)

**Problem:** Identical function body in two files. Any bug fix or improvement to resampling logic must be applied in two places.

**Fix required:** Move to `utils/bar_utils.py` or `app/data/bar_utils.py`, import from both files.

**Status:** ⚠️ Open

---

### Issue #54 — MEDIUM — `health_server.py` PORT binding may not match Railway-assigned PORT

**File:** `app/core/health_server.py`

**Problem:** `start_health_server()` reads `PORT` env var (default 8080). Railway's `healthcheckPath = "/health"` sends its probe to whatever port the app is listening on. Railway sets the `PORT` env var to the actual assigned port.

If `PORT` is correctly read, this is fine. The concern: `__main__.py` calls `start_health_server()` before importing scanner. But `scanner.py` also calls `start_health_server()` at module level. **Two calls to `start_health_server()`** → two `HTTPServer` instances bound to the same port → the second bind will raise `OSError: [Errno 98] Address already in use`.

**Current behavior:** The second `start_health_server()` call is in `scanner.py`'s module-level body. When `python -m app.core.scanner` is used (Railway start command), `__main__.py` is NOT run, so only scanner.py's call fires — one server, no conflict. But if `python -m app.core` is used, `__main__.py` calls it first, then scanner.py calls it again → port conflict crash.

**Fix required:** Add a `_STARTED = False` guard to `start_health_server()` so the second call is a no-op.

**Status:** ⚠️ Open — affects `python -m app.core` invocation path

---

### Issue #55 — MEDIUM — `watch_signal_store.py` public API calls nonexistent `ThreadSafeState` methods

**File:** `app/core/watch_signal_store.py` (bottom ~20 lines)

**Problem:** The public wrapper functions `add_watching_signal()`, `get_watching_signals()`, and `is_watching()` call `_state.add_watching_signal()`, `_state.get_watching_signals()`, and `_state.is_watching()` — but these methods **do not exist** on `ThreadSafeState` in `thread_safe_state.py`.

`ThreadSafeState` has:
- `set_watching_signal()` (not `add_watching_signal`)
- `get_all_watching_signals()` (not `get_watching_signals`)
- `ticker_is_watching()` (not `is_watching`)

**Impact:** Any code calling `add_watching_signal()`, `get_watching_signals()`, or `is_watching()` from `watch_signal_store.py` will raise `AttributeError`. These are currently not called by `sniper.py` (which uses `_state.set_watching_signal()` directly), so the bug is latent. But it would crash if these public functions are ever called.

**Fix required:** Rename the delegated calls to match the actual `ThreadSafeState` API:
- `_state.add_watching_signal()` → `_state.set_watching_signal()`
- `_state.get_watching_signals()` → `_state.get_all_watching_signals()`
- `_state.is_watching()` → `_state.ticker_is_watching()`

**Status:** ⚠️ Open

---

## Key Architecture Facts for `app/core/`

- **All state is in `ThreadSafeState`** — never use module-level dicts for mutable signal state. The singleton is the single source of truth.
- **Armed signals persist to DB** (`armed_signals_persist`) and **watch signals persist to DB** (`watching_signals_persist`). Both survive restarts.
- **DB restoration is automatic** — `_maybe_load_*()` is called at the top of `process_ticker()` on the first call after any restart. The `_armed_loaded` / `_watches_loaded` flags prevent double-loading.
- **The signal pipeline is one-way** — a signal can only move forward through gates. There is no retry or re-entry after a gate rejects it.
- **`arm_ticker()` is the last step** — it is the only function that opens a position, fires Discord, and sets cooldown. Nothing after it should do any of these.
- **The health server is the Railway lifeline** — if the scanner loop stalls for > 5 min during market hours, `/health` returns 503 and Railway will restart the container.
- **EOD reset is comprehensive** — armed signals, watching signals, BOS alert dedup, ORB classifications, funnel, PDH/PDL cache are all cleared at EOD.

---

## Next Batch

`app/data/` — data_manager, ws_feed, ws_quote_feed, candle_cache, db_connection, sql_safe, and all data infrastructure.
