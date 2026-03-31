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
| `app/signals/` | — | — | ⬜ Pending |
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
**Status:** ⚠️ 2 findings documented — fixes queued for next `core/` session

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-ASS-1 | ⚠️ | `import logging` placed last in import block, `logger =` assigned inline | ⬜ Fix pending |
| BUG-ASS-2 | ⚠️ | Redundant `from app.data.sql_safe import safe_execute` inside `clear_armed_signals()` — already imported at module scope | ⬜ Fix pending |

---

## Session WSS-1 — `app/core/watch_signal_store.py`
**Status:** ⚠️ 3 findings documented — fixes queued for next `core/` session

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-WSS-1 | ⚠️ | All error paths in 7 functions use `logger.info` instead of `logger.warning` — inconsistent with `armed_signal_store.py` | ⬜ Fix pending |
| BUG-WSS-2 | ⚠️ | Stray `print()` in `_load_watches_from_db()` (~line 140) — should be `logger.info()` | ⬜ Fix pending |
| BUG-WSS-3 | ⚠️ | `clear_watching_signals()` passes empty tuple `()` to `safe_execute` but `clear_armed_signals()` passes no params — minor inconsistency | ⬜ Fix pending |

---

## Open Fix Queue

All findings below are confirmed non-crashing unless marked 🐛/🔴.
Priority: fix during the session that next touches the owning file.

| Fix ID | File | Severity | Description | Session Target |
|--------|------|----------|-------------|----------------|
| BUG-ASS-1 | `app/core/armed_signal_store.py` | ⚠️ | Move `import logging` to top of import block | Next `core/` session |
| BUG-ASS-2 | `app/core/armed_signal_store.py` | ⚠️ | Remove redundant inner `import safe_execute` in `clear_armed_signals()` | Next `core/` session |
| BUG-WSS-1 | `app/core/watch_signal_store.py` | ⚠️ | Change 7 error-path `logger.info` → `logger.warning` | Next `core/` session |
| BUG-WSS-2 | `app/core/watch_signal_store.py` | ⚠️ | Replace `print()` with `logger.info()` in `_load_watches_from_db()` | Next `core/` session |
| BUG-WSS-3 | `app/core/watch_signal_store.py` | ⚠️ | Remove empty tuple `()` from `safe_execute` DELETE call in `clear_watching_signals()` | Next `core/` session |

---

## Completed Fixes Log

| Fix ID | File | Commit | Description |
|--------|------|--------|-------------|
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
| 1 | `app/core/` | `armed_signal_store.py`, `watch_signal_store.py` | Apply open fixes BUG-ASS-1/2, BUG-WSS-1/2/3 |
| 2 | `app/core/` | Remaining 13 files | `scanner.py`, `sniper.py`, `signal_scorecard.py`, `cfw6_gate_validator.py`, etc. |
| 3 | `app/data/` | All files | DB connection pool, sql_safe, schema files |
| 4 | `app/signals/` | All files | Gate validators, signal store, BOS/FVG detectors |
| 5 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 6 | `app/notifications/` | All files | Discord alert system |
| 7 | `app/backtesting/` | All files | Backtest engine, walk-forward, historical trainer |
| 8 | `app/ai/` | `ai_learning.py` | 18.6 KB — single file |
| 9 | `scripts/`, `tests/`, `utils/` | All files | Support infrastructure |
| 10 | Root config | `requirements.txt`, `railway.toml`, `nixpacks.toml`, etc. | Deployment config audit |
