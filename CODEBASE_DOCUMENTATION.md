# War Machine — Complete Codebase Documentation

> Last updated: 2026-03-27  
> Repository: [AlgoOps25/War-Machine](https://github.com/AlgoOps25/War-Machine)

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture Summary](#architecture-summary)
3. [app/core](#appcore)
4. [app/data](#appdata)
5. [app/filters](#appfilters)
6. [app/screening](#appscreening)
7. [app/signals](#appsignals)
8. [app/validation](#appvalidation)
9. [app/options](#appoptions)
10. [app/risk](#apprisk)
11. [app/analytics](#appanalytics)
12. [app/mtf](#appmtf)
13. [app/ml](#appml)
14. [app/ai](#appai)
15. [app/indicators](#appindicators)
16. [app/notifications](#appnotifications)
17. [app/backtesting](#appbacktesting)
18. [migrations](#migrations)
19. [utils](#utils)
20. [scripts](#scripts)
21. [tests](#tests)

---

## Project Overview

War Machine is a fully automated, Python-based algorithmic trading system designed for intraday equities and options trading. It integrates real-time market data (WebSocket feeds), multi-timeframe technical analysis, Smart Money Concepts (SMC), options intelligence, ML-based signal scoring, and Discord-based alerting into a single unified pipeline. The system is deployed on Railway (cloud) and uses PostgreSQL as its primary database.

**Core technologies:** Python, PostgreSQL, WebSockets, Discord webhooks, EODHD API, Tradier API, Unusual Whales API, BullFlow.

---

## Architecture Summary

```
Premarket Scanner → Watchlist Funnel → Signal Detection → Validation Gates → Options Intelligence → Risk/Position Manager → Discord Alerts
                                              ↑
                              Real-time WebSocket Feeds (ws_feed / ws_quote_feed)
                                              ↑
                              Candle Cache ← Data Manager ← DB Connection (PostgreSQL)
```

The pipeline flows from pre-market scanning and watchlist construction, through breakout/ORB signal detection, multi-layer validation (regime, MTF, Greeks, volume profile), options selection and optimization, and finally risk-managed position sizing with Discord notifications.

---

## app/core

The central orchestration layer. Manages the main event loop, boot sequence, health server, scanner, sniper pipeline, signal state stores, scoring, and analytics integration.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 22 B | Package init |
| `__main__.py` | 1.4 KB | Entry point — boots logging → health server → scanner loop in correct Railway-safe order |
| `analytics_integration.py` | 9.2 KB | Bridges core pipeline with analytics tracking modules |
| `arm_signal.py` | 8.1 KB | Arms a validated signal — transitions it from watch state to armed/ready-to-fire state |
| `armed_signal_store.py` | 8.6 KB | Thread-safe store for armed signals pending entry confirmation |
| `eod_reporter.py` | 4.3 KB | End-of-day performance report generator — sends EOD Discord summary |
| `health_server.py` | 5.4 KB | Lightweight HTTP health server bound to $PORT for Railway liveness probe |
| `logging_config.py` | 3.6 KB | Centralized logging configuration — called once at boot in `__main__.py` |
| `scanner.py` | 31.6 KB | Main scan loop — orchestrates premarket scan, OR window, and intraday signal cycles |
| `signal_scorecard.py` | 10.2 KB | Computes composite signal scorecard (0–100) from RVOL, MTF, Greeks, GEX, regime factors |
| `sniper.py` | 27.9 KB | Sniper engine — evaluates armed signals tick-by-tick for precise entry triggers |
| `sniper_log.py` | 2.4 KB | Structured logger for sniper decisions and entry/exit events |
| `sniper_pipeline.py` | 13.7 KB | Sniper pipeline orchestrator — coordinates sniper evaluation across all armed signals |
| `thread_safe_state.py` | 10.8 KB | Thread-safe shared state container used across scanner, sniper, and data threads |
| `watch_signal_store.py` | 9.9 KB | Thread-safe store for signals in watch state (detected but not yet armed) |

> **Note:** The following files listed in earlier documentation do not exist in the repository and were removed or never built: `config_validator.py`, `failover.py`, `health_monitor.py`, `lifecycle.py`, `main.py`, `market_hours.py`, `scheduler.py`, `session_manager.py`, `signal_pipeline.py`.

---

## app/data

Handles all data acquisition, caching, WebSocket feeds, and database connectivity.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 30 B | Package init |
| `candle_cache.py` | 16.1 KB | In-memory + DB-backed OHLCV candle caching system |
| `data_manager.py` | 43.8 KB | Primary data orchestrator — fetches, normalizes, and distributes market data across the system |
| `database.py` | 1.9 KB | Lightweight DB connection wrapper |
| `db_connection.py` | 27.8 KB | Full PostgreSQL connection manager with pooling, retries, and query helpers |
| `intraday_atr.py` | 3.8 KB | Real-time ATR (Average True Range) calculation from intraday bars |
| `sql_safe.py` | 12.8 KB | SQL injection-safe query builder and parameter sanitizer |
| `unusual_options.py` | 15.8 KB | Fetches and parses unusual options flow data (Unusual Whales integration) |
| `ws_feed.py` | 22.9 KB | Primary WebSocket feed handler for real-time trade/quote data |
| `ws_quote_feed.py` | 20.3 KB | Secondary WebSocket feed specifically for NBBO quote streaming |

---

## app/filters

Pre-signal quality gates that suppress low-probability setups before they reach the signal engine.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 341 B | Package init with filter exports |
| `correlation.py` | 8.0 KB | Filters signals correlated with broader market moves (anti-correlated alpha detection) |
| `dead_zone_suppressor.py` | 2.7 KB | Suppresses signals fired during known low-volatility/choppy dead zones |
| `early_session_disqualifier.py` | 3.0 KB | Blocks signals in the first minutes of RTH before price discovery settles |
| `gex_pin_gate.py` | 2.4 KB | Blocks entries near GEX pin levels where price tends to stall |
| `liquidity_sweep.py` | 4.6 KB | Detects and filters out liquidity sweep traps (stop hunts) |
| `market_regime_context.py` | 14.8 KB | Classifies current market regime (trending/ranging/volatile) and filters accordingly |
| `mtf_bias.py` | 7.4 KB | Multi-timeframe directional bias gate — blocks counter-trend signals |
| `order_block_cache.py` | 3.9 KB | Caches identified order blocks for reuse across filter/signal modules |
| `rth_filter.py` | 9.8 KB | Regular Trading Hours session filter with extended logic for open/close windows |
| `sd_zone_confluence.py` | 3.8 KB | Supply/demand zone confluence checker — requires price proximity to key zones |
| `vwap_gate.py` | 1.7 KB | VWAP-relative position gate — filters signals on wrong side of VWAP |

---

## app/screening

Pre-market and intraday stock screening pipeline that builds the actionable watchlist.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 24 B | Package init |
| `dynamic_screener.py` | 25.4 KB | Real-time intraday screener — scans for momentum, volume, and technical criteria dynamically |
| `gap_analyzer.py` | 8.0 KB | Identifies and scores pre-market gap candidates |
| `market_calendar.py` | 3.5 KB | Trading calendar utility — handles holidays, half-days, session boundaries |
| `news_catalyst.py` | 14.4 KB | Scrapes and scores news catalysts to identify event-driven movers |
| `premarket_scanner.py` | 35.2 KB | Full pre-market scanner — runs at 8:45–9:25 AM EST to build the day's watchlist |
| `volume_analyzer.py` | 14.0 KB | Relative volume analysis — identifies unusual volume surges vs. historical averages |
| `watchlist_funnel.py` | 41.0 KB | Master watchlist funnel — scores and ranks all screened candidates into a final prioritized list |

---

## app/signals

Core signal detection engines — generates raw trade signals from price action and structure.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 32 B | Package init |
| `breakout_detector.py` | 31.9 KB | Detects price breakouts above/below key levels with volume and candle confirmation |
| `opening_range.py` | 39.2 KB | Opening Range Breakout (ORB) engine — tracks and trades the opening range across multiple timeframes |
| `signal_analytics.py` | 31.3 KB | Records, scores, and tracks signal metadata for analytics and ML training |
| `vwap_reclaim.py` | 4.0 KB | Detects VWAP reclaim patterns as secondary signal triggers |

---

## app/validation

Multi-layer signal validation gates. A signal must pass all gates before proceeding to options/risk.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 1.4 KB | Package init with validator exports |
| `cfw6_confirmation.py` | 12.9 KB | CFW6 candle confirmation logic — validates directional candle structure |
| `cfw6_gate_validator.py` | 14.8 KB | Full CFW6 gate validation pipeline with scoring and pass/fail logic |
| `entry_timing.py` | 8.3 KB | Validates entry timing relative to session windows and momentum windows |
| `greeks_precheck.py` | 25.3 KB | Pre-validates options Greeks (delta, gamma, theta, IV) before committing to a trade |
| `hourly_gate.py` | 5.7 KB | Hourly performance-based gate — disables trading during poor-performing hours |
| `options_filter.py` | 16.4 KB | Options contract quality filter — liquidity, spread, OI requirements |
| `regime_filter.py` | 9.5 KB | Regime-based validation — blocks signals incompatible with current market regime |
| `validation.py` | 22.5 KB | Master validation orchestrator — runs all sub-validators in sequence |
| `volume_profile.py` | 19.2 KB | Volume profile analysis — validates signals at high-volume nodes and POC levels |

---

## app/options

Options intelligence, selection, optimization, and data management.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 25.1 KB | Package init — exports core options interfaces |
| `dte_historical_advisor.py` | 5.2 KB | Uses historical data to advise optimal DTE selection by symbol/regime |
| `dte_selector.py` | 3.9 KB | Core DTE selection logic based on signal type and market conditions |
| `gex_engine.py` | 9.9 KB | Gamma Exposure (GEX) calculation engine — identifies gamma walls and flip points |
| `iv_tracker.py` | 5.3 KB | Tracks implied volatility rank (IVR) and IV percentile in real-time |
| `options_data_manager.py` | 10.5 KB | Fetches and caches options chains, Greeks, and OI data |
| `options_dte_selector.py` | 15.1 KB | Advanced DTE selector with multi-factor scoring (IV, liquidity, delta target) |
| `options_intelligence.py` | 44.8 KB | Core options intelligence engine — scores contracts, detects unusual flow, recommends strikes |
| `options_optimizer.py` | 25.2 KB | Optimizes contract selection across strike, DTE, and spread type for maximum risk-adjusted return |

---

## app/risk

Position sizing, risk management, and trade lifecycle management.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 29 B | Package init |
| `dynamic_thresholds.py` | 7.2 KB | Dynamically adjusts stop/target thresholds based on ATR and regime |
| `position_helpers.py` | 4.8 KB | Helper utilities for position calculations (P&L, breakeven, sizing) |
| `position_manager.py` | 45.1 KB | Full position lifecycle manager — entry, monitoring, scaling, exit logic |
| `risk_manager.py` | 14.5 KB | Portfolio-level risk enforcement — daily loss limits, max positions, drawdown guards |
| `trade_calculator.py` | 14.0 KB | Trade sizing calculator — Kelly, fixed-fractional, and VIX-adjusted sizing models |
| `vix_sizing.py` | 10.1 KB | VIX-based position size scalar — reduces size in high-volatility environments |

---

## app/analytics

Performance tracking, funnel analytics, A/B testing, and signal outcome recording.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 1.2 KB | Package init with analytics exports |
| `ab_test.py` | 3.3 KB | Simple A/B test utility for comparing signal variants |
| `ab_test_framework.py` | 9.0 KB | Full A/B testing framework with statistical significance tracking |
| `cooldown_tracker.py` | 12.1 KB | Tracks per-symbol cooldown periods after losses to prevent revenge trading |
| `explosive_mover_tracker.py` | 14.9 KB | Identifies and tracks "explosive mover" stocks with outsized intraday range |
| `explosive_tracker.py` | 762 B | Lightweight explosive move flag tracker |
| `funnel_analytics.py` | 13.6 KB | Tracks signal drop-off at each funnel stage (screened → filtered → validated → traded) |
| `funnel_tracker.py` | 4.0 KB | Real-time funnel stage counter and reporter |
| `grade_gate_tracker.py` | 7.8 KB | Tracks signal grades and enforces minimum grade thresholds for entry |
| `performance_monitor.py` | 12.3 KB | Monitors live trading performance — win rate, PnL, Sharpe, expectancy |

---

## app/mtf

Multi-Timeframe (MTF) analysis, Smart Money Concepts (SMC), BOS/FVG detection.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 1.1 KB | Package init with MTF exports |
| `bos_fvg_engine.py` | 21.0 KB | Break of Structure (BOS) and Fair Value Gap (FVG) detection engine across multiple timeframes |
| `mtf_compression.py` | 9.4 KB | Detects multi-timeframe price compression as a pre-breakout signal |
| `mtf_fvg_priority.py` | 15.9 KB | Prioritizes and ranks FVGs by timeframe, freshness, and proximity |
| `mtf_integration.py` | 16.2 KB | Integrates MTF signals into the main validation pipeline |
| `mtf_validator.py` | 6.1 KB | Validates that signal direction aligns with MTF structure |
| `smc_engine.py` | 26.8 KB | Full Smart Money Concepts engine — order blocks, liquidity levels, market structure shifts |

---

## app/ml

Machine learning signal scoring, confidence boosting, and model training.

| File | Size | Description |
|------|------|-------------|
| `INTEGRATION.md` | 8.8 KB | Integration guide for plugging ML models into the live pipeline |
| `README.md` | 6.4 KB | ML module overview, feature descriptions, and training workflow |
| `__init__.py` | 27 B | Package init |
| `metrics_cache.py` | 1.2 KB | Caches computed ML feature metrics to avoid redundant computation |
| `ml_confidence_boost.py` | 6.4 KB | Applies ML model output to boost/suppress signal confidence scores |
| `ml_trainer.py` | 24.8 KB | Full ML training pipeline — feature engineering, model training, evaluation, and persistence |

---

## app/ai

AI-powered adaptive learning from live trading outcomes.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 29 B | Package init |
| `ai_learning.py` | 15.5 KB | Adaptive AI learning module — updates signal weights and parameters based on live trade outcomes |

---

## app/indicators

Technical indicator library used across signal detection and validation modules.

| File | Size | Description |
|------|------|-------------|
| `technical_indicators.py` | 31.8 KB | Core technical indicator library — RSI, MACD, Bollinger Bands, ATR, EMA, SMA, stochastics, and more |
| `technical_indicators_extended.py` | 15.5 KB | Extended indicators — Keltner Channels, Ichimoku, CMF, ADX, supertrend, etc. |
| `volume_indicators.py` | 11.3 KB | Volume-specific indicators — OBV, VWAP bands, volume delta, cumulative delta |
| `vwap_calculator.py` | 15.4 KB | Full VWAP calculator with standard deviation bands, anchored VWAP, and session reset logic |

---

## app/notifications

Discord-based alert and notification system.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 1.1 KB | Package init with notification exports |
| `discord_helpers.py` | 25.6 KB | Full Discord webhook integration — formats and sends signal alerts, EOD reports, health checks, and trade notifications with rich embeds |

---

## app/backtesting

Backtesting engine, historical simulation, and performance analysis.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 1.8 KB | Package init with backtesting exports |
| `backtest_engine.py` | 19.3 KB | Core backtesting engine — replays historical candles through the live signal pipeline |
| `historical_trainer.py` | 42.2 KB | Trains system parameters against historical data with full signal pipeline simulation |
| `parameter_optimizer.py` | 5.9 KB | Grid/random search optimizer for system parameters |
| `performance_metrics.py` | 7.2 KB | Computes backtest performance metrics — Sharpe, Sortino, max drawdown, win rate, expectancy |
| `signal_replay.py` | 6.8 KB | Replays recorded signals through updated logic for re-evaluation |
| `walk_forward.py` | 11.4 KB | Walk-forward optimization framework to prevent overfitting |

---

## migrations

Database schema migrations for PostgreSQL.

| File | Size | Description |
|------|------|-------------|
| `001_candle_cache.sql` | 1.2 KB | Creates the candle cache table schema |
| `002_signal_persist_tables.sql` | 1.3 KB | Creates signal persistence tables for outcome tracking |
| `add_dte_tracking_columns.py` | 1.3 KB | Migration script — adds DTE tracking columns to existing tables |
| `signal_outcomes_schema.sql` | 3.4 KB | Full schema for signal outcomes, trade results, and ML training data |

---

## utils

Shared utility modules used across the entire codebase.

| File | Size | Description |
|------|------|-------------|
| `__init__.py` | 22 B | Package init |
| `bar_utils.py` | 779 B | OHLCV bar manipulation helpers |
| `config.py` | 19.1 KB | Central configuration manager — loads and validates all environment variables and system settings |
| `production_helpers.py` | 5.9 KB | Production environment helpers — Railway-specific utilities, env detection |
| `time_helpers.py` | 1.7 KB | Time/timezone utility functions (ET conversion, market time checks) |

---

## scripts

Developer, maintenance, debug, and operational scripts. Not part of the live trading pipeline.

### Root Scripts

| File | Size | Description |
|------|------|-------------|
| `README_ML_TRAINING.md` | 7.2 KB | Guide for running ML training workflows |
| `audit_repo.py` | 25.3 KB | Full repository code audit — checks for issues, dead code, and inconsistencies |
| `check_db.py` | 1.9 KB | Quick database connectivity check |
| `check_eodhd_intraday.py` | 3.3 KB | Tests EODHD intraday API endpoints |
| `debug_bos_scan.py` | 3.4 KB | Debug script for BOS scanner output |
| `debug_comprehensive.py` | 4.2 KB | Comprehensive system debug runner |
| `debug_db.py` | 1.3 KB | Database query debugger |
| `deploy.ps1` | 2.1 KB | PowerShell deployment script for Railway |
| `extract_positions_from_db.py` | 5.1 KB | Extracts position records from DB for review |
| `extract_signals_from_logs.py` | 2.6 KB | Parses log files to extract historical signal data |
| `fix_print_to_logger.py` | 9.9 KB | Automated script to replace print() statements with logger calls across the codebase |
| `generate_backtest_intelligence.py` | 11.3 KB | Generates backtest intelligence reports from stored results |
| `generate_ml_training_data.py` | 16.1 KB | Exports ML training datasets from the signal outcomes database |
| `system_health_check.py` | 14.9 KB | Full system health check — validates all API connections, DB, feeds, and configs |

### scripts/analysis

| File | Size | Description |
|------|------|-------------|
| `analyze_ml_training_data.py` | 9.8 KB | Analyzes ML training dataset quality and feature distributions |
| `analyze_signal_failures.py` | 7.5 KB | Post-mortems on failed signals to identify common failure patterns |
| `atr_check.py` | 1.2 KB | Quick ATR value checker for specific symbols |
| `audit4.py` | 1.8 KB | Targeted code audit script (iteration 4) |
| `entry_times.py` | 2.2 KB | Analyzes distribution of trade entry times |
| `inspect_candles.py` | 485 B | Inspects raw candle data from the cache |
| `inspect_signal_outcomes.py` | 6.5 KB | Deep inspection of signal outcome records |
| `metric_scan.py` | 3.1 KB | Scans performance metrics across symbols and timeframes |
| `or_timing_analysis.py` | 18.9 KB | Detailed opening range timing analysis — best ORB entry windows |

### scripts/backtesting

| File | Size | Description |
|------|------|-------------|
| `analyze_losers.py` | 13.3 KB | Analyzes losing trades to identify correctable patterns |
| `analyze_signal_patterns.py` | 14.4 KB | Pattern analysis across historical signal data |
| `analyze_trades.py` | 9.2 KB | General trade analysis across backtest results |
| `backtest_optimized_params.py` | 29.8 KB | Runs backtests with optimized parameter sets |
| `backtest_sweep.py` | 10.1 KB | Parameter sweep backtester across a defined search space |
| `debug_fvg.py` | 2.4 KB | FVG detection debugger |
| `extract_candles_from_db.py` | 8.2 KB | Extracts candle data from DB for offline backtesting |
| `filter_ablation.py` | 8.9 KB | Ablation study — measures impact of removing individual filters on performance |
| `or_range_candle_grid.py` | 21.2 KB | Grid search over OR range and candle parameters |
| `or_range_grid.py` | 8.3 KB | OR range parameter grid search |
| `probe_db.py` | 1.0 KB | Quick DB probe for backtest data availability |
| `production_indicator_backtest.py` | 15.1 KB | Backtests production indicator configurations |
| `run_full_dte_backtest.py` | 3.1 KB | Runs full DTE optimization backtest |
| `simulate_from_candles.py` | 15.8 KB | Full candle-by-candle simulation engine |
| `test_dte_logic.py` | 7.5 KB | Unit-style tests for DTE selection logic |
| `unified_production_backtest.py` | 18.4 KB | Unified backtest runner matching exact production pipeline |
| `walk_forward_backtest.py` | 38.7 KB | Full walk-forward backtest implementation |

### scripts/backtesting/campaign

Numbered step-by-step campaign pipeline for running structured backtest campaigns.

| File | Size | Description |
|------|------|-------------|
| `README.md` | 2.5 KB | Campaign pipeline usage guide |
| `00_export_from_railway.py` | 12.5 KB | Step 0 — exports live data from Railway PostgreSQL for local backtesting |
| `00b_backfill_eodhd.py` | 11.9 KB | Step 0b — backfills missing candle history via EODHD API |
| `01_fetch_candles.py` | 6.3 KB | Step 1 — fetches and stores candles for campaign symbols |
| `02_run_campaign.py` | 17.5 KB | Step 2 — runs the full backtest campaign across all symbols and parameter sets |
| `03_analyze_results.py` | 7.1 KB | Step 3 — analyzes and summarizes campaign results |
| `probe_railway.py` | 2.4 KB | Probes Railway DB connectivity before campaign run |

### scripts/database

| File | Size | Description |
|------|------|-------------|
| `backfill_history.py` | 5.2 KB | Backfills historical OHLCV data into the database |
| `check_database.py` | 1.6 KB | Database health check |
| `create_daily_technicals.sql` | 758 B | SQL for daily technicals table creation |
| `db_diagnostic.py` | 3.5 KB | Detailed database diagnostics |
| `dte_selector_demo.py` | 7.0 KB | Demo script for DTE selector logic |
| `inspect_database_schema.py` | 4.9 KB | Inspects and prints full database schema |
| `inspect_tables.py` | 742 B | Lists all tables and row counts |
| `list_tables.py` | 290 B | Minimal table lister |
| `load_historical_data.py` | 14.7 KB | Loads historical data from external sources into DB |
| `setup_database.py` | 1.5 KB | Initial database setup script |

### scripts/maintenance

| File | Size | Description |
|------|------|-------------|
| `update_sniper_greeks.py` | 4.0 KB | Updates Greeks data for sniper-mode positions |

### scripts/ml

| File | Size | Description |
|------|------|-------------|
| `train_from_analytics.py` | 6.2 KB | Trains ML model from analytics/outcome data |
| `train_historical.py` | 5.4 KB | Trains ML model from historical signal database |
| `train_ml_booster.py` | 6.2 KB | Trains the ML confidence booster model |

### scripts/optimization

| File | Size | Description |
|------|------|-------------|
| `smart_optimization.py` | 25.5 KB | Smart parameter optimization using Bayesian/genetic approaches |

### scripts/powershell

| File | Size | Description |
|------|------|-------------|
| `dependency_analyzer.ps1` | 4.8 KB | PowerShell script to analyze Python module dependencies |
| `restore_and_deploy.ps1` | 830 B | Restore from backup and redeploy to Railway |

---

## tests

Pytest-based test suite covering core pipeline components.

| File | Size | Description |
|------|------|-------------|
| `README.md` | 181 B | Test suite overview |
| `__init__.py` | 25 B | Package init |
| `conftest.py` | 6.2 KB | Pytest fixtures and shared test configuration |
| `test_eod_reporter.py` | 9.4 KB | Tests for end-of-day report generation |
| `test_failover.py` | 13.4 KB | Tests for API/feed failover logic |
| `test_funnel_analytics.py` | 5.4 KB | Tests for funnel analytics tracking |
| `test_integrations.py` | 7.1 KB | Integration tests across multiple modules |
| `test_mtf.py` | 6.9 KB | Tests for multi-timeframe analysis |
| `test_signal_pipeline.py` | 27.3 KB | Comprehensive signal pipeline tests |
| `test_smc_engine.py` | 23.5 KB | Tests for SMC engine (BOS, FVG, order blocks) |

---

*Documentation maintained manually — update after every structural change to the codebase. Last audited: 2026-03-27.*
