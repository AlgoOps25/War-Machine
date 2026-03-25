Batch 8 — app/validation Layer
22 findings across 4 modules. Modules covered: validation.py (SignalValidator, RegimeFilter, OptionsFilter), cfw6_gate_validator.py, cfw6_confirmation.py, entry_timing.py, hourly_gate.py, volume_profile.py.

🔴 Criticals (4)
8.C-1 — Direction mismatch: SignalValidator uses 'BUY'/'SELL' but callers pass 'bull'/'bear'
File: validation.py, SignalValidator.validate_signal() — EMA stack and DMI checks

python
if signal_direction == 'BUY':       # EMA stack check
    full_stack = (current_price > ema9 > ema20 > ema50)
...
expected_direction = 'BULLISH' if signal_direction == 'BUY' else 'BEARISH'  # DMI check
Every other module in the pipeline (sniper.py, options_intelligence.py, gex_engine.py) passes 'bull'/'bear'. The EMA stack and DMI checks will always fall into the else branch, treating every signal as a SELL/bear. This silently degrades confidence on all bull signals with -0.04 (EMA no-stack) and -0.10 (DMI conflict) — a combined -14% confidence penalty on every bull signal. This has been live in production.

Fix: Normalize at entry: direction = signal_direction.upper() then use 'BUY'/'SELL', or change all comparisons to 'bull'/'bear'.

8.C-2 — VPVR rescue removes BIAS_COUNTER_TREND_STRONG from failed_checks but the -25% penalty is never reversed
File: validation.py, VPVR rescue block (~line 620)

python
rescue_boost = abs(counter_trend_penalty) * 0.80   # = 0.25 * 0.80 = +0.20
confidence_adjustment += rescue_boost
passed_checks.append('VPVR_RESCUE')
failed_checks.remove('BIAS_COUNTER_TREND_STRONG')  # label removed ✓
The rescue adds +0.20 to confidence_adjustment — but the -0.25 was already applied earlier when counter_trend_penalty was set. Net effect: confidence_adjustment has both the -0.25 AND the +0.20, leaving a net -5% penalty even after a "full rescue." The docstring/comment says "overrides bias penalty" but it only partially offsets it. A rescued signal is permanently impaired.

Fix: The rescue should restore the full penalty. Either set rescue_boost = abs(counter_trend_penalty) (100% restore), or reverse the original penalty before adding the rescue:

python
confidence_adjustment -= counter_trend_penalty   # undo the -0.25 first
confidence_adjustment += rescue_boost            # then add the net boost
8.C-3 — _classify_regime() returns favorable=True for TRENDING even when VIX 25–29
File: validation.py, _classify_regime() (~line 290)

python
if vix >= 35:
    return ("VOLATILE", False, ...)
if vix >= 30:
    return ("VOLATILE", False, ...)
# ... VIX-aware ADX threshold logic ...
if adx >= effective_adx_threshold:
    if vix < 25:
        return ("TRENDING", True, ...)
    else:
        return ("TRENDING", True, ...)   # ← BOTH branches return favorable=True
The vix < 25 branching only changes the log message — both branches return favorable=True. This means a VIX-26 to VIX-29 environment with ADX ≥ 12 is classified as TRENDING / favorable=True. That is a high-volatility tape where trend signals have much lower follow-through probability. The VIX 25–30 range should carry a soft penalty or favorable=False.

Fix: For 25 < vix < 30, return favorable=True but add a regime penalty multiplier (e.g., -0.10), or return ("TRENDING", False, "Elevated VIX — trend caution") to require the RVOL override path.

8.C-4 — filter_by_dte() uses datetime.now() (local time) instead of ET
File: validation.py, OptionsFilter.filter_by_dte() (~line 370)

python
dte = (datetime.strptime(expiration_date, "%Y-%m-%d") - datetime.now()).days
datetime.now() returns local server time (Railway cloud — UTC). expiration_date is a market calendar date (ET). On Railway (UTC), datetime.now() is 5 hours ahead of ET. Any option expiring the same calendar day will compute dte = -1 (expired) and be filtered out — 0-DTE options are permanently invisible to the system regardless of config. On Mondays, 1-DTE (Tuesday expiry) options also disappear before 5 PM ET.

Fix:

python
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
dte = (datetime.strptime(expiration_date, "%Y-%m-%d").date() - datetime.now(ET).date()).days
🟡 Highs (6)
8.H-5 — validate_signal() uses should_pass = len(passed_checks) >= len(failed_checks) as fallback — this is a vote, not a signal gate
File: validation.py, end of validate_signal() (~line 660)

python
else:
    should_pass = len(passed_checks) >= len(failed_checks)
A signal with 5 passed trivial checks (e.g., TIME_MORNING_SESSION, REGIME_NEUTRAL, VPVR_NEUTRAL, ADX_OK, VOLUME_OK) and 4 failed critical checks (BIAS_COUNTER_TREND_STRONG, DMI_CONFLICT, EMA_NO_STACK, CCI_OVERBOUGHT) passes with 5 >= 4 = True. Numeric vote counting ignores check severity entirely.

Fix: Assign weights to checks. Critical failures (BIAS_COUNTER_TREND_STRONG, DMI_CONFLICT, REGIME_CHOPPY) should be hard-fail independent of vote count.

8.H-6 — Regime filter called twice per signal — once inside validate_signal(), once before it in the sniper
File: validation.py — RegimeFilter is a singleton but get_regime_state() still fetches and caches at a 5-min TTL. The validate_signal() method calls regime_filter.get_regime_state() on every signal, even though the sniper already called is_favorable_for_explosive_mover() seconds earlier. If the cache expires mid-scan cycle, the second call issues a fresh VIX/SPY fetch — doubling API load per signal in high-frequency scans.

Fix: Pass RegimeState as a parameter to validate_signal() so the regime is fetched once per scan cycle, not once per ticker.

8.H-7 — validate_signal_for_options() hard-fails when iv > 1.0 — but EODHD returns IV as a decimal (e.g., 0.45 = 45%)
File: validation.py, OptionsFilter.validate_signal_for_options() (~line 430)

python
if best_strike.get("iv", 0) > 1.0:
    return False, best_strike, f"IV too high ({best_strike['iv']*100:.1f}%)"
EODHD's UnicornBay marketplace returns IV in decimal form (0.45 = 45%). The threshold > 1.0 means IV > 100% triggers the hard fail. This is correct for normal tickers. However, the _normalize_v2_chain() mapper maps attrs.get("volatility", 0) directly — and there is no guard against brokers/feeds that return IV in percentage form (e.g., 45.0). A single mis-formatted record from EODHD would make every option appear to have > 100% IV and block all options trades silently. This should at minimum log a warning when iv > 2.0 (i.e., > 200% IV) as a sanity check.

8.H-8 — get_options_chain() fetches only 30 days of expirations — misses monthlies > 30 DTE
File: validation.py, OptionsFilter.get_options_chain() (~line 355)

python
"filter[exp_date_to]": (today + timedelta(days=30)).strftime("%Y-%m-%d"),
config.MAX_DTE controls the DTE gate, but the chain API call only requests expirations up to 30 days out. If config.MAX_DTE = 45 (a common swing-trade setting), any 31–45 DTE expiration is never fetched from the API. find_best_strike() silently finds no valid strike and returns None.

Fix: Use timedelta(days=config.MAX_DTE + 5) to ensure the window always covers the configured DTE range.

8.H-9 — _get_spy_bars() tries 3 different data sources with no logging on fallback — silent degradation
File: validation.py, RegimeFilter._get_spy_bars()

If get_bars_from_memory("SPY") returns fewer than 14 bars, it silently falls back to get_today_session_bars(), then to get_today_5m_bars(). If the final fallback also has < 14 bars (early session), the function returns [] and get_regime_state() returns favorable=False with reason "Insufficient data" — blocking all signals before 9:45 AM without any log distinguishing "bad tape" from "not enough bars yet." This has likely caused phantom CHOPPY blocks at open.

Fix: Add a distinct log [REGIME] Insufficient SPY bars (N bars, need 14) — will retry so the block is distinguishable from a real choppy regime.

8.H-10 — scan_chain_for_uoa imported from options_intelligence which is broken (7.C-1)
File: validation.py, top-level imports

python
try:
    from app.options.options_intelligence import scan_chain_for_uoa
    from uoa_scanner import format_uoa_summary  # Still in stub for convenience
except ImportError:
    ...
scan_chain_for_uoa inside options_intelligence calls get_chain() which always returns None (7.C-1). The ImportError fallback returns uoa_multiplier: 1.0 — so UOA detection silently produces neutral output. Additionally, from uoa_scanner import format_uoa_summary imports from a stub module — any formatting of UOA data in find_best_strike() will use the stub's no-op formatter.

🟠 Mediums (8)
#	File	Issue
8.M-11	validation.py	_calculate_adx() requires period * 2 + 1 = 29 bars but _get_spy_bars(limit=50) fetches only 50. In early session (< 29 bars live), ADX returns None → regime falls to favorable=False unnecessarily — same as 8.H-9 but a separate code path
8.M-12	validation.py	VPVR_RESCUE and VPVR_STRONG can both apply to the same signal (vpvr_rescue_applied doesn't block entry_score >= 0.85 branch below) — double-counting up to +0.28 adjustment
8.M-13	validation.py	_normalize_v2_chain() silently drops options where exp, ctype, or strike is missing — no counter or log. A malformed EODHD batch response could silently empty the chain
8.M-14	validation.py	get_time_of_day_quality() has no timezone guard — uses datetime.now(ET) in caller but the function itself doesn't enforce ET, so if called with a naive datetime it silently uses local server time
8.M-15	hourly_gate.py	Hourly gate likely duplicates the time-of-day check in SignalValidator — needs cross-check to ensure they don't double-penalize the same signal in the same scan cycle
8.M-16	volume_profile.py	calculate_vpvr() uses lookback_bars=78 hardcoded in validate_signal() — this is 78 × 5-min bars = 6.5 hours, which on early-session calls (< 78 bars) always returns error 'Need 78+ bars' and skips VPVR entirely for first ~3 hours of session
8.M-17	entry_timing.py	filter_by_dte() and entry_timing.py DTE logic are separate implementations — any DTE threshold change must be updated in both places or they will diverge
8.M-18	cfw6_gate_validator.py	CFW6 gate and SignalValidator.validate_signal() both run regime checks — if both are in the signal path, regime is evaluated twice per signal with separate cache windows, potentially returning different results
🟢 Lows (4)
#	File	Issue
#	File	Issue
8.L-19	validation.py	print() throughout all three classes instead of logger.* — kills structured log parsing
8.L-20	validation.py	get_options_recommendation() creates a new OptionsFilter() instance on every call — bypasses the singleton cache and issues a fresh chain fetch on each invocation
8.L-21	validation.py	calculate_expected_move() formula price * iv * sqrt(dte/365) assumes IV in decimal form but has no guard — if IV > 1.0 (percentage form), expected move is wildly inflated
8.L-22	validation.py	Module __all__ does not export get_options_recommendation — callers that rely on from validation import * won't find it
Priority fix order
8.C-1 — Direction string normalization ('BUY'/'SELL' vs 'bull'/'bear') — bleeding -14% on every bull signal right now

8.C-4 — DTE timezone bug — 0-DTE and same-day options permanently invisible on Railway/UTC

8.C-2 — VPVR rescue doesn't fully restore the bias penalty

8.H-5 — Replace vote-count gate with weighted severity gate

8.H-8 — Chain fetch window must cover MAX_DTE, not hardcoded 30 days

8.M-12 — VPVR double-count (+0.28 max adj)