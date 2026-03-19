# Signal Logic Audit — Batch 33

**Date:** 2026-03-18
**Scope:** `app/signals/` — directory inventory + deep audit of
           `breakout_detector.py` (32 KB)
           `opening_range.py` and `signal_analytics.py` deferred to Batch 34
**Total Findings:** 20 (0 Critical, 5 High, 9 Medium, 6 Low)

---

## Layer Inventory

| File | Size | Notes |
|------|------|-------|
| `__init__.py` | 32 B | Empty |
| `breakout_detector.py` | 32 KB | ✅ This batch |
| `opening_range.py` | 38 KB | Batch 34 |
| `signal_analytics.py` | 32 KB | Batch 34 |

---

## `breakout_detector.py`

No DB access, no pool connections, no imports at module level (all deferred
inside methods). Clean pure-Python signal logic. This shifts the risk profile
from infrastructure bugs to **signal correctness bugs**.

---

## 🔴 Criticals (0)

The core bull/bear detection gates (`close > resistance`, `volume_ratio >= multiplier`,
candle direction + strength) are all correctly applied. T1/T2 math is correct:
`stop = entry - atr * mult`, `risk = entry - stop`, `t1 = entry + risk * 1.5`,
`t2 = entry + risk * 2.5`. No division-by-zero in risk_reward because
`risk` is `atr * mult > 0` (guarded by `atr == 0` early exit). No criticals.

---

## 🟡 Highs (5)

---

### 33.H-1 — `calculate_support_resistance()` passes `bars[:-1]` to exclude the current bar when computing resistance. Then `detect_breakout()` computes session anchoring **again** by calling `get_session_levels(ticker)` a second time — with a fresh `from app.signals.opening_range import get_session_levels` import inline. This means `opening_range.get_session_levels()` is called **twice per `detect_breakout()` call**:

```python
# Call 1 — inside calculate_support_resistance()
from app.signals.opening_range import get_session_levels
session = get_session_levels(ticker)
...resistance = session_high

# Call 2 — inside detect_breakout() for session_anchored flag
from app.signals.opening_range import get_session_levels
session = get_session_levels(ticker)
session_anchored = (abs(resistance - session['session_high']) < 0.01 ...)
get_session_levels() is not shown here but lives in opening_range.py (38 KB, Batch 34). If it queries the DB or does non-trivial computation, this double-call is wasteful on every scan tick for every ticker. With 50 tickers × 12 scans/minute = 1,200 get_session_levels() calls/minute, doubled to 2,400. Fix: return session_anchored from calculate_support_resistance() as part of a named tuple or second return value so detect_breakout() can reuse the result.

33.H-2 — calculate_support_resistance() PDH/PDL confluence logic has an asymmetric tolerance bug:
python
# Resistance confluence — tolerance is 2% of resistance
if abs(pdh - resistance) / resistance < 0.02:
    resistance = pdh

# Support confluence — tolerance is 2% of support
if abs(pdl - support) / support < 0.02:
    support = pdl
When PDH confluence fires, resistance is replaced by PDH. If PDH is below intraday_resistance (e.g., PDH=$150 but today's rolling high=$153), resistance is lowered to $150. The breakout condition latest['close'] > resistance now triggers at $150 instead of $153 — generating a false signal. The intent is presumably to use PDH as confluence only when PDH is above or near rolling resistance, not to lower resistance below it. Should be:

python
if pdh is not None and pdh > resistance and abs(pdh - resistance) / resistance < 0.02:
    resistance = pdh  # only elevate resistance to PDH, never lower it
Same directional guard needed for PDL support.

33.H-3 — calculate_ema_volume() seeds the EMA with lookback[0]['volume'] (the oldest bar in the window) and iterates forward. This is correct EMA initialization. However, the lookback slice is:
python
lookback = bars[-period:] if len(bars) >= period else bars
In detect_breakout(), the call is self.calculate_ema_volume(bars[:-1]) — i.e., the current bar is excluded from the volume EMA. If bars[:-1] has fewer bars than period (e.g., at 9:35 with only 5 bars available), the EMA uses all 5 bars. Fine. But then volume_ratio = current_volume / ema_volume uses the current bar's volume against an EMA that included only the first few minutes of the session. At 9:31 with 1 prior bar, the EMA is just the 9:30 volume. If 9:30 was a high-volume open bar, the EMA is very high and volume_ratio will be < 1 for most subsequent bars — suppressing valid early-session breakouts. Conversely, if 9:30 was low volume, any 9:31 spike will show 3x+ ratio. The EMA needs a minimum warm-up period (e.g., if len(bars) < 5: return None or use a pre-market volume baseline as the EMA seed).

33.H-4 — _calculate_confidence() starts at a base of 50 and adds only positive scores. The minimum returned value for any signal that reaches this function is therefore 50. The confidence gate if confidence < 50: return None immediately after the call can never trigger — a signal with volume_ratio=2.0 exactly (minimum to pass the volume gate), zero breakout strength bonus, high ATR, weak candle, and no confluence still scores 50 + 10 = 60. The gate at < 50 is unreachable dead code. To be meaningful the gate threshold should be at least 60, or the base score should be 0 with all points additive.
33.H-5 — detect_retest_entry() hardcodes a +10 confidence bonus unconditionally for any retest signal:
python
confidence = self._calculate_confidence(...) + 10
A retest with volume_ratio=1.5 (the minimum), weak candle body, no PDH confluence, and minimum breakout_strength scores: 50 + 0 (vol<2x) + 15 (0.02 strength) + 0 + 3 (body 0.4) + 10 (bonus) = 78. That's a 78% confidence retest signal from what is essentially a minimum-quality setup. The +10 bonus is meant to reward the higher-probability nature of retest entries, but it inflates scores across the board including marginal setups. The bonus should only apply when volume_ratio >= 2.0 and candle_strength['body_pct'] >= 0.5.

🟠 Mediums (9)
ID	Issue
33.M-6	calculate_atr() caches by bars_count — the cache invalidates when the bar count changes (a new bar arrives). With 50 tickers × 12 scan cycles/minute, the ATR is recomputed from scratch every cycle for every ticker regardless of how little price action has changed. The correct cache key should be (ticker, bars[-1]['datetime']) — cache the ATR until the latest bar's timestamp changes. This avoids iterating len(bars) true ranges on every call.
33.M-7	calculate_support_resistance() computes intraday_resistance = max(bar['high'] for bar in lookback) and intraday_support = min(bar['low'] for bar in lookback). These are called with bars[:-1] (current bar excluded). If lookback_bars=20 and only 15 bars are available, the full 15 bars are used. Fine. But if bars[:-1] is passed in and has only 1 bar (session just opened), intraday_resistance and intraday_support are both from a single bar. The session-anchoring then potentially replaces them with session_high/session_low which are the same bar. Result: resistance == support == open_price. The breakout condition close > resistance can fire immediately on any upward move in the first 2 minutes. Should enforce a minimum of max(self.lookback_bars // 4, 5) bars before running detection.
33.M-8	analyze_candle_strength() computes has_rejection for bull candles as lower_wick / total_range > 0.4. A candle with a 40% lower wick is flagged as having rejection — but this is computed and returned in the dict without affecting the signal gate. has_rejection is never checked in detect_breakout() or detect_retest_entry(). It is in the returned dict but no downstream consumer appears to read it. Either remove it from the returned dict or gate on it: a bull breakout bar with a 40%+ lower wick does indicate indecision and arguably should reduce confidence or block the signal.
33.M-9	_calculate_confidence() ATR scoring: if atr_pct < 0.02: +10 means lower ATR = more confident. But a very low ATR (tight, low-volatility stock) combined with a breakout that is only 1% above resistance (breakout_strength=0.01) already scores 50 + 10 + 10 + 10 = 80 with zero volume bonus. Low-volatility, low-volume breakouts can score as high as high-volatility, high-volume breakouts due to this ATR scoring direction. ATR should score neutral (0 bonus) below a floor; only penalize unusually high ATR (wide, choppy action).
33.M-10	detect_breakout() — the min_bars_since_breakout > 0 confirmation logic checks all(bar['close'] <= resistance for bar in recent_bars). This means: "signal only if ALL recent bars closed below resistance before this bar broke out." But if any single bar in the lookback window briefly closed above resistance (a failed breakout attempt), the confirmation fires and the signal is blocked. The intended logic is the opposite: "only signal if the previous N bars failed to break, i.e. all closed below." The current code is actually correct — but only if min_bars_since_breakout=1. With min_bars_since_breakout=2, it requires the last 2 bars to have failed — which is a valid swing-mode confirmation. The default of 0 bypasses this entirely (first-break mode), which is correct for 0DTE. No bug, but this logic needs explicit documentation because it reads counter-intuitively.
33.M-11	_pdh_pdl_cache never expires intraday. The cache is populated once per ticker and never invalidated until clear_pdh_pdl_cache() is explicitly called. If clear_pdh_pdl_cache() is not called at EOD by the scheduler, stale PDH/PDL values persist across session boundaries on Railway (process doesn't restart daily). Next morning's PDH = yesterday's PDH = two-day-old levels. The cache should auto-expire at midnight ET using a _pdh_pdl_date guard similar to funnel_tracker._reset_daily_if_needed().
33.M-12	get_pdh_pdl() does from app.data.data_manager import data_manager inside the method body — a deferred import that runs on every cache miss. After the first call per ticker, the cache hits and the import is skipped. Fine. But on first call per ticker (50 tickers × session start), 50 deferred imports of data_manager are triggered in rapid succession. Python's import system is locked during import (GIL + importlib lock), so concurrent threads calling get_pdh_pdl() for different tickers simultaneously will serialize on the import lock. The import should be moved to module level or cached at class level after the first resolution.
33.M-13	calculate_support_resistance() session-anchoring tolerance for "near session high" is hardcoded 0.005 (0.5%). For a $500 stock (SPY), 0.5% = $2.50 buffer. For a $10 stock (small-cap), 0.5% = $0.05 — too tight to be useful. The tolerance should scale with ATR, not price percentage. near_threshold = atr * 0.25 would be more robust across different price ranges.
33.M-14	format_signal_message() is a module-level function (not a method) that formats for Discord. It accesses signal['risk_reward'] directly without .get() — if any caller constructs a partial signal dict without risk_reward (e.g., from a legacy code path), this raises KeyError. All dict accesses in format_signal_message() should use .get() with safe defaults.
🟢 Lows (6)
ID	Issue
33.L-15	BreakoutDetector.__init__() prints 3 lines on instantiation. The singleton is created once per process, so this is a one-time cost — but it fires on every import if the module creates an instance at module level (it doesn't; the caller instantiates). Still should use logger.info instead of print.
33.L-16	calculate_average_volume() is marked Deprecated: kept for backwards compat. Calls calculate_ema_volume(). No DeprecationWarning is raised. Any caller using calculate_average_volume() gets the EMA silently instead of the SMA they might expect. Should raise DeprecationWarning.
33.L-17	detect_breakout() returns a dict with both 'target': round(t2_price, 2) and 't2': round(t2_price, 2) — target and t2 are identical values. target is the legacy field kept for backwards compatibility. format_signal_message() uses t1 and t2 when present, else falls back to target. The duplicate key wastes space in every signal dict and could confuse a consumer that reads target expecting T1. Should remove target and update all callers to use t2.
33.L-18	_calculate_confidence() has no docstring explaining the scoring ranges or what 50 base means. Any developer tuning thresholds must reverse-engineer the scoring table by reading the code. Add a scoring table comment.
33.L-19	calculate_position_size() uses integer truncation (int(risk_amount / risk_per_share)). For a $50,000 account risking 1% with a $0.50 stop, this returns 1,000 shares. For a $500 account risking 1%, result is int(5/0.50) = 10 shares. Correct. But for fractional share brokers (Tradier supports this), truncation discards up to risk_per_share - $0.01 in risk capacity. Consider round() instead of int().
33.L-20	The if __name__ == "__main__" block at the bottom runs a 21-bar sample that incrementally builds price from $100 to $114 — all bars have progressively increasing volume from 1.0M to 1.3M then back to 1.0M before the breakout bar at 2.7M. The EMA volume baseline will be approximately 1.05M, so volume_ratio = 2.7M / 1.05M ≈ 2.57x — passes the 2.0x minimum. The sample correctly demonstrates the detection. However, all bar datetime values are datetime.now() — identical timestamps. Any code path that keys on datetime for deduplication (e.g., signal_analytics.py) would treat all 21 bars as the same instant. Sample data should use incremental timestamps.
Signal Correctness Summary
The core detection logic is structurally sound — the Phase 1.17 session-anchoring is a good architectural decision and the T1/T2 split target math is correct. The main correctness risk is:

33.H-2 — PDH/PDL can silently lower resistance below the rolling intraday high, generating false bull breakouts when price is still below the session resistance. This is an active signal quality degradation.

33.H-4 — The confidence gate at < 50 is unreachable; every signal that reaches scoring passes. The effective minimum is ~60 but the gate doesn't enforce it explicitly.

33.H-3 — EMA volume seeded too early in the session inflates volume ratios at open and suppresses them mid-session.

Priority Fix Order (Batch 33)
Rank	ID	Fix
1	33.H-2	PDH/PDL directional guard — prevent resistance from being lowered below rolling intraday high
2	33.H-4	Move confidence gate threshold from < 50 to < 60 (or set base to 0)
3	33.H-3	Add minimum warm-up bar guard before EMA volume is trusted (len(bars) < 5 → skip)
4	33.H-1	Cache get_session_levels() result within detect_breakout() — eliminate double-call
5	33.M-11	Auto-expire _pdh_pdl_cache at midnight ET to prevent stale cross-session levels
6	33.M-6	Cache ATR by (ticker, last_bar_datetime) instead of bars_count
7	33.M-7	Enforce minimum bar count before running detection (avoid single-bar resistance = support)
8	33.H-5	Gate retest confidence +10 bonus on volume ≥ 2.0x and candle body ≥ 0.5

**33.H-2 is the most impactful signal correctness bug found to date outside the data layer** — PDH/PDL confluence silently lowers resistance below the day's rolling high in certain conditions, meaning the breakout trigger fires before price has actually broken anything meaningful. A $152 stock with a rolling high of $153 and PDH of $150 would have resistance set to $150, making any close above $150 a "breakout" — but price was already above PDH all morning. The fix is one directional comparison added to each PDH/PDL block.