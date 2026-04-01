# War Machine — Master Audit Registry

> **Purpose:** Single source of truth for every file-by-file, line-by-line audit session.
> Every finding, fix, and status change is recorded here chronologically — never delete entries.
> Updated after **every commit** — no exceptions.
>
> **Last updated:** 2026-04-01 — Consolidation commit. Merged root `audit_registry.md`,
> `docs/remediation_tracker.md`, and `docs/AUDIT_REGISTRY.md` into this single file.
> Next: `app/options/` full audit (S19).
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
| `app/ai/` | 2 | 0 | ⬜ Pending |
| `app/analytics/` | 9 | 9 | ✅ Complete (S4–S10) |
| `app/backtesting/` | 7 | 0 | ⬜ Pending |
| `app/core/` | 15 | 15 | ✅ **COMPLETE** — CORE-1 through CORE-6 + S9–S18 |
| `app/data/` | 10 | 10 | ✅ **COMPLETE** — DATA-1 through DATA-4 |
| `app/filters/` | 12 | 12 | ✅ Complete (S4, S9) — 2 deleted |
| `app/indicators/` | 4 | 0 | ⬜ Pending |
| `app/ml/` | 7 | 7 | ✅ Complete — ML-1, S11 |
| `app/mtf/` | 7 | 7 | ✅ Complete — S12 |
| `app/notifications/` | 2 | 0 | ⬜ Pending |
| `app/options/` | 9 | 0 | ⬜ **NEXT — S19** |
| `app/risk/` | 7 | 7 | ✅ Complete — S14 |
| `app/screening/` | 8 | 8 | ✅ Complete (S9) |
| `app/signals/` | 5 | 5 | ✅ **COMPLETE** — SIG-1 through SIG-3 |
| `app/validation/` | 9 | 9 | ✅ Complete (S1, S9) |
| `docs/` | 8 | — | Reference only |
| `migrations/` | 4 | 0 | ⬜ Pending |
| `scripts/` | 55 | 55 | ✅ Complete (S7–S8) — 1 quarantine pending |
| `tests/` | 9 | 9 | ✅ Complete (S8) |
| `utils/` | 4 | 4 | ✅ Complete (S8–S9) |
| Root config files | 8 | 0 | ⬜ Pending |

---

## Pending Actions Queue

| # | Priority | File | Action | Status |
|---|----------|------|--------|--------|
| 1 | 🔴 **NEXT** | `app/options/` (9 files) | **S19 full audit** | ⏳ Open |
| 2 | 🟡 MEDIUM | `scripts/backtesting/backtest_v2_detector.py` | Verify vs `backtest_realistic_detector.py` — possibly superseded | ⏳ Open |
| 3 | 🟢 LOW | `scripts/audit_repo.py` | QUARANTINE — one-time audit script, superseded by this registry | ⏳ Open |
| 4 | 🟢 LOW | `market_memory.db` | Verify if replaced by PostgreSQL on Railway or still active | ⏳ Open |
| 5 | 🟢 LOW | `scripts/war_machine.db` | Verify if stale vs root `war_machine.db` | ⏳ Open |
| 6 | 🟡 MEDIUM | `app/ml/ml_trainer.py` | BUG-ML-3: Platt calibration + threshold on same slice — data leakage | ⏳ Open |
| 7 | 🟡 MEDIUM | `app/validation/cfw6_gate_validator.py` | BUG-ML-4: `get_validation_stats()` permanent stub — wire or delete | ⏳ Open |
| 8 | 🟢 LOW | `app/ml/ml_confidence_boost.py` | BUG-ML-5: `.iterrows()` in logging loop — replace with `itertuples()` | ⏳ Open |

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
| 47.P2-1 | Options Selection | IV Rank filter: IVR < 50 for debits, IVR > 60 for credits | `app/options/iv_tracker.py`, `app/options/options_optimizer.py` |
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

> Complete history of every fix and structural change. Sessions S1–S18 (older numbering)
> correspond to the early batch audit (Sessions 1–18 in docs/AUDIT_REGISTRY.md legacy).
> Sessions CORE-1 through SIG-3 are the current file-by-file line-by-line audit series.

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
| 51 | 2026-03-31 | S16 | `app/core/health_server.py` | 🔧 BUG-HS-2: `from __future__ import annotations` added | `4ff5fba` | Forward compatibility |
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
| 73 | 2026-04-01 | CONSOLIDATION | `audit_registry.md` (root) | ❌ DELETED — merged into `docs/AUDIT_REGISTRY.md` | this commit | Cleanup |
| 74 | 2026-04-01 | CONSOLIDATION | `docs/remediation_tracker.md` | ❌ DELETED — Phase 6 backlog absorbed into this file | this commit | Cleanup |
| 75 | 2026-04-01 | CONSOLIDATION | `audit_reports/AUDIT_2026-03-26.md` | ❌ DELETED — old snapshot, fully superseded | this commit | Cleanup |

---

## Current Session Audit Notes

### Session SIG-3 — `app/signals/vwap_reclaim.py`
**Date:** 2026-04-01 | **Commit:** N/A — no fixes required
**Status:** ✅ Clean

**Checks confirmed clean:**
- Import block: `logging`, `typing`, `from utils import config` — correct order ✅
- `_get_adaptive_threshold()` lazy import inside `try/except`, fallback to `getattr(config, 'FVG_MIN_SIZE_PCT', 0.0015) * current_price` ✅
- `detect_vwap_reclaim()` entry guard `not bars or len(bars) < 3 or vwap <= 0` ✅
- Bull logic: `low < vwap` (sweep) + `close > vwap` (reclaim) + `in_zone` — all 3 required ✅
- Bear logic: symmetric, `close < vwap` in `[zone_low, vwap)` — intentional ✅
- Return dict keys consistent bull/bear: `direction`, `entry_price`, `vwap`, `zone_low`, `zone_high`, `grade` ✅
- No stray `print()` calls — Phase 5 fix confirmed ✅

---

### Session SIG-2 — Dead Code Fixes
**Date:** 2026-04-01 | **Commit:** `cbfc26d`
**Files:** `app/signals/opening_range.py`, `app/signals/breakout_detector.py`

**BUG-OR-1** → 🔧 Dead `or_data = classify_or()` in `should_scan_now()` removed
**BUG-OR-2** → 🔧 Duplicate `from utils import config` inside `for` loop removed
**BUG-BD-1** → 🔧 Dead `risk_reward_ratio: float = 2.0,` tuple assignment removed

---

### Session SIG-1 — `app/signals/breakout_detector.py` + `app/signals/signal_analytics.py`
**Date:** 2026-03-31

**`breakout_detector.py`** ✅ Fixed (BUG-BD-1 in SIG-2)
- `calculate_atr()` cache, `get_pdh_pdl()` composite key, `calculate_support_resistance()` rolling→session-anchor→PDH/PDL priority, EMA volume multiplier, `analyze_candle_strength()` Marubozu/Hammer/Engulfing, `detect_breakout()` uses `bars[:-1]`, BULL/BEAR/RETEST symmetric logic, `session_anchored` flag ✅

**`signal_analytics.py`** ✅ Clean
- `get_conn()` try/finally, `_initialize_database()` guard, Postgres/SQLite dual-path, all stage guards, ZeroDivisionError guards, `get_multiplier_impact()` fallback, singleton ✅

---

### Session DATA-4 — `app/data/ws_feed.py` + `app/data/ws_quote_feed.py`
**Date:** 2026-03-31 | **Commits:** `e77b5ba2`, `9ab785f6`
BUG-WF-1, BUG-WQF-1, BUG-WQF-2 fixed. **`app/data/` 100% complete (10/10)**

---

### Session DATA-3 — `app/data/data_manager.py`
**Date:** 2026-03-31 | **Commit:** `b0524d51`
BUG-DM-1 (`cleanup_old_bars()` ET-naive cutoff), BUG-DM-2 (explicit WS/API counters)

---

### Session DATA-2 — `app/data/db_connection.py`
**Date:** 2026-03-31 | **Commit:** `b0524d51`
BUG-DBC-1 (`datetime.now()` → `datetime.now(_ET)`), BUG-DBC-2 (logs → `logger.warning`)

---

### Session DATA-1 — `app/data/` Small & Medium Files
**Date:** 2026-03-31 | **Commit:** `a982d079`
BUG-IAT-1, BUG-SS-1, BUG-SS-2, BUG-UOA-1 fixed.
`__init__.py` ✅ · `database.py` ✅ 🔁 · `intraday_atr.py` ✅ Fixed · `sql_safe.py` ✅ Fixed · `candle_cache.py` ✅ · `unusual_options.py` ✅ Fixed

---

### Session CORE-6 — Pending Fix Clearance
**Date:** 2026-03-31 | **Commit:** `0c2290af`
BUG-SC-1 (`signal_scorecard.py` blank line + unused import), BUG-SP-3 (`sniper_pipeline.py` dead import)

---

### Session CORE-5 — `app/core/scanner.py`
**Date:** 2026-03-31 | **Commit:** `7ece10fd`
BUG-SC-A through SC-G (6 fixes). **`app/core/` 100% complete (15/15 files).**

---

### Session CORE-4 — `app/core/sniper.py`
**Date:** 2026-03-31 | **Commit:** `e25f3200`
BUG-SN-4, SN-5, SN-6 fixed.

---

### Session CORE-3 — `app/core/arm_signal.py` + `analytics_integration.py`
**Date:** 2026-03-31 | Both ✅ Clean.

---

### Session CORE-2 — `app/core/` Pipeline Files
**Date:** 2026-03-31
`thread_safe_state.py` ✅ · `signal_scorecard.py` / `sniper_pipeline.py` — see CORE-6.

---

### Session CORE-1 — `app/core/` Bootstrap Files
**Date:** 2026-03-31 | All 6 files ✅ Clean.
`app/__init__.py` · `app/core/__init__.py` · `app/core/__main__.py` · `logging_config.py` · `sniper_log.py` · `eod_reporter.py` · `health_server.py`

---

### Session ML-1 — `app/ml/` Full Audit
**Date:** 2026-03-31 | **Commit:** `5255863a`
`__init__.py` ✅ · `metrics_cache.py` ✅ · `ml_confidence_boost.py` ✅ Fixed · `ml_signal_scorer_v2.py` ✅ · `ml_trainer.py` ✅ Fixed

---

### Session ASS-1 — `app/core/armed_signal_store.py`
**Date:** 2026-03-31 | **SHA post-fix:** `7ea03339`
BUG-ASS-1, ASS-2, ASS-3 all addressed.

---

### Session WSS-1 — `app/core/watch_signal_store.py`
**Date:** 2026-03-31 | **SHA:** `061e6481`
BUG-WSS-1, WSS-2, WSS-3 fixed.

---

### Session S-OR-1 — `app/signals/opening_range.py`
**Date:** 2026-03-31 | ✅ Clean audit — BUG-OR-1/2 fixed in SIG-2.

---

## Session S18 — Cross-File Key-Consistency Audit (2026-03-31)

> Full re-verification of all 9 `app/core` files. One real silent-data-loss bug found.

| Check | Result |
|-------|--------|
| BUG-ASS-3: `data.get('validation')` vs `arm_signal.py`'s `'validation_data'` key | 🔧 **FIXED** — key corrected to `'validation_data'` |
| BUG-ASS-1/2 cosmetic | ⚠️ NOTED — non-crashing, no fix needed |
| `signal_scorecard.py` — all 11 scorer functions | ✅ Confirmed correct |
| `SCORECARD_GATE_MIN=60`, `RVOL_CEILING penalty=-20`, exception returns 59 | ✅ Confirmed |
| `logging_config.py`, `sniper_log.py`, `analytics_integration.py` | ✅ All re-verified clean |
| `health_server.py`, `eod_reporter.py`, `__main__.py`, `__init__.py` | ✅ All re-verified clean |

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
| 1 🔥 | `app/options/` | 9 files | Options chain, Greeks, GEX, DTE selection |
| 2 | `app/notifications/` | 2 files | Discord alert system |
| 3 | `app/backtesting/` | 7 files | Backtest engine, walk-forward |
| 4 | `app/filters/`, `app/indicators/`, `app/mtf/`, `app/screening/`, `app/validation/`, `app/risk/`, `app/ai/` | All | Secondary modules |
| 5 | `scripts/`, `tests/`, `utils/` | All | Support infrastructure |
| 6 | Root config | `requirements.txt`, `railway.toml`, etc. | Deployment config |
