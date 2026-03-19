# Batch 2: Signal Engine — COMPLETE

**Modules**
- app/signals/breakout_detector.py
- app/signals/opening_range.py
- app/signals/signal_analytics.py

**Status: COMPLETE — 11 findings across 3 sub-sections.**

---

## Batch 2.A: breakout_detector.py — CLOSED

**Key invariants confirmed**
- `detect_breakout()` uses `bars[:-1]` for both S/R calculation and EMA volume — signal bar excluded. ✅
- Guard: `if ema_volume == 0 or atr == 0: return None`. ✅
- PDH/PDL confluence uses relative tolerance. ✅
- T1 and T2 are on the correct side of entry for both bull and bear. ✅

**Findings**
1. (Low) Rename `current_price` → `last_closed_bar_price` in S/R calculation for clarity.
2. (High) Raise `min_confidence` floor from 50 → 65 in `detect_breakout()` to eliminate marginal signals.
3. (Medium) Add `session_date` assertion or `max_age_bars` guard to `detect_retest_entry()`.
4. (Low) Add session date to `_atr_cache` key.
5. (Low) Deduplicate `get_session_levels()` — compute once at top of `detect_breakout()`, pass into S/R method.
6. (Observation) `calculate_position_size()` is unused by live pipeline — label clearly as test utility.

---

## Batch 2.B: opening_range.py — CLOSED

**Key invariants confirmed**
- `classify_or()` never returns before 9:40 ET. ✅
- DYNAMIC entries expire after 30 minutes. ✅
- Secondary range never evaluated before 10:30 ET. ✅
- All bar time extractions use `_to_et_time()`. ✅ (in original extract methods; NOT in Phase 5 #24 helpers — see finding 2.B-2)
- Price sanity clamp uses `np.median`. ✅

**Findings**
1. (Critical) `adjust_signal_for_or()` may be silently skipped in some signal paths — audit all sniper.py call sites.
2. (Critical) `compute_opening_range_from_bars()` and `compute_premarket_range()` use `_bar_time()` without ET coercion — must switch to `_to_et_time()`.
3. (Medium) DYNAMIC TTL comparison strips tz before normalizing to ET — normalize to ET first.
4. (Medium) `get_session_levels()` is an uncached DB read — add 5–10s TTL cache keyed by `(ticker, date)`.
5. (Observation) `sr_range_pct` denominator is `sr_low` — correct.
6. (Observation) `should_scan_now()` is a permanent stub returning True — remove or implement.

---

## Batch 2.C: signal_analytics.py — CLOSED

**Key invariants confirmed**
- Stage transitions enforce correct prior stage via `session_signals` cache. ✅
- All DB connections use try/finally + `return_conn()`. ✅
- `clear_session_cache()` must be called at EOD — caller responsibility.

**Findings**
1. (High) `position_id` column is semantically overloaded — split into `parent_event_id` (linkage) and `position_id` (actual position FK, nullable).
2. (High) VALIDATED/REJECTED rows missing `signal_type`, `direction`, `grade` — carry forward from GENERATED row.
3. (Medium) `session_signals` dict is not thread-safe — add `threading.Lock`.
4. (Medium) Intraday analytics calls mix today's partial data with prior days — scope to `session_date = today` for mid-session reports.
5. (Observation) Discord EOD summary truncates to top 5 rejection reasons by design — no issue.
6. (Observation) Composite index on `(session_date, hour_of_day, stage)` correctly covers hourly funnel query — good design.

---

## Batch 2 Priority Fix List

| Priority | # | Module | Fix |
|----------|---|--------|-----|
| 🔴 Critical | 2.B-1 | opening_range | Audit all sniper.py signal paths — confirm `adjust_signal_for_or()` called unconditionally |
| 🔴 Critical | 2.B-2 | opening_range | Replace `_bar_time()` with `_to_et_time()` in `compute_opening_range_from_bars()` and `compute_premarket_range()` |
| 🟡 High | 2.A-2 | breakout_detector | Raise `min_confidence` floor from 50 → 65 in `detect_breakout()` |
| 🟡 High | 2.C-2 | signal_analytics | Pass `signal_type`, `direction`, `grade` into VALIDATED/REJECTED rows |
| 🟡 High | 2.C-1 | signal_analytics | Rename `position_id` linkage → `parent_event_id`; separate actual position FK |
| 🟠 Medium | 2.B-4 | opening_range | Add TTL cache to `get_session_levels()` |
| 🟠 Medium | 2.B-3 | opening_range | Normalize `current_time` to ET before DYNAMIC TTL comparison |
| 🟠 Medium | 2.C-3 | signal_analytics | Thread-safety lock on `session_signals` |
| 🟢 Low | 2.A-1 | breakout_detector | Rename `current_price` → `last_closed_bar_price` in S/R calculation |
| 🟢 Low | 2.A-5 | breakout_detector | Deduplicate `get_session_levels()` call — compute once, pass to S/R method |
| 🟢 Low | 2.A-4 | breakout_detector | Add session date to ATR cache key |
