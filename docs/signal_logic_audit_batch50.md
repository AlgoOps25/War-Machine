# Signal Logic Audit — Batch 50
## Phase 3: `app/analytics/` — Complete Module Audit
**Date:** Mar 27 2026  
**Auditor:** Perplexity AI (assisted)  
**Status:** ✅ COMPLETE — 3 issues found, all fixed and committed

---

## Module Overview

`app/analytics/` is the **observability and analytics layer** for War Machine.
It tracks every signal from generation through to fill, measures cooldowns,
records A/B experiment outcomes, monitors live P&L, and provides EOD reports.
It does **not** generate signals — it only observes and records them.

### Architecture: Intentional Shim → Canonical Pattern

Three file pairs exist that look like duplicates but are **not**:

| Shim | Canonical | Purpose |
|---|---|---|
| `ab_test.py` | `ab_test_framework.py` | Legacy import path + CI fallback |
| `explosive_tracker.py` | `explosive_mover_tracker.py` | Legacy import path re-export |
| `funnel_tracker.py` | `funnel_analytics.py` | Legacy import path + CI fallback |

The shims exist so that callers using old import paths continue to work after
the canonical file was created/renamed. **Do not delete any of them.**

---

## File-by-File Documentation

### `__init__.py`
- **Role:** Central export point for the analytics module
- **Imports from:** `funnel_tracker` (shim), `ab_test` (shim),
  `app.core.analytics_integration.AnalyticsIntegration`
- **Exports:** `funnel_tracker`, `ab_test`, 7x `log_*` stage helpers,
  `ANALYTICS_AVAILABLE`, `AnalyticsIntegration`
- **Pattern:** All imports wrapped in `try/except ImportError` — graceful
  degradation if individual modules unavailable
- **Status:** ✅ Clean. No issues.

---

### `ab_test.py` (3.3 KB) — SHIM
- **Role:** Thin shim over `ab_test_framework.py`
- **Exports:** `ab_test` singleton
- **Fallback:** If DB unavailable, creates `_InMemoryABTest` instance —
  ensures unit tests and CI runs without a live Postgres connection
- **Callers:** `__init__.py`, any module using `from app.analytics.ab_test import ab_test`
- **Status:** ✅ Clean. No issues.

---

### `ab_test_framework.py` (9.2 KB) — CANONICAL
- **Role:** Full A/B testing engine. DB-backed experiment tracking.
- **DB Table:** `ab_test_experiments`, `ab_test_results`
- **Experiments tracked (5):**
  - `rvol_threshold` — RVOL minimum for signal qualification
  - `min_confidence` — confidence gate threshold
  - `cooldown_minutes` — cooldown duration
  - `atr_multiplier` — ATR-based target/stop multiplier
  - `lookback_bars` — lookback window for pattern detection
- **Key functions:** `get_variant()`, `record_outcome()`, `check_winners()`
- **Already fixed:** FIX 13.C-2 (Mar 19 2026) — Railway cold-start crash
  when table not yet created; `_ensure_tables()` now called lazily
- **Status:** ✅ Clean. Uses `return_conn()` correctly throughout.

---

### `cooldown_tracker.py` (12.3 KB) — CANONICAL
- **Role:** Prevents duplicate signals across Railway restarts by persisting
  cooldown state to Postgres. Cooldown cache survives restarts.
- **DB Table:** `signal_cooldowns` (ticker PK, direction, signal_type, expires_at)
- **Cooldown Rules:**
  - Same ticker + same direction: 30 min (`COOLDOWN_SAME_DIRECTION_MINUTES`)
  - Same ticker + opposite direction: 15 min (`COOLDOWN_OPPOSITE_DIRECTION_MINUTES`)
- **Hot path protection:** Cleanup (`DELETE`) only runs at write time
  (`set_cooldown()`), never on read (`is_on_cooldown()`) — FIX 43.M-9
- **TZ convention:** `expires_at` stored as UTC. All comparisons use
  `datetime.now(timezone.utc)` — FIX 43.M-12
- **Singleton:** `cooldown_tracker = CooldownTracker(...)` (legacy class shim
  over module-level functions)
- **Key public API:** `is_on_cooldown()`, `set_cooldown()`, `clear_cooldown()`,
  `get_active_cooldowns()`, `cleanup_expired_cooldowns()`
- **Already fixed:** FIX 12.C-2, FIX 43.M-9, FIX 43.M-12
- **FIX #43 (Mar 27 2026):** Stray `print()` inside `print_cooldown_summary()`
  row loop replaced with `logger.info()`. All header/footer lines already used
  `logger.info()`; the per-ticker data row was the only bare `print()` remaining.
  Commit: [de44998](https://github.com/AlgoOps25/War-Machine/commit/de4499891e89aeaf4b8f12ce00ed71bf25560f57)
- **Status:** ✅ Clean post-fix.

---

### `explosive_tracker.py` (762 B) — SHIM
- **Role:** Pure re-export shim. Imports everything from `explosive_mover_tracker`
  and re-exports it unchanged.
- **Why it exists:** `sniper.py` and some callers used the short path before
  the canonical file was created.
- **Status:** ✅ Clean. No logic — nothing to fix.

---

### `explosive_mover_tracker.py` (15.5 KB) — CANONICAL
- **Role:** Tracks every signal that bypasses the regime filter due to the
  **Explosive Mover Override** (score ≥ 80, RVOL ≥ 4.0x).
- **DB Table:** `explosive_mover_overrides`
  - Columns: ticker, direction, score, rvol, tier, regime_type, vix_level,
    entry_price, grade, confidence, outcome (PENDING/WIN/LOSS), pnl_pct, timestamp
- **Key functions:**
  - `track_explosive_override()` — records when override fires
  - `update_override_outcome()` — marks WIN/LOSS when trade closes
  - `get_daily_override_stats()` — today’s win rate, avg score/RVOL/confidence
  - `get_threshold_optimization_data(days=30)` — score/RVOL bracket win rates
    for threshold tuning
  - `print_threshold_recommendations()` — EOD bracket analysis report
- **Singleton:** `explosive_tracker = ExplosiveMoverTracker()` (legacy shim class)
- **Already fixed:** FIX 13.C-1 (conn.close → return_conn), FIX 49.A-1
  (print → logger), FIX 49.A-2 (inline `__import__` → `ph()`)
- **Status:** ✅ Clean.

---

### `funnel_tracker.py` (4 KB) — SHIM
- **Role:** Shim over `funnel_analytics.py`. Falls back to
  `_InMemoryFunnelTracker` if DB unavailable (CI-safe).
- **Exports:** `funnel_tracker` singleton + 7 stage helpers:
  `log_screened`, `log_bos`, `log_fvg`, `log_validator`,
  `log_armed`, `log_fired`, `log_filled`
- **Status:** ✅ Clean. No issues.

---

### `funnel_analytics.py` (14 KB) — CANONICAL
- **Role:** Full funnel dashboard. Tracks signal progression through all 7 stages.
- **Funnel stages (in order):**
  `SCREENED → BOS → FVG → VALIDATOR → ARMED → FIRED → FILLED`
- **DB Table:** `funnel_events`
  - Columns: ticker, session (YYYY-MM-DD), stage, passed (0/1), reason,
    confidence, timestamp, signal_id, hour
  - Indexes: `idx_funnel_session_stage`, `idx_funnel_ticker`
- **In-memory counters:** `daily_counters` (dict), `rejection_counts` (dict)
  — reset on new trading day
- **Key methods:**
  - `record_stage(ticker, stage, passed, reason, confidence, signal_id)`
  - `get_stage_conversion(stage, session)` → `{total, passed, failed, conversion_rate}`
  - `get_rejection_reasons(session, limit)` → list of `(reason, count)` tuples
  - `get_daily_report(session)` → formatted string with funnel + top rejections
  - `get_hourly_breakdown(session)` → dict `{hour: {stage: count}}`
- **Singleton:** `funnel_tracker = FunnelTracker()`
- **FIX #42 (Mar 27 2026):** `_initialize_database()` finally block was calling
  `return_conn(conn)` with no `None` guard. If `get_conn()` itself raised,
  `return_conn(None)` would fire a second exception masking the original and
  leaving pool semaphore in undefined state. Fixed to `if conn: return_conn(conn)`
  — consistent with the defensive pattern used across entire repo.
  Commit: [b7de0e5](https://github.com/AlgoOps25/War-Machine/commit/b7de0e5485490e37f6f0bd95994cef9b205b05c7)
- **Status:** ✅ Clean post-fix.

---

### `grade_gate_tracker.py` (8.4 KB)
- **Role:** Records every signal that hits the confidence gate — both passes
  and rejections. Used to measure gate efficiency and calibrate grade
  thresholds over time.
- **DB Table:** `grade_gate_events`
  - Columns: ticker, grade, confidence, threshold, signal_type, result
    (pass/reject), timestamp
- **Key public API (called from `sniper.py`):**
  - `grade_gate_tracker.record_gate_rejection(ticker, grade, confidence, threshold, signal_type)`
  - `grade_gate_tracker.record_gate_pass(ticker, grade, confidence, threshold, signal_type)`
- **EOD report:** Grade distribution, pass/reject rate by grade, threshold calibration view
- **Already fixed:** FIX 49.A-3 (print → logger in `record_gate_rejection/pass`),
  FIX 49.A-4 (dead variable `label = 'passed' if False...` removed)
- **Status:** ✅ Clean.

---

### `performance_monitor.py` (12.8 KB)
- **Role:** Phase 4 live P&L dashboard + risk alert system. Fires Discord
  alerts when risk thresholds are breached.
- **DB Table:** `performance_snapshots` (EOD snapshot per session)
- **Session state (in-memory, reset daily):**
  `signals_generated`, `signals_armed`, `signals_rejected`,
  `wins`, `losses`, `total_pnl_pct`, `peak_pnl_pct`, `max_drawdown_pct`,
  `last_dashboard_ts`, `risk_alerts_fired`
- **Risk constants (hardcoded by design — cannot be changed via env var):**
  - `_MAX_DAILY_LOSS_PCT = -3.0` — halts signal generation if daily P&L < -3%
  - `_MAX_DRAWDOWN_PCT = 4.0` — Discord alert if drawdown exceeds 4%
  - `_MAX_CONSECUTIVE_LOSS = 3` — declared but NOT yet wired into alert logic
    (future enhancement)
- **Dashboard cadence:** Every 60 scanner cycles (~5 min at 5s/cycle)
- **Alert cadence:** Every 20 scanner cycles (~100s)
- **sniper.py integration:**
  ```python
  check_performance_dashboard(_state, PHASE_4_ENABLED)  # every cycle
  check_performance_alerts(_state, PHASE_4_ENABLED, alert_manager, send_simple_message)
  ```
- **Singleton:** `performance_monitor = PerformanceMonitor()`
- **Already fixed:** FIX 49.A-5 (print → logger in `_print_dashboard()`)
- **FIX #44 (Mar 27 2026):** Added prominent config block comment documenting
  all three risk constants, their rationale, and why they are intentionally
  hardcoded (prevent accidental Railway env-var widening). Also noted that
  `_MAX_CONSECUTIVE_LOSS` is declared but the consecutive-loss check is not yet
  wired into `_check_risk_alerts()` — flagged as future enhancement.
  No logic or values changed — documentation/maintainability only.
  Commit: [0c2da9d](https://github.com/AlgoOps25/War-Machine/commit/0c2da9d2e9636cb04eebdddfc580ab915df2df8f)
- **Status:** ✅ Clean post-fix.

---

## Issues Found & Resolved This Batch

| # | File | Severity | Description | Commit | Status |
|---|---|---|---|---|---|
| 42 | `funnel_analytics.py` | MED | `_initialize_database()` finally block called `return_conn(conn)` with no `None` guard — double exception if `get_conn()` raised | [b7de0e5](https://github.com/AlgoOps25/War-Machine/commit/b7de0e5485490e37f6f0bd95994cef9b205b05c7) | ✅ Fixed |
| 43 | `cooldown_tracker.py` | LOW | Stray `print()` in `print_cooldown_summary()` row loop — bypasses Railway log pipeline | [de44998](https://github.com/AlgoOps25/War-Machine/commit/de4499891e89aeaf4b8f12ce00ed71bf25560f57) | ✅ Fixed |
| 44 | `performance_monitor.py` | LOW | Hardcoded risk constants undocumented — no config block, no note that `_MAX_CONSECUTIVE_LOSS` is unwired | [0c2da9d](https://github.com/AlgoOps25/War-Machine/commit/0c2da9d2e9636cb04eebdddfc580ab915df2df8f) | ✅ Fixed |

---

## Architecture Notes for Future Reference

1. **Shim pattern is permanent** — never remove `ab_test.py`,
   `explosive_tracker.py`, or `funnel_tracker.py`. They are load-bearing
   import aliases.

2. **`return_conn(None)` is the #1 recurring bug class** in this codebase
   (Issues #13, #42, others). Any new DB function must follow the pattern:
   ```python
   conn = None
   try:
       conn = get_conn()
       ...
   except Exception as e:
       logger.info(f"[TAG] Error: {e}")
   finally:
       if conn:          # ← THIS GUARD IS REQUIRED
           return_conn(conn)
   ```

3. **`print()` is banned on Railway** — all output must use `logger.info()`.
   Railway only surfaces structured log output; bare `print()` appears
   unformatted without timestamp or log level and is easy to miss.

4. **`_MAX_CONSECUTIVE_LOSS` in `performance_monitor.py` is unwired** —
   when consecutive-loss circuit-breaker is added, hook it into
   `_check_risk_alerts()` alongside the existing daily-loss and drawdown checks.

5. **Explosive override threshold candidates** (for future tuning):
   - Score: 80 (current) — optimize with `get_threshold_optimization_data()`
   - RVOL: 4.0x (current) — optimize with `get_threshold_optimization_data()`
   - Need ≥20 samples per bracket for statistical significance

---

## Phase 3 Status: COMPLETE

**Files audited:** 10/10  
**Issues found:** 3 (1 MED, 2 LOW)  
**Issues resolved:** 3/3  
**Files deleted:** 0 (shim/canonical split is correct)  
**Next phase:** TBD (pending direction from Michael)
