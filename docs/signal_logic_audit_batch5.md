# Batch 5: Filters Layer — COMPLETE

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

## Batch 5.A: vwap_gate.py — CLOSED

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

## Batch 5.B: market_regime_context.py — CLOSED

**Key invariants confirmed**
- Regime never hard-blocks signals — `score_adj` is a passive confidence nudge only. ✅
- Exception path returns `UNKNOWN` with `score_adj=0` — fail-open. ✅

**Findings**

4. **OBSERVATION — `NEUTRAL_BEAR` label exists in `_combine()` output but never in `_score_instrument()` output** — documentation gap only, no logic error.

5. **ISSUE — `_get_slope_bull()` recomputes EMA twice** — `_score_instrument()` already computed EMA; `_get_slope_bull()` internally recomputes both `ema(bars)` and `ema(bars[:-1])`. **Fix**: compute `ema_prev` in `_score_instrument()` and pass it in.

6. **OBSERVATION — `import requests` inside try/except in `_fetch_eodhd_intraday()`** — safe-fail, observation only.

---

## Batch 5.C: mtf_bias.py — CLOSED

**Key invariants confirmed**
- Fail-open when disabled or bars insufficient. ✅
- `CONF_PENALTY` applied on `_fail()` path only. ✅

**Findings**

7. (Observation) `_detect_bos()` is a rolling momentum proxy, not structural SMC BOS — document as intentional.

8. **ISSUE — 15m BOS checked BEFORE 1H BOS — inverts top-down hierarchy**
   Per Nitro Trades methodology: 1H → 15m → 5m. **Fix**: swap check order — evaluate 1H alignment first.

9. (Observation) `BOS_LOOKBACK = 8` — empirically chosen, document as momentum proxy.

10. **ISSUE — `evaluate()` silently skips 1H VWAP check when `current_price=0.0` (default)**
    **Fix**: add explicit `if current_price <= 0: log warning` guard; make price a required positional argument.

11. **ISSUE — `_compute_vwap()` in mtf_bias.py duplicates `compute_vwap()` in vwap_gate.py** (reinforces 5.A-3).

---

## Batch 5.D: rth_filter.py — CLOSED

**Key invariants confirmed**
- Naive `dt` gets ET assigned, not rejected. ✅
- `get_window_label()` covers all segments. ✅

**Findings**

12. **ISSUE — `get_window_label()` labels exactly 16:00:00 as `close_chop` instead of `after_hours`**
    **Fix**: move `after_hours` check before `close_chop` in the if-chain.

13. **OBSERVATION — `is_rth()` has no chop blocking; `passes_rth_filter()` does** — add docstring warning on `is_rth()`.

---

## Batch 5.E: sd_zone_confluence.py — CLOSED

**Findings**

14. **ISSUE — `identify_sd_zones()` requires only one opposing candle of any size** — a doji qualifies. **Fix**: add minimum prior bar body guard.

15. **ISSUE — `_SD_CACHE` never cleared between sessions** — call `clear_sd_cache()` at EOD alongside OB cache.

---

## Batch 5.F: order_block_cache.py — CLOSED

**Findings**

16. **OBSERVATION — `body` variable returns dollars but used as fraction** — rename to `body_pct` for clarity.

17. **OBSERVATION — `ob["used"] = True` mutation is safe in single-threaded design** — add lock if multi-threading ever added.

---

## Batch 5.G: liquidity_sweep.py — CLOSED

**Findings**

18. **ISSUE (Critical) — Bull sweep `close_reclaim` allows close 0.10% BELOW the level**
    The check `(bar["close"] - level) / level >= -SWEEP_CLOSE_MAX_PCT` means close can still be below the level and qualify as a reclaim. **Fix**: change to strict `bar["close"] >= level`.

---

## Batch 5.H: correlation.py — CLOSED

**Findings**

19. **ISSUE — `confidence_adjustment` on −10 to +10 integer scale (0–100 basis); pipeline uses 0–1 float**
    **Fix**: divide by 100 before wiring: `adj = result["confidence_adjustment"] / 100.0`. Confirm whether called live.

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
