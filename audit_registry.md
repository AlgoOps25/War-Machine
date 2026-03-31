# War Machine — Master Audit Registry

> **Purpose:** Single source of truth for every file-by-file, line-by-line audit session.
> Every finding, fix, and status change is recorded here chronologically.
> Never delete entries — append only.
>
> **Size rule:** Keep this file under 90 KB. If it approaches that limit, archive
> completed sections to `audit_reports/AUDIT_ARCHIVE_<date>.md` and add a
> reference link here.

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

---

## Overall Folder Progress

| Folder | Files | Audited | Status |
|--------|-------|---------|--------|
| `app/` (root) | 1 | 1 | ✅ Complete — Session CORE-1 |
| `app/ai/` | 2 | 0 | ⬜ Pending |
| `app/analytics/` | 9 | 9 | ✅ Complete (prior sessions) |
| `app/backtesting/` | 7 | 0 | ⬜ Pending |
| `app/core/` | 15 | 11 | 🔄 In Progress — CORE-1 (6) + CORE-2 (3) + ASS-1 + WSS-1 |
| `app/data/` | — | — | ⬜ Pending |
| `app/filters/` | — | — | ⬜ Pending |
| `app/indicators/` | — | — | ⬜ Pending |
| `app/ml/` | 7 | 5 | ✅ Complete — Session ML-1 (2026-03-31) |
| `app/mtf/` | — | — | ⬜ Pending |
| `app/notifications/` | — | — | ⬜ Pending |
| `app/options/` | — | — | ⬜ Pending |
| `app/risk/` | — | — | ⬜ Pending |
| `app/screening/` | — | — | ⬜ Pending |
| `app/signals/` | 1 | 1 | 🔄 In Progress — `opening_range.py` audited S-OR-1 |
| `app/validation/` | — | — | ⬜ Pending |
| `audit_reports/` | 1 | — | Reference only |
| `backtests/` | — | — | ⬜ Pending |
| `docs/` | — | — | ⬜ Pending |
| `migrations/` | — | — | ⬜ Pending |
| `scripts/` | — | — | ⬜ Pending |
| `tests/` | — | — | ⬜ Pending |
| `utils/` | — | — | ⬜ Pending |
| Root config files | 8 | 0 | ⬜ Pending |

---

## Session CORE-2 — `app/core/` Pipeline Files
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Files audited:** 3 files
- `app/core/thread_safe_state.py`
- `app/core/signal_scorecard.py`
- `app/core/sniper_pipeline.py`

**Fixes applied:** None this session — 2 findings documented for fix-on-next-touch.

---

### `app/core/thread_safe_state.py`
**SHA:** `34ae63dc19f697c496adca2c991f45d1a7ae735f`
**Size:** ~12 KB
**Status:** ✅ Clean

**Purpose:** Double-checked locking singleton (`ThreadSafeState`) managing all global
mutable state: armed signals, watching signals, validator stats, validation call tracker,
and Phase 4 dashboard/alert timing. Module-level convenience wrappers expose the same
API surface without requiring callers to import the class directly.

**Architecture:**
- `ThreadSafeState.__new__` + `_lock` double-checked locking pattern — correct singleton
- Each state domain has its own dedicated `threading.Lock()` — no shared lock across domains (no deadlock risk)
- `_armed_lock`, `_watching_lock`, `_validator_stats_lock`, `_validation_tracker_lock`, `_monitoring_lock` — all distinct

**Checks passed:**
- `from __future__ import annotations` NOT present — no union types used, absence is correct ✅
- Import order: stdlib (`threading`, `typing`, `datetime`, `zoneinfo`, `logging`) → no third-party → no local ✅
- `logger = logging.getLogger(__name__)` correctly placed after all imports ✅ (BUG-TSS-3 fix confirmed)
- `_initialize()` called inside `__new__` under the class lock — thread-safe initialization ✅
- BUG-TSS-2 fix confirmed: `_last_dashboard_check` and `_last_alert_check` both initialized with `datetime.now(_et)` where `_et = ZoneInfo("America/New_York")` — ET-aware, no naive datetime ✅
- BUG-TSS-1 fix confirmed: `increment_validator_stat()` warns via `logger.warning` on unknown stat names — no silent no-op ✅
- BUG-TSS-4 fix confirmed: `get_all_armed_signals()` and `get_all_watching_signals()` module-level wrappers present ✅
- `get_all_armed_signals()` and `get_all_watching_signals()` return `.copy()` — callers cannot mutate internal dicts ✅
- `update_armed_signals_bulk()` and `update_watching_signals_bulk()` use `.update()` under the lock — atomic bulk load ✅
- `clear_armed_signals()` resets `_armed_loaded = False` — correct; DB re-load triggered on next access ✅
- `clear_watching_signals()` resets `_watches_loaded = False` — same ✅
- `update_watching_signal_field()` returns `False` when ticker not present (bool sentinel) — callers can detect missing tickers ✅
- `track_validation_call()` returns count (1 = first call, 2+ = duplicate) — useful for dedup detection ✅
- `get_validator_stats()` returns `.copy()` — safe ✅
- `reset_validator_stats()` zeros all keys via iteration — no key mismatch possible ✅
- `get_state()` convenience function returns singleton — backward compat maintained ✅
- Module-level wrappers exactly mirror the class methods they delegate to — no divergence ✅
- No stray `print()` calls
- No redundant imports

**No findings.**

---

### `app/core/signal_scorecard.py`
**SHA:** `5734267e86c03d43a33a503d415ab254afd3b43b`
**Size:** ~12 KB
**Status:** ⚠️ 1 minor finding (BUG-SC-1) — non-crashing, fix on next touch

**Purpose:** `SignalScorecard` dataclass + `build_scorecard()` factory. Scores all signal
contributors (grade, IVR, GEX, MTF, SMC, VWAP, sweep, OB, regime, CFW6 base, RVOL
ceiling) into a 0–95 total. Gate: score < 60 drops the signal.

**Architecture:**
- Pure scoring module — no DB, no threading, no side effects outside logging
- `build_scorecard()` wraps all scoring in a `try/except`; on crash returns score 59 (gate-blocking)
- `_score_rvol_ceiling()` defers `from utils import config` inside function body — avoids circular import at module load

**Checks passed:**
- Import order: stdlib (`dataclasses`, `typing`) → no third-party → no local. `logging` present, `logger` assigned immediately after — ⚠️ see BUG-SC-1
- `SCORECARD_GATE_MIN = 60` constant correctly exported — `sniper_pipeline.py` imports it
- `SignalScorecard.compute()` sums all 11 fields and builds breakdown string — count matches dataclass fields ✅
- Breakdown string includes all 11 contributors including `cfw6=` and `rvol_ceil=` — complete ✅
- `_score_grade()` dict lookup with `.get(grade, 8)` default — unknown grades get 8 (below minimum known grade B=10), correct fallback ✅
- `_score_ivr()`: `None` options_rec → 10.0 fallback (Phase 1.38c raised from 5) — documented ✅
- `_score_gex()`: `not gex_data.get("has_data")` guard before accessing `neg_gex_zone` — no KeyError risk ✅
- `_score_mtf_trend()`: 3-tier: >0.05 → 15, >0.0 → 10, else → 8. Phase 1.38c raised floor from 5 to 8 ✅
- `_score_smc()`: `None` → 7.0 neutral (not 0 — missing data ≠ bad signal) ✅
- `_score_cfw6_confidence()`: 5 tiers (0.80/0.70/0.60/0.50/else) — `None` → 5.0 neutral ✅
- `_score_regime()`: `not spy_regime` guard → 1.0 (not 0) — SPY data unavailable ≠ strong penalty ✅
- `_score_rvol_ceiling()`: `rvol >= ceiling` deducts -20 (pushes any ≥60 signal below gate) — backtest-validated ✅
- `_score_rvol_ceiling()` defers config import in `try/except` with `ceiling = 3.0` fallback — safe if config unavailable ✅
- `_check_confidence_inversion()` — A+ + RVOL < 1.2x warns at `logger.warning` — surfaced in Railway logs ✅
- `build_scorecard()` FIX P2: exception returns `SCORECARD_GATE_MIN - 1` (59) — crash blocks signal, does not accidentally pass it through at boundary ✅
- `build_scorecard()` logs scorecard at `logger.info` on success, `logger.warning` on crash — correct level hierarchy ✅
- No stray `print()` calls
- No redundant imports

**Findings:**

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-SC-1 | ⚠️ | `import logging` and `logger = logging.getLogger(__name__)` are on consecutive lines with no blank line separator (`logger = logging.getLogger(__name__)` immediately follows `import logging` with no blank line). Minor style inconsistency vs rest of codebase. No runtime impact. | ⬜ Fix on next touch |

---

### `app/core/sniper_pipeline.py`
**SHA:** `cb87b539c60aab3b05cc55409e81e4fe3f254f3a`
**Size:** ~14 KB
**Status:** ⚠️ 1 finding (BUG-SP-3) — non-crashing dead import, fix on next touch

**Purpose:** `_run_signal_pipeline()` — the 14-gate CFW6 signal pipeline extracted from
`sniper.py`. Runs TIME → RVOL → VWAP → DEAD ZONE → GEX → COOLDOWN → CFW6 →
MTF → SMC/SWEEP/OB → SCORECARD → STOP → ARM gates in order.

**Architecture:**
- Pure pipeline function — no class, no singleton, no module-level state
- All enrichment steps (SMC, sweep, OB) deferred inside `try/except` blocks — failures are non-fatal
- `**_unused_kwargs` absorbs legacy callers passing `state=` and `get_ticker_screener_metadata=` (FIX A)
- Returns `True` on arm completion, `False` on any gate rejection

**Checks passed:**
- `from __future__ import annotations` present ✅
- Import order: stdlib (`logging`, `datetime.time`, `zoneinfo`) → local utils (`config`, `time_helpers`, `bar_utils`) → app modules ✅
- `logger = logging.getLogger(__name__)` at module scope, after all imports ✅
- `_ET = ZoneInfo("America/New_York")` defined at module scope ✅
- Gate 1 TIME gate runs before any data fetch (BUG-SP-1 fix confirmed) — no wasted RVOL call on post-11am signals ✅
- Gate 3 RVOL floor uses `RVOL_SIGNAL_GATE` from `utils.config` — not a hardcoded literal ✅
- Gate 4 RVOL ceiling uses `RVOL_CEILING` from `utils.config` — not a hardcoded literal ✅
- Gate 4 is redundant with `_score_rvol_ceiling()` in scorecard but is intentional: hard reject before CFW6 work begins (avoids 5+ expensive gate calls for a known-bad signal) ✅
- `options_rec=None` default (FIX B) — all callers omit it, scorecard handles None gracefully ✅
- `confidence_base` from `grade_signal_with_confirmations()` wired into `build_scorecard()` as `cfw6_confidence_base` (BUG-SP-2 fix confirmed) — no longer discarded ✅
- `skip_cfw6_confirmation=True` path sets `grade="A"`, `confidence_base=0.65` — correct fallback values (A grade = 13pts, 0.65 = 5pts) ✅
- MTF block guards `bars_1m_raw` for `None` and empty before resampling — no crash on missing data ✅
- MTF counter-trend + RVOL < 1.8x → hard reject — correct gating logic ✅
- All 3 enrichment steps (SMC, sweep, OB) deferred with `try/except` → default on failure — pipeline never halts on enrichment errors ✅
- `build_scorecard()` receives all 12 parameters (including `rvol` and `cfw6_confidence_base`) — no missing args ✅
- `_confidence = min(0.85, max(0.60, _sc.score / 100.0))` — clipped correctly, no out-of-range confidence ✅
- `compute_stop_and_targets()` return `None` check — `None` drops signal cleanly before `arm_ticker()` is called ✅
- `arm_ticker()` called with all 16 required keyword arguments — no TypeError ✅ (FIX 1-6 from 2026-03-26 confirmed)
- FIX C confirmed: no duplicate `set_cooldown()` call after `arm_ticker()` — cooldown is handled inside `arm_ticker()` ✅
- FIX D confirmed: `return True` after `arm_ticker()` (arm_ticker returns None implicitly) — callers get a meaningful bool ✅
- No stray `print()` calls

**Findings:**

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-SP-3 | ⚠️ | `BEAR_SIGNALS_ENABLED` imported from `utils.config` at module scope (`from utils.config import RVOL_SIGNAL_GATE, RVOL_CEILING, BEAR_SIGNALS_ENABLED`) but never referenced anywhere in the file body. Dead import — no runtime impact but misleads readers into thinking there's a bear-signal gate in this file. | ⬜ Remove on next touch |

---

## Session CORE-1 — `app/core/` Bootstrap Files
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Files audited:** 6 files
- `app/__init__.py`
- `app/core/__init__.py`
- `app/core/__main__.py`
- `app/core/logging_config.py`
- `app/core/sniper_log.py`
- `app/core/eod_reporter.py`
- `app/core/health_server.py`

**Fixes applied:** None — all 6 files are clean. No commits required.

---

### `app/__init__.py`
**SHA:** `8f86f5e17250937b011f421c65f2b4355fc0337e` | **Size:** 54 B | **Status:** ✅ Clean
- Single comment, no logic, no imports.

### `app/core/__init__.py`
**SHA:** `16b2448aa04e3212eb530588bf6b7e9b333a4b7f` | **Size:** 22 B | **Status:** ✅ Clean
- Single comment, no logic, no imports.

### `app/core/__main__.py`
**SHA:** `8cbad489dce74f37d1fe599654576bc8c299849b` | **Size:** 1,352 B | **Status:** ✅ Clean
- Boot order correct: logging → health server → scanner import → loop. No dead imports, no stray prints.

### `app/core/logging_config.py`
**SHA:** `d22f6ca12a8389edb4ad19a46904d6aacc85259f` | **Size:** 3,495 B | **Status:** ✅ Clean
- `_CONFIGURED` guard idempotent. `root.handlers.clear()` prevents duplicate handlers. `_QUIET_LOGGERS` correct. BUG-LC-1 fix confirmed.

### `app/core/sniper_log.py`
**SHA:** `bdcb22e04ede41c75bee904d3ea8706ce98ad7a3` | **Size:** 2,855 B | **Status:** ✅ Clean
- Never raises. Fallback `print()` intentional (BUG-SL-1). All 6 parameters logged. Correct confidence × 100 display.

### `app/core/eod_reporter.py`
**SHA:** `84d9fe798b6f073d4734cedac18fe72225a0ab38` | **Size:** 4,267 B | **Status:** ✅ Clean
- Independent `try/except` per block. ET-aware session_date. `clear_session_cache()` called. No stray prints.

### `app/core/health_server.py`
**SHA:** `bafbaa9fbd33b55617b33061b6240cebef36a464` | **Size:** 6,087 B | **Status:** ✅ Clean
- `_started` guard prevents double-bind. `_is_market_hours()` called once per request. Heartbeat seeded at startup. BUG-HS-1/2 confirmed.

---

## Session ML-1 — `app/ml/` Full Audit
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Files audited:** 5 Python files (`__init__.py`, `metrics_cache.py`, `ml_confidence_boost.py`, `ml_signal_scorer_v2.py`, `ml_trainer.py`)
**Docs skipped (read-only):** `INTEGRATION.md`, `README.md`
**Fixes applied commit:** `5255863a1844eb34ca76ef9bbb1b9a2241173432`

---

### `app/ml/__init__.py`
**SHA:** `7cc0e794a5949749e57a5c2867493af623e92ac2` | **Size:** 27 B | **Status:** ✅ Clean

### `app/ml/metrics_cache.py`
**SHA:** `f2dbbf05b0c60321520095d2b2531477359b790d` | **Size:** 2,628 B | **Status:** ✅ Clean
- `get_conn()`/`return_conn()` with `conn = None` guard. `ph()` dual-dialect. `logger.warning` on error. ET-aware timestamps.

### `app/ml/ml_confidence_boost.py`
**SHA post-fix:** commit `5255863` | **Size:** ~6,522 B | **Status:** ✅ Fixed in ML-1

| ID | Fix | Description |
|----|-----|-------------|
| BUG-MCB-1 | ✅ | `import logging` moved to top of import block |
| BUG-MCB-2 | ✅ | 3 error-path `logger.info` → `logger.warning` |

### `app/ml/ml_signal_scorer_v2.py`
**SHA:** `42392e748e9bf5c7e397666deed162f62a099103` | **Size:** 7,599 B | **Status:** ✅ Clean
- Model resolution chain correct (HistGBM → XGBoost → heuristic). Feature vector zero-fills missing keys. `adx` defaults to 20.0. `-1.0` / `0.5` sentinels correct.

### `app/ml/ml_trainer.py`
**SHA post-fix:** commit `5255863` | **Size:** ~28,379 B | **Status:** ✅ Fixed in ML-1

| ID | Fix | Description |
|----|-----|-------------|
| BUG-MLT-1 | ✅ | `df = df.copy()` at top of `_prepare_features()` — CoW-safe |

---

## Session ASS-1 — `app/core/armed_signal_store.py`
**Date:** 2026-03-31 | **SHA:** `6263afa75a0249706aacf9f7c6bd4f14ba723442` | **Status:** ✅ Fixed in-file

| ID | Fix | Description |
|----|-----|-------------|
| BUG-ASS-1 | ✅ | `import logging` moved to top of import block |
| BUG-ASS-2 | ✅ | Removed redundant inner `import safe_execute` in `clear_armed_signals()` |

---

## Session WSS-1 — `app/core/watch_signal_store.py`
**Date:** 2026-03-31 | **SHA:** `061e64817f36a6c7c46c577d6dd9f14b8d0260f2` | **Status:** ✅ Fixed in-file

| ID | Fix | Description |
|----|-----|-------------|
| BUG-WSS-1 | ✅ | 7 error-path `logger.info` → `logger.warning` |
| BUG-WSS-2 | ✅ | Stray `print()` → `logger.info()` in `_load_watches_from_db()` |
| BUG-WSS-3 | ✅ | Removed empty `()` from `safe_execute` DELETE in `clear_watching_signals()` |

---

## Session S-OR-1 — `app/signals/opening_range.py`
**Date:** 2026-03-31 | **SHA:** `8c141c9a852c8cd1b11d80bdd6cf5f810615ee99` | **Status:** ✅ Clean (2 minor findings pending)

**Purpose:** `OpeningRangeDetector` — classifies 9:30–9:40 OR as TIGHT/NORMAL/WIDE/DYNAMIC.
Phase B1 adds secondary range (10:00–10:30). Used by `sniper.py` for breakout anchor levels.

**Key checks:** `_to_et_time()` handles all datetime variants. DYNAMIC TTL correctly expires.
Price sanity clamp uses `np.median`. `clear_cache()` clears all 3 dicts. `get_secondary_range_levels()` returns `{}` not `None`.

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-OR-1 | ⚠️ | `should_scan_now()`: `or_data` computed but never used — dead code. Always returns `True`. | ⬜ Fix on next touch |
| BUG-OR-2 | ⚠️ | `detect_breakout_after_or()`: `from utils import config` imported twice inside same function | ⬜ Fix on next touch |

---

## Open Fix Queue

All findings below are confirmed non-crashing unless marked 🐛/🔴.
Priority: fix during the session that next touches the owning file.

| Fix ID | File | Severity | Description | Session Target |
|--------|------|----------|-------------|----------------|
| BUG-SC-1 | `app/core/signal_scorecard.py` | ⚠️ | `import logging` and `logger =` on consecutive lines — no blank separator (style inconsistency) | Next `signal_scorecard.py` touch |
| BUG-SP-3 | `app/core/sniper_pipeline.py` | ⚠️ | `BEAR_SIGNALS_ENABLED` imported at module scope but never used in file body — dead import | Next `sniper_pipeline.py` touch |
| BUG-OR-1 | `app/signals/opening_range.py` | ⚠️ | `should_scan_now()` computes `or_data` but never uses it — dead code | Next `signals/` session |
| BUG-OR-2 | `app/signals/opening_range.py` | ⚠️ | `detect_breakout_after_or()` imports `from utils import config` twice inside function | Next `signals/` session |

---

## Completed Fixes Log

| Fix ID | File | Commit | Description |
|--------|------|--------|-------------|
| BUG-WSS-1 | `app/core/watch_signal_store.py` | in-file | Changed 7 error-path `logger.info` → `logger.warning` |
| BUG-WSS-2 | `app/core/watch_signal_store.py` | in-file | Stray `print()` → `logger.info()` in `_load_watches_from_db()` |
| BUG-WSS-3 | `app/core/watch_signal_store.py` | in-file | Removed empty `()` from `safe_execute` DELETE |
| BUG-ASS-1 | `app/core/armed_signal_store.py` | in-file | `import logging` moved to top of import block |
| BUG-ASS-2 | `app/core/armed_signal_store.py` | in-file | Removed redundant inner `import safe_execute` |
| BUG-MCB-1 | `app/ml/ml_confidence_boost.py` | `5255863` | `import logging` moved to top of import block |
| BUG-MCB-2 | `app/ml/ml_confidence_boost.py` | `5255863` | 3 error-path `logger.info` → `logger.warning` |
| BUG-MLT-1 | `app/ml/ml_trainer.py` | `5255863` | `df = df.copy()` at top of `_prepare_features()` — CoW-safe |
| BUG-ML-2 | `app/ml/metrics_cache.py` | Session 11 | `pd.read_sql_query` → `ph()` abstraction, positional tuple params |
| BUG-ML-1 | `app/ml/ml_signal_scorer_v2.py` | Session 11 | File created — Gate 5 ImportError silent failure |
| BUG-#41 | `app/ml/ml_confidence_boost.py` | prior | `train()` `print()` → `logger.info()` |
| BUG-#42 | `app/ml/ml_confidence_boost.py` | prior | `save_model()` `datetime.now()` → `datetime.now(ET)` |
| BUG-#25 | `app/ml/ml_trainer.py` | prior | `train_model()` uses `walk_forward_cv()` |
| BUG-#26 | `app/ml/ml_trainer.py` | prior | `_fetch_training_data()` uses connection pool |
| BUG-#27 | `app/ml/ml_trainer.py` | prior | `LIVE_FEATURE_COLS` constant added |
| BUG-#39 | `app/ml/ml_trainer.py` | prior | `should_retrain()` `datetime.now()` → `datetime.now(ET)` |
| BUG-#40 | `app/ml/ml_trainer.py` | prior | All `trained_at` timestamps use `datetime.now(ET).isoformat()` |

---

## Next Session Queue

| Priority | Folder | Files | Notes |
|----------|--------|-------|-------|
| 1 | `app/core/` | `arm_signal.py` (~9 KB), `analytics_integration.py` (~9.5 KB) | Two remaining medium core files before the big two |
| 2 | `app/core/` | `sniper.py` (~28 KB), `scanner.py` (~31 KB) | Large files — all smaller core files must be clean first |
| 3 | `app/data/` | All files | DB pool, `sql_safe`, schema — foundational, high priority |
| 4 | `app/signals/` | Remaining files | Fix BUG-OR-1/2 here. `breakout_detector.py`, `bos_fvg_engine.py`, etc. |
| 5 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 6 | `app/notifications/` | All files | Discord alert system |
| 7 | `app/backtesting/` | All files | Backtest engine, walk-forward |
| 8 | `app/filters/`, `app/indicators/`, `app/mtf/`, `app/screening/`, `app/validation/`, `app/risk/`, `app/ai/` | All | Secondary modules |
| 9 | `scripts/`, `tests/`, `utils/` | All | Support infrastructure |
| 10 | Root config | `requirements.txt`, `railway.toml`, `nixpacks.toml`, etc. | Deployment config |
