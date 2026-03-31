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
| `app/` (root) | 1 | 0 | ⬜ Pending |
| `app/ai/` | 2 | 0 | ⬜ Pending |
| `app/analytics/` | 9 | 9 | ✅ Complete (prior sessions) |
| `app/backtesting/` | 7 | 0 | ⬜ Pending |
| `app/core/` | 15 | 2 | 🔄 In Progress |
| `app/data/` | — | — | ⬜ Pending |
| `app/ml/` | 7 | 5 | ✅ Complete — Session ML-1 (2026-03-31) |
| `app/notifications/` | — | — | ⬜ Pending |
| `app/options/` | — | — | ⬜ Pending |
| `app/signals/` | 1 | 1 | 🔄 In Progress — `opening_range.py` audited S-OR-1 |
| `audit_reports/` | 1 | — | Reference only |
| `backtests/` | — | — | ⬜ Pending |
| `docs/` | — | — | ⬜ Pending |
| `migrations/` | — | — | ⬜ Pending |
| `scripts/` | — | — | ⬜ Pending |
| `tests/` | — | — | ⬜ Pending |
| `utils/` | — | — | ⬜ Pending |
| Root config files | 8 | 0 | ⬜ Pending |

---

## Session ML-1 — `app/ml/` Full Audit
**Date:** 2026-03-31
**Auditor:** Perplexity AI
**Files audited:** 5 Python files (`__init__.py`, `metrics_cache.py`, `ml_confidence_boost.py`, `ml_signal_scorer_v2.py`, `ml_trainer.py`)
**Docs skipped (read-only):** `INTEGRATION.md`, `README.md`
**Fixes applied commit:** `5255863a1844eb34ca76ef9bbb1b9a2241173432`

---

### `app/ml/__init__.py`
**SHA:** `7cc0e794a5949749e57a5c2867493af623e92ac2`
**Size:** 27 B
**Status:** ✅ Clean

- Single comment line: `# ML module initialization`
- No imports, no logic — correct for a namespace package init
- No issues

---

### `app/ml/metrics_cache.py`
**SHA:** `f2dbbf05b0c60321520095d2b2531477359b790d`
**Size:** 2,628 B
**Status:** ✅ Clean

**Purpose:** Provides `get_ticker_win_rates(days=30) → dict[ticker, float]` used by
`MLConfidenceBooster` and `ml_trainer.py` to supply the `ticker_win_rate` feature at
inference time.

**Checks passed:**
- Module docstring is complete and accurate — describes callers, return type, fallback behaviour, and BUG-ML-2 fix
- `get_conn()` / `return_conn()` pattern with `conn = None` guard in `finally` — correct
- `ph()` abstraction used for SQL placeholder — dual-dialect safe (PostgreSQL `%s` / SQLite `?`)
- `pd.read_sql_query()` params passed as positional tuple `(since,)` — correct post BUG-ML-2 fix
- `logger.warning()` on error path — consistent log level (not `logger.info`)
- Falls back to `{}` on any exception — callers notified via docstring to treat missing keys as 0.5 neutral
- `ET = ZoneInfo("America/New_York")` used for `datetime.now(ET)` — timezone-aware throughout
- No stray `print()` calls
- No redundant imports

**No findings.**

---

### `app/ml/ml_confidence_boost.py`
**SHA at audit:** `0acd64b0d38af5307a3e83ffe628b526dddc5b9a`
**SHA post-fix:** updated in commit `5255863`
**Size:** ~6,522 B
**Status:** ✅ All findings fixed in Session ML-1

**Purpose:** `MLConfidenceBooster` — XGBoost binary classifier. Outputs confidence
adjustment in `[-15%, +15%]`. Saved to `/app/models/confidence_booster.pkl`.
Separate from `ml_trainer.py` (HistGBM). Weekly retrain via Railway cron.

#### 🔧 BUG-MCB-1 — `import logging` import order (FIXED)
**Severity:** ⚠️ Non-crashing cosmetic
`import logging` was placed after all other imports. Moved to the top of the import
block so standard-library imports precede third-party imports — consistent with the
rest of the codebase.

#### 🔧 BUG-MCB-2 — Error paths used `logger.info` instead of `logger.warning` (FIXED)
**Severity:** ⚠️ Non-crashing, log-visibility issue
Three locations changed:
- `_load_model()` error path: `logger.info` → `logger.warning`
- `predict_confidence_adjustment()` error path: `logger.info` → `logger.warning`
- `save_model()` no-model path: `logger.info` → `logger.warning`

Now consistent with `metrics_cache.py` and `ml_signal_scorer_v2.py`.

---

### `app/ml/ml_signal_scorer_v2.py`
**SHA:** `42392e748e9bf5c7e397666deed162f62a099103`
**Size:** 7,599 B
**Status:** ✅ Clean

**Purpose:** Gate 5 adapter — bridges trained models into the interface expected by
`cfw6_gate_validator.py`. Model resolution order: HistGBM (`ml_model.joblib`) →
XGBoost booster (`confidence_booster.pkl`) → heuristic fallback. Created in
BUG-ML-1 fix (Session 11, Mar 27 2026).

**Checks passed:**
- Model resolution chain is correctly ordered (HistGBM first, booster second, fallback last)
- `_HIST_MODEL_PATH` uses `os.path.join(__file__, '..', '..', 'ml_model.joblib')` — relative path correct
- `_BOOSTER_MODEL_PATH = "/app/models/confidence_booster.pkl"` — absolute path correct for Railway
- `_build_feature_vector()` zero-fills missing keys (matches training-time `fillna(0)`)
- `adx` defaults to `20.0` (neutral), not `0.0` — correct, avoids poisoning the feature vector
- Confidence normalised from `[0,100]` to `[0,1]` if `> 1.0` — handles both caller conventions
- `score_signal()` returns `-1.0` sentinel when no model (callers skip adjustment cleanly)
- `score_signal()` returns `0.5` on inference error (neutral — no adjustment)
- `logger.warning` used on all load-failure and inference-error paths — consistent
- Thread-safe for read-only inference (no shared mutable state after `__init__`)
- `is_ready` attribute correctly set before `_load_best_model()` returns
- No stray `print()` calls
- No redundant imports
- Imports `joblib` / `pickle` / `numpy` deferred inside methods — avoids hard dependency at import time

**No findings.**

---

### `app/ml/ml_trainer.py`
**SHA at audit:** `5f63c55aed39472c137095bf4987098b4a8ede66`
**SHA post-fix:** updated in commit `5255863`
**Size:** ~28,379 B
**Status:** ✅ All findings fixed in Session ML-1

**Purpose:** Trains `HistGradientBoostingClassifier` + Platt scaling. Two entry points:
`train_from_dataframe()` (historical pre-training) and `train_model()` (live EOD retrain).
Saves to `ml_model.joblib`. Separate from `ml_confidence_boost.py` (XGBoost).

#### 🔧 BUG-MLT-1 — `_prepare_features()` mutated caller's DataFrame (CoW-unsafe) (FIXED)
**Severity:** ⚠️ Non-crashing in pandas < 2.0; silent data corruption risk in pandas 2.0+

With pandas Copy-on-Write (default from 2.0+), writing `df[col] = df[col].fillna(...)`
on a DataFrame slice raises `SettingWithCopyWarning` and may silently not persist.
Added `df = df.copy()` at the top of `_prepare_features()` so all mutations target
a local copy. The one-line fix is standard pandas CoW hygiene for any function
receiving an externally-owned DataFrame.

#### BUG-MLT-2 — `should_retrain()` model load count (NOTED, no fix needed)
On second review: `should_retrain()` calls `joblib.load(MODEL_PATH)` once and reuses
the result throughout the function. No double-load. Noted for completeness — confirmed
not an issue.

---

## Session ASS-1 — `app/core/armed_signal_store.py`
**Date:** 2026-03-31
**SHA at audit:** `6263afa75a0249706aacf9f7c6bd4f14ba723442`
**Status:** ✅ All findings fixed (applied in-file, documented in file header comment)

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-ASS-1 | ⚠️ | `import logging` placed last in import block, `logger =` assigned inline | ✅ Fixed |
| BUG-ASS-2 | ⚠️ | Redundant `from app.data.sql_safe import safe_execute` inside `clear_armed_signals()` — already imported at module scope | ✅ Fixed |

**Checks passed (clean):**
- File-header comment block above imports — correct placement
- `get_conn()`/`return_conn()` deferred inside every function body — correct pool pattern
- `_ensure_armed_db()` uses `logger.warning` on error path — consistent
- `_persist_armed_signal()` inserts all 11 schema fields — matches table definition
- `ON CONFLICT` upsert uses `CURRENT_TIMESTAMP` for `saved_at` (not `EXCLUDED.saved_at`) — correct
- `safe_execute` used for all DML — correct
- `_remove_armed_from_db()` parametrized — no string interpolation
- `_cleanup_stale_armed_signals()` uses `position_manager.get_open_positions()` — correct cross-module reference
- `safe_in_clause` used for bulk delete — correct
- `_load_armed_signals_from_db()` — `_dc()` / `USE_POSTGRES` branching for dual-dialect date filter — correct
- `row.get("validation_data")` dict-style access — valid because `dict_cursor` is used
- `_armed_load_lock = __import__('threading').Lock()` — valid pattern, avoids top-level import
- `_maybe_load_armed_signals()` lock wraps `is_armed_loaded()` + `set_armed_loaded()` check — no double-load possible
- `clear_armed_signals()` has docstring, uses `logger.warning` on error — consistent
- No stray `print()` calls

---

## Session WSS-1 — `app/core/watch_signal_store.py`
**Date:** 2026-03-31
**SHA at audit:** `061e64817f36a6c7c46c577d6dd9f14b8d0260f2`
**Status:** ✅ All findings fixed (applied in-file, documented in file header comment)

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-WSS-1 | ⚠️ | All error paths in 7 functions used `logger.info` instead of `logger.warning` | ✅ Fixed |
| BUG-WSS-2 | ⚠️ | Stray `print()` in `_load_watches_from_db()` — should be `logger.info()` | ✅ Fixed |
| BUG-WSS-3 | ⚠️ | `clear_watching_signals()` passed empty tuple `()` to `safe_execute` — inconsistent with `armed_signal_store.py` | ✅ Fixed |

**Checks passed (clean):**
- `_watch_load_lock` present, wraps `is_watches_loaded()` + `set_watches_loaded()` — no double-load
- All 3 FIX #55 state method names corrected: `set_watching_signal`, `ticker_is_watching`, `get_all_watching_signals`
- `_strip_tz()` helper correctly handles tz-aware datetimes for SQLite compat
- `MAX_WATCH_BARS = 12` mirrors `sniper.py` constant
- `_cleanup_stale_watches()` uses `breakout_bar_dt < cutoff_time` time-based cutoff — correct
- `cursor.rowcount` used for deleted count — works on both SQLite and PostgreSQL
- `send_bos_watch_alert()` defers `send_simple_message` import — correct
- `clear_watching_signals()` logs success at `logger.info` and error at `logger.warning` — correct
- No stray `print()` calls
- No redundant imports

---

## Session S-OR-1 — `app/signals/opening_range.py`
**Date:** 2026-03-31
**SHA:** `8c141c9a852c8cd1b11d80bdd6cf5f810615ee99`
**Status:** ✅ Clean — no issues found

**Purpose:** `OpeningRangeDetector` class + module-level convenience functions.
Classifies 9:30–9:40 OR as TIGHT/NORMAL/WIDE/DYNAMIC. Phase B1 adds secondary
range (10:00–10:30). Used by `sniper.py` for breakout anchor levels and scan
frequency recommendations.

**Architecture:**
- `or_detector` singleton at module scope — correct for session-scoped state
- Phase 1.17 fixes: `bar['datetime']` key (not `'timestamp'`), mid-session DYNAMIC fallback,
  historical ATR via `get_bars_from_memory()`, OR cache TTL for DYNAMIC entries
- Phase B1: `classify_secondary_range()` + `get_secondary_range_levels()`, `_extract_secondary_bars()`
- Phase B1 Bug Fix #6: `_to_et_time()` helper forces ET conversion before window comparisons,
  price sanity clamp (`SR_PRICE_SANITY_MULT = 5.0`) guards against tick/timestamp corruption

**Checks passed:**
- `_to_et_time()` handles tz-aware, tz-naive, string, and None datetimes — correct
- `OR_CACHE_DYNAMIC_TTL = timedelta(minutes=30)` — DYNAMIC entries expire; TIGHT/NORMAL/WIDE never do
- `or_cache` TTL comparison uses `.replace(tzinfo=None)` on both sides — avoids tz-aware vs tz-naive compare crash
- `classify_or()` cache eviction on TTL expiry (`del self.or_cache[ticker]`) then re-evaluates — correct
- `classify_secondary_range()` defers `from utils import config` inside function — avoids circular import at module load
- `_extract_secondary_bars()` also defers `from utils import config` — consistent with above
- Price sanity clamp uses `np.median(closes)` as reference price — robust to outliers
- `classify_secondary_range()` checks `SECONDARY_RANGE_MIN_BARS` both before and after price clamp — double guard
- `sr_cache` entries never expire (10:00–10:30 window is immutable) — correct
- `clear_cache()` clears all three dicts: `or_cache`, `alerts_sent`, `sr_cache` — complete
- `get_secondary_range_levels()` returns `{}` (not `None`) on missing data — safe for callers that unpack keys
- `detect_breakout_after_or()` defers `from utils import config` twice (redundant but harmless) — minor
- `detect_fvg_after_break()` doji-c1 guard (`if c1_body == 0: continue`) present on both bull and bear paths — correct
- `compute_opening_range_from_bars()` returns `(None, None)` if fewer than 3 OR bars — correct sentinel
- `compute_premarket_range()` requires `>= 10` premarket bars — correct minimum
- `or_detector` global instance created at module import — `OpeningRangeDetector.__init__` logs 7 info lines at startup; acceptable
- `should_scan_now()` always returns `True` — scan frequency handled by scanner loop. The `or_data` variable is computed but unused. Non-crashing dead code.
- `ET = ZoneInfo("America/New_York")` defined at module scope and used consistently
- `logger = logging.getLogger(__name__)` correct placement (after `import logging`)
- No stray `print()` calls (all replaced Mar 27 2026 per file docstring)
- No redundant imports

**Findings:**

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-OR-1 | ⚠️ | `should_scan_now()`: `or_data = self.classify_or(ticker, current_time)` result is computed but never used — dead code. Always returns `True` regardless. | ⬜ Low priority — document only, no logic impact |
| BUG-OR-2 | ⚠️ | `detect_breakout_after_or()`: `from utils import config` imported twice inside the same function (lines ~615 and ~622) — redundant second import. | ⬜ Fix on next touch of `opening_range.py` |

---

## Open Fix Queue

All findings below are confirmed non-crashing unless marked 🐛/🔴.
Priority: fix during the session that next touches the owning file.

| Fix ID | File | Severity | Description | Session Target |
|--------|------|----------|-------------|----------------|
| BUG-OR-1 | `app/signals/opening_range.py` | ⚠️ | `should_scan_now()` computes `or_data` but never uses it — dead code | Next `signals/` session |
| BUG-OR-2 | `app/signals/opening_range.py` | ⚠️ | `detect_breakout_after_or()` imports `from utils import config` twice inside function | Next `signals/` session |

---

## Completed Fixes Log

| Fix ID | File | Commit | Description |
|--------|------|--------|-------------|
| BUG-WSS-1 | `app/core/watch_signal_store.py` | in-file (header) | Changed 7 error-path `logger.info` → `logger.warning` across all DB functions |
| BUG-WSS-2 | `app/core/watch_signal_store.py` | in-file (header) | Replaced stray `print()` in `_load_watches_from_db()` with `logger.info()` |
| BUG-WSS-3 | `app/core/watch_signal_store.py` | in-file (header) | Removed empty `()` params tuple from `safe_execute` DELETE in `clear_watching_signals()` |
| BUG-ASS-1 | `app/core/armed_signal_store.py` | in-file (header) | Moved `import logging` to top of import block — consistent import ordering |
| BUG-ASS-2 | `app/core/armed_signal_store.py` | in-file (header) | Removed redundant inner `import safe_execute` in `clear_armed_signals()` |
| BUG-MCB-1 | `app/ml/ml_confidence_boost.py` | `5255863` | Moved `import logging` to top of import block — consistent import ordering |
| BUG-MCB-2 | `app/ml/ml_confidence_boost.py` | `5255863` | Changed 3 error-path `logger.info` → `logger.warning` (model load, prediction, save) |
| BUG-MLT-1 | `app/ml/ml_trainer.py` | `5255863` | Added `df = df.copy()` at top of `_prepare_features()` — CoW-safe, prevents silent corruption in pandas 2.0+ |
| BUG-ML-2 | `app/ml/metrics_cache.py` | Session 11 | `pd.read_sql_query` placeholder → `ph()` abstraction, positional tuple params |
| BUG-ML-1 | `app/ml/ml_signal_scorer_v2.py` | Session 11 | File created — Gate 5 was silently catching ImportError every run |
| BUG-#41 | `app/ml/ml_confidence_boost.py` | Session prior | `train()` `print()` → `logger.info()` for training metrics |
| BUG-#42 | `app/ml/ml_confidence_boost.py` | Session prior | `save_model()` `datetime.now()` → `datetime.now(ET)` |
| BUG-#25 | `app/ml/ml_trainer.py` | Session prior | `train_model()` uses `walk_forward_cv()` instead of single 80/20 split |
| BUG-#26 | `app/ml/ml_trainer.py` | Session prior | `_fetch_training_data()` uses `get_conn()`/`return_conn()` pool — not raw `psycopg2.connect()` |
| BUG-#27 | `app/ml/ml_trainer.py` | Session prior | `LIVE_FEATURE_COLS` constant added — feature-set divergence made explicit |
| BUG-#39 | `app/ml/ml_trainer.py` | Session prior | `should_retrain()` `datetime.now()` → `datetime.now(ET)` |
| BUG-#40 | `app/ml/ml_trainer.py` | Session prior | All `trained_at` timestamps use `datetime.now(ET).isoformat()` |

---

## Next Session Queue

| Priority | Folder | Files | Notes |
|----------|--------|-------|-------|
| 1 | `app/core/` | `sniper.py` | Large strategy engine — line-by-line audit |
| 2 | `app/core/` | `sniper_pipeline.py`, `signal_scorecard.py`, `cfw6_gate_validator.py` | Core pipeline files |
| 3 | `app/core/` | Remaining 10 files | `scanner.py`, `thread_safe_state.py`, `position_manager.py`, etc. |
| 4 | `app/data/` | All files | DB connection pool, sql_safe, schema files |
| 5 | `app/signals/` | Remaining files | After `opening_range.py` — `breakout_detector.py`, `bos_fvg_engine.py`, etc. |
| 6 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 7 | `app/notifications/` | All files | Discord alert system |
| 8 | `app/backtesting/` | All files | Backtest engine, walk-forward, historical trainer |
| 9 | `app/ai/` | `ai_learning.py` | 18.6 KB — single file |
| 10 | `scripts/`, `tests/`, `utils/` | All files | Support infrastructure |
| 11 | Root config | `requirements.txt`, `railway.toml`, `nixpacks.toml`, etc. | Deployment config audit |
