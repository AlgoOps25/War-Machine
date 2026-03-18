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

### Batch 3: Core pipeline orchestration — COMPLETE

**Modules**
- app/core/sniper.py
- app/core/arm_signal.py
- app/core/armed_signal_store.py
- app/core/watch_signal_store.py
- app/core/analytics_integration.py
- app/core/thread_safe_state.py

**Status: COMPLETE — 18 findings. See sub-sections below.**

---

### Batch 3.A: `_run_signal_pipeline()` — gate ordering and confidence math — CLOSED

**Gate order confirmed**: DB cooldown → analytics cooldown → options gate → volume profile → confirmation → entry timing → order block → VWAP → MTF bias → grade → confidence construction → post-3pm decay → dynamic threshold → hourly gate → final confidence gate → arm_ticker().

**Findings (summary)**
1. (Critical) `adjust_signal_for_or()` CONFIRMED MISSING — OR quality filter fully bypassed.
2. (Critical) Analytics cooldown hard-blocks with `return False` — should be print-only.
3. (Medium) Greeks gate uses pre-confirmation entry price — should run post-confirmation.
4. (Medium) Volume profile blocks on empty data — needs `data_insufficient` flag to skip.
5. (Medium) MTF bias exception skips `record_stat()` — catch and record separately.
6. (High) `mode_decay=0.95` is the only OR adjustment applied — flat and width-unaware.
7. (High) `eff_min` has no upper cap — can exceed 0.95 causing ungatable threshold.
8. (Observation) INTRADAY_BOS `or_high_ref`/`or_low_ref` using BOS price is intentional.

---

### Batch 3.B: `process_ticker()` — scan flow, watch management, VWAP reclaim — CLOSED

**Findings (summary)**
9. (Medium) VWAP reclaim path has no time-of-day guard — can fire pre-9:45 or post-15:30.
10. (Medium) Watch datetime match fails on microsecond precision mismatch after restart.
11. (Low) Early session gate log message misleadingly says "OR < threshold" — should say "time-gated".
12. (Medium) `_bos_watch_alerted` not rebuilt from DB on restart — duplicate Discord alerts.
13. (Observation) `_orb_classifications` populated post-pipeline — purely cosmetic, confirms 3.A-1.

---

### Batch 3.C: `arm_signal.py` — arming sequence integrity — CLOSED

**Findings (summary)**
14. (High) `log_proposed_trade()` called before position open — logs trades that may never execute.
15. (Critical) `screener_integration` deferred import has no fallback — latent ImportError crash.
16. (Medium) ARMED stage may be missing when `record_trade_executed()` fires — add health-check.
17. (Observation) Watch cleanup correctly separated into `process_ticker()` — no issue.
18. (High) All arm_signal.py deferred imports lack try/except fallbacks present in sniper.py.

---

## Batch 3 Priority Fix List

| Priority | # | Module | Fix |
|----------|---|--------|-----|
| 🔴 Critical | 3.A-1 | sniper.py | Wire `adjust_signal_for_or()` into `_run_signal_pipeline()` — CONFIRMED MISSING |
| 🔴 Critical | 3.A-2 | sniper.py | Fix analytics cooldown block — change `return False` to print-only |
| 🔴 Critical | 3.C-15 | arm_signal.py | Wrap `screener_integration` import in try/except stub |
| 🟡 High | 3.A-7 | sniper.py | Cap `eff_min = min(eff_min, 0.92)` after hourly gate multiplication |
| 🟡 High | 3.B-9 | sniper.py | Add time-of-day guards to VWAP reclaim path (≥ 9:45, < 15:30) |
| 🟡 High | 3.C-14 | arm_signal.py | Move `log_proposed_trade()` to after `position_id > 0` check |
| 🟡 High | 3.C-18 | arm_signal.py | Wrap all deferred imports in try/except fallbacks |
| 🟠 Medium | 3.B-10 | sniper.py | Truncate both sides to second precision in watch datetime match |
| 🟠 Medium | 3.B-12 | sniper.py | Populate `_bos_watch_alerted` from DB-loaded watches at startup |
| 🟠 Medium | 3.A-4 | sniper.py | Run greeks check after confirmation using confirmed entry_price |
| 🟠 Medium | 3.A-5 | sniper.py | Add `data_insufficient` flag to volume profile validate_entry() |
| 🟠 Medium | 3.C-16 | sniper.py | Startup health-check: confirm signal_tracker not None + PHASE_4_ENABLED=True |
| 🟢 Low | 3.B-11 | sniper.py | Fix misleading early session gate log message |
| 🟢 Low | 3.A-5b | sniper.py | Call `mtf_bias_engine.record_stat()` even on exception path |

---

### Batch 4: Validation layer — COMPLETE

**Modules**
- app/validation/cfw6_confirmation.py
- app/validation/cfw6_gate_validator.py
- app/validation/entry_timing.py
- app/validation/hourly_gate.py
- app/validation/volume_profile.py

**Status: COMPLETE — 17 findings across 5 sub-sections. See sub-sections below.**

---

### Batch 4.A: cfw6_confirmation.py — CLOSED
1. (High) Dead wick_ratio zone [0.15, 0.25) silently rejects valid green bull/red bear candles.
2. (Critical) `wait_for_confirmation()` always tests latest bar only — skips valid mid-cycle confirmation candles.
3. (Medium) Blocks main thread up to 75 min — confirm single-ticker use or refactor.
4. (Low) Add grade assertion after `grade_signal_with_confirmations()` in sniper.py.
5. (Observation) 3× institutional volume threshold not per-ticker normalized — calibration improvement.

### Batch 4.B: cfw6_gate_validator.py — CLOSED
6. (High) Entire validator is dead code — `validate_signal = None` in scanner.py.
7. (Medium) Duplicate time-of-day and volume gates vs sniper.py — reconcile before enabling.
8. (Medium) ADX=None silently passes regime gate.
9. (Low) `get_validation_stats()` is a permanent stub — implement before re-enabling.

### Batch 4.C: entry_timing.py — CLOSED
10. (Critical) `HOURLY_WIN_RATES` is hardcoded fabricated data — replace with live DB query.
11. (Low) `get_timing_boost()` return scale undocumented (0–1 fraction vs 0–100 integer).
12. (Low) `SESSION_PERIODS` has 30-min overlap at 10:00–10:30 — close overlap.

### Batch 4.D: hourly_gate.py — CLOSED
13. (High) `build_heatmap_data()` permanent stub — hourly gate always neutral.
14. (Low) `_stats['neutral']` counter conflates off-hours and no-data — split counters.

### Batch 4.E: volume_profile.py — CLOSED
15. (Medium) LVN checked before HVN in `validate_breakout()` — swap order.
16. (Medium) Bar volume distributed at 3 discrete points (H/L/C) not across full range.
17. (Observation) Cache key rounding is fine for practical broker prices.

---

## Batch 4 Priority Fix List

| Priority | # | Module | Fix |
|----------|---|--------|-----|
| 🔴 Critical | 4.C-10 | entry_timing | Replace hardcoded `HOURLY_WIN_RATES` with live DB query from `signal_events` |
| 🔴 Critical | 4.A-2 | cfw6_confirmation | Fix `wait_for_confirmation()` to scan all new bars per cycle, not just the latest |
| 🟡 High | 4.A-1 | cfw6_confirmation | Close wick_ratio dead zone [0.15, 0.25) |
| 🟡 High | 4.D-13 | hourly_gate | Implement `build_heatmap_data()` from existing `signal_events` data |
| 🟡 High | 4.B-6 | cfw6_gate_validator | Decision: enable or formally defer `validate_signal()` |
| 🟠 Medium | 4.A-3 | cfw6_confirmation | Confirm single-ticker use or refactor to non-blocking confirmation |
| 🟠 Medium | 4.E-15 | volume_profile | Swap LVN/HVN check order in `validate_breakout()` |
| 🟠 Medium | 4.E-16 | volume_profile | Distribute bar volume across full price range bins |
| 🟠 Medium | 4.B-7 | cfw6_gate_validator | Reconcile duplicate gates before re-enabling |
| 🟠 Medium | 4.B-8 | cfw6_gate_validator | Require explicit `adx` or `regime_filter=False` — never silently pass |
| 🟠 Medium | 4.D-14 | hourly_gate | Split `_stats['neutral']` into `off_hours` + `no_data` counters |
| 🟢 Low | 4.C-12 | entry_timing | Close SESSION_PERIODS overlap: end `market_open` at 10:00 |
| 🟢 Low | 4.C-11 | entry_timing | Document `get_timing_boost()` return scale as 0–1 fraction |
| 🟢 Low | 4.A-4 | cfw6_confirmation | Add grade assertion in sniper.py after `grade_signal_with_confirmations()` |
| 🟢 Low | 4.B-9 | cfw6_gate_validator | Implement `get_validation_stats()` DB persistence before re-enabling |

---

### Batch 5: Filters layer — COMPLETE

**Modules**
- app/filters/vwap_gate.py
- app/filters/market_regime_context.py
- app/filters/mtf_bias.py
- app/filters/rth_filter.py
- app/filters/sd_zone_confluence.py
- app/filters/order_block_cache.py
- app/filters/liquidity_sweep.py
- app/filters/correlation.py
- app/filters/early_session_disqualifier.py
- app/filters/__init__.py

**Status: COMPLETE — 19 findings across 8 sub-sections.**

---

### Batch 5.A: vwap_gate.py — CLOSED

**Key invariants confirmed**
- Correct VWAP formula (H+L+C)/3. ✅
- `VWAP_GATE_ENABLED` toggle respected. ✅
- Unknown direction returns True (fail-open). ✅

**Findings**

1. **ISSUE — `passes_vwap_gate()` called with `bars_session[-1]["close"]` (last closed bar), not the confirmed entry price**
   After confirmation, the entry price may differ. Gate result is stale if price crosses VWAP during the confirmation window. **Fix**: re-evaluate `passes_vwap_gate()` post-confirmation using confirmed entry price.

2. **ISSUE — `compute_vwap()` 5-bar minimum is misleadingly low**
   VWAP on 5 session bars is not a meaningful anchored VWAP. **Fix**: raise minimum to 15 bars or document intent.

3. **OBSERVATION — `mtf_bias.py` defines an identical `_compute_vwap()` — duplicate implementation**
   **Fix**: `from app.filters.vwap_gate import compute_vwap` in mtf_bias.py; remove local copy.

---

### Batch 5.B: market_regime_context.py — CLOSED

**Key invariants confirmed**
- Regime never hard-blocks signals — `score_adj` is a passive confidence nudge only. ✅
- Exception path returns `UNKNOWN` with `score_adj=0` — fail-open. ✅

**Findings**

4. **OBSERVATION — `NEUTRAL_BEAR` label exists in `_combine()` output but never in `_score_instrument()` output** — documentation gap only, no logic error.

5. **ISSUE — `_get_slope_bull()` recomputes EMA twice** — `_score_instrument()` already computed EMA; `_get_slope_bull()` internally recomputes both `ema(bars)` and `ema(bars[:-1])`. **Fix**: compute `ema_prev` in `_score_instrument()` and pass it in.

6. **OBSERVATION — `import requests` inside try/except in `_fetch_eodhd_intraday()`** — safe-fail, observation only.

---

### Batch 5.C: mtf_bias.py — CLOSED

**Key invariants confirmed**
- Fail-open when disabled or bars insufficient. ✅
- `CONF_PENALTY` applied on `_fail()` path only. ✅

**Findings**

7. (Observation) `_detect_bos()` is a rolling momentum proxy, not structural SMC BOS — document as intentional.

8. **ISSUE — 15m BOS checked BEFORE 1H BOS — inverts top-down hierarchy**
   Per Nitro Trades methodology: 1H → 15m → 5m. If 15m is momentarily conflicted but 1H is aligned, signal is rejected. **Fix**: swap check order — evaluate 1H alignment first.

9. (Observation) `BOS_LOOKBACK = 8` — `last close > max(high of prior 8 bars)` — empirically chosen, document as momentum proxy.

10. **ISSUE — `evaluate()` silently skips 1H VWAP check when `current_price=0.0` (default)**
    An entire check layer is invisibly disabled if caller omits price. **Fix**: add explicit `if current_price <= 0: log warning` guard; make price a required positional argument.

11. **ISSUE — `_compute_vwap()` in mtf_bias.py duplicates `compute_vwap()` in vwap_gate.py** (reinforces 5.A-3).

---

### Batch 5.D: rth_filter.py — CLOSED

**Key invariants confirmed**
- Naive `dt` gets ET assigned, not rejected. ✅
- `get_window_label()` covers all segments. ✅

**Findings**

12. **ISSUE — `get_window_label()` labels exactly 16:00:00 as `close_chop` instead of `after_hours`**
    At 16:00, `t >= CLOSE_CHOP_START` (15:55) fires first. **Fix**: move `after_hours` check before `close_chop` in the if-chain.

13. **OBSERVATION — `is_rth()` has no chop blocking; `passes_rth_filter()` does** — callers must pick deliberately. Add docstring warning on `is_rth()`.

---

### Batch 5.E: sd_zone_confluence.py — CLOSED

**Findings**

14. **ISSUE — `identify_sd_zones()` requires only one opposing candle of any size** — a doji qualifies. **Fix**: add `prev_body_pct = _candle_body_pct(prev); if prev_body_pct < SD_MOMENTUM_MIN_PCT * 0.5: continue` guard.

15. **ISSUE — `_SD_CACHE` never cleared between sessions** — call `clear_sd_cache()` at EOD alongside OB cache.

---

### Batch 5.F: order_block_cache.py — CLOSED

**Findings**

16. **OBSERVATION — `body` variable returns dollars but used as fraction** — rename to `body_pct` for clarity.

17. **OBSERVATION — `ob["used"] = True` mutation is safe in single-threaded design** — add lock if multi-threading ever added.

---

### Batch 5.G: liquidity_sweep.py — CLOSED

**Findings**

18. **ISSUE (Critical) — Bull sweep `close_reclaim` allows close 0.10% BELOW the level**
    The check `(bar["close"] - level) / level >= -SWEEP_CLOSE_MAX_PCT` means close can still be below the level and qualify as a reclaim. **Fix**: change to strict `bar["close"] >= level`.

---

### Batch 5.H: correlation.py — CLOSED

**Findings**

19. **ISSUE — `confidence_adjustment` on −10 to +10 integer scale (0–100 basis); pipeline uses 0–1 float**
    Direct addition would shift confidence by 10 full units. **Fix**: divide by 100 before wiring: `adj = result["confidence_adjustment"] / 100.0`. Confirm whether called live.

---

## Batch 5 Priority Fix List

| Priority | # | Module | Fix |
|----------|---|--------|-----|
| 🔴 Critical | 5.G-18 | liquidity_sweep | Fix bull sweep close_reclaim — must be `close >= level`, not `close >= level −0.10%` |
| 🟡 High | 5.C-8 | mtf_bias | Swap 15m/1H BOS check order — 1H should be primary per top-down methodology |
| 🟡 High | 5.C-10 | mtf_bias | Add explicit guard + warning when `evaluate()` called with `current_price=0.0` |
| 🟡 High | 5.H-19 | correlation | Normalize confidence_adjustment by /100 before wiring; confirm if called live |
| 🟠 Medium | 5.A-1 | vwap_gate | Re-evaluate `passes_vwap_gate()` post-confirmation using confirmed entry price |
| 🟠 Medium | 5.C-11 | mtf_bias | Replace local `_compute_vwap()` with import from `vwap_gate.compute_vwap` |
| 🟠 Medium | 5.E-14 | sd_zone_confluence | Require minimum prior bar body before qualifying SD zone |
| 🟠 Medium | 5.E-15 | sd_zone_confluence | Call `clear_sd_cache()` at EOD alongside OB cache and session cache |
| 🟠 Medium | 5.D-12 | rth_filter | Fix `get_window_label()` — move `after_hours` check before `close_chop` check |
| 🟢 Low | 5.A-3 | vwap_gate | Consolidate duplicate VWAP implementations (vwap_gate + mtf_bias) |
| 🟢 Low | 5.A-2 | vwap_gate | Raise `compute_vwap()` minimum bars from 5 to 15 or document intent |
| 🟢 Low | 5.F-16 | order_block_cache | Rename `body` → `body_pct` in `identify_order_block()` for clarity |
| 🟢 Low | 5.D-13 | rth_filter | Add docstring warning on `is_rth()` re: no chop blocking |

---

### Batch 6: Indicators layer — COMPLETE

**Modules**
- app/indicators/technical_indicators.py
- app/indicators/technical_indicators_extended.py
- app/indicators/volume_indicators.py
- app/indicators/volume_profile.py
- app/indicators/vwap_calculator.py

**Status: COMPLETE — 17 findings across 5 sub-sections.**

---

### Batch 6.A: technical_indicators.py — CLOSED

**Current behaviour**
- EODHD API-backed indicators: ADX, BB, AVGVOL, CCI, DMI, MACD, SAR, STOCH, RSI, RSI Divergence, EMA.
- Adaptive TTL cache: 5min pre-market, 2min RTH, 10min after-hours.
- M6 fix: `_ensure_oldest_first()` defensive sort guard added for `check_rsi_divergence()` and `check_rvol()`.

**Key invariants confirmed**
- `_ensure_oldest_first()` sort guard correctly handles missing `datetime`/`date` keys — falls back gracefully. ✅
- TTL cache correctly segments by time-of-day using ET timezone. ✅
- Cache eviction on read (not deferred) — stale entries removed immediately on `get()`. ✅

**Findings**

1. **ISSUE — `_ensure_oldest_first()` falls back silently when no sortable key is present, returning the list in its original (unknown) order**
   If a bar dict has neither `datetime` nor `date`, the function returns the list as-is with no log warning. Any downstream index-based arithmetic on an unsorted list will silently produce wrong results. **Fix**: add `print(f"[INDICATORS] WARNING: bars have no sortable key — order not guaranteed")` on the fallback path so the problem is visible in logs.

2. **ISSUE — `IndicatorCache._get_ttl_seconds()` has no guard for DST transitions**
   The ET boundary checks use `dtime(9, 30)` etc. which are naive time comparisons. During the one-hour DST gap (clocks spring forward at 2:00 AM ET), `datetime.now(ET)` correctly handles the transition, but `dtime` comparisons do not account for the fact that 2:00–3:00 AM ET does not exist. In practice, the system is idle during that window, so there is no functional impact — but it is worth noting.
   **Recommendation**: observation only — no fix required. Document as a known safe edge case.

3. **ISSUE — `IndicatorCache.get_stats()` recomputes TTL for every entry by calling `_get_ttl_seconds()` once and comparing all entries against that single snapshot**
   This is correct and efficient — TTL is time-of-day based, not per-entry. ✅ However, `get_stats()` does not expose `expired_entries` count (total minus valid). **Minor**: add `'expired_entries': len(self.cache) - valid` to the returned dict for better observability.

4. **ISSUE — RSI divergence check (`check_rsi_divergence()`) requires a minimum number of bars for meaningful divergence, but the minimum bar guard (if any) is not visible in the truncated file**
   The M6 fix added `_ensure_oldest_first()` but the minimum bar count before divergence is declared valid is unknown from the visible code. If called with 2–3 bars, a spurious divergence signal could fire. **Action**: confirm that `check_rsi_divergence()` has a `len(bars) >= N` guard (recommend N ≥ 10) and add one if missing.

5. **ISSUE — The RVOL check (`check_rvol()`) compares today's cumulative volume vs the same-time-yesterday cumulative volume using index-based lookups on bars after `_ensure_oldest_first()` sort**
   If the prior day had a different number of intraday bars (holiday-shortened session, early close, WS reconnect gap), the index alignment is wrong — bar[i] today does not correspond to bar[i] yesterday. **Fix**: compare by matching on the `datetime.time()` component of each bar, not by index position, to guarantee same-time-of-day alignment.

---

### Batch 6.B: technical_indicators_extended.py — CLOSED

**Current behaviour**
- Wraps `fetch_technical_indicator()` for ATR, StochRSI, SLOPE, STDDEV.
- Analysis helpers: `get_atr_percentage()`, `calculate_atr_stop()`, `calculate_position_size()`, `validate_breakout_strength()`, `check_stochrsi_signal()`, `check_trend_slope()`, `check_volatility_regime()`, `check_volatility_expansion()`.

**Key invariants confirmed**
- `calculate_atr_stop()` correctly applies direction (LONG subtracts, SHORT adds). ✅
- `calculate_position_size()` guards against `stop_distance == 0` (returns 0). ✅
- `check_stochrsi_signal()` returns `None, None` on data absence — fail-open. ✅

**Findings**

6. **ISSUE — `calculate_position_size()` returns `max(1, shares)` — always returns at least 1 share even when ATR stop distance is enormous relative to account risk**
   If `risk_amount / stop_distance` computes to 0.001 (e.g., very wide ATR stop on a small account), `int(0.001) = 0` and the function returns 1 share anyway. For a $10 stock with a $50 ATR stop and $100 risk, this function would return 1 share — a position that violates the risk parameter. This is called a "forced entry" bug. **Fix**: instead of `max(1, shares)`, return `shares` and let the caller decide whether to skip the trade entirely when shares == 0.

7. **ISSUE — `validate_breakout_strength()` fetches ATR from EODHD (daily ATR by default) but `move_size` is an intraday dollar move**
   EODHD ATR (period=14) is a 14-day ATR based on daily bars. An intraday move of $0.50 on a stock with a 14-day daily ATR of $3.00 will always fail the `>= 1.5 ATR` check, making `validate_breakout_strength()` permanently too strict for intraday breakouts. **Fix**: either (a) fetch intraday ATR (e.g., 14-bar ATR from 5m bars computed locally), or (b) scale the threshold: `min_atr_multiple=0.15` for intraday use (roughly 1/10th of daily ATR), or (c) document that this function is daily-timeframe only and should not be called for intraday signals.

8. **ISSUE — `check_volatility_regime()` calls `data_manager.get_bars_from_memory(ticker, limit=1)` inside a try/except that silently returns `None, None` on any exception**
   If `data_manager` is not yet initialized (startup race), `AttributeError` is swallowed and the regime is unknown. Since the caller in the signal pipeline treats `None` as fail-open (no volatility filter applied), this is safe. But it means volatility filtering is silently bypassed at startup. **Fix**: add `except AttributeError as e: print(f"[INDICATORS] data_manager not ready: {e}")` to distinguish startup from genuine data absence.

9. **ISSUE — `check_volatility_expansion()` computes "average STDDEV over last 10 bars" using `stddev_data[:10]` — oldest 10 bars after EODHD returns newest-first**
   EODHD API returns data newest-first. If `_ensure_oldest_first()` is NOT called on `stddev_data` before `[:10]`, the slice is the 10 most-recent bars (which may be the correct intent). But `get_latest_value()` uses `stddev_data[-1]` (the last element), which is the OLDEST bar if newest-first. This creates a contradiction: `current_stddev` is the oldest bar's value, `recent_stddevs` is the 10 newest. **Fix**: call `_ensure_oldest_first(stddev_data)` before all slicing in `check_volatility_expansion()`, then use `stddev_data[-1]` for current (newest) and `stddev_data[-11:-1]` for the 10 prior bars.

---

### Batch 6.C: volume_indicators.py — CLOSED

**Current behaviour**
- Local (non-API) calculations: VWAP, MFI, OBV, confluence scoring, signal validation.
- All computed from raw OHLCV bars passed in by the caller.

**Key invariants confirmed**
- `calculate_vwap()` returns `bars[-1]['close']` when `total_volume == 0` — safe fallback. ✅
- `calculate_mfi()` returns 50.0 (neutral) when insufficient bars. ✅
- `calculate_obv()` starts cumulative sum at 0. ✅

**Findings**

10. **ISSUE — `calculate_mfi()` computes positive/negative flow over `range(len(typical_prices) - period, len(typical_prices))` but starts the loop at `i=1` only if `i < 1: continue`**
    The guard `if i < 1: continue` is only relevant when `len(typical_prices) - period == 0`, i.e., exactly `period` bars. In all normal cases (more bars than period), the loop range starts at a value ≥ 1 and the guard never fires. This is harmless but dead code. More importantly: the positive/negative flow calculation does not use the first bar's money flow at all (comparing `typical_prices[i] vs [i-1]` requires `i >= 1`). This is correct RSI-style flow calculation. ✅ Minor: remove the dead `if i < 1: continue` guard.

11. **ISSUE — `calculate_obv_trend()` uses `obv_values[-lookback:]` then compares first-half vs second-half averages with a 5% threshold**
    The 5% threshold (`change_pct > 5` = bullish, `< -5` = bearish) is applied to the percentage change between OBV halves. OBV is a cumulative sum of volume — its absolute value depends entirely on the session's volume scale. A 5% change in OBV for a high-float stock (millions of shares) is trivially easy to achieve, while for a low-float stock it may be impossible. The threshold is not normalized to share count or average daily volume. **Fix**: normalize by computing the change as a fraction of the most recent OBV's absolute value: `change_pct = (second_half_avg - first_half_avg) / max(abs(first_half_avg), 1) * 100`. Also document that "5% OBV slope" is the criterion.

12. **ISSUE — `check_indicator_confluence()` uses `mfi_bullish = 20 <= mfi <= 80` for BOTH bull AND bear confluence checks**
    For a bullish confluence check, MFI between 20–80 is interpreted as "not overbought — still room to run." For a bearish confluence check, MFI between 20–80 is interpreted as "not oversold — still room to fall." Both checks use the same MFI neutral zone. This means MFI almost always confirms regardless of direction (MFI is within 20–80 ~90% of the time). The MFI signal adds very little discriminatory power to the confluence score. **Fix**: for bull confluence, MFI should ideally be rising (compare current vs N-bars-ago) or in the 40–70 zone (momentum building, not exhausted). For bear confluence, MFI should be falling or in the 30–60 zone. At minimum, document that the current MFI gate is intentionally lenient.

13. **ISSUE — `validate_signal_with_volume_indicators()` defaults all three `require_*` flags to `False`**
    With all flags False, this function always returns `(True, details)` regardless of VWAP, MFI, or OBV values. The function is effectively a no-op unless the caller explicitly passes `require_vwap_confirm=True` etc. If the call site in the pipeline uses the default params, volume validation is bypassed entirely. **Fix**: audit all call sites to confirm at least one `require_*` flag is set to `True`, or change the defaults to `True` for the most critical check (recommend `require_vwap_confirm=True` as default since VWAP is the most reliable of the three).

---

### Batch 6.D: volume_profile.py (indicators layer) — CLOSED

**Current behaviour**
- `VolumeProfile` class: POC, VAH, VAL, HVN, LVN from intraday OHLCV bars.
- 50 price bins, 70% value area, 1.5× HVN threshold.
- 5-minute TTL cache keyed by ticker.
- Note: this is the `app/indicators/volume_profile.py` — distinct from `app/validation/volume_profile.py` audited in Batch 4.E.

**Key invariants confirmed**
- Cache eviction on read by age comparison. ✅
- `_find_value_area()` expands toward the higher-volume side at each step. ✅
- `calculate_profile()` requires ≥ 3 bars. ✅
- HVN list capped at top 10; LVN list capped at bottom 10. ✅

**Findings**

14. **ISSUE — `_distribute_volume()` distributes bar volume evenly across ALL price levels that fall within the bar's high-low range**
    This is the same finding as Batch 4.E-16 applied to the `app/indicators` copy. Volume is split equally across price levels within each bar's range. This overstates volume at the extremes (bars that span wide ranges spread volume thinly and uniformly). A more accurate approach weights levels by proximity to the close or uses a triangular distribution peaked at the close. **Note**: both `app/validation/volume_profile.py` and `app/indicators/volume_profile.py` have this same implementation — they are effectively duplicates. **Fix (structural)**: consolidate into one canonical `VolumeProfile` class, imported by both the validation and indicator layers.

15. **ISSUE — `_find_poc()` returns the first maximum when multiple price levels share the same volume**
    `max(..., key=lambda x: x[1])` on a dict's `.items()` returns the first item with the maximum value in dict insertion order. If two price levels have identical volume (common with small bar counts), the POC is arbitrarily the lower-indexed bin. **Fix**: when ties exist, return the price level closest to the weighted average close price, or log a warning that POC is ambiguous.

16. **ISSUE — `check_poc_breakout()` and `check_value_area_breakout()` are binary (price > POC = True) with no tolerance band**
    A stock trading at $100.01 above a POC of $100.00 returns True — a 1-cent "breakout." This creates false positives during price consolidation directly at the POC. **Fix**: add a minimum distance parameter: `return price > poc * (1 + min_pct)` where `min_pct` defaults to 0.002 (0.2% minimum breakout distance above POC).

---

### Batch 6.E: vwap_calculator.py — CLOSED

**Current behaviour**
- `VWAPCalculator`: volume-weighted VWAP + 1σ/2σ/3σ standard deviation bands.
- Session-level cache keyed by ticker + bar count.
- Mean reversion signals at 2σ/3σ bands.
- Global singleton `vwap_calculator` with convenience functions.

**Key invariants confirmed**
- Volume-weighted variance formula (not simple variance) — correct for VWAP bands. ✅
- Band keys use integer σ labels (`upper_1sd`, `upper_2sd`, `upper_3sd`). ✅
- `get_vwap_cached()` invalidates on bar count change — ensures recalc when new bars arrive. ✅
- Mean reversion signal checks 3σ before 2σ — correct priority order. ✅

**Findings**

17. **ISSUE — `get_mean_reversion_signal()` computes `stop` for the SELL signal as `vwap_data['upper_3sd'] * 1.005` (hardcoded key access) without a `.get()` guard**
    If `vwap_data` was computed with a non-default `num_std_devs` list that does not include 3.0, `vwap_data['upper_3sd']` raises a `KeyError`. The global singleton is always initialized with `[1.0, 2.0, 3.0]` so in practice this is safe. But if a caller ever creates a `VWAPCalculator([1.0, 2.0])` (no 3σ) and calls `get_mean_reversion_signal()`, it will crash. **Fix**: use `vwap_data.get('upper_3sd', vwap_data.get('upper_2sd', current_price))` as a safe fallback, or assert `3.0 in self.num_std_devs` in `__init__`.

    **Additionally**: `vwap_calculator.py` defines its own VWAP calculation (`calculate_vwap()`) which uses volume-weighted variance for the std dev bands. `volume_indicators.py` defines `calculate_vwap()` which uses simple (H+L+C)/3 × volume sum. `vwap_gate.py` defines `compute_vwap()` with the same formula. **This is the third independent VWAP implementation in the codebase.** All three exist simultaneously and may produce slightly different results depending on which one the caller uses. **Fix**: designate `vwap_calculator.py`'s `VWAPCalculator.calculate_vwap()` as the canonical implementation (it is the most complete — includes std dev bands). Import from it in `vwap_gate.py` and `volume_indicators.py`. Remove the duplicates.

---

## Batch 6 Priority Fix List

| Priority | # | Module | Fix |
|----------|---|--------|-----|
| 🔴 Critical | 6.B-9 | technical_indicators_extended | Fix `check_volatility_expansion()` — call `_ensure_oldest_first()` before slicing; `current_stddev` must be newest bar |
| 🔴 Critical | 6.B-7 | technical_indicators_extended | `validate_breakout_strength()` uses daily ATR vs intraday move — scale threshold or switch to intraday ATR |
| 🟡 High | 6.A-5 | technical_indicators | Fix `check_rvol()` same-time alignment — match by `datetime.time()` component, not array index |
| 🟡 High | 6.C-13 | volume_indicators | Audit all `validate_signal_with_volume_indicators()` call sites — confirm at least one `require_*` flag is True |
| 🟡 High | 6.D-14 | volume_profile (indicators) | Consolidate `app/indicators/volume_profile.py` + `app/validation/volume_profile.py` into one canonical class |
| 🟡 High | 6.E-17b | vwap_calculator | Consolidate 3 duplicate VWAP implementations — designate `VWAPCalculator.calculate_vwap()` as canonical |
| 🟠 Medium | 6.B-6 | technical_indicators_extended | Remove `max(1, shares)` forced-entry floor — return 0 and let caller skip trade |
| 🟠 Medium | 6.C-11 | volume_indicators | Normalize OBV trend threshold — use fraction of absolute OBV, not raw 5% |
| 🟠 Medium | 6.C-12 | volume_indicators | Tighten MFI confluence gate — directional MFI zone or rising/falling MFI, not static 20–80 band |
| 🟠 Medium | 6.D-16 | volume_profile (indicators) | Add minimum breakout distance to `check_poc_breakout()` and `check_value_area_breakout()` |
| 🟠 Medium | 6.A-4 | technical_indicators | Confirm `check_rsi_divergence()` has ≥10 bar minimum guard; add if missing |
| 🟠 Medium | 6.B-8 | technical_indicators_extended | Distinguish `AttributeError` (data_manager not ready) from genuine data absence in `check_volatility_regime()` |
| 🟢 Low | 6.A-1 | technical_indicators | Add log warning in `_ensure_oldest_first()` fallback path (no sortable key) |
| 🟢 Low | 6.A-3 | technical_indicators | Add `'expired_entries'` to `IndicatorCache.get_stats()` return dict |
| 🟢 Low | 6.C-10 | volume_indicators | Remove dead `if i < 1: continue` guard in `calculate_mfi()` |
| 🟢 Low | 6.D-15 | volume_profile (indicators) | Break POC ties by proximity to weighted average close, not dict insertion order |
| 🟢 Low | 6.E-17a | vwap_calculator | Use `.get()` fallback on `upper_3sd`/`lower_3sd` in `get_mean_reversion_signal()` |

---

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
