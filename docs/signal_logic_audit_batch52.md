# Batch 52 — `app/backtesting/` Audit

**Date:** 2026-03-27  
**Auditor:** Perplexity / War Machine Audit System  
**Files audited:** 7  
**Issues found:** 2 (Issue #48, Issue #49)  
**Fixes applied this batch:** 0 (issues logged; fixes pending)

---

## Module Overview

`app/backtesting/` is War Machine's **offline strategy validation layer**.
It is completely standalone — no live DB, no Tradier, no Railway environment
required. Its job is to answer: *"Does this strategy actually make money on
historical data, and will it survive unseen market conditions?"*

The module sits **outside the live signal path** and is driven manually or
by scheduled maintenance scripts. It feeds results back into `app/ai/` to
retrain `MLSignalScorerV2`.

### Dependency graph

```
app/backtesting/
  __init__.py
      ↓ imports from all 6 siblings
  backtest_engine.py          ← core replay loop
      ↑ used by
  walk_forward.py             ← WF validation orchestrator
  parameter_optimizer.py      ← grid search, uses BacktestEngine
      ↑ used by
  walk_forward.py             ← calls ParameterOptimizer on each train window
  performance_metrics.py      ← pure math, no imports from project
      ↑ used by
  backtest_engine.py
  walk_forward.py
  signal_replay.py            ← strategy factory helpers
      ↑ used by callers of BacktestEngine (not internally)
  historical_trainer.py       ← self-contained ML training pipeline
      ↑ no project imports except optional pandas/numpy/requests
```

---

## File-by-File Documentation

---

### `__init__.py`

**Role:** Public API surface for the entire backtesting module.

**What it exports:**

| Symbol | Source file | Purpose |
|---|---|---|
| `BacktestEngine` | `backtest_engine.py` | Core replay engine |
| `BacktestResults` | `backtest_engine.py` | Results container |
| `Trade` | `backtest_engine.py` | Completed trade dataclass |
| `Position` | `backtest_engine.py` | Open position dataclass |
| `calculate_sharpe_ratio` | `performance_metrics.py` | Sharpe ratio |
| `calculate_sortino_ratio` | `performance_metrics.py` | Sortino ratio |
| `calculate_max_drawdown` | `performance_metrics.py` | Peak-to-trough % |
| `calculate_win_rate` | `performance_metrics.py` | % winning trades |
| `calculate_profit_factor` | `performance_metrics.py` | Gross profit / gross loss |
| `calculate_expectancy` | `performance_metrics.py` | Avg $ per trade |
| `WalkForward` | `walk_forward.py` | WF validation engine |
| `WalkForwardResults` | `walk_forward.py` | WF results container |
| `ParameterOptimizer` | `parameter_optimizer.py` | Grid search |
| `create_strategy_from_breakout_detector` | `signal_replay.py` | Strategy factory |
| `create_strategy_from_signal_generator` | `signal_replay.py` | Strategy factory |
| `example_simple_breakout_strategy` | `signal_replay.py` | Test harness strategy |

**Gotchas:**
- No import-time side effects. Safe to import on Railway startup.
- `HistoricalMLTrainer` is **NOT** exported here. It must be imported directly:
  `from app.backtesting.historical_trainer import HistoricalMLTrainer`

---

### `backtest_engine.py`

**Role:** Bar-by-bar historical replay engine. The core of the backtesting
system.

**Key dataclasses:**

```
Trade     — immutable record of a completed round-trip trade
Position  — mutable state of an open position during replay
```

**`BacktestResults` class:**
- Computed on construction from a list of `Trade` objects
- Calculates all performance metrics automatically (Sharpe, Sortino, drawdown, etc.)
- `.summary()` → human-readable string (safe to logger.info)
- `.to_dict()` → JSON-serializable dict for storage

**`BacktestEngine` class:**

Constructor parameters:

| Param | Default | Meaning |
|---|---|---|
| `initial_capital` | `10000` | Starting account balance |
| `commission_per_trade` | `0.50` | Fixed $ commission per fill |
| `slippage_pct` | `0.05` | Slippage as % of price |
| `max_position_size_pct` | `100.0` | Max position as % of capital |
| `risk_per_trade_pct` | `1.0` | Risk per trade as % of capital |
| `max_bars_held` | `390` | Max bars before forced exit (390 = full trading day) |
| `enable_t1_t2_exits` | `True` | Use split T1/T2 exit logic |

**Replay flow (`engine.run()`):**

```
For each bar i in bars:
  1. manage_positions()   — check stops, T1/T2 targets, timeouts
  2. if no open position AND i >= 50:
       signal = strategy(lookback_bars[-100:i], params)
       if signal: open_position()
Close any remaining positions EOD
Return BacktestResults
```

**Important behaviour facts:**
- **One position at a time** — new signals are blocked while a position is open
- **Needs 50 bars** before it starts generating signals (warm-up)
- **T1 half-exit** reduces `position.shares //= 2` but does NOT close the trade —
  only updates the dataclass field. The T1 P&L is never captured in a `Trade`
  object. This means reported P&L understates multi-leg T1/T2 wins. (**Issue #48**)
- `close_position()` double-counts commission (charges `commission_per_trade * 2`
  on the exit Trade object, but already deducted once at entry and once at exit
  from `current_capital`). Commission field in Trade is informational only and
  does not affect P&L accuracy — `current_capital` is the ground truth.
- `print()` used in `run()` and `grid_search()` — outputs to stdout, not logger.
  Will appear in Railway logs but won't be captured by the logging framework.
  (**Issue #49**)

**Exit reason taxonomy:**

| Reason | Trigger |
|---|---|---|
| `TARGET` | High/Low hit T2 (or regular target) |
| `STOP` | Low/High hit stop_loss |
| `EOD` | Position open at end of bar list |
| `TIMEOUT` | `bars_held >= max_bars_held` |

---

### `performance_metrics.py`

**Role:** Pure math functions. No project imports. Stateless.

**Functions:**

| Function | Input | Output | Notes |
|---|---|---|---|
| `calculate_sharpe_ratio` | `List[float]` returns, risk_free | `float` | Returns 0.0 if < 2 samples |
| `calculate_sortino_ratio` | `List[float]` returns, risk_free | `float` | Returns `inf` if no downside returns |
| `calculate_max_drawdown` | `List[float]` equity curve | `float` % | Returns 0.0 if < 2 points |
| `calculate_win_rate` | `List[Trade]` | `float` % | Requires `.pnl` attribute |
| `calculate_profit_factor` | `List[Trade]` | `float` | Returns `inf` if no losses |
| `calculate_expectancy` | `List[Trade]` | `float` $ | Avg PnL per trade |
| `calculate_calmar_ratio` | total_return_pct, max_dd_pct | `float` | NOT exported in `__init__.py` |
| `calculate_recovery_factor` | net_profit, max_dd_$ | `float` | NOT exported in `__init__.py` |
| `calculate_trade_distribution_stats` | `List[Trade]` | `dict` | NOT exported in `__init__.py` |

**Gotchas:**
- Sharpe/Sortino use **trade return %** not annualised returns. Results are
  not comparable to traditional annual Sharpe ratios — they are trade-level
  ratios only.
- `calculate_calmar_ratio`, `calculate_recovery_factor`, and
  `calculate_trade_distribution_stats` are implemented but not exported
  from `__init__.py`. If callers need them they must import directly.

---

### `parameter_optimizer.py`

**Role:** Exhaustive grid search over a parameter space. Runs one
`BacktestEngine` per parameter combination.

**`ParameterOptimizer` class:**

Constructor:

| Param | Default | Meaning |
|---|---|---|
| `initial_capital` | `10000` | Capital for each backtest |
| `optimization_metric` | `'sharpe_ratio'` | Attribute name on `BacktestResults` to rank by |
| `min_trades` | `10` | Skip combos that produce fewer than this many trades |

Valid metrics: `sharpe_ratio`, `sortino_ratio`, `profit_factor`, `win_rate`,
`expectancy`, `total_return_pct`

**`grid_search()` flow:**

```
1. Generate all cartesian products of param_grid values
2. For each combo:
   a. Run BacktestEngine.run()
   b. Check total_trades >= min_trades
   c. Read metric_value = getattr(results, optimization_metric)
   d. Append to results list
3. Sort results descending by metric_value
4. Return top_n results
```

**Gotchas:**
- `print()` used inside the loop — same Railway logging issue as backtest_engine.
  (**Issue #49** — shared)
- No parallelism. For large grids (e.g. 3×3×3 = 27 combos × ~10k bars each)
  this will be slow. Fine for offline use, not suitable for real-time.
- Exception handling swallows errors silently (`except Exception: continue`).
  A broken strategy function will produce 0 valid results with no traceback.
  Acceptable for grid search robustness, but debugging requires checking logs.

---

### `signal_replay.py`

**Role:** Strategy factory functions that bridge War Machine's live signal
logic into the `BacktestEngine` callback interface.

**Functions:**

| Function | What it wraps | Notes |
|---|---|---|
| `create_strategy_from_breakout_detector()` | `BreakoutDetector` | All exceptions silently return `None` |
| `create_strategy_from_signal_generator()` | `SignalGenerator` | H5 fix: `ImportError` and unexpected exceptions now log `WARNING` |
| `create_custom_strategy()` | Any callable | Wraps in try/except, logs info on error |
| `example_simple_breakout_strategy()` | Inline logic | Test/demo only — not production |

**H5 fix (Mar 2026) — documented in file:**
- `create_strategy_from_signal_generator` previously swallowed all exceptions
  silently (a bare `except Exception: return None`).
- Fixed to: `ImportError` → `logger.warning` once; all other exceptions →
  `logger.warning` per bar.
- `create_strategy_from_breakout_detector` still silently returns `None` on
  all exceptions — this was not changed because `BreakoutDetector` is stable
  and silent fails are acceptable for the breakout path.

**Gotchas:**
- `create_strategy_from_breakout_detector` instantiates a **new
  `BreakoutDetector` object on every single bar** during replay. For a
  10k-bar run this is 10,000 object creations. It works but is wasteful.
  (Low priority — backtesting is offline.)
- `create_strategy_from_signal_generator` also instantiates a new
  `SignalGenerator` per bar. Same concern.

---

### `walk_forward.py`

**Role:** Walk-forward validation — the anti-overfitting layer on top of
`BacktestEngine` + `ParameterOptimizer`.

**`WalkForwardResults` class:**
- Aggregates all out-of-sample (OOS) trades across all windows into
  `all_test_trades`
- Computes aggregate OOS metrics (win rate, profit factor, Sharpe, etc.)
- `.summary()` → formatted table of all windows with train/test periods and OOS P&L

**`WalkForward` class:**

Constructor:

| Param | Default | Meaning |
|---|---|---|
| `train_months` | `3` | Training window size |
| `test_months` | `1` | OOS test window size |
| `step_months` | `1` | Roll-forward step size |
| `optimization_metric` | `'sharpe_ratio'` | Metric to optimize on train window |
| `min_train_bars` | `1000` | Skip window if train has fewer bars |

**`run()` flow:**

```
1. create_windows(bars)  → list of WalkForwardWindow objects
2. For each window:
   a. ParameterOptimizer.grid_search() on train_bars
   b. Get best_params from top result
   c. BacktestEngine.run() on test_bars using best_params
   d. Store test_results on window
3. WalkForwardResults(windows)  → aggregate all OOS trades
```

**Gotchas:**
- Window dates use `timedelta(days=30 * months)` — this is approximate
  (treats every month as 30 days). For precision, trading calendar bars
  should be used instead. This causes minor drift but is acceptable for
  monthly-granularity WF splits.
- `min_train_bars=1000` default means you need at least 1000 5-minute bars
  in the train window (~8.5 days of intraday data). The fallback daily bars
  would need a much lower threshold — no auto-adjustment exists.
- If `ParameterOptimizer.grid_search()` returns empty results for a window,
  that window is skipped entirely (no OOS test run). The skip is logged but
  not flagged as an error.

---

### `historical_trainer.py`

**Role:** Self-contained ML training data pipeline. Fetches EODHD OHLCV,
replays War Machine signal logic bar-by-bar, labels outcomes WIN/LOSS/TIMEOUT,
and returns a pandas DataFrame ready for `MLSignalScorerV2` retraining.

**This is the largest and most complex file in the module (43KB, ~900 lines).**

#### Constants

| Constant | Value | Meaning |
|---|---|---|
| `DEFAULT_TIMEOUT_BARS` | `12` | 60 min on 5m data — bars before labelling TIMEOUT |
| `TARGET_MULT` | `1.5` | ATR multiplier for target price |
| `STOP_MULT` | `1.0` | ATR multiplier for stop loss |
| `OR_WINDOW_BARS` | `12` | First 60 min = Opening Range window |
| `MTF_LOOKBACK_BARS` | `180` | ~3 sessions of 5m for MTF resampling |
| `RVOL_MIN_DAILY` | `1.3` | Lower RVOL threshold for daily bars |

#### Feature vector — 20 features

`FEATURE_NAMES` list (must match `MLSignalScorerV2._build_features()`):

| # | Feature | Description |
|---|---|---|
| 1 | `confidence` | Raw confidence score from `_detect_signal()` |
| 2 | `rvol` | Relative volume vs 20-bar avg |
| 3 | `score_norm` | `score / 100` |
| 4 | `mtf_convergence` | Bool: all 3 TF SMAs rising |
| 5 | `mtf_convergence_count` | 0–3 TF count / 3.0 |
| 6 | `vwap_distance` | (close - VWAP) / VWAP |
| 7 | `vwap_side` | +1 above / -1 below VWAP (BUG-11 addition) |
| 8 | `or_range_pct` | Opening range as % of price |
| 9 | `adx_norm` | ADX / 50 |
| 10 | `atr_pct` | ATR / close |
| 11 | `atr_ratio` | Current ATR / 20-bar avg ATR (BUG-11 addition) |
| 12 | `is_or_signal` | 1.0 if within first OR_WINDOW_BARS of session |
| 13 | `hour_norm` | UTC hour / 21 |
| 14 | `time_bucket_norm` | Session bucket 0/1/2 / 2.0 (BUG-11 addition) |
| 15 | `resist_proximity` | BOS strength clipped [0,3]/3 (BUG-11 addition) |
| 16 | `ticker_win_rate` | Per-ticker win rate computed from this dataset |
| 17 | `spy_regime` | +1 bull / -1 bear / 0 neutral (EMA slope) |
| 18 | `conf_score` | FVG retest candle grade (1.0=A+, 0.85=A, 0.70=A-) |
| 19 | `fvg_size_pct` | FVG gap size as % of price |
| 20 | `bos_strength` | (close - swing_high) / swing_high |

**Note:** The list has 20 entries but the class docstring says 15. The 15
refers to the original non-redundant count pre-BUG-11. `FEATURE_NAMES` is the
source of truth — it has 20. Both `_signal_to_features()` and `FEATURE_NAMES`
must stay in sync with `MLSignalScorerV2._build_features()`. (**critical
dependency**)

#### Signal detection (`_detect_signal()`)

Mirrors `bos_fvg_engine.scan_bos_fvg()` exactly. 5-step flow:

```
1. RVOL gate         — skip if rvol < rvol_min
2. BOS detection     — close > swing_high (bull) or close < swing_low (bear)
3. FVG search        — scan bars after BOS for Fair Value Gap
4. FVG retest check  — prev bar must have entered the FVG zone
5. Candle grade      — prev bar must score > 0.0 (A+/A/A- only)
6. Entry             — open of current bar (next bar after confirmation)
```

#### Outcome labelling (`_label_outcome()`)

Strict no-look-ahead: only uses bars strictly after `entry_idx`.

```
WIN     — any future bar's high  >= target     (before stop hit)
LOSS    — any future bar's low   <= stop_loss  (before target hit)
TIMEOUT — neither hit within DEFAULT_TIMEOUT_BARS (12 bars = 60 min)
```

With `include_timeout=True` (default), TIMEOUT → LOSS in `build_dataset()`.

#### Bug fixes applied (all documented in file header)

| Bug | Fix |
|---|---|
| BUG-1 | Skip intraday endpoint when interval='d' (EODHD 422) |
| BUG-2 | `_safe_float()` handles EODHD null volume/price fields |
| BUG-3 | Daily-calibrated thresholds |
| BUG-4 | Filter after-hours zero-volume bars |
| BUG-5 | `_rvol()` and `_vwap_distance()` guard against zero-volume bars |
| BUG-6 | `_or_range()` uses session_bars not full history window |
| BUG-7 | `_mtf_convergence()` slices MTF_LOOKBACK_BARS before resampling |
| BUG-8 | `is_or_signal` uses session bar count not absolute index |
| BUG-9 | MTF asks direction-aware bull confirmation |
| BUG-10 | MTF uses SMA slope (sma_now > sma_prev) not price position |
| BUG-11 | Dropped 4 dead/redundant features; added 4 outcome-correlated |

#### `HistoricalMLTrainer` class methods

| Method | Purpose |
|---|---|
| `fetch_bars(ticker, months_back)` | Fetch EODHD intraday or EOD bars with fallback |
| `replay_ticker(ticker, bars, spy_bars)` | Bar-by-bar signal scan + outcome labelling |
| `build_dataset(tickers, months_back)` | Full pipeline → labelled DataFrame |
| `walk_forward_split(df, val_fraction)` | Temporal train/val split (no shuffle) |
| `summary(df)` | Human-readable dataset stats |

**Gotchas:**
- Requires `pandas`, `numpy`, `requests` — guarded with try/import flags
  (`_PANDAS_OK`, `_REQUESTS_OK`). Will log errors and degrade gracefully if missing.
- `EODHD_API_KEY` read from env var — if missing, warns once at init.
- `build_dataset()` has a stray extra indentation before the
  `ticker_win_rate` computation block (cosmetic, not a bug).
- `ticker_win_rate` is only set on signals where `outcome in ('WIN', 'LOSS')`
  before the TIMEOUT conversion — TIMEOUT signals that become LOSS get
  `sig['ticker_win_rate'] = ticker_win_rates.get(...)` inside the loop but
  only after the win-rate dict is built from WIN/LOSS-only signals. This is
  correct — timeouts are excluded from win-rate calculation intentionally.

---

## Issues Found This Batch

### Issue #48 — MEDIUM — T1 half-exit P&L not captured in Trade objects

**File:** `backtest_engine.py` → `manage_positions()` → T1 branch  
**Symptom:** When T1 target is hit, `position.shares //= 2` reduces size but
no `Trade` object is created for the half-exit. Only the final close (T2/STOP/EOD)
produces a Trade. This means:
- T1 profit is **not reflected** in `BacktestResults.total_pnl`
- Win rate and profit factor calculations **undercount** profits on T1/T2 wins
- P&L in `current_capital` is also wrong (no credit for T1 exit)

**Status:** ⚠️ Open  
**Fix required:** Create a partial `Trade` record at T1 hit with `exit_reason='T1'`
and credit `current_capital` with the half-exit P&L.

---

### Issue #49 — LOW — `print()` used instead of `logger` in engine and optimizer

**Files:** `backtest_engine.py` (`run()` method), `parameter_optimizer.py`
(`grid_search()` method)  
**Symptom:** Two `print()` calls produce output that bypasses the logging
framework. On Railway these appear in stdout but cannot be filtered, levelled,
or routed to the structured log handler.

**Lines:**
- `backtest_engine.py` line ~285: `print(f"\n[BACKTEST] Complete: ...")`
- `parameter_optimizer.py` lines ~95, ~107: two `print()` calls inside
  grid_search loop

**Status:** ⚠️ Open  
**Fix required:** Replace all `print()` calls with `logger.info()`.

---

## Key Architecture Facts for This Module

- **`historical_trainer.py` is completely self-contained** — it re-implements
  the BOS/FVG detection logic locally (`_detect_signal()`) rather than
  importing from `app/signals/`. This means any change to live signal logic
  in `bos_fvg_engine.py` must be **manually mirrored** to `_detect_signal()`
  or training data will diverge from live signal quality.
- **`BacktestEngine` is stateful** — calling `run()` resets `current_capital`,
  `positions`, and `trades`. Safe to reuse the same instance across multiple
  `run()` calls (as `ParameterOptimizer` does).
- **`WalkForward` produces truly OOS validation** — the model sees train data
  only during optimization; the OOS test window is never touched during that
  step. This is the most reliable anti-overfit signal in the system.
- **Grid search has no regularisation** — the best-ranked train params could
  still overfit. Walk-forward is the only guard against this.
- **No integration with live scheduler yet** — nothing calls
  `HistoricalMLTrainer.build_dataset()` or `WalkForward.run()` automatically.
  These must be triggered manually or wired to `eod_reporter.py`.

---

## Next Batch

`app/` root-level files or `app/alerts/` — confirm before proceeding.
