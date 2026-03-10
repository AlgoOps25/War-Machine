# WAR MACHINE — MASTER FILE REGISTRY
### Complete Role Analysis, Coverage Audit & Elite Optimization Plan
**Repository:** AlgoOps25/War-Machine  
**Compiled:** March 10, 2026  
**Purpose:** Single source of truth for every file in the repo — what it does, what it connects to, what is broken or missing, and the roadmap to make this system elite.

---

## ARCHITECTURE DOC STATUS CHECK

The original `war_machine_architecture_doc.txt` covered the core orchestration files thoroughly but was **missing the following directories entirely**:

| Missing Coverage | Files Not Documented |
|---|---|
| `app/core/analytics_integration.py` | Present in repo, not in arch doc |
| `app/core/error_recovery.py` | Present in repo, not in arch doc |
| `app/core/health_server.py` | Present in repo, not in arch doc |
| `app/core/sniper_mtf_trend_patch.py` | Present in repo, not in arch doc |
| `app/core/sniper_stubs.py` | Present in repo, not in arch doc |
| `app/core/__main__.py` | Present in repo, not in arch doc |
| All of `app/signals/` (7 files) | Entire module undocumented |
| All of `app/filters/` (4 files) | Entire module undocumented |
| All of `app/mtf/` (4 files + init) | Entire module undocumented |
| All of `app/indicators/` (2 files) | Entire module undocumented |
| All of `app/backtesting/` (5 files + init) | Entire module undocumented |
| All of `app/ml/` (10 files) | Entire module undocumented |
| `app/enhancements/signal_boosters.py` | Undocumented |
| `app/data/candle_cache.py` | Undocumented |
| `app/data/database.py` | Undocumented |
| `app/data/db_connection.py` | Undocumented |
| `app/data/sql_safe.py` | Undocumented |
| `app/data/unusual_options.py` | Undocumented |
| All of `app/analytics/` expansion (14 files) | Partially documented |
| `app/options/dte_historical_advisor.py` | Undocumented |
| `app/options/gex_engine.py` | Undocumented |
| `app/options/iv_tracker.py` | Undocumented |
| `app/options/options_data_manager.py` | Undocumented |
| `app/options/options_dte_selector.py` | Undocumented |
| `app/options/options_optimizer.py` | Undocumented |
| `app/validation/cfw6_confirmation.py` | Undocumented |
| `app/validation/entry_timing.py` | Undocumented |
| `app/validation/greeks_precheck.py` | Undocumented |
| `app/validation/hourly_gate.py` | Undocumented |
| `app/validation/volume_profile.py` | Undocumented |
| `app/risk/dynamic_thresholds.py` | Undocumented |
| `app/risk/trade_calculator.py` | Undocumented |
| `app/risk/vix_sizing.py` | Undocumented |
| `app/screening/dynamic_screener.py` | Undocumented |
| `app/screening/gap_analyzer.py` | Undocumented |
| `app/screening/news_catalyst.py` | Undocumented |
| `app/screening/premarket_scanner.py` | Undocumented |
| `app/screening/screener_integration.py` | Undocumented |
| `app/screening/sector_rotation.py` | Undocumented |
| `app/screening/volume_analyzer.py` | Undocumented |

---

## COMPLETE FILE REGISTRY

---

### SECTION 0 — REPOSITORY ROOT (INFRASTRUCTURE / DEPLOYMENT)

#### `main.py` ★ PROCESS ENTRYPOINT ★
- **Role:** Top-level process entrypoint, launched by Railway's `python main.py` start command. Calls `start_scanner_loop()` from `app/core/scanner.py`.
- **Connects to:** `app/core/scanner.py`
- **Data sources:** None directly
- **⚠ Flaw:** If this file crashes at import time (e.g., bad env var), the entire deployment dies silently with no health-check recovery possible.
- **Lean note:** File is appropriate. No bloat.

#### `railway.toml`
- **Role:** Railway deployment config. Defines build/start commands, health check path (`/health`), restart policy, and environment variable bindings.
- **Connects to:** `app/health_check.py` (via healthcheckPath), `main.py` (startCommand)
- **⚠ Flaw:** If the health check HTTP server fails to bind, Railway restarts the container even if the scanner itself is healthy.

#### `nixpacks.toml`
- **Role:** Tells Railway's Nixpacks builder which Python version + system packages to include. Pins Python 3.11+ and adds gcc/libpq for psycopg2 native compilation.
- **⚠ Flaw:** If Python version is not tightly pinned, a builder update can silently break `match/case` or `ZoneInfo` behavior.

#### `requirements.txt`
- **Role:** Python dependency manifest. Core packages: websockets, psycopg2-binary, requests, pyarrow, pandas, numpy.
- **⚠ Flaw:** No version pins on websockets. psycopg2-binary may conflict with nixpacks libpq-dev.

#### `audit_repo.py`
- **Role:** Standalone developer tool. Walks the repo tree, reads every `.py` file, produces structured audit reports in `audit_reports/`. Checks for missing `__init__.py`, circular imports, TODO/FIXME markers, missing docstrings, and unused imports.
- **Connects to:** `audit_reports/` directory (output)
- **⚠ Flaw:** Not run in CI — audit findings are never enforced automatically.

#### `.railway-trigger` / `.railway_trigger`
- **Role:** Empty dummy files committed to force Railway redeployment without code changes.
- **⚠ Flaw:** Redundant — two variants exist. Standardize to one.

#### `.gitignore`
- **Role:** Prevents committing `.env`, cache dirs, parquet files, ML models, etc.

#### `README.md`
- **Role:** Project overview, quick-start, and architecture summary for external readers.

#### `CONTRIBUTING.md`
- **Role:** Developer contribution guidelines.

#### `LICENSE`
- **Role:** Repository license.

---

### SECTION 1 — app/core/ (THE BRAIN — ORCHESTRATION LAYER)

#### `app/core/scanner.py` ★ PRIMARY ORCHESTRATOR ★  (~41KB)
- **Role:** Master control loop. Owns the entire session lifecycle: Pre-market → Market Hours → After Hours → EOD.
- **Flow:** Starts WS feeds as daemon threads → backfill daemons → enters `while True` loop gated by `is_premarket()` / `is_market_hours()` / after-hours EOD block.
- **Connects to:** `data_manager`, `ws_feed`, `ws_quote_feed`, `scanner_optimizer`, `watchlist_funnel`, `risk_manager`, `position_manager`, `sniper`, `validation`, `options`, `analytics`, `discord_helpers`, `ai_learning`
- **Data sources consumed:** EODHD REST (via data_manager), EODHD WebSocket (OHLCV + quotes), Tradier (options chain via options module)
- **⚠ Flaws:**
  1. `process_ticker()` called in both pre-market AND market hours — no deduplication guard at transition window.
  2. `analytics.monitor_active_signals()` has no rate limiting — can spike DB writes on fast scan intervals.
  3. `last_subscribed_watchlist` is case-sensitive string set — mixed case tickers cause duplicate subscriptions.
  4. EOD reset clears `loss_streak_alerted` but NOT the loss streak counter in `risk_manager`.
  5. No global timeout watchdog — hung `process_ticker()` stalls entire scan cycle silently.

#### `app/core/sniper.py` ★ CFW6 SIGNAL ENGINE ★  (~78KB — largest file)
- **Role:** Core signal detection and trade management per ticker. Implements CFW6 (Confirmation Framework Wave 6) logic.
- **Flow:** Fetches bars → runs EMA/ATR/VWAP/RSI/BOS/FVG/PDH/PDL indicators → regime filter → spread gate → cooldown check → evaluates 6 confirmations (BOS, FVG, VWAP, RVOL, MTF, RSI) → scores signal 0-100 → arms/fires/manages trades.
- **Connects to:** `data_manager`, `ws_feed`, `signal_generator_cooldown`, `position_manager`, `analytics`, `discord_helpers`, `validation`, `mtf` modules, `indicators` modules
- **Data sources consumed:** EODHD bars (REST + WS), bid/ask quotes from ws_quote_feed
- **⚠ Flaws:**
  1. `_armed_signals` and `_watching_signals` are plain dicts — NOT thread-safe (thread_safe_state.py exists but is NOT used here).
  2. 2000-line monolith — no unit tests for individual CFW6 confirmations.
  3. ATR stop uses last bar's ATR, not a rolling ATR — too tight after gaps.
  4. Re-fetches bars on every call — no in-memory cache between cycles.
  5. Discord alert fires BEFORE position_manager accept/reject — can send false signals.

#### `app/core/scanner_optimizer.py`
- **Role:** Provides three adaptive functions: `get_adaptive_scan_interval()` (sleep based on time-of-day), `should_scan_now()` (blocks during first 5 min of market open), `calculate_optimal_watchlist_size()` (scales watchlist cap by time + signal frequency).
- **Connects to:** `scanner.py`
- **⚠ Flaws:** 5-minute ORB window is hardcoded. Watchlist size has no feedback from current system load.

#### `app/core/signal_generator_cooldown.py`
- **Role:** Prevents re-generating same signal for same ticker within cooldown window (default 5 min per ticker/direction). Exposes `is_cooldown_active()`, `record_signal()`, `reset_cooldowns()`.
- **Connects to:** `sniper.py`
- **⚠ Flaws:** Not persisted — Railway restart mid-day resets all cooldowns. Cooldown is per-direction but not per signal type.

#### `app/core/thread_safe_state.py`
- **Role:** Provides `ThreadSafeDict` and `ThreadSafeSet` wrappers using `threading.RLock()`. Intended to replace bare dicts in `sniper.py`.
- **Connects to:** NOTHING (dead code — not imported by sniper.py)
- **⚠ Critical Flaw:** Built but never wired in. The safety wrapper is dead code.
- **Action Required:** Import and use in `sniper.py` for `_armed_signals` and `_watching_signals`.

#### `app/core/analytics_integration.py`
- **Role:** Bridge layer that connects the scanner loop to the analytics subsystem. Provides `AnalyticsIntegration` class with methods like `monitor_active_signals()`, `log_signal_event()`, `generate_eod_report()`. Abstracts analytics calls so scanner.py doesn't import analytics internals directly.
- **Connects to:** `app/analytics/` modules, `scanner.py`, `discord_helpers.py`
- **⚠ Note:** Rate limiting for `monitor_active_signals()` calls should be enforced here, not in scanner.py.

#### `app/core/error_recovery.py`  (~17KB)
- **Role:** Centralized error recovery and circuit-breaker logic. Handles exceptions from WS disconnects, API failures, DB outages. Provides retry logic with exponential backoff and recovery state machines.
- **Connects to:** `scanner.py`, `ws_feed.py`, `ws_quote_feed.py`, `data_manager.py`
- **⚠ Note:** Verify this is actively called in scanner's exception handlers — if not, it's near-dead code.

#### `app/core/health_server.py`
- **Role:** Lightweight HTTP server exposing `/health` endpoint for Railway's health check. Runs as a background thread. Returns 200 OK when the scanner loop is alive.
- **Connects to:** `railway.toml` (healthcheckPath = `/health`), `scanner.py` (started on launch)
- **Note:** This AND `app/health_check.py` both exist. Verify which one is actually started at runtime — one may be dead code.

#### `app/core/sniper_mtf_trend_patch.py`
- **Role:** Hot-patch module that overrides or supplements the MTF trend check inside `sniper.py`. Applied when the full `app/mtf/` integration was still being built — allows partial MTF alignment checks without refactoring the 2000-line sniper.
- **Connects to:** `sniper.py` (monkey-patch or import override), `app/mtf/`
- **⚠ Flaw:** Patch architecture adds complexity. Once `app/mtf/mtf_integration.py` is stable, this patch should be absorbed and removed.

#### `app/core/sniper_stubs.py`
- **Role:** Stub/mock replacements for sniper functions used during testing or when the full sniper is unavailable. Provides no-op versions of `process_ticker()` etc.
- **Connects to:** test environment
- **⚠ Note:** Ensure stubs are never accidentally imported in production. Guard with `if __name__ == '__main__'` or test-only import guards.

#### `app/core/__main__.py`
- **Role:** Allows `python -m app.core` execution. Thin wrapper that calls `scanner.start_scanner_loop()` — alternative entry point for local dev.
- **Connects to:** `scanner.py`

---

### SECTION 2 — app/data/ (DATA LAYER)

#### `app/data/data_manager.py` ★  (~44KB)
- **Role:** Central bar data CRUD layer. Fetches OHLCV bars from EODHD REST API, stores/retrieves from PostgreSQL and parquet cache. Manages startup_backfill and intraday_backfill. Provides `get_bars()`, `store_bars()`, `backfill_ticker()` interfaces.
- **Connects to:** `scanner.py`, `sniper.py`, `ws_feed.py`, `candle_cache.py`, `db_connection.py`
- **Data sources consumed:** EODHD REST API (historical + intraday bars)
- **⚠ Flaws:**
  1. REST fallback on WS miss means stale bars can power live signals.
  2. No per-ticker request throttle — concurrent backfills can hit EODHD rate limits.
  3. Parquet cache invalidation logic may not account for trading halts or corporate actions.

#### `app/data/ws_feed.py`  (~23KB)
- **Role:** EODHD WebSocket OHLCV feed. Connects to EODHD WS endpoint, subscribes to tickers, and writes incoming bars to an in-memory dict consumed by `sniper.py`. Handles reconnection and heartbeat.
- **Connects to:** `scanner.py`, `data_manager.py`, `sniper.py`
- **Data sources consumed:** EODHD WebSocket (real-time OHLCV bars)
- **⚠ Flaw:** No versioned websockets pin — breaking change in EODHD WS protocol could silently break this.

#### `app/data/ws_quote_feed.py`  (~16KB)
- **Role:** EODHD WebSocket bid/ask quote feed. Provides real-time spread data used by `is_spread_acceptable()` in sniper.py. Separate from OHLCV feed to allow independent reconnection.
- **Connects to:** `scanner.py`, `sniper.py`
- **Data sources consumed:** EODHD WebSocket (real-time quotes/bid-ask)

#### `app/data/candle_cache.py`  (~18KB)
- **Role:** Parquet-based on-disk candle cache. Persists OHLCV bars from EODHD to `cache/` directory. Provides fast local reads to avoid repeat API calls for the same data. Handles cache expiration and stale detection.
- **Connects to:** `data_manager.py`
- **Data sources:** Local filesystem (parquet files)
- **Lean note:** Critical for reducing EODHD API call volume — ensure all REST fetches route through here first.

#### `app/data/database.py`
- **Role:** Thin DB utility wrapper — likely holds connection string constants or simple helper functions. Very small (1KB).
- **Connects to:** `db_connection.py`
- **⚠ Note:** Possibly redundant alongside `db_connection.py`. Audit if both are needed.

#### `app/data/db_connection.py`  (~19KB)
- **Role:** PostgreSQL connection pool manager. Handles connection lifecycle, retry on failure, and exposes `get_conn()` / `release_conn()` pattern. Used by analytics, position_manager, signal logging.
- **Connects to:** `analytics` modules, `position_manager.py`, `risk_manager.py`, `data_manager.py`
- **⚠ Flaw:** If pool exhausts under rapid DB writes, scanner cycle can deadlock waiting for a connection.

#### `app/data/sql_safe.py`  (~13KB)
- **Role:** SQL safety layer — parameterized query builder, SQL injection protection wrappers, and schema validation helpers for all DB writes in the system.
- **Connects to:** All modules that write to PostgreSQL
- **Lean note:** Good hygiene. Ensure ALL DB writes go through this layer, not bare psycopg2 execute calls.

#### `app/data/unusual_options.py`  (~15KB)
- **Role:** Fetches and parses unusual options activity data from the Unusual Whales API. Feeds options flow signals into the screening and validation pipeline. Tracks sweeps, blocks, and large order flow.
- **Connects to:** `watchlist_funnel.py`, `options_intelligence.py`, `signal_boosters.py`
- **Data sources consumed:** Unusual Whales API (unusual options flow)
- **⚠ Note:** This is a high-alpha data source — verify it's actively integrated into watchlist scoring and signal boosting, not just fetched and discarded.

---

### SECTION 3 — app/core continued — app/health_check.py

#### `app/health_check.py`  (~13KB)
- **Role:** HTTP health check server (alternative/original version). Exposes `/health` endpoint. May overlap with `app/core/health_server.py`.
- **⚠ Action Required:** Determine which health server is actually launched at startup (check main.py and scanner.py imports). Consolidate into one file and delete the other.

---

### SECTION 4 — app/screening/ (TICKER PIPELINE — PRE-MARKET FUNNEL)

#### `app/screening/watchlist_funnel.py`  (~16KB)
- **Role:** ★ Tiered ticker selection engine. Aggregates results from all screening modules and scores tickers into a final ranked watchlist. Called by scanner.py during pre-market to build/refresh the day's watchlist.
- **Connects to:** `premarket_scanner.py`, `dynamic_screener.py`, `gap_analyzer.py`, `news_catalyst.py`, `volume_analyzer.py`, `sector_rotation.py`, `unusual_options.py`
- **Data sources consumed:** EODHD REST (fundamentals, historical), Unusual Whales, news feeds
- **⚠ Note:** This is the gateway — poor funnel quality upstream means poor signal quality downstream.

#### `app/screening/premarket_scanner.py`  (~26KB)
- **Role:** Core pre-market candidate scan. Runs during 4:00–9:30 AM window. Scans for price action, gap size, relative volume, and momentum characteristics using EODHD pre-market data.
- **Connects to:** `watchlist_funnel.py`, `data_manager.py`, `gap_analyzer.py`
- **Data sources consumed:** EODHD REST (pre-market OHLCV, EOD data)

#### `app/screening/dynamic_screener.py`  (~26KB)
- **Role:** Real-time intraday screener that re-scores and re-ranks watchlist candidates as market conditions evolve during RTH. Removes tickers that no longer qualify and surfaces new breakout candidates.
- **Connects to:** `watchlist_funnel.py`, `scanner.py`, `data_manager.py`
- **Data sources consumed:** EODHD WebSocket (real-time bars)

#### `app/screening/gap_analyzer.py`  (~8KB)
- **Role:** Analyzes overnight gap size, direction, and historical gap-fill rates for each candidate. Tags tickers as gap-up, gap-down, or inside-day. Feeds into watchlist scoring.
- **Connects to:** `watchlist_funnel.py`, `premarket_scanner.py`
- **Data sources consumed:** EODHD REST (previous day close vs. pre-market open)

#### `app/screening/news_catalyst.py`  (~14KB)
- **Role:** Pulls and scores news catalysts for watchlist candidates. Categorizes by catalyst type (earnings, FDA, M&A, macro). High-catalyst tickers get scoring boosts in the funnel.
- **Connects to:** `watchlist_funnel.py`
- **Data sources consumed:** EODHD news API
- **Enhancement opportunity:** Add sentiment scoring to news headlines to weight catalyst quality.

#### `app/screening/volume_analyzer.py`  (~14KB)
- **Role:** Relative volume (RVOL) calculator and unusual volume pattern detector. Computes RVOL vs. 20-day average, flags volume spikes, and scores tickers by volume rank for funnel weighting.
- **Connects to:** `watchlist_funnel.py`, `dynamic_screener.py`
- **Data sources consumed:** EODHD REST (volume history)

#### `app/screening/sector_rotation.py`  (~9KB)
- **Role:** Tracks sector-level money flow to prioritize tickers in hot sectors and deprioritize those in lagging sectors. Uses SPY/QQQ sector ETF momentum as a relative strength baseline.
- **Connects to:** `watchlist_funnel.py`
- **Data sources consumed:** EODHD REST (sector ETF data)

#### `app/screening/screener_integration.py`  (~3KB)
- **Role:** Thin integration glue that wires all screening sub-modules into `watchlist_funnel.py`. Likely contains `build_watchlist()` or similar top-level function.
- **Connects to:** All `app/screening/` modules, `watchlist_funnel.py`

---

### SECTION 5 — app/signals/ (SIGNAL DETECTION LIBRARY)

#### `app/signals/breakout_detector.py`  (~32KB — largest in signals)
- **Role:** Core breakout pattern detection library. Detects range breakouts, consolidation breaks, PDH/PDL breaks, and multi-day breakouts. Used by sniper.py as the primary pattern recognition engine.
- **Connects to:** `sniper.py`, `signal_generator.py`
- **Data sources consumed:** Bar data from data_manager/ws_feed
- **⚠ Note:** At 32KB this may have significant overlap with sniper.py's internal indicator logic — audit for deduplication.

#### `app/signals/opening_range.py`  (~24KB)
- **Role:** ORB (Opening Range Breakout) detector. Calculates the high/low of the opening range (configurable: 5/15/30 min), monitors for breakouts above/below, and generates ORB signals with volume confirmation.
- **Connects to:** `sniper.py`, `breakout_detector.py`
- **Data sources consumed:** EODHD bars (first N minutes of RTH)
- **⚠ Note:** scanner_optimizer.py hardcodes 5-min ORB — this module may support wider windows but the optimizer gates it. Align the two.

#### `app/signals/signal_analytics.py`  (~24KB)
- **Role:** Post-signal analytics and pattern analysis. Tracks signal outcomes, computes win rates per signal type/ticker/time-of-day, and produces signal quality metrics for AI learning.
- **Connects to:** `analytics/` modules, `ai_learning.py`, `ml_signal_scorer.py`
- **Data sources consumed:** PostgreSQL (historical signal logs)

#### `app/signals/mtf_validator.py`  (~12KB)
- **Role:** Multi-timeframe signal validation module within the signals layer. Cross-validates a signal found on the base timeframe against higher-timeframe (15m, 1H) trend alignment.
- **Connects to:** `sniper.py`, `app/mtf/` modules
- **Note:** Relationship with `app/mtf/mtf_integration.py` should be clarified — potential overlap.

#### `app/signals/signal_generator.py`  (~9KB)
- **Role:** Structured signal object factory. Builds standardized signal dicts/dataclasses from raw indicator conditions. Ensures consistent signal schema across all detection paths.
- **Connects to:** `sniper.py`, `breakout_detector.py`, `analytics` modules

#### `app/signals/signal_processor.py`  (~3KB)
- **Role:** Signal post-processing pipeline. Takes raw signals from `signal_generator.py`, applies deduplication, formats for Discord/analytics/position_manager consumption.
- **Connects to:** `signal_generator.py`, `discord_helpers.py`, `position_manager.py`

#### `app/signals/signal_validator.py`  (~1KB)
- **Role:** Minimal wrapper or interface stub for signal validation. Very small — likely a pass-through to `app/validation/`.
- **⚠ Note:** At 1KB this may be a stub or dead code. Verify if actively used or if `app/validation/__init__.py` supersedes it.

#### `app/signals/bos_fvg_detector.py`  (~1KB)
- **Role:** Minimal BOS (Break of Structure) and FVG (Fair Value Gap) detection stub. Very small — likely delegates to `app/mtf/bos_fvg_engine.py`.
- **⚠ Note:** At 1KB, verify if this is actively used or if `app/mtf/bos_fvg_engine.py` is the real implementation. May be redundant.

---

### SECTION 6 — app/mtf/ (MULTI-TIMEFRAME ENGINE)

#### `app/mtf/bos_fvg_engine.py`  (~21KB)
- **Role:** ★ Core BOS + FVG pattern detection engine with full multi-timeframe support. Detects Break of Structure and Fair Value Gaps across 1m, 5m, 15m, 1H timeframes. The authoritative implementation — `app/signals/bos_fvg_detector.py` is likely a stub pointing here.
- **Connects to:** `sniper.py`, `sniper_mtf_trend_patch.py`, `mtf_integration.py`
- **Data sources consumed:** EODHD bars (multiple timeframes via data_manager)

#### `app/mtf/mtf_integration.py`  (~18KB)
- **Role:** Top-level MTF integration module. Orchestrates cross-timeframe analysis, calls `bos_fvg_engine.py` and `mtf_compression.py`, and returns a unified MTF bias object to sniper.py.
- **Connects to:** `sniper.py`, `bos_fvg_engine.py`, `mtf_compression.py`, `mtf_fvg_priority.py`

#### `app/mtf/mtf_fvg_priority.py`  (~15KB)
- **Role:** FVG prioritization logic. When multiple FVGs are detected across timeframes, this module ranks and selects the highest-priority FVG to use as the trade entry reference.
- **Connects to:** `mtf_integration.py`, `bos_fvg_engine.py`

#### `app/mtf/mtf_compression.py`  (~8KB)
- **Role:** Compresses 1-minute EODHD bars into higher timeframes (5m, 15m, 1H) without making additional API calls. Allows MTF analysis from a single base-timeframe WS feed.
- **Connects to:** `mtf_integration.py`, `bos_fvg_engine.py`
- **Data sources consumed:** 1m bars from `ws_feed.py`
- **Lean note:** ★ This is critical for minimizing EODHD API usage. All MTF analysis should flow through here rather than making separate bar requests for each timeframe.

---

### SECTION 7 — app/indicators/ (RAW INDICATOR LIBRARY)

#### `app/indicators/vwap_calculator.py`  (~16KB)
- **Role:** VWAP (Volume-Weighted Average Price) calculator. Computes intraday VWAP, VWAP bands, and VWAP deviation from session open. Used by sniper.py's C3 confirmation check.
- **Connects to:** `sniper.py`, `validation.py`
- **Data sources consumed:** Intraday bars from ws_feed

#### `app/indicators/volume_profile.py`  (~20KB)
- **Role:** Volume profile and POC (Point of Control) calculator. Builds intraday and historical volume profiles to identify key support/resistance levels based on traded volume clusters.
- **Connects to:** `sniper.py`, `validation/volume_profile.py`
- **Note:** There is also a `app/validation/volume_profile.py` — ensure these serve distinct roles (calculation vs. validation gate).

---

### SECTION 8 — app/filters/ (SESSION & TIMING GATES)

#### `app/filters/early_session_disqualifier.py`  (~3KB)
- **Role:** Disqualifies signals generated during the first N minutes of market open (configurable chaos window). Prevents low-quality opening prints from triggering entries.
- **Connects to:** `sniper.py`, `scanner_optimizer.py`
- **Note:** Works alongside `should_scan_now()` in scanner_optimizer — ensure they use the same window config to avoid conflict.

#### `app/filters/entry_timing_optimizer.py`  (~5KB)
- **Role:** Scores entry timing quality based on time-of-day, distance from power hours (9:45-11:30, 13:30-15:30), and historical win-rate by hour. Adjusts entry confirmation thresholds dynamically.
- **Connects to:** `sniper.py`, `validation/__init__.py`

#### `app/filters/options_dte_filter.py`  (~5KB)
- **Role:** Filters options trades based on DTE (Days to Expiration) suitability given current VIX and signal confidence. Rejects contracts with unfavorable theta decay risk.
- **Connects to:** `options/__init__.py`, `options_dte_selector.py`, `greeks_precheck.py`

#### `app/filters/correlation.py`  (~8KB)
- **Role:** Cross-ticker correlation filter. Prevents holding multiple highly-correlated positions simultaneously (e.g., NVDA + AMD + SMCI all long). Reduces portfolio-level correlated drawdown risk.
- **Connects to:** `position_manager.py`, `scanner.py`

---

### SECTION 9 — app/validation/ (SIGNAL QUALITY GATE)

#### `app/validation/validation.py`  (~61KB — largest validation file)
- **Role:** ★ Master signal validation pipeline. The final quality gate before any trade is greenlit. Runs the full suite of validation checks: market regime, volatility regime, spread, RVOL, time-of-day, MTF alignment, options pre-check, Greeks pre-check, volume profile.
- **Connects to:** `scanner.py`, `sniper.py`, `options/__init__.py`, all sub-validation modules
- **⚠ Flaw:** 61KB monolith. Difficult to test individual validation stages in isolation.

#### `app/validation/__init__.py`  (~15KB)
- **Role:** Package initializer that exposes `validate_signal()` as the single entry point. Orchestrates calls to all validation sub-modules and returns a composite pass/fail + confidence score.
- **Connects to:** `validation.py`, `cfw6_confirmation.py`, `greeks_precheck.py`, `entry_timing.py`, `hourly_gate.py`, `volume_profile.py`

#### `app/validation/cfw6_confirmation.py`  (~11KB)
- **Role:** External re-validation of CFW6 confirmations. After sniper.py scores a signal internally, this module re-runs the 6 confirmation checks as an independent gate — prevents sniper bugs from letting bad signals through.
- **Connects to:** `validation/__init__.py`, `sniper.py`
- **Note:** This is a critical redundancy layer. Keep it.

#### `app/validation/greeks_precheck.py`  (~20KB)
- **Role:** Options Greeks pre-validation gate. Before building an options trade, checks that the target contract has acceptable Delta, Gamma, Theta, Vega, and IV Rank. Rejects contracts with poor risk/reward Greeks profile.
- **Connects to:** `validation/__init__.py`, `options/__init__.py`, `options_intelligence.py`
- **Data sources consumed:** Tradier (options chain Greeks)

#### `app/validation/entry_timing.py`  (~9KB)
- **Role:** Entry timing validation gate. Checks entry against power hours, avoids Fed/FOMC announcement windows, and rejects entries within the last 30 minutes of market close.
- **Connects to:** `validation/__init__.py`

#### `app/validation/hourly_gate.py`  (~6KB)
- **Role:** Per-hour signal rate limiter. Prevents more than N signals per hour across all tickers to avoid overtrading and protect daily PnL limits.
- **Connects to:** `validation/__init__.py`, `risk_manager.py`

#### `app/validation/volume_profile.py`  (~7KB)
- **Role:** Volume profile validation check. Verifies that a signal entry price is not at a high-volume node (price magnet) that would reduce momentum potential. Favors entries at low-volume nodes near POC boundaries.
- **Connects to:** `validation/__init__.py`, `indicators/volume_profile.py`

---

### SECTION 10 — app/options/ (OPTIONS INTELLIGENCE)

#### `app/options/__init__.py`  (~30KB)
- **Role:** ★ Top-level options module. Exposes `build_options_trade()` called by scanner.py. Orchestrates contract selection, strike/DTE logic, Greeks validation, and order construction. Integrates all sub-modules in this package.
- **Connects to:** `scanner.py`, `options_intelligence.py`, `options_dte_selector.py`, `options_optimizer.py`, `greeks_precheck.py`, `gex_engine.py`, `iv_tracker.py`
- **Data sources consumed:** Tradier (options chains), EODHD (underlying price)

#### `app/options/options_intelligence.py`  (~53KB — 2nd largest file)
- **Role:** Deep options analysis engine. Scores options contracts by liquidity, spread tightness, open interest, volume, and flow alignment. Integrates with unusual_options.py dark pool/flow data to bias contract selection.
- **Connects to:** `options/__init__.py`, `unusual_options.py`, `iv_tracker.py`, `gex_engine.py`
- **Data sources consumed:** Tradier, Unusual Whales

#### `app/options/options_optimizer.py`  (~25KB)
- **Role:** Contract parameter optimizer. Given a signal's target price, direction, and confidence, determines the optimal strike, expiration, and contract type (calls/puts/spreads) to maximize expected value.
- **Connects to:** `options/__init__.py`, `options_dte_selector.py`, `dte_historical_advisor.py`

#### `app/options/options_dte_selector.py`  (~15KB)
- **Role:** DTE (Days to Expiration) selection logic. Balances theta risk vs. directional leverage based on signal confidence, VIX level, and time-of-day. Returns optimal DTE range for contract selection.
- **Connects to:** `options_optimizer.py`, `options/__init__.py`, `dte_historical_advisor.py`

#### `app/options/dte_historical_advisor.py`  (~5KB)
- **Role:** Historical win-rate data by DTE. Provides lookup of which DTE ranges historically performed best for similar setups, feeding into DTE selection logic.
- **Connects to:** `options_dte_selector.py`
- **Data sources consumed:** PostgreSQL (historical trade outcomes by DTE)

#### `app/options/gex_engine.py`  (~10KB)
- **Role:** GEX (Gamma Exposure) calculator. Computes market-maker gamma exposure at key strike levels. High positive GEX acts as a price magnet/pinning force; negative GEX creates explosive move potential. Used to bias directional conviction.
- **Connects to:** `options_intelligence.py`, `validation/__init__.py`
- **Data sources consumed:** Tradier (options chain open interest by strike)

#### `app/options/iv_tracker.py`  (~5KB)
- **Role:** Implied Volatility rank and percentile tracker. Tracks rolling IV for each ticker, computes IV Rank (current IV vs. 52-week range) and IV Percentile. Used by greeks_precheck and options_optimizer to determine if IV is cheap or expensive.
- **Connects to:** `options_intelligence.py`, `greeks_precheck.py`
- **Data sources consumed:** Tradier (IV from options chain)

#### `app/options/options_data_manager.py`  (~11KB)
- **Role:** Options-specific data persistence layer. Caches options chains, Greeks snapshots, and IV history to PostgreSQL. Prevents redundant Tradier API calls within the same session.
- **Connects to:** All `app/options/` modules, `db_connection.py`
- **Lean note:** ★ Ensure all Tradier calls go through this cache layer to minimize API usage.

---

### SECTION 11 — app/risk/ (RISK MANAGEMENT)

#### `app/risk/risk_manager.py`  (~14KB)
- **Role:** Session-level risk controller. Tracks daily PnL, loss streak count, max drawdown, and open exposure. Exposes circuit-breaker logic (halt trading on N consecutive losses), session status checks, and EOD risk report generation.
- **Connects to:** `scanner.py`, `position_manager.py`, `discord_helpers.py`
- **⚠ Flaw:** Loss streak counter may not reset on the same EOD cadence as scanner.py's `loss_streak_alerted` flag — misalignment can block trading at session start.

#### `app/risk/position_manager.py`  (~41KB)
- **Role:** ★ Open position lifecycle manager. Tracks all active trades, manages entry/exit execution via Tradier brokerage API, monitors stop-loss and take-profit conditions, and updates position P&L in real-time.
- **Connects to:** `scanner.py`, `sniper.py`, `risk_manager.py`, `trade_calculator.py`, `discord_helpers.py`, `analytics`
- **Data sources consumed:** Tradier (order execution, position status), EODHD (live price for P&L)
- **⚠ Flaw:** Discord alert in sniper.py fires BEFORE position_manager confirms acceptance — need to reverse this order.

#### `app/risk/trade_calculator.py`  (~11KB)
- **Role:** Trade sizing calculator. Computes position size, dollar risk per trade, max contracts based on account equity, VIX-adjusted sizing, and Kelly Criterion approximation.
- **Connects to:** `position_manager.py`, `risk_manager.py`, `vix_sizing.py`

#### `app/risk/vix_sizing.py`  (~11KB)
- **Role:** VIX-driven position sizing adjuster. Scales trade size down when VIX is elevated (>20, >30 thresholds) to reduce risk in high-volatility regimes.
- **Connects to:** `trade_calculator.py`, `risk_manager.py`
- **Data sources consumed:** VIX data via EODHD or ws_feed

#### `app/risk/dynamic_thresholds.py`  (~7KB)
- **Role:** Dynamically adjusts signal confidence thresholds, stop distances, and target multipliers based on current market regime (trending, ranging, volatile). Higher thresholds in choppy markets, looser in trending.
- **Connects to:** `sniper.py`, `validation/__init__.py`, `risk_manager.py`

---

### SECTION 12 — app/analytics/ (PERFORMANCE & LEARNING LAYER)

#### `app/analytics/technical_indicators.py`  (~32KB)
- **Role:** Primary technical indicator library. Computes EMA, SMA, RSI, MACD, ATR, Bollinger Bands, ADX, Stochastic. Shared utility used by sniper.py and validation modules.
- **Connects to:** `sniper.py`, `validation.py`, `backtesting`

#### `app/analytics/technical_indicators_extended.py`  (~15KB)
- **Role:** Extended indicator library. Adds Ichimoku, Heikin-Ashi, squeeze momentum, and other advanced indicators not in the primary file.
- **Connects to:** `sniper.py`, `signal_boosters.py`

#### `app/analytics/volume_indicators.py`  (~11KB)
- **Role:** Volume-specific indicators: OBV, MFI (Money Flow Index), VWAP deviation, volume delta. Feeds CFW6 C4 (volume confirmation) and dynamic_screener.
- **Connects to:** `sniper.py`, `dynamic_screener.py`, `breakout_detector.py`

#### `app/analytics/performance_monitor.py`  (~20KB)
- **Role:** Real-time performance monitoring. Tracks running win rate, PnL curve, max drawdown, Sharpe ratio, and signal quality metrics per session. Writes to PostgreSQL for EOD reporting.
- **Connects to:** `analytics_integration.py`, `signal_analytics.py`, `eod_discord_report.py`

#### `app/analytics/performance_alerts.py`  (~17KB)
- **Role:** Threshold-based alert system for performance degradation. Fires Discord alerts when win rate drops below threshold, consecutive losses exceed limit, or drawdown approaches max.
- **Connects to:** `performance_monitor.py`, `discord_helpers.py`, `risk_manager.py`

#### `app/analytics/funnel_analytics.py`  (~14KB)
- **Role:** Funnel conversion tracking. Measures how many tickers enter each stage of the pipeline (screened → watchlist → signal → validated → traded → won). Identifies where candidates drop off.
- **Connects to:** `watchlist_funnel.py`, `scanner.py`, `performance_monitor.py`

#### `app/analytics/target_discovery.py`  (~14KB)
- **Role:** Post-market target discovery. Analyzes missed signals and near-misses to identify tickers that moved significantly but weren't in the watchlist. Feeds back into watchlist funnel calibration.
- **Connects to:** `watchlist_funnel.py`, `ai_learning.py`

#### `app/analytics/explosive_mover_tracker.py`  (~15KB)
- **Role:** Tracks and catalogs explosive movers (>3% intraday moves) across all scanned tickers. Builds a historical database of explosive-move setups to train ML models and improve pre-market screening.
- **Connects to:** `ai_learning.py`, `ml_trainer.py`, `target_discovery.py`

#### `app/analytics/explosive_tracker.py`  (~5KB)
- **Role:** Lighter companion to explosive_mover_tracker. Real-time monitoring of current-session tickers for explosive move qualification. May overlap — audit for consolidation opportunity.
- **⚠ Note:** Two explosive tracker files — verify distinct roles or merge.

#### `app/analytics/grade_gate_tracker.py`  (~10KB)
- **Role:** Tracks signal grade distribution over time (A/B/C signal grades). Monitors grade gate thresholds — if system is generating too many C-grade signals, it tightens filters automatically.
- **Connects to:** `validation/__init__.py`, `ai_learning.py`

#### `app/analytics/cooldown_tracker.py`  (~11KB)
- **Role:** Analytics-side cooldown tracking. Distinct from `signal_generator_cooldown.py` — this tracks cooldown events for analytics/reporting purposes rather than enforcement.
- **Connects to:** `signal_generator_cooldown.py`, `performance_monitor.py`

#### `app/analytics/ab_test_framework.py`  (~12KB)
- **Role:** A/B testing framework for strategy variations. Allows running two versions of signal parameters simultaneously (e.g., different RVOL thresholds) and comparing outcomes statistically.
- **Connects to:** `ai_learning.py`, `signal_analytics.py`

#### `app/analytics/rth_filter.py`  (~10KB)
- **Role:** Regular Trading Hours filter and analytics. Tracks performance by RTH sub-session (pre-market, open, midday, power hour, close) to identify which time windows produce the best signals.
- **Connects to:** `performance_monitor.py`, `scanner_optimizer.py`

#### `app/analytics/eod_discord_report.py`  (~6KB)
- **Role:** End-of-day Discord report generator. Formats and posts the daily performance summary to Discord: total signals, win rate, PnL, best/worst trades, signal quality breakdown.
- **Connects to:** `performance_monitor.py`, `discord_helpers.py`

#### `app/analytics/VOLUME_INDICATORS_README.md`
- **Role:** Documentation for volume_indicators.py usage and formula references.

---

### SECTION 13 — app/ai/ (ADAPTIVE LEARNING)

#### `app/ai/ai_learning.py`  (~15KB)
- **Role:** EOD weight optimization engine. After market close, analyzes that day's signal outcomes and adjusts CFW6 confirmation weights, score thresholds, and screening parameters. Implements a feedback loop for the system to improve daily.
- **Connects to:** `scanner.py` (EOD block), `signal_analytics.py`, `performance_monitor.py`, `ml_signal_scorer.py`
- **Data sources consumed:** PostgreSQL (signal history, outcome data)

---

### SECTION 14 — app/ml/ (MACHINE LEARNING LAYER)

#### `app/ml/ml_signal_scorer.py`  (~17KB)
- **Role:** ML-based signal scoring v1. Trained classifier that takes CFW6 feature vectors and outputs a probability-weighted confidence score. Supplements rule-based scoring in sniper.py.
- **Connects to:** `sniper.py`, `ai_learning.py`

#### `app/ml/ml_signal_scorer_v2.py`  (~16KB)
- **Role:** ML signal scorer v2. Likely uses a different model architecture or feature set than v1. Verify which version is active in production.
- **⚠ Action Required:** Confirm which scorer version is imported by sniper.py. If both exist, document which is primary and why.

#### `app/ml/ml_confidence_boost.py`  (~6KB)
- **Role:** Applies ML-derived confidence boost to rule-based signal scores. Takes the output from `ml_signal_scorer` and adds a calibrated delta to the sniper's confidence score before the threshold gate.
- **Connects to:** `sniper.py`, `ml_signal_scorer.py`, `signal_boosters.py`

#### `app/ml/ml_trainer.py`  (~16KB)
- **Role:** Model training pipeline. Takes labeled signal data from `signal_analytics.py`, engineers features, trains the classifier, and saves the model artifact to `models/` directory.
- **Connects to:** `train_from_analytics.py`, `models/` directory

#### `app/ml/train_from_analytics.py`  (~11KB)
- **Role:** Training data prep. Extracts and engineers features from the PostgreSQL analytics tables, labels them with signal outcomes (win/loss/miss), and feeds `ml_trainer.py`.
- **Connects to:** `ml_trainer.py`, PostgreSQL

#### `app/ml/train_ml_booster.py`  (~6KB)
- **Role:** Trains the confidence booster model specifically. Focused on calibrating the boost delta rather than the primary signal classifier.
- **Connects to:** `ml_confidence_boost.py`, `ml_trainer.py`

#### `app/ml/analyze_signal_failures.py`  (~7KB)
- **Role:** Post-hoc failure analysis tool. Queries failed/losing signals and identifies common feature patterns in losers. Feeds into model retraining and filter tightening.
- **Connects to:** `ml_trainer.py`, `train_from_analytics.py`

#### `app/ml/check_database.py`  (~1KB)
- **Role:** Minimal DB health check script for the ML pipeline. Verifies the analytics tables have sufficient labeled data before training runs.
- **Connects to:** PostgreSQL

#### `app/ml/INTEGRATION.md`
- **Role:** Integration guide for the ML layer — how to wire ml_signal_scorer into the live system.

#### `app/ml/README.md`
- **Role:** ML module overview, training cadence, and model version notes.

---

### SECTION 15 — app/enhancements/ (SIGNAL BOOSTERS)

#### `app/enhancements/signal_boosters.py`  (~11KB)
- **Role:** Rule-based signal confidence boosters. Applies score bonuses when additional confirming conditions are present: dark pool sweeps (from unusual_options), news catalyst alignment, sector tailwind, or explosive mover history. Boosts signal score above threshold without changing core CFW6 logic.
- **Connects to:** `sniper.py`, `unusual_options.py`, `news_catalyst.py`, `sector_rotation.py`, `ml_confidence_boost.py`
- **Data sources consumed:** Unusual Whales (flow), EODHD news

---

### SECTION 16 — app/backtesting/ (BACKTESTING FRAMEWORK)

#### `app/backtesting/backtest_engine.py`  (~20KB)
- **Role:** ★ Core backtesting engine. Replays historical EODHD bar data through the signal detection pipeline (sniper logic) and measures hypothetical performance. Generates equity curves, win rates, and drawdown metrics.
- **Connects to:** `signal_replay.py`, `performance_metrics.py`, `parameter_optimizer.py`, `data_manager.py`
- **Data sources consumed:** EODHD REST (historical OHLCV)

#### `app/backtesting/signal_replay.py`  (~7KB)
- **Role:** Signal replay module. Replays a saved set of historical signals through the exit logic to evaluate different stop/target configurations without re-running full bar-by-bar simulation.
- **Connects to:** `backtest_engine.py`, `performance_metrics.py`

#### `app/backtesting/walk_forward.py`  (~11KB)
- **Role:** Walk-forward optimization framework. Splits historical data into in-sample/out-of-sample windows, optimizes parameters on in-sample, validates on out-of-sample. Prevents overfitting.
- **Connects to:** `backtest_engine.py`, `parameter_optimizer.py`

#### `app/backtesting/parameter_optimizer.py`  (~6KB)
- **Role:** Parameter search engine. Runs grid search or random search over CFW6 thresholds, ATR multipliers, and RVOL minimums to find highest-Sharpe parameter sets.
- **Connects to:** `backtest_engine.py`, `walk_forward.py`

#### `app/backtesting/performance_metrics.py`  (~7KB)
- **Role:** Calculates backtest performance statistics: Sharpe ratio, Sortino ratio, max drawdown, win rate, profit factor, average win/loss, and expectancy.
- **Connects to:** `backtest_engine.py`, `signal_replay.py`

---

### SECTION 17 — app/discord_helpers.py

#### `app/discord_helpers.py`  (~20KB)
- **Role:** Central Discord notification module. Provides `send_simple_message()`, `send_signal_alert()`, `send_options_trade()`, `send_eod_report()`, and `send_error_alert()` functions. All Discord webhook calls route through here.
- **Connects to:** `scanner.py`, `sniper.py`, `risk_manager.py`, `position_manager.py`, `eod_discord_report.py`, `performance_alerts.py`
- **⚠ Note:** Verify webhook URL is environment-variable-driven and never hardcoded.

---

### SECTION 18 — DOCS, MIGRATIONS, MODELS, SCRIPTS, TESTS, UTILS

#### `docs/` directory
- **Role:** Architecture documents, this registry, and other developer reference docs.

#### `migrations/` directory
- **Role:** PostgreSQL database migration scripts. Should contain versioned SQL files for schema changes.
- **⚠ Note:** Verify migrations are tracked and applied to Railway's production DB consistently.

#### `models/` directory
- **Role:** Persisted ML model artifacts (pickle or joblib files) for `ml_signal_scorer.py`. Should be gitignored for large binary files — verify `.gitignore` covers this.

#### `scripts/` directory
- **Role:** Utility scripts for one-off operations: DB seeding, data export, manual backfill runs, etc.

#### `tests/` directory
- **Role:** Unit and integration test suite. Currently sparse — no tests exist for individual CFW6 confirmations, validation gates, or indicator calculations.
- **⚠ Critical Gap:** Zero automated tests on the most business-critical logic. This is the highest-risk gap in the entire system.

#### `utils/` directory
- **Role:** Shared utility functions used across modules: time zone helpers, date math, logging config, etc.

#### `audit_reports/` directory
- **Role:** Output directory for `audit_repo.py` reports. Not committed to version control.

---

## CONFIRMED FLAWS FROM ARCHITECTURE DOC — STATUS

| Flaw | Location | Status | Priority |
|---|---|---|---|
| `thread_safe_state.py` built but never used | `sniper.py` | 🔴 UNRESOLVED | P0 |
| Discord alert fires before position_manager accepts | `sniper.py` | 🔴 UNRESOLVED | P0 |
| No global timeout watchdog on process_ticker() | `scanner.py` | 🔴 UNRESOLVED | P0 |
| Loss streak counter / alerted flag mismatch | `scanner.py` / `risk_manager.py` | 🔴 UNRESOLVED | P1 |
| Cooldown dict not persisted across restarts | `signal_generator_cooldown.py` | 🔴 UNRESOLVED | P1 |
| Ticker case sensitivity in watchlist set | `scanner.py` | 🔴 UNRESOLVED | P1 |
| ATR stop uses spot ATR, not rolling | `sniper.py` | 🔴 UNRESOLVED | P1 |
| sniper.py re-fetches bars every call | `sniper.py` | 🔴 UNRESOLVED | P1 |
| Two health server files — one may be dead | `health_check.py` / `health_server.py` | 🟡 NEEDS AUDIT | P1 |
| Two explosive tracker files | `analytics/` | 🟡 NEEDS AUDIT | P2 |
| Two ML scorer versions — unclear which is primary | `ml/` | 🟡 NEEDS AUDIT | P1 |
| `sniper_mtf_trend_patch.py` — patch approach | `core/` | 🟡 NEEDS CLEANUP | P2 |
| `sniper_stubs.py` — risk of prod import | `core/` | 🟡 NEEDS GUARD | P2 |
| `signals/bos_fvg_detector.py` — possibly stub | `signals/` | 🟡 NEEDS AUDIT | P2 |
| `signals/signal_validator.py` — 1KB stub | `signals/` | 🟡 NEEDS AUDIT | P2 |
| Zero automated tests | `tests/` | 🔴 CRITICAL GAP | P0 |
| audit_repo.py not run in CI | root | 🟡 IMPROVEMENT | P3 |

---

## EODHD & DATA SOURCE OPTIMIZATION PLAN

### Current EODHD Endpoints in Use
| Endpoint | Used By | Lean Opportunity |
|---|---|---|
| REST historical bars | `data_manager.py`, `backtest_engine.py` | Route ALL through `candle_cache.py` first |
| REST intraday bars | `data_manager.py` | Compress to higher TFs via `mtf_compression.py` — avoid repeat calls |
| WebSocket OHLCV | `ws_feed.py` | Already streaming — make this the primary source, REST is fallback only |
| WebSocket quotes | `ws_quote_feed.py` | Already streaming — no REST fallback needed for spread checks |
| News API | `news_catalyst.py` | Cache per-ticker per-day — no re-fetch needed within same session |
| EOD data | `premarket_scanner.py` | Pull once at 4AM, cache in memory for entire pre-market session |

### Current Other Data Sources
| Source | Module | Status |
|---|---|---|
| Tradier (options chains + execution) | `options/`, `position_manager.py` | Active |
| Unusual Whales (options flow) | `unusual_options.py`, `signal_boosters.py` | Active — verify full integration |
| EODHD news | `news_catalyst.py` | Active |
| VIX data | `vix_sizing.py`, `sniper.py` | Verify source — EODHD or hardcoded? |

### Key Unused Data Opportunities (High Alpha Available)
| Data | Source | Integration Path |
|---|---|---|
| Dark pool prints | Unusual Whales | Already fetched — wire directly into `signal_boosters.py` score |
| Options flow sweeps | Unusual Whales | Wire into `watchlist_funnel.py` tier 1 scoring |
| GEX levels by strike | Tradier (computed) | `gex_engine.py` exists — verify it feeds `validation/__init__.py` |
| IV Rank trend | Tradier | `iv_tracker.py` exists — verify it feeds `greeks_precheck.py` |
| Sector ETF flow | EODHD | `sector_rotation.py` exists — verify real-time vs. EOD only |

---

## ELITE SYSTEM ENHANCEMENT ROADMAP

### Phase 1 — CRITICAL FIXES (P0) — Do These First
1. **Wire `thread_safe_state.py` into `sniper.py`** — Replace `_armed_signals` and `_watching_signals` plain dicts with `ThreadSafeDict`. This is already built, just import it.
2. **Fix Discord alert order in `sniper.py`** — Move Discord fire AFTER `position_manager.accept_signal()` returns True.
3. **Add timeout watchdog to `process_ticker()`** — Wrap in `concurrent.futures.ThreadPoolExecutor` with a timeout so a hung ticker can't stall the entire scan loop.
4. **Write 10 critical unit tests** — At minimum: CFW6 C1-C6 individual confirmation tests, spread gate test, cooldown test, loss streak reset test.

### Phase 2 — HIGH IMPACT FIXES (P1)
5. **Align loss streak reset cadence** — Ensure `risk_manager.reset_loss_streak()` is called in the same EOD block as `loss_streak_alerted = False`.
6. **Persist cooldown dict** — Serialize to Redis or a small SQLite sidecar so Railway restarts don't reset it.
7. **Force uppercase on all tickers** — One `.upper()` call at watchlist_funnel output eliminates the case-sensitivity bug permanently.
8. **Switch sniper ATR to rolling** — Use 5-bar rolling average ATR instead of spot ATR for stop calculation.
9. **Add in-memory bar cache to sniper.py** — Cache last fetched bars per ticker with a 30-second TTL so scanner cycles hit memory, not EODHD REST.
10. **Consolidate health server** — Keep `app/core/health_server.py`, delete `app/health_check.py`, update all imports.
11. **Determine active ML scorer** — Confirm whether `ml_signal_scorer.py` or `ml_signal_scorer_v2.py` is imported in production. Delete the inactive version.

### Phase 3 — LEAN & ELITE (P2)
12. **Route all REST bar fetches through `candle_cache.py`** — Zero duplicate EODHD REST calls within a session window.
13. **Wire GEX into validation gate** — `gex_engine.py` should actively block trades against a strong GEX pin level.
14. **Fully integrate Unusual Whales flow into funnel scoring** — Dark pool sweeps should add 10-15 points to watchlist tier score.
15. **Wire `mtf_compression.py` as the sole MTF data source** — Compress 1m bars to 5m/15m/1H in memory. Eliminate separate higher-timeframe REST calls entirely.
16. **Absorb `sniper_mtf_trend_patch.py` into `sniper.py`** — Once mtf_integration.py is stable, delete the patch file.
17. **Merge or clearly separate `explosive_tracker.py` vs `explosive_mover_tracker.py`** — One for real-time, one for historical. Name them accordingly.
18. **Add CI step to run `audit_repo.py`** — Fail the build if critical issues are found. Add a GitHub Actions workflow.

### Phase 4 — MAXIMUM DATA UTILIZATION (P3)
19. **Add IV Rank trend to options optimizer** — Not just current IV Rank but whether IV is expanding or contracting (IV trend from `iv_tracker.py`).
20. **Feed `explosive_mover_tracker.py` into next-day pre-market scan** — Tickers that made explosive moves yesterday are prime candidates for follow-through or reversal setups.
21. **Add `ab_test_framework.py` to CI** — Run parallel strategy variants in paper mode automatically.
22. **Wire `walk_forward.py` into monthly parameter refresh cycle** — Run walk-forward optimization on last 30 days of data every weekend and auto-update CFW6 thresholds.
23. **Add sector rotation real-time feed** — Currently likely EOD-based. Upgrade to intraday sector ETF flow from EODHD WebSocket for live sector bias.

---

*Document compiled: March 10, 2026 | AlgoOps25/War-Machine | For internal use only.*
