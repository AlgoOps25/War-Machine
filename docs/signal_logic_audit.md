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

### Batch 4: Validation layer — IN PROGRESS

**Modules**
- app/validation/cfw6_confirmation.py
- app/validation/cfw6_gate_validator.py
- app/validation/entry_timing.py
- app/validation/hourly_gate.py
- app/validation/volume_profile.py
- app/validation/validation.py (65KB — main SignalValidator)

**Objectives**
- Confirm CFW6 candle confirmation logic is mathematically symmetric and covers all candle patterns.
- Confirm `wait_for_confirmation()` cannot block the pipeline indefinitely.
- Confirm `cfw6_gate_validator.validate_signal()` is actually called in the live pipeline (or is it dead code?).
- Confirm `EntryTimingValidator` win rates are based on live data vs hardcoded stubs.
- Confirm `hourly_gate.build_heatmap_data()` is implemented or confirmed as a permanent neutral stub.
- Confirm `VolumeProfileAnalyzer` handles empty bar sets without blocking (ties back to 3.A-5).
- Audit `validation.py` (SignalValidator) — largest file in the layer at 65KB.

---

### Batch 4.A: cfw6_confirmation.py — candle confirmation and grade logic

**Current behaviour (summary)**
- `analyze_confirmation_candle()` implements 3-tier CFW6 candle type logic (TYPE 1/A+, TYPE 2/A, TYPE 3/A-) for both bull and bear.
- Zone entry check: bull requires `low` in zone; bear requires `high` in zone.
- `wait_for_confirmation()` loops up to `max_wait_candles` (default 15 = 75 minutes), re-fetching bars each cycle, sleeping 60s between cycles.
- `grade_signal_with_confirmations()` applies 3 confirmation layers (VWAP, PDH/PDL, institutional volume) and upgrades/downgrades grade based on 3/3 or 0/3 alignment.
- VWAP calculation fixed Mar 16 2026 to use correct (H+L+C)/3 formula from `app.filters.vwap_gate`.

**Key invariants**
- `analyze_confirmation_candle()` must return `("reject", "reject")` if the candle does not touch the zone. ✅
- `wait_for_confirmation()` must eventually time out after `max_wait_candles` cycles regardless of data availability. ✅
- `grade_signal_with_confirmations()` must only upgrade/downgrade by exactly one grade level. ✅ (A→A+ for 3/3, A+→A for 0/3)

**Findings**

1. **ISSUE — `analyze_confirmation_candle()` has a dead candle pattern gap between TYPE 2 and TYPE 3 for bull direction (logic gap)**
   For a bull candle that is GREEN (`close > open`), the code checks:
   - `wick_ratio < 0.15` → TYPE 1 (A+)
   - `wick_ratio >= 0.25` → TYPE 2 (A)
   - But wick_ratio in [0.15, 0.25) → **falls through to `return ("reject", "reject")`** — no pattern matched.
   This is a dead zone: a green candle with a 15–24% lower wick has a respectable bullish pattern but is classified as a reject. The same gap exists on the bear side for red candles with upper wick in [0.15, 0.25).
   **Fix**: change the `>= 0.25` TYPE 2 check to `>= 0.15` (i.e., close the gap with TYPE 1), OR add an explicit catch-all: if `close > open` (bull, green) and wick_ratio is in [0.15, 0.25), return TYPE 2 ("flip", "A") as a borderline flip. The current code silently rejects valid confirmation candles in a 10-point wick_ratio window.

2. **ISSUE — `wait_for_confirmation()` always uses the LAST bar after `start_time`, not the LATEST UNTESTED bar (logic error)**
   The loop iterates all bars and updates `latest_bar` on every bar with `bar_dt > start_time`. This means `latest_bar` is always the newest bar, not the bar that was most recently completed and not yet evaluated. If the pipeline fires on bar N+3 but bar N+1 was the actual confirmation candle, it is silently skipped — only bar N+3 (the latest) is tested each cycle. **Fix**: track the last-evaluated bar index across cycles (e.g., store `last_checked_idx` and only evaluate bars with idx > last_checked_idx). This ensures every new bar gets a chance to be the confirmation candle.

3. **ISSUE — `wait_for_confirmation()` calls `time.sleep(60)` which blocks the main thread for up to 75 minutes (architectural)**
   The confirmation loop is a blocking synchronous sleep loop. If `sniper.py` calls `wait_for_confirmation()` from the main scan loop (confirmed: it does, via `_run_signal_pipeline()` step 5 when `skip_cfw6_confirmation=False`), the entire bot is frozen for up to 75 minutes per confirmation wait. No other tickers are scanned during this window. This is architecturally acceptable only if War Machine is single-stock-focused; it is a serious problem for multi-ticker scans.
   **Recommendation**: either (a) confirm that the live pipeline uses `skip_cfw6_confirmation=True` for all multi-ticker scans and `wait_for_confirmation()` is only used in manual/single-ticker mode, or (b) refactor to async/non-blocking confirmation checks (e.g., mark ticker as "pending confirmation" in state, check on the next scan cycle).

4. **ISSUE — `grade_signal_with_confirmations()` never downgrades below "A-" — a 0/3 signal with base grade "A-" gets final_grade = "reject" but the function still returns a dict (not None)**
   The caller in `sniper.py` receives `result["final_grade"] == "reject"` and must check for this. Searching `_run_signal_pipeline()`: after `grade_signal_with_confirmations()` returns, the code checks `if confirm_result["final_grade"] == "reject": return False`. ✅ Correctly handled. However, if the check is ever removed or the key name changes, the reject will silently propagate as an armed signal with grade="reject". **Recommendation**: add an assertion `assert confirm_result["final_grade"] in VALID_GRADES` after the call.

5. **OBSERVATION — `check_institutional_volume()` uses a hard 3× threshold (avg_volume × 3) with no per-ticker normalization**
   For high-float mega-caps like AAPL or MSFT, institutional block trades regularly exceed 3× average volume without being directionally meaningful. For low-float small-caps, 3× is a very weak signal. The threshold is not parameterized. No immediate fix required — mark as a calibration improvement for backtesting.

---

### Batch 4.B: cfw6_gate_validator.py — gate validator pipeline

**Current behaviour (summary)**
- Six sequential gates: time-of-day (hard) → regime/ADX (hard, RVOL bypass at 3.0×) → volume (soft, -5 pts) → greeks (soft, -10 pts) → ML adjustment (±15 pts) → min confidence floor (60%).
- `validate_signal = None` in scanner.py currently disables this validator — it is **not active** in the live pipeline.
- `get_validation_stats()` is a permanent stub returning zeroed counters.

**Key invariants**
- Gates 1 and 2 are hard-exit (early `return`). All others are soft (adjust confidence). ✅
- ML gate is safe-fail: `is_ready=False` → zero adjustment. ✅
- `adjusted_confidence` is clamped to [0, 100] after ML adjustment. ✅

**Findings**

6. **ISSUE — `cfw6_gate_validator.validate_signal()` is CONFIRMED DISABLED in scanner.py (dead code in live pipeline)**
   The docstring explicitly states: `"validate_signal = None" in scanner.py — re-enable by removing that line once the CFW6 gate is ready"`. This means the entire 6-gate validation pipeline (time-of-day hard-reject, regime, volume, greeks, ML, confidence floor) is bypassed. This is a deliberate deferral, not a bug, but it means the `cfw6_gate_validator` module provides zero signal filtering currently.
   **Decision required**: confirm whether this gate should be enabled in production. If yes, remove the `validate_signal = None` override in scanner.py and wire the result into `_run_signal_pipeline()`.

7. **ISSUE — Gate 1 time-of-day and Gate 3 volume in `cfw6_gate_validator` DUPLICATE checks already in `_run_signal_pipeline()` and `sniper.py` (redundancy)**
   If this gate is ever re-enabled, it will apply time-of-day and volume checks that overlap with:
   - `_check_time_of_day()` vs. the lunch/afternoon windows already enforced in `process_ticker()` (via `is_active_session()` and the direct time checks in the scan loop).
   - `_check_volume()` RVOL floor vs. the RVOL tier already enforced by the screener watchlist funnel.
   The overlapping gates are not harmful (defense-in-depth) but the hard-reject windows differ: `cfw6_gate_validator` rejects 11:30–13:00 lunch; `sniper.py` does not have this exact window. These need to be reconciled before enabling.

8. **ISSUE — Gate 2 regime uses `adx=None` → passes with "no ADX data" (trivially bypassed)**
   If the caller doesn't pass `adx`, the regime gate always returns `passed=True`. Since scanner.py calls `validate_signal()` without an `adx` parameter (in the stub), ADX would never be checked. **Fix**: require either `adx` or explicit `regime_filter=False` — never silently pass.

9. **ISSUE — `get_validation_stats()` is a permanent stub — no gate telemetry is ever recorded**
   Gate pass/fail counts are never persisted. When this validator goes live, there will be zero visibility into which gates fire most often. **Fix**: before enabling in production, implement DB persistence for gate stats (the TODO comment references PostgreSQL).

---

### Batch 4.C: entry_timing.py — hourly win rate validator

**Current behaviour (summary)**
- `EntryTimingValidator` classifies signal entry times against `HOURLY_WIN_RATES`, a hardcoded dict of `{hour: (win_rate, sample_size)}`.
- Weak hour (< 50% WR): blocks signal unless grade is A+.
- Golden hour (≥ 65% WR): always allows.
- `get_timing_boost()` returns a ±0–5% confidence adjustment based on WR distance from threshold.

**Key invariants**
- `validate_entry_time()` must always return `(True, ...)` if no hour data exists (fail-open). ✅
- Timezone coercion to ET must happen before hour extraction. ✅

**Findings**

10. **ISSUE — `HOURLY_WIN_RATES` is HARDCODED with fabricated sample data — not derived from live trade history (critical data integrity)**
    The values `{9: (0.58, 45), 10: (0.68, 52), 11: (0.62, 38), 12: (0.45, 28), ...}` are static constants embedded in the class definition. They are not loaded from the DB, not updated daily, and the `sample_size` values (45, 52, 38 etc.) are fictional. This means `EntryTimingValidator` applies filtering rules based on made-up win rates. If the bot is in its first 3 months of trading, these rates could be wildly wrong for your actual strategy. The `hourly_gate.py` module has the right design (queries `session_heatmap`) but `entry_timing.py` completely bypasses it.
    **Fix**: replace `HOURLY_WIN_RATES` with a DB query at initialization time, using the same `build_heatmap_data()` pattern from `hourly_gate.py`. Until sufficient history exists (< `MIN_TRADES_HOUR`), default to neutral (fail-open). The hardcoded values should be removed entirely.

11. **ISSUE — `get_timing_boost()` returns a float in [−0.05, +0.05] but the calling convention in `_run_signal_pipeline()` treats confidence as a 0–1 float**
    `get_timing_boost()` returns e.g. `0.03` meaning +3%. If the caller adds this to `final_confidence` (which is a 0–1 float like `0.72`), the adjustment is correct. However, `cfw6_gate_validator` uses confidence on a 0–100 scale. If `get_timing_boost()` is ever called from the gate validator context and the result is added directly, it applies a 0.03-point adjustment on a 0–100 scale — effectively zero. **Recommendation**: explicitly document the return scale as a 0–1 fraction, or rename to `get_timing_boost_fraction()` for clarity.

12. **ISSUE — `SESSION_PERIODS` overlap: `market_open` is 9:30–10:30 and `golden_hours` is 10:00–11:30 — 30 minutes of overlap**
    `_get_session_quality()` iterates the dict and returns the FIRST match. Dict insertion order in Python 3.7+ is guaranteed, so `market_open` always wins for the 10:00–10:30 overlap window. The 10:00–10:30 period is actually classified as `market_open` not `golden_hours`, even though it has the highest win rate. This affects only the session_quality label in `timing_data` (used for logging/Discord) — not the actual gate decision. **Fix**: close the overlap: change `market_open` to end at `time(10, 0)`, making the ranges contiguous.

---

### Batch 4.D: hourly_gate.py — dynamic confidence threshold modifier

**Current behaviour (summary)**
- `get_hourly_confidence_multiplier()` queries `build_heatmap_data()` once per trading day (cached).
- Returns 1.10 (weak), 0.95 (strong), or 1.00 (neutral/no data).
- `build_heatmap_data()` is a **permanent stub** returning `{"hour_totals": {}}` — always neutral.

**Key invariants**
- Cache must refresh on date change, not on arbitrary TTL. ✅ (checks `_last_update.date() != now.date()`)
- Outside 9–15 ET must always return 1.0. ✅
- No data (insufficient history) must return 1.0 (neutral). ✅

**Findings**

13. **ISSUE — `build_heatmap_data()` is a permanent stub — `hourly_gate` always returns 1.0 (neutral) for every signal**
    The function returns `{"hour_totals": {}}` unconditionally. This means the hourly gate never raises or lowers the confidence threshold. It is a no-op. This is explicitly noted in the docstring ("Hourly gate will run neutral until this is populated") but there is no TODO ticket, no schema for `session_heatmap`, and no timeline to implement it. Combined with finding 4.C-10 (hardcoded win rates in entry_timing.py), the entire time-of-day performance calibration layer is effectively non-functional.
    **Fix**: implement `build_heatmap_data()` to query `signal_events` grouped by `hour_of_day` and `session_date` (the data already exists from `signal_analytics.py`). This requires no new schema — just a SQL query against existing data.

14. **ISSUE — `_stats['neutral']` counter is incremented both when hour is outside 9–15 AND when hour has insufficient data, making it impossible to distinguish "off-hours" from "data too thin"**
    Both cases increment `_stats['neutral']` and `print_hourly_gate_stats()` reports them together as a single "Neutral" bucket. **Fix**: add a separate counter `_stats['off_hours']` for the `hour < 9 or hour > 15` early return path.

---

### Batch 4.E: volume_profile.py — entry-gate volume profile validator

**Current behaviour (summary)**
- `VolumeProfileAnalyzer.validate_entry()` builds a 20-bin session profile and checks if entry is near HVN (block) or LVN (favor), above VAH (bull), or below VAL (bear).
- Results cached 5 minutes per `(ticker, direction, entry_price)`.
- Correctly returns `(True, "Volume profile unavailable...", None)` when `len(bars) < 10` — fail-open for insufficient data. ✅ This directly resolves finding 3.A-5 from Batch 3.

**Key invariants**
- Empty profile must return `(True, ...)` not `(False, ...)`. ✅ (`_empty_profile()` returns total_volume=0 → caught by `validate_entry()`)
- HVN/LVN checks use relative 1% tolerance (`abs(price - level) / price < 0.01`). ✅
- POC distance calculation guards against `poc == 0`. ✅

**Findings**

15. **ISSUE — `validate_breakout()` checks LVN *before* HVN — a price near both an HVN and an LVN simultaneously returns True (LVN wins)**
    If a price bin happens to be both in the top-80th-percentile (HVN) AND bottom-20th-percentile (LVN) volume — which can't happen mathematically since those are mutually exclusive percentiles — this isn't a real issue. However, the LVN list can contain a bin that is *near* an HVN bin (adjacent bins), and the 1% price tolerance could match both. If the entry price is within 1% of an LVN AND within 1% of an HVN, the code returns True (favorable) because LVN is checked first. **Fix**: check HVN first (blocking check), then LVN (confirming check), so HVN always wins if both are nearby.

16. **ISSUE — `analyze_session_profile()` distributes each bar's volume equally across H, L, and C points (volume/3 each) — this under-weights the close price**
    The standard TPO/volume profile convention is to use the bar's range as a uniform distribution across all price bins within [low, high], not just 3 discrete points. The current approach creates a "jagged" profile with spikes at H, L, and C and gaps between them. For 20 bins this is a minor distortion, but it means the POC can be pinned to a high/low extreme rather than the true highest-volume price range. **Recommendation**: distribute `bar['volume']` proportionally across all bins within `[bar['low'], bar['high']]` using `np.searchsorted` range allocation. This is the 3-line fix that makes the profile mathematically correct.

17. **OBSERVATION — Cache key uses `entry_price:.2f` which may round differently for prices like $99.995**
    For practical entry prices (2 decimal places from broker), this is fine. No issue.

---

## Batch 4 Priority Fix List

| Priority | # | Module | Fix |
|----------|---|--------|-----|
| 🔴 Critical | 4.C-10 | entry_timing | Replace hardcoded `HOURLY_WIN_RATES` with live DB query from `signal_events`; remove fabricated sample data |
| 🔴 Critical | 4.A-2 | cfw6_confirmation | Fix `wait_for_confirmation()` to scan all new bars per cycle, not just the latest |
| 🟡 High | 4.A-1 | cfw6_confirmation | Close wick_ratio dead zone [0.15, 0.25) — green bull candles in this range silently rejected |
| 🟡 High | 4.D-13 | hourly_gate | Implement `build_heatmap_data()` using existing `signal_events` data — hourly gate is permanently neutral until done |
| 🟡 High | 4.B-6 | cfw6_gate_validator | Decision point: enable or formally defer `validate_signal()` — currently 100% dead code in live pipeline |
| 🟠 Medium | 4.A-3 | cfw6_confirmation | Architectural: `wait_for_confirmation()` blocks main thread up to 75 min — confirm single-ticker use or refactor to non-blocking |
| 🟠 Medium | 4.E-15 | volume_profile | Swap LVN/HVN check order in `validate_breakout()` — HVN (blocking) must be checked before LVN (confirming) |
| 🟠 Medium | 4.E-16 | volume_profile | Distribute bar volume across price range bins (not just H/L/C points) for mathematically correct profile |
| 🟠 Medium | 4.B-7 | cfw6_gate_validator | Reconcile duplicate time-of-day and volume gates with existing pipeline checks before re-enabling |
| 🟠 Medium | 4.B-8 | cfw6_gate_validator | Require explicit `adx` or `regime_filter=False` — don't silently pass on missing ADX |
| 🟠 Medium | 4.D-14 | hourly_gate | Split `_stats['neutral']` into `off_hours` + `no_data` counters |
| 🟢 Low | 4.C-12 | entry_timing | Close `SESSION_PERIODS` overlap: end `market_open` at 10:00, not 10:30 |
| 🟢 Low | 4.C-11 | entry_timing | Document `get_timing_boost()` return scale as 0–1 fraction or rename for clarity |
| 🟢 Low | 4.A-4 | cfw6_confirmation | Add `assert final_grade in VALID_GRADES` after `grade_signal_with_confirmations()` call in sniper.py |
| 🟢 Low | 4.B-9 | cfw6_gate_validator | Implement `get_validation_stats()` DB persistence before re-enabling gate |

---

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
