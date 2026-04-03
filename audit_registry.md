# War-Machine Audit Registry
> **Purpose:** Complete system map of every file in the repo. Track audit status, dependencies, and flag unnecessary files for removal.
> **Last Updated:** 2026-04-03
> **Legend:** ⬜ Not Audited | 🟡 In Progress | ✅ Audited | 🗑️ Candidate for Removal | 📦 Data/Output (no audit needed)

---

## Audit Progress Summary

| Category | Files | Audited | Status |
|----------|-------|---------|--------|
| app/ (all modules) | ~90 | 0 | ⬜ |
| utils/ | 5 | 0 | ⬜ |
| tests/ | 10 | 0 | ⬜ |
| migrations/ | 7 | 0 | ⬜ |
| scripts/ (all subdirs) | 47 | 0 | ⬜ |
| docs/ | 8 | 0 | ⬜ |
| backtests/results/ | ~80 | N/A | 📦 |
| backtests/analysis/ | 4 | N/A | 📦 |
| root | 13 | 0 | ⬜ |

---

## 🕸️ Dependency Spiderweb (Preliminary)

```
utils/config.py ─────────────────────────────────────────► ALL modules
utils/bar_utils.py ─────────────────────────────────────► indicators/, signals/
utils/time_helpers.py ──────────────────────────────────► core/, screening/

app/data/data_manager.py ──────────────────────────────► core/scanner.py
app/data/eodhd_client.py ──────────────────────────────► data_manager, screening/
app/data/tradier_client.py ────────────────────────────► options/, validation/greeks_precheck
app/data/ws_feed.py ───────────────────────────────────► core/scanner.py

app/indicators/ ────────────────────────────────────────► signals/, filters/, validation/
app/signals/ ───────────────────────────────────────────► validation/
app/validation/ ─────────────────────────────────────────► core/scanner.py
app/filters/ ───────────────────────────────────────────► validation/, signals/
app/screening/ ─────────────────────────────────────────► core/scanner.py
app/risk/ ──────────────────────────────────────────────► scanner.py, notifications/
app/notifications/ ──────────────────────────────────────► scanner.py
app/analytics/ ─────────────────────────────────────────► scanner.py, signals/
app/options/ ───────────────────────────────────────────► validation/greeks_precheck, tradier_client
app/ml/ ───────────────────────────────────────────────► signals/, indicators/
app/mtf/ ───────────────────────────────────────────────► indicators/, data_manager
app/ai/ ────────────────────────────────────────────────► signals/, analytics/
app/futures/ ───────────────────────────────────────────► data/, indicators/
app/backtesting/ ───────────────────────────────────────► signals/, validation/, data/
```

> ⚠️ Import-level dependency map will be filled in as each file is audited.

---

## ROOT FILES

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 1 | `.gitignore` | — | Config | ✅ Audited | Standard |
| 2 | `.railway_trigger` | — | Config | ⬜ Not Audited | Railway deploy trigger |
| 3 | `CODEBASE_DOCUMENTATION.md` | — | Docs | ⬜ Not Audited | May duplicate docs/ |
| 4 | `CONTEXT.md` | — | Docs | ⬜ Not Audited | Project context |
| 5 | `CONTRIBUTING.md` | — | Docs | ⬜ Not Audited | |
| 6 | `LICENSE` | — | Legal | ✅ Audited | |
| 7 | `README.md` | — | Docs | ⬜ Not Audited | |
| 8 | `REBUILD_PLAN.md` | — | Docs | 🗑️ Review | May be stale planning doc |
| 9 | `nixpacks.toml` | — | Config | ⬜ Not Audited | Railway build config |
| 10 | `pytest.ini` | — | Config | ⬜ Not Audited | |
| 11 | `railway.toml` | — | Config | ⬜ Not Audited | |
| 12 | `requirements.txt` | — | Config | ⬜ Not Audited | Python dependencies |
| 13 | `run_migration_006.py` | — | Migration | 🗑️ Review | One-off migration in wrong place; 006 SQL exists in migrations/ |

---

## app/

### app/core/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 14 | `app/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 15 | `app/core/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 16 | `app/core/scanner.py` | ~36KB | **Core Orchestrator** | data_manager, ws_feed, validation, screening, risk, notifications | ⬜ Not Audited | Central hub |
| 17 | `app/core/main.py` | — | Entry Point | scanner.py | ⬜ Not Audited | App entry |
| 18 | `app/core/scheduler.py` | — | Scheduler | scanner.py | ⬜ Not Audited | |
| 19 | `app/core/session_manager.py` | — | State | scanner.py | ⬜ Not Audited | |
| 20 | `app/core/health_monitor.py` | — | Monitoring | — | ⬜ Not Audited | |
| 21 | `app/core/failover.py` | — | Reliability | data_manager, ws_feed | ⬜ Not Audited | |

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
| 30 | `app/signals/bos_fvg_engine.py` | — | Signal | indicators/, config | ⬜ Not Audited | **CORE** |
| 31 | `app/signals/crt_engine.py` | — | Signal | indicators/, config | ⬜ Not Audited | |
| 32 | `app/signals/opening_range.py` | — | Signal | indicators/, config | ⬜ Not Audited | |
| 33 | `app/signals/signal_composer.py` | — | Signal | bos_fvg_engine, crt_engine, opening_range | ⬜ Not Audited | Signal aggregator |
| 34 | `app/signals/signal_store.py` | — | Signal | db_manager | ⬜ Not Audited | |
| 35 | `app/signals/eod_reporter.py` | — | Signal | signal_store, notifications | ⬜ Not Audited | |
| 36 | `app/signals/or_engine.py` | — | Signal | indicators/ | ⬜ Not Audited | OR engine variant |
| 37 | `app/signals/smc_engine.py` | — | Signal | indicators/, bos_fvg_engine | ⬜ Not Audited | **CORE** |

### app/validation/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 38 | `app/validation/__init__.py` | 1.4KB | Init | — | ⬜ Not Audited | |
| 39 | `app/validation/validation.py` | 23KB | **Validation** | cfw6_gate_validator, regime_filter, entry_timing | ⬜ Not Audited | Master validator |
| 40 | `app/validation/cfw6_gate_validator.py` | 18KB | Validation | indicators/, config | ⬜ Not Audited | CFW6 gate |
| 41 | `app/validation/cfw6_confirmation.py` | 13KB | Validation | cfw6_gate_validator | ⬜ Not Audited | |
| 42 | `app/validation/greeks_precheck.py` | 26KB | Validation | tradier_client, options/ | ⬜ Not Audited | Options Greeks filter |
| 43 | `app/validation/options_filter.py` | 17KB | Validation | greeks_precheck, tradier_client | ⬜ Not Audited | |
| 44 | `app/validation/regime_filter.py` | 10KB | Validation | indicators/ | ⬜ Not Audited | |
| 45 | `app/validation/entry_timing.py` | 10KB | Validation | indicators/, config | ⬜ Not Audited | |
| 46 | `app/validation/hourly_gate.py` | 6KB | Validation | config | ⬜ Not Audited | |

### app/filters/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 47 | `app/filters/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 48 | `app/filters/volume_filter.py` | — | Filter | indicators/, config | ⬜ Not Audited | |
| 49 | `app/filters/trend_filter.py` | — | Filter | indicators/ | ⬜ Not Audited | |
| 50 | `app/filters/news_filter.py` | — | Filter | config | ⬜ Not Audited | |
| 51 | `app/filters/gap_filter.py` | — | Filter | indicators/ | ⬜ Not Audited | |
| 52 | `app/filters/liquidity_filter.py` | — | Filter | indicators/ | ⬜ Not Audited | |

### app/indicators/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 53 | `app/indicators/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 54 | `app/indicators/atr.py` | — | Indicator | bar_utils | ⬜ Not Audited | |
| 55 | `app/indicators/vwap.py` | — | Indicator | bar_utils | ⬜ Not Audited | |
| 56 | `app/indicators/ema.py` | — | Indicator | bar_utils | ⬜ Not Audited | |
| 57 | `app/indicators/rsi.py` | — | Indicator | bar_utils | ⬜ Not Audited | |
| 58 | `app/indicators/macd.py` | — | Indicator | bar_utils | ⬜ Not Audited | |
| 59 | `app/indicators/bollinger.py` | — | Indicator | bar_utils | ⬜ Not Audited | |
| 60 | `app/indicators/swing_points.py` | — | Indicator | bar_utils | ⬜ Not Audited | |

### app/screening/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 61 | `app/screening/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 62 | `app/screening/universe_builder.py` | — | Screening | eodhd_client, config | ⬜ Not Audited | |
| 63 | `app/screening/premarket_screener.py` | — | Screening | eodhd_client, filters/ | ⬜ Not Audited | |
| 64 | `app/screening/gap_screener.py` | — | Screening | filters/gap_filter | ⬜ Not Audited | |
| 65 | `app/screening/watchlist_manager.py` | — | Screening | db_manager | ⬜ Not Audited | |

### app/risk/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 66 | `app/risk/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 67 | `app/risk/position_sizer.py` | — | Risk | config | ⬜ Not Audited | |
| 68 | `app/risk/risk_manager.py` | — | Risk | position_sizer, config | ⬜ Not Audited | **CORE** |
| 69 | `app/risk/stop_manager.py` | — | Risk | indicators/, config | ⬜ Not Audited | |
| 70 | `app/risk/drawdown_monitor.py` | — | Risk | db_manager | ⬜ Not Audited | |

### app/notifications/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 71 | `app/notifications/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 72 | `app/notifications/discord_notifier.py` | — | Notifications | config | ⬜ Not Audited | |
| 73 | `app/notifications/alert_manager.py` | — | Notifications | discord_notifier | ⬜ Not Audited | |
| 74 | `app/notifications/eod_summary.py` | — | Notifications | signal_store, db_manager | ⬜ Not Audited | |

### app/analytics/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 75 | `app/analytics/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 76 | `app/analytics/funnel_analytics.py` | — | Analytics | signal_store, db_manager | ⬜ Not Audited | |
| 77 | `app/analytics/performance_tracker.py` | — | Analytics | db_manager | ⬜ Not Audited | |
| 78 | `app/analytics/win_rate_analyzer.py` | — | Analytics | db_manager | ⬜ Not Audited | |

### app/backtesting/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 79 | `app/backtesting/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 80 | `app/backtesting/backtester.py` | — | Backtesting | signals/, validation/, data/ | ⬜ Not Audited | |
| 81 | `app/backtesting/walk_forward.py` | — | Backtesting | backtester | ⬜ Not Audited | |
| 82 | `app/backtesting/ablation_tester.py` | — | Backtesting | backtester, filters/ | ⬜ Not Audited | |
| 83 | `app/backtesting/results_writer.py` | — | Backtesting | — | ⬜ Not Audited | |
| 84 | `app/backtesting/metrics.py` | — | Backtesting | — | ⬜ Not Audited | |

### app/options/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 85 | `app/options/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 86 | `app/options/options_chain.py` | — | Options | tradier_client | ⬜ Not Audited | |
| 87 | `app/options/options_selector.py` | — | Options | options_chain, greeks_precheck | ⬜ Not Audited | |
| 88 | `app/options/greeks_calculator.py` | — | Options | — | ⬜ Not Audited | |
| 89 | `app/options/iv_ranker.py` | — | Options | options_chain | ⬜ Not Audited | |

### app/ml/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 90 | `app/ml/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 91 | `app/ml/model_trainer.py` | — | ML | signals/, indicators/ | ⬜ Not Audited | |
| 92 | `app/ml/feature_builder.py` | — | ML | indicators/, signals/ | ⬜ Not Audited | |
| 93 | `app/ml/predictor.py` | — | ML | model_trainer | ⬜ Not Audited | |

### app/mtf/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 94 | `app/mtf/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 95 | `app/mtf/mtf_analyzer.py` | — | MTF | indicators/, data_manager | ⬜ Not Audited | |
| 96 | `app/mtf/htf_bias.py` | — | MTF | indicators/ | ⬜ Not Audited | |
| 97 | `app/mtf/confluence_scorer.py` | — | MTF | mtf_analyzer, htf_bias | ⬜ Not Audited | |

### app/ai/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 98 | `app/ai/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 99 | `app/ai/ai_signal_enhancer.py` | — | AI | signals/, analytics/ | ⬜ Not Audited | |
| 100 | `app/ai/pattern_classifier.py` | — | AI | indicators/ | ⬜ Not Audited | |

### app/futures/

| # | File | Size | Category | Depends On | Audit Status | Notes |
|---|------|------|----------|------------|--------------|-------|
| 101 | `app/futures/__init__.py` | — | Init | — | ⬜ Not Audited | |
| 102 | `app/futures/futures_feed.py` | — | Futures | data/, config | ⬜ Not Audited | |
| 103 | `app/futures/futures_bias.py` | — | Futures | futures_feed, indicators/ | ⬜ Not Audited | |

---

## utils/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 104 | `utils/__init__.py` | 22B | Init | ⬜ Not Audited | |
| 105 | `utils/config.py` | 19.5KB | **Root Config** | ⬜ Not Audited | Imported by ALL modules — **audit first** |
| 106 | `utils/bar_utils.py` | 779B | Utility | ⬜ Not Audited | |
| 107 | `utils/production_helpers.py` | 6KB | Utility | ⬜ Not Audited | |
| 108 | `utils/time_helpers.py` | 1.7KB | Utility | ⬜ Not Audited | |

---

## tests/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 109 | `tests/__init__.py` | 25B | Init | ⬜ Not Audited | |
| 110 | `tests/README.md` | 181B | Docs | ⬜ Not Audited | |
| 111 | `tests/conftest.py` | 6.3KB | Tests | ⬜ Not Audited | Pytest fixtures |
| 112 | `tests/test_eod_reporter.py` | 9.9KB | Tests | ⬜ Not Audited | |
| 113 | `tests/test_failover.py` | 13.7KB | Tests | ⬜ Not Audited | |
| 114 | `tests/test_funnel_analytics.py` | 5.5KB | Tests | ⬜ Not Audited | |
| 115 | `tests/test_integrations.py` | 7.3KB | Tests | ⬜ Not Audited | |
| 116 | `tests/test_mtf.py` | 7.1KB | Tests | ⬜ Not Audited | |
| 117 | `tests/test_signal_pipeline.py` | 28KB | Tests | ⬜ Not Audited | Largest test |
| 118 | `tests/test_smc_engine.py` | 24KB | Tests | ⬜ Not Audited | |

---

## migrations/

> ⚠️ Migrations 003 and 004 are missing from the folder. Verify they were applied and intentionally omitted or were never created.

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 119 | `migrations/001_candle_cache.sql` | 1.2KB | Migration | ⬜ Not Audited | |
| 120 | `migrations/002_signal_persist_tables.sql` | 1.4KB | Migration | ⬜ Not Audited | |
| 121 | `migrations/005_ml_feature_columns.sql` | 1.5KB | Migration | ⬜ Not Audited | |
| 122 | `migrations/006_futures_signals.sql` | 2KB | Migration | ⬜ Not Audited | |
| 123 | `migrations/007_armed_signals_be_price.sql` | 344B | Migration | ⬜ Not Audited | |
| 124 | `migrations/add_dte_tracking_columns.sql` | 824B | Migration | 🗑️ Review | Not numbered — applied? |
| 125 | `migrations/signal_outcomes_schema.sql` | 3.4KB | Migration | 🗑️ Review | Not numbered — applied? |

---

## scripts/

### scripts/ (root level)

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 126 | `scripts/README_ML_TRAINING.md` | 7.4KB | Docs | ⬜ Not Audited | |
| 127 | `scripts/check_db.py` | 1.9KB | Debug | 🗑️ Review | Superseded by scripts/database/ |
| 128 | `scripts/check_eodhd_intraday.py` | 3.4KB | Debug | 🗑️ Review | One-off check |
| 129 | `scripts/debug_bos_scan.py` | 3.5KB | Debug | 🗑️ Remove | Debug script |
| 130 | `scripts/debug_comprehensive.py` | 4.3KB | Debug | 🗑️ Remove | Debug script |
| 131 | `scripts/debug_db.py` | 1.3KB | Debug | 🗑️ Remove | Debug script |
| 132 | `scripts/deploy.ps1` | 2.2KB | DevOps | ⬜ Not Audited | May duplicate scripts/powershell/ |
| 133 | `scripts/extract_positions_from_db.py` | 5.2KB | Utility | ⬜ Not Audited | |
| 134 | `scripts/extract_signals_from_logs.py` | 2.7KB | Utility | ⬜ Not Audited | |
| 135 | `scripts/fix_print_to_logger.py` | 10.2KB | Utility | 🗑️ Remove | One-time refactor script |
| 136 | `scripts/generate_backtest_intelligence.py` | 11.6KB | Backtesting | ⬜ Not Audited | |
| 137 | `scripts/generate_ml_training_data.py` | 16.5KB | ML | ⬜ Not Audited | |
| 138 | `scripts/system_health_check.py` | 15.5KB | Monitoring | ⬜ Not Audited | |

### scripts/analysis/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 139 | `scripts/analysis/analyze_ml_training_data.py` | 10KB | Analysis | ⬜ Not Audited | |
| 140 | `scripts/analysis/analyze_signal_failures.py` | 7.7KB | Analysis | ⬜ Not Audited | |
| 141 | `scripts/analysis/atr_check.py` | 1.2KB | Debug | 🗑️ Review | Tiny debug script |
| 142 | `scripts/analysis/entry_times.py` | 2.3KB | Analysis | ⬜ Not Audited | |
| 143 | `scripts/analysis/inspect_candles.py` | 485B | Debug | 🗑️ Review | Very small debug script |
| 144 | `scripts/analysis/inspect_signal_outcomes.py` | 6.7KB | Analysis | ⬜ Not Audited | |
| 145 | `scripts/analysis/metric_scan.py` | 3.2KB | Analysis | ⬜ Not Audited | |
| 146 | `scripts/analysis/or_timing_analysis.py` | 19.4KB | Analysis | ⬜ Not Audited | Large — keep |

### scripts/backtesting/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 147 | `scripts/backtesting/analyze_losers.py` | 13.6KB | Backtesting | ⬜ Not Audited | |
| 148 | `scripts/backtesting/analyze_signal_patterns.py` | 14.7KB | Backtesting | ⬜ Not Audited | |
| 149 | `scripts/backtesting/analyze_trades.py` | 9.4KB | Backtesting | ⬜ Not Audited | |
| 150 | `scripts/backtesting/backtest_optimized_params.py` | 30.5KB | Backtesting | ⬜ Not Audited | Large |
| 151 | `scripts/backtesting/backtest_sweep.py` | 10.3KB | Backtesting | ⬜ Not Audited | |
| 152 | `scripts/backtesting/debug_fvg.py` | 2.4KB | Debug | 🗑️ Review | Debug script |
| 153 | `scripts/backtesting/extract_candles_from_db.py` | 8.4KB | Utility | ⬜ Not Audited | |
| 154 | `scripts/backtesting/filter_ablation.py` | 9.1KB | Backtesting | ⬜ Not Audited | |
| 155 | `scripts/backtesting/or_range_candle_grid.py` | 21.7KB | Backtesting | ⬜ Not Audited | |
| 156 | `scripts/backtesting/or_range_grid.py` | 8.5KB | Backtesting | ⬜ Not Audited | |
| 157 | `scripts/backtesting/probe_db.py` | 2.8KB | Debug | 🗑️ Review | Debug script |
| 158 | `scripts/backtesting/production_indicator_backtest.py` | 15.5KB | Backtesting | ⬜ Not Audited | |
| 159 | `scripts/backtesting/run_full_dte_backtest.py` | 3.2KB | Backtesting | ⬜ Not Audited | |
| 160 | `scripts/backtesting/simulate_from_candles.py` | 16.2KB | Backtesting | ⬜ Not Audited | |
| 161 | `scripts/backtesting/test_dte_logic.py` | 7.7KB | Debug/Test | 🗑️ Review | Test script outside tests/ |
| 162 | `scripts/backtesting/unified_production_backtest.py` | 36.3KB | Backtesting | ⬜ Not Audited | **Largest backtest script** |
| 163 | `scripts/backtesting/update_hourly_win_rates.py` | 9.5KB | Backtesting | ⬜ Not Audited | |
| 164 | `scripts/backtesting/walk_forward_backtest.py` | 39.6KB | Backtesting | ⬜ Not Audited | **Largest script in repo** |

### scripts/backtesting/campaign/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 165 | `scripts/backtesting/campaign/README.md` | 3KB | Docs | ⬜ Not Audited | Campaign pipeline docs |
| 166 | `scripts/backtesting/campaign/00_export_from_railway.py` | 12.7KB | Campaign | ⬜ Not Audited | Step 0: Railway export |
| 167 | `scripts/backtesting/campaign/00b_backfill_eodhd.py` | 12.2KB | Campaign | ⬜ Not Audited | Step 0b: EODHD backfill |
| 168 | `scripts/backtesting/campaign/01_fetch_candles.py` | 6.5KB | Campaign | ⬜ Not Audited | Step 1: Fetch candles |
| 169 | `scripts/backtesting/campaign/02_run_campaign.py` | 17.9KB | Campaign | ⬜ Not Audited | Step 2: Run campaign |
| 170 | `scripts/backtesting/campaign/03_analyze_results.py` | 7.3KB | Campaign | ⬜ Not Audited | Step 3: Analyze results |
| 171 | `scripts/backtesting/campaign/probe_railway.py` | 2.5KB | Debug | 🗑️ Review | Debug probe |

### scripts/database/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 172 | `scripts/database/backfill_history.py` | 5.3KB | Database | ⬜ Not Audited | |
| 173 | `scripts/database/check_database.py` | 1.7KB | Debug | 🗑️ Review | Superseded by db_diagnostic? |
| 174 | `scripts/database/create_daily_technicals.sql` | 758B | Database | ⬜ Not Audited | Schema creation |
| 175 | `scripts/database/db_diagnostic.py` | 3.6KB | Database | ⬜ Not Audited | |
| 176 | `scripts/database/inspect_database_schema.py` | 5KB | Database | ⬜ Not Audited | |
| 177 | `scripts/database/inspect_tables.py` | 742B | Debug | 🗑️ Review | Tiny, likely superseded |
| 178 | `scripts/database/list_tables.py` | 290B | Debug | 🗑️ Review | Very tiny, likely superseded |
| 179 | `scripts/database/load_historical_data.py` | 15KB | Database | ⬜ Not Audited | |
| 180 | `scripts/database/setup_database.py` | 1.5KB | Database | ⬜ Not Audited | |

### scripts/maintenance/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 181 | `scripts/maintenance/update_sniper_greeks.py` | 4KB | Maintenance | ⬜ Not Audited | |

### scripts/ml/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 182 | `scripts/ml/train_from_analytics.py` | 6.4KB | ML | ⬜ Not Audited | |
| 183 | `scripts/ml/train_historical.py` | 5.5KB | ML | ⬜ Not Audited | |
| 184 | `scripts/ml/train_ml_booster.py` | 6.3KB | ML | ⬜ Not Audited | |

### scripts/optimization/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 185 | `scripts/optimization/smart_optimization.py` | 26.1KB | Optimization | ⬜ Not Audited | |

### scripts/powershell/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 186 | `scripts/powershell/dependency_analyzer.ps1` | 4.9KB | DevOps | ⬜ Not Audited | |
| 187 | `scripts/powershell/restore_and_deploy.ps1` | 830B | DevOps | 🗑️ Review | Very small — may overlap scripts/deploy.ps1 |

---

## docs/

> ⚠️ `docs/AUDIT_REGISTRY.md` (41KB) already exists. Evaluate if it should replace or merge with this file.

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 188 | `docs/ARCHITECTURE.md` | 10.7KB | Docs | ⬜ Not Audited | Architecture overview |
| 189 | `docs/AUDIT_REGISTRY.md` | 41KB | Docs | 🗑️ Review | **Pre-existing registry — merge or replace with this file** |
| 190 | `docs/BACKTEST_INTELLIGENCE.md` | 5.7KB | Docs | ⬜ Not Audited | |
| 191 | `docs/CHANGELOG.md` | 21.4KB | Docs | ⬜ Not Audited | |
| 192 | `docs/DISCORD_SIGNALS.md` | 6.7KB | Docs | ⬜ Not Audited | |
| 193 | `docs/FEATURES.md` | 9.9KB | Docs | ⬜ Not Audited | |
| 194 | `docs/INTEGRATION_GUIDE.md` | 9KB | Docs | ⬜ Not Audited | |
| 195 | `docs/README.md` | 17.8KB | Docs | ⬜ Not Audited | |

---

## backtests/ (Data/Output — No Source Audit Needed)

### backtests/analysis/
| # | File | Size | Status |
|---|------|------|--------|
| 196 | `backtests/analysis/feature_summary.csv` | 432B | 📦 Data |
| 197 | `backtests/analysis/filter_candidates.txt` | 3.3KB | 📦 Data |
| 198 | `backtests/analysis/ticker_ranking.csv` | 826B | 📦 Data |
| 199 | `backtests/analysis/trade_data.csv` | 21.5KB | 📦 Data |

### backtests/results/
> 📦 **Generated output files — no source audit needed.**
> Per-ticker files: `_summary.json`, `_trades.csv`, `_walk_forward_folds.json`, `_YYYY-MM-DD.json`
> Tickers: AAOI, AAPL, AMD, AMZN, AVGO, AXTI, BAC, BOX, BP, CMCSA, CRM, FCX, FSLY, GLD, HYMC, LYB, MSFT, MSTR, NVDA, ORCL, OXY, PBF, PYPL, QQQ, SLB, SPY, TSLA, T, UNH, VG, WMT, XPEV
> Aggregate files: `ablation_results.csv`, `aggregate_summary.json`, `hourly_win_rates.json`, `or_candle_grid.csv`, `or_candle_grid_trades.csv` (71KB), `or_range_grid.csv`

---

## 🗑️ Removal Candidates (All Flagged)

| File | Size | Reason |
|------|------|--------|
| `scripts/debug_bos_scan.py` | 3.5KB | Dev debug script |
| `scripts/debug_comprehensive.py` | 4.3KB | Dev debug script |
| `scripts/debug_db.py` | 1.3KB | Dev debug script |
| `scripts/fix_print_to_logger.py` | 10.2KB | One-time refactor, already applied |
| `run_migration_006.py` (root) | — | One-off migration; 006 SQL is in migrations/ |
| `scripts/check_db.py` | 1.9KB | Likely superseded by scripts/database/ |
| `scripts/check_eodhd_intraday.py` | 3.4KB | One-off check |
| `scripts/analysis/atr_check.py` | 1.2KB | Tiny debug script |
| `scripts/analysis/inspect_candles.py` | 485B | Very tiny debug script |
| `scripts/backtesting/debug_fvg.py` | 2.4KB | Debug script |
| `scripts/backtesting/probe_db.py` | 2.8KB | Debug script |
| `scripts/backtesting/test_dte_logic.py` | 7.7KB | Test outside tests/ — move or delete |
| `scripts/backtesting/campaign/probe_railway.py` | 2.5KB | Debug probe |
| `scripts/database/check_database.py` | 1.7KB | Likely superseded by db_diagnostic.py |
| `scripts/database/inspect_tables.py` | 742B | Tiny, likely superseded |
| `scripts/database/list_tables.py` | 290B | Very tiny, likely superseded |
| `scripts/powershell/restore_and_deploy.ps1` | 830B | Possible overlap with scripts/deploy.ps1 |
| `migrations/add_dte_tracking_columns.sql` | 824B | Not numbered — verify applied |
| `migrations/signal_outcomes_schema.sql` | 3.4KB | Not numbered — verify applied |
| `docs/AUDIT_REGISTRY.md` | 41KB | Pre-existing registry — merge into this file or delete |
| `REBUILD_PLAN.md` (root) | — | Stale planning doc |

---

## 📋 Audit Session Log

| Date | Session | Files Audited | Notes |
|------|---------|---------------|-------|
| 2026-04-03 | Session 1 | 0 | Full inventory complete — all 195+ files catalogued |

---

## ⏭️ Recommended Audit Order

1. **`utils/config.py`** — imported by everything; understand this first
2. **`app/core/scanner.py`** — central orchestrator
3. **`app/data/`** — data_manager, ws_feed, eodhd_client, tradier_client
4. **`app/indicators/`** — foundation for signals and validation
5. **`app/signals/`** — bos_fvg_engine, smc_engine, signal_composer
6. **`app/validation/`** — validation.py, cfw6_gate_validator, greeks_precheck
7. **`app/filters/`**, **`app/screening/`**, **`app/risk/`**
8. Remaining app/ modules
9. Tests, scripts (confirm which are still needed)
10. **Execute removals** on all 🗑️ flagged files after confirming unused
