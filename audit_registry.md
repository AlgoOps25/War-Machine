# War-Machine Audit Registry
> **Purpose:** Complete system map of every file in the repo. Track audit status, dependencies, and flag unnecessary files.
> **Last Updated:** 2026-04-03
> **Legend:** ⬜ Not Audited | 🟡 In Progress | ✅ Audited | 🗑️ Candidate for Removal | 📦 Data/Output (no audit needed)

---

## Audit Progress

| Category | Total Files | Audited | Remaining |
|----------|-------------|---------|-----------|
| app/core | 8 | 0 | 8 |
| app/data | 7 | 0 | 7 |
| app/signals | 9 | 0 | 9 |
| app/validation | 9 | 0 | 9 |
| app/filters | 6 | 0 | 6 |
| app/indicators | 8 | 0 | 8 |
| app/screening | 5 | 0 | 5 |
| app/risk | 5 | 0 | 5 |
| app/notifications | 4 | 0 | 4 |
| app/analytics | 4 | 0 | 4 |
| app/backtesting | 6 | 0 | 6 |
| app/options | 5 | 0 | 5 |
| app/ml | 4 | 0 | 4 |
| app/mtf | 4 | 0 | 4 |
| app/ai | 3 | 0 | 3 |
| app/futures | 3 | 0 | 3 |
| utils | 5 | 0 | 5 |
| tests | 10 | 0 | 10 |
| migrations | TBD | 0 | TBD |
| scripts | 18+ | 0 | 18+ |
| backtests/results | ~80 | N/A | 📦 |
| backtests/analysis | 4 | N/A | 📦 |
| docs | TBD | N/A | TBD |
| root | 12 | 0 | 12 |

---

## 🕸️ Dependency Spiderweb (High-Level)

```
utils/config.py ──────────────────────────────────────────► ALL modules
utils/bar_utils.py ──────────────────────────────────────► indicators/, signals/
utils/time_helpers.py ───────────────────────────────────► core/, screening/

app/data/data_manager.py ────────────────────────────────► core/scanner.py
app/data/ws_feed.py ─────────────────────────────────────► core/scanner.py
app/data/eodhd_client.py ────────────────────────────────► data_manager.py, backtesting/
app/data/tradier_client.py ──────────────────────────────► options/, validation/greeks_precheck.py

app/indicators/ ──────────────────────────────────────────► signals/
app/signals/ ─────────────────────────────────────────────► validation/
app/validation/ ──────────────────────────────────────────► core/scanner.py
app/filters/ ─────────────────────────────────────────────► validation/, signals/
app/screening/ ───────────────────────────────────────────► core/scanner.py
app/risk/ ────────────────────────────────────────────────► core/scanner.py, notifications/
app/notifications/ ───────────────────────────────────────► core/scanner.py
app/analytics/ ───────────────────────────────────────────► core/, signals/
app/options/ ─────────────────────────────────────────────► validation/greeks_precheck.py, tradier_client
app/ml/ ──────────────────────────────────────────────────► signals/, indicators/
app/mtf/ ─────────────────────────────────────────────────► indicators/, signals/
app/ai/ ──────────────────────────────────────────────────► signals/, analytics/
app/futures/ ─────────────────────────────────────────────► data/, indicators/
app/backtesting/ ─────────────────────────────────────────► signals/, validation/, data/
```

> ⚠️ This map is preliminary. It will be updated with exact import-level dependencies as each file is audited.

---

## ROOT FILES

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 1 | `.gitignore` | — | Config | ✅ Audited | Standard gitignore |
| 2 | `.railway_trigger` | — | Config | ⬜ Not Audited | Railway deploy trigger |
| 3 | `CODEBASE_DOCUMENTATION.md` | — | Docs | ⬜ Not Audited | System documentation |
| 4 | `CONTEXT.md` | — | Docs | ⬜ Not Audited | Project context notes |
| 5 | `CONTRIBUTING.md` | — | Docs | ⬜ Not Audited | Contribution guide |
| 6 | `LICENSE` | — | Legal | ✅ Audited | License file |
| 7 | `README.md` | — | Docs | ⬜ Not Audited | Main readme |
| 8 | `REBUILD_PLAN.md` | — | Docs | ⬜ Not Audited | Rebuild planning doc |
| 9 | `nixpacks.toml` | — | Config | ⬜ Not Audited | Railway build config |
| 10 | `pytest.ini` | — | Config | ⬜ Not Audited | Pytest configuration |
| 11 | `railway.toml` | — | Config | ⬜ Not Audited | Railway deploy config |
| 12 | `requirements.txt` | — | Config | ⬜ Not Audited | Python dependencies |
| 13 | `run_migration_006.py` | — | Migration | ⬜ Not Audited | One-off migration script |

---

## app/ — CORE ENGINE

### app/core/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 14 | `app/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 15 | `app/core/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 16 | `app/core/scanner.py` | ~36KB | Core Engine | data_manager, ws_feed, validation, screening, risk, notifications | ⬜ Not Audited | Main scanner orchestrator |
| 17 | `app/core/main.py` | — | Entry Point | scanner.py | ⬜ Not Audited | App entry point |
| 18 | `app/core/scheduler.py` | — | Scheduler | scanner.py | ⬜ Not Audited | Job scheduling |
| 19 | `app/core/session_manager.py` | — | State | scanner.py | ⬜ Not Audited | Session state management |
| 20 | `app/core/health_monitor.py` | — | Monitoring | — | ⬜ Not Audited | System health checks |
| 21 | `app/core/failover.py` | — | Reliability | data_manager, ws_feed | ⬜ Not Audited | Failover logic |

### app/data/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 22 | `app/data/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 23 | `app/data/data_manager.py` | — | Data | eodhd_client, db_manager, config | ⬜ Not Audited | Central data hub |
| 24 | `app/data/ws_feed.py` | — | Data | tradier_client, config | ⬜ Not Audited | WebSocket feed |
| 25 | `app/data/eodhd_client.py` | — | Data | config | ⬜ Not Audited | EODHD API client |
| 26 | `app/data/tradier_client.py` | — | Data | config | ⬜ Not Audited | Tradier API client |
| 27 | `app/data/db_manager.py` | — | Data | config | ⬜ Not Audited | PostgreSQL manager |
| 28 | `app/data/candle_store.py` | — | Data | db_manager | ⬜ Not Audited | Candle storage |

### app/signals/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 29 | `app/signals/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 30 | `app/signals/bos_fvg_engine.py` | — | Signal | indicators/, config | ⬜ Not Audited | BOS/FVG detection — CORE |
| 31 | `app/signals/crt_engine.py` | — | Signal | indicators/, config | ⬜ Not Audited | CRT pattern engine |
| 32 | `app/signals/opening_range.py` | — | Signal | indicators/, config | ⬜ Not Audited | Opening range breakout |
| 33 | `app/signals/signal_composer.py` | — | Signal | bos_fvg_engine, crt_engine, opening_range | ⬜ Not Audited | Signal aggregator |
| 34 | `app/signals/signal_store.py` | — | Signal | db_manager | ⬜ Not Audited | Signal persistence |
| 35 | `app/signals/eod_reporter.py` | — | Signal | signal_store, notifications | ⬜ Not Audited | EOD report generator |
| 36 | `app/signals/or_engine.py` | — | Signal | indicators/ | ⬜ Not Audited | OR engine variant |
| 37 | `app/signals/smc_engine.py` | — | Signal | indicators/, bos_fvg_engine | ⬜ Not Audited | SMC pattern engine — CORE |

### app/validation/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 38 | `app/validation/__init__.py` | 1.4KB | Init | — | ⬜ Not Audited | |
| 39 | `app/validation/validation.py` | 23KB | Validation | cfw6_gate_validator, regime_filter, entry_timing | ⬜ Not Audited | Master validator — CORE |
| 40 | `app/validation/cfw6_gate_validator.py` | 18KB | Validation | indicators/, config | ⬜ Not Audited | CFW6 gate logic |
| 41 | `app/validation/cfw6_confirmation.py` | 13KB | Validation | cfw6_gate_validator | ⬜ Not Audited | CFW6 confirmation |
| 42 | `app/validation/greeks_precheck.py` | 26KB | Validation | tradier_client, options/ | ⬜ Not Audited | Options Greeks filter |
| 43 | `app/validation/options_filter.py` | 17KB | Validation | greeks_precheck, tradier_client | ⬜ Not Audited | Options filter |
| 44 | `app/validation/regime_filter.py` | 10KB | Validation | indicators/ | ⬜ Not Audited | Market regime filter |
| 45 | `app/validation/entry_timing.py` | 10KB | Validation | indicators/, config | ⬜ Not Audited | Entry timing gate |
| 46 | `app/validation/hourly_gate.py` | 6KB | Validation | config | ⬜ Not Audited | Hourly trading gate |

### app/filters/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 47 | `app/filters/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 48 | `app/filters/volume_filter.py` | — | Filter | indicators/, config | ⬜ Not Audited | Volume filter |
| 49 | `app/filters/trend_filter.py` | — | Filter | indicators/ | ⬜ Not Audited | Trend filter |
| 50 | `app/filters/news_filter.py` | — | Filter | config | ⬜ Not Audited | News/event filter |
| 51 | `app/filters/gap_filter.py` | — | Filter | indicators/ | ⬜ Not Audited | Gap filter |
| 52 | `app/filters/liquidity_filter.py` | — | Filter | indicators/ | ⬜ Not Audited | Liquidity filter |

### app/indicators/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 53 | `app/indicators/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 54 | `app/indicators/atr.py` | — | Indicator | bar_utils | ⬜ Not Audited | ATR calculation |
| 55 | `app/indicators/vwap.py` | — | Indicator | bar_utils | ⬜ Not Audited | VWAP calculation |
| 56 | `app/indicators/ema.py` | — | Indicator | bar_utils | ⬜ Not Audited | EMA calculation |
| 57 | `app/indicators/rsi.py` | — | Indicator | bar_utils | ⬜ Not Audited | RSI calculation |
| 58 | `app/indicators/macd.py` | — | Indicator | bar_utils | ⬜ Not Audited | MACD calculation |
| 59 | `app/indicators/bollinger.py` | — | Indicator | bar_utils | ⬜ Not Audited | Bollinger Bands |
| 60 | `app/indicators/swing_points.py` | — | Indicator | bar_utils | ⬜ Not Audited | Swing high/low detection |

### app/screening/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 61 | `app/screening/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 62 | `app/screening/universe_builder.py` | — | Screening | eodhd_client, config | ⬜ Not Audited | Ticker universe builder |
| 63 | `app/screening/premarket_screener.py` | — | Screening | eodhd_client, filters/ | ⬜ Not Audited | Pre-market screener |
| 64 | `app/screening/gap_screener.py` | — | Screening | filters/gap_filter | ⬜ Not Audited | Gap screener |
| 65 | `app/screening/watchlist_manager.py` | — | Screening | db_manager | ⬜ Not Audited | Watchlist management |

### app/risk/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 66 | `app/risk/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 67 | `app/risk/position_sizer.py` | — | Risk | config | ⬜ Not Audited | Position sizing logic |
| 68 | `app/risk/risk_manager.py` | — | Risk | position_sizer, config | ⬜ Not Audited | Risk management — CORE |
| 69 | `app/risk/stop_manager.py` | — | Risk | indicators/, config | ⬜ Not Audited | Stop loss management |
| 70 | `app/risk/drawdown_monitor.py` | — | Risk | db_manager | ⬜ Not Audited | Drawdown tracking |

### app/notifications/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 71 | `app/notifications/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 72 | `app/notifications/discord_notifier.py` | — | Notifications | config | ⬜ Not Audited | Discord alerts |
| 73 | `app/notifications/alert_manager.py` | — | Notifications | discord_notifier | ⬜ Not Audited | Alert routing |
| 74 | `app/notifications/eod_summary.py` | — | Notifications | signal_store, db_manager | ⬜ Not Audited | EOD summary alerts |

### app/analytics/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 75 | `app/analytics/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 76 | `app/analytics/funnel_analytics.py` | — | Analytics | signal_store, db_manager | ⬜ Not Audited | Signal funnel analytics |
| 77 | `app/analytics/performance_tracker.py` | — | Analytics | db_manager | ⬜ Not Audited | Trade performance |
| 78 | `app/analytics/win_rate_analyzer.py` | — | Analytics | db_manager | ⬜ Not Audited | Win rate analysis |

### app/backtesting/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 79 | `app/backtesting/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 80 | `app/backtesting/backtester.py` | — | Backtesting | signals/, validation/, data/ | ⬜ Not Audited | Core backtester |
| 81 | `app/backtesting/walk_forward.py` | — | Backtesting | backtester | ⬜ Not Audited | Walk-forward testing |
| 82 | `app/backtesting/ablation_tester.py` | — | Backtesting | backtester, filters/ | ⬜ Not Audited | Filter ablation tests |
| 83 | `app/backtesting/results_writer.py` | — | Backtesting | — | ⬜ Not Audited | Results output |
| 84 | `app/backtesting/metrics.py` | — | Backtesting | — | ⬜ Not Audited | Backtest metrics |

### app/options/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 85 | `app/options/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 86 | `app/options/options_chain.py` | — | Options | tradier_client | ⬜ Not Audited | Options chain fetcher |
| 87 | `app/options/options_selector.py` | — | Options | options_chain, greeks_precheck | ⬜ Not Audited | Strike/expiry selection |
| 88 | `app/options/greeks_calculator.py` | — | Options | — | ⬜ Not Audited | Greeks computation |
| 89 | `app/options/iv_ranker.py` | — | Options | options_chain | ⬜ Not Audited | IV rank filter |

### app/ml/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 90 | `app/ml/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 91 | `app/ml/model_trainer.py` | — | ML | signals/, indicators/ | ⬜ Not Audited | ML model training |
| 92 | `app/ml/feature_builder.py` | — | ML | indicators/, signals/ | ⬜ Not Audited | Feature engineering |
| 93 | `app/ml/predictor.py` | — | ML | model_trainer | ⬜ Not Audited | Live ML predictions |

### app/mtf/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 94 | `app/mtf/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 95 | `app/mtf/mtf_analyzer.py` | — | MTF | indicators/, data_manager | ⬜ Not Audited | Multi-timeframe analysis |
| 96 | `app/mtf/htf_bias.py` | — | MTF | indicators/ | ⬜ Not Audited | Higher timeframe bias |
| 97 | `app/mtf/confluence_scorer.py` | — | MTF | mtf_analyzer, htf_bias | ⬜ Not Audited | MTF confluence scoring |

### app/ai/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 98 | `app/ai/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 99 | `app/ai/ai_signal_enhancer.py` | — | AI | signals/, analytics/ | ⬜ Not Audited | AI signal enhancement |
| 100 | `app/ai/pattern_classifier.py` | — | AI | indicators/ | ⬜ Not Audited | Pattern classification |

### app/futures/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 101 | `app/futures/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 102 | `app/futures/futures_feed.py` | — | Futures | data/, config | ⬜ Not Audited | Futures data feed |
| 103 | `app/futures/futures_bias.py` | — | Futures | futures_feed, indicators/ | ⬜ Not Audited | Futures market bias |

---

## utils/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 104 | `utils/__init__.py` | 22B | Init | — | ⬜ Not Audited | |
| 105 | `utils/config.py` | 19.5KB | Config | — | ⬜ Not Audited | **ROOT CONFIG — imported everywhere** |
| 106 | `utils/bar_utils.py` | 779B | Utility | — | ⬜ Not Audited | Bar/candle utilities |
| 107 | `utils/production_helpers.py` | 6KB | Utility | config | ⬜ Not Audited | Production helpers |
| 108 | `utils/time_helpers.py` | 1.7KB | Utility | — | ⬜ Not Audited | Time/timezone helpers |

---

## tests/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 109 | `tests/__init__.py` | 25B | Init | — | ⬜ Not Audited | |
| 110 | `tests/README.md` | 181B | Docs | — | ⬜ Not Audited | Test documentation |
| 111 | `tests/conftest.py` | 6.3KB | Tests | app/ modules | ⬜ Not Audited | Pytest fixtures |
| 112 | `tests/test_eod_reporter.py` | 9.9KB | Tests | signals/eod_reporter | ⬜ Not Audited | |
| 113 | `tests/test_failover.py` | 13.7KB | Tests | core/failover | ⬜ Not Audited | |
| 114 | `tests/test_funnel_analytics.py` | 5.5KB | Tests | analytics/funnel_analytics | ⬜ Not Audited | |
| 115 | `tests/test_integrations.py` | 7.3KB | Tests | multiple | ⬜ Not Audited | |
| 116 | `tests/test_mtf.py` | 7.1KB | Tests | mtf/ | ⬜ Not Audited | |
| 117 | `tests/test_signal_pipeline.py` | 28KB | Tests | signals/ pipeline | ⬜ Not Audited | **Largest test file** |
| 118 | `tests/test_smc_engine.py` | 24KB | Tests | signals/smc_engine | ⬜ Not Audited | |

---

## migrations/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 119 | `run_migration_006.py` (root) | — | Migration | ⬜ Not Audited | Should this be in migrations/? |
| 120+ | `migrations/*.py` | — | Migration | ⬜ Not Audited | DB schema migrations — need full crawl |

---

## scripts/

### scripts/ (root level)

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 121 | `scripts/README_ML_TRAINING.md` | 7.4KB | Docs | ⬜ Not Audited | ML training guide |
| 122 | `scripts/check_db.py` | 1.9KB | Debug | ⬜ Not Audited | DB check utility |
| 123 | `scripts/check_eodhd_intraday.py` | 3.4KB | Debug | ⬜ Not Audited | EODHD intraday check |
| 124 | `scripts/debug_bos_scan.py` | 3.5KB | Debug | ⬜ Not Audited | 🗑️ Debug script — review for removal |
| 125 | `scripts/debug_comprehensive.py` | 4.3KB | Debug | ⬜ Not Audited | 🗑️ Debug script — review for removal |
| 126 | `scripts/debug_db.py` | 1.3KB | Debug | ⬜ Not Audited | 🗑️ Debug script — review for removal |
| 127 | `scripts/deploy.ps1` | 2.2KB | DevOps | ⬜ Not Audited | PowerShell deploy script |
| 128 | `scripts/extract_positions_from_db.py` | 5.2KB | Utility | ⬜ Not Audited | DB extraction tool |
| 129 | `scripts/extract_signals_from_logs.py` | 2.7KB | Utility | ⬜ Not Audited | Log extraction tool |
| 130 | `scripts/fix_print_to_logger.py` | 10.2KB | Utility | ⬜ Not Audited | 🗑️ One-time fix — review for removal |
| 131 | `scripts/generate_backtest_intelligence.py` | 11.6KB | Backtesting | ⬜ Not Audited | Backtest intelligence gen |
| 132 | `scripts/generate_ml_training_data.py` | 16.5KB | ML | ⬜ Not Audited | ML training data gen |
| 133 | `scripts/system_health_check.py` | 15.5KB | Monitoring | ⬜ Not Audited | System health checker |

### scripts/subdirectories (need crawl)

| # | Directory | Audit Status | Notes |
|---|-----------|--------------|-------|
| 134 | `scripts/analysis/` | ⬜ Not Audited | Analysis scripts |
| 135 | `scripts/backtesting/` | ⬜ Not Audited | Backtest scripts |
| 136 | `scripts/database/` | ⬜ Not Audited | DB scripts |
| 137 | `scripts/maintenance/` | ⬜ Not Audited | Maintenance scripts |
| 138 | `scripts/ml/` | ⬜ Not Audited | ML scripts |
| 139 | `scripts/optimization/` | ⬜ Not Audited | Optimization scripts |
| 140 | `scripts/powershell/` | ⬜ Not Audited | PowerShell scripts |

---

## backtests/ (Data/Output — No Source Audit Needed)

### backtests/analysis/
| # | File | Size | Category | Notes |
|---|------|------|----------|-------|
| 141 | `backtests/analysis/feature_summary.csv` | 432B | 📦 Data | Feature summary output |
| 142 | `backtests/analysis/filter_candidates.txt` | 3.3KB | 📦 Data | Filter candidate list |
| 143 | `backtests/analysis/ticker_ranking.csv` | 826B | 📦 Data | Ticker ranking output |
| 144 | `backtests/analysis/trade_data.csv` | 21.5KB | 📦 Data | Trade data output |

### backtests/results/ (ticker output files)
> 📦 These are **generated output files**, not source code. They do not require source audit.
> Tickers present: AAOI, AAPL, AMD, AMZN, AVGO, AXTI, BAC, BOX, BP, CMCSA, CRM, FCX, FSLY, GLD, HYMC, LYB, MSFT, MSTR, NVDA, ORCL, OXY, PBF, PYPL, QQQ, SLB, SPY, TSLA, T, UNH, VG, WMT, XPEV
> File types per ticker: `_summary.json`, `_trades.csv`, `_walk_forward_folds.json`, `_YYYY-MM-DD.json`
> Aggregate files: `ablation_results.csv`, `aggregate_summary.json`, `hourly_win_rates.json`, `or_candle_grid.csv`, `or_candle_grid_trades.csv` (71KB), `or_range_grid.csv`

---

## docs/ (Need Crawl)

| # | Directory | Audit Status | Notes |
|---|-----------|--------------|-------|
| TBD | `docs/` | ⬜ Not Crawled | Documentation files — crawl next session |

---

## 🗑️ Removal Candidates (Flagged So Far)

| File | Reason |
|------|--------|
| `scripts/debug_bos_scan.py` | Debug/dev script — likely not needed in production |
| `scripts/debug_comprehensive.py` | Debug/dev script — likely not needed in production |
| `scripts/debug_db.py` | Debug/dev script — likely not needed in production |
| `scripts/fix_print_to_logger.py` | One-time refactor script — already applied? |
| `run_migration_006.py` (root) | One-off migration — should be in migrations/ or deleted post-run |

---

## 📋 Audit Session Log

| Date | Session | Files Audited | Notes |
|------|---------|---------------|-------|
| 2026-04-03 | Session 1 | 0 | Registry initialized — full file inventory complete |

---

## ⏭️ Next Steps

1. Crawl `scripts/analysis/`, `scripts/backtesting/`, `scripts/database/`, `scripts/maintenance/`, `scripts/ml/`, `scripts/optimization/`, `scripts/powershell/`
2. Crawl `migrations/` and `docs/`
3. Begin auditing `utils/config.py` first (imported by everything)
4. Audit `app/core/scanner.py` (central orchestrator)
5. Build exact import-level dependency map as audits complete
6. Mark removal candidates after confirming they are unused
