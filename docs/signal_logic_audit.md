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

**Current behaviour**
- `compute_vwap()` uses correct (H+L+C)/3 typical price formula. ✅
- `passes_vwap_gate()` hard-rejects bull below VWAP, bear above VWAP.
- Fails open (`return True`) when `vwap == 0.0` (< 5 bars or zero volume). ✅

**Key invariants confirmed**
- Correct VWAP formula (H+L+C)/3. ✅
- `VWAP_GATE_ENABLED` toggle respected. ✅
- Unknown direction returns True (fail-open). ✅

**Findings**

1. **ISSUE — `passes_vwap_gate()` uses `current_price` as a parameter, but in `_run_signal_pipeline()` it is called with `bars_session[-1]["close"]` (the last closed bar close), not the confirmed entry price**
   This mirrors finding 3.A-3 (greeks gate uses pre-confirmation price). The VWAP gate fires against the last closed bar price. After confirmation, the entry price may be different. If the confirmed entry price crosses VWAP during the confirmation window, the gate result is stale. **Fix**: after confirmation is complete, re-evaluate `passes_vwap_gate()` using the confirmed entry price before proceeding to the grade step. Or accept this as an approximation — in practice, price rarely crosses VWAP between a BOS signal bar and confirmation.

2. **ISSUE — `compute_vwap()` has a 5-bar minimum but `passes_vwap_gate()` only gets bars from `bars_session` which may be all intraday bars (hundreds) causing minor performance overhead**
   `bars_session` passed to `passes_vwap_gate()` from `_run_signal_pipeline()` is the full session bar list. `compute_vwap()` iterates all of them every call. For 390 1-minute bars this is ~1ms — acceptable. However, the 5-bar minimum check (`len(bars) < 5`) is misleadingly low: VWAP on 5 bars of a session is not a meaningful session VWAP. **Recommendation**: raise minimum to 15 bars, or document that session VWAP is intentionally a full-session anchored VWAP.

3. **OBSERVATION — `mtf_bias.py` defines its own `_compute_vwap()` function that duplicates `vwap_gate.compute_vwap()` exactly**
   Two identical VWAP implementations in the same codebase (same formula, same guard). **Fix**: have `mtf_bias.py` import and call `compute_vwap` from `vwap_gate` instead. One canonical implementation.

---

### Batch 5.B: market_regime_context.py — CLOSED

**Current behaviour**
- SPY + QQQ EMA 9/21/50 on 5m bars; combined conviction label + passive `score_adj` only (no hard blocks).
- 3-tier bar fallback: WS memory → DB session bars → EODHD REST.
- 90s TTL cache; Discord posts rate-limited to 5 min.

**Key invariants confirmed**
- Regime never hard-blocks signals — `score_adj` is a passive confidence nudge only. ✅
- Exception path returns `UNKNOWN` with `score_adj=0` — fail-open. ✅
- `_last_discord_post` prevents Discord spam. ✅

**Findings**

4. **ISSUE — `_score_instrument()` has a missing label for `NEUTRAL_BEAR` — the combined label can be `NEUTRAL_BEAR` but the per-instrument `_score_instrument()` never produces it**
   `_score_instrument()` returns labels: STRONG_BULL, BULL, NEUTRAL_BULL, STRONG_BEAR, BEAR, NEUTRAL, UNKNOWN. There is no `NEUTRAL_BEAR` in the per-instrument output. The `_combine()` function CAN return `NEUTRAL_BEAR` (when avg ≤ -1). If a caller ever tries to reverse-engineer the individual instrument labels from the combined label, they will never see NEUTRAL_BEAR at the instrument level. This is a minor documentation gap, not a logic error — the combined label is what matters. No fix required, but add a docstring note.

5. **ISSUE — `_get_slope_bull()` recomputes `_compute_ema(bars[:-1], period)` from scratch every call, doubling the EMA computation cost**
   `_score_instrument()` calls `_compute_ema(bars, 50)` for the EMA value, then `_get_slope_bull(bars, 50)` which internally calls both `_compute_ema(bars, period)` AND `_compute_ema(bars[:-1], period)`. The first call is therefore computed twice. For 390-bar lists this is O(n·p) duplicated work. **Fix**: compute `ema50_prev = _compute_ema(bars[:-1], 50)` directly in `_score_instrument()` and pass it as a parameter to `_get_slope_bull()`, or inline the slope check.

6. **ISSUE — EODHD REST fallback in `_fetch_eodhd_intraday()` imports `requests` inside the function at call time, which will fail silently if `requests` is not installed**
   The import `import requests` is inside a try/except block, so an `ImportError` here is caught and returns `[]`. This is safe-fail. However, if `requests` IS installed but the API key is missing (`api_key == ""`), the function returns `[]` before the import — consistent. The only issue is that `requests` is also imported inside `send_regime_discord()` in the same way. Both work fine but the pattern of importing inside try/except is a code smell. **Observation only** — no change required for correctness.

7. **ISSUE — `_combine()` averages SPY and QQQ scores equally, but when one instrument is UNKNOWN, it substitutes 0 for its score**
   If SPY is STRONG_BULL (+15) and QQQ is UNKNOWN (0 substituted), the combined avg = 7.5, producing label BULL (+8). This is correct behavior — partial data yields a reduced but valid signal. ✅ However, the reason string says `"SPY=STRONG_BULL QQQ=UNKNOWN"` which accurately communicates the partial data situation. No issue.

---

### Batch 5.C: mtf_bias.py — CLOSED

**Current behaviour**
- 3-layer check: 1H BOS direction match → 15m BOS direction match → 1H VWAP directional alignment.
- Fully aligned (1H + 15m): +0.08 confidence boost.
- 15m conflict: hard REJECT with −0.10 penalty.
- 1H conflict: hard REJECT with −0.10 penalty.
- 1H VWAP conflict: hard REJECT with −0.10 penalty.

**Key invariants confirmed**
- Fail-open when disabled or bars insufficient. ✅
- CONF_PENALTY applied on `_fail()` path only. ✅
- `_db_ready` guards all DB operations. ✅

**Findings**

8. **ISSUE — 15m BOS is checked BEFORE 1H BOS, meaning a 15m conflict rejects before the 1H alignment is even evaluated (asymmetric priority)**
   The check order is:
   1. `if aligned_15m is False: return _fail(...)` — 15m conflict hard-rejects first
   2. `if aligned_1h is False: return _fail(...)` — 1H conflict hard-rejects second
   The Nitro Trades top-down methodology is 1H → 15m → 5m, meaning 1H should be the primary filter. If 1H is fully aligned but 15m is momentarily conflicted, the signal is rejected regardless of 1H context. This inverts the top-down hierarchy. **Fix**: swap the check order: evaluate 1H alignment first, then 15m.

9. **ISSUE — `_detect_bos()` uses `bars[-(BOS_LOOKBACK+1):-1]` for the lookback window and `bars[-1]["close"]` as the current bar — this is correct BUT the lookback bars are also closed bars, not a reference to a "break" event**
   `BOS_LOOKBACK = 8` means: last close > max(high of prior 8 bars) = bull BOS. This is a rolling breakout detection, not a structural BOS (which would require identifying a swing high/low and then a break of that level). For the 1H and 15m timeframes, this is a simplified momentum proxy. The `# Backtest-optimized` comment suggests this was chosen empirically, which is valid. No fix required — document that this is a momentum-based BOS proxy, not a structural SMC BOS.

10. **ISSUE — `evaluate()` receives `current_price=0.0` as default, meaning the 1H VWAP directional check is silently skipped if the caller doesn't pass price**
    The 1H VWAP check: `if has_1h and vwap_1h and current_price:` — if `current_price=0.0`, the condition is `False` and VWAP alignment is never checked. The caller in `_run_signal_pipeline()` must explicitly pass `current_price`. If it doesn't (or passes 0.0), an entire check layer is silently disabled. **Fix**: use `current_price: float = 0.0` with an explicit `if current_price > 0:` guard AND add an assertion or log warning when called with price=0 to make the skip visible.

11. **ISSUE — `_compute_vwap()` in mtf_bias.py is a direct duplicate of `compute_vwap()` in vwap_gate.py (reinforces finding 5.A-3)**
    Identical logic. One canonical source. **Fix**: `from app.filters.vwap_gate import compute_vwap` and remove local `_compute_vwap()`.

---

### Batch 5.D: rth_filter.py — CLOSED

**Current behaviour**
- `is_rth()`: simple 9:30–16:00 ET gate, no chop windows.
- `RTHFilter`: configurable policy with open chop (9:30–9:35), lunch (12:00–13:30), close chop (15:55–16:00).
- Default singleton: `block_open_chop=True`, `block_lunch=False`, `block_close_chop=True`.

**Key invariants confirmed**
- Naive `dt` (no tzinfo) gets ET assigned, not rejected. ✅
- `get_window_label()` covers all time segments without gaps. ✅ (checked: pre_market, open_chop, morning, lunch, afternoon, close_chop, after_hours — all contiguous)
- Self-test at module bottom covers 8 edge cases. ✅

**Findings**

12. **ISSUE — `get_window_label()` has a gap: after-hours check (`t >= MARKET_CLOSE`) is placed AFTER `t >= CLOSE_CHOP_START` in the if-chain, but `MARKET_CLOSE` is 16:00 and `CLOSE_CHOP_START` is 15:55 — at exactly 16:00, both conditions are True**
    At 16:00:00 ET: `t >= CLOSE_CHOP_START` (15:55) is True, so the function returns `'close_chop'` instead of `'after_hours'`. This is a minor labeling bug — at 16:00 the session is closed, not in chop. The gate itself (`passes()`) correctly uses `MARKET_OPEN <= t < MARKET_CLOSE` which excludes 16:00. **Fix**: move the `after_hours` check before the `CLOSE_CHOP_START` check in `get_window_label()`.

13. **OBSERVATION — `is_rth()` and `passes_rth_filter()` exist as separate entry points with different semantics (no chop blocking vs chop blocked) — callers must pick the right one**
    The hot-path scanner uses `is_rth()` (no chop blocking). If a caller mistakenly uses `is_rth()` when they want chop-blocked behavior, they will allow open chop and close chop signals. **Recommendation**: add a docstring note on `is_rth()` explicitly warning: "Does NOT block open/close chop. Use `passes_rth_filter()` for chop-blocked behavior."

---

### Batch 5.E: sd_zone_confluence.py — CLOSED

**Current behaviour**
- `identify_sd_zones()` scans last 50 bars for strong impulse candles preceded by opposing color — keeps top 5 by body strength.
- `check_sd_confluence()` checks entry price against demand (bull) or supply (bear) zones with ±0.20% buffer.
- Boost: +3% confidence on match, capped at 0.95. ✅

**Key invariants confirmed**
- Direction filtering: demand only for bull, supply only for bear. ✅
- Cache cleared per ticker or globally. ✅

**Findings**

14. **ISSUE — `identify_sd_zones()` requires ONLY the immediately prior bar to be opposing color — no minimum prior move size**
    A single opposing candle of any size triggers zone identification, even if it's a doji with 0.01% body. The `SD_MOMENTUM_MIN_PCT` threshold applies to the CURRENT (impulse) candle body, not the prior move. This means a tiny red bar followed by a large green bar qualifies as a demand zone, even without a meaningful prior down-move. For a true SMC supply/demand zone, the prior move should be at least equal in magnitude to the impulse candle. **Fix**: add a `prev_body = _candle_body_pct(prev); if prev_body < SD_MOMENTUM_MIN_PCT * 0.5: continue` guard to require a minimum prior bar body before qualifying the zone.

15. **ISSUE — `_SD_CACHE` is in-memory only and never cleared between sessions — stale zones from prior days may persist**
    The `_SD_CACHE` dict is module-level. It is never cleared automatically. On a Railway restart between sessions, it starts empty (fine). But during a long-running session, zones identified from pre-market bars persist alongside intraday zones. If `cache_sd_zones()` is called repeatedly for the same ticker (every scan cycle), old zones are overwritten (fine). But if a ticker falls off the watchlist mid-session and `clear_sd_cache()` is never called for it, its zones persist until restart. **Fix**: call `clear_sd_cache()` at EOD in the same place as `clear_ob_cache()` and `clear_session_cache()`.

---

### Batch 5.F: order_block_cache.py — CLOSED

**Current behaviour**
- `identify_order_block()` finds the last opposing candle before a BOS (up to 10 bars back) as the OB.
- Zone: OB body ±0.15% buffer. Boost: +3% capped at 0.95. ✅
- `ob["used"] = True` marks OB as consumed to prevent double-boosting. ✅
- In-memory only; resets on restart. ✅ (consistent with intended session-scoped behavior)

**Key invariants confirmed**
- OB direction must match signal direction. ✅
- Minimum body size (0.10%) required. ✅
- Max 5 OBs per ticker. ✅

**Findings**

16. **ISSUE — `OB_BODY_MIN_PCT` uses `body / bar["close"]` for the size check, but `body` is an absolute dollar amount (not a percentage)**
    `_candle_body()` returns `abs(close - open)` in dollars. The guard is `body / bar["close"] < OB_BODY_MIN_PCT`. At a price of $100, a $0.10 body = 0.10% — passes the 0.10% threshold exactly. At a price of $10, a $0.01 body = 0.10% — also barely passes. The math is correct (it's actually a relative percentage check). However, the variable name `body` returning dollars and being used as a fraction without an explicit comment makes this code confusing. **Recommendation**: rename to `body_pct = _candle_body(bar) / bar["close"]` for clarity.

17. **ISSUE — `OB_CACHE` is a module-level global dict, but `check_ob_retest()` mutates `ob["used"] = True` in-place on the cached dict object**
    This is intentional — the `used` flag prevents double-boosting. However, since it mutates in-place, if two coroutines/threads call `check_ob_retest()` for the same ticker simultaneously, both could see `used=False` and both apply the boost. In the current single-threaded scanner design this is safe. **Note**: if multi-threading is ever added, this needs a lock around the `ob["used"]` check-and-set.

---

### Batch 5.G: liquidity_sweep.py — CLOSED

**Current behaviour**
- Scans last 6 bars for a sweep (wick breach + close reclaim) of OR high/low or VWAP.
- Bull sweep: low breaches level by ≥0.15%, close reclaims to within 0.10% of level.
- Bear sweep: symmetric.
- Boost: +4% confidence, capped at 0.95. ✅

**Key invariants confirmed**
- Fails open (returns None) with < 3 bars. ✅
- Level filtering: bull sweeps OR_LOW + VWAP only; bear sweeps OR_HIGH + VWAP only. ✅

**Findings**

18. **ISSUE — `_candle_swept_level()` for bull sweep checks `close_reclaim = (bar["close"] - level) / level >= -SWEEP_CLOSE_MAX_PCT` — this allows close BELOW the level by up to 0.10%**
    The intent of a bull sweep is: price wicks below a level but CLOSES BACK ABOVE it. The `close_reclaim` condition `>= -0.001` means the close can be up to 0.10% BELOW the level and still qualify as a "reclaim". This allows sweep confirmation on bars that never actually reclaimed the level. **Fix**: the bull close_reclaim check should be `bar["close"] >= level` (strict reclaim above level), not `(bar["close"] - level) / level >= -SWEEP_CLOSE_MAX_PCT`.

---

### Batch 5.H: correlation.py — CLOSED

**Current behaviour**
- `check_spy_correlation()` computes Pearson correlation between ticker and SPY returns over last 20 bars.
- High (>0.7): -5 adj; Low (<0.3) with divergence: +10 adj; Low without divergence: +5 adj; Moderate: 0.
- `get_divergence_score()` returns a 0–100 score.
- **Not actively wired into `_run_signal_pipeline()` — the `confidence_adjustment` is returned but the caller must apply it manually.**

**Key invariants**
- NaN correlation (flat price) handled → 0.0. ✅
- Returns neutral dict on all exception paths. ✅

**Findings**

19. **ISSUE — `check_spy_correlation()` returns `confidence_adjustment` on a -10 to +10 integer scale, but `_run_signal_pipeline()` uses confidence as a 0–1 float — scale mismatch if ever wired in (design issue)**
    The +10/-5/+5 integer adjustments from `correlation.py` are percentage points (0–100 scale). If added directly to `final_confidence` (0.72, etc.), they would shift confidence by 10 full units — far beyond the 0.95 cap. This means `correlation.py` was designed with `cfw6_gate_validator`'s 0–100 confidence scale in mind, not `_run_signal_pipeline()`'s 0–1 scale. **Fix**: before wiring, normalize the adjustments by dividing by 100: `adj_fraction = result["confidence_adjustment"] / 100.0`. Also confirm whether `correlation.py` is currently called anywhere in the live pipeline or is unused.

---

## Batch 5 Priority Fix List

| Priority | # | Module | Fix |
|----------|---|--------|-----|
| 🔴 Critical | 5.G-18 | liquidity_sweep | Fix bull sweep close_reclaim check — must be `close >= level`, not `close >= level −0.10%` |
| 🟡 High | 5.C-8 | mtf_bias | Swap 15m/1H BOS check order — 1H should be primary per top-down methodology |
| 🟡 High | 5.C-10 | mtf_bias | Add explicit guard + warning when `evaluate()` called with `current_price=0.0` |
| 🟡 High | 5.H-19 | correlation | Normalize confidence_adjustment by /100 before wiring into pipeline (scale mismatch); confirm if called live |
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

_This file will be updated continuously as we work through each batch so it stays in sync with the current understanding and decisions from the audit._
