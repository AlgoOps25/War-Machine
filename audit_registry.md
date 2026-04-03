# War-Machine Audit Registry
> **Purpose:** Complete system map of every source file in the repo. Track audit status, dependencies, and flag stale/unnecessary files.
> **Last Updated:** 2026-04-03
> **Source:** Verified against local `C:\Dev\War-Machine` file tree
> **Legend:** ⬜ Not Audited | 🟡 In Progress | ✅ Audited | 🗑️ Candidate for Removal | 📦 Data/Output (no audit needed)

---

## Audit Progress Summary

| Module | Files | Audited | Removal Candidates |
|--------|-------|---------|--------------------|
| app/ai | 2 | 0 | 0 |
| app/analytics | 10 | 0 | 2 |
| app/backtesting | 7 | 0 | 0 |
| app/core | 15 | 0 | 0 |
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
| utils | 5 | 0 | 0 |
| tests | 10 | 0 | 0 |
| migrations | 7 | 0 | 2 |
| scripts (all) | 64 | 0 | 15 |
| docs | 8 | 0 | 1 |
| root files | 18 | 0 | 4 |
| **TOTAL** | **235** | **0** | **25** |

> ⚠️ **Not tracked in source audit:** `backtests/results/` (output data), `backtests/analysis/` (output CSVs), `scripts/backtesting/campaign/*.db`, `.venv/`, `.pytest_cache/`, `__pycache__/`, `.env`, `*.log`, `*.db` (runtime), `*.pyc`

---

## 🕸️ Dependency Spiderweb (Preliminary)

```
utils/config.py ─────────────────────────────────────────► ALL modules
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

> ⚠️ Full import-level map populated as each file is audited.

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
| 48 | `app/core/scanner.py` | **Core Orchestrator** | ⬜ Not Audited | Central hub — audit 2nd |
| 49 | `app/core/signal_scorecard.py` | Core | ⬜ Not Audited | |
| 50 | `app/core/sniper.py` | Core | ⬜ Not Audited | **CORE** Sniper entry/execution |
| 51 | `app/core/sniper_log.py` | Core | ⬜ Not Audited | Sniper trade log |
| 52 | `app/core/sniper_pipeline.py` | Core | ⬜ Not Audited | **CORE** Sniper pipeline |
| 53 | `app/core/thread_safe_state.py` | Core | ⬜ Not Audited | Thread-safe shared state |
| 54 | `app/core/watch_signal_store.py` | Core | ⬜ Not Audited | Watch-mode signal store |

### app/data/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 55 | `app/data/__init__.py` | Init | ⬜ Not Audited | |
| 56 | `app/data/candle_cache.py` | Data | ⬜ Not Audited | In-memory candle cache |
| 57 | `app/data/data_manager.py` | Data | ⬜ Not Audited | **CORE** Central data hub |
| 58 | `app/data/database.py` | Data | ⬜ Not Audited | DB abstraction layer |
| 59 | `app/data/db_connection.py` | Data | ⬜ Not Audited | PostgreSQL connection pool |
| 60 | `app/data/intraday_atr.py` | Data | ⬜ Not Audited | Intraday ATR computation |
| 61 | `app/data/sql_safe.py` | Data | ⬜ Not Audited | SQL injection helpers |
| 62 | `app/data/unusual_options.py` | Data | ⬜ Not Audited | Unusual options data feed |
| 63 | `app/data/ws_feed.py` | Data | ⬜ Not Audited | WebSocket market feed |
| 64 | `app/data/ws_quote_feed.py` | Data | ⬜ Not Audited | Quote-level WS feed |

### app/filters/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 65 | `app/filters/__init__.py` | Init | ⬜ Not Audited | |
| 66 | `app/filters/correlation.py` | Filter | ⬜ Not Audited | |
| 67 | `app/filters/dead_zone_suppressor.py` | Filter | ⬜ Not Audited | |
| 68 | `app/filters/early_session_disqualifier.py` | Filter | ⬜ Not Audited | |
| 69 | `app/filters/gex_pin_gate.py` | Filter | ⬜ Not Audited | GEX pin suppression |
| 70 | `app/filters/liquidity_sweep.py` | Filter | ⬜ Not Audited | |
| 71 | `app/filters/market_regime_context.py` | Filter | ⬜ Not Audited | |
| 72 | `app/filters/mtf_bias.py` | Filter | ⬜ Not Audited | MTF bias filter |
| 73 | `app/filters/order_block_cache.py` | Filter | ⬜ Not Audited | OB zone cache |
| 74 | `app/filters/rth_filter.py` | Filter | ⬜ Not Audited | RTH session gating |
| 75 | `app/filters/sd_zone_confluence.py` | Filter | ⬜ Not Audited | S/D zone confluence |
| 76 | `app/filters/vwap_gate.py` | Filter | ⬜ Not Audited | VWAP gate filter |

### app/futures/

| # | File | Size | Category | Audit Status | Notes |
|---|------|------|----------|--------------|-------|
| 77 | `app/futures/__init__.py` | 579B | Init | ⬜ Not Audited | |
| 78 | `app/futures/futures_orb_scanner.py` | 24.4KB | Futures | ⬜ Not Audited | **Largest futures file** |
| 79 | `app/futures/futures_position_monitor.py` | 13.2KB | Futures | ⬜ Not Audited | |
| 80 | `app/futures/futures_scanner_loop.py` | 3.8KB | Futures | ⬜ Not Audited | |
| 81 | `app/futures/tradier_futures_feed.py` | 9.8KB | Futures | ⬜ Not Audited | Tradier futures feed |

### app/indicators/

> ⚠️ No `__init__.py` found on disk — confirm this is intentional.

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 82 | `app/indicators/technical_indicators.py` | Indicator | ⬜ Not Audited | **CORE** |
| 83 | `app/indicators/technical_indicators_extended.py` | Indicator | ⬜ Not Audited | Extended indicator set |
| 84 | `app/indicators/volume_indicators.py` | Indicator | ⬜ Not Audited | |
| 85 | `app/indicators/vwap_calculator.py` | Indicator | ⬜ Not Audited | |

### app/ml/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 86 | `app/ml/__init__.py` | Init | ⬜ Not Audited | |
| 87 | `app/ml/INTEGRATION.md` | Docs | ⬜ Not Audited | ML integration notes |
| 88 | `app/ml/metrics_cache.py` | ML | ⬜ Not Audited | |
| 89 | `app/ml/ml_confidence_boost.py` | ML | ⬜ Not Audited | |
| 90 | `app/ml/ml_signal_scorer_v2.py` | ML | ⬜ Not Audited | **CORE** ML scorer |
| 91 | `app/ml/ml_trainer.py` | ML | ⬜ Not Audited | |
| 92 | `app/ml/README.md` | Docs | ⬜ Not Audited | |

### app/mtf/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 93 | `app/mtf/__init__.py` | Init | ⬜ Not Audited | |
| 94 | `app/mtf/bos_fvg_engine.py` | MTF | ⬜ Not Audited | **CORE** BOS/FVG detection |
| 95 | `app/mtf/mtf_compression.py` | MTF | ⬜ Not Audited | Bar compression |
| 96 | `app/mtf/mtf_fvg_priority.py` | MTF | ⬜ Not Audited | FVG priority scoring |
| 97 | `app/mtf/mtf_integration.py` | MTF | ⬜ Not Audited | MTF pipeline integration |
| 98 | `app/mtf/mtf_validator.py` | MTF | ⬜ Not Audited | |
| 99 | `app/mtf/smc_engine.py` | MTF | ⬜ Not Audited | **CORE** SMC engine |

### app/notifications/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 100 | `app/notifications/__init__.py` | Init | ⬜ Not Audited | |
| 101 | `app/notifications/annotation_bot.py` | Notifications | ⬜ Not Audited | Discord annotation |
| 102 | `app/notifications/discord_helpers.py` | Notifications | ⬜ Not Audited | Discord message helpers |

### app/options/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 103 | `app/options/__init__.py` | Init | ⬜ Not Audited | |
| 104 | `app/options/dte_historical_advisor.py` | Options | ⬜ Not Audited | DTE selection advisor |
| 105 | `app/options/gex_engine.py` | Options | ⬜ Not Audited | GEX computation |
| 106 | `app/options/iv_tracker.py` | Options | ⬜ Not Audited | IV tracking |
| 107 | `app/options/options_data_manager.py` | Options | ⬜ Not Audited | Options data layer |
| 108 | `app/options/options_dte_selector.py` | Options | ⬜ Not Audited | DTE selection logic |
| 109 | `app/options/options_intelligence.py` | Options | ⬜ Not Audited | Options signal intelligence |

### app/risk/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 110 | `app/risk/__init__.py` | Init | ⬜ Not Audited | |
| 111 | `app/risk/dynamic_thresholds.py` | Risk | ⬜ Not Audited | Adaptive thresholds |
| 112 | `app/risk/position_helpers.py` | Risk | ⬜ Not Audited | |
| 113 | `app/risk/position_manager.py` | Risk | ⬜ Not Audited | **CORE** |
| 114 | `app/risk/risk_manager.py` | Risk | ⬜ Not Audited | **CORE** |
| 115 | `app/risk/trade_calculator.py` | Risk | ⬜ Not Audited | Trade sizing |
| 116 | `app/risk/vix_sizing.py` | Risk | ⬜ Not Audited | VIX-based position sizing |

### app/screening/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 117 | `app/screening/__init__.py` | Init | ⬜ Not Audited | |
| 118 | `app/screening/dynamic_screener.py` | Screening | ⬜ Not Audited | |
| 119 | `app/screening/gap_analyzer.py` | Screening | ⬜ Not Audited | |
| 120 | `app/screening/market_calendar.py` | Screening | ⬜ Not Audited | Market holiday calendar |
| 121 | `app/screening/news_catalyst.py` | Screening | ⬜ Not Audited | |
| 122 | `app/screening/premarket_scanner.py` | Screening | ⬜ Not Audited | |
| 123 | `app/screening/volume_analyzer.py` | Screening | ⬜ Not Audited | |
| 124 | `app/screening/watchlist_funnel.py` | Screening | ⬜ Not Audited | **CORE** Watchlist funnel |

### app/signals/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 125 | `app/signals/__init__.py` | Init | ⬜ Not Audited | |
| 126 | `app/signals/annotation_resolver.py` | Signal | ⬜ Not Audited | |
| 127 | `app/signals/breakout_detector.py` | Signal | ⬜ Not Audited | |
| 128 | `app/signals/opening_range.py` | Signal | ⬜ Not Audited | **CORE** OR signal logic |
| 129 | `app/signals/signal_analytics.py` | Signal | ⬜ Not Audited | |
| 130 | `app/signals/vwap_reclaim.py` | Signal | ⬜ Not Audited | |

### app/validation/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 131 | `app/validation/__init__.py` | Init | ⬜ Not Audited | |
| 132 | `app/validation/cfw6_confirmation.py` | Validation | ⬜ Not Audited | |
| 133 | `app/validation/cfw6_gate_validator.py` | Validation | ⬜ Not Audited | **CORE** CFW6 gate |
| 134 | `app/validation/entry_timing.py` | Validation | ⬜ Not Audited | |
| 135 | `app/validation/entry_timing.py.bak` | Backup | 🗑️ Remove | Backup file — delete |
| 136 | `app/validation/greeks_precheck.py` | Validation | ⬜ Not Audited | **CORE** Options Greeks filter |
| 137 | `app/validation/hourly_gate.py` | Validation | ⬜ Not Audited | |
| 138 | `app/validation/options_filter.py` | Validation | ⬜ Not Audited | |
| 139 | `app/validation/regime_filter.py` | Validation | ⬜ Not Audited | |
| 140 | `app/validation/validation.py` | Validation | ⬜ Not Audited | **CORE** Master validator |
| 141 | `app/validation/volume_profile.py` | Validation | ⬜ Not Audited | |

---

## utils/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 142 | `utils/__init__.py` | Init | ⬜ Not Audited | |
| 143 | `utils/bar_utils.py` | Utility | ⬜ Not Audited | Bar/candle helpers |
| 144 | `utils/config.py` | **Root Config** | ⬜ Not Audited | Imported by ALL modules — **audit first** |
| 145 | `utils/production_helpers.py` | Utility | ⬜ Not Audited | |
| 146 | `utils/time_helpers.py` | Utility | ⬜ Not Audited | |

---

## tests/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 147 | `tests/__init__.py` | Init | ⬜ Not Audited | |
| 148 | `tests/README.md` | Docs | ⬜ Not Audited | |
| 149 | `tests/conftest.py` | Tests | ⬜ Not Audited | Pytest fixtures |
| 150 | `tests/test_eod_reporter.py` | Tests | ⬜ Not Audited | |
| 151 | `tests/test_failover.py` | Tests | ⬜ Not Audited | |
| 152 | `tests/test_funnel_analytics.py` | Tests | ⬜ Not Audited | |
| 153 | `tests/test_integrations.py` | Tests | ⬜ Not Audited | |
| 154 | `tests/test_mtf.py` | Tests | ⬜ Not Audited | |
| 155 | `tests/test_signal_pipeline.py` | Tests | ⬜ Not Audited | Largest test file |
| 156 | `tests/test_smc_engine.py` | Tests | ⬜ Not Audited | |

---

## migrations/

> ⚠️ Migrations 003 and 004 are missing. Confirm they were applied and intentionally removed, or never existed.
> ⚠️ `add_dte_tracking_columns.sql` and `signal_outcomes_schema.sql` are unnumbered — verify they've been applied.

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 157 | `migrations/001_candle_cache.sql` | Migration | ⬜ Not Audited | |
| 158 | `migrations/002_signal_persist_tables.sql` | Migration | ⬜ Not Audited | |
| 159 | `migrations/005_ml_feature_columns.sql` | Migration | ⬜ Not Audited | |
| 160 | `migrations/006_futures_signals.sql` | Migration | ⬜ Not Audited | |
| 161 | `migrations/007_armed_signals_be_price.sql` | Migration | ⬜ Not Audited | |
| 162 | `migrations/add_dte_tracking_columns.sql` | Migration | 🗑️ Review | Unnumbered — verify applied |
| 163 | `migrations/signal_outcomes_schema.sql` | Migration | 🗑️ Review | Unnumbered — verify applied |

---

## docs/

> ⚠️ `docs/AUDIT_REGISTRY.md` (41KB) is a pre-existing registry. Evaluate merge vs. delete once this file is complete.

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 164 | `docs/ARCHITECTURE.md` | Docs | ⬜ Not Audited | |
| 165 | `docs/AUDIT_REGISTRY.md` | Docs | 🗑️ Review | Pre-existing registry — merge into root audit_registry.md |
| 166 | `docs/BACKTEST_INTELLIGENCE.md` | Docs | ⬜ Not Audited | |
| 167 | `docs/CHANGELOG.md` | Docs | ⬜ Not Audited | |
| 168 | `docs/DISCORD_SIGNALS.md` | Docs | ⬜ Not Audited | |
| 169 | `docs/FEATURES.md` | Docs | ⬜ Not Audited | |
| 170 | `docs/INTEGRATION_GUIDE.md` | Docs | ⬜ Not Audited | |
| 171 | `docs/README.md` | Docs | ⬜ Not Audited | |

---

## scripts/

### scripts/ (root level)

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 172 | `scripts/README_ML_TRAINING.md` | Docs | ⬜ Not Audited | |
| 173 | `scripts/check_db.py` | Debug | 🗑️ Remove | Superseded by scripts/database/ |
| 174 | `scripts/check_eodhd_intraday.py` | Debug | 🗑️ Remove | One-off check |
| 175 | `scripts/debug_bos_scan.py` | Debug | 🗑️ Remove | Dev debug script |
| 176 | `scripts/debug_comprehensive.py` | Debug | 🗑️ Remove | Dev debug script |
| 177 | `scripts/debug_db.py` | Debug | 🗑️ Remove | Dev debug script |
| 178 | `scripts/deploy.ps1` | DevOps | ⬜ Not Audited | May overlap scripts/powershell/ |
| 179 | `scripts/extract_positions_from_db.py` | Utility | ⬜ Not Audited | |
| 180 | `scripts/extract_signals_from_logs.py` | Utility | ⬜ Not Audited | |
| 181 | `scripts/fix_print_to_logger.py` | Utility | 🗑️ Remove | One-time refactor; already applied |
| 182 | `scripts/generate_backtest_intelligence.py` | Backtesting | ⬜ Not Audited | |
| 183 | `scripts/generate_ml_training_data.py` | ML | ⬜ Not Audited | |
| 184 | `scripts/system_health_check.py` | Monitoring | ⬜ Not Audited | |

### scripts/analysis/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 185 | `scripts/analysis/analyze_ml_training_data.py` | Analysis | ⬜ Not Audited | |
| 186 | `scripts/analysis/analyze_signal_failures.py` | Analysis | ⬜ Not Audited | |
| 187 | `scripts/analysis/atr_check.py` | Debug | 🗑️ Review | Tiny (1.2KB) debug script |
| 188 | `scripts/analysis/entry_times.py` | Analysis | ⬜ Not Audited | |
| 189 | `scripts/analysis/inspect_candles.py` | Debug | 🗑️ Review | Very tiny (485B) debug script |
| 190 | `scripts/analysis/inspect_signal_outcomes.py` | Analysis | ⬜ Not Audited | |
| 191 | `scripts/analysis/metric_scan.py` | Analysis | ⬜ Not Audited | |
| 192 | `scripts/analysis/or_timing_analysis.py` | Analysis | ⬜ Not Audited | Large (19.4KB) — keep |

### scripts/backtesting/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 193 | `scripts/backtesting/analyze_losers.py` | Backtesting | ⬜ Not Audited | |
| 194 | `scripts/backtesting/analyze_signal_patterns.py` | Backtesting | ⬜ Not Audited | |
| 195 | `scripts/backtesting/analyze_trades.py` | Backtesting | ⬜ Not Audited | |
| 196 | `scripts/backtesting/backtest_optimized_params.py` | Backtesting | ⬜ Not Audited | |
| 197 | `scripts/backtesting/backtest_sweep.py` | Backtesting | ⬜ Not Audited | |
| 198 | `scripts/backtesting/debug_fvg.py` | Debug | 🗑️ Remove | Dev debug script |
| 199 | `scripts/backtesting/extract_candles_from_db.py` | Utility | ⬜ Not Audited | |
| 200 | `scripts/backtesting/filter_ablation.py` | Backtesting | ⬜ Not Audited | |
| 201 | `scripts/backtesting/or_range_candle_grid.py` | Backtesting | ⬜ Not Audited | |
| 202 | `scripts/backtesting/or_range_grid.py` | Backtesting | ⬜ Not Audited | |
| 203 | `scripts/backtesting/probe_db.py` | Debug | 🗑️ Remove | Dev debug script |
| 204 | `scripts/backtesting/production_indicator_backtest.py` | Backtesting | ⬜ Not Audited | |
| 205 | `scripts/backtesting/run_full_dte_backtest.py` | Backtesting | ⬜ Not Audited | |
| 206 | `scripts/backtesting/simulate_from_candles.py` | Backtesting | ⬜ Not Audited | |
| 207 | `scripts/backtesting/test_dte_logic.py` | Debug/Test | 🗑️ Review | Test script outside tests/ — move or delete |
| 208 | `scripts/backtesting/unified_production_backtest.py` | Backtesting | ⬜ Not Audited | Large (36.3KB) |
| 209 | `scripts/backtesting/update_hourly_win_rates.py` | Backtesting | ⬜ Not Audited | |
| 210 | `scripts/backtesting/walk_forward_backtest.py` | Backtesting | ⬜ Not Audited | **Largest script (39.6KB)** |

### scripts/backtesting/campaign/

> 📦 `campaign_data.db` and `campaign_results.db` are runtime SQLite databases — not source files.

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 211 | `scripts/backtesting/campaign/README.md` | Docs | ⬜ Not Audited | Pipeline docs |
| 212 | `scripts/backtesting/campaign/00_export_from_railway.py` | Campaign | ⬜ Not Audited | Step 0 |
| 213 | `scripts/backtesting/campaign/00b_backfill_eodhd.py` | Campaign | ⬜ Not Audited | Step 0b |
| 214 | `scripts/backtesting/campaign/01_fetch_candles.py` | Campaign | ⬜ Not Audited | Step 1 |
| 215 | `scripts/backtesting/campaign/02_run_campaign.py` | Campaign | ⬜ Not Audited | Step 2 |
| 216 | `scripts/backtesting/campaign/03_analyze_results.py` | Campaign | ⬜ Not Audited | Step 3 |
| 217 | `scripts/backtesting/campaign/probe_railway.py` | Debug | 🗑️ Review | Debug probe |

### scripts/database/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 218 | `scripts/database/backfill_history.py` | Database | ⬜ Not Audited | |
| 219 | `scripts/database/check_database.py` | Debug | 🗑️ Review | Likely superseded by db_diagnostic.py |
| 220 | `scripts/database/create_daily_technicals.sql` | Database | ⬜ Not Audited | |
| 221 | `scripts/database/db_diagnostic.py` | Database | ⬜ Not Audited | |
| 222 | `scripts/database/inspect_database_schema.py` | Database | ⬜ Not Audited | |
| 223 | `scripts/database/inspect_tables.py` | Debug | 🗑️ Review | Tiny (742B) — superseded? |
| 224 | `scripts/database/list_tables.py` | Debug | 🗑️ Remove | Very tiny (290B) — superseded |
| 225 | `scripts/database/load_historical_data.py` | Database | ⬜ Not Audited | |
| 226 | `scripts/database/setup_database.py` | Database | ⬜ Not Audited | |

### scripts/maintenance/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 227 | `scripts/maintenance/update_sniper_greeks.py` | Maintenance | ⬜ Not Audited | |

### scripts/ml/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 228 | `scripts/ml/train_from_analytics.py` | ML | ⬜ Not Audited | |
| 229 | `scripts/ml/train_historical.py` | ML | ⬜ Not Audited | |
| 230 | `scripts/ml/train_ml_booster.py` | ML | ⬜ Not Audited | |

### scripts/optimization/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 231 | `scripts/optimization/smart_optimization.py` | Optimization | ⬜ Not Audited | Large (26.1KB) |

### scripts/powershell/

| # | File | Category | Audit Status | Notes |
|---|------|----------|--------------|-------|
| 232 | `scripts/powershell/dependency_analyzer.ps1` | DevOps | ⬜ Not Audited | |
| 233 | `scripts/powershell/restore_and_deploy.ps1` | DevOps | 🗑️ Review | Tiny (830B) — overlap with scripts/deploy.ps1? |

---

## backtests/ (Data/Output — No Audit Needed)

### backtests/analysis/
| File | Status |
|------|--------|
| `feature_summary.csv` | 📦 Data |
| `filter_candidates.txt` | 📦 Data |
| `ticker_ranking.csv` | 📦 Data |
| `trade_data.csv` | 📦 Data |

### backtests/results/
> 📦 **Generated output files — no source audit needed.**
> Per-ticker files: `_summary.json`, `_trades.csv`, `_walk_forward_folds.json`, `_YYYY-MM-DD.json`
> Tickers with daily files: AAPL, AMD, MSFT, NVDA, TSLA (2026-04-02, 2026-04-03)
> All other tickers: AAOI, AMZN, AVGO, AXTI, BAC, BOX, BP, CMCSA, CRM, FCX, FSLY, GLD, HYMC, LYB, MSTR, ORCL, OXY, PBF, PYPL, QQQ, SLB, SPY, T, UNH, VG, WMT, XPEV
> Aggregate files: `ablation_results.csv`, `aggregate_summary.json`, `hourly_win_rates.json`, `or_candle_grid.csv`, `or_candle_grid_trades.csv`, `or_range_grid.csv`

---

## 🗑️ Removal Candidates (All Flagged)

| File | Reason |
|------|--------|
| `run_migration_006.py` (root) | One-off migration runner; 006 SQL already in migrations/ |
| `REBUILD_PLAN.md` (root) | Stale planning doc |
| `app/validation/entry_timing.py.bak` | Backup file |
| `app/analytics/ab_test.py` | Likely duplicate of ab_test_framework.py |
| `app/analytics/explosive_mover_tracker.py` | Likely duplicate of explosive_tracker.py |
| `scripts/check_db.py` | Superseded by scripts/database/ |
| `scripts/check_eodhd_intraday.py` | One-off check |
| `scripts/debug_bos_scan.py` | Dev debug script |
| `scripts/debug_comprehensive.py` | Dev debug script |
| `scripts/debug_db.py` | Dev debug script |
| `scripts/fix_print_to_logger.py` | One-time refactor; already applied |
| `scripts/analysis/atr_check.py` | Tiny debug script |
| `scripts/analysis/inspect_candles.py` | Very tiny debug script |
| `scripts/backtesting/debug_fvg.py` | Debug script |
| `scripts/backtesting/probe_db.py` | Debug script |
| `scripts/backtesting/test_dte_logic.py` | Test outside tests/ — move or delete |
| `scripts/backtesting/campaign/probe_railway.py` | Debug probe |
| `scripts/database/check_database.py` | Likely superseded by db_diagnostic.py |
| `scripts/database/inspect_tables.py` | Tiny, likely superseded |
| `scripts/database/list_tables.py` | Very tiny (290B), superseded |
| `scripts/powershell/restore_and_deploy.ps1` | Possible overlap with scripts/deploy.ps1 |
| `migrations/add_dte_tracking_columns.sql` | Unnumbered — verify applied |
| `migrations/signal_outcomes_schema.sql` | Unnumbered — verify applied |
| `docs/AUDIT_REGISTRY.md` | Pre-existing registry — merge or delete |

---

## 📋 Audit Session Log

| Date | Session | Files Audited | Notes |
|------|---------|---------------|-------|
| 2026-04-03 | Session 1 | 0 | Full inventory complete — 235 source files catalogued from verified local tree |

---

## ⏭️ Recommended Audit Order

1. **`utils/config.py`** — imported by everything; understand config keys first
2. **`app/core/scanner.py`** — central orchestrator
3. **`app/data/`** — db_connection → database → data_manager → ws_feed, ws_quote_feed
4. **`app/indicators/`** — technical_indicators.py (foundation for signals/validation)
5. **`app/mtf/`** — bos_fvg_engine, smc_engine (core signal detection)
6. **`app/signals/`** — opening_range, breakout_detector
7. **`app/validation/`** — validation.py, cfw6_gate_validator, greeks_precheck
8. **`app/filters/`** — all gate/filter files
9. **`app/core/`** — sniper.py, sniper_pipeline.py, arm_signal.py
10. **`app/risk/`**, **`app/options/`**, **`app/screening/`**
11. **`app/analytics/`**, **`app/notifications/`**, **`app/futures/`**
12. **`app/ml/`**, **`app/backtesting/`**, **`app/ai/`**
13. Tests — validate coverage matches audited modules
14. **Execute removals** on all 🗑️ flagged files after confirming unused
