# War Machine Signal Logic Audit

This document is maintained by the assistant to track the ongoing end-to-end audit of War Machine's signal logic and execution pipeline.

## Scope

- Repository: AlgoOps25/War-Machine
- Focus: Data → Screening → Signals → Risk/Execution → Surrounding services
- Goal: Mathematically clear, invariant-based signal logic with no edge-case failure modes.

## Working Methodology

- Audit is performed in batches, aligned to the live signal pipeline rather than directory layout.
- For each batch we:
  - Document current behaviour and assumptions.
  - Define explicit invariants (what must always be true for correctness).
  - Identify issues, ambiguities, and edge cases.
  - Propose concrete code changes and new/updated tests.
  - Record decisions and rationale here.

## Batches

### Batch 1: Core signal path — COMPLETE

**Modules**
- app/data/data_manager.py
- app/data/ws_feed.py
- app/screening/market_calendar.py
- app/screening/dynamic_screener.py
- app/screening/premarket_scanner.py
- app/screening/volume_analyzer.py
- app/screening/watchlist_funnel.py
- app/risk/position_manager.py

**Status: COMPLETE — 1.A, 1.B, 1.C all closed. See sub-sections below.**

---

### Batch 1.A: Calendar, sessions, and data ingestion — CLOSED

**Status: CLOSED — no outstanding issues.**

**Key invariants confirmed**
- No scanning on weekends or holidays; `build_watchlist()` short-circuits via `is_active_session()`.
- WS-first: no REST intraday calls when `ws_feed.is_connected()` is True.
- `get_today_session_bars()` bounded to today's ET date (04:00–20:00); never falls back to prior day.
- Every WS bar flushed exactly once; 5m bars idempotently materialized.
- REST failover: 15s per-ticker TTL, only when `_connected=False`.

**Findings**
- Holiday sets hard-coded for 2026–2027 only — future years need updates.
- All other invariants confirmed clean.

---

### Batch 1.B: Screener, pre-market scanner, and volume signals — CLOSED

**Status: CLOSED — no outstanding issues.**

**Key invariants confirmed**
- ETFs (except SPY/QQQ) never leak into scored universe; Tier D (sub-1.0 RVOL) hard-dropped.
- Pre-market RVOL uses cumulative intraday volume; REST bars clamped (10×).
- `fetch_fundamental_data()` failure → `scan_ticker()` returns `None` (no ghost scores).
- `price <= 0` after bar resolution → hard-stop for that ticker.
- `detect_catalyst()` called at most once per scan; Discord failures non-blocking.
- Composite = 0.60·volume + 0.25·gap + 0.15·catalyst + sector_bonus (no alternate weight path).

**Findings**
- All ghost-score paths closed by Phase 1.23–1.29.
- Gap analysis uses REST `open` + `previousClose`; 0.0% bug resolved.
- Catalyst: strict keywords, 48h window, per-ticker cache.

---

### Batch 1.C: Watchlist funnel and position manager — CLOSED

**Status: CLOSED — 4 actionable items recorded (see original section).**

**Outstanding action items**
1. (**Safety**) `open_position()`: add T1/T2 ordering assertion.
2. (**Design**) Replace static `SECTOR_GROUPS` lookup with dynamic screener `sector` field.
3. (**Low**) Cap live-stage volume signal adjustment at ±5 per ticker (deduplicate).
4. (**Minor**) Remove redundant inline bypass check from `_build_narrow_scan()`.

---

### Batch 2: Signal engine — COMPLETE

**Modules**
- app/signals/breakout_detector.py
- app/signals/opening_range.py
- app/signals/signal_analytics.py

**Status: COMPLETE — 11 findings. See sub-sections below.**

---

### Batch 2.A: breakout_detector.py — CLOSED

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

### Batch 2.B: opening_range.py — CLOSED

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

### Batch 2.C: signal_analytics.py — CLOSED

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

---

### Batch 3: Core pipeline orchestration — IN PROGRESS

**Modules**
- app/core/sniper.py (65KB — primary orchestrator)
- app/core/arm_signal.py (position open, Discord, armed state, cooldown)
- app/core/armed_signal_store.py (DB persistence for armed signals)
- app/core/watch_signal_store.py (DB persistence for watch signals)
- app/core/analytics_integration.py (analytics wiring)
- app/core/thread_safe_state.py (state management)

**Objectives**
- Trace every signal path end-to-end through `process_ticker()` and `_run_signal_pipeline()`.
- Confirm all gates (cooldown, greeks, VWAP, regime, validator, confidence, hourly) fire in the correct order and cannot be silently bypassed.
- Confirm `adjust_signal_for_or()` (finding 2.B-1) is actually wired — or confirm it is missing.
- Confirm arm → position → Discord → analytics sequence is atomic-enough.
- Confirm watch/armed persistence is correct across Railway restarts.
- Confirm VWAP reclaim path is gated correctly and does not bypass the standard pipeline.

---

### Batch 3.A: `_run_signal_pipeline()` — gate ordering and confidence math

**Current gate order (confirmed from code)**

```
1. DB cooldown gate          (is_on_cooldown — restart-safe)
2. Analytics cooldown        (in-memory, non-blocking)
3. Options pre-gate          (greeks_precheck → validate_signal_greeks → options_filter)
4. Volume profile validation (get_volume_analyzer().validate_entry)
5. Confirmation              (wait_for_confirmation OR skip_cfw6_confirmation path)
6. Entry timing validation   (get_entry_timing_validator)
7. Order block cache         (identify_order_block → cache_order_block)
8. VWAP directional gate     (passes_vwap_gate)
9. MTF Bias gate (1H+15m)    (mtf_bias_engine.evaluate)
10. Grade confirmation        (grade_signal_with_confirmations)
11. Confidence construction   (compute_confidence + MTF trend + SMC + multipliers)
12. Post-3pm decay
13. Dynamic threshold gate    (get_dynamic_threshold)
14. Hourly gate modifier      (get_hourly_confidence_multiplier × eff_min)
15. Final confidence ≥ eff_min gate
16. arm_ticker()
```

**Key invariants to validate**
- Gates must be in the correct order: blocking gates before expensive operations.
- `adjust_signal_for_or()` must appear somewhere in this chain for OR signals.
- Confidence must be clamped to [0.40, 0.95] before the gate check.
- `arm_ticker()` must be called only after all gates pass.

**Findings**

1. **ISSUE — `adjust_signal_for_or()` is CONFIRMED MISSING from `_run_signal_pipeline()` (Critical — closes 2.B-1)**
   A full search of `_run_signal_pipeline()` and `process_ticker()` finds zero calls to `adjust_signal_for_or()` or `adjust_signal_confidence()`. The OR width classification (`or_detector.classify_or()`) is called *after* `_run_signal_pipeline()` completes (at the very bottom of `process_ticker()`), which means it is purely cosmetic/logging. The WIDE OR 75% minimum confidence and TIGHT OR +5% boost from `opening_range.py` are **never applied** to live signals. This is a silent signal quality failure — wide-OR, low-quality setups pass the confidence gate with no penalty.
   **Fix**: Call `or_detector.classify_or(ticker)` *before* `_run_signal_pipeline()` in `process_ticker()`, then pass the classification into `_run_signal_pipeline()` as a parameter. Inside the pipeline, apply `or_detector.adjust_signal_confidence(or_data, confidence)` immediately before the dynamic threshold gate (step 13 above). Move `_orb_classifications[ticker] = or_data` to this earlier call point.

2. **ISSUE — Analytics cooldown (step 2) is a hard `return False`, not just a warning (logic error)**
   The header comment says "in-memory reporting, non-blocking" but the code does `return False` when `is_in_cooldown()`. This means the in-memory analytics cooldown *also blocks* the signal. If the in-memory cooldown and the DB cooldown have different TTLs (they do — analytics cooldown is session-only, not persisted), a signal that is not actually in DB cooldown can be incorrectly dropped after a restart that clears in-memory state but is within the old analytics window. **Fix**: Change the analytics cooldown block to `print(...)` only, matching the stated intent of "non-blocking", or explicitly remove it and rely solely on the DB-persisted cooldown at step 1.

3. **ISSUE — Entry price for greeks pre-gate uses `bars_session[-1]["close"]` which may be stale (minor)**
   At step 3, `_proxy_entry = bars_session[-1]["close"]` is used as the entry price for greeks validation. This is the last *completed* bar, not the actual confirmation price (which is determined at step 5). If confirmation runs multiple bars later, the greeks check is done against a price that could be 0.3–0.8% away from actual entry. For ATM strikes this can mean validating the wrong strike. **Fix**: Run the greeks check *after* confirmation (step 5) using the confirmed `entry_price`, or accept this as an acceptable approximation (the current tolerance in `validate_signal_greeks()` is ±2 strikes, so it rarely matters in practice).

4. **ISSUE — Volume profile hard-blocks signal but is not gated by VOLUME_PROFILE_ENABLED on the *filter* path, only on the fetch path**
   If `VOLUME_PROFILE_ENABLED = True` and `get_volume_analyzer()` returns a non-None analyzer, but the ticker has no volume data (empty bars → `validate_entry()` returns `is_valid=False` for the wrong reason), the signal is dropped with `return False`. There is no check for whether the VP failure is a genuine "price outside high-volume zone" vs "insufficient data to build the profile". **Fix**: Add a minimum bar count guard inside `validate_entry()` and/or propagate a `data_insufficient` flag that causes VP to be skipped rather than blocking.

5. **ISSUE — `_mtf_bias_adj` is initialized to `0.0` in the `else` branch but is also `0.0` if `MTF_BIAS_ENABLED` is True and the check raises an exception (silent)**
   If `mtf_bias_engine.evaluate()` raises an exception, `_mtf_bias_adj = 0.0` and execution continues — *including calling `arm_ticker()`*. This is the intended non-fatal behavior. However, the exception path also skips `mtf_bias_engine.record_stat()`, meaning the MTF bias stat tracker silently under-counts evaluations for any ticker that throws. **Fix**: catch the exception separately and still call `mtf_bias_engine.record_stat(ticker, direction, {'pass': None, 'error': True})` for accurate tracking.

6. **ISSUE — Confidence formula applies `mode_decay = 0.95` for `CFW6_OR` signals but the final `_orb_classifications` OR adjustment is never applied (reinforces finding 3.A-1)**
   `mode_decay = 0.95` is applied to CFW6_OR signals in `mult_to_adjustment()`. This is the *only* OR-related confidence adjustment actually in the pipeline. It is a flat 5% penalty on all CFW6_OR signals regardless of OR width. WIDE OR signals (which should require 75% confidence) and TIGHT OR signals (which should receive a +5% boost) are both treated identically — both get the same flat 5% mode decay. This is a direct consequence of `adjust_signal_for_or()` never being called.

7. **ISSUE — Confidence is clamped to [0.40, 0.95] but the threshold gate `eff_min` can theoretically also be above 0.95 (edge case)**
   `eff_min` is computed as `max(min_type, min_grade, CONFIDENCE_ABSOLUTE_FLOOR)`. If hourly gate multiplies `eff_min *= hourly_mult` and `hourly_mult` is high (e.g., 1.3 for a very weak hour), `eff_min` could exceed 0.95. Since `final_confidence` is capped at 0.95, any signal in a weak hour could be permanently ungatable. In practice, `hourly_mult` is unlikely to push `eff_min` above 0.95, but no explicit cap exists. **Fix**: add `eff_min = min(eff_min, 0.92)` after the hourly gate multiplication.

8. **OBSERVATION — `or_high_ref` / `or_low_ref` on the INTRADAY_BOS path are set to `bos_price` / `zone_low` (bull) or `zone_high` / `bos_price` (bear), not to actual OR levels**
   This is intentional — for INTRADAY_BOS there is no OR to anchor to; the BOS price serves as the reference. `compute_stop_and_targets()` uses these as context references, not as hard price levels. No issue, but worth documenting explicitly.

---

### Batch 3.B: `process_ticker()` — scan flow, watch management, VWAP reclaim

**Current scan flow (confirmed)**

```
1. Load watches + armed signals from DB
2. Performance dashboard + alert checks
3. Regime filter (explosive override if qualified)
4. Early return if ticker already armed
5. Fetch bars (production_helper or direct)
6. SD zone cache
7. SPY EMA regime context
8. Force-close time check → EOD reports
9. Watch resolution (bar index recovery from datetime)
10. Watch expiry check (MAX_WATCH_BARS = 12)
11. Watch continuation (FVG search → pipeline if found)
12. OR range detection (compute_opening_range_from_bars)
    a. Narrow OR → skip OR path, fall to intraday
    b. Early session gate (should_skip_cfw6_or_early)
    c. OR breakout detection (detect_breakout_after_or)
    d. FVG search → pipeline OR watch entry
    e. If 10:30+ and no scan: secondary range check
13. INTRADAY_BOS path (scan_bos_fvg)
14. _run_signal_pipeline()
15. ORB classify (cosmetic, AFTER pipeline) ← out of order (see 3.A-1)
16. VWAP reclaim check (only if scan_mode is None)
```

**Findings**

9. **ISSUE — VWAP reclaim path fires only when `scan_mode is None` (after the full OR + BOS scan) but uses `skip_cfw6_confirmation=True` without any session time guard (medium)**
   `detect_vwap_reclaim()` is called only when no scan_mode was set (no OR breakout, no BOS+FVG found). This is correct gating. However, `_run_signal_pipeline()` is called with `skip_cfw6_confirmation=True`, meaning the signal proceeds directly from `bars_session[-1]["close"]` as entry price with no retest confirmation, no FVG zone (the zone is a ±0.15% synthetic band around VWAP), and no session time check. There is no guard preventing VWAP reclaim signals before 9:45 or after 15:30. **Fix**: add time-of-day guards to the VWAP reclaim block (`_now_et().time() >= time(9, 45)` and `< time(15, 30)`).

10. **ISSUE — Watch restoration relies on exact `datetime` match (`_strip_tz(bar["datetime"]) == bar_dt_target`) which fails if bar timestamps are resampled with sub-second differences (medium)**
    After a Railway restart, the watch entry stores `breakout_bar_dt` from `_strip_tz(bars_session[breakout_idx]["datetime"])`. On reload, `process_ticker()` iterates all bars looking for an exact datetime match. If the bar timestamp is stored with microsecond precision but reloaded as a truncated timestamp (e.g., via SQLite's TEXT serialization which drops microseconds), the match fails and the watch is discarded. **Fix**: truncate both sides to second precision before comparison: `bar_dt.replace(microsecond=0) == bar_dt_target.replace(microsecond=0)`.

11. **ISSUE — `should_skip_cfw6_or_early()` prints a misleading reason string (minor)**
    The early session gate prints: `"EARLY SESSION GATE: CFW6_OR blocked before 9:45 AM (OR=X.XX% < threshold)"` — but the gate is controlled by `should_skip_cfw6_or_early(or_range_pct, now_et)` which checks time, not whether OR is below the threshold (that check already happened above). The `< or_threshold` in the log message is a copy-paste from the narrow OR message. **Fix**: update the print message to `"OR={or_range_pct:.2%} — time-gated before 9:45"` so it's not confused with the narrow-OR skip.

12. **ISSUE — `_bos_watch_alerted` set is in-memory only and is never persisted or cleared across restarts**
    The BOS watch dedup set (`_bos_watch_alerted`) prevents sending the same BOS watch alert twice per session. However, it is reset to an empty set on every Railway restart. If the bot restarts mid-session and the same BOS is detected again, a duplicate Discord alert fires. The fix is low-friction because the watch itself IS persisted (via `_persist_watch`) and `_maybe_load_watches()` will reload it — so the watch won't be duplicated. But the Discord alert will fire again. **Fix**: Populate `_bos_watch_alerted` from the loaded watch DB entries at startup inside `_maybe_load_watches()` by reconstructing the key `f"{ticker}:{direction}:{breakout_bar_dt}"`.

13. **OBSERVATION — `_orb_classifications` is populated AFTER `_run_signal_pipeline()` (confirmed redundant)**
    This was already identified in 3.A-1. The ORB classification is stored to `_orb_classifications[ticker]` purely for logging after the pipeline runs. It is never read back anywhere in `process_ticker()` or `_run_signal_pipeline()`. This confirms the classification is decorative and `adjust_signal_for_or()` is not wired.

---

### Batch 3.C: `arm_signal.py` — arming sequence integrity

**Current sequence (confirmed)**
```
1. Stop tightness guard (< 0.1% of entry → skip)
2. log_proposed_trade()
3. get_ticker_screener_metadata()
4. position_manager.open_position() → position_id
5. If position_id == -1 → return (no alert)
6. record_trade_executed() (analytics TRADED stage)
7. Discord alert (production_helper path or fallback)
8. _persist_armed_signal() + _state.set_armed_signal()
9. set_cooldown()
```

**Key invariants confirmed**
- Discord alert fires only after `position_id > 0`. ✅ (FIX C2, Mar 10)
- Cooldown set only after successful position open. ✅
- Analytics TRADED stage recorded after position open. ✅ (FIX Mar 16)

**Findings**

14. **ISSUE — `log_proposed_trade()` is called before `position_id` is known (step 2 vs step 4)**
    `log_proposed_trade()` fires before `open_position()`, meaning it logs a trade that may never open (e.g., if the risk manager rejects it). This pollutes the proposed-trade log with false entries. **Fix**: move `log_proposed_trade()` to after step 5 (after confirming `position_id != -1`), matching the same pattern as the Discord alert.

15. **ISSUE — `screener_integration.get_ticker_screener_metadata()` is imported inside `arm_ticker()` via a deferred import, but it also appears in `sniper.py` as a try/except stub**
    If `screener_integration` is unavailable (which it is — the module was deleted and replaced with a stub in sniper.py), the arm_ticker deferred import `from app.screening.screener_integration import get_ticker_screener_metadata` will raise `ImportError` at runtime during position open. This is a latent crash risk. **Fix**: replace the deferred import in `arm_signal.py` with the same try/except stub pattern used in `sniper.py`, so it falls back to `{'qualified': False, 'score': 0, 'rvol': 0.0, 'tier': None}` gracefully.

16. **ISSUE — `record_trade_executed()` failure is caught and printed but does not block arming (by design) — however the ARMED stage may not have been recorded either**
    `record_trade_executed()` in `signal_analytics` checks `session_signals[ticker]['stage'] == 'ARMED'` before proceeding. If `record_signal_armed()` was never called (because PHASE_4_ENABLED was False, or a tracking error occurred at that step in `_run_signal_pipeline()`), `record_trade_executed()` prints a warning and returns -1. The TRADED stage is silently lost and the funnel shows a gap. **Fix**: confirm PHASE_4_ENABLED is True in production and add a health-check log at startup that verifies `signal_tracker is not None`.

17. **OBSERVATION — `arm_ticker()` does not call `_state.remove_watching_signal()` or `_remove_watch_from_db()`**
    Watch cleanup happens in `process_ticker()` *after* `_run_signal_pipeline()` returns `True` from the watch continuation path. The arm function doesn't need to know about watches — this is correct separation of concerns. ✅

18. **OBSERVATION — `sniper_log.log_proposed_trade` is imported with a try/except stub in sniper.py, but in arm_signal.py it is imported as a hard import (no fallback)**
    Same pattern as finding 3.C-15. Any deleted/missing module imported without a fallback in `arm_signal.py` is a hidden crash risk since arm_signal is called from the hot path. **Recommendation**: all imports inside `arm_signal.py` that were previously wrapped in try/except stubs in sniper.py should be similarly wrapped here.

---

## Batch 3 Priority Fix List

| Priority | # | Module | Fix |
|----------|---|--------|-----|
| 🔴 Critical | 3.A-1 | sniper.py | Wire `adjust_signal_for_or()` into `_run_signal_pipeline()` — CONFIRMED MISSING; OR quality filter is completely bypassed |
| 🔴 Critical | 3.A-2 | sniper.py | Fix analytics cooldown block — change `return False` to print-only (or remove); rely solely on DB cooldown |
| 🔴 Critical | 3.C-15 | arm_signal.py | Wrap `screener_integration` import in try/except stub to prevent runtime ImportError during position open |
| 🟡 High | 3.A-7 | sniper.py | Cap `eff_min = min(eff_min, 0.92)` after hourly gate multiplication to prevent ungatable threshold |
| 🟡 High | 3.B-9 | sniper.py | Add time-of-day guards to VWAP reclaim path (≥ 9:45, < 15:30) |
| 🟡 High | 3.C-14 | arm_signal.py | Move `log_proposed_trade()` to after `position_id > 0` check |
| 🟡 High | 3.C-18 | arm_signal.py | Wrap all try/except-stub imports from sniper.py with matching fallbacks in arm_signal.py |
| 🟠 Medium | 3.B-10 | sniper.py | Truncate both sides to second precision in watch datetime match |
| 🟠 Medium | 3.B-12 | sniper.py | Populate `_bos_watch_alerted` from DB-loaded watches at startup to prevent duplicate alerts after restart |
| 🟠 Medium | 3.A-4 | sniper.py | Run greeks check after confirmation so `entry_price` is the confirmed price, not the last bar close |
| 🟠 Medium | 3.A-5 | sniper.py | Add `data_insufficient` flag to volume profile `validate_entry()` to skip rather than block on no-data |
| 🟠 Medium | 3.C-16 | sniper.py | Add startup health-check log confirming `signal_tracker is not None` and `PHASE_4_ENABLED = True` |
| 🟢 Low | 3.B-11 | sniper.py | Fix misleading early session gate log message |
| 🟢 Low | 3.A-5b | sniper.py | Call `mtf_bias_engine.record_stat()` even on exception path for accurate stat tracking |

---

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
