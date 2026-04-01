# War Machine — Master Audit Registry

> **Purpose:** Single source of truth for every file-by-file, line-by-line audit session.
> Every finding, fix, and status change is recorded here chronologically — never delete entries.
> Updated after **every commit** — no exceptions.
>
> **Last updated:** 2026-04-01 — S27: `migrations/` complete. BUG-DTC-1 (broken Python migration) fixed.
> Next: `app/backtesting/` (Phase 6 backlog items)
>
> **Auditor:** Perplexity AI (interactive audit with Michael)
> **Size rule:** Keep under **90 KB**. If approaching limit, archive completed
> section to `audit_reports/AUDIT_ARCHIVE_<date>.md` and add a reference link here.
>
> **Deployment entrypoint:** `PYTHONPATH=/app python -m app.core.scanner`
> **Healthcheck:** `/health` on port 8080
> **Prohibited (runtime-critical) dirs:** `app/core`, `app/data`, `app/risk`,
> `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications`,
> `utils/`, `migrations/`

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
| ❌ | DELETE candidate |
| 📦 | MOVED to correct location |

---

## Overall Folder Progress

| Folder | Files | Audited | Status |
|--------|-------|---------|--------|
| `app/` (root) | 1 | 1 | ✅ Complete |
| `app/ai/` | 2 | 2 | ✅ **COMPLETE** — S23 + S25 |
| `app/analytics/` | 9 | 9 | ✅ Complete (S4–S10) |
| `app/backtesting/` | 7 | 7 | ✅ **COMPLETE** — S21 + S24 |
| `app/core/` | 15 | 15 | ✅ **COMPLETE** — CORE-1 through CORE-6 + S9–S18 |
| `app/data/` | 10 | 10 | ✅ **COMPLETE** — DATA-1 through DATA-4 |
| `app/filters/` | 12 | 12 | ✅ Complete (S4, S9) — 2 deleted |
| `app/indicators/` | 4 | 4 | ✅ **COMPLETE** — S22 |
| `app/ml/` | 7 | 7 | ✅ Complete — ML-1, S11 |
| `app/mtf/` | 7 | 7 | ✅ Complete — S12 |
| `app/notifications/` | 2 | 2 | ✅ **COMPLETE** — S20 |
| `app/options/` | 9 | 9 | ✅ **COMPLETE** — S19-A + S19-B (1 deleted) |
| `app/risk/` | 7 | 7 | ✅ Complete — S14 |
| `app/screening/` | 8 | 8 | ✅ Complete (S9) |
| `app/signals/` | 5 | 5 | ✅ **COMPLETE** — SIG-1 through SIG-3 |
| `app/validation/` | 9 | 9 | ✅ Complete (S1, S9) |
| `docs/` | 8 | — | Reference only |
| `migrations/` | 4 | 4 | ✅ **COMPLETE** — S27 |
| `scripts/` | 55 | 55 | ✅ Complete (S7–S8) — 1 quarantine pending |
| `tests/` | 9 | 9 | ✅ Complete (S8) |
| `utils/` | 4 | 4 | ✅ Complete (S8–S9) |
| Root config files | 8 | 8 | ✅ **COMPLETE** — S26 |

---

## Pending Actions Queue

| # | Priority | File | Action | Status |
|---|----------|------|--------|--------|
| 1 | 🟡 MEDIUM | `app/options/__init__.py` | `_calculate_optimal_dte()` returns 14/21/30 DTE — inconsistent with 0DTE/1DTE architecture. Clarify whether `build_options_trade()` is still the live path or legacy | ⏳ Open |
| 2 | 🟡 MEDIUM | `scripts/backtesting/backtest_v2_detector.py` | Verify vs `backtest_realistic_detector.py` — possibly superseded | ⏳ Open |
| 3 | 🟢 LOW | `scripts/audit_repo.py` | QUARANTINE — one-time audit script, superseded by this registry | ⏳ Open |
| 4 | 🟢 LOW | `market_memory.db` | Verify if replaced by PostgreSQL on Railway or still active | ⏳ Open |
| 5 | 🟢 LOW | `scripts/war_machine.db` | Verify if stale vs root `war_machine.db` | ⏳ Open |
| 6 | 🟡 MEDIUM | `app/ml/ml_trainer.py` | BUG-ML-3: Platt calibration + threshold on same slice — data leakage | ⏳ Open |
| 7 | 🟡 MEDIUM | `app/validation/cfw6_gate_validator.py` | BUG-ML-4: `get_validation_stats()` permanent stub — wire or delete | ⏳ Open |
| 8 | 🟢 LOW | `app/ml/ml_confidence_boost.py` | BUG-ML-5: `.iterrows()` in logging loop — replace with `itertuples()` | ⏳ Open |
| 9 | 🟡 MEDIUM | `app/notifications/discord_helpers.py` | BUG-DH-1: `test_webhook()` uses blocking `requests.post()` on calling thread — blocks startup if Discord is slow | ⏳ Open |
| 10 | 🟢 LOW | `app/notifications/discord_helpers.py` | BUG-DH-2: `get_company_name()` yfinance call has no timeout guard — blocks on slow network at cache miss | ⏳ Open |
| 11 | 🟢 LOW | `app/notifications/discord_helpers.py` | BUG-DH-3: Footer timestamps use `EST` hardcoded string — wrong during EDT (Mar–Nov). Should use `ET` or derive from `ZoneInfo('America/New_York')` | ⏳ Open |
| 12 | 🟢 LOW | `app/backtesting/walk_forward.py` | BUG-WF-1: `create_windows()` uses `timedelta(days=30 * months)` — Feb / 31-day months cause 1-2 day boundary drift. Low risk for dev/research use; fix with `dateutil.relativedelta` if production walk-forward is enabled | ⏳ Open |
| 13 | 🟡 MEDIUM | `migrations/` | BUG-DTC-1: Run `add_dte_tracking_columns.sql` on Railway Postgres — columns not yet applied | ⏳ Open |

---

## Phase 6 — High-Probability Signal Architecture (Open Backlog)

> Phase 6 shifts from bug-fixing to precision improvements.
> Goal: raise signal win rate to ≥65%, reduce false-positive rate to <20%.
> **19 items open** — none started yet.

| ID | Area | Description | Target File(s) |
|----|------|-------------|----------------|
| 47.P1-1 | Signal Scoring | Weighted multi-factor scorecard (RVOL, MTF, Greeks, GEX, UOA, regime) — output 0–100, fire at ≥72 | `app/core/sniper.py`, `app/validation/validation.py` |
| 47.P1-2 | Signal Scoring | Dead-zone suppressor: suppress when VIX > 30 AND SPY 5m trend opposing | `app/filters/market_regime_context.py` |
| 47.P1-3 | Signal Scoring | GEX pin-zone gate: suppress if price within ±0.3% of gamma-flip level | `app/options/gex_engine.py`, `app/validation/validation.py` |
| 47.P2-1 | Options Selection | IV Rank filter: IVR < 50 for debits, IVR > 60 for credits | `app/options/iv_tracker.py`, `app/options/options_dte_selector.py` |
| 47.P2-2 | Options Selection | Delta-adjusted strike selector: intraday ATR → delta-optimal strikes (0.35–0.45Δ directional) | `app/options/options_dte_selector.py`, `app/validation/greeks_precheck.py` |
| 47.P2-3 | Options Selection | 0-DTE vs 1-DTE regime switch: force 1-DTE when VIX > 22, 0-DTE when IVR < 25 AND within 60m of close | `app/options/options_dte_selector.py` |
| 47.P3-1 | ML Confidence | Retrain ML model on post-fix signal data — all pre-fix records corrupted. Gate: 50 clean signals | `app/ml/ml_trainer.py`, `app/ml/ml_confidence_boost.py` |
| 47.P3-2 | ML Confidence | Feature engineering: add GEX_distance, IVR, time_to_close, SPY_5m_bias, RVOL_ratio | `app/ml/ml_trainer.py` |
| 47.P3-3 | ML Confidence | Confidence floor raise: reject ML confidence < 0.55 (current 0.45 too permissive) | `app/ml/ml_confidence_boost.py`, `app/core/sniper.py` |
| 47.P4-1 | Backtesting | Walk-forward backtest on 90 days EODHD data for top-5 tickers | `scripts/backtesting/unified_production_backtest.py` |
| 47.P4-2 | Backtesting | Per-hour win-rate map: replace fabricated `HOURLY_WIN_RATES` with real computed map | `app/validation/entry_timing.py`, `scripts/backtesting/` |
| 47.P4-3 | Backtesting | Sweep parameter optimization: optimal `MIN_CONFIDENCE`, `FVG_MIN_SIZE_PCT`, `RVOL_MIN` | `scripts/backtesting/backtest_sweep.py`, `utils/config.py` |
| 47.P5-1 | Risk | Dynamic position sizing via IVR: scale contract count down when IVR > 60 | `app/risk/vix_sizing.py`, `app/risk/trade_calculator.py` |
| 47.P5-2 | Risk | Profit-lock trailing stop: once +50% of max gain, move stop to breakeven | `app/risk/position_manager.py` |
| 47.P5-3 | Risk | Session loss limit: halt new signals after 2 consecutive losses | `app/risk/risk_manager.py` |
| 47.P6-1 | Data Quality | EODHD bar quality validator: monotonic timestamps, no zero-volume RTH bars, no gaps > 2m | `app/data/data_manager.py`, `app/data/candle_cache.py` |
| 47.P6-2 | Data Quality | Intraday ATR compute: rolling 14-bar ATR from live 1m bars — replace all daily-ATR hot-path calls | `app/indicators/technical_indicators_extended.py`, `app/signals/breakout_detector.py` |
| 47.P7-1 | Observability | Signal scorecard Discord embed: full scorecard in alert — RVOL, MTF, IVR, GEX, ML confidence | `app/notifications/discord_helpers.py` |
| 47.P7-2 | Observability | EOD signal quality report: auto Discord summary — signals generated/gated/fired, avg score, funnel | `app/core/eod_reporter.py` |

---

## Implemented Changes Log

> Complete history of every fix and structural change.

| # | Date | Session | File | Change | Commit SHA | Impact |
|---|------|---------|------|--------|-----------|--------|
| 1 | 2026-03-16 | S0 | `app/validation/cfw6_confirmation.py` | 🔧 VWAP formula corrected | `95be3ae` | Live bug fix |
| 2 | 2026-03-16 | S1 | `app/discord_helpers.py` | Converted to re-export shim. Fixed `send_options_signal_alert` bug | `a629a84` | Live bug fix + legacy compat |
| 3 | 2026-03-16 | S1 | `app/ml/check_database.py` | 📦 Moved → `scripts/database/check_database.py` | `3e4681a` | Clean separation |
| 4 | 2026-03-16 | S1 | `app/validation/volume_profile.py` | 5-min TTL cache + module docstring | `cea9180` | Perf improvement |
| 5 | 2026-03-16 | S2 | `app/data/database.py` | Converted to re-export shim over `db_connection.py` | `9cd17f5` | All callers use production pool |
| 6 | 2026-03-16 | S2 | `.gitignore` | Added `models/signal_predictor.pkl` exclusion | `5828488` | Prevents binary tracking |
| 7 | 2026-03-16 | S3 | `tests/test_task10_backtesting.py` | Renamed → `tests/test_backtesting_extended.py` | `dd750bb` | Cleaner test discovery |
| 8 | 2026-03-16 | S3 | `tests/test_task12.py` | Renamed → `tests/test_premarket_scanner_v2.py` | `dd750bb` | Cleaner test discovery |
| 9 | 2026-03-16 | S4 | `app/core/arm_signal.py` | Wired `record_trade_executed()`. TRADED funnel stage now records | pre-confirmed | Funnel stats complete |
| 10 | 2026-03-16 | S4 | `app/signals/signal_analytics.py` | Added `get_rejection_breakdown()`, `get_hourly_funnel()`, `get_discord_eod_summary()` | pre-confirmed | Full metrics instrumentation |
| 11 | 2026-03-16 | S4 | `app/filters/entry_timing_optimizer.py` | ❌ DELETED — exact duplicate of `entry_timing.py` | `d1821d1` | -1 file, 4.8 KB |
| 12 | 2026-03-16 | S4 | `app/filters/options_dte_filter.py` | ❌ DELETED — superseded by `greeks_precheck.py` | `3abfdd5` | -1 file, 5.3 KB |
| 13 | 2026-03-16 | S4 | `app/core/sniper.py` | Wired `funnel_analytics` on all 3 scan paths | `f5fd87b` | Funnel fires on every scan |
| 14 | 2026-03-16 | S4 | `requirements.txt` | Removed `yfinance>=0.2.40` | same | Faster deploys |
| 15 | 2026-03-16 | S5 | `app/core/confidence_model.py` | ❌ DELETED — dead stub, zero callers | `b99a63a` | Dead code removed |
| 16 | 2026-03-16 | S6 | `app/ml/analyze_signal_failures.py` | 📦 MOVED → `scripts/analysis/analyze_signal_failures.py` | `42126d5` | Dev tool in correct location |
| 17 | 2026-03-16 | S6 | `app/ml/train_from_analytics.py` | 📦 MOVED → `scripts/ml/train_from_analytics.py` | `42126d5` | Dev tool in correct location |
| 18 | 2026-03-16 | S6 | `app/ml/train_historical.py` | 📦 MOVED → `scripts/ml/train_historical.py` | `42126d5` | Dev tool in correct location |
| 19 | 2026-03-25 | S9 | `app/options/options_intelligence.py` | 🔧 `get_chain()` dead-code in cache branch removed | `edb6ba9` | Runtime bug fix |
| 20 | 2026-03-25 | S9 | `app/validation/greeks_precheck.py` | 🔧 Missing `ZoneInfo` import added | `08648df` | Runtime bug fix |
| 21 | 2026-03-25 | S9 | `app/signals/breakout_detector.py` | 🔧 `resistance_source` NameError + duplicate PDH/PDL resolved | `df2e625` | Runtime bug fix |
| 22 | 2026-03-25 | S10 | `app/screening/watchlist_funnel.py` | 🔧 Spurious `()` on `datetime.now(tz=ET)` — crashing every pre-market cycle | manual | **Critical crash fix** |
| 23 | 2026-03-25 | S10 | `app/core/scanner.py` | 🔧 `_run_analytics()` missing `conn=None` parameter | manual | Critical crash fix |
| 24 | 2026-03-25 | S10 | `app/ml/metrics_cache.py` | 🔧 Raw SQLAlchemy pool replaced with `get_conn()`/`return_conn()` | manual | Connection leak eliminated |
| 25 | 2026-03-27 | S11 | `app/ml/metrics_cache.py` | 🔧 BUG-ML-2: `%(since)s` named param → `ph()` positional + tuple | `900e211` | ML feature correctness |
| 26 | 2026-03-27 | S11 | `app/ml/ml_signal_scorer_v2.py` | 🔧 BUG-ML-1: Created missing file — Gate 5 was silently dead | `0fad513` | Gate 5 ML now functional |
| 27 | 2026-03-27 | S11 | `app/analytics/performance_monitor.py` | 🔧 BUG-ML-6: `_consecutive_losses` counter wired + Discord alert | `74ce832` | Risk control now active |
| 28 | 2026-03-27 | S12 | `app/mtf/mtf_compression.py` | 🔧 BUG-MTF-1: `compress_to_1m()` direction-aware high/low step placement | `6fc7c7b` | FVG signal quality fix |
| 29 | 2026-03-27 | S12 | `app/mtf/mtf_fvg_priority.py` | 🔧 BUG-MTF-2: volume check moved from `c2` → `c1` (impulse bar) | `137f36f` | FVG volume filter correctness |
| 30 | 2026-03-27 | S12 | `app/mtf/mtf_fvg_priority.py` | 🔧 BUG-MTF-3: `get_full_mtf_analysis()` now builds `15m`+`30m` bars | `137f36f` | Higher-TF FVG detection active |
| 31 | 2026-03-30 | S14 | `s16_helpers.txt` | ❌ DELETED root staging file — duplicate of `app/risk/position_helpers.py` | `2cb2020` | Root cleaned |
| 32 | 2026-03-30 | S14 | `s16_trade.txt` | ❌ DELETED root staging file — duplicate of `app/risk/trade_calculator.py` | `09f25f8` | Root cleaned |
| 33 | 2026-03-30 | S14 | `s16_vix.txt` | ❌ DELETED root staging file — duplicate of `app/risk/vix_sizing.py` | `72abc33` | Root cleaned |
| 34 | 2026-03-30 | S14 | `app/risk/risk_manager.py` | 🔧 BUG-RISK-1: `_reject()` redundant `compute_stop_and_targets()` removed | `5f651ff` | Perf + correctness |
| 35 | 2026-03-30 | S14 | `app/core/sniper_pipeline.py` | 🔧 BUG-SP-1: TIME gate moved above RVOL fetch | `7f5b377` | Perf fix |
| 36 | 2026-03-30 | S14 | `app/core/sniper_pipeline.py` + `signal_scorecard.py` | 🔧 BUG-SP-2: `confidence_base` wired into scorecard. Max score 85→95 | `7f5b377` / `032ffcc` | Signal quality improvement |
| 37 | 2026-03-30 | S14 | `app/core/arm_signal.py` | 🔧 BUG-ARM-1: Module docstring moved above `import logging` | `0165db5` | Cosmetic / introspection fix |
| 38 | 2026-03-31 | S15 | `app/core/watch_signal_store.py` | 🔧 BUG-WSS-1: Error-path `logger.info` → `logger.warning` | `19fc732` | Log level consistency |
| 39 | 2026-03-31 | S15 | `app/core/watch_signal_store.py` | 🔧 BUG-WSS-2: Stray `print()` → `logger.info()` in `_load_watches_from_db()` | `19fc732` | Logging hygiene |
| 40 | 2026-03-31 | S15 | `app/core/watch_signal_store.py` | 🔧 BUG-WSS-3: Empty `()` tuple removed from full-table DELETE | `19fc732` | Style consistency |
| 41 | 2026-03-31 | S16 | `app/core/thread_safe_state.py` | 🔧 BUG-TSS-1: `increment_validator_stat()` logs warning on unknown stat | `b65deb9` | Data integrity visibility |
| 42 | 2026-03-31 | S16 | `app/core/thread_safe_state.py` | 🔧 BUG-TSS-2: Naive datetime → ET-aware for `_last_dashboard_check` / `_last_alert_check` | `b65deb9` | Runtime crash prevention |
| 43 | 2026-03-31 | S16 | `app/core/thread_safe_state.py` | 🔧 BUG-TSS-3: `logger` assignment moved after all imports | `b65deb9` | Style consistency |
| 44 | 2026-03-31 | S16 | `app/core/thread_safe_state.py` | 🔧 BUG-TSS-4: Added missing `get_all_armed_signals()` + `get_all_watching_signals()` wrappers | `b65deb9` | API completeness |
| 45 | 2026-03-31 | S16 | `app/core/sniper_log.py` | 🔧 BUG-SL-1: `except Exception: pass` → `except Exception as e: print(...)` | `aafef1` | Visibility improvement |
| 46 | 2026-03-31 | S16 | `app/core/logging_config.py` | 🔧 BUG-LC-1: Module-level `logger` added for consistency | `4ff5fba` | Style + grep consistency |
| 47 | 2026-03-31 | S16 | `app/core/analytics_integration.py` | 🔧 BUG-AI-1: Bare `logging.*` → `logger = logging.getLogger(__name__)` | `4ff5fba` | Railway log namespace fix |
| 48 | 2026-03-31 | S16 | `app/core/analytics_integration.py` | 🔧 BUG-AI-2: `_tracker.session_signals` → `get_funnel_stats()` public API | `4ff5fba` | Decoupling |
| 49 | 2026-03-31 | S16 | `app/core/analytics_integration.py` | 🔧 BUG-AI-3: `eod_report_done` never reset at midnight — EOD report stops after day 1 | `4ff5fba` | **Real bug — EOD report broken** |
| 50 | 2026-03-31 | S16 | `app/core/health_server.py` | 🔧 BUG-HS-1: Blank line between `import logging` and `logger` | `4ff5fba` | Style consistency |
| 51 | 2026-03-31 | S16 | `app/core/health_server.py` | 🔧 BUG-HS-2: `from __future__ import annotations` added | `4ff5fba` | Style consistency |
| 52 | 2026-03-31 | S16 | `app/core/arm_signal.py` | 🔧 BUG-S16-1: `'validation'` key → `'validation_data'` — validation payload silently lost | `eea5239` | **Real bug — validation data never persisted** |
| 53 | 2026-03-31 | S17 | `app/core/scanner.py` | 🔧 BUG-SC-1/5: PEP 8 fixes + startup Discord message correctness | `c6a6adf` | Style + UX accuracy |
| 54 | 2026-03-31 | S18 | `app/core/armed_signal_store.py` | 🔧 BUG-ASS-3: `_persist_armed_signal()` key `'validation'` → `'validation_data'` — silent data loss | live | **Real bug — validation payload never written to DB** |
| 55 | 2026-03-31 | DATA-1 | `app/data/intraday_atr.py` | 🔧 BUG-IAT-1: `logger.info` → `logger.warning` on compute exception | `a982d079` | Logging level |
| 56 | 2026-03-31 | DATA-1 | `app/data/sql_safe.py` | 🔧 BUG-SS-1/2: `build_insert/update/delete()` + `safe_insert/update_dict()` call `sanitize_table_name()` | `a982d079` | SQL injection prevention |
| 57 | 2026-03-31 | DATA-1 | `app/data/unusual_options.py` | 🔧 BUG-UOA-1: `_cache_result()` stores `.isoformat()` | `a982d079` | Cache correctness |
| 58 | 2026-03-31 | DATA-2 | `app/data/db_connection.py` | 🔧 BUG-DBC-1/2: naive datetime → ET-aware; `logger.info` → `logger.warning` | `b0524d51` | TZ correctness |
| 59 | 2026-03-31 | DATA-3 | `app/data/data_manager.py` | 🔧 BUG-DM-1/2: ET-naive cutoff fix + explicit WS/API counters | `b0524d51` | TZ + observability |
| 60 | 2026-03-31 | DATA-4 | `app/data/ws_feed.py` | 🔧 BUG-WF-1: `materialize_5m_bars()` moved inside `if count:` block | `e77b5ba2` | Runtime correctness |
| 61 | 2026-03-31 | DATA-4 | `app/data/ws_quote_feed.py` | 🔧 BUG-WQF-1/2: ask/bid `or` → `is not None` (0.0 falsy trap) | `9ab785f6` | Data correctness |
| 62 | 2026-03-31 | CORE-4 | `app/core/sniper.py` | 🔧 BUG-SN-4/5/6: dispatcher doc, import order, `.get()` guard | `e25f3200` | Style + safety |
| 63 | 2026-03-31 | CORE-5 | `app/core/scanner.py` | 🔧 BUG-SC-A–G: version, dead var, `.get()` guards, constants — 6 fixes | `7ece10fd` | Multiple correctness |
| 64 | 2026-03-31 | CORE-6 | `app/core/signal_scorecard.py` | 🔧 BUG-SC-1: blank line + unused `field` import removed | `0c2290af` | Style |
| 65 | 2026-03-31 | CORE-6 | `app/core/sniper_pipeline.py` | 🔧 BUG-SP-3: `BEAR_SIGNALS_ENABLED` dead import removed | `0c2290af` | Dead code |
| 66 | 2026-03-31 | ML-1 | `app/ml/ml_confidence_boost.py` | 🔧 BUG-MCB-1/2: logging import order + 3× `info`→`warning` | `5255863a` | Logging level |
| 67 | 2026-03-31 | ML-1 | `app/ml/ml_trainer.py` | 🔧 BUG-MLT-1: `df = df.copy()` CoW-safe | `5255863a` | Pandas future compat |
| 68 | 2026-03-31 | WSS-1 | `app/core/watch_signal_store.py` | ✅ BUG-WSS-1/2/3 confirmed fixed (see #38–40) | `061e6481` | Confirmed |
| 69 | 2026-03-31 | ASS-1 | `app/core/armed_signal_store.py` | 🔧 BUG-ASS-1/2/3: logging order, redundant import, validation key fix | `7ea03339` | Multiple |
| 70 | 2026-04-01 | SIG-2 | `app/signals/opening_range.py` | 🔧 BUG-OR-1: dead `or_data = classify_or()` in `should_scan_now()` removed | `cbfc26d` | Dead code |
| 71 | 2026-04-01 | SIG-2 | `app/signals/opening_range.py` | 🔧 BUG-OR-2: duplicate `from utils import config` inside `for` loop removed | `cbfc26d` | Import hygiene |
| 72 | 2026-04-01 | SIG-2 | `app/signals/breakout_detector.py` | 🔧 BUG-BD-1: dead `risk_reward_ratio: float = 2.0,` tuple assignment removed | `cbfc26d` | Dead code |
| 73 | 2026-04-01 | CONSOLIDATION | `audit_registry.md` (root) | ❌ DELETED — merged into `docs/AUDIT_REGISTRY.md` | `34171dfa` | Cleanup |
| 74 | 2026-04-01 | CONSOLIDATION | `docs/remediation_tracker.md` | ❌ DELETED — Phase 6 backlog absorbed into this file | `34171dfa` | Cleanup |
| 75 | 2026-04-01 | CONSOLIDATION | `audit_reports/AUDIT_2026-03-26.md` | ❌ DELETED — old snapshot, fully superseded | `34171dfa` | Cleanup |
| 76 | 2026-04-01 | S19-A | `app/options/dte_selector.py` | 🔧 BUG-ODS-A1: `datetime.now().replace(...)` → `current_time.replace(...)` | S19-A | TZ correctness |
| 77 | 2026-04-01 | S19-A | `app/options/dte_historical_advisor.py` | 🔧 BUG-DHA-1/2: 2× `logger.info` → `logger.warning` on error/init paths | S19-A | Logging level |
| 78 | 2026-04-01 | S19-A | `app/options/options_data_manager.py` | 🔧 BUG-ODM-1: `f"{result['delta']:.2f}"` TypeError when delta is None | S19-A | Runtime crash prevention |
| 79 | 2026-04-01 | S19-A | `app/options/options_dte_selector.py` | 🔧 BUG-ODTS-1: 2× bare `except:` → `except Exception as e: logger.warning(...)` | S19-A | Railway visibility |
| 80 | 2026-04-01 | S19-B | `app/options/options_intelligence.py` | 🔧 BUG-OIN-1: `get_chain()` exception uses `logger.info` → `logger.warning` | `d6564a3f` | Railway visibility |
| 81 | 2026-04-01 | S19-B | `app/options/options_intelligence.py` | 🔧 BUG-OIN-2: `get_options_score()` catches price fetch exception with bare `except` → `except Exception` | `d6564a3f` | Hygiene |
| 82 | 2026-04-01 | S19-B | `app/options/options_intelligence.py` | ✅ BUG-OIN-3: `_get_ivr_data()` early-return on first ATM call — intentional, earliest expiry = most liquid IV proxy | `d6564a3f` | Verified OK |
| 83 | 2026-04-01 | S19-B | `app/options/options_intelligence.py` | ✅ BUG-OIN-4: `_compute_gex_score()` direction-blind — intentional at scan time, direction unknown. `validate_for_trading()` handles directional GEX | `d6564a3f` | Verified OK |
| 84 | 2026-04-01 | S19-B | `app/options/options_intelligence.py` | 🔧 BUG-OIN-5: `pin_headwind` stub always `False` — removed from return dict; callers use `gamma_pin` vs `current_price` directly | `d6564a3f` | Runtime correctness |
| 85 | 2026-04-01 | S20 | `app/options/options_optimizer.py` | ❌ DELETED — zero callers, `asyncio.run()` crashes Railway loop, ET-naive, superseded by `OptionsDataManager` + `options_dte_selector` | `8b63b6f7` | Dead code removed |
| 86 | 2026-04-01 | S20 | `app/notifications/__init__.py` | ✅ Clean — explicit re-export shim, correct `__all__`, matches `discord_helpers.py` public API exactly | `8b63b6f7` | No action needed |
| 87 | 2026-04-01 | S20 | `app/notifications/discord_helpers.py` | ⚠️ BUG-DH-1: `test_webhook()` calls blocking `requests.post()` on the calling thread | pending | Railway startup safety |
| 88 | 2026-04-01 | S20 | `app/notifications/discord_helpers.py` | ⚠️ BUG-DH-2: `get_company_name()` yfinance call has no timeout guard | pending | Scan loop safety |
| 89 | 2026-04-01 | S20 | `app/notifications/discord_helpers.py` | ⚠️ BUG-DH-3: All footer timestamps use `EST` hardcoded string — wrong during EDT (Mar–Nov) | pending | Accuracy |
| 90 | 2026-04-01 | S21 | `app/backtesting/backtest_engine.py` | ✅ BUG-BE-1–5 confirmed present | pre-applied | Confirmed |
| 91 | 2026-04-01 | S21 | `app/backtesting/signal_replay.py` | ✅ BUG-SR-1/2 confirmed present | pre-applied | Confirmed |
| 92 | 2026-04-01 | S21 | `app/backtesting/walk_forward.py` | ✅ BUG-WF-2 confirmed present | pre-applied | Confirmed |
| 93 | 2026-04-01 | S21 | `app/backtesting/historical_trainer.py` | ✅ BUG-HT-1 confirmed present | pre-applied | Confirmed |
| 94 | 2026-04-01 | S21 | `app/backtesting/walk_forward.py` | ⚠️ BUG-WF-1 (deferred): `timedelta(days=30 * months)` window boundary approximation | pending | Low risk |
| 95 | 2026-04-01 | S21 | `app/backtesting/__init__.py` | ✅ Clean — explicit `__all__`, all 12 exported symbols match actual implementations | pre-applied | Confirmed |
| 96 | 2026-04-01 | S21 | `app/backtesting/performance_metrics.py` | ✅ Clean — all 8 metric functions correct, edge cases handled | pre-applied | Confirmed |
| 97 | 2026-04-01 | S21 | `app/backtesting/parameter_optimizer.py` | ✅ Clean — grid search with min_trades guard, metric validation, sorted results | pre-applied | Confirmed |
| 98 | 2026-04-01 | S21 | `app/backtesting/performance_metrics.py` | 🔧 BUG-PM-1: `calculate_sortino_ratio()` returns `float('inf')` capped to 10.0 before grid sort | `e8e5f0a` | Sort stability |
| 99 | 2026-04-01 | S21 | `app/backtesting/walk_forward.py` | 🔧 BUG-WF-3: `from app.backtesting import performance_metrics` hoisted to module level | `e8e5f0a` | Import hygiene |
| 100 | 2026-04-01 | S21 | `app/backtesting/backtest_engine.py` | 🔧 BUG-BE-6: T1 partial commission denominator corrected | `d3f67b7` | Commission accuracy |
| 101 | 2026-04-01 | S21 | `app/backtesting/backtest_engine.py` | 🔧 BUG-BE-7: Docstring clarifies one-position-at-a-time constraint | `d3f67b7` | Documentation |
| 102 | 2026-04-01 | S21 | `app/backtesting/parameter_optimizer.py` | 🔧 BUG-PO-1: `inf` metric values capped to `sys.float_info.max` before sort | `88a3516` | Sort stability |
| 103 | 2026-04-01 | S22 | `app/indicators/technical_indicators_extended.py` | 🔧 BUG-TIE-1 [HIGH]: `check_volatility_expansion()` slice `[-11:-1]` → `[1:11]` — EODHD newest-first ordering; was reading oldest 10 bars as baseline | `80da33a` | **Signal quality — volatility expansion detection fixed** |
| 104 | 2026-04-01 | S22 | `app/indicators/technical_indicators.py` | 🔧 BUG-TI-1: `fetch_technical_indicator()` HTTPError + Exception logged at `info` → `warning` | `80da33a` | Railway visibility |
| 105 | 2026-04-01 | S22 | `app/indicators/technical_indicators.py` | 🔧 BUG-TI-2/3: `batch_fetch_indicators()` unknown indicator + per-ticker fetch error `info` → `warning` | `80da33a` | Railway visibility |
| 106 | 2026-04-01 | S22 | `app/indicators/technical_indicators.py` | 🔧 BUG-TI-4: `check_rsi_divergence()` exception catch `info` → `warning` | `80da33a` | Railway visibility |
| 107 | 2026-04-01 | S22 | `app/indicators/vwap_calculator.py` | 🔧 BUG-VC-1: `VWAPCalculator.__init__()` module-level init `logger.info` → `logger.debug` — spammy on import | `80da33a` | Log noise reduction |
| 108 | 2026-04-01 | S22 | `app/indicators/volume_indicators.py` | ✅ Clean — RVOL, OBV, Accumulation/Distribution, CMF, MFI, VWAP-volume all correct. No issues | `80da33a` | Confirmed |
| 109 | 2026-04-01 | S24 | `app/backtesting/historical_trainer.py` | 🔧 BUG-HT-2: `build_dataset()` row dict wrote `sig['outcome']` (still `'TIMEOUT'`) instead of local `outcome` (reassigned to `'LOSS'`). `df['outcome']` column contained `'TIMEOUT'` strings even with `include_timeout=True` — any `df['outcome']=='LOSS'` filter silently missed all timed-out signals. `outcome_binary` was correct. Fix: `'outcome': outcome` | `fc42b59` | **ML training data correctness — LOSS label coverage restored** |
| 110 | 2026-04-01 | S24 | `app/backtesting/historical_trainer.py` | ℹ️ BUG-HT-3: `summary()` `TIMEOUT→LOSS` count check now always returns 0 after BUG-HT-2 fix — kept as zero-assertion guard (non-zero = regression) | `fc42b59` | Documentation / guard |
| 111 | 2026-04-01 | S25 | `app/ai/ai_learning.py` | ✅ BUG-AIL-1: 6× `logger.info` on error/exception paths → `logger.warning` — confirmed in source | pre-applied | Railway visibility |
| 112 | 2026-04-01 | S25 | `app/ai/ai_learning.py` | ✅ BUG-AIL-2: `optimize_confirmation_weights()` not-enough-data log → `logger.debug` — confirmed in source | pre-applied | Log noise reduction |
| 113 | 2026-04-01 | S25 | `app/ai/ai_learning.py` | ✅ BUG-AIL-3: `get_options_flow_weight()` general except `logger.info` → `logger.warning` — covered by BUG-AIL-1 fix, confirmed | pre-applied | Railway visibility |
| 114 | 2026-04-01 | S25 | `app/ai/ai_learning.py` | ✅ BUG-AIL-4: `__init__` `load_data()` fallback → `logger.warning` — confirmed in source | pre-applied | Startup visibility |
| 115 | 2026-04-01 | S25 | `app/ai/ai_learning.py` | ✅ BUG-AIL-5: `optimize_fvg_threshold()` silent early return → `logger.debug` with count/threshold — confirmed in source | pre-applied | Observability |
| 116 | 2026-04-01 | S26 | `railway.toml` | 🔧 BUG-RC-1: cron command `python app/ml/train_ml_booster.py` — file does not exist. Fixed to `python -m app.ml.ml_trainer` | `e12aa5b` | **Cron was silently failing every Sunday** |
| 117 | 2026-04-01 | S26 | `app/ml/ml_trainer.py` | 🔧 BUG-RC-2: no `__main__` block — `python -m app.ml.ml_trainer` exited silently after import, never called `train_model()`. Added `__main__` with `logging.basicConfig`, `train_model()`, `sys.exit(1)` on failure | `af9b726` | **Weekly ML retrain now functional** |
| 118 | 2026-04-01 | S27 | `migrations/add_dte_tracking_columns.py` | ❌ DELETED (was never tracked in git) — used SQLite `get_conn()` path, never ran on Railway Postgres | n/a | Dead migration removed |
| 119 | 2026-04-01 | S27 | `migrations/add_dte_tracking_columns.sql` | 🔧 BUG-DTC-1: Created idempotent SQL replacement — 4× `ALTER TABLE positions ADD COLUMN IF NOT EXISTS` for `dte_selected`, `adx_at_entry`, `vix_at_entry`, `target_pct_t1` | `9f6483c` | **DTE tracking columns migration ready — run on Railway to apply** |
| 120 | 2026-04-01 | S27 | `migrations/001_candle_cache.sql` | ✅ Clean — `candle_cache` table DDL correct, indexes on `(ticker, bar_time)` and `ticker` | `9f6483c` | Confirmed |
| 121 | 2026-04-01 | S27 | `migrations/002_signal_persist_tables.sql` | ✅ Clean — `signals`, `positions`, `trade_outcomes` DDL correct, FK constraints, `IF NOT EXISTS` throughout | `9f6483c` | Confirmed |
| 122 | 2026-04-01 | S27 | `migrations/signal_outcomes_schema.sql` | ✅ Clean — extended schema with `signal_outcomes` + `signal_filters` audit tables; `IF NOT EXISTS` safe | `9f6483c` | Confirmed |

---

## Current Session Audit Notes

### Session S27 — `migrations/` (2026-04-01)
**Status:** ✅ Complete — 4 files audited, BUG-DTC-1 fixed

| File | Result |
|------|--------|
| `001_candle_cache.sql` | ✅ Clean |
| `002_signal_persist_tables.sql` | ✅ Clean |
| `signal_outcomes_schema.sql` | ✅ Clean |
| `add_dte_tracking_columns.py` | ❌ Was never git-tracked — dead migration using SQLite path |
| `add_dte_tracking_columns.sql` | 🔧 BUG-DTC-1 — Created idempotent SQL replacement |

**BUG-DTC-1:** The original `add_dte_tracking_columns.py` used the SQLite `get_conn()` path and was never tracked in git, meaning the 4 DTE tracking columns (`dte_selected`, `adx_at_entry`, `vix_at_entry`, `target_pct_t1`) were never applied to Railway Postgres. Replaced with `add_dte_tracking_columns.sql` using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. **Action required:** run `psql $DATABASE_URL -f migrations/add_dte_tracking_columns.sql` on Railway to apply.

---

### Sessions S26–S11 and earlier
*(See Implemented Changes Log above for full details)*

---

## `app/core` File Necessity Assessment

| File | Necessary? | If Removed |
|------|-----------|------------|
| `__init__.py` | ✅ YES | All `app.core.*` imports fail |
| `__main__.py` | ✅ YES | Railway can't start |
| `scanner.py` | ✅ YES | System doesn't run |
| `sniper.py` | ✅ YES | No signals detected |
| `sniper_pipeline.py` | ✅ YES | All signals pass without filtering |
| `signal_scorecard.py` | ✅ YES | No confidence scoring |
| `arm_signal.py` | ✅ YES | No trades execute |
| `armed_signal_store.py` | ✅ YES | Armed signals lost on restart |
| `watch_signal_store.py` | ✅ YES | Watch phase broken |
| `thread_safe_state.py` | ✅ YES | Race conditions on all shared state |
| `sniper_log.py` | ✅ YES | `ImportError` on every arm attempt |
| `logging_config.py` | ✅ YES | All loggers use basicConfig defaults |
| `analytics_integration.py` | ✅ YES | Signal lifecycle events stop recording |
| `eod_reporter.py` | ✅ YES | EOD Discord reports stop; cache never cleared |
| `health_server.py` | ✅ YES | Railway silent failures undetected |

**All 15 files in `app/core` are 100% necessary. No candidates for removal.**

---

## Next Session Queue

| Priority | Target | Files | Notes |
|----------|--------|-------|-------|
| 1 | Pending actions | Various | BUG-DTC-1: run `add_dte_tracking_columns.sql` on Railway |
| 2 | Phase 6 backlog | Various | Start 47.P1-1 signal scoring |
