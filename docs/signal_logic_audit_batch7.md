Batch 7 — app/options Layer
19 findings across 5 modules. Modules covered: __init__.py, options_intelligence.py, gex_engine.py, iv_tracker.py (referenced), options_dte_selector.py/options_optimizer.py (structural review).

🔴 Criticals (3)
7.C-1 — get_chain() is permanently broken — always returns None
File: options_intelligence.py, get_chain() method (~line 115)

python
# chain = self.options_filter.get_options_chain(ticker)  # Merged into validation.py
chain = None  # TODO: Implement via validation.py if needed
get_chain() always returns None. This means every downstream call — validate_for_trading(), get_options_score(), scan_chain_for_uoa(), get_live_gex() — immediately hard-fails or returns an empty/zero result. Step 6.5 of the signal pipeline is effectively disabled. This is your single most dangerous live bug in the options layer.

Fix: Wire get_chain() to the actual chain source (EODHD UnicornBay /options/contracts endpoint or app/validation/validation.py's chain fetcher — whichever is canonical). Until this is done, the GEX gate, IVR gate, and UOA detection produce no real signal.

7.C-2 — GEX gamma_flip fallback selects wrong strike
File: gex_engine.py, compute_gex_levels() (~line 90)

python
# If no zero-crossing found, use the strike closest to zero GEX
if gamma_flip is None:
    gamma_flip = min(gex_by_strike.keys(), key=lambda s: abs(gex_by_strike[s]))
When there is no zero-crossing (i.e., the entire chain is one-sided — all positive or all negative GEX), the fallback picks the strike with the smallest absolute GEX value and promotes it as the "flip level." This is conceptually wrong: a small-GEX strike is not a flip point. In a deeply one-sided market, neg_gex_zone will then be set incorrectly, flipping the multiplier logic.

Fix: When no zero-crossing exists, set gamma_flip = None and neg_gex_zone = (total_gex < 0) — the whole chain is one-sided, use total GEX sign as the environment signal instead.

7.C-3 — _calculate_uoa_score() uses circular self-referential averages
File: options_intelligence.py, _calculate_uoa_score() (~line 340)

python
if avg_volume is None:
    avg_volume = max(volume / 2.0, 1)   # assumes today is 2× average
if avg_oi is None:
    avg_oi = max(open_interest / 1.5, 1)  # assumes today is 1.5× average
When no historical baseline is passed, the "average" is derived from the current value itself. This means:

volume_ratio = volume / (volume/2) = always 2.0

oi_ratio = open_interest / (open_interest/1.5) = always 1.5

Every single contract will appear to have UOA, because the ratio is always ≥ the minimum threshold (MIN_VOLUME_RATIO = 2.0, MIN_OI_RATIO = 1.5). UOA detection is firing on every contract — it has zero discriminating power.

Fix: Require a real historical baseline (5-day avg vol per strike stored in DB or passed from the chain snapshot). Until that exists, return score 0.0 with label UOA-NO-BASELINE rather than fabricating ratios.

🟡 Highs (5)
7.H-4 — risk_reward is a hardcoded placeholder on every trade
File: __init__.py, build_options_trade() (~line 130)

python
risk_reward = f"1:{2.5}"  # Placeholder - calculate based on targets
risk_reward has never been calculated. Every trade built by this function shows 1:2.5 regardless of actual stop/target levels. Anything downstream that uses this value (Discord alert, position sizing, logging) is getting fabricated data.

Fix: Compute from entry_price, stop (ATR-based), and target (T1/T2 from signal):

python
risk = entry_price - stop_price
reward = target_price - entry_price
risk_reward = f"1:{reward/risk:.1f}" if risk > 0 else "N/A"
7.H-5 — validate_for_trading() pin-drag sign logic is inverted for bears
File: options_intelligence.py, validate_for_trading(), bear branch (~line 250)

python
elif direction == 'bear':
    pin_pct = (entry_price - pin) / entry_price
    if pin_pct < -0.02:    # pin >2% above bear entry
pin_pct = (entry_price - pin) / entry_price. If pin > entry_price (pin is above), pin_pct is negative. The comment says "pin >2% above" but the condition fires when pin_pct < -0.02, which means pin > entry * 1.02 — correct intent. But the cap/floor soft warning immediately below:

python
elif 0.0 < pin_pct < 0.03:  # pin just below entry (support floor)
This fires when pin < entry_price (pin below bear entry). For a bear trade, a pin below entry is a target assist (price gravitates toward the pin in the direction of the trade), not a "support floor" headwind. The warning label is factually wrong and will suppress valid bear signals.

Fix: For bears, a pin below entry within 3% should be PIN-TARGET-NEAR (favorable), not PIN-FLOOR-NEAR (warning).

7.H-6 — _compute_gex_score() awards bull-biased points without direction
File: options_intelligence.py, _compute_gex_score() (~line 455)

python
if pin > current_price * 1.01:
    score += 10
    factors.append(f'PIN-ABOVE@{pin:.2f}')
elif pin < current_price * 0.99:
    score += 5
    factors.append(f'PIN-BELOW@{pin:.2f}')
Pin-above always gets 10 pts, pin-below always gets 5 pts — regardless of signal direction. For a bear signal, pin-above is a headwind (10 pts is wrong; it should be penalized) and pin-below is a tailwind (5 pts is correct). The scoring function has no direction parameter at all.

Fix: Add direction: str parameter and invert the scoring for bear signals.

7.H-7 — _get_ivr_data() reads only the first call it encounters
File: options_intelligence.py, _get_ivr_data() (~line 490)

python
for expiry, opts in data.items():
    for strike_str, opt in opts.get('calls', {}).items():
        iv = opt.get('impliedVolatility', 0)
        if iv and iv > 0:
            store_iv_observation(ticker, iv)
            ...
            return   # ← exits on FIRST call option with any IV
The IVR is computed from whichever call option happens to appear first in dict iteration (which is expiration-date ordered but strike-unordered). This could be a deep OTM or a far-expiry option whose IV is not representative of ATM short-term IV.

Fix: Scan for the ATM call on the nearest expiration and use that IV specifically (same ATM logic already used in _compute_liquidity_score()).

7.H-8 — _calculate_fallback_expiration() skips to next Friday when today is Friday
File: __init__.py, _calculate_fallback_expiration() (~line 380)

python
days_until_friday = (4 - target_date.weekday()) % 7
if days_until_friday == 0:
    days_until_friday = 7   # If today is Friday, go to next Friday
This if checks target_date.weekday(), not today's weekday. If the target date (not today) falls on a Friday, it's bumped an extra week — meaning a 7-DTE trade requested on a Monday targeting the following Friday jumps to 14 DTE instead. For options, missing the target expiry by a week is a significant pricing difference.

Fix: Remove the days_until_friday == 0 special-case. If days_until_friday == 0 the target IS Friday — return it directly.

🟠 Mediums (7)
#	File	Issue
7.M-9	__init__.py	quantity capped at 10 contracts with no config override — hardcoded min(quantity, 10) ignores account size growth
7.M-10	__init__.py	_get_current_price() silently returns None and causes build_options_trade() to return None with no caller-side guard in most callers
7.M-11	options_intelligence.py	_ivr_cache dict is populated in __init__ but never written to — _get_ivr_data() stores nothing in it, so every IVR call is a DB round-trip
7.M-12	gex_engine.py	top_negative built with [-5:][::-1] on the already-desc-sorted list — this produces the 5 least-negative entries, not the 5 most negative. Should be sorted_by_gex[-5:] before reversing
7.M-13	options_intelligence.py	get_chain() cache invalidates _score_cache, _gex_cache, _uoa_cache on refresh — but not _ivr_cache, which can serve a stale IVR from a prior chain snapshot
7.M-14	__init__.py	_select_strike_with_greeks() computes target_dte from datetime.now() at call time, but target_date was computed earlier in build_options_trade() — race condition across midnight boundary (minor but real on 9:30 PM restarts)
7.M-15	options_intelligence.py	scan_chain_for_uoa() scans all expirations including LEAPS, inflating OI figures — should filter to near-term expirations (≤ 45 DTE) to detect real short-term flow
🟢 Lows (4)
#	File	Issue
7.L-16	__init__.py	iv * 100 comment says "Convert decimal to percentage" but no guard against IV already being in percentage form (some brokers return 40.0 not 0.40) — could produce IV = 4000%
7.L-17	gex_engine.py	No handling for zero current_price in GEX formula — contribution = gamma * oi * 100 * 0 → all GEX = 0, silent data corruption
7.L-18	options_intelligence.py	print() statements in __init__ and clear_cache() instead of logger.*
7.L-19	__init__.py	OCC symbol builder _build_contract_symbol() does not pad the ticker to 6 chars (OCC standard) — symbols for tickers < 6 chars (e.g. AAPL) will be malformed for broker submission
Priority fix order
7.C-1 — Wire get_chain() (entire options validation layer is dark until this is fixed)

7.C-3 — UOA baseline (every signal is flagged as "unusual")

7.C-2 — GEX flip fallback

7.H-5 — Bear pin-drag sign inversion (live trade suppression bug)

7.H-6 — Direction-aware GEX scoring

7.M-12 — top_negative list built backwards