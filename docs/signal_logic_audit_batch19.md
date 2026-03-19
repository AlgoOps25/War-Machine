Here is the full Batch 19 audit. Ready to copy-paste.

File: docs/signal_logic_audit_batch19.md
text
# Signal Logic Audit — Batch 19

**Date:** 2026-03-18
**Scope:** `app/core/sniper.py`
**Total Findings:** 26 (2 Critical, 8 High, 10 Medium, 6 Low)

---

## 🔴 Criticals (2)

---

### 19.C-1 — `_run_signal_pipeline()` calls `signal_tracker.record_signal_generated()` AFTER `wait_for_confirmation()`, `grade_signal_with_confirmations()`, and the validator — but `signal_analytics.py` expects `record_signal_generated()` to be the FIRST event in the lifecycle chain (stage = GENERATED), with `record_validation_result()` called next. In `sniper.py`, GENERATED is recorded AFTER validation has already run, so the lifecycle order is inverted: VALIDATED is recorded before GENERATED exists in the session cache, causing `record_validation_result()` to always warn "No GENERATED signal found for {ticker}" and return -1.

**File:** `sniper.py` → `_run_signal_pipeline()`

The Phase 4 GENERATED block:
```python
if PHASE_4_ENABLED and signal_tracker:
    signal_tracker.record_signal_generated(
        ticker=ticker, signal_type=signal_type, direction=direction,
        grade=final_grade, confidence=compute_confidence(...), ...
    )
…appears at line ~410, AFTER:

wait_for_confirmation() (line ~280)

grade_signal_with_confirmations() (line ~360)

validator.validate_signal() (line ~385)

signal_tracker.record_validation_result() (line ~400)

record_validation_result() checks self.session_signals.get(ticker) for a cached GENERATED entry. Since GENERATED hasn't been recorded yet, cached is None → warning fires → validation event returns -1 → the entire funnel is broken. generated=0, validated=0 for every signal in the analytics DB, making the Phase 4 funnel completely useless.

Fix: Move record_signal_generated() to the very top of _run_signal_pipeline(), immediately after the cooldown check, using original_confidence = compute_confidence(final_grade, "5m", ticker) as a preliminary confidence estimate. The phase 4 tracking block currently at line ~410 should be removed.

19.C-2 — process_ticker() calls _run_signal_pipeline() with skip_cfw6_confirmation=True for both INTRADAY_BOS and VWAP_RECLAIM paths — but when skip_cfw6_confirmation=True, entry_price = bars_session[-1]["close"] and base_grade = bos_confirmation if bos_confirmation in ("A+", "A", "A-", "B+", "B") else "A-". For the VWAP reclaim path, bos_confirmation=None (not passed to _run_signal_pipeline()), so base_grade always defaults to "A-" regardless of actual candle quality. An "A+" quality VWAP reclaim candle will be graded A-, producing an artificially lower confidence and a lower dynamic threshold — the signal may pass a threshold it shouldn't.
File: sniper.py → process_ticker() → VWAP reclaim block

python
_run_signal_pipeline(
    ticker, vr["direction"], vr_zone_low, vr_zone_high,
    vr_or_high, vr_or_low, "CFW6_INTRADAY",
    bars_session, vr["reclaim_bar_idx"],
    spy_regime=spy_regime,
    skip_cfw6_confirmation=True,   # ← bos_confirmation not passed
)
detect_vwap_reclaim() returns a dict — it likely contains a quality/grade field. That grade should be extracted and passed as bos_confirmation=vr.get("grade", "A-") so the actual candle quality drives the grade assignment.

Fix:

python
_run_signal_pipeline(
    ticker, vr["direction"], vr_zone_low, vr_zone_high,
    vr_or_high, vr_or_low, "CFW6_INTRADAY",
    bars_session, vr["reclaim_bar_idx"],
    bos_confirmation=vr.get("grade", "A-"),   # ← pass actual grade
    bos_candle_type=vr.get("candle_type"),
    spy_regime=spy_regime,
    skip_cfw6_confirmation=True,
)
🟡 Highs (8)
19.H-3 — The analytics cooldown tracker (in-memory) blocks signals with return False — this is AFTER the DB cooldown check which is the intended dedup gate. The analytics tracker was designed for "reporting only (non-blocking)" per the comment, but return False on line ~245 makes it a hard gate. If cooldown_tracker.is_in_cooldown() returns True due to a stale in-memory state (e.g., after a Railway restart where in-memory is fresh but DB has a 29-minute-old cooldown), a valid new signal is dropped by the in-memory tracker but would have passed the DB gate. The two gates are redundant and inconsistent.
File: sniper.py → _run_signal_pipeline()

python
if TRACKERS_ENABLED and cooldown_tracker:
    if cooldown_tracker.is_in_cooldown(ticker):
        remaining = cooldown_tracker.get_cooldown_remaining(ticker)
        print(f"[{ticker}] 🚫 ANALYTICS COOLDOWN: {remaining:.0f}s remaining — signal dropped")
        return False   # ← hard gate on in-memory tracker
The comment says "non-blocking" but it blocks. After a Railway restart, the in-memory tracker is always empty (0-second cooldown) so the stale-state issue is actually the reverse: the DB gate correctly blocks duplicate signals after restart, but the in-memory gate is always fresh. The risk is a future bug where the in-memory tracker gets a stale state and silently drops valid signals.

Fix: Remove return False from the analytics cooldown block — make it log-only:

python
if cooldown_tracker.is_in_cooldown(ticker):
    remaining = cooldown_tracker.get_cooldown_remaining(ticker)
    print(f"[{ticker}] ⚠️ ANALYTICS COOLDOWN (non-blocking): {remaining:.0f}s — logged only")
19.H-4 — _run_signal_pipeline() calls compute_confidence(final_grade, "5m", ticker) three times for the same signal in the same call — once for base_confidence_pre_mtf_trend, once for the Phase 4 GENERATED record, and once for original_confidence. If compute_confidence() has any side effects (AI learning model state mutation, DB write, etc.) this triple-call will corrupt the learning model state. Even without side effects, the triple call is wasteful and error-prone if the grade changes between calls (it doesn't here, but creates fragility).
File: sniper.py → _run_signal_pipeline()

python
base_confidence_pre_mtf_trend = compute_confidence(final_grade, "5m", ticker)     # call 1
...
confidence=compute_confidence(final_grade, "5m", ticker),                          # call 2 (Phase 4)
...
original_confidence = compute_confidence(final_grade, "5m", ticker)                # call 3
Fix: Compute once at the top of the block and reuse:

python
original_confidence = compute_confidence(final_grade, "5m", ticker)
base_confidence_pre_mtf_trend = original_confidence
19.H-5 — _run_signal_pipeline() runs greeks_precheck.validate_signal_greeks() and options_filter.validate_signal_for_options() inside the function body — both imported dynamically with from app.validation.greeks_precheck import ... and from app.validation.validation import get_options_filter on every call. Dynamic imports inside hot function paths are resolved once by Python's import system (cached in sys.modules) but the from X import Y syntax still executes the lookup on every call. In a scanner loop processing 50 tickers every 30 seconds, this is 100+ redundant attribute lookups per minute. Minor but consistent overhead in the hottest path of the system.
File: sniper.py → _run_signal_pipeline() → OPTIONS_PRE_GATE block

Fix: Move these imports to module-level with try/except stubs, matching the pattern already used for every other optional module in sniper.py.

19.H-6 — _resample_bars() is defined inside _run_signal_pipeline() — a new function object is created on every call. In a 50-ticker scanner loop this is 50 function definitions per cycle. The function has no closure dependencies — it only uses collections.defaultdict which should be imported at module level. Move to module scope.
File: sniper.py → _run_signal_pipeline() → MTF_BIAS_ENABLED block

19.H-7 — The OR path early-session gate calls should_skip_cfw6_or_early(or_range_pct, now_et) but then does return — this returns from process_ticker() entirely, which means neither the intraday BOS path nor the secondary range path runs. If the OR is valid but the session is too early for the OR path, the intraday BOS path (scan_bos_fvg) is also skipped. An intraday BOS that fires at 9:42 AM on a ticker with a wide OR would be silently dropped.
File: sniper.py → process_ticker()

python
if should_skip_cfw6_or_early(or_range_pct, now_et):
    print(...)
    return   # ← exits process_ticker entirely — intraday BOS also skipped
Fix: Use continue to the next scan path (fall through to scan_mode is None block) rather than return:

python
if should_skip_cfw6_or_early(or_range_pct, now_et):
    print(...)
    # fall through to intraday BOS path
19.H-8 — process_ticker() checks _state.ticker_is_armed(ticker) to skip tickers that are already in a position — but this check happens BEFORE the bars fetch. If data_manager.get_today_session_bars() is the slow operation (network I/O), checking armed state first is correct. However, _maybe_load_watches() and _maybe_load_armed_signals() are called at the very top of process_ticker() on every single call — even for tickers that will immediately return due to regime filter or armed check. These DB loads should be lazy or rate-limited to avoid unnecessary DB I/O in the hot path.
File: sniper.py → process_ticker()

python
def process_ticker(ticker: str):
    try:
        _maybe_load_watches()          # ← DB call on every ticker, every cycle
        _maybe_load_armed_signals()    # ← DB call on every ticker, every cycle
Fix: Gate these calls with a session-level flag so they run once per scan cycle, not once per ticker:

python
if not _state.watches_loaded_this_cycle:
    _maybe_load_watches()
    _maybe_load_armed_signals()
    _state.watches_loaded_this_cycle = True
19.H-9 — process_ticker() calls check_performance_dashboard() and check_performance_alerts() on every ticker — these are per-ticker calls in a 50-ticker scan loop. If either function queries the DB or does any I/O, this is 50 DB queries per scan cycle just for dashboard refresh. The dashboard should be refreshed once per cycle, not once per ticker.
File: sniper.py → process_ticker()

python
check_performance_dashboard(_state, PHASE_4_ENABLED)
check_performance_alerts(_state, PHASE_4_ENABLED, alert_manager, send_simple_message)
Fix: Same pattern as 19.H-8 — gate with a cycle-level flag or move these calls to scanner.py's outer cycle loop.

19.H-10 — process_ticker() calls get_market_regime(force_refresh=False) for every ticker in the scan loop — the SPY regime is the same for all tickers at a given moment. If get_market_regime() fetches or recalculates the regime per-call (even with caching), this is redundant. The SPY regime should be fetched once per scan cycle in scanner.py and passed into process_ticker() as a parameter.
File: sniper.py → process_ticker()

python
if SPY_EMA_CONTEXT_ENABLED:
    spy_regime = get_market_regime()   # ← called for every ticker
🟠 Mediums (10)
ID	File	Issue
19.M-11	sniper.py	_get_or_threshold() calls get_regime_filter().get_regime_state().vix inside a try/except that catches all exceptions — if get_regime_filter() raises, vix = 20.0 is used silently. No warning is logged. A corrupt regime state (e.g. stale VIX from failed API fetch) produces a potentially wrong OR threshold with no visibility.
19.M-12	sniper.py	mult_to_adjustment() is defined inside _run_signal_pipeline() — same issue as _resample_bars() (19.H-6). New function object created per-call. Move to module scope.
19.M-13	sniper.py	The post-3PM decay final_confidence *= decay is applied AFTER the final_confidence = max(0.40, min(..., 0.95)) clamp, then re-clamped. The sequence is: clamp → decay → clamp again. If final_confidence = 0.40 (floor) and decay = 0.85, the result is 0.34, which is then clamped back to 0.40. The decay has zero effect on floor-level confidence signals near 3 PM. Likely intentional (floor is absolute), but undocumented.
19.M-14	sniper.py	scan_mode variable is checked with if scan_mode is None and VWAP_RECLAIM_ENABLED at the bottom of process_ticker(). But if scan_mode was set to "OR_ANCHORED" or "INTRADAY_BOS" and _run_signal_pipeline() returned False (signal dropped), the VWAP reclaim path is NOT checked as a fallback. This may be intentional (one signal per ticker per cycle), but it means a ticker with a failed OR signal and a valid VWAP reclaim will always miss the VWAP reclaim until the next cycle.
19.M-15	sniper.py	_bos_watch_alerted set is module-level and never cleared during the session (only mentioned "Cleared at EOD alongside watching_signals" in a comment). But the actual clear happens in clear_watching_signals() from watch_signal_store.py — _bos_watch_alerted.clear() is NOT called anywhere in sniper.py. If clear_watching_signals() is called at EOD, the BOS dedup set remains populated until process restart. This is benign (EOD is end of trading) but if the process stays alive across days (Railway persistent), day-old BOS keys remain in the set and a same-day-next-day BOS for the same ticker at the same datetime would be suppressed.
19.M-16	sniper.py	final_confidence = max(0.40, min(final_confidence, 0.95)) hard-codes 0.40 and 0.95 as confidence bounds. These same bounds appear in app/ai/ai_learning.py and config.py. Three separate places define the same floor/ceiling — the constants are not imported from a single source of truth. If the floor is raised to 0.45 in config.py, the clamp in sniper.py still uses 0.40.
19.M-17	sniper.py	The VWAP reclaim vr_zone_low = vr["vwap_at_reclaim"] * 0.9985 and vr_zone_high = vr["vwap_at_reclaim"] * 1.0015 construct a synthetic ±0.15% zone around VWAP as the FVG proxy. This 0.15% constant is hardcoded with no config entry and no comment explaining its derivation. It also makes the zone width independent of price volatility — a $500 stock gets a $1.50 zone; a $10 stock gets a $0.015 zone. The zone should be ATR-derived or at minimum pulled from a config constant.
19.M-18	sniper.py	_pre_options_data is set inside the OPTIONS_PRE_GATE_ENABLED block, but is referenced unconditionally later as options_rec = _pre_options_data. If OPTIONS_PRE_GATE_ENABLED = False, _pre_options_data is never initialized → NameError: name '_pre_options_data' is not defined. The variable is initialized to None at the start of the OPTIONS_PRE_GATE block but ONLY if the block is entered. If OPTIONS_PRE_GATE_ENABLED = False, the block is skipped and the variable is never set.
19.M-19	sniper.py	_TICKER_WIN_CACHE = get_ticker_win_rates(days=30) is executed at module import time — a DB query runs at startup. The result is never refreshed during the session. Win rates learned intraday are never incorporated until the next process restart.
19.M-20	sniper.py	The OR watch entry stored in _state.set_watching_signal() uses "breakout_bar_dt": _strip_tz(bars_session[breakout_idx]["datetime"]). Later in process_ticker(), the watch restoration loop does _strip_tz(bar["datetime"]) == bar_dt_target to find the bar. If two bars have the same datetime (clock skew, duplicate bars from API), resolved_idx will always resolve to the first matching bar, potentially using a wrong breakout_idx. No dedup/warning for duplicate bar datetimes.
🟢 Lows (6)
ID	File	Issue
19.L-21	sniper.py	Module-level print() calls (15+) fire at every import — process startup logs are noisy and impossible to suppress. Same issue flagged batches 8–18. Replace with logger.info() or gate behind a DEBUG flag.
19.L-22	sniper.py	The EXPLOSIVE_RVOL_THRESHOLD = 3.0 constant at module scope conflicts with the header comment # EXPLOSIVE MOVER OVERRIDE: Score >=80 + RVOL >=4.0x. The comment says 4.0x, the code is 3.0x. One is stale.
19.L-23	sniper.py	_orb_classifications dict grows unbounded during the session (one entry per ticker per successful OR scan). Never cleared. For a 100-ticker watchlist running 6.5 hours, this is benign (100 entries), but it should be cleared at EOD to avoid stale data surviving into the next session on a long-running process.
19.L-24	sniper.py	or_high, or_low = compute_opening_range_from_bars(bars_session) is computed for every ticker every scan cycle after 9:30 AM — even tickers that have already had their OR captured. The OR is fixed after 9:40 AM (_now_et().time() < time(9,30) guard only skips pre-market). Caching the OR per ticker in _orb_classifications would avoid recomputing it every cycle.
19.L-25	sniper.py	mode_decay = 0.95 if signal_type == "CFW6_OR" else 1.0 — a 5% penalty on OR signals is applied but never explained in comments. This hardcoded decay has no config entry and no documentation linking it to a backtest result or design decision.
19.L-26	sniper.py	vp_bias = vp_data.get('options_bias', 'NEUTRAL') is computed and printed but never used — it is not applied to final_confidence or passed to options filter. Dead variable.
Priority Fix Order
19.C-1 — record_signal_generated() called AFTER record_validation_result() — entire Phase 4 funnel is inverted and broken

19.C-2 — VWAP reclaim path always assigns A- grade regardless of actual candle quality — confidence artificially lowered

19.H-7 — Early session OR gate return exits process_ticker() entirely — intraday BOS path silently skipped for early signals

19.M-18 — _pre_options_data uninitialized if OPTIONS_PRE_GATE_ENABLED = False → NameError at runtime

19.H-4 — compute_confidence() called 3× per signal — potential AI model side-effect corruption

19.H-3 — In-memory analytics cooldown blocks signals with return False (comment says non-blocking)

19.H-6 + 19.M-12 — _resample_bars() and mult_to_adjustment() defined inside hot function — move to module scope

19.H-8 + 19.H-9 + 19.H-10 — Per-ticker DB loads, dashboard checks, and SPY regime fetches — move to cycle scope

text

***

Add to `docs/signal_logic_audit_index.md`:

**Batch Status row:**


