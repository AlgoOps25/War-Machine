# Signal Logic Audit — Batch 51
## Phase 4: `app/ai/` — AI Learning & Confidence Module
**Date:** Mar 27 2026
**Auditor:** Perplexity AI (assisted)
**Status:** ✅ COMPLETE — 3 issues found, 2 fixed, 1 noted (cosmetic)

---

## Module Overview

`app/ai/` is the **adaptive learning and confidence scoring layer** for War Machine.
It has two responsibilities:

1. **Confidence scoring** (`compute_confidence`, `grade_to_label`) — converts a CFW6
   grade string into a float score that gates signal arming. Formerly in `learning_policy.py`,
   now consolidated here.
2. **AI learning engine** (`AILearningEngine`) — records every closed trade outcome,
   tracks win rates by grade/ticker/timeframe, and adjusts confirmation weights and
   parameter thresholds over time.

### Files

| File | Size | Role |
|---|---|---|
| `__init__.py` | 29 B | Comment header only — no exports |
| `ai_learning.py` | 18.7 KB | All logic: confidence scoring + learning engine |

---

## File-by-File Documentation

### `__init__.py`
- **Role:** Module marker with comment `# AI Learning & Optimization`
- **Exports:** Nothing
- **Status:** ✅ Clean. No issues.

---

### `ai_learning.py` (18.7 KB) — CANONICAL

#### Module-level constants

**`_GRADE_BASE`** — confidence midpoints for all 9 CFW6 grades:

| Grade | Base Confidence | Range |
|---|---|---|
| A+ | 0.90 | (0.88–0.92) |
| A  | 0.85 | (0.83–0.87) |
| A- | 0.80 | (0.78–0.82) |
| B+ | 0.74 | (0.72–0.76) |
| B  | 0.68 | (0.66–0.70) |
| B- | 0.62 | (0.60–0.64) |
| C+ | 0.575 | (0.55–0.60) |
| C  | 0.525 | (0.50–0.55) |
| C- | 0.475 | (0.45–0.50) |

**`_TF_MULTIPLIER`** — timeframe weighting applied to base confidence:
- `5m`: 1.05 (highest weight)
- `3m`: 1.02
- `2m`: 1.00
- `1m`: 0.97 (lowest weight)

**`MIN_CONFIDENCE = 0.50`** — signals below this are dropped by upstream gate.

**`_DEFAULT_DATA`** — module-level dict used as fallback in `__init__()` if
`load_data()` raises. Added in Fix #47 so it doesn't need to be re-declared
inside the class.

#### Module-level functions

**`compute_confidence(grade, timeframe, ticker) -> float`**
- Formula: `round(clamp(_GRADE_BASE[grade] * _TF_MULTIPLIER[timeframe], 0.0, 1.0), 4)`
- Unknown grade defaults to `MIN_CONFIDENCE (0.50)`
- Unknown timeframe defaults to multiplier `1.00`
- `ticker` is reserved for future per-ticker tuning — currently unused
- Called by: `sniper.py`, `signal_validator.py`

**`grade_to_label(confidence) -> str`**
- Inverse of `compute_confidence` — maps a float back to a grade string
- Thresholds: `A+(0.88)`, `A(0.83)`, `A-(0.78)`, `B+(0.72)`, `B(0.66)`,
  `B-(0.60)`, `C+(0.55)`, `C(0.50)`, `C-(0.45)`, `reject(<0.45)`
- Called by: EOD reporter, Discord alert formatter

#### `AILearningEngine` class

**DB Table: `ai_learning_state`**
```sql
CREATE TABLE IF NOT EXISTS ai_learning_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    data JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1)
)
```
- Single-row table. Entire learning state stored as one JSONB blob.
- `CONSTRAINT single_row CHECK (id = 1)` enforces exactly one row.
- Upsert pattern: `INSERT ... ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data`

**In-memory state structure (`self.data`):**
```python
{
    "trades": [],                     # list of trade dicts (full history)
    "pattern_performance": {},        # keyed by grade: {count, wins, total_pnl}
    "ticker_performance": {},         # keyed by ticker: {count, wins, total_pnl}
    "timeframe_performance": {},      # keyed by timeframe: {count, wins, total_pnl}
    "confirmation_weights": {         # live-adjusted weights
        "vwap": 1.0,
        "prev_day": 1.0,
        "institutional": 1.0,
        "options_flow": 1.0
    },
    "fvg_size_optimal": 0.002,        # updated by optimize_fvg_threshold()
    "or_break_threshold_optimal": 0.001,
    "last_update": None               # ISO8601 ET timestamp
}
```

**`__init__(db_path)`**
- Calls `_init_learning_table()` → creates Postgres table if needed
- Calls `load_data()` wrapped in try/except (Fix #47) — falls back to
  `_DEFAULT_DATA` if load raises. Prevents Railway startup crash on
  malformed JSONB or corrupt JSON file.

**`_init_learning_table()`**
- Creates `ai_learning_state` in Postgres
- No-op if `USE_POSTGRES = False` (local SQLite mode)
- Uses `if conn: return_conn(conn)` pattern (correct)

**`load_data() -> Dict`**
- Postgres path: reads row id=1, merges with `_DEFAULT_DATA` (caller’s keys win)
- File path: reads `self.db_path` JSON, merges with `_DEFAULT_DATA`
- Both paths: any exception logs and returns `_DEFAULT_DATA`
- Uses `if conn: return_conn(conn)` pattern (correct)

**`save_data()`**
- Sets `last_update` to `datetime.now(ET).isoformat()` (Fix #38)
- Postgres path: UPSERT into `ai_learning_state`
- File path: writes to `self.db_path`
- Uses `if conn: return_conn(conn)` pattern (correct)

**`record_trade(trade: Dict)`**
- Builds `trade_record` dict with timestamp, ticker, direction, grade, entry,
  exit, pnl, win, hold_duration, fvg_size, or_break_size, confirmations, timeframe
- Calls `update_performance_metrics()` then `save_data()`
- Logs via `logger.info()` (Fix #37)
- Called from: `sniper.py` signal lifecycle tracker

**`update_performance_metrics(trade: Dict)`**
- Updates `pattern_performance[grade]`, `ticker_performance[ticker]`,
  `timeframe_performance[timeframe]` in-place
- Creates dict entry if key not yet seen
- No DB write — caller (`record_trade`) handles save

**`optimize_confirmation_weights()`**
- Requires ≥20 trades with confirmations to run
- For each of `vwap`, `prev_day`, `institutional`, `options_flow`:
  - Calculates win rate among trades where that confirmation was present
  - Sets `weight = win_rate / baseline_win_rate`
- Weights > 1.0 = confirmation correlated with wins
- Weights < 1.0 = confirmation correlated with losses
- Saves after updating. Logs each weight.
- Called from: EOD reporter (future — not yet wired to scheduler)

**`optimize_fvg_threshold()`**
- Uses last 100 trades, needs ≥30 to run
- Sets `fvg_size_optimal` = median FVG size of winning trades (min 10 wins)
- Called from: EOD reporter (future — not yet wired to scheduler)

**`get_ticker_confidence_multiplier(ticker) -> float`**
- Returns multiplier based on ticker’s historical win rate (needs ≥5 trades)
- `WR ≥75%` → 1.10, `≥65%` → 1.05, `≥55%` → 1.00, `≥45%` → 0.95, `<45%` → 0.90
- Returns 1.0 (neutral) if ticker has <5 trades
- Called from: `sniper.py` confidence pipeline

**`get_options_flow_weight(ticker) -> float`**
- Dynamically imports `options_dm` from `app.options.options_intelligence`
- Calls `options_dm.get_options_score(ticker)` for a score on 0–100 scale
- Maps score to multiplier: `0.7 + (score/100) * 0.6` → range [0.70, 1.30]
- Returns 1.0 (neutral) if `tradeable=False` or any import/runtime error
- Fix #39: Previously imported from wrong module (`options_data_manager`),
  always silently returned 1.0. Now wired correctly.

**`get_optimal_parameters() -> Dict`**
- Returns `{fvg_min_size_pct, orb_break_threshold, confirmation_weights}`
- Called from: signal validators, breakout detector

**`generate_performance_report() -> str`**
- Builds multi-line report: total trades, win rate, P&L, grade breakdown (9 grades),
  top 5 tickers by P&L
- Fix #46: Now calls `logger.info()` for each line — previously returned silently
  with no Railway log output unless the caller explicitly logged the string.
- Still returns the string so EOD reporter can embed it in Discord messages.

**Singleton:** `learning_engine = AILearningEngine()` — module-level instance
imported by `sniper.py` and `eod_reporter.py`.

---

## Issues Found & Resolved This Batch

| # | Severity | Description | Fix | Commit | Status |
|---|---|---|---|---|---|
| 45 | LOW | `get_options_flow_weight()` catches `ImportError` explicitly but not `AttributeError` — if `options_dm` imports but `get_options_score` is missing, it falls into general `except Exception` and logs noise | Added inline NOTE comment flagging for future cleanup. No logic change — behavior is acceptable. | [c4095b6](https://github.com/AlgoOps25/War-Machine/commit/c4095b6ed355dd8590ec8a35f4c7373fb6b24093) | ⚠️ Noted |
| 46 | LOW | `generate_performance_report()` built a full report string but never logged it — silent dead-end on Railway unless caller explicitly logged the return value | Added `logger.info()` for each line; still returns string | [c4095b6](https://github.com/AlgoOps25/War-Machine/commit/c4095b6ed355dd8590ec8a35f4c7373fb6b24093) | ✅ Fixed |
| 47 | MED | `AILearningEngine.__init__()` called `self.data = self.load_data()` bare — malformed Postgres JSONB or corrupt JSON file would crash the module-level singleton and take down Railway startup | Wrapped in `try/except` with fallback to `dict(_DEFAULT_DATA)` | [c4095b6](https://github.com/AlgoOps25/War-Machine/commit/c4095b6ed355dd8590ec8a35f4c7373fb6b24093) | ✅ Fixed |

---

## Architecture Notes

1. **Single-row JSONB pattern** — entire learning state lives in one Postgres row.
   Fast reads/writes but no row-level history. If we ever need audit trail of
   weight changes, we’ll need a `ai_learning_history` append-only table.

2. **`optimize_*` methods not yet on a scheduler** — `optimize_confirmation_weights()`
   and `optimize_fvg_threshold()` are defined but not wired to any cron or EOD trigger.
   They must be called manually or by EOD reporter. Future work: wire to `eod_reporter.py`.

3. **`trades` list grows unbounded** — `self.data["trades"]` appends every trade
   and is saved to Postgres on every `record_trade()` call. With many trades, the
   JSONB blob will grow large and Postgres write latency will increase. Future work:
   cap at last N trades or move to a dedicated `ai_trades` table.

4. **`ticker` param in `compute_confidence()` is reserved** — currently unused.
   When per-ticker tuning is implemented, `get_ticker_confidence_multiplier()` output
   should be folded here rather than applied ad-hoc in `sniper.py`.

5. **`_DEFAULT_DATA` is now a module-level constant** (not re-declared inside `load_data()`).
   Any future keys added to the learning state must be added to `_DEFAULT_DATA` to
   ensure clean fallback on startup.

---

## Phase 4 Status

**Module:** `app/ai/` — ✅ COMPLETE
**Files audited:** 2/2
**Issues found:** 3 (0 HIGH, 1 MED, 2 LOW)
**Issues resolved:** 2 (MED + 1 LOW fixed, 1 LOW noted)
**Next module:** `app/backtesting/`
