# Batch 4: Validation Layer — COMPLETE

**Modules**
- app/validation/cfw6_confirmation.py
- app/validation/cfw6_gate_validator.py
- app/validation/entry_timing.py
- app/validation/hourly_gate.py
- app/validation/volume_profile.py

**Status: COMPLETE — 17 findings across 5 sub-sections.**

---

## Batch 4.A: cfw6_confirmation.py — CLOSED

**Findings**
1. (High) Dead wick_ratio zone [0.15, 0.25) silently rejects valid green bull/red bear candles.
2. (Critical) `wait_for_confirmation()` always tests latest bar only — skips valid mid-cycle confirmation candles.
3. (Medium) Blocks main thread up to 75 min — confirm single-ticker use or refactor.
4. (Low) Add grade assertion after `grade_signal_with_confirmations()` in sniper.py.
5. (Observation) 3× institutional volume threshold not per-ticker normalized — calibration improvement.

---

## Batch 4.B: cfw6_gate_validator.py — CLOSED

**Findings**
6. (High) Entire validator is dead code — `validate_signal = None` in scanner.py.
7. (Medium) Duplicate time-of-day and volume gates vs sniper.py — reconcile before enabling.
8. (Medium) ADX=None silently passes regime gate.
9. (Low) `get_validation_stats()` is a permanent stub — implement before re-enabling.

---

## Batch 4.C: entry_timing.py — CLOSED

**Findings**
10. (Critical) `HOURLY_WIN_RATES` is hardcoded fabricated data — replace with live DB query.
11. (Low) `get_timing_boost()` return scale undocumented (0–1 fraction vs 0–100 integer).
12. (Low) `SESSION_PERIODS` has 30-min overlap at 10:00–10:30 — close overlap.

---

## Batch 4.D: hourly_gate.py — CLOSED

**Findings**
13. (High) `build_heatmap_data()` permanent stub — hourly gate always neutral.
14. (Low) `_stats['neutral']` counter conflates off-hours and no-data — split counters.

---

## Batch 4.E: volume_profile.py — CLOSED

**Findings**
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
