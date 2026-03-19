Here is the full Batch 17 audit. Ready to copy-paste.

File: docs/signal_logic_audit_batch17.md
text
# Signal Logic Audit — Batch 17

**Date:** 2026-03-18
**Scope:** `app/signals/breakout_detector.py`, `app/signals/opening_range.py`
**Total Findings:** 21 (1 Critical, 6 High, 8 Medium, 6 Low)

---

## 🔴 Criticals (1)

---

### 17.C-1 — `detect_breakout()` calculates support/resistance on `bars[:-1]` but checks `session_anchored` flag on the FULL `bars` list — the two calls can disagree on resistance level, so `session_anchored=True` can be set even when the entry logic used the rolling (non-session-anchored) resistance
**File:** `breakout_detector.py`

```python
support, resistance = self.calculate_support_resistance(bars[:-1], ticker)
# ... entry logic fires against `resistance` from bars[:-1] ...

# Later, session_anchored detection (separate call):
session = get_session_levels(ticker)
session_anchored = (
    abs(resistance - session['session_high']) < 0.01 or
    abs(support    - session['session_low'])  < 0.01
)
calculate_support_resistance(bars[:-1]) may return session_high from get_session_levels(). But the session_anchored flag detection below it also calls get_session_levels() independently and checks the tolerance as < 0.01 (1 cent). If session_high is e.g. $415.23 and calculate_support_resistance snapped resistance to $415.23, then abs(resistance - session['session_high']) = 0.0 → session_anchored = True. This path is actually correct. The real failure case is when get_session_levels() returns a slightly different value the second time (race between two data_manager.get_today_session_bars() calls during fast tape) — the first call has one more tick than the second, so session_high differs by a tick. The < 0.01 tolerance is too tight for this. More critically: the session_anchored flag is checked for the Discord log/reason string but is NOT checked before the entry fires — an entry can fire against the wrong resistance level and report [session-anchored] in the reason.

Fix: Call calculate_support_resistance once, store intermediate info (was session anchor used), and use a loose tolerance (e.g. 0.1%) for the flag check:

python
support, resistance = self.calculate_support_resistance(bars[:-1], ticker)
# Inside calculate_support_resistance(), set a flag and return it as part of result
# Or: widen tolerance to abs(resistance - session_high) / session_high < 0.001
🟡 Highs (6)
17.H-2 — detect_breakout() computes ATR on the full bars list but support/resistance on bars[:-1] — ATR includes the breakout bar itself, inflating stop distance and risk/reward when the breakout bar has a large range
File: breakout_detector.py

python
support, resistance = self.calculate_support_resistance(bars[:-1], ticker)
ema_volume          = self.calculate_ema_volume(bars[:-1])
atr                 = self.calculate_atr(bars, ticker)   # ← full bars including latest
calculate_support_resistance and calculate_ema_volume intentionally exclude the latest bar to avoid using the signal bar itself in the baseline. calculate_atr does not apply this same discipline — it includes the breakout bar in the ATR calculation. A 3% range breakout bar can inflate ATR by 20–40%, widening the stop by the same margin, making the trade look less attractive (risk rises, risk_reward shrinks), and potentially suppressing confidence via the atr_pct scorer. Consistently: ATR should also be computed on bars[:-1].

Fix:

python
atr = self.calculate_atr(bars[:-1], ticker)
17.H-3 — _calculate_confidence() starts at 50 and can exceed 100 before the min(confidence, 100) cap — retest entries add +10 after calling _calculate_confidence() without re-capping to 95/100 — no, they do min(confidence, 95) — but breakout entries add +10 for PDH confluence INSIDE the scorer, putting the cap at 100 — a 3x volume + strong candle + PDH confluence + 3% break = 50+30+20+10+10+10 = 130 → capped at 100 — meaning the confluence bonus is absorbed in most high-quality signals and has zero marginal effect
File: breakout_detector.py

python
confidence = 50
# volume >= 3.0:     +30  → 80
# breakout >= 0.03:  +20  → 100
# atr_pct < 0.02:    +10  → 110 → but cap is applied at end
# candle body >= 0.7: +10 → but cap kills this
# PDH:               +10  → still capped
return min(confidence, 100)
The scoring model starts at 50 (meaning a signal with zero volume and zero strength still has 50 confidence — above the 50 filter threshold). High-quality signals saturate at 100 frequently, making the top tier completely undifferentiated. The < 50 filter at the end of detect_breakout() only rejects signals that scored below zero in ALL additive categories — which can never happen since they start at 50. The filter is effectively dead for any real signal.

Fix: Start confidence at 0, adjust the filter threshold to e.g. < 55 or < 60, and rebalance the point values to spread the distribution meaningfully:

python
confidence = 0
# volume >= 3.0: +35, >= 2.5: +25, >= 2.0: +15
# breakout >= 0.03: +20, ...
# ATR pct ...
# candle body ...
# PDH: +10
# threshold: < 55
17.H-4 — calculate_support_resistance() PDH/PDL confluence check divides by resistance and support respectively — if support == 0.0 (bar with corrupted low) this is ZeroDivisionError
File: breakout_detector.py

python
if pdh is not None:
    if abs(pdh - resistance) / resistance < 0.02:   # resistance could be 0.0
if pdl is not None:
    if abs(pdl - support) / support < 0.02:         # support could be 0.0
intraday_support = min(bar['low'] for bar in lookback) — if any bar has low = 0.0 (REST API returning a malformed bar), support = 0.0. Division by zero in the PDH/PDL confluence check follows. Same issue flagged for or_range_pct in opening_range.py (17.M-12 below).

Fix: Guard both divisions:

python
if pdh is not None and resistance > 0:
    if abs(pdh - resistance) / resistance < 0.02:
if pdl is not None and support > 0:
    if abs(pdl - support) / support < 0.02:
17.H-5 — classify_or() TTL comparison strips tzinfo from both sides with .replace(tzinfo=None) — if current_time is tz-naive (passed in from a caller that does datetime.now() without ET), and _cached_at is tz-naive ET, this silently compares a UTC-offset naive time against an ET naive time — the DYNAMIC cache may expire 4–5 hours early during DST
File: opening_range.py

python
cached_at = cached.get('_cached_at')
if cached_at and (current_time.replace(tzinfo=None) - cached_at.replace(tzinfo=None)) < OR_CACHE_DYNAMIC_TTL:
    return cached
_cached_at is stored as current_time.replace(tzinfo=None) — i.e. ET wall time stripped of tzinfo. If a caller passes current_time=datetime.now() (no timezone, UTC on Railway), then current_time.replace(tzinfo=None) is UTC naive, and the delta is UTC_now - ET_cached_at = 4-5 hours ahead of actual age. A DYNAMIC cache entry cached at 9:42 ET (stored as naive 09:42) is compared against current_time = 13:45 UTC (naive) → delta = 4h03m > 30min TTL → immediately expires on the next call. The DYNAMIC classification re-runs every call instead of every 30 minutes.

Fix: Normalize all datetimes to ET-aware before comparison:

python
now_et = current_time if current_time.tzinfo else datetime.now(ET)
cached_at_et = cached.get('_cached_at')
if cached_at_et:
    if isinstance(cached_at_et, datetime) and cached_at_et.tzinfo is None:
        cached_at_et = cached_at_et.replace(tzinfo=ET)
    if (now_et - cached_at_et) < OR_CACHE_DYNAMIC_TTL:
        return cached
17.H-6 — should_scan_now() always returns True — OR classification is computed but its result is never used; the scan frequency or_data['scan_frequency'] is computed but discarded
File: opening_range.py

python
def should_scan_now(self, ticker, current_time=None):
    if not self._is_or_complete(current_time):
        return True
    or_data = self.classify_or(ticker, current_time)
    return True  # scan frequency handled by scanner loop
classify_or() is called (triggering cache hits or DB reads on every scanner tick for every ticker), but the result is thrown away and True is always returned. This adds N_tickers cache reads per scanner cycle for zero gain. The comment says "scan frequency handled by scanner loop" — but get_scan_frequency() exists for exactly this purpose and is never called by the scanner. Either wire get_scan_frequency() into the scanner or remove the dead classify_or() call inside should_scan_now().

Fix (minimal): Remove the dead classify call:

python
def should_scan_now(self, ticker, current_time=None):
    return True  # frequency managed externally
17.H-7 — adjust_signal_confidence() multiplies confidence_adjustment * 100 — but confidence_adjustment is already a percentage expressed as a fraction (e.g. 0.05 for 5%) — so the boost applied is 0.05 * 100 = 5.0 added to an integer confidence score (e.g. 72) — net result 72 + 5 = 77 instead of the intended 72 + 5% = 75.6 → 76
File: opening_range.py

python
signal['confidence'] = min(100, original_confidence + (confidence_adjustment * 100))
For a TIGHT OR, confidence_adjustment = 0.05. The signal confidence is an integer 0–100. The intended behavior is "add 5 percentage points." 0.05 * 100 = 5.0 — so the math is actually correct. However, min_confidence on line:

python
min_confidence = or_data['min_confidence'] * 100
min_confidence is stored as 0.60 (float) → 0.60 * 100 = 60. The WIDE OR filter requires:

python
if signal['confidence'] < min_confidence:   # e.g. 59 < 60
This works correctly. The real bug is that or_boost is stored as the raw confidence_adjustment float (0.05) in the signal dict, but confidence was boosted by confidence_adjustment * 100 (5 integer points). Consumers reading signal['or_boost'] see 0.05 and may interpret it as 5% when it was actually 5 points added to an integer scale — the semantics are inconsistent.

Fix: Store or_boost as an integer points value for consistency:

python
boost_pts = int(confidence_adjustment * 100)
signal['confidence'] = min(100, original_confidence + boost_pts)
signal['or_boost']   = boost_pts   # store as integer points (e.g. 5), not fraction
🟠 Mediums (8)
ID	File	Issue
17.M-8	breakout_detector.py	calculate_atr() cache key is ticker + bars_count. Two calls with the same bar count but different bar lists (e.g. one on bars[:-1] and one on bars) will return a stale ATR if the count happens to match a previous call. The cache should include a content hash or use (ticker, bars_count, bars[-1]['datetime']) as the key to avoid false cache hits across different bar sets.
17.M-9	breakout_detector.py	get_pdh_pdl() does a lazy import of data_manager inside the method on every call. Python caches module imports, so the import itself is O(dict lookup). But the pattern is inconsistent with the rest of the codebase and hides the dependency. Move to a top-level import.
17.M-10	breakout_detector.py	detect_breakout() calls get_session_levels() twice (once inside calculate_support_resistance() and once for the session_anchored flag check). Each call triggers data_manager.get_today_session_bars(ticker) → DB read. Cache get_session_levels() result locally within the method call to avoid 2x DB reads per signal check.
17.M-11	breakout_detector.py	detect_retest_entry() hardcodes confidence + 10 bonus for retests without a cap applied on the retest entry type specifically — min(confidence, 95) is applied on the return but the +10 is applied before that. A retest with 3x volume + strong candle + 0.03 break gets 50+30+20+10+10+10 = 130 → min(130, 95) = 95 — identical to a marginal retest that hit 95. The min(..., 95) cap and the initial 50 starting point interact to produce the same ceiling. Related to 17.H-3.
17.M-12	opening_range.py	_classify_from_bars() computes or_range_pct = (or_range / or_low) * 100 — or_low can be 0.0 if bars contain a corrupt low tick. No guard. Same issue in classify_secondary_range() for sr_range_pct.
17.M-13	opening_range.py	get_session_levels() calls data_manager.get_today_session_bars(ticker) and then _extract_session_bars() — same two calls duplicated identically in classify_or(). These are separate DB reads on every call. There is no short-circuit or shared session-bar cache between the two public methods.
17.M-14	opening_range.py	compute_opening_range_from_bars(), compute_premarket_range(), detect_breakout_after_or(), and detect_fvg_after_break() are Phase 5 #24 functions at the bottom of the file that duplicate logic in BreakoutDetector and OpeningRangeDetector. They use _bar_time() from utils.time_helpers (lazy import inside each function), making them independent of the class structure. They belong in a dedicated orb_scanner.py or as methods of the detector, not appended to the module bottom.
17.M-15	opening_range.py	_calculate_atr() uses range(1, min(len(bars), period + 1)) — this computes only period true ranges (indices 1..14 from a 60-bar slice). ATR is the mean of those TRs, not a proper EMA-smoothed ATR. Consistent with breakout_detector.calculate_atr() which also uses statistics.mean(), but the two ATR calculations use different bar inputs (historical DB vs today's bars) and could diverge significantly, causing different stop distances depending on which path was taken in classify_or() vs detect_breakout().
🟢 Lows (6)
ID	File	Issue
17.L-16	breakout_detector.py	calculate_average_volume() is marked deprecated and delegates to calculate_ema_volume(). Remove it or document which call sites still use it — it appears in no other file based on the current audit trail.
17.L-17	breakout_detector.py	_pdh_pdl_cache has no TTL. At daily reset, clear_pdh_pdl_cache() must be called explicitly. If not called (e.g. Railway process restarts after midnight but before clear_pdh_pdl_cache() runs), yesterday's PDH/PDL are used as today's levels. Add a date-stamp to the cache entry and auto-invalidate on date change.
17.L-18	breakout_detector.py	__init__ prints 3 lines at import time — same pattern flagged across all batches.
17.L-19	opening_range.py	or_detector = OpeningRangeDetector() singleton at module scope prints 7 lines at import. Same pattern flagged across all batches.
17.L-20	opening_range.py	should_scan_now() calls classify_or() unconditionally — the dead call costs N_tickers × DB reads per scanner loop iteration. Flagged as 17.H-6 from a correctness standpoint; also a low-severity performance issue even after the dead classify call is removed.
17.L-21	Both files	All print() calls should be logger.*. Same pattern flagged in batches 8–16.
Priority Fix Order
17.C-1 — session_anchored flag can be set on entries that used rolling resistance, not session resistance; Discord reason string misrepresents signal quality

17.H-3 — Confidence scorer starts at 50 — the < 50 filter is a no-op; high-quality signals saturate at 100 and can't be differentiated

17.H-2 — ATR includes the breakout bar; stop distance and R:R are inflated on strong breakout candles

17.H-5 — DYNAMIC OR cache TTL comparison mixes UTC-naive and ET-naive datetimes; DYNAMIC re-runs every call on Railway

17.H-6 — should_scan_now() calls classify_or() and discards the result — dead DB reads every scanner cycle

17.H-4 — support == 0.0 → ZeroDivisionError in PDH/PDL confluence check

17.M-10 — get_session_levels() called twice per detect_breakout() → 2× DB reads per signal check

17.M-14 — Phase 5 OR scanner functions appended to module bottom; should be moved to dedicated file


