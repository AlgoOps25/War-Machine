# War Machine — Full Repo Audit Registry

> **Purpose:** Master reference for the file-by-file audit of all tracked files.  
> **Last updated:** 2026-03-31 Session 16 — `thread_safe_state.py` 🔧 BUG-TSS-1/2/3/4 fixed | `sniper_log.py` 🔧 BUG-SL-1 fixed | `logging_config.py` 🔧 BUG-LC-1 fixed | `analytics_integration.py` 🔧 BUG-AI-1/2/3 fixed | `health_server.py` 🔧 BUG-HS-1/2 fixed | `eod_reporter.py` ✅ clean  
> **Auditor:** Perplexity AI (interactive audit with Michael)  
> **Status legend:** ✅ KEEP | ⚠️ REVIEW | 🔀 MERGE → target | 🗃️ QUARANTINE | ❌ DELETE | 🔧 FIXED | 📦 MOVED  
> **Prohibited (runtime-critical) directories:** `app/core`, `app/data`, `app/risk`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications`, `utils/`, `migrations/`  
> **Deployment entrypoint:** `PYTHONPATH=/app python -m app.core.scanner`  
> **Healthcheck:** `/health` on port 8080  
> **Standing rule:** AUDIT_REGISTRY.md is updated after every change and every important finding — no exceptions.

---

## Progress Tracker

| Batch | Directory Scope | Files | Status |
|-------|----------------|-------|--------|
| A1 | `app/core` | 15 | ✅ Complete — reconciled Session 9 |
| A2 | `app/risk`, `app/data`, `app/signals`, `app/validation`, `app/filters`, `app/mtf`, `app/notifications` | 47 | ✅ Complete — reconciled Session 9 |
| S4-S5 | Signal quality metrics deep audit | 7 | ✅ Complete |
| B | `app/ml`, `app/analytics`, `app/ai` | 27 | ✅ Complete — app/ml deep-audited Session 11 |
| C | `app/backtesting/`, `scripts/` (all subfolders) | 55 | ✅ Complete |
| D | `app/screening`, `app/options`, `app/indicators`, `utils/` | 27 | ✅ Complete — reconciled Session 9 |
| E | `tests/`, `docs/`, `migrations/`, `models/`, root files | 30 | ✅ Complete |
| Cross-Batch | Overlap analysis across all batches | all | ✅ Current |
| **Session 9** | **Full live-repo reconciliation vs registry** | **all** | **✅ Complete 2026-03-25** |
| **Session 10** | **Hotfix logging + pending queue #8/#9/#10 closed** | **3 items** | **✅ Complete 2026-03-25** |
| **Session 11** | **app/ml line-by-line deep audit — BUG-ML-1/2/6 fixed** | **3 fixes + 1 new file** | **✅ Complete 2026-03-27** |
| **Session 12** | **app/mtf line-by-line deep audit — BUG-MTF-1/2/3 fixed** | **3 fixes across 2 files** | **✅ Complete 2026-03-27** |
| **Session 13** | **app/core/sniper.py + scanner.py deep audit — 2 confirmed fixes, 3 already-clean** | **2 new items confirmed** | **✅ Complete 2026-03-29** |
| **Session 14** | **app/risk + app/core/sniper_pipeline.py + arm_signal.py deep audit — BUG-RISK-1, BUG-SP-1/SP-2, BUG-ARM-1 fixed** | **4 fixes across 4 files** | **✅ Complete 2026-03-30** |
| **Session 15** | **app/core/armed_signal_store.py + watch_signal_store.py line-by-line audit — BUG-ASS-1/2 noted (non-crashing), BUG-WSS-1/2/3 fixed** | **3 fixes in 1 file** | **✅ Complete 2026-03-31** |
| **Session 16** | **app/core remaining 6 files: thread_safe_state.py, sniper_log.py, logging_config.py, analytics_integration.py, health_server.py, eod_reporter.py — 10 bugs fixed across 5 files, 1 file fully clean** | **10 fixes across 5 files** | **✅ Complete 2026-03-31** |

---

## Implemented Changes Log

| # | Date | Session | File | Change | Commit SHA | Impact |
|---|------|---------|------|--------|-----------|--------|
| 1 | 2026-03-16 | S0 | `app/validation/cfw6_confirmation.py` | 🔧 FIXED: VWAP formula corrected. | `95be3ae` | Live bug fix |
| 2 | 2026-03-16 | S1 | `app/discord_helpers.py` | Converted to re-export shim. Fixed `send_options_signal_alert` bug. | `a629a84` | Live bug fix + legacy compat |
| 3 | 2026-03-16 | S1 | `app/ml/check_database.py` | Moved to `scripts/database/check_database.py`. | `3e4681a` / `aeae51d` | Clean separation |
| 4 | 2026-03-16 | S1 | `app/validation/volume_profile.py` | 5-min TTL cache + module docstring. | `cea9180` | Perf improvement + clarity |
| 5 | 2026-03-16 | S2 | `app/data/database.py` | Converted to re-export shim over `db_connection.py`. | `9cd17f5` | All callers use production pool |
| 6 | 2026-03-16 | S2 | `.gitignore` | Added `models/signal_predictor.pkl` exclusion. | `5828488` | Prevents binary tracking |
| 7 | 2026-03-16 | S3 | `tests/test_task10_backtesting.py` | Renamed → `tests/test_backtesting_extended.py`. | `dd750bb` / `0454fd4` | Cleaner test discovery |
| 8 | 2026-03-16 | S3 | `tests/test_task12.py` | Renamed → `tests/test_premarket_scanner_v2.py`. | `dd750bb` / `7944437` | Cleaner test discovery |
| 9 | 2026-03-16 | S4 | `app/core/arm_signal.py` | Wired `record_trade_executed()`. TRADED funnel stage now records. | pre-confirmed | Funnel stats now complete |
| 10 | 2026-03-16 | S4 | `app/signals/signal_analytics.py` | Added `get_rejection_breakdown()`, `get_hourly_funnel()`, `get_discord_eod_summary()`. | pre-confirmed | Full metrics instrumentation |
| 11 | 2026-03-16 | S4 | `app/filters/entry_timing_optimizer.py` | DELETED — exact duplicate of `entry_timing.py`. | `d1821d1` | -1 file, 4.8 KB |
| 12 | 2026-03-16 | S4 | `app/filters/options_dte_filter.py` | DELETED — superseded by `greeks_precheck.py`. | `3abfdd5` | -1 file, 5.3 KB; yfinance removed |
| 13 | 2026-03-16 | S4 | `app/core/sniper.py` | Wired `funnel_analytics` on all 3 scan paths. | `f5fd87b` | Funnel fires on every scan |
| 14 | 2026-03-16 | S4 | `requirements.txt` | Removed `yfinance>=0.2.40`. | [this commit] | Faster deploys |
| 15 | 2026-03-16 | S5 | `app/core/confidence_model.py` | DELETED — dead stub, zero callers, superseded by `ai_learning.py`. | `b99a63a` | Dead code removed |
| 16 | 2026-03-16 | S6 | `app/ml/analyze_signal_failures.py` | 📦 MOVED → `scripts/analysis/analyze_signal_failures.py`. | `42126d5` / `f6254b5` | Dev tool in correct location |
| 17 | 2026-03-16 | S6 | `app/ml/train_from_analytics.py` | 📦 MOVED → `scripts/ml/train_from_analytics.py`. | `42126d5` / `2f586e6` | Dev tool in correct location |
| 18 | 2026-03-16 | S6 | `app/ml/train_historical.py` | 📦 MOVED → `scripts/ml/train_historical.py`. | `42126d5` / `dc9a8db` | Dev tool in correct location |
| 19 | 2026-03-17 | S7 | `docs/AUDIT_REGISTRY.md` | Batch C complete — all `app/backtesting/` and `scripts/` audited. | this commit | Registry current |
| 20 | 2026-03-17 | S8 | `docs/AUDIT_REGISTRY.md` | Batch D + E complete. | this commit | Registry current |
| 21 | 2026-03-25 | S9 | `app/options/options_intelligence.py` | 🔧 FIXED: `get_chain()` dead-code in cache branch removed. | `edb6ba9` | Runtime bug fix |
| 22 | 2026-03-25 | S9 | `app/validation/greeks_precheck.py` | 🔧 FIXED: Missing `ZoneInfo` import added. | `08648df` | Runtime bug fix |
| 23 | 2026-03-25 | S9 | `app/signals/breakout_detector.py` | 🔧 FIXED: `resistance_source` NameError + duplicate PDH/PDL resolved. | `df2e625` | Runtime bug fix |
| 24 | 2026-03-25 | S9 | `docs/AUDIT_REGISTRY.md` | Full live-repo reconciliation. | this commit | Registry current |
| 25 | 2026-03-25 | S10 | `app/screening/watchlist_funnel.py` | 🔧 FIXED: spurious `()` on `datetime.now(tz=ET)` — crashing every pre-market cycle. | manual patch | Critical runtime crash fix |
| 26 | 2026-03-25 | S10 | `app/core/scanner.py` | 🔧 FIXED: `_run_analytics()` missing `conn=None` parameter. | manual patch | Critical runtime crash fix |
| 27 | 2026-03-25 | S10 | `app/ml/metrics_cache.py` | 🔧 FIXED: Raw SQLAlchemy pool replaced with `get_conn()`/`return_conn()`. | manual patch | Connection leak eliminated |
| 28 | 2026-03-27 | S11 | `app/ml/metrics_cache.py` | 🔧 FIXED BUG-ML-2: `%(since)s` named param → `ph()` positional + tuple. | `900e211` | ML feature correctness |
| 29 | 2026-03-27 | S11 | `app/ml/ml_signal_scorer_v2.py` | 🔧 FIXED BUG-ML-1: Created missing file — Gate 5 was silently dead. | `0fad513` | Gate 5 ML now functional |
| 30 | 2026-03-27 | S11 | `app/analytics/performance_monitor.py` | 🔧 FIXED BUG-ML-6: `_consecutive_losses` counter wired + Discord alert. | `74ce832` | Risk control now active |
| 31 | 2026-03-27 | S11 | `docs/AUDIT_REGISTRY.md` | Session 11 logged. | `f4fc398` | Registry current |
| 32 | 2026-03-27 | S12 | `app/mtf/mtf_compression.py` | 🔧 FIXED BUG-MTF-1: `compress_to_1m()` direction-aware high/low step placement. | `6fc7c7b` | FVG signal quality fix |
| 33 | 2026-03-27 | S12 | `app/mtf/mtf_fvg_priority.py` | 🔧 FIXED BUG-MTF-2: volume check moved from `c2` → `c1` (impulse bar). | `137f36f` | FVG volume filter correctness |
| 34 | 2026-03-27 | S12 | `app/mtf/mtf_fvg_priority.py` | 🔧 FIXED BUG-MTF-3: `get_full_mtf_analysis()` now builds `15m`+`30m` bars. | `137f36f` | Higher-TF FVG detection now active |
| 35 | 2026-03-29 | S13 | `app/core/sniper.py` | ✅ CONFIRMED: `clear_bos_alerts()` public API present. `_orb_classifications` dead block already absent. | live | EOD dedup reset works |
| 36 | 2026-03-29 | S13 | `app/core/scanner.py` | ✅ CONFIRMED: `clear_bos_alerts()` imported + called at EOD. Dead functions already absent. Full line-by-line audit complete — no bugs found. | live | Scanner EOD reset complete |
| 37 | 2026-03-30 | S14-pre | `models/signal_predictor.pkl` + `models/training_dataset.csv` | ✅ CONFIRMED never tracked — `.gitignore` rule from S2 effective. | n/a | Items #13 + #14 closed |
| 38 | 2026-03-30 | S14-pre | `s16_helpers.txt` | ❌ DELETED root staging file — duplicate of `app/risk/position_helpers.py`. | `2cb2020` | Root cleaned |
| 39 | 2026-03-30 | S14-pre | `s16_trade.txt` | ❌ DELETED root staging file — duplicate of `app/risk/trade_calculator.py`. | `09f25f8` | Root cleaned |
| 40 | 2026-03-30 | S14-pre | `s16_vix.txt` | ❌ DELETED root staging file — duplicate of `app/risk/vix_sizing.py`. | `72abc33` | Root cleaned |
| 41 | 2026-03-30 | S14 | `app/risk/risk_manager.py` | 🔧 FIXED BUG-RISK-1: `_reject()` refactored — removed redundant `compute_stop_and_targets()` call on every early-gate rejection. | `5f651ff` | Perf + correctness |
| 42 | 2026-03-30 | S14 | `app/risk/position_manager.py` | ✅ AUDIT COMPLETE — no new bugs found. All prior fixes confirmed. | live | No changes needed |
| 43 | 2026-03-30 | S14 | `app/core/sniper_pipeline.py` | 🔧 FIXED BUG-SP-1: TIME gate moved above RVOL fetch. | `7f5b377` | Perf fix |
| 44 | 2026-03-30 | S14 | `app/core/sniper_pipeline.py` + `app/core/signal_scorecard.py` | 🔧 FIXED BUG-SP-2: `confidence_base` wired into scorecard. `_score_cfw6_confidence()` added. Max score 85→95. | `7f5b377` / `032ffcc` | Signal quality improvement |
| 45 | 2026-03-30 | S14 | `app/core/arm_signal.py` | 🔧 FIXED BUG-ARM-1: Module docstring moved above `import logging`. | `0165db5` | Cosmetic / introspection fix |
| 46 | 2026-03-30 | S14 | `app/core/arm_signal.py` | ✅ BUG-ARM-2 RETRACTED — `sniper_log.py` confirmed live in repo. | live | No action needed |
| 47 | 2026-03-31 | S15 | `app/core/armed_signal_store.py` | ⚠️ BUG-ASS-1 NOTED (non-crashing): `logger` assigned after last import — cosmetic. No fix. | live | Non-crashing cosmetic |
| 48 | 2026-03-31 | S15 | `app/core/armed_signal_store.py` | ⚠️ BUG-ASS-2 NOTED (non-crashing): Redundant `safe_execute` re-import inside `clear_armed_signals()`. No fix. | live | Non-crashing cosmetic |
| 49 | 2026-03-31 | S15 | `app/core/watch_signal_store.py` | 🔧 FIXED BUG-WSS-1: All error-path `logger.info` → `logger.warning`. | `19fc732` | Log level consistency |
| 50 | 2026-03-31 | S15 | `app/core/watch_signal_store.py` | 🔧 FIXED BUG-WSS-2: Stray `print()` → `logger.info()` in `_load_watches_from_db()`. | `19fc732` | Logging hygiene |
| 51 | 2026-03-31 | S15 | `app/core/watch_signal_store.py` | 🔧 FIXED BUG-WSS-3: Empty `()` tuple removed from full-table DELETE. | `19fc732` | Style consistency |
| 52 | 2026-03-31 | S16 | `app/core/thread_safe_state.py` | 🔧 FIXED BUG-TSS-1: `increment_validator_stat()` now logs `logger.warning` on unknown stat name. Previously silently dropped — typos at call sites were invisible. | `b65deb9` | Data integrity visibility |
| 53 | 2026-03-31 | S16 | `app/core/thread_safe_state.py` | 🔧 FIXED BUG-TSS-2: `_last_dashboard_check` and `_last_alert_check` initialized with `datetime.now()` (naive). Changed to `datetime.now(ZoneInfo("America/New_York"))`. Naive vs ET-aware comparison raises `TypeError` at runtime. Added `from zoneinfo import ZoneInfo` import. | `b65deb9` | Runtime crash prevention |
| 54 | 2026-03-31 | S16 | `app/core/thread_safe_state.py` | 🔧 FIXED BUG-TSS-3: `logger` assignment moved to after all imports (cosmetic consistency). | `b65deb9` | Style consistency |
| 55 | 2026-03-31 | S16 | `app/core/thread_safe_state.py` | 🔧 FIXED BUG-TSS-4: Added missing module-level `get_all_armed_signals()` and `get_all_watching_signals()` wrappers. Module-level API was incomplete — callers using `get_state().get_all_*()` still worked but the module-level shortcut was absent. | `b65deb9` | API completeness |
| 56 | 2026-03-31 | S16 | `app/core/sniper_log.py` | 🔧 FIXED BUG-SL-1: Replaced `except Exception: pass` with `except Exception as e: print(...)` fallback. Pure logging function — arm path never blocked. Railway stdout now surfaces any logger failure. | `aafef1` | Visibility improvement |
| 57 | 2026-03-31 | S16 | `app/core/logging_config.py` | 🔧 FIXED BUG-LC-1: Added `logger = logging.getLogger(__name__)` at module scope. Previously used inline `logging.getLogger(__name__).info(...)` at end of `setup_logging()`. Now consistent with all other `app/core` files. | `4ff5fba` | Style + grep consistency |
| 58 | 2026-03-31 | S16 | `app/core/analytics_integration.py` | 🔧 FIXED BUG-AI-1: Replaced bare `logging.warning/logging.info` module-level calls with `logger = logging.getLogger(__name__)`. Log lines previously appeared as `root` logger — now correctly namespaced as `app.core.analytics_integration`. | `4ff5fba` | Railway log grep correctness |
| 59 | 2026-03-31 | S16 | `app/core/analytics_integration.py` | 🔧 FIXED BUG-AI-2: `get_today_stats()` was accessing `_tracker.session_signals` directly (tight coupling, breaks on rename). Now uses `_tracker.get_funnel_stats().get("unique_tickers", 0)` — public API only. | `4ff5fba` | Decoupling / future-proofing |
| 60 | 2026-03-31 | S16 | `app/core/analytics_integration.py` | 🔧 FIXED BUG-AI-3: `check_scheduled_tasks()` midnight reset block reset `daily_reset_done` but NOT `eod_report_done`. On multi-day runs the EOD report would fire once then never again. Added `self.eod_report_done = False` to midnight block. | `4ff5fba` | **Real bug — EOD report would stop firing after day 1** |
| 61 | 2026-03-31 | S16 | `app/core/health_server.py` | 🔧 FIXED BUG-HS-1: Added blank line between `import logging` and `logger` assignment for visual consistency. | `4ff5fba` | Style consistency |
| 62 | 2026-03-31 | S16 | `app/core/health_server.py` | 🔧 FIXED BUG-HS-2: Added `from __future__ import annotations` so `int \| None` / `threading.Thread \| None` union syntax is safe on Python < 3.10. Railway runs 3.11 — no runtime risk — but forward/backward compatible and consistent with `eod_reporter.py`. | `4ff5fba` | Forward compatibility |
| 63 | 2026-03-31 | S16 | `app/core/eod_reporter.py` | ✅ AUDIT COMPLETE — fully clean. All error levels correct, nested try/except correct, deferred `signal_tracker` import correct, `print()` replaced with `logger.info()` confirmed, `clear_session_cache()` called at EOD confirmed. | live | No changes needed |

---

## Pending Actions Queue

| # | Priority | File | Action | Status |
|---|----------|------|--------|--------|
| 1–10 | ✅ DONE | Various | See log above | ✅ |
| 11 | 🟡 MEDIUM | `scripts/backtesting/backtest_v2_detector.py` | Verify vs `backtest_realistic_detector.py` — possibly superseded | ⏳ Open |
| 12 | 🟢 LOW | `scripts/audit_repo.py` | QUARANTINE — one-time audit script, superseded by this registry | ⏳ Open |
| 15 | 🟢 LOW | `market_memory.db` | Verify if replaced by PostgreSQL on Railway or still active | ⏳ Open |
| 16 | 🟢 LOW | `scripts/war_machine.db` | Verify if stale vs root `war_machine.db` | ⏳ Open |
| 17 | 🟢 LOW | `audit_reports/venv/` | Venv accidentally committed — should be gitignored/removed | ⏳ Open |
| 21 | 🟡 MEDIUM | `app/ml/ml_trainer.py` | BUG-ML-3: Platt calibration + threshold on same slice — data leakage | ⏳ Open |
| 22 | 🟡 MEDIUM | `app/validation/cfw6_gate_validator.py` | BUG-ML-4: `get_validation_stats()` permanent stub — wire or delete | ⏳ Open |
| 23 | 🟢 LOW | `app/ml/ml_confidence_boost.py` | BUG-ML-5: `.iterrows()` in logging loop — replace with `itertuples()` | ⏳ Open |

---

## File Necessity Assessment — app/core (Session 16)

> Every file below is evaluated: **Is it 100% necessary for War Machine to function?**

| File | Necessary? | Reason | If Removed |
|------|-----------|--------|------------|
| `__init__.py` | ✅ YES | Python package marker — without it `app.core.*` imports all fail | Entire `app/core` breaks at import |
| `__main__.py` | ✅ YES | Railway entrypoint shim — `python -m app.core` calls this | Railway can't start the process |
| `scanner.py` | ✅ YES | Main scan loop — the process IS this file | System doesn't run |
| `sniper.py` | ✅ YES | Signal detection engine called every scan cycle | No signals detected |
| `sniper_pipeline.py` | ✅ YES | Gate chain (RVOL, time, CFW6, scorecard, risk) — extracted from sniper.py | All signals pass without filtering |
| `signal_scorecard.py` | ✅ YES | 0–100 scoring gate — arming threshold enforced here | No confidence scoring; all signals arm |
| `arm_signal.py` | ✅ YES | Opens positions and triggers Discord alerts | No trades execute |
| `armed_signal_store.py` | ✅ YES | Thread-safe + DB-backed armed signal state — survives restarts | Armed signals lost on restart |
| `watch_signal_store.py` | ✅ YES | Pre-armed signal store (BOS watching state) | Watch phase broken; signals skip directly to arm |
| `thread_safe_state.py` | ✅ YES | Shared in-memory state for all threads — singleton accessed by scanner + sniper | Race conditions on all shared state |
| `sniper_log.py` | ✅ YES | Imported by `arm_signal.py` at module level — missing file = `ImportError` on every arm attempt (confirmed BUG-ARM-2 / FIX 2026-03-26) | All arming crashes with ImportError |
| `logging_config.py` | ✅ YES | Called once in `__main__.py` — without it all loggers use basicConfig defaults and Railway logs lose module-name namespacing | Logs become ungrepped root logger noise |
| `analytics_integration.py` | ✅ YES | Called by `scanner.py` to route every signal through the analytics funnel | Signal lifecycle events stop recording; EOD report is empty |
| `eod_reporter.py` | ✅ YES | Called by `scanner.py` at market close — sends EOD Discord embed + clears session cache | EOD Discord reports stop; session cache never cleared (memory leak) |
| `health_server.py` | ✅ YES | Railway healthcheck — without it Railway thinks a dead scanner is healthy and never restarts it | Silent failures go undetected; Railway never auto-restarts |

**Result: All 15 files in `app/core` are 100% necessary. No candidates for removal.**

---

## thread_safe_state.py — Audit Results (S16, 2026-03-31)

> Full line-by-line audit complete. 4 bugs fixed in commit `b65deb9`.

| Check | Result |
|-------|--------|
| Module docstring present and accurate | ✅ Correct |
| Double-checked locking singleton pattern | ✅ Correct |
| `_initialize()` called only inside inner lock | ✅ Correct |
| 5 distinct lock domains (no cross-contamination) | ✅ Correct |
| `clear_armed_signals()` resets `_armed_loaded = False` inside lock | ✅ Correct and critical |
| `clear_watching_signals()` resets `_watches_loaded = False` inside lock | ✅ Correct |
| `get_all_*()` methods return `.copy()` | ✅ Defensive copy — callers can't mutate internal state |
| `track_validation_call()` is atomic | ✅ No TOCTOU |
| BUG-TSS-1: `increment_validator_stat()` silent no-op on unknown stat | ✅ FIXED `b65deb9` — `logger.warning` on unknown key |
| BUG-TSS-2: `_last_dashboard_check`/`_last_alert_check` naive datetime | ✅ FIXED `b65deb9` — `datetime.now(ZoneInfo("America/New_York"))` + ZoneInfo import |
| BUG-TSS-3: `logger` before imports (cosmetic) | ✅ FIXED `b65deb9` — moved after all imports |
| BUG-TSS-4: Missing `get_all_armed_signals()` / `get_all_watching_signals()` module-level wrappers | ✅ FIXED `b65deb9` — both added |

---

## sniper_log.py — Audit Results (S16, 2026-03-31)

> Full audit complete. 1 cosmetic fix applied.

| Check | Result |
|-------|--------|
| Module docstring present + FIX history accurate | ✅ Correct |
| `log_proposed_trade()` wrapped in try/except (arm path never blocked) | ✅ Correct |
| Log format includes `[PROPOSED-TRADE]` grep key | ✅ Consistent |
| `[OR]` / `[INTRADAY]` mode tags match `watch_signal_store.py` | ✅ Consistent |
| No side effects, pure logging utility | ✅ Correct |
| BUG-SL-1: `except Exception: pass` → fallback `print()` | ✅ FIXED `aafef1` |

---

## logging_config.py — Audit Results (S16, 2026-03-31)

> Full audit complete. 1 cosmetic fix applied.

| Check | Result |
|-------|--------|
| `_CONFIGURED` idempotency guard | ✅ Correct |
| `LOG_LEVEL` env var safe fallback | ✅ `getattr(logging, raw_level, logging.INFO)` |
| `root.handlers.clear()` before adding handler | ✅ Prevents duplicate handlers |
| `sys.stdout` (not stderr) | ✅ Railway captures stdout |
| `asyncio` removed from `_QUIET_LOGGERS` | ✅ Confirmed (prior audit fix) |
| BUG-LC-1: Inline `logging.getLogger(__name__).info()` → module-level `logger` | ✅ FIXED `4ff5fba` |

---

## analytics_integration.py — Audit Results (S16, 2026-03-31)

> Full audit complete. 3 bugs fixed — 1 real (BUG-AI-3), 2 style/decoupling.

| Check | Result |
|-------|--------|
| `_TRACKER_AVAILABLE` guard on all public methods | ✅ Correct |
| No-op fallback returns consistent values | ✅ `process_signal` returns `1` in no-op mode |
| `check_scheduled_tasks()` uses `ZoneInfo("America/New_York")` | ✅ FIX #35 confirmed |
| `monitor_active_signals()` documented no-op placeholder | ✅ Correct |
| BUG-AI-1: Bare `logging.*` calls → `logger = logging.getLogger(__name__)` | ✅ FIXED `4ff5fba` — logs now namespaced correctly |
| BUG-AI-2: `_tracker.session_signals` direct access → `get_funnel_stats()` | ✅ FIXED `4ff5fba` — decoupled from internal attribute |
| BUG-AI-3: `eod_report_done` never reset at midnight | ✅ FIXED `4ff5fba` — **real bug: EOD report would stop after day 1 on multi-day runs** |

---

## health_server.py — Audit Results (S16, 2026-03-31)

> Full audit complete. 2 cosmetic/compatibility fixes applied.

| Check | Result |
|-------|--------|
| FIX #54 `_started` double-call guard | ✅ Confirmed |
| `_is_market_hours()` called once, result reused | ✅ Prior audit refactor confirmed |
| `do_GET` handles 404 for unknown paths | ✅ Correct |
| `log_message` suppressed | ✅ Prevents Railway log spam |
| `Content-Length` header set | ✅ Good HTTP practice |
| `health_heartbeat()` seeded at startup | ✅ Prevents false 503 on boot |
| BUG-HS-1: Blank line between `import logging` and `logger` | ✅ FIXED `4ff5fba` — style consistency |
| BUG-HS-2: `from __future__ import annotations` added for union type syntax | ✅ FIXED `4ff5fba` — forward compatibility |

---

## eod_reporter.py — Audit Results (S16, 2026-03-31)

> Full audit complete. **Fully clean — no changes needed.**

| Check | Result |
|-------|--------|
| `from __future__ import annotations` present | ✅ Required for `str \| None` on Python < 3.10 |
| `try/except ImportError` for `zoneinfo` | ✅ Backward compat guard |
| Delegates to `risk_manager` (not direct DB) | ✅ Correct abstraction |
| Nested try/except for top-performers block | ✅ Correct — non-critical path isolated |
| `signal_tracker` deferred import inside function | ✅ Prevents circular import |
| `clear_session_cache()` called at EOD | ✅ No memory leak |
| `print()` replaced with `logger.info()` (FIX #36) | ✅ Confirmed |
| Error severity mapping correct | ✅ `top-performers` → warning, stats/analytics → error |
| `if __name__ == "__main__"` standalone test block | ✅ Correct |

---

## armed_signal_store.py — Audit Results (S15, 2026-03-31)

> Full line-by-line audit complete. 2 non-crashing cosmetic findings noted. No fix applied.

| Check | Result |
|-------|--------|
| Module comment block above imports | ✅ Correct |
| BUG-ASS-1: `import logging` is last import; `logger` assigned inline below it | ⚠️ NOTED — non-crashing, cosmetic. No fix. |
| BUG-ASS-2: Redundant `safe_execute` re-import inside `clear_armed_signals()` | ⚠️ NOTED — non-crashing, cosmetic. No fix. |
| `_ensure_armed_db()` error path uses `logger.warning` | ✅ Correct (previously upgraded) |
| `_persist_armed_signal()` — all 11 fields inserted | ✅ Confirmed |
| `ON CONFLICT` upsert — `saved_at` uses `CURRENT_TIMESTAMP` | ✅ Correct |
| `safe_execute` on all DML | ✅ Consistent |
| `_remove_armed_from_db()` parametrized | ✅ Confirmed |
| `_cleanup_stale_armed_signals()` — uses `position_manager.get_open_positions()` | ✅ Correct |
| `safe_in_clause` on bulk delete | ✅ Confirmed |
| `_load_armed_signals_from_db()` dual-dialect branching | ✅ Correct |
| `row.get("validation_data")` dict-style access | ✅ Safe — `dict_cursor` confirmed |
| `_armed_load_lock` | ✅ Valid pattern |
| `_maybe_load_armed_signals()` lock wraps check | ✅ No double-load possible |

---

## watch_signal_store.py — Audit Results (S15, 2026-03-31)

> Full line-by-line audit complete. 3 bugs fixed in commit `19fc732`.

| Check | Result |
|-------|--------|
| FIX I `_watch_load_lock` present | ✅ Confirmed |
| FIX #55 state method names all 3 corrected | ✅ Confirmed |
| BUG-WSS-1: Error-path `logger.info` → `logger.warning` | ✅ FIXED `19fc732` |
| BUG-WSS-2: Stray `print()` in `_load_watches_from_db()` | ✅ FIXED `19fc732` |
| BUG-WSS-3: Empty `()` tuple on full-table DELETE | ✅ FIXED `19fc732` |
| `_strip_tz()` helper | ✅ Correct |
| `MAX_WATCH_BARS = 12` | ✅ Mirrors `sniper.py` |
| `_cleanup_stale_watches()` time-based cutoff | ✅ Correct |
| `cursor.rowcount` for deleted count | ✅ SQLite + PostgreSQL compat |
| `send_bos_watch_alert()` defers import | ✅ Deferred inside function |

---

## arm_signal.py — Audit Results (S14, 2026-03-30)

> Full line-by-line audit complete. 1 bug fixed, 1 false positive retracted.

| Check | Result |
|-------|--------|
| Stop-too-tight guard | ✅ Confirmed |
| All heavy imports deferred inside function | ✅ Confirmed |
| `open_position()` before Discord alert | ✅ Confirmed |
| `position_id == -1` guard suppresses alert | ✅ Confirmed |
| `record_trade_executed()` try/except non-fatal | ✅ Confirmed |
| BUG-ARM-1: docstring before logger assignment | ✅ FIXED `0165db5` |
| BUG-ARM-2: `sniper_log` import dead? | ✅ RETRACTED — `sniper_log.py` confirmed live |

---

## sniper_pipeline.py — Audit Results (S14, 2026-03-30)

| Check | Result |
|-------|--------|
| BUG-SP-1: TIME gate before RVOL fetch | ✅ FIXED `7f5b377` |
| BUG-SP-2: `confidence_base` wired into scorecard | ✅ FIXED `7f5b377` / `032ffcc` |
| All gates try/except guarded | ✅ Confirmed |
| Gate chain order correct | ✅ Confirmed |

---

## position_manager.py — Audit Results (S14, 2026-03-30)

| Check | Result |
|-------|--------|
| BUG-PM-1/2/3 | ✅ All confirmed fixed |
| FIX #4/7/8/9/12/13 | ✅ All confirmed present |
| All DB calls use `get_conn()`/`return_conn()` | ✅ Confirmed |

---

## LOCAL ACTIONS REQUIRED (Cannot Be Done via GitHub)

> ✅ All previously listed local actions are resolved.

---

## BATCH A1 — `app/core` (Runtime-Critical Core)

| File | Size | Role | Used By | Verdict | Notes |
|------|------|------|---------|---------|-------|
| `__init__.py` | 22 B | Package marker | All importers | ✅ KEEP | |
| `__main__.py` | 1.4 KB | Railway entrypoint shim | Railway start | ✅ KEEP | |
| `scanner.py` | 28.6 KB | Main scan loop | Entrypoint | ✅ KEEP | **PROHIBITED** — ✅ S13 AUDIT COMPLETE |
| `sniper.py` | 27.3 KB | Signal detection engine | `scanner.py` | ✅ KEEP | **PROHIBITED** — ✅ S13 AUDIT COMPLETE |
| `sniper_pipeline.py` | 14.9 KB | Signal gate chain | `sniper.py` | ✅ KEEP | **PROHIBITED** — ✅ S14 AUDIT COMPLETE. BUG-SP-1/2 fixed. |
| `signal_scorecard.py` | 12 KB | 0–100 scoring gate | `sniper.py`, `sniper_pipeline.py` | ✅ KEEP | **PROHIBITED** — ✅ Updated S14 (cfw6_score field, max 85→95). |
| `arm_signal.py` | 8.5 KB | Signal arming + trade open | `sniper.py` | ✅ KEEP | **PROHIBITED** — ✅ S14 AUDIT COMPLETE. BUG-ARM-1 fixed. |
| `armed_signal_store.py` | 9.3 KB | Armed signal DB + memory store | `sniper.py`, `scanner.py` | ✅ KEEP | ✅ S15 AUDIT COMPLETE. BUG-ASS-1/2 noted (cosmetic). |
| `watch_signal_store.py` | 10.4 KB | Watch signal DB + memory store | `sniper.py`, `scanner.py` | ✅ KEEP | ✅ S15 AUDIT COMPLETE. BUG-WSS-1/2/3 fixed. |
| `thread_safe_state.py` | 12.3 KB | Thread-safe singleton state | `scanner.py`, `sniper.py` | ✅ KEEP | ✅ S16 AUDIT COMPLETE. BUG-TSS-1/2/3/4 fixed. |
| `sniper_log.py` | 2.9 KB | Pre-arm trade logger | `arm_signal.py` | ✅ KEEP | ✅ S16 AUDIT COMPLETE. BUG-SL-1 fixed. |
| `logging_config.py` | 3.9 KB | Centralized logging setup | `__main__.py` | ✅ KEEP | ✅ S16 AUDIT COMPLETE. BUG-LC-1 fixed. |
| `analytics_integration.py` | 9.5 KB | Core↔analytics bridge | `scanner.py` | ✅ KEEP | ✅ S16 AUDIT COMPLETE. BUG-AI-1/2/3 fixed. |
| `eod_reporter.py` | 4.3 KB | EOD Discord reports + cache clear | `scanner.py` | ✅ KEEP | ✅ S16 AUDIT COMPLETE. Fully clean. |
| `health_server.py` | 5.6 KB | `/health` endpoint for Railway | Railway healthcheck | ✅ KEEP | **PROHIBITED** — ✅ S16 AUDIT COMPLETE. BUG-HS-1/2 fixed. |

**app/core: 15/15 KEEP. All 15 files 100% necessary. Session 16 complete.**

---

## BATCH A2 — Supporting Runtime Modules

### `app/notifications/` — 2/2 KEEP
### `app/risk/` — 7/7 KEEP

| File | Size | Role | Verdict | Notes |
|------|------|------|---------|-------|
| `__init__.py` | — | Package marker | ✅ KEEP | |
| `dynamic_thresholds.py` | — | Adaptive confidence floor | ✅ KEEP | **PROHIBITED** |
| `position_helpers.py` | — | Shared sizing helpers | ✅ KEEP | **PROHIBITED** |
| `position_manager.py` | ~24 KB | Sizing, circuit breaker, P&L, DB writes | ✅ KEEP | **PROHIBITED** — ✅ S14 AUDIT COMPLETE |
| `risk_manager.py` | ~14 KB | Unified risk orchestration | ✅ KEEP | **PROHIBITED** — ✅ S14 AUDIT COMPLETE. BUG-RISK-1 fixed. |
| `trade_calculator.py` | — | ATR-based stops + targets | ✅ KEEP | **PROHIBITED** |
| `vix_sizing.py` | — | VIX regime multiplier | ✅ KEEP | **PROHIBITED** |

### `app/data/` — 9/9 KEEP
### `app/signals/` — 5 KEEP, 1 FIXED (breakout_detector)
### `app/filters/` — 12 KEEP, 2 DELETED, 3 NEW

### `app/mtf/` — Session 12 deep audit complete

| File | Size | Role | Verdict | Notes |
|------|------|------|---------|-------|
| `__init__.py` | 0.8 KB | Package marker + re-exports | ✅ KEEP | |
| `bos_fvg_engine.py` | ~14 KB | BOS+FVG primary detector | ✅ KEEP | **PROHIBITED** |
| `mtf_validator.py` | ~6 KB | EMA 9/21 MTF trend alignment | ✅ KEEP | **PROHIBITED** |
| `mtf_integration.py` | ~14 KB | MTF convergence + Step 8.5 | ✅ KEEP | **PROHIBITED** |
| `mtf_compression.py` | 9.8 KB | Timeframe compression | ✅ KEEP | 🔧 FIXED S12 BUG-MTF-1 |
| `mtf_fvg_priority.py` | 15.9 KB | Highest-TF FVG resolver | ✅ KEEP | 🔧 FIXED S12 BUG-MTF-2+3 |
| `smc_engine.py` | ~17 KB | SMC context: CHoCH, OB, Phase | ✅ KEEP | **PROHIBITED** |

### `app/validation/` — 7/7 KEEP, 2 FIXED

---

## BATCH B — ML, Analytics, AI

### `app/ml/` — 7 active KEEP, 1 CREATED, 2 FIXED (Session 11)
### `app/analytics/` — 10/10 KEEP, 1 FIXED (performance_monitor)
### `app/ai/` — 2/2 KEEP

---

## BATCH C — Backtesting & Scripts

### `app/backtesting/` — 7/7 KEEP
### `scripts/` — 55 KEEP (net), 1 QUARANTINE pending, 1 REVIEW pending

---

## BATCH D — Screening, Options, Indicators, Utils

### `app/screening/` — 8/8 KEEP, 1 FIXED (watchlist_funnel)
### `app/options/` — 9 KEEP, 1 FIXED, 1 NEW
### `app/indicators/` — 5/5 KEEP
### `utils/` — 4/4 KEEP

---

## BATCH E — Tests, Docs, Migrations, Models, Root Files
