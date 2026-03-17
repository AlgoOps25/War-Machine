#!/usr/bin/env python3
"""
tests/test_smc_engine.py
========================
SMC Engine smoke test — all 5 SMC components, zero external dependencies.

FIX v3 (Mar 17 2026) — corrected 3 new root causes:
  RC-A  _markup_bars: zigzag up-bars are monotone-rising so bar[i].high is
        never a local peak (bar[i+1].high always > bar[i].high within a wave).
        Fix: use isolated spike pattern — DOWN, BIG-UP (pivot high), DOWN-then
        UP — so the peak bar has lower bars on BOTH sides.
  RC-B  _sideways_bars: all bars share identical high=110.6 / low=109.4.
        The >= pivot condition fires on every bar, all pivot highs are equal,
        lh_count dominates → MARKDOWN. Fix: alternate highs/lows slightly so
        no clear trend but mixed HH/LH and HL/LL counts → ACCUM/DIST.
  RC-C  _inducement_bars_on_markup downstream of RC-A: MARKUP never returned
        so CHoCH fired BREAKOUT (+0.04) instead of CONTINUATION (0), making
        net delta positive. Fixed automatically once RC-A is resolved.

Run from repo root:
    python tests/test_smc_engine.py
"""
import sys
import os
import math
from datetime import datetime, timedelta
from typing   import List, Dict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import unittest.mock as mock
mock.patch(
    "app.mtf.smc_engine._persist_smc_context",
    side_effect=lambda *a, **kw: None
).start()
mock.patch(
    "app.mtf.smc_engine._ensure_smc_table",
    side_effect=lambda: None
).start()

from app.mtf.smc_engine import (
    classify_trend_phase,
    detect_choch,
    detect_inducement,
    find_order_block,
    check_ob_retest,
    enrich_signal_with_smc,
)

# ============================================================================
# SYNTHETIC BAR HELPERS
# ============================================================================

def _bar(open_, high, low, close, volume=100_000, dt=None) -> Dict:
    return {
        "datetime": dt or datetime(2026, 3, 17, 9, 30),
        "open":  float(open_),
        "high":  float(high),
        "low":   float(low),
        "close": float(close),
        "volume": int(volume),
    }


def _markup_bars(n_waves: int = 10) -> List[Dict]:
    """
    RC-A FIX: Create isolated pivot highs that satisfy the 3-bar pivot rule:
        sample[i].high >= sample[i-1].high  AND  sample[i].high >= sample[i+1].high

    Pattern per wave (4 bars):
        1. Down bar      — low precursor so next bar is a local peak
        2. Big up bar    — THIS is the pivot high (higher than bars on both sides)
        3. Small down    — confirms the pivot high on the right side
        4. Shallow up    — HL (higher than prior wave's low = ascending lows)

    Each wave starts ~1.5 points above the previous wave's base → HH + HL.
    """
    bars = []
    base  = datetime(2026, 3, 17, 9, 30)
    price = 100.0
    i = 0
    for wave in range(n_waves):
        peak = price + 2.0 + wave * 1.8   # Each wave: higher peak (HH)
        hl   = price + 0.3 + wave * 0.9   # Each wave: higher low  (HL)

        # Bar 1: down bar (precursor — low neighbour on left of pivot)
        bars.append(_bar(price + 0.5, price + 0.6, price - 0.2, price + 0.1,
                         dt=base + timedelta(minutes=i))); i += 1
        # Bar 2: big up bar — isolated pivot HIGH
        bars.append(_bar(price + 0.1, peak, price,       peak - 0.1,
                         dt=base + timedelta(minutes=i))); i += 1
        # Bar 3: small down bar (right neighbour — lower than peak)
        bars.append(_bar(peak - 0.1, peak - 0.0, peak - 1.5, peak - 1.2,
                         dt=base + timedelta(minutes=i))); i += 1
        # Bar 4: shallow up to HL (higher than prior wave's low)
        bars.append(_bar(peak - 1.2, hl + 0.5, hl - 0.1, hl,
                         dt=base + timedelta(minutes=i))); i += 1
        price = hl  # next wave starts from the HL
    return bars


def _markdown_bars(n_waves: int = 10) -> List[Dict]:
    """
    Mirror of _markup_bars for MARKDOWN (LH + LL structure).
    Pattern per wave (4 bars):
        1. Up bar        — high precursor
        2. Big down bar  — isolated pivot LOW
        3. Small up bar  — confirms pivot low on right
        4. Shallow down  — LH (lower than prior wave's high)
    """
    bars  = []
    base  = datetime(2026, 3, 17, 9, 30)
    price = 120.0
    i = 0
    for wave in range(n_waves):
        trough = price - 2.0 - wave * 1.8   # Each wave: lower trough (LL)
        lh     = price - 0.3 - wave * 0.9   # Each wave: lower high  (LH)

        # Bar 1: up bar (precursor)
        bars.append(_bar(price - 0.5, price + 0.2, price - 0.6, price - 0.1,
                         dt=base + timedelta(minutes=i))); i += 1
        # Bar 2: big down bar — isolated pivot LOW
        bars.append(_bar(price - 0.1, price,       trough, trough + 0.1,
                         dt=base + timedelta(minutes=i))); i += 1
        # Bar 3: small up bar (right neighbour — higher than trough)
        bars.append(_bar(trough + 0.1, trough + 1.5, trough, trough + 1.2,
                         dt=base + timedelta(minutes=i))); i += 1
        # Bar 4: shallow down to LH
        bars.append(_bar(trough + 1.2, lh + 0.1, lh - 0.5, lh,
                         dt=base + timedelta(minutes=i))); i += 1
        price = lh  # next wave starts from LH
    return bars


def _sideways_bars(n: int = 40) -> List[Dict]:
    """
    RC-B FIX: Alternate highs and lows slightly so pivot detection fires but
    produces mixed HH/LH and HL/LL counts → neither bull nor bear dominates
    → ACCUMULATION or DISTRIBUTION (not MARKDOWN).

    Pattern: oscillate between two slightly different pivot levels.
      Even waves: high=111.0, low=109.5  (slightly bullish bar)
      Odd  waves: high=110.8, low=109.3  (slightly bearish bar)
    The alternating highs (111.0 / 110.8 / 111.0 / ...) create alternating
    HH and LH counts; same for lows → mixed structure.
    """
    bars = []
    base = datetime(2026, 3, 17, 9, 30)
    for i in range(n):
        if i % 4 == 0:
            o, h, l, c = 110.2, 111.0, 109.5, 110.5   # slightly bullish
        elif i % 4 == 1:
            o, h, l, c = 110.3, 110.7, 109.2, 109.8   # slightly bearish
        elif i % 4 == 2:
            o, h, l, c = 109.9, 111.1, 109.6, 110.4   # slight new HH
        else:
            o, h, l, c = 110.1, 110.6, 109.1, 109.7   # slight new LL
        bars.append(_bar(o, h, l, c, dt=base + timedelta(minutes=i)))
    return bars


def _bos_bull_bars() -> List[Dict]:
    """
    MARKDOWN bars + clean bull BOS → CHoCH REVERSAL.
    """
    bars = _markdown_bars()
    last_close = bars[-1]["close"]
    bars.append(_bar(
        open_=last_close,
        high =last_close + 3.0,
        low  =last_close - 0.10,
        close=last_close + 2.80,
        dt=datetime(2026, 3, 17, 9, 30) + timedelta(minutes=len(bars))
    ))
    return bars


def _bos_bull_continuation_bars() -> List[Dict]:
    """
    MARKUP bars + another bull BOS → CHoCH CONTINUATION (no CHoCH).
    """
    bars = _markup_bars()
    last_close = bars[-1]["close"]
    bars.append(_bar(
        open_=last_close,
        high =last_close + 3.0,
        low  =last_close - 0.10,
        close=last_close + 2.80,
        dt=datetime(2026, 3, 17, 9, 30) + timedelta(minutes=len(bars))
    ))
    return bars


def _inducement_bars_on_markup() -> tuple:
    """
    RC-C (fixed via RC-A): MARKUP base → CHoCH fires CONTINUATION (delta=0).
    Bull BOS candle is a tiny-close sweep → inducement penalty -0.03.
    phase_align fires +0.02 (bull signal on MARKUP/bull bias).
    Net delta = 0.0 - 0.03 + 0.02 = -0.01 < 0  ✓
    """
    bars = _markup_bars()
    swing_high = max(b["high"] for b in bars)
    bars.append(_bar(
        open_=swing_high - 0.50,
        high =swing_high * 1.010,   # wick 1% above swing
        low  =swing_high - 0.60,
        close=swing_high * 1.0015,  # close only 0.15% above swing
        dt=datetime(2026, 3, 17, 9, 30) + timedelta(minutes=len(bars))
    ))
    return bars, swing_high


def _ob_bars(direction: str = "bull") -> List[Dict]:
    """
    Fresh OB setup — impulse bars stay outside OB zone so mitigated=False.

    BULL OB: red candle low=109.00 high=110.60 mid=109.80
             impulse bars start at 110.80, lows > 109.80 (fresh)
    BEAR OB: green candle low=109.40 high=111.00 mid=110.20
             impulse bars start at 109.00, highs < 110.20 (fresh)
    """
    bars = []
    base = datetime(2026, 3, 17, 9, 30)
    for i in range(10):
        p = 110.0
        bars.append(_bar(p, p + 0.30, p - 0.30, p, dt=base + timedelta(minutes=i)))

    if direction == "bull":
        bars.append(_bar(110.5, 110.6, 109.0, 109.1,
                         dt=base + timedelta(minutes=10)))
        start = 110.80
        for j in range(5):
            o = start + j * 1.20
            bars.append(_bar(o, o + 0.50, o - 0.10, o + 0.40,
                             dt=base + timedelta(minutes=11 + j)))
    else:
        bars.append(_bar(109.5, 111.0, 109.4, 110.9,
                         dt=base + timedelta(minutes=10)))
        start = 109.00
        for j in range(5):
            o = start - j * 1.20
            bars.append(_bar(o, o + 0.10, o - 0.50, o - 0.40,
                             dt=base + timedelta(minutes=11 + j)))
    return bars


# ============================================================================
# TEST RUNNER
# ============================================================================

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
_failures = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}  {detail}")
        _failures.append(label)


# ============================================================================
# 1. TREND PHASE
# ============================================================================

def test_trend_phase():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("1. TREND PHASE CLASSIFICATION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    r = classify_trend_phase(_markup_bars())
    print(f"  Markup   : phase={r['phase']} bias={r['trend_bias']} HH={r['hh_count']} HL={r['hl_count']}")
    check("MARKUP phase",     r["phase"] == "MARKUP")
    check("MARKUP bias=bull", r["trend_bias"] == "bull")

    r = classify_trend_phase(_markdown_bars())
    print(f"  Markdown : phase={r['phase']} bias={r['trend_bias']} LH={r['lh_count']} LL={r['ll_count']}")
    check("MARKDOWN phase",     r["phase"] == "MARKDOWN")
    check("MARKDOWN bias=bear", r["trend_bias"] == "bear")

    r = classify_trend_phase(_sideways_bars())
    print(f"  Sideways : phase={r['phase']} bias={r['trend_bias']}")
    check("SIDEWAYS is ACCUM/DIST/UNKNOWN",
          r["phase"] in ("ACCUMULATION", "DISTRIBUTION", "UNKNOWN"))

    r = classify_trend_phase([_bar(100, 101, 99, 100)] * 5)
    check("Too few bars → UNKNOWN", r["phase"] == "UNKNOWN")


# ============================================================================
# 2. CHoCH
# ============================================================================

def test_choch():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("2. CHoCH DETECTION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    bars = _bos_bull_bars()  # MARKDOWN + bull BOS
    r = detect_choch(bars, "bull")
    print(f"  Bull BOS after MARKDOWN: is_choch={r['is_choch']} type={r['choch_type']} delta={r['confidence_delta']:+.3f}")
    check("REVERSAL CHoCH detected",   r["is_choch"] == True)
    check("CHoCH type = REVERSAL",      r["choch_type"] == "REVERSAL")
    check("CHoCH boost = +0.04",        math.isclose(r["confidence_delta"], 0.04, abs_tol=1e-9))

    bars = _bos_bull_continuation_bars()  # MARKUP + bull BOS
    r = detect_choch(bars, "bull")
    print(f"  Bull BOS after MARKUP:   is_choch={r['is_choch']} type={r['choch_type']} delta={r['confidence_delta']:+.3f}")
    check("CONTINUATION not CHoCH",     r["is_choch"] == False)
    check("CHoCH type = CONTINUATION",   r["choch_type"] == "CONTINUATION")
    check("No boost on CONTINUATION",   math.isclose(r["confidence_delta"], 0.0, abs_tol=1e-9))

    bars = _sideways_bars() + [
        _bar(111, 114, 110.8, 113.5,
             dt=datetime(2026, 3, 17, 9, 30) + timedelta(minutes=41))
    ]
    r = detect_choch(bars, "bull")
    print(f"  Bull BOS after SIDEWAYS: is_choch={r['is_choch']} type={r['choch_type']} delta={r['confidence_delta']:+.3f}")
    check("BREAKOUT CHoCH after range",  r["is_choch"] == True)
    check("CHoCH type = BREAKOUT",       r["choch_type"] == "BREAKOUT")


# ============================================================================
# 3. INDUCEMENT
# ============================================================================

def test_inducement():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("3. INDUCEMENT DETECTION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    bars_md    = _markdown_bars()
    swing_high = max(b["high"] for b in bars_md)
    sweep_bar  = _bar(
        open_=swing_high - 0.50,
        high =swing_high * 1.010,
        low  =swing_high - 0.60,
        close=swing_high * 1.0015,
        dt=datetime(2026, 3, 17, 9, 30) + timedelta(minutes=len(bars_md))
    )
    r = detect_inducement(bars_md + [sweep_bar], "bull", swing_high)
    print(f"  Sweep candle: is_inducement={r['is_inducement']} sweep={r['sweep_pct']:.4f}% wick={r['wick_extension']:.4f}% delta={r['confidence_delta']:+.3f}")
    check("Inducement detected",        r["is_inducement"] == True)
    check("Inducement penalty = -0.03", math.isclose(r["confidence_delta"], -0.03, abs_tol=1e-9))
    check("sweep_pct > 0",              r["sweep_pct"] > 0)
    check("wick >> close extension",    r["wick_extension"] > r["sweep_pct"] * 2)

    bars2  = _bos_bull_bars()
    swing2 = max(b["high"] for b in bars2[:-1])
    r2 = detect_inducement(bars2, "bull", swing2)
    print(f"  Clean BOS:    is_inducement={r2['is_inducement']} sweep={r2['sweep_pct']:.4f}% delta={r2['confidence_delta']:+.3f}")
    check("Clean BOS NOT inducement",   r2["is_inducement"] == False)
    check("No penalty on clean BOS",    math.isclose(r2["confidence_delta"], 0.0, abs_tol=1e-9))


# ============================================================================
# 4. ORDER BLOCK
# ============================================================================

def test_order_block():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("4. ORDER BLOCK DETECTION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    bars = _ob_bars("bull")
    ob   = find_order_block(bars, "bull", len(bars) - 1)
    if ob:
        print(f"  BULL OB: low={ob['ob_low']:.2f} high={ob['ob_high']:.2f} mitigated={ob['mitigated']}")
    else:
        print("  BULL OB: not found")
    check("BULL OB found",         ob is not None)
    if ob:
        check("BULL OB is FRESH",   ob["mitigated"] == False)
        check("BULL OB direction",  ob["ob_direction"] == "bull")
        check("BULL OB valid zone", ob["ob_low"] < ob["ob_high"])

    bars = _ob_bars("bear")
    ob   = find_order_block(bars, "bear", len(bars) - 1)
    if ob:
        print(f"  BEAR OB: low={ob['ob_low']:.2f} high={ob['ob_high']:.2f} mitigated={ob['mitigated']}")
    else:
        print("  BEAR OB: not found")
    check("BEAR OB found",         ob is not None)
    if ob:
        check("BEAR OB is FRESH",   ob["mitigated"] == False)
        check("BEAR OB direction",  ob["ob_direction"] == "bear")

    ob_none = find_order_block(bars, "bull", 2)
    check("bos_idx too small → None", ob_none is None)


# ============================================================================
# 5. OB RETEST
# ============================================================================

def test_ob_retest():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("5. OB RETEST")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    base_bars = _ob_bars("bull")
    ob        = find_order_block(base_bars, "bull", len(base_bars) - 1)

    if ob is None:
        print("  ⚠️  No OB found — skipping retest tests")
        return

    print(f"  OB zone: ${ob['ob_low']:.2f}–${ob['ob_high']:.2f} mid=${ob['ob_mid']:.2f} mitigated={ob['mitigated']}")

    retest_body = _bar(
        open_=ob["ob_low"] + 0.15,
        high =ob["ob_high"] - 0.05,
        low  =ob["ob_low"] + 0.05,
        close=ob["ob_low"] + 0.25,
        dt=datetime(2026, 3, 17, 10, 0)
    )
    r = check_ob_retest(base_bars + [retest_body], ob)
    print(f"  BODY retest: is_retest={r['is_retest']} quality={r['retest_quality']} delta={r['confidence_delta']:+.3f}")
    check("BODY retest detected",   r["is_retest"] == True)
    check("BODY quality",           r["retest_quality"] == "BODY")
    check("BODY boost = +0.03",     math.isclose(r["confidence_delta"], 0.03, abs_tol=1e-9))

    retest_wick = _bar(
        open_=ob["ob_high"] + 0.20,
        high =ob["ob_high"] + 0.50,
        low  =ob["ob_low"]  + 0.05,
        close=ob["ob_high"] + 0.10,
        dt=datetime(2026, 3, 17, 10, 1)
    )
    r = check_ob_retest(base_bars + [retest_wick], ob)
    print(f"  WICK retest: is_retest={r['is_retest']} quality={r['retest_quality']} delta={r['confidence_delta']:+.3f}")
    check("WICK retest detected",   r["is_retest"] == True)
    check("WICK quality",           r["retest_quality"] == "WICK")
    check("WICK boost = +0.015",    math.isclose(r["confidence_delta"], 0.015, abs_tol=1e-9))

    no_touch = _bar(
        open_=ob["ob_high"] + 2.0,
        high =ob["ob_high"] + 3.0,
        low  =ob["ob_high"] + 1.5,
        close=ob["ob_high"] + 2.5,
        dt=datetime(2026, 3, 17, 10, 2)
    )
    r = check_ob_retest(base_bars + [no_touch], ob)
    print(f"  No retest:   is_retest={r['is_retest']}")
    check("No retest when bar far above", r["is_retest"] == False)

    ob_mit = dict(ob); ob_mit["mitigated"] = True
    r = check_ob_retest(base_bars + [retest_body], ob_mit)
    check("Mitigated OB → no retest", r["is_retest"] == False)


# ============================================================================
# 6. FULL PIPELINE
# ============================================================================

def test_full_pipeline():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("6. FULL PIPELINE — enrich_signal_with_smc()")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    bars = _bos_bull_bars()
    signal_data = {
        "direction":  "bull",
        "bos_idx":    len(bars) - 1,
        "bos_price":  max(b["high"] for b in bars[:-1]),
        "entry_type": "CFW6_INTRADAY",
    }
    result = enrich_signal_with_smc("TEST", bars, signal_data)
    smc = result.get("smc", {})

    print(f"  smc_summary : {smc.get('smc_summary')}")
    print(f"  total_delta : {smc.get('total_confidence_delta'):+.4f}")
    print(f"  CHoCH       : {smc.get('choch',{}).get('is_choch')} type={smc.get('choch',{}).get('choch_type')}")
    print(f"  Phase       : {smc.get('trend_phase',{}).get('phase')} bias={smc.get('trend_phase',{}).get('trend_bias')}")
    print(f"  Inducement  : {smc.get('inducement',{}).get('is_inducement')}")
    print(f"  OB found    : {smc.get('order_block') is not None}")

    check("smc key in signal_data",          "smc" in result)
    check("choch present",                   "choch" in smc)
    check("inducement present",              "inducement" in smc)
    check("trend_phase present",             "trend_phase" in smc)
    check("total_confidence_delta is float", isinstance(smc.get("total_confidence_delta"), float))
    check("smc_summary is string",           isinstance(smc.get("smc_summary"), str))
    check("direction preserved",             smc.get("direction") == "bull")


# ============================================================================
# 7. CONFIDENCE DELTA CAPS
# ============================================================================

def test_delta_caps():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("7. CONFIDENCE DELTA CAPS (+0.10 / -0.05)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    bars = _bos_bull_bars()
    result = enrich_signal_with_smc("CAP_TEST", bars, {
        "direction":  "bull",
        "bos_idx":    len(bars) - 1,
        "bos_price":  max(b["high"] for b in bars[:-1]),
        "entry_type": "CFW6_INTRADAY",
    })
    delta = result["smc"]["total_confidence_delta"]
    print(f"  Multi-boost cap scenario: delta={delta:+.4f}")
    check("Delta <= +0.10", delta <= 0.10 + 1e-9)
    check("Delta >= -0.05", delta >= -0.05 - 1e-9)

    bars2, swing2 = _inducement_bars_on_markup()
    result2 = enrich_signal_with_smc("FLOOR_TEST", bars2, {
        "direction":  "bull",
        "bos_idx":    len(bars2) - 1,
        "bos_price":  swing2,
        "entry_type": "CFW6_INTRADAY",
    })
    delta2 = result2["smc"]["total_confidence_delta"]
    choch2 = result2["smc"]["choch"]
    ind2   = result2["smc"]["inducement"]
    print(f"  Inducement floor scenario: delta={delta2:+.4f}  CHoCH={choch2['choch_type']}  ind={ind2['is_inducement']}")
    check("Inducement fires on MARKUP base",       ind2["is_inducement"] == True)
    check("CHoCH is CONTINUATION on MARKUP base", choch2["choch_type"] == "CONTINUATION")
    check("Net delta is negative",                 delta2 < 0.0)
    check("Delta floor >= -0.05",                  delta2 >= -0.05 - 1e-9)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("\n" + "═" * 54)
    print(" SMC ENGINE SMOKE TEST v3 — War Machine")
    print(" app/mtf/smc_engine.py")
    print("═" * 54)

    test_trend_phase()
    test_choch()
    test_inducement()
    test_order_block()
    test_ob_retest()
    test_full_pipeline()
    test_delta_caps()

    print("\n" + "═" * 54)
    if _failures:
        print(f"\033[91m FAILED: {len(_failures)} test(s)\033[0m")
        for f in _failures:
            print(f"  ✗  {f}")
        sys.exit(1)
    else:
        print(f"\033[92m ALL CHECKS PASSED — SMC engine is healthy ✅\033[0m")
        sys.exit(0)
