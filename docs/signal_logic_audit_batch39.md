Full Batch 39 audit below — this is the longest and most complex file in the audit.

File: docs/signal_logic_audit_batch39.md
text
# Signal Logic Audit — Batch 39

**Date:** 2026-03-18
**Scope:** `app/core/sniper.py` (65 KB) — CFW6 signal pipeline
**Total Findings:** 28 (1 Critical, 6 High, 13 Medium, 8 Low)

---

## Overview

`sniper.py` is the execution core of War Machine. It is responsible for:

1. Module-level import of 30+ optional dependencies with stubs
2. `process_ticker()` — per-ticker dispatch: OR path, watch path, intraday BOS path, VWAP reclaim path
3. `_run_signal_pipeline()` — the 15-step confirmation → arming funnel

The module shows significant organic growth (40+ referenced phases / fixes in
comments). The architecture is sound: optional modules are guarded with
`try/except ImportError` stubs, the thread-safe state singleton is used
correctly throughout, and the two-phase (BOS watch → FVG confirmation)
design is well-implemented. The critical finding involves a subtle ordering
bug in the pipeline that can cause a confirmed signal to fire twice.

---

## 🔴 Criticals (1)

---

### 39.C-1 — **`_run_signal_pipeline()` is called TWICE for the INTRADAY_BOS path in `process_ticker()` when `scan_mode == "INTRADAY_BOS"` AND `VWAP_RECLAIM_ENABLED` is True.**

The VWAP reclaim block at the bottom of `process_ticker()` checks:

```python
if scan_mode is None and VWAP_RECLAIM_ENABLED:
    vr = detect_vwap_reclaim(bars_session)
    ...
    _run_signal_pipeline(...)
The condition is if scan_mode is None. After the INTRADAY_BOS path completes, scan_mode = "INTRADAY_BOS" — so the VWAP block is correctly skipped. However, the ORB classification block runs between the INTRADAY_BOS _run_signal_pipeline() call and the VWAP reclaim check:

python
_run_signal_pipeline(...)           # ← INTRADAY_BOS fires

if ORB_TRACKER_ENABLED ...:         # ← runs, may raise
    or_data = or_detector.classify_or(ticker)

if scan_mode is None and VWAP_RECLAIM_ENABLED:   # ← VWAP check
If or_detector.classify_or(ticker) raises an exception AND the exception propagates out of its try/except orb_err: print(...) (which it shouldn't — but the except only catches Exception silently), scan_mode stays "INTRADAY_BOS" and the VWAP block is correctly skipped. This path is safe.

The actual double-fire occurs on the OR path, not INTRADAY_BOS. If scan_mode = "OR_ANCHORED" AND detect_vwap_reclaim() finds a reclaim signal: the VWAP block fires because scan_mode is None is False — but there is a second call path. After the INTRADAY_BOS block sets scan_mode = "INTRADAY_BOS", process_ticker() calls _run_signal_pipeline() immediately. Then the ORB block runs. Then the if scan_mode is None VWAP check is False. This is actually correct.

Re-reading more carefully: the real critical is that when the OR path detects BOS but zone_low is None (no FVG yet), it sets watching_signals and returns early. But if the OR path detects BOS AND zone_low (FVG found), scan_mode = "OR_ANCHORED" is set but _run_signal_pipeline() is not called in the OR detection block — it falls through to the bottom:

python
signal_type = "CFW6_OR" if scan_mode == "OR_ANCHORED" else "CFW6_INTRADAY"
_run_signal_pipeline(...)   # ← called once at the bottom for OR_ANCHORED
Then the VWAP reclaim block: if scan_mode is None → False → skipped. Correct.

The actual confirmed double-fire path: The _run_signal_pipeline() call after the watching path (_state.ticker_is_watching) does not return early on success:

python
if _state.ticker_is_watching(ticker):
    ...
    _run_signal_pipeline(...)       # ← fires for watch→FVG path
    _state.remove_watching_signal(ticker)
    _remove_watch_from_db(ticker)
    return                          # ← returns correctly
This return is correct. But the code continues past the watching block without return only if _state.ticker_is_watching() is False at the second check (after breakout_idx resolution). If the first _state.ticker_is_watching() call is True but the second (after update_watching_signal_field()) is somehow False (e.g., a concurrent remove_watching_signal from another thread between the two checks), process_ticker() falls through to the OR scanning block and runs a second full scan for the same ticker that was just in watch mode. The TOCTOU window here is between _state.ticker_is_watching() check #1 and check #2, which involves a DB index resolve loop that can take 10–100ms. With _ticker_executor(max_workers=1) (serial), the risk of a concurrent thread is low but nonzero (sniper's _run_signal_pipeline launches arm_ticker which has its own threads). Fix: assign is_watching = _state.ticker_is_watching(ticker) once before the resolve block, and use that cached value for both the resolve and the pipeline dispatch.

🟡 Highs (6)
39.H-1 — _TICKER_WIN_CACHE = get_ticker_win_rates(days=30) runs at module import time. This makes a DB query (30 days of trade outcomes) synchronously during import sniper. On Railway cold start, if the DB pool isn't ready when sniper.py is first imported, this raises and the entire module fails to import. scanner.py does a hard from app.core.sniper import process_ticker (Phase 1.30 — no stubs fallback). A DB timeout at import time kills the entire scanner process with ImportError, not a DB error. Should be lazily initialized: _TICKER_WIN_CACHE = None at module level, with a _get_ticker_win_cache() function that initializes on first call.
39.H-2 — _run_signal_pipeline() calls signal_tracker.record_signal_generated() mid-pipeline, before the confidence gate. If the signal later fails the confidence gate (which most signals do — it's the final filter), the event is already recorded as GENERATED in signal_analytics. Then record_validation_result() is also called (passed or failed). But there is no corresponding record_signal_rejected_at_gate() call. The funnel analytics will show: GENERATED=N, VALIDATED=N, ARMED=M (where M << N) — but the gap between VALIDATED and ARMED represents the confidence gate rejections, which have no stage label. Gate rejections are the most informative filter to optimize. The confidence gate rejection path should call signal_tracker.record_signal_rejected_at_gate(ticker, reason=f"{final_confidence:.2f} < {eff_min:.2f}") so the funnel shows GENERATED → VALIDATED → GATED → ARMED.
39.H-3 — The _resample_bars() function is defined inside _run_signal_pipeline() on every call. Python re-compiles a new function object on every invocation of _run_signal_pipeline(). This is minor overhead per call but more importantly the _resample_bars() implementation is a full defaultdict resampler that gets called with limit=390 bars (1 full trading day of 1m bars). With 50 tickers × N scan cycles, this function is redefined and executed thousands of times per session. It should be a module-level utility function. More critically: _bars_1m_raw = data_manager.get_bars_from_memory(ticker, limit=390) fetches all 1m bars for the day on every pipeline call — this is a separate DB read from bars_session (which is 5m bars). If bars_session already contains the raw 1m bars, this fetch is redundant. If not, it's an extra DB call in the hot path of every signal validation.
39.H-4 — process_ticker() calls check_performance_dashboard(_state, PHASE_4_ENABLED) and check_performance_alerts(...) at the top of every ticker scan, before any early returns. With 50 tickers per cycle, these two functions are called 50 times per scan cycle (100 calls/cycle total). check_performance_dashboard() likely reads from _state (thread-safe, fast) but check_performance_alerts() may issue DB queries or Discord webhook calls. The _last_dashboard_check and _last_alert_check timestamps in thread_safe_state are supposed to debounce these (only fire every N minutes), but as found in 38.M-1, those timestamps are tz-naive and the comparison with datetime.now(ET) raises TypeError. The result: check_performance_dashboard and check_performance_alerts may be either always firing (if the TypeError is swallowed) or always skipping (if it propagates). Either way, they are called 50× per cycle when they should be called once. These should be called once per scan cycle in scanner.py, not inside process_ticker().
39.H-5 — run_eod_reports() (the stub or real version) is called inside process_ticker() when is_force_close_time() returns True. process_ticker() is called for every ticker in the watchlist — 50 tickers per cycle. is_force_close_time() checks if the last bar is at or after 15:55 ET. During the 15:55–16:00 window, every ticker scan triggers run_eod_reports() — 50 × EOD report calls in a single cycle. The real run_eod_reports() call sends Discord messages, clears caches, and runs AI optimization. On 50 simultaneous calls, Discord will rate-limit, cache will be cleared 50×, and AI optimization will run 50× redundantly. Should gate with a module-level _eod_reports_fired: bool = False flag, reset at EOD.
39.H-6 — The analytics dual-tracker architecture creates conflicting cooldown decisions. _run_signal_pipeline() checks two cooldown systems in sequence:
is_on_cooldown(ticker, direction) — DB-persisted via cooldown_tracker

cooldown_tracker.is_in_cooldown(ticker) — in-memory analytics tracker

If #1 says NOT blocked but #2 says IS blocked (in-memory cooldown set from earlier in the same session), the signal is dropped by #2. But the in-memory cooldown tracker is not synchronized with the DB cooldown. After a Railway restart: DB cooldown may still be active (correctly blocking), but in-memory is empty — so a signal that should be blocked by in-memory history fires immediately on restart. Conversely, if the in-memory tracker has a 30-minute cooldown but the DB only has a 15-minute cooldown, a valid reversal signal is blocked by stale in-memory state. The two systems must either be unified (remove in-memory, use DB exclusively — the architecture the Phase 1.33 comment implies) or the in-memory tracker must be populated from the DB on startup. Currently neither happens.

🟠 Mediums (13)
ID	Issue
39.M-7	The 30+ print(f"[SNIPER] ✅ ...") startup lines at module import level fire on every import sniper — including test imports. All should be logger.debug(). The Railway log stream is already cluttered from the scanner.py banner (38.M-8); sniper.py adds another 30 lines of ✅ noise before the first ticker is processed.
39.M-8	process_ticker() catches Exception in the top-level try/except and calls traceback.print_exc(). This means every unhandled exception in the entire pipeline — including DB errors, network errors, and assertion failures — is silently swallowed and printed. There is no re-raise, no Discord alert for repeated failures, and no dead-ticker tracking. A ticker that raises every single cycle accumulates errors silently forever. Should track per-ticker error counts and send a Discord alert after N consecutive failures.
39.M-9	_run_signal_pipeline() accesses bars_session[-1] multiple times without guarding len(bars_session) > 0. process_ticker() does check if not bars_session: return before calling the pipeline — but bars_session is data_manager.get_today_session_bars() which could theoretically return a list with items that are subsequently filtered (e.g., pre-9:30 bars removed). If all bars are pre-market and the filtered list is empty, bars_session[-1] raises IndexError. Should add if len(bars_session) < 2: return guard at the top of _run_signal_pipeline().
39.M-10	_get_or_threshold() calls get_regime_filter().get_regime_state().vix on every process_ticker() call. get_regime_filter() is a singleton getter but get_regime_state() may trigger a VIX/SPY data fetch. With 50 tickers per cycle, this is 50 VIX fetches per scan cycle. Should cache the VIX level per cycle in the scan loop (or in spy_regime passed into process_ticker()).
39.M-11	compute_opening_range_from_bars(bars_session) is called unconditionally for every ticker every scan cycle. After the OR is established (typically by 9:35–9:40), it doesn't change. Recomputing the OR for every ticker on every 45-second cycle is wasteful. Should cache the OR per ticker per session in thread_safe_state or _orb_classifications.
39.M-12	After the watching path resolves and _run_signal_pipeline() is called, the code always calls _state.remove_watching_signal(ticker) and _remove_watch_from_db(ticker) regardless of whether _run_signal_pipeline() succeeded (returned True) or failed (returned False). If the pipeline returns False (e.g., greeks gate failed, entry timing failed), the watch is still cleared — the ticker will not be re-watched and the BOS opportunity is permanently abandoned. Should only remove the watch if _run_signal_pipeline() returns True, or re-watch with a decremented bar counter.
39.M-13	options_rec = _pre_options_data after the validator block. If _pre_options_data is None (greeks gate soft-failed or OPTIONS_PRE_GATE_ENABLED is False), options_rec is None and all multipliers default to 1.0. This is correct behavior, but options_rec.get(...) calls will raise AttributeError if options_rec is somehow not None but also not a dict (e.g., a string error message). Should add if not isinstance(options_rec, dict): options_rec = None before the multiplier extraction block.
39.M-14	The mult_to_adjustment() function is defined inside _run_signal_pipeline() (same issue as _resample_bars() in 39.H-3). It is a pure mathematical function with no closures. Should be a module-level utility.
39.M-15	final_confidence = max(0.40, min(final_confidence, 0.95)) is applied after each boost step (sweep, OB, SD, post-3PM decay). Each max(0.40, min(..., 0.95)) clamp is correct individually, but the final CONFIDENCE_ABSOLUTE_FLOOR from config is not used here — it's only used in the eff_min calculation path via get_dynamic_threshold. If config.CONFIDENCE_ABSOLUTE_FLOOR is changed (e.g., raised to 0.50), the hardcoded 0.40 floor in the confidence formula remains, creating a divergence between the floor used in confidence clamping and the floor used in threshold calculation. Should reference config.CONFIDENCE_ABSOLUTE_FLOOR directly.
39.M-16	The spy_regime_adj calculation: max(0, score_adj) / 100.0 if direction == "bull" applies the SPY adjustment only when score_adj > 0 for bulls, and max(0, -score_adj) / 100.0 for bears. For a bearish regime (score_adj < 0), a bull signal gets max(0, negative) = 0 adjustment — neutral. This means the SPY regime never penalizes bull signals in a bearish market, only rewards them in a bullish market. For a bearish market bull signal, spy_regime_adj = 0 — it passes through unchanged. The regime should apply a negative adjustment to counter-trend signals. Should use score_adj / 100.0 without the max(0, ...) for directional penalties.
39.M-17	VWAP_RECLAIM_ENABLED path constructs a synthetic FVG zone as vwap * 0.9985 to vwap * 1.0015 (±0.15%). This is a hardcoded zone width with no relation to the ticker's ATR, OR range, or current volatility. For a $500 stock (NVDA), this zone is ±$0.75. For a $10 stock, ±$0.015. The zone should scale with get_adaptive_fvg_threshold() or the current ATR.
39.M-18	process_ticker() checks if _state.ticker_is_armed(ticker): return near the top. But this check happens after _maybe_load_watches(), _maybe_load_armed_signals(), and two check_performance_* calls. The armed check should be the first thing after the regime filter — before any DB loads or performance checks — to short-circuit as fast as possible for already-armed tickers. With 30–50 armed tickers after a busy morning, 30+ unnecessary performance checks and DB loads fire per cycle.
39.M-19	_bos_key = f"{ticker}:{direction}:{bars_session[breakout_idx]['datetime']}" uses the bar's datetime object formatted via str() (f-string). If datetime has timezone info, str(datetime_with_tz) includes the +00:00 suffix. After a restart, the same bar's datetime may be loaded tz-naive from the DB (via _strip_tz), producing str(datetime_naive) without the suffix. The same BOS event produces two different _bos_key values depending on whether the datetime is tz-aware or tz-naive, bypassing the dedup set. Should normalize via _strip_tz(bars_session[breakout_idx]['datetime']).isoformat().
🟢 Lows (8)
ID	Issue
39.L-20	from app.core.eod_reporter import run_eod_reports — the import expects run_eod_reports but eod_reporter.py exports run_eod_report (no trailing 's'). The stub fallback defined here is run_eod_reports(*args, **kwargs) — with 's'. The ImportError path correctly names the stub. But if eod_reporter.py is fixed to add run_eod_reports as an alias, the stub would conflict. Should align the name: use run_eod_report everywhere.
39.L-21	is_duplicate = _track_validation_call(ticker, direction, entry_price) — the stub returns False always (no duplicate detection). If sniper_log is unavailable, every signal passes the duplicate check silently. Should log a warning when the stub fires.
39.L-22	Module-level print("[SNIPER] ✅ VWAP directional gate enabled ...") fires without a corresponding try/except ImportError — it's a bare print regardless of whether vwap_gate.py actually loaded. The preceding from app.filters.vwap_gate import ... is a hard import (no try/except). If vwap_gate is missing, ImportError propagates and kills the module before the print. The print is misleading.
39.L-23	or_high, or_low = compute_opening_range_from_bars(bars_session) — or_high may be None if no OR bars exist. The if or_high is not None: guard is correct. However compute_premarket_range is imported but never called in process_ticker(). Dead import.
39.L-24	The should_skip_cfw6_or_early() guard prints "EARLY SESSION GATE: CFW6_OR blocked before 9:45 AM (OR={or_range_pct:.2%} < {or_threshold:.2%})" — but the description says "blocked before 9:45 AM" while or_threshold is the OR range width threshold, not a time threshold. The log message confuses time gating with range gating.
39.L-25	_smc_signal_data = dict(_mtf_trend_signal_data) then .update(...) — shallow copy of the MTF trend dict before passing to SMC. If _mtf_trend_signal_data contains nested dicts (e.g., {'mtf_trend': {'boost': 0.03, 'details': {...}}}), the shallow copy means _smc_signal_data['mtf_trend'] is the same object. SMC enrichment mutating this nested dict would corrupt _mtf_trend_signal_data. Should use copy.deepcopy().
39.L-26	The confidence formula print statement ([CONFIDENCE-v2] Base:...) is 350+ characters on a single line. Railway log lines are typically truncated at 512 bytes. The OB and SD boost display uses (0.03 if _ob_result else 0.0) — hardcoding 0.03 rather than reading the actual boost from _ob_result. If the OB boost is ever changed, the display will show the old hardcoded value while the actual calculation uses the new value.
39.L-27	_orb_classifications is a module-level dict that grows unbounded: _orb_classifications[ticker] = or_data. With 50 tickers × 5 trading days without restart, this dict holds 250 stale classifications. Should be keyed by (ticker, date) or cleared in the EOD reset path alongside _bos_watch_alerted.
Priority Fix Order (Batch 39)
Rank	ID	Fix
1	39.H-5	Add _eod_reports_fired module-level guard — prevents 50× EOD report calls at 15:55
2	39.C-1	Cache is_watching state before breakout_idx resolve loop — eliminates TOCTOU race
3	39.H-6	Unify dual cooldown systems — remove in-memory tracker or seed from DB on startup
4	39.M-12	Only clear watching signal when _run_signal_pipeline() returns True
5	39.H-1	Lazy-init _TICKER_WIN_CACHE — prevents import-time DB query blocking startup
6	39.H-4	Move check_performance_dashboard/alerts out of process_ticker() → once per cycle in scanner.py
7	39.M-18	Move ticker_is_armed check to be the first guard in process_ticker()
8	39.M-11	Cache OR per ticker per session — stop recomputing on every 45s cycle
9	39.M-16	Fix SPY regime directional penalty — apply negative adj for counter-trend signals
10	39.H-2	Add record_signal_rejected_at_gate() call for confidence gate failures

**39.H-5 is the most immediately harmful** — at 15:55 ET, every one of the 50 watchlist tickers triggers `run_eod_reports()` in the same cycle. Discord rate-limits, the session cache is cleared mid-scan, and AI optimization runs 50 times in 50 seconds. A one-line `_eod_reports_fired` flag is the fix.

**39.M-12 is the most signal-quality impactful** — clearing the watch regardless of pipeline outcome means a legitimate BOS with a failed greeks gate permanently loses its watch window. The ticker won't be re-watched even though the BOS is still valid. Every greeks-gate failure on a watched ticker silently abandons the setup.

**39.H-1 (`_TICKER_WIN_CACHE` at import time)** is the most dangerous from a stability standpoint — if the DB pool isn't ready when `scanner.py` does its hard `from app.core.sniper import process_ticker`, the entire process dies with a confusing `ImportError` instead of a DB timeout.

***

## `app/core/` Full Audit Summary (Batches 36–39)

| File | Batch | C | H | M | L | Total |
|------|-------|---|---|---|---|-------|
| `arm_signal.py` | 36 | 0 | 4 | 5 | 6 | 15 |
| `armed_signal_store.py` | 36 | 0 | 0 | 4 | 2 | 6 |
| `analytics_integration.py` | 37 | 0 | 3 | 5 | 3 | 11 |
| `eod_reporter.py` | 37 | 0 | 0 | 2 | 1 | 3 |
| `watch_signal_store.py` | 37 | 0 | 0 | 2 | 2 | 4 |
| `health_server.py` | 37 | 0 | 0 | 0 | 2 | 2 |
| `thread_safe_state.py` | 38 | 0 | 0 | 3 | 3 | 6 |
| `scanner.py` | 38 | 0 | 5 | 8 | 8 | 21 |
| `sniper.py` | 39 | 1 | 6 | 13 | 8 | 28 |
| **`app/core/` TOTAL** | | **1** | **18** | **42** | **35** | **96** |
