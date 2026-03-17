#!/usr/bin/env python3
"""
tests/test_smc_engine.py
========================
SMC Engine smoke test — all 5 SMC components, zero external dependencies.

FIX v2 (Mar 17 2026) — corrected 3 root causes:
  RC-1  _markup_bars / _markdown_bars used monotone staircases — the 3-bar
        pivot detector requires actual local highs/lows. Replaced with a
        zigzag staircase (2 up + 1 pullback repeating) that produces real
        HH/HL (MARKUP) and LH/LL (MARKDOWN) pivots.
  RC-2  Downstream of RC-1: CHoCH was always BREAKOUT because phase came
        back UNKNOWN/neutral. Fixed by fixing bars.
  RC-3  _ob_bars() impulse lows dropped below OB mid immediately after the
        OB candle, marking it mitigated=True. Fixed by making impulse bars
        whose lows stay above the OB zone.
  RC-4  OB retest tests all failed because OB was mitigated (downstream RC-3).
  RC-5  Inducement floor test: CHoCH +0.04 overpowered inducement -0.03 →
        delta=+0.01. Fixed by using a MARKUP base so CHoCH fires CONTINUATION
        (delta=0), leaving only the inducement penalty.

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
    RC-1 FIX: Zigzag staircase that creates real 3-bar pivot highs/lows.
    Pattern: 2 up bars (HH) + 1 pullback bar (HL) repeated n_waves times.
    Guarantees HH+HL structure → classify_trend_phase returns MARKUP.
    """
    bars = []
    base = datetime(2026, 3, 17, 9, 30)
    price = 100.0
    i = 0
    for _ in range(n_waves):
        # Up bar 1
        bars.append(_bar(price, price + 1.2, price - 0.1, price + 1.0, dt=base + timedelta(minutes=i)))
        price += 1.0; i += 1
        # Up bar 2 (new HH)
        bars.append(_bar(price, price + 1.3, price - 0.1, price + 1.1, dt=base + timedelta(minutes=i)))
        price += 1.1; i += 1
        # Pullback bar (HL — stays above prior HL)
        bars.append(_bar(price, price + 0.3, price - 0.4, price - 0.3, dt=base + timedelta(minutes=i)))
        price -= 0.3; i += 1
    return bars


def _markdown_bars(n_waves: int = 10) -> List[Dict]:
    """
    RC-1 FIX: Zigzag staircase creating real 3-bar pivot lows (LH+LL).
    Pattern: 2 down bars (LL) + 1 bounce bar (LH) repeated n_waves times.
    """
    bars = []
    base = datetime(2026, 3, 17, 9, 30)
    price = 120.0
    i = 0
    for _ in range(n_waves):
        # Down bar 1
        bars.append(_bar(price, price + 0.1, price - 1.2, price - 1.0, dt=base + timedelta(minutes=i)))
        price -= 1.0; i += 1
        # Down bar 2 (new LL)
        bars.append(_bar(price, price + 0.1, price - 1.3, price - 1.1, dt=base + timedelta(minutes=i)))
        price -= 1.1; i += 1
        # Bounce bar (LH — stays below prior LH)
        bars.append(_bar(price, price + 0.4, price - 0.1, price + 0.3, dt=base + timedelta(minutes=i)))
        price += 0.3; i += 1
    return bars


def _sideways_bars(n: int = 35) -> List[Dict]:
    """Tight range oscillation — ACCUMULATION / DISTRIBUTION."""
    bars = []
    for i in range(n):
        side  = 1 if i % 2 == 0 else -1
        open_ = 110.0 + side * 0.10
        high  = 110.6
        low   = 109.4
        close = 110.0 - side * 0.10
        bars.append(_bar(open_, high, low, close,
                         dt=datetime(2026, 3, 17, 9, 30) + timedelta(minutes=i)))
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
    RC-5 FIX: Use MARKUP base so CHoCH fires CONTINUATION (delta=0).
    Then the bull BOS candle is a tiny-close sweep → inducement penalty -0.03.
    Net delta = 0.0 + (-0.03) + phase_align(+0.02) = -0.01 < 0  ✓

    (phase_align fires because direction=bull and markup trend_bias=bull)
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
    RC-3 FIX: Impulse bars after the OB candle must have lows that stay
    ABOVE the OB zone so mitigated=False.

    BULL:
      OB candle: red, low=109.00, high=110.60, mid=109.80
      Impulse bars: open starts at 110.80 (above OB high), rising.
                    low = open - 0.10 → always > 109.80. Fresh OB.

    BEAR:
      OB candle: green, low=109.40, high=111.00, mid=110.20
      Impulse bars: open starts at 109.00 (below OB low), falling.
                    high = open + 0.10 → always < 110.20. Fresh OB.
    """
    bars = []
    base = datetime(2026, 3, 17, 9, 30)
    for i in range(10):
        p = 110.0
        bars.append(_bar(p, p + 0.30, p - 0.30, p, dt=base + timedelta(minutes=i)))

    if direction == "bull":
        # OB: big red candle, mid = (109.00+110.60)/2 = 109.80
        bars.append(_bar(110.5, 110.6, 109.0, 109.1,
                         dt=base + timedelta(minutes=10)))  # bearish OB
        # Impulse bars: start ABOVE OB high (110.60), lows stay > 109.80
        start = 110.80
        for j in range(5):
            o = start + j * 1.20
            bars.append(_bar(o, o + 0.50, o - 0.10, o + 0.40,
                             dt=base + timedelta(minutes=11 + j)))
    else:
        # OB: big green candle, mid = (109.40+111.00)/2 = 110.20
        bars.append(_bar(109.5, 111.0, 109.4, 110.9,
                         dt=base + timedelta(minutes=10)))  # bullish OB
        # Impulse bars: start BELOW OB low (109.40), highs stay < 110.20
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
    check("REVERSAL CHoCH detected",       r["is_choch"] == True)
    check("CHoCH type = REVERSAL",          r["choch_type"] == "REVERSAL")
    check("CHoCH boost = +0.04",            math.isclose(r["confidence_delta"], 0.04, abs_tol=1e-9))

    bars = _bos_bull_continuation_bars()  # MARKUP + bull BOS
    r = detect_choch(bars, "bull")
    print(f"  Bull BOS after MARKUP:   is_choch={r['is_choch']} type={r['choch_type']} delta={r['confidence_delta']:+.3f}")
    check("CONTINUATION not CHoCH",         r["is_choch"] == False)
    check("CHoCH type = CONTINUATION",       r["choch_type"] == "CONTINUATION")
    check("No boost on CONTINUATION",       math.isclose(r["confidence_delta"], 0.0, abs_tol=1e-9))

    bars = _sideways_bars() + [
        _bar(111, 114, 110.8, 113.5,
             dt=datetime(2026, 3, 17, 9, 30) + timedelta(minutes=36))
    ]
    r = detect_choch(bars, "bull")
    print(f"  Bull BOS after SIDEWAYS: is_choch={r['is_choch']} type={r['choch_type']} delta={r['confidence_delta']:+.3f}")
    check("BREAKOUT CHoCH after range",      r["is_choch"] == True)
    check("CHoCH type = BREAKOUT",           r["choch_type"] == "BREAKOUT")


# ============================================================================
# 3. INDUCEMENT
# ============================================================================

def test_inducement():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("3. INDUCEMENT DETECTION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Sweep candle on markdown base
    bars_md = _markdown_bars()
    swing_high = max(b["high"] for b in bars_md)
    sweep_bar = _bar(
        open_=swing_high - 0.50,
        high =swing_high * 1.010,
        low  =swing_high - 0.60,
        close=swing_high * 1.0015,
        dt=datetime(2026, 3, 17, 9, 30) + timedelta(minutes=len(bars_md))
    )
    r = detect_inducement(bars_md + [sweep_bar], "bull", swing_high)
    print(f"  Sweep candle: is_inducement={r['is_inducement']} sweep={r['sweep_pct']:.4f}% wick={r['wick_extension']:.4f}% delta={r['confidence_delta']:+.3f}")
    check("Inducement detected",         r["is_inducement"] == True)
    check("Inducement penalty = -0.03",  math.isclose(r["confidence_delta"], -0.03, abs_tol=1e-9))
    check("sweep_pct > 0",               r["sweep_pct"] > 0)
    check("wick >> close extension",     r["wick_extension"] > r["sweep_pct"] * 2)

    # Clean BOS — no inducement
    bars2  = _bos_bull_bars()
    swing2 = max(b["high"] for b in bars2[:-1])
    r2 = detect_inducement(bars2, "bull", swing2)
    print(f"  Clean BOS:    is_inducement={r2['is_inducement']} sweep={r2['sweep_pct']:.4f}% delta={r2['confidence_delta']:+.3f}")
    check("Clean BOS NOT inducement",    r2["is_inducement"] == False)
    check("No penalty on clean BOS",     math.isclose(r2["confidence_delta"], 0.0, abs_tol=1e-9))


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

    # BODY retest: open, close and low all inside OB zone
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

    # WICK retest: low touches OB, but body (open+close) is above OB high
    retest_wick = _bar(
        open_=ob["ob_high"] + 0.20,
        high =ob["ob_high"] + 0.50,
        low  =ob["ob_low"] + 0.05,   # wick dips into OB
        close=ob["ob_high"] + 0.10,  # body above OB
        dt=datetime(2026, 3, 17, 10, 1)
    )
    r = check_ob_retest(base_bars + [retest_wick], ob)
    print(f"  WICK retest: is_retest={r['is_retest']} quality={r['retest_quality']} delta={r['confidence_delta']:+.3f}")
    check("WICK retest detected",   r["is_retest"] == True)
    check("WICK quality",           r["retest_quality"] == "WICK")
    check("WICK boost = +0.015",    math.isclose(r["confidence_delta"], 0.015, abs_tol=1e-9))

    # No retest — bar completely above OB
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

    # Mitigated OB → no retest
    ob_mit = dict(ob); ob_mit["mitigated"] = True
    r = check_ob_retest(base_bars + [retest_body], ob_mit)
    check("Mitigated OB → no retest",    r["is_retest"] == False)


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
    check("Delta <= +0.10",   delta <= 0.10 + 1e-9)
    check("Delta >= -0.05",   delta >= -0.05 - 1e-9)

    # RC-5 FIX: MARKUP base → CHoCH CONTINUATION (delta=0) + inducement (-0.03)
    # + phase_align (+0.02 because bull signal aligns with MARKUP bias=bull)
    # net = -0.01 < 0  ✓
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
    check("Inducement fires on MARKUP base",        ind2["is_inducement"] == True)
    check("CHoCH is CONTINUATION on MARKUP base",  choch2["choch_type"] == "CONTINUATION")
    check("Net delta is negative",                  delta2 < 0.0)
    check("Delta floor >= -0.05",                   delta2 >= -0.05 - 1e-9)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("\n" + "═" * 54)
    print(" SMC ENGINE SMOKE TEST v2 — War Machine")
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
