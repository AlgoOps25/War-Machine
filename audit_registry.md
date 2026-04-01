# War Machine — Audit Registry

> **Purpose:** Permanent, file-by-file record of every audit session.
> Tracks what was reviewed, what was found, what was fixed, and what remains.
> Updated after every commit. Never delete entries — append only.
>
> **Size rule:** Keep this file under 90 KB (GitHub 100 KB pull limit).
> Split into `audit_registry_2.md` if approaching that limit.

---

## Quick Reference — Open Issues

| ID | File | Severity | Description | Status |
|----|------|----------|-------------|--------|
| BUG-OR-1 | `app/signals/opening_range.py` | HIGH | `_detect_orb_breakout()` uses `bar['close']` directly — KeyError if bar dict missing 'close' key | **OPEN** |
| BUG-OR-2 | `app/signals/opening_range.py` | MEDIUM | No guard against division-by-zero when `or_range == 0` in extension calc | **OPEN** |
| BUG-WF-1 | `app/backtesting/walk_forward.py` | LOW | Month windows use `timedelta(days=30*n)` — 1-2 day drift per window over long runs | **KNOWN / DEFERRED** |

---

## Folder Progress

| Folder | Files | Audited | Clean | Fixed | Skipped |
|--------|-------|---------|-------|-------|---------|
| `app/` (root) | 1 | 1 | 1 | 0 | 0 |
| `app/core/` | 6 | 6 | 6 | 0 | 0 |
| `app/backtesting/` | 8 | 1 | 0 | 1 | 0 |
| `app/signals/` | ~6 | 1 | 0 | 0 | 0 |
| `app/filters/` | TBD | 0 | — | — | — |
| `app/indicators/` | TBD | 0 | — | — | — |
| `app/mtf/` | TBD | 0 | — | — | — |
| `app/risk/` | TBD | 0 | — | — | — |
| `app/screening/` | TBD | 0 | — | — | — |
| `app/validation/` | TBD | 0 | — | — | — |
| `app/ml/` | TBD | 1 | 0 | 1 | 0 |
| `app/analytics/` | TBD | 0 | — | — | — |

---

## Session Log

---

### Session CORE-1 — `app/__init__.py`, `app/core/` (6 files)
**Date:** 2026-03-31
**Commit:** `0c2290af`
**Result:** ✅ All 6 files clean — zero bugs, zero fixes

#### Files Audited

| File | Size | Verdict | Notes |
|------|------|---------|-------|
| `app/__init__.py` | 54 B | ✅ Clean | Correct namespace init; no logic |
| `app/core/__init__.py` | 22 B | ✅ Clean | Correct namespace init; no logic |
| `app/core/__main__.py` | 1.4 KB | ✅ Clean | Boot order correct: logging → health → DB pool → scanner loop |
| `app/core/logging_config.py` | 3.5 KB | ✅ Clean | `_CONFIGURED` guard prevents duplicate handlers; `root.handlers.clear()` correct; `_QUIET_LOGGERS` list appropriate |
| `app/core/sniper_log.py` | 2.9 KB | ✅ Clean | Never raises; fallback `print()` is intentional (last-resort Railway console visibility) |
| `app/core/eod_reporter.py` | 4.3 KB | ✅ Clean | Independent `try/except` blocks per section; ET-aware; no stray prints |
| `app/core/health_server.py` | 6.1 KB | ✅ Clean | `_started` guard prevents double-bind on port; `_is_market_hours()` called once per request; heartbeat seeded at startup |

#### How These Files Coexist
- `__main__.py` is the single entry point. It calls `configure_logging()` first, then starts the health server, then initialises the DB pool, then enters the scanner loop.
- `logging_config.py` is called exactly once via `_CONFIGURED` guard — all subsequent imports of any module get the already-configured root logger.
- `sniper_log.py` wraps `logging.getLogger('sniper')` and adds a safety net `print()` so Railway always shows critical messages even if the logging pipeline fails.
- `eod_reporter.py` is called from the scanner loop at EOD. It is self-contained and does not depend on any signal or ML state.
- `health_server.py` runs in a background thread started by `__main__.py`. It owns the `/health` and `/heartbeat` endpoints used by Railway's health checks.

---

### Session BT-1 — `app/backtesting/walk_forward.py`
**Date:** 2026-04-01
**Commit:** `efc2d587` (BUG-WF-2 fix — already present in repo at audit time)
**Result:** 1 bug fixed (BUG-WF-2)

#### Files Audited

| File | Size | Verdict | Notes |
|------|------|---------|-------|
| `app/backtesting/walk_forward.py` | ~9 KB | ✅ Fixed | BUG-WF-2 resolved — see below |

#### BUG-WF-2 — `'datetime'` KeyError on EODHD bars
- **Root cause:** `create_windows()` and `run()` accessed `bars[0]['datetime']` directly. EODHD bars from `historical_trainer` use `'timestamp'` as the key, not `'datetime'`. Any WalkForward run fed EODHD-sourced data would immediately raise `KeyError: 'datetime'`.
- **Fix:** Introduced `_bar_datetime(bar)` helper function that tries `bar.get('datetime')` first, then falls back to `bar.get('timestamp')`, and also handles string → `datetime` parsing for both `%Y-%m-%d %H:%M:%S` and `%Y-%m-%dT%H:%M:%S` formats. All bar datetime access throughout the file now routes through this helper.
- **Also added:** `None` guard after `_bar_datetime()` calls — if neither key exists, the function logs a warning and returns `[]` rather than crashing.
- **BUG-WF-1 (deferred):** Window boundaries still use `timedelta(days=30 * months)`. This is a known approximation causing 1–2 day drift over long runs. Marked in module docstring. Fix requires `dateutil.relativedelta` — deferred to a dedicated refactor session.

#### How This File Fits the System
- `WalkForward` is used by `app/ml/historical_trainer.py` to validate strategy parameters on out-of-sample data before any live deployment.
- It depends on `BacktestEngine` (executes trades on a window of bars) and `ParameterOptimizer` (grid-searches param combinations on the train window).
- `WalkForwardResults` aggregates all OOS windows into a single performance summary used to gate model acceptance.

---

### Session ML-1 — `app/ml/historical_trainer.py` (partial)
**Date:** 2026-03-30 (pre-registry)
**Commit:** `0c2290af` (bundled with CORE-1)
**Result:** 1 bug fixed (BUG-HT-1)

#### BUG-HT-1 — `ticker_win_rate` only assigned for TIMEOUT outcomes
- **Root cause:** In `build_dataset()`, the line `sig['ticker_win_rate'] = ticker_win_rates.get(ticker, 0.40)` was nested inside the `if outcome == 'TIMEOUT':` block. WIN and LOSS rows silently received the hardcoded `0.40` fallback inside `_signal_to_features()`.
- **Fix:** Dedented the assignment out of the `TIMEOUT` block so all signals (WIN, LOSS, TIMEOUT) receive the correctly computed per-ticker win rate from the `ticker_win_rates` dict.

---

## Conventions

### Severity Levels
| Level | Meaning |
|-------|---------|
| **CRITICAL** | Will cause a crash or silent data corruption in live trading |
| **HIGH** | Will crash under realistic conditions (e.g. missing dict key on live data) |
| **MEDIUM** | Logic error that degrades results but doesn't crash |
| **LOW** | Style, approximation, or deferred improvement |

### Bug ID Format
`BUG-{MODULE}-{N}` — e.g. `BUG-WF-2` = second bug found in the WalkForward module.

### Commit References
All commits are on the `main` branch of `AlgoOps25/War-Machine`.

---

*Registry started: 2026-03-31. Last updated: 2026-04-01.*
