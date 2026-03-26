# Batch 49 — app/analytics/ Full Audit
**Date:** 2026-03-26  
**Status:** COMPLETE  
**Auditor:** Perplexity audit assistant  
**Scope:** `app/analytics/` — 9 files

---

## Summary

3 issues found across 9 files. No logic-breaking bugs. Two `print()` calls in hot paths
(same category as the FIX #29 pattern in `mtf_fvg_priority.py`), and one dead variable
assignment in `grade_gate_tracker.py`. Everything else is clean.

---

## Files Audited

| File | Size | Status | Notes |
|------|------|--------|-------|
| `__init__.py` | 1.2KB | ✅ Clean | Re-exports only |
| `ab_test.py` | 3.3KB | ✅ Clean | Shim/fallback pattern correct; DB fallback healthy |
| `ab_test_framework.py` | 9.2KB | ✅ Clean | FIX 13.C-2 confirmed; `return_conn` in all try/finally |
| `cooldown_tracker.py` | 12.4KB | ✅ Clean | FIX 12.C-2, 43.M-9, 43.M-12 all confirmed; UTC-aware throughout |
| `explosive_mover_tracker.py` | 15.3KB | 🟡 2 issues | #46 (print in hot path), #47 (print in hot path) |
| `explosive_tracker.py` | 0.8KB | ✅ Clean | Shim re-exports correct |
| `funnel_analytics.py` | 14.0KB | ✅ Clean | DB try/finally pattern correct; `return_conn(conn)` even on None is safe (return_conn guards it) |
| `funnel_tracker.py` | 4.1KB | ✅ Clean | Shim fallback correct; `record_scan`/`get_funnel_stats` stub functions present |
| `grade_gate_tracker.py` | 7.9KB | 🟡 1 issue | #48 (dead variable in record_gate_rejection) |
| `performance_monitor.py` | 12.6KB | 🟡 1 issue | #49 (print in dashboard — LOW, intentional but should use logger) |

---

## Issues Found

### Issue #46 — LOW
**File:** `app/analytics/explosive_mover_tracker.py`  
**Function:** `track_explosive_override()` (line ~101)  
**Description:** `print()` call in hot-path tracker function — same pattern as FIX #29.

```python
# Current (bad):
print(
    f"[EXPLOSIVE-OVERRIDE] 🚀 {ticker} {direction.upper()} tracked | ..."
)

# Fix:
logger.info(
    f"[EXPLOSIVE-OVERRIDE] 🚀 {ticker} {direction.upper()} tracked | ..."
)
```

**Impact:** Writes to stdout instead of the Railway log stream. Low priority but consistent with the logger convention enforced across the rest of the codebase.

---

### Issue #47 — LOW
**File:** `app/analytics/grade_gate_tracker.py`  
**Function:** `record_gate_rejection()` and `record_gate_pass()` (lines ~104, ~111)  
**Description:** Both `print()` calls in public API methods — same pattern as #46.

```python
# Current (bad):
print(f"[GRADE-GATE] ❌ {ticker} | {grade} | ...")
print(f"[GRADE-GATE] ✅ {ticker} | {grade} | ...")

# Fix:
logger.info(f"[GRADE-GATE] ❌ {ticker} | {grade} | ...")
logger.info(f"[GRADE-GATE] ✅ {ticker} | {grade} | ...")
```

**Impact:** Same as #46 — stdout vs Railway structured log.

---

### Issue #48 — LOW (dead code)
**File:** `app/analytics/grade_gate_tracker.py`  
**Function:** `record_gate_rejection()` (line ~103)  
**Description:** Dead variable assignment that is never used.

```python
# Current (dead):
def record_gate_rejection(self, ...):
    label = 'passed' if False else 'rejected'   # ← always 'rejected', never read
    print(...)
    _record(...)
```

`label` is assigned as `'rejected'` unconditionally (`if False` is always False) and then never referenced. Should be removed entirely.

**Fix:** Delete the `label = ...` line.

---

### Issue #49 — LOW
**File:** `app/analytics/performance_monitor.py`  
**Function:** `_print_dashboard()` (line ~130)  
**Description:** `print()` in the dashboard function. Unlike #46/#47, this is used for live monitoring output — partially intentional — but should use `logger.info` for Railway log stream consistency.

```python
# Current:
print(f"[PERF-MONITOR] 📊 {now_str} | ...")

# Fix:
logger.info(f"[PERF-MONITOR] 📊 {now_str} | ...")
```

**Impact:** LOW — dashboard is called every ~5 min and is display-only. No signal logic impact.

---

## Logic Verification Notes

### ab_test_framework.py
- `SAMPLE_SIZE_REQUIRED = 30`, `MIN_WIN_RATE_DIFF = 5.0` — conservative thresholds, appropriate
- `get_variant()` uses MD5 hash of `{ticker}_{param}_{date}` — deterministic assignment within session, randomizes across days and tickers
- `check_winners()` correctly gates on both sample size AND win rate delta before declaring a winner
- `record_outcome()` try/except with `logger.info` (not raise) — non-fatal DB writes correct

### cooldown_tracker.py
- FIX 43.M-9 confirmed: `cleanup_expired_cooldowns()` called only from `set_cooldown()`, not from `_load_cooldowns_from_db()`
- FIX 12.C-2 confirmed: `expires_at` always normalised to UTC-aware in both `_load_cooldowns_from_db()` and `is_on_cooldown()`
- `COOLDOWN_SAME_DIRECTION_MINUTES = 30`, `COOLDOWN_OPPOSITE_DIRECTION_MINUTES = 15` — asymmetric reversal cooldown is correct; same-direction block is longer
- `is_on_cooldown()` evicts expired in-memory entries AND calls `_remove_cooldown_from_db()` — cache + DB stay in sync
- `_maybe_load_cooldowns()` — lazy-load on first call; `_cooldowns_loaded` flag prevents repeated DB reads across scanner cycles ✅

### explosive_mover_tracker.py
- FIX 13.C-1 confirmed: all `conn.close()` replaced with `return_conn(conn)` in `try/finally`
- `get_daily_override_stats()` contains a legacy Postgres/SQLite branch using `__import__` inline detection — this pattern is stale (the rest of the codebase uses `ph()` for parameterization). No bug, but a code smell. Tracked as Issue #50 (LOW) below.

### funnel_analytics.py
- `return_conn(None)` in `finally` blocks — safe because `return_conn` guards against None input
- `get_daily_report()` `from_prev_pct` arithmetic: `stats['passed'] / prev_passed * 100` — correct; `prev_passed` is only set when `stats['total'] > 0`, so no ZeroDivisionError
- Hourly breakdown uses `defaultdict(lambda: defaultdict(int))` — correct for multi-level sparse hourly data

### grade_gate_tracker.py
- `_record()` correctly uses `try/finally: return_conn(conn)` — DB write is non-fatal ✅
- `reset_daily_stats()` uses `dict.update()` to reset in-place — correct; module-level `_daily_stats` reference preserved
- Issue #48 (`label = 'passed' if False else 'rejected'`) is the only dead code; rest of the file is clean

### performance_monitor.py
- `record_trade_outcome()` correctly tracks peak P&L and rolling drawdown in-memory
- `_MAX_DAILY_LOSS_PCT = -3.0`, `_MAX_DRAWDOWN_PCT = 4.0`, `_MAX_CONSECUTIVE_LOSS = 3` defined but `_consecutive_losses` counter is never incremented — the consecutive loss halt from 47.P5-3 isn't wired yet (planned feature, not a bug in this file)
- `check_performance_dashboard()` cycle counter correctly resets to 0 after printing ✅
- `_persist_snapshot()` called on `print_eod_report()` — DB write deferred to EOD, not per trade ✅

---

## Additional Issue

### Issue #50 — LOW (code smell)
**File:** `app/analytics/explosive_mover_tracker.py`  
**Function:** `get_daily_override_stats()` (line ~149)  
**Description:** Legacy Postgres/SQLite branch detection using `__import__` inline:

```python
cursor.execute(
    "SELECT COUNT(*) FROM ... WHERE DATE(timestamp) = %s"
    if __import__('app.data.db_connection', fromlist=['USE_POSTGRES']).USE_POSTGRES
    else "SELECT COUNT(*) FROM ... WHERE DATE(timestamp) = ?",
    (today,)
)
```

The rest of the codebase uses `ph()` from `db_connection` to abstract the placeholder (`%s` vs `?`). This inline `__import__` pattern is inconsistent and fragile.

**Fix:** Replace with standard `ph()` pattern — `f"... WHERE DATE(timestamp) = {ph()}"`.

**Impact:** LOW — no runtime bug as long as `USE_POSTGRES=True` on Railway. But `ph()` is the established convention.

---

## Batch 49 Issue Registry

| ID | Severity | File | Description | Status |
|----|----------|------|-------------|--------|
| #46 | LOW | `explosive_mover_tracker.py` | `print()` in `track_explosive_override()` | Open |
| #47 | LOW | `grade_gate_tracker.py` | `print()` in `record_gate_rejection/pass()` | Open |
| #48 | LOW | `grade_gate_tracker.py` | Dead variable `label = 'passed' if False else 'rejected'` | Open |
| #49 | LOW | `performance_monitor.py` | `print()` in `_print_dashboard()` | Open |
| #50 | LOW | `explosive_mover_tracker.py` | Inline `__import__` for Postgres detection vs `ph()` | Open |

All 5 are LOW severity — safe to batch into a single "print→logger cleanup pass" alongside the existing FIX #29 pattern.

---

## Next: app/core/ or app/filters/

Suggested next module: `app/filters/` (market_regime_context.py, gex_engine.py, etc.) — directly feeds signal quality (47.P1-2, 47.P1-3 items from batch47 plan).

---

*Batch 49 authored 2026-03-26 by Perplexity audit assistant.*  
*Next batch: 50 — suggested: app/filters/ audit.*
