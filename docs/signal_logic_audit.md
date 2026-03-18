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

### Batch 2: Signal engine — IN PROGRESS

**Modules**
- app/signals/breakout_detector.py
- app/signals/opening_range.py
- app/signals/signal_analytics.py

**Objectives**
- Validate that breakout/breakdown and OR-breakout signals are mathematically correct and symmetric (bull/bear parity).
- Validate session-anchoring logic and secondary range mechanics.
- Validate OR confidence adjustment and wide-OR filter are applied consistently before signals reach execution.
- Validate signal_analytics lifecycle state machine: no stage-skip, no duplicate records, correct session scoping.

---

### Batch 2.A: breakout_detector.py

**Current behaviour (summary)**
- `detect_breakout()` fires on the first bar that closes above resistance (bull) or below support (bear) with ≥2× EMA volume and a strong candle (body ≥ 40%, direction-correct). Stop = entry ± ATR×1.5; T1 = entry ± risk×1.5R; T2 = entry ± risk×2.5R.
- `calculate_support_resistance()` is session-anchored (Phase 1.17): uses rolling lookback for intraday levels, then promotes session_high/session_low from `get_session_levels()` when they are the true extremes or price is within 0.5%.
- PDH/PDL confluence: if PDH is within 2% of rolling resistance, resistance snaps to PDH (and likewise for PDL/support).
- `detect_retest_entry()` fires when price revisits the prior breakout level within ATR×0.5, with volume ≥1.5× EMA and a direction-correct strong candle.
- `_calculate_confidence()` starts at base 50, adds up to 30 (volume), 20 (strength), 10 (ATR%), 10 (candle body), 10 (PDH/PDL). Hard floor: 50; signals below 50 confidence suppressed.

**Key invariants**
- `detect_breakout()` must call `calculate_support_resistance(bars[:-1])` and `calculate_ema_volume(bars[:-1])` (excluding the signal bar) so levels and avg volume are not contaminated by the breakout bar itself. ✅ Confirmed.
- `calculate_ema_volume(bars[:-1])` result must never be 0 when there are valid prior bars. Guard: `if ema_volume == 0 or atr == 0: return None`. ✅ Confirmed.
- PDH/PDL confluence snap must use relative tolerance (`abs(pdh - resistance) / resistance < 0.02`), not absolute, to be price-scale invariant. ✅ Confirmed.
- T1 and T2 must both be on the correct side of entry for the signal direction. ✅ Confirmed for both bull and bear paths (entry + risk×R for bull; entry - risk×R for bear).
- `detect_retest_entry()` must never fire without a prior `detect_breakout()` signal providing `breakout_level` and `breakout_type` — callers are responsible for this. (No internal guard; invariant is caller-enforced.)

**Findings**

1. **ISSUE — Session anchoring uses `bars[-1]['close']` as `current_price` before the signal bar exclusion (minor)**
   In `calculate_support_resistance(bars[:-1])`, the `current_price` used for `near_session_high/low` proximity check is `bars[-1]['close']` — but because the caller passes `bars[:-1]`, this is actually the bar *before* the signal bar, which is correct. However, the variable name inside `calculate_support_resistance` references `bars[-1]` of whatever slice was passed, which is implicitly the N-1 bar. This is correct but confusing. **Recommendation**: rename the local variable to `last_closed_bar_price` to make the intent explicit.

2. **ISSUE — `_calculate_confidence()` base score of 50 means the floor is hardcoded into the scorer (informational)**
   The confidence scorer starts at 50 and can only add points (volume +30, strength +20, ATR +10, candle +10, PDH/PDL +10 = max 130 → capped at 100). This means a signal with 2× volume, 0 breakout strength, high ATR, and a doji candle still scores exactly 60 and passes the 50-threshold filter. The real floor for a *useful* signal is higher — around 65–70 in practice. **Recommendation**: raise `min_confidence` filter in `detect_breakout()` from 50 to 65 to avoid marginal signals leaking into the pipeline.

3. **ISSUE — No minimum bar count guard in `detect_retest_entry()` for session context**
   `detect_retest_entry()` requires only `len(bars) >= 3`. It does not verify that the provided `breakout_level` is still within the current session (i.e., it was generated today). If a stale `breakout_level` from a prior session were passed by a caller, the retest check would fire incorrectly. **Recommendation**: add a `session_date` assertion at the call site or add a staleness guard parameter (e.g., `max_age_bars`) to `detect_retest_entry()`.

4. **ISSUE — `_atr_cache` never expires intraday**
   ATR is cached by `(atr, bars_count)` and evicted only when `bars_count` changes. This is correct for a single ticker in a single session. However, if `detect_breakout()` is called with exactly the same number of bars across two different time windows (e.g., after a gap fill produces a duplicate bar count), the cached ATR is reused without recalculation. Low probability in practice but worth noting. **Recommendation**: add a session date key to the cache, or simply accept the risk as negligible given daily `clear_pdh_pdl_cache()` calls do not clear `_atr_cache`.

5. **ISSUE — `detect_breakout()` calls `get_session_levels()` twice per signal (minor perf)**
   Once inside `calculate_support_resistance()` and once again in the `session_anchored` detection block at the bottom of `detect_breakout()`. Each call re-queries the DB via `data_manager.get_today_session_bars()`. For the current scan cadence this is acceptable, but it duplicates a DB read per signal. **Recommendation**: compute `session_levels = get_session_levels(ticker)` once at the top of `detect_breakout()` and pass it into `calculate_support_resistance()` as an optional parameter.

6. **OBSERVATION — `calculate_position_size()` is present in BreakoutDetector but unused by the live pipeline**
   Position sizing is done entirely by `position_manager.py`. The `calculate_position_size()` method here is a standalone utility for testing and is not called by any live code path. No issue — but it should not be treated as a source of truth for actual risk calculations.

---

### Batch 2.B: opening_range.py

**Current behaviour (summary)**
- `classify_or()` extracts 9:30–9:40 bars, computes OR range / ATR, and classifies as TIGHT (<0.5 ATR), NORMAL (0.5–1.5 ATR), or WIDE (>1.5 ATR). If the OR window was missed (mid-session restart), falls back to full session range → DYNAMIC label with 30-minute TTL.
- `get_session_levels()` returns session_high, session_low, session_open from all bars since 9:30 — used by `breakout_detector.calculate_support_resistance()` for session anchoring.
- Phase B1: `classify_secondary_range()` builds a 10:00–10:30 Power Hour range (SECONDARY_TIGHT/NORMAL/WIDE) as a mid-session BOS anchor. Bars are ET-coerced (Phase B1 Bug Fix #6) and price-sanity-clamped (reference × 5×).
- `adjust_signal_confidence()` adds the TIGHT OR boost (+5%) and enforces the WIDE OR minimum confidence (75%). This is the OR→signal integration point.
- Phase 5 #24 functions: `compute_opening_range_from_bars()`, `compute_premarket_range()`, `detect_breakout_after_or()`, `detect_fvg_after_break()` — extracted from sniper.py, used as helpers.

**Key invariants**
- `classify_or()` must never return a result before 9:40 ET. ✅ Confirmed: `_is_or_complete()` gates entry.
- DYNAMIC entries must expire after 30 minutes and re-evaluate. ✅ Confirmed (Phase 1.17 BUG #5 fix).
- Secondary range must never be evaluated before 10:30 ET. ✅ Confirmed: `current_time.time() < config.SECONDARY_RANGE_END` guard.
- All bar time extractions must use `_to_et_time()` to prevent UTC/ET confusion. ✅ Confirmed in all three extract methods.
- Price sanity clamp for secondary range must use median close (not mean) to resist outlier corruption. ✅ Confirmed (`np.median`).

**Findings**

1. **ISSUE — `adjust_signal_confidence()` is not called consistently in the live pipeline (critical)**
   `adjust_signal_confidence()` is defined and correct, but its integration depends entirely on callers (sniper.py / signal_validator) explicitly calling `adjust_signal_for_or(signal)` before confidence is evaluated. If any signal path skips this call, OR-based filtering (WIDE OR min 75%, TIGHT OR +5%) is silently bypassed. **Recommendation**: audit every signal generation path in sniper.py to confirm `adjust_signal_for_or()` is called unconditionally before the confidence threshold check. Make it a mandatory step in the signal validation protocol, not optional.

2. **ISSUE — `compute_opening_range_from_bars()` uses `utils.time_helpers._bar_time()` without ET coercion**
   The Phase 5 #24 helper `compute_opening_range_from_bars()` calls `_bar_time(b)` and compares against `time(9,30)–time(9,40)` without going through `_to_et_time()`. If `_bar_time()` returns a tz-naive UTC time, bars at 13:30–13:40 UTC (= 9:30–9:40 ET) would correctly match, but bars stored with tz-aware UTC datetimes would return their UTC hour and be excluded — exactly the same class of bug that was fixed in `_extract_or_bars()` (Phase B1 Bug Fix #6). **Recommendation**: replace the `_bar_time()` call with `_to_et_time()` in both `compute_opening_range_from_bars()` and `compute_premarket_range()` for consistency.

3. **ISSUE — `classify_or()` DYNAMIC TTL comparison uses mixed tz-naivety (minor)**
   The TTL check does: `current_time.replace(tzinfo=None) - cached_at.replace(tzinfo=None)`. Both sides strip timezone info, which is safe as long as `current_time` is ET-aware (it is, when passed from the live loop) and `_cached_at` was stored as tz-naive ET (it is, per `_classify_from_bars`). However, if `classify_or()` is ever called with a UTC-aware `current_time`, the comparison would produce an incorrect (up to 5h) delta. **Recommendation**: normalize both sides to ET before stripping tzinfo: `current_time.astimezone(ET).replace(tzinfo=None)`.

4. **ISSUE — `get_session_levels()` called directly by `breakout_detector` bypasses OR cache**
   `get_session_levels()` calls `data_manager.get_today_session_bars()` on every invocation — it has no caching. In the hot-path (every scan cycle per ticker), this is an uncached DB read per ticker per signal evaluation. **Recommendation**: add a 5–10 second TTL cache to `get_session_levels()` keyed by `(ticker, date)`, matching the pattern used in `position_manager.py` (FIX #5).

5. **OBSERVATION — Secondary range `sr_low > 0` check for `sr_range_pct` is correct but the denominator should be `sr_low` (confirmed)**
   `sr_range_pct = (sr_range / sr_low) * 100` is standard and correct for intraday ranges. No issue.

6. **OBSERVATION — `should_scan_now()` always returns True**
   The method is a stub: `return True  # scan frequency handled by scanner loop`. This is by design (scan cadence is managed externally). No issue, but the method is dead code and should either be removed or given a real implementation.

---

### Batch 2.C: signal_analytics.py

**Current behaviour (summary)**
- `SignalTracker` records the five lifecycle stages per signal: GENERATED → VALIDATED/REJECTED → ARMED → TRADED. Each stage is a separate DB row in `signal_events`, linked by `position_id` (somewhat misnamed — it holds the prior stage's row ID for linkage, not a position_manager position ID, until the TRADED stage where it holds the actual position ID).
- Session cache (`session_signals`) holds the latest stage and event IDs per ticker for fast in-session lookups.
- Analytics queries: funnel stats, grade distribution, multiplier impact, rejection breakdown (7d), hourly funnel (7d).
- `get_daily_summary()` and `get_discord_eod_summary()` produce human-readable reports.

**Key invariants**
- Each stage transition must be preceded by the correct prior stage in `session_signals`. `record_validation_result()` checks `stage == 'GENERATED'`; `record_signal_armed()` checks `stage == 'VALIDATED'`; `record_trade_executed()` checks `stage == 'ARMED'`. ✅ Confirmed.
- All DB connections must use try/finally with `return_conn(conn)`. ✅ Confirmed (Mar 10 fix).
- Session cache must not span across trading days — `clear_session_cache()` must be called at EOD. (Caller responsibility.)

**Findings**

1. **ISSUE — `position_id` column is overloaded (semantic confusion)**
   In VALIDATED, ARMED rows, `position_id` holds the *prior stage's signal_events row ID* (used as a linkage key). In the TRADED row it holds the *actual position_manager position ID*. This column serves two fundamentally different purposes depending on stage. Queries that JOIN on `position_id` to find trades could accidentally join on signal linkage IDs. **Recommendation**: rename the linkage field to `parent_event_id` and add a separate `position_id` column (nullable, only populated at TRADED stage). This is a schema migration — should be done with a DB migration script.

2. **ISSUE — `record_validation_result()` inserts a new row without `signal_type` or `direction` (data gap)**
   The VALIDATED/REJECTED row does not carry `signal_type`, `direction`, or `grade` forward from the GENERATED row. Any query that filters `signal_events` on `stage = 'VALIDATED' AND direction = 'bull'` will return 0 rows. Analytics that aggregate by direction or grade must join back to the GENERATED row. **Recommendation**: pass `signal_type`, `direction`, and `grade` through to `record_validation_result()` and include them in the INSERT, or denormalize them from the GENERATED row at insert time.

3. **ISSUE — `session_signals` cache is not thread-safe**
   The `session_signals` dict is read and written from the main signal loop. If `signal_tracker` is ever called from multiple coroutines or threads (e.g., an async alert path alongside the sync scan loop), concurrent writes can corrupt the stage state machine. **Recommendation**: protect `session_signals` with a `threading.Lock` or use an `asyncio.Lock` if the pipeline is async-first.

4. **ISSUE — `get_hourly_funnel()` and `get_rejection_breakdown()` use `session_date >= cutoff` which includes today**
   When called from `get_daily_summary()` with `days=1`, the cutoff is yesterday's date, so today's data is included. This is correct for an EOD report. However, if called intraday (e.g., a mid-session Discord report), it returns partial-day data mixed with yesterday's, potentially misrepresenting rates. **Recommendation**: for intraday calls, filter to `session_date = today` only; reserve the rolling-N-day query for the EOD summary.

5. **OBSERVATION — `get_discord_eod_summary()` truncates rejection reasons to top 5**
   This is intentional for Discord message length limits. No issue.

6. **OBSERVATION — `_initialize_database()` creates 4 indexes including a composite `(session_date, hour_of_day, stage)` index that covers the hourly funnel query pattern. ✅ Good index design.**

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

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
