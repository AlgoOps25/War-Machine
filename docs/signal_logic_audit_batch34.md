# Signal Logic Audit — Batch 34

**Date:** 2026-03-18
**Scope:** `app/signals/opening_range.py` (38 KB)
           `signal_analytics.py` deferred to Batch 35
**Total Findings:** 22 (0 Critical, 5 High, 10 Medium, 7 Low)

---

## `opening_range.py`

This is the most architecturally mature file audited so far. The Phase 1.17
and Phase B1 fix history in the docstring shows active, disciplined bug
tracking. The `_to_et_time()` helper is exactly the right abstraction.
The DYNAMIC TTL cache is well-designed. Criticals = 0.

---

## 🔴 Criticals (0)

The Phase B1 `$1336.72 for TSEM` price sanity clamp is correctly implemented.
The `_to_et_time()` UTC→ET conversion is correct. Cache eviction for DYNAMIC
entries is correct. No criticals.

---

## 🟡 Highs (5)

---

### 34.H-1 — `get_session_levels()` calls `data_manager.get_today_session_bars(ticker)` directly — **no caching**. This function is called from `breakout_detector.calculate_support_resistance()` and again from `breakout_detector.detect_breakout()` for the `session_anchored` flag (see 33.H-1). With 50 tickers × 12 scan cycles/minute, `get_session_levels()` performs **600+ `get_today_session_bars()` DB queries per minute** independently of `classify_or()`. `classify_or()` already caches its full result — but `get_session_levels()` bypasses that cache entirely and re-queries the DB each time. Fix: check `or_cache` first; if a cached OR result exists, derive `session_high`/`session_low` from `or_high`/`or_low`. If not cached, fall through to the full `_extract_session_bars()` path.

---

### 34.H-2 — `classify_or()` TTL comparison strips tzinfo from both sides before subtracting:

```python
if cached_at and (current_time.replace(tzinfo=None) - cached_at.replace(tzinfo=None)) < OR_CACHE_DYNAMIC_TTL:
current_time is datetime.now(ET) — a tz-aware ET datetime. cached_at is stored as current_time.replace(tzinfo=None) in _classify_from_bars() — a tz-naive datetime. Stripping tz from current_time before subtraction assumes both datetimes represent the same wall-clock timezone. This is correct as long as current_time is always ET. But if a caller passes a UTC datetime as current_time (which is valid — any tz-aware datetime works for _is_or_complete() etc.), the TTL comparison will be off by 4-5 hours. The comparison 14:35 UTC - 14:05 tz-naive yields timedelta(minutes=30) which appears to match the TTL but is comparing UTC against a tz-naive ET time. The fix is to store _cached_at as a full tz-aware ET datetime and always convert current_time to ET before comparison.

34.H-3 — classify_secondary_range() does from utils import config inside the method body — a deferred import run on every call before the sr_cache hit (if ticker in self.sr_cache: return happens before the config import, so cache hits are fine). Once the window closes and the cache is populated, subsequent calls return immediately. But the first call per ticker — during the 10:30 processing burst — triggers from utils import config for every ticker. On the first miss, this is a module-level import that resolves the utils.config module. Python caches the module after first import, so subsequent calls are fast (just a dict lookup in sys.modules). The real risk is that utils.config is imported at call time rather than declared at module top — a missing config module causes AttributeError at runtime inside a live signal path instead of at startup. from utils import config should be a module-level import.
34.H-4 — classify_secondary_range() early-exit check:
python
if (sr_range / sr_low) < config.SECONDARY_RANGE_MIN_PCT:
    ...return None
sr_low comes from min(b['low'] for b in sr_bars). If all bars in the secondary window have low = 0.0 (a data corruption edge case — a bar with a missing low field that defaults to 0), sr_low = 0 and this line raises ZeroDivisionError. The price sanity clamp earlier (b.get("low", 0) >= ref_price / SR_PRICE_SANITY_MULT) should catch most corruption, but a bar with low=0 exactly passes the sanity clamp when ref_price / 5 = 0 (impossible for a real stock). The division sr_range / sr_low needs a guard:

python
if sr_low <= 0 or (sr_range / sr_low) < config.SECONDARY_RANGE_MIN_PCT:
    return None
34.H-5 — or_detector = OpeningRangeDetector() at module level triggers __init__() which prints 7 lines to stdout on import. More importantly, __init__() sets up instance dicts (or_cache, alerts_sent, sr_cache) — no DB call, so no pool drain. However, or_detector is the module-level singleton. Any module that imports from app.signals.opening_range import get_session_levels (including breakout_detector.py) triggers OpeningRangeDetector.__init__() and its 7 print() calls at import time. On Railway where the process restarts on crash, these 7 lines appear in logs on every restart, polluting the log stream. Not a runtime bug, but should be logger.debug.
🟠 Mediums (10)
ID	Issue
34.M-6	_calculate_atr() is not cached — it's called by classify_or() → _classify_from_bars(), by should_alert_or_forming(), and by classify_secondary_range(). Each call runs data_manager.get_bars_from_memory(ticker, limit=60) (a DB query) then iterates up to 14 bars computing true ranges. With 50 tickers, the 9:40 OR classification burst fires 50 uncached get_bars_from_memory() queries. The ATR result does not change between classification calls within the same session. Should cache as self._atr_cache: Dict[str, float] and clear in clear_cache().
34.M-7	should_scan_now() computes the OR classification (or_data = self.classify_or(...)) and then returns True unconditionally — or_data is never used. The method is dead logic: regardless of OR classification, it always returns True. The docstring says "scan frequency handled by scanner loop" but the method is still called and wastes a cache lookup. Should either be removed or replaced with return True directly without the classify call.
34.M-8	adjust_signal_confidence() accesses signal['ticker'] directly without .get(). If a signal dict is passed without a ticker key (possible from legacy code paths that build partial signal dicts), this raises KeyError in the confidence adjustment path — silently bypassing the OR filter. Should use signal.get('ticker') with a None guard.
34.M-9	_classify_from_bars() stores _cached_at in the returned result dict. This means every consumer of classify_or() — including the sniper, signal formatter, and dashboard — receives a dict containing the internal _cached_at field. This is an implementation detail leaking into the public API. Should be stripped from the returned result or stored separately from the public result dict.
34.M-10	get_or_summary() calls self.classify_or(ticker, current_time) in a loop over all tickers. Each call acquires the cached result (fast), but if any ticker is not yet cached, it triggers data_manager.get_today_session_bars(ticker) — a DB query. At the dashboard print cadence (every 5 min), if any tickers fall off the cache (e.g., DYNAMIC expiry), get_or_summary() can trigger up to 50 DB queries in the dashboard print path. Should be a read-only cache summary — skip any ticker not in or_cache with a "pending" label rather than triggering live classification.
34.M-11	compute_opening_range_from_bars() and compute_premarket_range() are module-level functions added in "Phase 5 #24 — OR Scanner Functions extracted from sniper.py". Both use from utils.time_helpers import _bar_time — a deferred import inside a function body. _bar_time starts with an underscore, indicating it's a private helper. If time_helpers is refactored and _bar_time is renamed, this import silently breaks at runtime with ImportError. Should be imported at module top.
34.M-12	detect_breakout_after_or() and detect_fvg_after_break() are also Phase 5 extracts at module level. They import from utils import config inside the function body (same deferred-import risk as 34.H-3). detect_fvg_after_break() accesses config.FVG_MIN_SIZE_PCT — if this config key is renamed or missing, AttributeError fires inside a live detection path.
34.M-13	_extract_or_bars() has an optional end_time parameter used by should_alert_or_forming() to extract only up to 9:38. The filter is self.or_start_time <= bar_time < end_time. When end_time = time(9, 38), this includes bars from 9:30:00 up to 9:37:59. If should_alert_or_forming() is called at exactly 9:38:00, or_bars_so_far includes only 8 bars (9:30–9:37). The check len(or_bars_so_far) < 8 then passes on exactly 8 bars. The ATR ratio is computed on only 8 bars, which may not represent the full tight range if the 9:38 bar is the compression candle. The end_time should be inclusive: <= time(9, 38).
34.M-14	classify_secondary_range() price sanity clamp uses ref_price = float(np.median(closes)). With np imported at module top, this is fine. However, opening_range.py imports numpy at the top — this is the only numpy usage in the entire file (one np.median() call and one np.mean() in _calculate_atr()). For a file that otherwise uses only stdlib, the numpy dependency is heavyweight. Both calls can be replaced with statistics.median() and statistics.mean() from stdlib to eliminate the numpy dependency, consistent with breakout_detector.py which uses statistics.mean().
34.M-15	_classify_from_bars() returns None when atr is None or atr == 0. The caller classify_or() does not check for None return from _classify_from_bars() before caching:
python
return self._classify_from_bars(ticker, or_bars, ...)  # may be None
The None return propagates correctly to callers (they all handle None). But the None is not cached — so the next call re-triggers the full classification path including another _calculate_atr() DB query. With 50 tickers where some have no ATR data at session open, this means repeated uncached get_bars_from_memory() calls every scan cycle for those tickers. Should cache a sentinel {"classification": "NO_DATA"} on ATR failure and respect a short TTL for it.

🟢 Lows (7)
ID	Issue
34.L-16	__init__() prints 7 lines. All should be logger.info / logger.debug. Applies to all print() calls throughout the file (~25 total).
34.L-17	or_range_pct = (or_range / or_low) * 100 in _classify_from_bars() — same ZeroDivisionError risk as 34.H-4 if or_low = 0. Needs a if or_low > 0 guard. or_range_pct is logged and returned in the result dict but not used for classification decisions, so impact is print corruption rather than a logic error.
34.L-18	clear_cache() clears or_cache, alerts_sent, and sr_cache. It does not clear _atr_cache (because that cache doesn't exist yet — see 34.M-6). Once 34.M-6 is fixed and an ATR cache is added, clear_cache() must clear it too. Flag this as a pre-condition for 34.M-6 fix.
34.L-19	get_or_summary() uses or_data['or_range_atr'] with direct dict access in the label: f"{ticker} ({or_data['or_range_atr']:.2f}x ATR)". If or_data is returned from cache and happens to be missing this key (shouldn't happen given _classify_from_bars() always sets it, but defensive coding), this raises KeyError in the summary string. Use .get('or_range_atr', 0.0).
34.L-20	detect_breakout_after_or() logs with raw print(f"[BREAKOUT] BULL ..."). This function was extracted from sniper.py but still uses the [BREAKOUT] log prefix. After being moved to opening_range.py, the prefix should be [ORB] to distinguish from breakout_detector.py's [BREAKOUT] logs. Same for detect_fvg_after_break() → [ORB-FVG].
34.L-21	compute_premarket_range() requires len(pm_bars) < 10 to return None, None. On a slow pre-market day (low-float thinly traded), a stock may have only 6-8 pre-market bars at 9:25 and this returns None, None silently. No log message, no reason. Callers that use the premarket range for gap detection will silently get None without knowing whether it's "no data" or "insufficient data". Should log the bar count on early return.
34.L-22	The if __name__ == "__main__" block tests against test_ticker = "SPY" which requires a live data_manager DB connection. On a developer machine without Railway env vars, this crashes immediately on from app.data.data_manager import data_manager at the module top. Should wrap the __main__ block in a try/except with a friendly message.
Architecture Observation — OR as Session Level Provider
get_session_levels() is now called by breakout_detector.py as the canonical source of truth for session high/low, but it re-queries the DB on every call (34.H-1). The correct architecture is:

or_detector is the single session-level cache

get_session_levels() should read from or_cache if populated, DB only on first call

breakout_detector.detect_breakout() should receive pre-computed session levels as a parameter rather than calling get_session_levels() twice per tick (33.H-1)

This makes or_detector the true session state manager — which is exactly what it's designed to be — but requires threading the session levels through the call stack rather than re-fetching.

Priority Fix Order (Batch 34)
Rank	ID	Fix
1	34.H-1	get_session_levels() — serve from or_cache if populated; eliminate 600+ DB queries/min
2	34.M-6	Cache _calculate_atr() result per ticker; clear in clear_cache()
3	34.H-2	Store _cached_at as tz-aware ET datetime; eliminate tz-strip comparison bug
4	34.H-4	sr_low <= 0 guard before sr_range / sr_low division
5	34.H-3 / 34.M-12	Move all from utils import config to module-level imports
6	34.M-7	Remove dead or_data computation from should_scan_now()
7	34.M-15	Cache NO_DATA sentinel on ATR failure to prevent repeated uncached DB queries
8	34.M-8	signal.get('ticker') with None guard in adjust_signal_confidence()

**34.H-1 is the most impactful single finding in this batch** — `get_session_levels()` is called on every scan tick for every ticker with zero caching, generating 600+ DB queries per minute from the breakout detector alone. The fix is 3 lines: check `or_cache`, return derived levels if cached, otherwise proceed.

The OR module is overall the best-maintained file in the analytics/signals layer — the Phase B1 bug fix history shows real debugging discipline, and the `_to_et_time()` abstraction is the pattern every other file should follow for datetime handling.