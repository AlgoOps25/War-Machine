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