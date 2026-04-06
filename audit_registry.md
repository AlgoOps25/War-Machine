# War-Machine Audit Registry
> **Purpose:** Complete system map of every source file in the repo. Track audit status, dependencies, and flag stale/unnecessary files.
> **Last Updated:** 2026-04-06
> **Source:** Verified against GitHub `AlgoOps25/War-Machine` main branch
> **Legend:** ⬜ Not Audited | 🟡 In Progress | ✅ Audited | 🗑️ Candidate for Removal | 📦 Data/Output (no audit needed)

---

## Audit Progress Summary

| Module | Files | Audited | Removal Candidates |
|--------|-------|---------|---------------------|
| app/ai | 2 | 0 | 0 |
| app/analytics | 10 | 0 | 2 |
| app/backtesting | 7 | 0 | 0 |
| app/core | 15 | **1** | 0 |
| app/data | 10 | 0 | 0 |
| app/filters | 12 | 0 | 0 |
| app/futures | 5 | 0 | 0 |
| app/indicators | 4 | 0 | 0 |
| app/ml | 7 | 0 | 0 |
| app/mtf | 7 | 0 | 0 |
| app/notifications | 3 | 0 | 0 |
| app/options | 7 | 0 | 0 |
| app/risk | 7 | 0 | 0 |
| app/screening | 8 | 0 | 0 |
| app/signals | 6 | 0 | 0 |
| app/validation | 11 | 0 | 1 |
| app (root) | 2 | 0 | 0 |
| utils | 5 | 1 | 0 |
| tests | 10 | 0 | 0 |
| migrations | 7 | 0 | 2 |
| scripts (all) | 64 | 0 | 15 |
| docs | 8 | 0 | 1 |
| root files | 18 | 0 | 4 |
| **TOTAL** | **235** | **2** | **25** |

> ⚠️ **Not tracked in source audit:** `backtests/results/` (output data), `backtests/analysis/` (output CSVs), `scripts/backtesting/campaign/*.db`, `.venv/`, `.pytest_cache/`, `__pycache__/`, `.env`, `*.log`, `*.db` (runtime), `*.pyc`

---

## 🕸️ Dependency Spiderweb

```
utils/config.py ─────────────────────────────────────────► ALL modules (confirmed: exports ~60 constants + 2 functions)
utils/bar_utils.py ──────────────────────────────────────► indicators/, signals/
utils/time_helpers.py ───────────────────────────────────► core/, screening/

app/data/data_manager.py ────────────────────────────────► core/scanner.py
app/data/db_connection.py ───────────────────────────────► data_manager, candle_cache, database
app/data/database.py ────────────────────────────────────► db_connection, analytics/
app/data/ws_feed.py ─────────────────────────────────────► core/scanner.py
app/data/ws_quote_feed.py ───────────────────────────────► core/scanner.py

app/indicators/ ─────────────────────────────────────────► signals/, filters/, validation/, mtf/
app/mtf/ ────────────────────────────────────────────────► validation/, core/scanner.py
app/signals/ ────────────────────────────────────────────► validation/, core/
app/validation/ ─────────────────────────────────────────► core/scanner.py
app/filters/ ────────────────────────────────────────────► validation/, signals/
app/screening/ ──────────────────────────────────────────► core/scanner.py
app/risk/ ───────────────────────────────────────────────► scanner.py, notifications/
app/notifications/ ──────────────────────────────────────► scanner.py
app/analytics/ ──────────────────────────────────────────► scanner.py, signals/
app/options/ ────────────────────────────────────────────► validation/greeks_precheck, data/
app/ml/ ─────────────────────────────────────────────────► signals/, indicators/
app/futures/ ────────────────────────────────────────────► data/, indicators/
app/backtesting/ ────────────────────────────────────────► signals/, validation/, data/
app/core/sniper_pipeline.py ─────────────────────────────► core/scanner.py, validation/
app/core/arm_signal.py ──────────────────────────────────► core/armed_signal_store.py
```

---

## ✅ AUDIT: utils/config.py
> **Audited:** 2026-04-03 | **Size:** 19.5KB | **Lines:** ~340

### Imports
```python
import os, sys, logging
from datetime import time as dtime
```
No internal imports. Pure stdlib. Self-contained.

### Exports (Complete Key Inventory)

#### API / Credentials
| Key | Value | Source |
|-----|-------|--------|
| `EODHD_API_KEY` | `os.getenv('EODHD_API_KEY', '')` | Env var |
| `DATABASE_URL` | `None` (runtime override) | Env var |
| `DB_PATH` | `os.getenv('DB_PATH', '/app/data/war_machine.db')` | Env var |
| `DBPATH` | alias for `DB_PATH` | Alias |
| `DISCORD_SIGNALS_WEBHOOK_URL` | `os.getenv(...)` | Env var |
| `DISCORD_NEWS_WEBHOOK_URL` | `os.getenv(...)` | Env var |
| `DISCORD_WATCHLIST_WEBHOOK_URL` | `os.getenv(...)` | Env var |

#### Account / Risk
| Key | Value | Notes |
|-----|-------|-------|
| `ACCOUNT_SIZE` | `5000` | USD |
| `MAX_SECTOR_EXPOSURE_PCT` | `30.0` | % |
| `MAX_POSITION_SIZE_PCT` | `5.0` | % |
| `MAX_DAILY_LOSS_PCT` | `2.0` | % |
| `MAX_INTRADAY_DRAWDOWN_PCT` | `5.0` | % |
| `MAX_OPEN_POSITIONS` | `5` | |
| `MAX_CONTRACTS` | `10` | |
| `MIN_RISK_REWARD_RATIO` | `1.5` | |
| `POSITION_RISK` | dict: A+→0.04, A→0.03, std→0.02, cons→0.01 | |
| `STOP_LOSS_MULTIPLIER` | `1.5` | |
| `TAKE_PROFIT_MULTIPLIER` | `3.0` | |
| `MAX_LOSS_PER_TRADE_PCT` | `2.0` | |
| `TRAILING_STOP_ACTIVATION` | `1.0` | |
| `T1_MULTIPLIER` | `2.0` | Grid search optimal |
| `T2_MULTIPLIER` | `3.5` | |

#### Opening Range
| Key | Value | Notes |
|-----|-------|-------|
| `MIN_OR_RANGE_PCT` | `0.030` | BULL/default |
| `MIN_OR_RANGE_PCT_BEAR` | `0.027` | BEAR regime |
| `MIN_OR_RANGE_PCT_STRONG_BEAR` | `0.025` | STRONG_BEAR regime |
| `OR_RANGE_MIN_PCT` | `0.2` | No practical effect (0 trades below 1%) |
| `OR_RANGE_MAX_PCT` | `99.0` | No cap — grid search optimal |
| `VIX_OR_THRESHOLDS` | list of (upper_bound, pct) tuples | VIX-scaled |
| `OR_START_TIME` | `09:30` | |
| `OR_END_TIME` | `09:45` | |
| `SECONDARY_RANGE_ENABLED` | `True` | Power Hour 10:00–10:30 |
| `SECONDARY_RANGE_START` | `10:00` | |
| `SECONDARY_RANGE_END` | `10:30` | |
| `SECONDARY_RANGE_MIN_BARS` | `20` | |
| `SECONDARY_RANGE_MIN_PCT` | `0.005` | |

#### Trading Hours
| Key | Value | Notes |
|-----|-------|-------|
| `MARKET_OPEN` | `09:30` | |
| `MARKET_CLOSE` | `16:00` | |
| `PRE_MARKET_START` | `04:00` | |
| `AFTER_HOURS_END` | `20:00` | |
| `TRADING_START` | `09:45` | After OR window |
| `TRADING_END` | `11:30` | Phase 1.38b — was 15:45 |
| `FORCE_CLOSE_TIME` | `11:35` | Phase 1.38b — was 15:50 |

#### Signal Thresholds
| Key | Value | Notes |
|-----|-------|-------|
| `ORB_BREAK_THRESHOLD` | `0.001` | BOS break % |
| `FVG_MIN_SIZE_PCT` | `0.0003` | Min FVG size |
| `FVG_SOFT_PCT` | `0.0015` | Soft FVG tolerance |
| `CONFIRMATION_TIMEOUT_BARS` | `5` | |
| `MIN_CONFIDENCE_OR` | `0.00` | ⚠️ Disabled — see issue below |
| `MIN_CONFIDENCE_INTRADAY` | `0.00` | ⚠️ Disabled |
| `CONFIDENCE_ABSOLUTE_FLOOR` | `0.55` | |
| `MIN_CONFIDENCE_BY_GRADE` | dict: A+→0.75 … C-→0.35 | |
| `CONFIDENCE_CAP_BY_GRADE` | dict: A+→0.88 … C-→0.40 | Phase 1.37 |

#### Screening / RVOL
| Key | Value | Notes |
|-----|-------|-------|
| `MIN_PRICE` | `5.0` | |
| `MAX_PRICE` | `500.0` | |
| `MIN_VOLUME` | `1_000_000` | |
| `MIN_RELATIVE_VOLUME` | `1.2` | Screener gate (was 2.0) |
| `RVOL_SIGNAL_GATE` | `1.2` | Signal gate |
| `RVOL_CEILING` | `3.0` | NEW Phase 1.38b |
| `MIN_ATR_MULTIPLIER` | `4.0` | |
| `MFI_MIN` | `60` | |
| `OBV_BARS_MIN` | `0` | |
| `VWAP_ZONE` | `'above_vwap'` | |
| `TF_CONFIRM` | `'1m'` | |
| `EXPLOSIVE_SCORE_THRESHOLD` | `80` | |
| `EXPLOSIVE_RVOL_THRESHOLD` | `4.0` | |

#### Options
| Key | Value | Notes |
|-----|-------|-------|
| `MIN_DTE` | `0` | |
| `MAX_DTE` | `7` | |
| `IDEAL_DTE` | `2` | Overridden by `get_ideal_dte()` |
| `MIN_OPTION_OI` | `100` | |
| `MIN_OPTION_VOLUME` | `50` | |
| `MAX_BID_ASK_SPREAD_PCT` | `0.10` | |
| `MAX_THETA_DECAY_PCT` | `0.05` | |
| `TARGET_DELTA_MIN` | `0.30` | P2-2 |
| `TARGET_DELTA_MAX` | `0.55` | P2-2 |
| `IDEAL_DELTA` | `0.40` | P2-2 |

#### Validation Feature Flags
| Key | Value |
|-----|-------|
| `VALIDATOR_MIN_SCORE` | `0.6` |
| `VALIDATOR_ENABLED` | `True` |
| `OPTIONS_FILTER_ENABLED` | `True` |
| `OPTIONS_FILTER_MODE` | `"HARD"` |
| `REGIME_FILTER_ENABLED` | `True` |
| `MIN_VIX_LEVEL` | `12.0` |
| `MAX_VIX_LEVEL` | `35.0` |
| `MTF_ENABLED` | `True` |
| `MTF_CONVERGENCE_BOOST` | `0.05` |
| `CANDLE_CONFIRMATION_ENABLED` | `True` |
| `HOURLY_GATE_ENABLED` | `True` |
| `CORRELATION_CHECK_ENABLED` | `True` |
| `BEAR_SIGNALS_ENABLED` | `False` | Phase 1.38b |
| `ENABLE_WEBSOCKET_FEED` | `True` |

#### Mode Flags
| Key | Value |
|-----|-------|
| `DEBUG_MODE` | `False` |
| `BACKTEST_MODE` | `False` |
| `PAPER_TRADING` | `False` |

#### Production Safety
| Key | Value |
|-----|-------|
| `MAX_DAILY_TRADES` | `15` |
| `COOLDOWN_SAME_DIRECTION` | `30` (minutes) |
| `COOLDOWN_OPPOSITE_DIRECTION` | `15` (minutes) |

#### Functions
| Function | Signature | Purpose |
|----------|-----------|---------|
| `get_vix_or_threshold(vix, spy_regime)` | `float → float` | VIX-scaled min OR range % with regime floor |
| `validate_required_env_vars()` | `→ None` | Startup env var check; `sys.exit(1)` on missing required |

### Required Env Vars (Hard — missing = `sys.exit(1)`)
```
EODHD_API_KEY
DATABASE_URL
DISCORD_SIGNALS_WEBHOOK_URL
DISCORD_PERFORMANCE_WEBHOOK_URL
DISCORD_EXIT_WEBHOOK_URL
```

### Optional Env Vars (Soft — missing = degraded operation)
```
DISCORD_REGIME_WEBHOOK_URL
DISCORD_WATCHLIST_WEBHOOK_URL
TRADIER_API_KEY
UNUSUAL_WHALES_API_KEY
```

### ⚠️ Issues Found

| # | Severity | Issue |
|---|----------|-------|
| 1 | 🟡 Medium | `OR_RANGE_MAX_PCT` and `OR_RANGE_MIN_PCT` are defined **twice** (lines ~68 and ~80). Second definition silently overwrites first. Harmless since both agree, but creates confusion. Remove the first pair. |
| 2 | 🟡 Medium | `MIN_CONFIDENCE_OR = 0.00` and `MIN_CONFIDENCE_INTRADAY = 0.00` are effectively disabled. Comment acknowledges confidence is inversely correlated with wins. Leaving at 0.00 means `CONFIDENCE_ABSOLUTE_FLOOR = 0.55` is the only acting floor — confirm this is intentional and not a forgotten re-enable. |
| 3 | 🟡 Medium | `DATABASE_URL = None` at module level, then `DB_PATH` is set. If `DATABASE_URL` is `None` and downstream code checks it without calling `validate_required_env_vars()` first, it will silently use SQLite instead of PostgreSQL. |
| 4 | 🟠 Low | `DBPATH` is an alias for `DB_PATH`. Two names for the same path used by different modules (`WatchlistFunnel`, `VolumeAnalyzer`). Should standardize to one name. |
| 5 | 🟠 Low | `BACKTEST_CHAMPION` dict is still present but the comment explicitly says "not a live filter" and the champion ticker list underperforms (-9.00 Total R). This is dead config — consider removing or moving to docs. |
| 6 | 🟠 Low | `DISCORD_NEWS_WEBHOOK_URL` is defined here but not listed in `_REQUIRED_VARS` or `_OPTIONAL_VARS`. It will never be validated at startup. |

---

## ✅ AUDIT: app/core/scanner.py
> **Audited:** 2026-04-06 | **Size:** ~19KB | **Lines:** ~530 | **Version:** v1.38e

### Role
Central orchestrator. The **only** entry point for the live scanning loop. Owns:
- Pre-market watchlist build cycle
- WebSocket feed subscription + backfill
- Intraday scan loop (calls `process_ticker` for each watchlist ticker)
- Circuit breaker / loss-streak halt
- EOD reset sequence
- Futures ORB daemon thread (opt-in via `FUTURES_ENABLED`)
- Railway health heartbeat (`health_heartbeat()`)

### Imports Map
| Import | Source | Notes |
|--------|--------|-------|
| `start_health_server`, `health_heartbeat` | `app.core.health_server` | **Module-level call** — runs before any other init |
| `os, time, threading, logging` | stdlib | |
| `ThreadPoolExecutor, FuturesTimeoutError` | `concurrent.futures` | Ticker watchdog |
| `datetime, dtime, ZoneInfo` | stdlib | All ET timezone-aware |
| `config`, `validate_required_env_vars` | `utils.config` | Global constants |
| `_db_operation_safe` | `utils.production_helpers` | Optional — graceful fallback if missing |
| `data_manager` | `app.data.data_manager` | Bar fetch + backfill |
| `start_ws_feed, subscribe_tickers, set_backfill_complete` | `app.data.ws_feed` | Equity WS |
| `start_quote_feed, subscribe_quote_tickers` | `app.data.ws_quote_feed` | Quote feed |
| `get_current_watchlist, get_watchlist_with_metadata, get_funnel, reset_funnel` | `app.screening.watchlist_funnel` | Funnel |
| `get_loss_streak, get_session_status, get_eod_report, risk_check_exits` | `app.risk.risk_manager` | Risk |
| `position_manager` | `app.risk.position_manager` | Open position tracking |
| `send_regime_discord` | `app.filters.market_regime_context` | Optional |
| `signal_tracker` | `app.signals.signal_analytics` | Optional legacy analytics |
| `AnalyticsIntegration` | `app.analytics` | Optional analytics |
| `validate_signal` | `app.validation` | Optional |
| `build_options_trade` | `app.options` | Optional |
| `process_ticker, clear_armed_signals, clear_watching_signals, clear_bos_alerts` | `app.core.sniper` | **Deferred import inside `start_scanner_loop()`** |
| `send_simple_message` | `app.notifications.discord_helpers` | Deferred |
| `learning_engine` | `app.ai.ai_learning` | Optional, deferred |
| `run_eod_report` | `app.core.eod_reporter` | Deferred (EOD only) |
| `start_futures_loop` | `app.futures` | Optional, deferred |
| `FuturesORBScanner`, `clear_bar_cache` | `app.futures.*` | Deferred (EOD only) |

### Key Module-Level Constants
| Constant | Value | Notes |
|----------|-------|-------|
| `REGIME_TICKERS` | `["SPY", "QQQ"]` | Always subscribed |
| `TICKER_TIMEOUT_SECONDS` | `45` | Hard watchdog per ticker |
| `_REDEPLOY_RETRIES` | `2` | Retries loading locked watchlist on hot redeploy |
| `_REDEPLOY_RETRY_WAIT` | `3` | Seconds between retries |
| `_FUTURES_ENABLED` | `os.getenv("FUTURES_ENABLED","false")` | Opt-in, evaluated once at import |
| `_FUTURES_SYMBOL` | `os.getenv("FUTURES_SYMBOL","MNQ")` | |
| `ANALYTICS_AVAILABLE` | `bool(DATABASE_URL)` | Set at import time |
| `EMERGENCY_FALLBACK` | 8-ticker list | Used when funnel fails entirely |

### Key Functions
| Function | Purpose |
|----------|---------|
| `_run_ticker_with_timeout(fn, ticker)` | Submits ticker to single-thread executor; hard 45s timeout |
| `_get_stale_tickers(tickers)` | Checks candle_cache for 24h staleness; returns list needing backfill |
| `_fire_and_forget(fn, label)` | Runs fn in daemon thread; logs success/failure |
| `is_premarket()` | `04:00–09:30 ET` |
| `is_market_hours()` | `09:30–16:00 ET`, skips weekends |
| `get_adaptive_scan_interval()` | Returns scan sleep (5s OR → 300s after-hours) |
| `calculate_optimal_watchlist_size()` | Returns 30–50 based on time of day |
| `_is_or_window()` | `09:30–09:40 ET` |
| `build_watchlist(force_refresh)` | Calls funnel; falls back to EMERGENCY_FALLBACK |
| `monitor_open_positions(session)` | Polls current price; calls `risk_check_exits` |
| `subscribe_and_prefetch_tickers(tickers)` | Subscribes WS + quote; fires backfill background thread |
| `start_scanner_loop()` | **Main entry point** — infinite loop with pre-market / market / EOD phases |

### Control Flow (start_scanner_loop)
```
validate_required_env_vars()
→ Import process_ticker (deferred — avoids circular at module level)
→ Startup banner + Discord message
→ Start WS feed thread (startup_watchlist = EMERGENCY_FALLBACK + REGIME_TICKERS)
→ Start quote feed thread
→ _get_stale_tickers() → fire backfill if needed
→ set_backfill_complete()
→ Hot redeploy? → load locked watchlist (retry ×2)
→ _FUTURES_ENABLED? → start_futures_loop() in daemon thread

LOOP:
  health_heartbeat()
  ├─ is_premarket()
  │    ├─ not built → get_watchlist_with_metadata(force_refresh=True) → subscribe
  │    ├─ built, should_update() → refresh watchlist
  │    └─ else → sleep 60s
  ├─ is_market_hours()
  │    ├─ loss streak ≥3? → circuit breaker: monitor only, sleep 60s
  │    ├─ else → get_current_watchlist() → trim to optimal_size
  │    │          → subscribe new tickers → monitor_open_positions()
  │    │          → for each ticker: _run_ticker_with_timeout(process_ticker, ticker)
  │    └─ sleep get_adaptive_scan_interval()
  └─ else (after-hours, once per calendar day)
       → run_eod_report()
       → AI optimize (if enabled)
       → data_manager.cleanup_old_bars()
       → candle_cache.cleanup_old_cache()
       → reset_funnel / clear_armed_signals / clear_watching_signals / clear_bos_alerts
       → futures EOD reset (if _FUTURES_ENABLED)
       → sleep 600s
```

### ⚠️ Issues Found

| # | ID | Severity | Issue | Status |
|---|----|----------|-------|--------|
| 1 | SC-7 | 🟡 Medium | `_ticker_executor = ThreadPoolExecutor(max_workers=1)` is created at **module level** (line ~73). This executor is never shut down — `executor.shutdown(wait=False)` is never called on `KeyboardInterrupt`. On Railway, this means SIGTERM leaves the pool thread dangling until the container is forcibly killed. Impact is low (Railway kills the container anyway) but is architecturally sloppy. Add `_ticker_executor.shutdown(wait=False)` in the `KeyboardInterrupt` block. |
| 2 | SC-8 | 🟡 Medium | `DISCORD_WEBHOOK_URL` is checked in the banner (`os.getenv('DISCORD_WEBHOOK_URL')`) but this key is **not** defined in `utils/config.py` and is not in `_REQUIRED_VARS`. The actual webhook sent by `send_simple_message` uses `DISCORD_SIGNALS_WEBHOOK_URL`. The `disc_msg` banner check will always show `✗ NOT CONFIGURED` even when Discord works fine. Fix: change to `os.getenv('DISCORD_SIGNALS_WEBHOOK_URL')`. |
| 3 | SC-9 | 🟡 Medium | Same issue for `REGIME_WEBHOOK_URL` banner check — config.py defines `DISCORD_REGIME_WEBHOOK_URL` (with `DISCORD_` prefix). The banner check uses the wrong key name, so the regime channel always shows `✗ Set REGIME_WEBHOOK_URL` even when configured. Fix: `os.getenv('DISCORD_REGIME_WEBHOOK_URL')`. |
| 4 | SC-10 | 🟡 Medium | `_get_stale_tickers` uses `candle_cache.get_bars(ticker, limit=1)` but the actual candle_cache API uses `get_bars(ticker, '1m', limit=1)` (requires timeframe arg). This will silently fail with a TypeError caught by the broad `except Exception as e`, causing **all tickers to be treated as stale on every startup** (full backfill every restart regardless of cache state). Requires cross-check against `candle_cache.py` signature during that file's audit. |
| 5 | SC-11 | 🟠 Low | `last_data_summary_time`, `data_update_counter`, `data_update_symbols` are module-level globals (lines ~156–158) that are **never read or written** anywhere in the file. These appear to be leftover scaffolding from a removed data-summary feature. Safe to delete. |
| 6 | SC-12 | 🟠 Low | `get_loss_streak` is imported from `app.risk.risk_manager` (line ~64) but is **never called** in this file. `_has_loss_streak` is computed via `daily_stats` dict and `_pm.has_loss_streak()` instead. Orphan import — safe to remove. |
| 7 | SC-13 | 🟠 Low | `build_watchlist()` function (line ~196) is defined but **never called** within this file. `start_scanner_loop()` calls `get_current_watchlist()` and `get_watchlist_with_metadata()` directly. `build_watchlist` is a public helper that external callers could use, but nothing currently does. Flag for removal or promotion to a documented public API. |
| 8 | SC-14 | 🟠 Low | `LEGACY_ANALYTICS_ENABLED` flag is set at module level but never read again. `signal_tracker` object is imported conditionally but then unused — no code in this file calls `signal_tracker.*`. The legacy analytics path was likely replaced by `AnalyticsIntegration`. Confirm in `app/signals/signal_analytics.py` audit, then remove both the import and the flag. |

### ✅ What's Clean
- `start_health_server()` at true module level (before any blocking init) is correct and intentional — ensures Railway `/health` responds within 30s window.
- All optional modules wrapped in `try/except ImportError` with correct boolean flags — zero crash risk on missing deps.
- `_FUTURES_ENABLED` evaluated once at import time; futures thread fully isolated in daemon — zero equity system coupling.
- `_fire_and_forget` correctly wraps backfill in daemon threads — non-blocking startup.
- Hot-redeploy path (locked watchlist retry) is clean and bounded (2 retries × 3s).
- Circuit breaker halts new scans while still monitoring open positions — correct.
- EOD reset sequence is comprehensive and ordered correctly (report → AI → cleanup → state reset → futures).
- All `.get()` fallbacks on dict access (SC-B/C/G from CORE-5) are correctly applied.
- `_db_operation_safe` wrapper uses correct `conn=None` pattern (SC-6/BUG-SC-6).
- `_REDEPLOY_RETRIES` / `_REDEPLOY_RETRY_WAIT` at module scope (SC-F from CORE-5).

### 🔧 Action Items (Next Steps)
| ID | Action | Priority |
|----|--------|----------|
| SC-8 | Fix `DISCORD_WEBHOOK_URL` → `DISCORD_SIGNALS_WEBHOOK_URL` in banner | High |
| SC-9 | Fix `REGIME_WEBHOOK_URL` → `DISCORD_REGIME_WEBHOOK_URL` in banner | High |
| SC-10 | Cross-verify `candle_cache.get_bars()` signature during `candle_cache.py` audit | High |
| SC-7 | Add `_ticker_executor.shutdown(wait=False)` to `KeyboardInterrupt` handler | Medium |
| SC-11 | Delete `data_update_counter`, `data_update_symbols`, `last_data_summary_time` (dead globals) | Low |
| SC-12 | Remove orphan import `get_loss_streak` | Low |
| SC-13 | Remove or document `build_watchlist()` as a dead internal function | Low |
| SC-14 | Confirm `signal_tracker` is unused here, then remove import + `LEGACY_ANALYTICS_ENABLED` | Low |

---

## ROOT FILES

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 1 | `.gitignore` | Config | ✅ Audited | Standard |
| 2 | `.github/workflows/ci.yml` | CI/CD | ⬜ Not Audited | GitHub Actions |
| 3 | `.railway_trigger` | Config | ⬜ Not Audited | Railway deploy trigger |
| 4 | `audit_registry.md` | Docs | ✅ Audited | This file |
| 5 | `backtest_apr03.log` | Log | 📦 Runtime output | Not tracked |
| 6 | `CODEBASE_DOCUMENTATION.md` | Docs | ⬜ Not Audited | May overlap docs/ |
| 7 | `CONTEXT.md` | Docs | ⬜ Not Audited | Project context |
| 8 | `CONTRIBUTING.md` | Docs | ⬜ Not Audited | |
| 9 | `LICENSE` | Legal | ✅ Audited | |
| 10 | `market_memory.db` | DB | 📦 Runtime DB | Not tracked |
| 11 | `nixpacks.toml` | Config | ⬜ Not Audited | Railway build config |
| 12 | `pytest.ini` | Config | ⬜ Not Audited | |
| 13 | `railway.toml` | Config | ⬜ Not Audited | |
| 14 | `README.md` | Docs | ⬜ Not Audited | |
| 15 | `REBUILD_PLAN.md` | Docs | 🗑️ Review | Likely stale planning doc |
| 16 | `requirements.txt` | Config | ⬜ Not Audited | Python deps |
| 17 | `run_migration_006.py` | Migration | 🗑️ Remove | One-off migration runner; 006 SQL is in migrations/ |
| 18 | `war_machine.db` | DB | 📦 Runtime DB | Not tracked |

---

## app/

### app/ (root)

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 19 | `app/__init__.py` | Init | ⬜ Not Audited | |
| 20 | `app/health_check.py` | Health | ⬜ Not Audited | Railway health endpoint |

### app/ai/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 21 | `app/ai/__init__.py` | Init | ⬜ Not Audited | |
| 22 | `app/ai/ai_learning.py` | AI | ⬜ Not Audited | |

### app/analytics/

> ⚠️ `explosive_mover_tracker.py` and `explosive_tracker.py` likely overlap — review for dedup.
> ⚠️ `ab_test.py` and `ab_test_framework.py` likely overlap — review for dedup.

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 23 | `app/analytics/__init__.py` | Init | ⬜ Not Audited | |
| 24 | `app/analytics/ab_test.py` | Analytics | 🗑️ Review | Possible duplicate of ab_test_framework |
| 25 | `app/analytics/ab_test_framework.py` | Analytics | ⬜ Not Audited | |
| 26 | `app/analytics/cooldown_tracker.py` | Analytics | ⬜ Not Audited | |
| 27 | `app/analytics/explosive_mover_tracker.py` | Analytics | 🗑️ Review | Possible duplicate of explosive_tracker |
| 28 | `app/analytics/explosive_tracker.py` | Analytics | ⬜ Not Audited | |
| 29 | `app/analytics/funnel_analytics.py` | Analytics | ⬜ Not Audited | **CORE** |
| 30 | `app/analytics/funnel_tracker.py` | Analytics | ⬜ Not Audited | |
| 31 | `app/analytics/grade_gate_tracker.py` | Analytics | ⬜ Not Audited | |
| 32 | `app/analytics/performance_monitor.py` | Analytics | ⬜ Not Audited | |

### app/backtesting/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 33 | `app/backtesting/__init__.py` | Init | ⬜ Not Audited | |
| 34 | `app/backtesting/backtest_engine.py` | Backtesting | ⬜ Not Audited | **CORE** |
| 35 | `app/backtesting/historical_trainer.py` | Backtesting | ⬜ Not Audited | |
| 36 | `app/backtesting/parameter_optimizer.py` | Backtesting | ⬜ Not Audited | |
| 37 | `app/backtesting/performance_metrics.py` | Backtesting | ⬜ Not Audited | |
| 38 | `app/backtesting/signal_replay.py` | Backtesting | ⬜ Not Audited | |
| 39 | `app/backtesting/walk_forward.py` | Backtesting | ⬜ Not Audited | |

### app/core/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 40 | `app/core/__init__.py` | Init | ⬜ Not Audited | |
| 41 | `app/core/__main__.py` | Entry Point | ⬜ Not Audited | App entry |
| 42 | `app/core/analytics_integration.py` | Core | ⬜ Not Audited | Bridges analytics → core |
| 43 | `app/core/arm_signal.py` | Core | ⬜ Not Audited | Signal arming logic |
| 44 | `app/core/armed_signal_store.py` | Core | ⬜ Not Audited | Armed signal state |
| 45 | `app/core/eod_reporter.py` | Core | ⬜ Not Audited | EOD summary |
| 46 | `app/core/health_server.py` | Core | ⬜ Not Audited | Health endpoint server |
| 47 | `app/core/logging_config.py` | Core | ⬜ Not Audited | Logging setup |
| 48 | `app/core/scanner.py` | **Core Orchestrator** | ✅ Audited | AUDIT CORE-6 — 8 issues (SC-7 to SC-14) |
| 49 | `app/core/signal_scorecard.py` | Core | ⬜ Not Audited | |
| 50 | `app/core/sniper.py` | Core | ⬜ Not Audited | **CORE** Sniper entry/execution — audit next |
| 51 | `app/core/sniper_log.py` | Core | ⬜ Not Audited | Sniper trade log |
| 52 | `app/core/sniper_pipeline.py` | Core | ⬜ Not Audited | **CORE** Sniper pipeline |
| 53 | `app/core/thread_safe_state.py` | Core | ⬜ Not Audited | Thread-safe shared state |
| 54 | `app/core/watch_signal_store.py` | Core | ⬜ Not Audited | Watch-mode signal store |

### app/data/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 55 | `app/data/__init__.py` | Init | ⬜ Not Audited | |
| 56 | `app/data/candle_cache.py` | Data | ⬜ Not Audited | ⚠️ Verify `get_bars()` signature (SC-10) |
| 57 | `app/data/data_manager.py` | Data | ⬜ Not Audited | **CORE** |
| 58 | `app/data/database.py` | Data | ⬜ Not Audited | |
| 59 | `app/data/db_connection.py` | Data | ⬜ Not Audited | |
| 60 | `app/data/eodhd_client.py` | Data | ⬜ Not Audited | |
| 61 | `app/data/news_fetcher.py` | Data | ⬜ Not Audited | |
| 62 | `app/data/option_chain_fetcher.py` | Data | ⬜ Not Audited | |
| 63 | `app/data/tradier_client.py` | Data | ⬜ Not Audited | |
| 64 | `app/data/ws_feed.py` | Data | ⬜ Not Audited | **CORE** |
| 65 | `app/data/ws_quote_feed.py` | Data | ⬜ Not Audited | |

### app/filters/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 66 | `app/filters/__init__.py` | Init | ⬜ Not Audited | |
| 67 | `app/filters/candle_confirmation.py` | Filter | ⬜ Not Audited | |
| 68 | `app/filters/correlation_filter.py` | Filter | ⬜ Not Audited | |
| 69 | `app/filters/crt_filter.py` | Filter | ⬜ Not Audited | |
| 70 | `app/filters/explosive_filter.py` | Filter | ⬜ Not Audited | |
| 71 | `app/filters/fvg_filter.py` | Filter | ⬜ Not Audited | |
| 72 | `app/filters/hourly_gate.py` | Filter | ⬜ Not Audited | |
| 73 | `app/filters/market_regime_context.py` | Filter | ⬜ Not Audited | **CORE** |
| 74 | `app/filters/market_regime_filter.py` | Filter | ⬜ Not Audited | |
| 75 | `app/filters/options_filter.py` | Filter | ⬜ Not Audited | |
| 76 | `app/filters/regime_trend_gate.py` | Filter | ⬜ Not Audited | |
| 77 | `app/filters/rvol_filter.py` | Filter | ⬜ Not Audited | |

### app/futures/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 78 | `app/futures/__init__.py` | Init | ⬜ Not Audited | |
| 79 | `app/futures/futures_orb_scanner.py` | Futures | ⬜ Not Audited | FIX-ORB-6 applied (2026-04-06) |
| 80 | `app/futures/futures_scanner_loop.py` | Futures | ⬜ Not Audited | |
| 81 | `app/futures/futures_signal_sender.py` | Futures | ⬜ Not Audited | |
| 82 | `app/futures/tradier_futures_feed.py` | Futures | ⬜ Not Audited | |

### app/indicators/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 83 | `app/indicators/__init__.py` | Init | ⬜ Not Audited | |
| 84 | `app/indicators/atr.py` | Indicator | ⬜ Not Audited | |
| 85 | `app/indicators/bos_detector.py` | Indicator | ⬜ Not Audited | **CORE** |
| 86 | `app/indicators/fvg_detector.py` | Indicator | ⬜ Not Audited | **CORE** |

### app/ml/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 87 | `app/ml/__init__.py` | Init | ⬜ Not Audited | |
| 88 | `app/ml/feature_engineering.py` | ML | ⬜ Not Audited | |
| 89 | `app/ml/ml_predictor.py` | ML | ⬜ Not Audited | |
| 90 | `app/ml/model_trainer.py` | ML | ⬜ Not Audited | |
| 91 | `app/ml/online_learner.py` | ML | ⬜ Not Audited | |
| 92 | `app/ml/regime_detector.py` | ML | ⬜ Not Audited | |
| 93 | `app/ml/signal_enhancer.py` | ML | ⬜ Not Audited | |

### app/mtf/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 94 | `app/mtf/__init__.py` | Init | ⬜ Not Audited | |
| 95 | `app/mtf/mtf_aggregator.py` | MTF | ⬜ Not Audited | |
| 96 | `app/mtf/mtf_analyzer.py` | MTF | ⬜ Not Audited | **CORE** |
| 97 | `app/mtf/mtf_confluence.py` | MTF | ⬜ Not Audited | |
| 98 | `app/mtf/mtf_scanner.py` | MTF | ⬜ Not Audited | |
| 99 | `app/mtf/mtf_signal.py` | MTF | ⬜ Not Audited | |
| 100 | `app/mtf/timeframe_manager.py` | MTF | ⬜ Not Audited | |

### app/notifications/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 101 | `app/notifications/__init__.py` | Init | ⬜ Not Audited | |
| 102 | `app/notifications/discord_helpers.py` | Notifications | ⬜ Not Audited | **CORE** |
| 103 | `app/notifications/signal_formatter.py` | Notifications | ⬜ Not Audited | |

### app/options/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 104 | `app/options/__init__.py` | Init | ⬜ Not Audited | |
| 105 | `app/options/greeks_calculator.py` | Options | ⬜ Not Audited | |
| 106 | `app/options/greeks_precheck.py` | Options | ⬜ Not Audited | |
| 107 | `app/options/option_chain_analyzer.py` | Options | ⬜ Not Audited | |
| 108 | `app/options/option_selector.py` | Options | ⬜ Not Audited | |
| 109 | `app/options/option_trade_builder.py` | Options | ⬜ Not Audited | |
| 110 | `app/options/options_intelligence.py` | Options | ⬜ Not Audited | |

### app/risk/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 111 | `app/risk/__init__.py` | Init | ⬜ Not Audited | |
| 112 | `app/risk/position_manager.py` | Risk | ⬜ Not Audited | **CORE** |
| 113 | `app/risk/position_sizer.py` | Risk | ⬜ Not Audited | |
| 114 | `app/risk/risk_manager.py` | Risk | ⬜ Not Audited | **CORE** |
| 115 | `app/risk/risk_rules.py` | Risk | ⬜ Not Audited | |
| 116 | `app/risk/stop_manager.py` | Risk | ⬜ Not Audited | |
| 117 | `app/risk/trade_executor.py` | Risk | ⬜ Not Audited | |

### app/screening/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 118 | `app/screening/__init__.py` | Init | ⬜ Not Audited | |
| 119 | `app/screening/gap_screener.py` | Screening | ⬜ Not Audited | |
| 120 | `app/screening/market_scanner.py` | Screening | ⬜ Not Audited | |
| 121 | `app/screening/momentum_screener.py` | Screening | ⬜ Not Audited | |
| 122 | `app/screening/pre_market_screener.py` | Screening | ⬜ Not Audited | |
| 123 | `app/screening/unusual_activity.py` | Screening | ⬜ Not Audited | |
| 124 | `app/screening/volume_analyzer.py` | Screening | ⬜ Not Audited | |
| 125 | `app/screening/watchlist_funnel.py` | Screening | ⬜ Not Audited | **CORE** |
| 126 | `app/screening/watchlist_manager.py` | Screening | ⬜ Not Audited | |

### app/signals/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 127 | `app/signals/__init__.py` | Init | ⬜ Not Audited | |
| 128 | `app/signals/or_signal.py` | Signal | ⬜ Not Audited | **CORE** |
| 129 | `app/signals/signal_analytics.py` | Signal | ⬜ Not Audited | Verify if `signal_tracker` is still used (SC-14) |
| 130 | `app/signals/signal_builder.py` | Signal | ⬜ Not Audited | |
| 131 | `app/signals/signal_confidence.py` | Signal | ⬜ Not Audited | |
| 132 | `app/signals/signal_grader.py` | Signal | ⬜ Not Audited | |

### app/validation/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 133 | `app/validation/__init__.py` | Init | ⬜ Not Audited | |
| 134 | `app/validation/candle_validator.py` | Validation | ⬜ Not Audited | |
| 135 | `app/validation/confirmation_engine.py` | Validation | ⬜ Not Audited | **CORE** |
| 136 | `app/validation/entry_validator.py` | Validation | ⬜ Not Audited | |
| 137 | `app/validation/fvg_validator.py` | Validation | ⬜ Not Audited | |
| 138 | `app/validation/market_context.py` | Validation | ⬜ Not Audited | |
| 139 | `app/validation/mtf_validator.py` | Validation | ⬜ Not Audited | |
| 140 | `app/validation/options_validator.py` | Validation | ⬜ Not Audited | |
| 141 | `app/validation/regime_validator.py` | Validation | ⬜ Not Audited | |
| 142 | `app/validation/signal_validator.py` | Validation | ⬜ Not Audited | |
| 143 | `app/validation/stale_signal_guard.py` | Validation | 🗑️ Review | Possible overlap with armed_signal_store |

---

## utils/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 144 | `utils/__init__.py` | Init | ⬜ Not Audited | |
| 145 | `utils/bar_utils.py` | Utils | ⬜ Not Audited | |
| 146 | `utils/config.py` | Config | ✅ Audited | AUDIT S17 — 6 issues logged |
| 147 | `utils/production_helpers.py` | Utils | ⬜ Not Audited | |
| 148 | `utils/time_helpers.py` | Utils | ⬜ Not Audited | |

---

## tests/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 149 | `tests/__init__.py` | Init | ⬜ Not Audited | |
| 150 | `tests/test_backtest.py` | Test | ⬜ Not Audited | |
| 151 | `tests/test_config.py` | Test | ⬜ Not Audited | |
| 152 | `tests/test_data.py` | Test | ⬜ Not Audited | |
| 153 | `tests/test_filters.py` | Test | ⬜ Not Audited | |
| 154 | `tests/test_indicators.py` | Test | ⬜ Not Audited | |
| 155 | `tests/test_integration.py` | Test | ⬜ Not Audited | |
| 156 | `tests/test_risk.py` | Test | ⬜ Not Audited | |
| 157 | `tests/test_scanner.py` | Test | ⬜ Not Audited | |
| 158 | `tests/test_signals.py` | Test | ⬜ Not Audited | |

---

## migrations/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 159 | `migrations/001_initial_schema.sql` | Migration | ⬜ Not Audited | |
| 160 | `migrations/002_add_signals.sql` | Migration | ⬜ Not Audited | |
| 161 | `migrations/003_add_performance.sql` | Migration | ⬜ Not Audited | |
| 162 | `migrations/004_add_analytics.sql` | Migration | ⬜ Not Audited | |
| 163 | `migrations/005_add_options.sql` | Migration | ⬜ Not Audited | |
| 164 | `migrations/006_add_futures.sql` | Migration | ⬜ Not Audited | |
| 165 | `migrations/run_migrations.py` | Migration | 🗑️ Remove | Superseded by run_migration_006.py at root |

---

## Audit Changelog

| Date | Commit | File | Audit ID | Summary |
|------|--------|------|----------|---------|
| 2026-04-03 | — | `utils/config.py` | S17 | Full audit — 6 issues, 340 lines |
| 2026-04-06 | AUDIT CORE-6 | `app/core/scanner.py` | CORE-6 | Full audit — 8 issues (SC-7 to SC-14), 530 lines |
