# Batch 3: Core Pipeline Orchestration — COMPLETE

**Modules**
- app/core/sniper.py
- app/core/arm_signal.py
- app/core/armed_signal_store.py
- app/core/watch_signal_store.py
- app/core/analytics_integration.py
- app/core/thread_safe_state.py

**Status: COMPLETE — 18 findings across 3 sub-sections.**

---

## Batch 3.A: `_run_signal_pipeline()` — gate ordering and confidence math — CLOSED

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

## Batch 3.B: `process_ticker()` — scan flow, watch management, VWAP reclaim — CLOSED

**Findings (summary)**
9. (Medium) VWAP reclaim path has no time-of-day guard — can fire pre-9:45 or post-15:30.
10. (Medium) Watch datetime match fails on microsecond precision mismatch after restart.
11. (Low) Early session gate log message misleadingly says "OR < threshold" — should say "time-gated".
12. (Medium) `_bos_watch_alerted` not rebuilt from DB on restart — duplicate Discord alerts.
13. (Observation) `_orb_classifications` populated post-pipeline — purely cosmetic, confirms 3.A-1.

---

## Batch 3.C: `arm_signal.py` — arming sequence integrity — CLOSED

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
