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
**SHA:** `0acd64b0d38af5307a3e83ffe628b526dddc5b9a`  
**Size:** 6,522 B  
**Status:** ⚠️ 3 findings — non-crashing

**Purpose:** `MLConfidenceBooster` — XGBoost binary classifier. Outputs confidence
adjustment in `[-15%, +15%]`. Saved to `/app/models/confidence_booster.pkl`.
Separate from `ml_trainer.py` (HistGBM). Weekly retrain via Railway cron.

#### Finding BUG-MCB-1 ⚠️ — `logger` import style inconsistency
**Line:** ~32  
```python
import logging
logger = logging.getLogger(__name__)
```
`import logging` is placed **after** all other imports (numpy, pandas, typing, datetime,
zoneinfo, xgboost, sklearn) and `logger =` is assigned on the very next line inline
with imports — same pattern as BUG-ASS-1 in `armed_signal_store.py`. Syntactically
valid but inconsistent with the rest of the codebase where `import logging` appears
first or second in the import block. Non-crashing. Cosmetic.

**Fix:** Move `import logging` to the top of the import block (before numpy/pandas).

#### Finding BUG-MCB-2 ⚠️ — Error paths use `logger.info` instead of `logger.warning`
**Lines:** `_load_model()` error path (~line 50), `predict_confidence_adjustment()` error path (~line 73), `save_model()` no-model path (~line 100)

```python
# Current (all 3 locations):
logger.info(f"[ML] Model load error: {e}")
logger.info(f"[ML] Prediction error: {e}")
logger.info("[ML] No trained model to save")
```

`metrics_cache.py` (same module) uses `logger.warning` on all error paths. The
`armed_signal_store.py` was explicitly upgraded to `logger.warning` on errors in a
prior session. These three `logger.info` on error/exception paths are inconsistent
with the codebase standard. A model load failure is operationally significant and
should surface as WARNING, not INFO.

**Fix:** Change all 3 to `logger.warning(...)`.

#### Finding BUG-MCB-3 ⚠️ — `_save_feature_importance()` uses `logger.info` for loop body
**Lines:** ~155-158  
```python
logger.info("top 10 features:")
for idx, row in df.head(10).iterrows():
    logger.info(f"  {row['feature']}: {row['importance']:.4f}")
```
This is operational output (not an error). `logger.info` is correct here — no change
needed. Noted for completeness, not a finding.

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
**SHA:** `5f63c55aed39472c137095bf4987098b4a8ede66`  
**Size:** 28,379 B  
**Status:** ⚠️ 2 findings — non-crashing

**Purpose:** Trains `HistGradientBoostingClassifier` + Platt scaling. Two entry points:
`train_from_dataframe()` (historical pre-training) and `train_model()` (live EOD retrain).
Saves to `ml_model.joblib`. Separate from `ml_confidence_boost.py` (XGBoost).

#### Finding BUG-MLT-1 ⚠️ — `_prepare_features()` mutates input DataFrame in-place
**Lines:** `_prepare_features()` function body (~lines 370-390)

```python
# Current:
df = pd.concat([df, dummies], axis=1)   # rebinds local var — OK
...
df[col] = df[col].fillna(df[col].median())  # mutates local — OK but CoW-unsafe
```

The `df` passed in is a slice of the caller's DataFrame. With pandas Copy-on-Write
(CoW, default from pandas 2.0+), `df[col] = ...` on a slice raises a
`SettingWithCopyWarning` and may silently not persist. The prior fix in the docstring
mentions CoW was addressed in `train_from_dataframe()` (fillna replaced with
non-inplace) but `_prepare_features()` still uses direct column assignment.

**Fix:** Add `.copy()` at the top of `_prepare_features()`:
```python
df = df.copy()
```

#### Finding BUG-MLT-2 ⚠️ — `should_retrain()` loads model twice
**Lines:** `should_retrain()` function (~lines 415-450)

```python
model_data = joblib.load(MODEL_PATH)   # load 1 — for trained_at
...
df = _fetch_training_data()
...
n_at_train = model_data['metrics']['n_train'] + ...  # uses load 1 result — OK
```

Single load, reused — actually fine on second read. No issue. Noted for completeness.

---

## Session ASS-1 — `app/core/armed_signal_store.py` (prior sessions)
**Status:** ⚠️ 2 findings documented, fixes pending

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-ASS-1 | ⚠️ | `import logging` placed last in import block, `logger =` assigned inline | ⬜ Fix pending |
| BUG-ASS-2 | ⚠️ | Redundant `from app.data.sql_safe import safe_execute` inside `clear_armed_signals()` — already imported at module scope | ⬜ Fix pending |

---

## Session WSS-1 — `app/core/watch_signal_store.py` (prior sessions)
**Status:** ⚠️ 3 findings documented, fixes pending

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
| BUG-MCB-1 | `app/ml/ml_confidence_boost.py` | ⚠️ | Move `import logging` to top of import block | Next `ml/` touch |
| BUG-MCB-2 | `app/ml/ml_confidence_boost.py` | ⚠️ | Change 3 error-path `logger.info` → `logger.warning` | Next `ml/` touch |
| BUG-MLT-1 | `app/ml/ml_trainer.py` | ⚠️ | Add `df = df.copy()` at top of `_prepare_features()` to avoid CoW mutation | Next `ml/` touch |

---

## Completed Fixes Log

| Fix ID | File | Commit | Description |
|--------|------|--------|-------------|
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
| 2 | `app/ml/` | `ml_confidence_boost.py`, `ml_trainer.py` | Apply open fixes BUG-MCB-1/2, BUG-MLT-1 |
| 3 | `app/core/` | Remaining 13 files | `scanner.py`, `sniper.py`, `signal_scorecard.py`, etc. |
| 4 | `app/data/` | All files | DB connection pool, sql_safe, schema files |
| 5 | `app/signals/` | All files | Gate validators, signal store, BOS/FVG detectors |
| 6 | `app/options/` | All files | Options chain, Greeks, pre-validation |
| 7 | `app/notifications/` | All files | Discord alert system |
| 8 | `app/backtesting/` | All files | Backtest engine, walk-forward, historical trainer |
| 9 | `app/ai/` | `ai_learning.py` | 18.6 KB — single file |
| 10 | `scripts/`, `tests/`, `utils/` | All files | Support infrastructure |
| 11 | Root config | `requirements.txt`, `railway.toml`, `nixpacks.toml`, etc. | Deployment config audit |
