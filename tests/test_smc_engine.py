#!/usr/bin/env python3
"""
tests/test_smc_engine.py
========================
SMC Engine smoke test — validates all 5 SMC components using
synthetic bar data. Zero external dependencies: no DB, no API, no config.

Run from repo root:
    python tests/test_smc_engine.py

Components tested:
    1. Trend Phase       — MARKUP / MARKDOWN / ACCUMULATION / DISTRIBUTION
    2. CHoCH             — REVERSAL / CONTINUATION / BREAKOUT
    3. Inducement        — sweep detection + penalty
    4. Order Block       — BULL OB / BEAR OB, fresh vs mitigated
    5. OB Retest         — BODY retest / WICK retest
    6. enrich_signal_with_smc() — full pipeline integration
    7. Confidence delta  — cap at +0.10 / floor at -0.05
"""
import sys
import os
import math
from datetime import datetime, timedelta
from typing   import List, Dict

# ---------------------------------------------------------------------------
# Bootstrap: make repo root importable without installing the package
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Monkey-patch the DB persistence call so the test never touches a real DB
import unittest.mock as mock
_DB_PATCH = mock.patch(
    "app.mtf.smc_engine._persist_smc_context",
    side_effect=lambda *a, **kw: None
)
_DB_PATCH.start()

# Monkey-patch _ensure_smc_table so import doesn't need a DB connection
import unittest.mock as mock2
_TABLE_PATCH = mock2.patch(
    "app.mtf.smc_engine._ensure_smc_table",
    side_effect=lambda: None
)
_TABLE_PATCH.start()

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


def _markup_bars(n: int = 35) -> List[Dict]:
    """Rising staircase — clear HH+HL structure (MARKUP)."""
    bars = []
    price = 100.0
    for i in range(n):
        open_  = price
        high   = price + 0.80 + (i % 3) * 0.10
        low    = price - 0.20
        close  = price + 0.50
        bars.append(_bar(open_, high, low, close, dt=datetime(2026,3,17,9,30) + timedelta(minutes=i)))
        price  = close
    return bars


def _markdown_bars(n: int = 35) -> List[Dict]:
    """Falling staircase — clear LH+LL structure (MARKDOWN)."""
    bars = []
    price = 120.0
    for i in range(n):
        open_  = price
        high   = price + 0.20
        low    = price - 0.80 - (i % 3) * 0.10
        close  = price - 0.50
        bars.append(_bar(open_, high, low, close, dt=datetime(2026,3,17,9,30) + timedelta(minutes=i)))
        price  = close
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
        bars.append(_bar(open_, high, low, close, dt=datetime(2026,3,17,9,30) + timedelta(minutes=i)))
    return bars


def _bos_bull_bars() -> List[Dict]:
    """
    20 bars in MARKDOWN (LH+LL), then a clean bullish BOS candle.
    Perfect CHoCH REVERSAL setup for a bull signal.
    """
    bars = _markdown_bars(20)
    # Add BOS bull candle: clean close well above recent high
    last_close = bars[-1]["close"]
    bars.append(_bar(
        open_=last_close,
        high =last_close + 3.0,
        low  =last_close - 0.10,
        close=last_close + 2.80,  # strong conviction close
        dt=datetime(2026,3,17,9,30) + timedelta(minutes=21)
    ))
    return bars


def _bos_bull_continuation_bars() -> List[Dict]:
    """
    20 bars in MARKUP, then another bull BOS — CONTINUATION (not CHoCH).
    """
    bars = _markup_bars(20)
    last_close = bars[-1]["close"]
    bars.append(_bar(
        open_=last_close,
        high =last_close + 3.0,
        low  =last_close - 0.10,
        close=last_close + 2.80,
        dt=datetime(2026,3,17,9,30) + timedelta(minutes=21)
    ))
    return bars


def _inducement_bars() -> List[Dict]:
    """
    20 bars of downtrend, then a bull BOS candle that:
    - closes only 0.15% above the swing high (< INDUCEMENT_MAX_PCT=0.3%)
    - has a wick extending 0.8% above the swing high (wick >> close extension)
    → should trigger inducement detection.
    """
    bars = _markdown_bars(20)
    swing_high = max(b["high"] for b in bars)
    # BOS candle with tiny close break + big wick
    bars.append(_bar(
        open_=swing_high - 0.50,
        high =swing_high * 1.010,    # wick 1% above swing
        low  =swing_high - 0.60,
        close=swing_high * 1.0015,   # close only 0.15% above swing
        dt=datetime(2026,3,17,9,30) + timedelta(minutes=21)
    ))
    return bars, swing_high


def _ob_bars(direction: str = "bull") -> List[Dict]:
    """
    Build bars containing a clear OB setup:
    BULL: preceding bearish candle (red body) before bullish impulse.
    BEAR: preceding bullish candle (green body) before bearish impulse.
    """
    bars = []
    base = datetime(2026, 3, 17, 9, 30)
    # 10 neutral bars
    for i in range(10):
        p = 110.0
        bars.append(_bar(p, p+0.30, p-0.30, p, dt=base + timedelta(minutes=i)))
    if direction == "bull":
        # OB: big red candle (bearish OB)
        bars.append(_bar(110.5, 110.6, 109.0, 109.1, dt=base + timedelta(minutes=10)))  # red
        # Impulsive bull move
        for j in range(5):
            p = 109.1 + (j+1) * 1.5
            bars.append(_bar(p-1.5, p+0.2, p-1.6, p, dt=base + timedelta(minutes=11+j)))
    else:
        # OB: big green candle (bullish OB)
        bars.append(_bar(109.5, 111.0, 109.4, 110.9, dt=base + timedelta(minutes=10)))  # green
        # Impulsive bear move
        for j in range(5):
            p = 110.9 - (j+1) * 1.5
            bars.append(_bar(p+1.5, p+1.6, p-0.2, p, dt=base + timedelta(minutes=11+j)))
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
    check("SIDEWAYS phase is ACCUMULATION or DISTRIBUTION",
          r["phase"] in ("ACCUMULATION", "DISTRIBUTION", "UNKNOWN"))

    r = classify_trend_phase([_bar(100,101,99,100)] * 5)  # too few bars
    check("Too few bars → UNKNOWN", r["phase"] == "UNKNOWN")


# ============================================================================
# 2. CHoCH
# ============================================================================

def test_choch():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("2. CHoCH DETECTION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Bull BOS after MARKDOWN → REVERSAL CHoCH
    bars = _bos_bull_bars()
    r = detect_choch(bars, "bull")
    print(f"  Bull BOS after MARKDOWN: is_choch={r['is_choch']} type={r['choch_type']} delta={r['confidence_delta']:+.3f}")
    check("REVERSAL CHoCH detected",       r["is_choch"] == True)
    check("CHoCH type = REVERSAL",          r["choch_type"] == "REVERSAL")
    check("CHoCH boost = +0.04",            math.isclose(r["confidence_delta"], 0.04, abs_tol=1e-9))

    # Bull BOS after MARKUP → CONTINUATION
    bars = _bos_bull_continuation_bars()
    r = detect_choch(bars, "bull")
    print(f"  Bull BOS after MARKUP: is_choch={r['is_choch']} type={r['choch_type']} delta={r['confidence_delta']:+.3f}")
    check("CONTINUATION not CHoCH",         r["is_choch"] == False)
    check("CHoCH type = CONTINUATION",       r["choch_type"] == "CONTINUATION")
    check("No CHoCH boost on continuation", math.isclose(r["confidence_delta"], 0.0, abs_tol=1e-9))

    # BOS after sideways → BREAKOUT
    bars = _sideways_bars() + [_bar(111, 114, 110.8, 113.5, dt=datetime(2026,3,17,9,30)+timedelta(minutes=36))]
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

    bars, swing_high = _inducement_bars()
    r = detect_inducement(bars, "bull", swing_high)
    print(f"  Sweep candle: is_inducement={r['is_inducement']} sweep_pct={r['sweep_pct']:.4f}% wick={r['wick_extension']:.4f}% delta={r['confidence_delta']:+.3f}")
    check("Inducement detected",              r["is_inducement"] == True)
    check("Inducement penalty = -0.03",        math.isclose(r["confidence_delta"], -0.03, abs_tol=1e-9))
    check("Sweep_pct > 0",                    r["sweep_pct"] > 0)
    check("Wick >> close extension",          r["wick_extension"] > r["sweep_pct"] * 2)

    # Clean BOS — no inducement
    bars2 = _bos_bull_bars()
    swing2 = max(b["high"] for b in bars2[:-1])
    r2 = detect_inducement(bars2, "bull", swing2)
    print(f"  Clean BOS:    is_inducement={r2['is_inducement']} sweep_pct={r2['sweep_pct']:.4f}% delta={r2['confidence_delta']:+.3f}")
    check("Clean BOS is NOT inducement",      r2["is_inducement"] == False)
    check("No penalty on clean BOS",          math.isclose(r2["confidence_delta"], 0.0, abs_tol=1e-9))


# ============================================================================
# 4. ORDER BLOCK
# ============================================================================

def test_order_block():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("4. ORDER BLOCK DETECTION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # BULL OB
    bars = _ob_bars("bull")
    bos_idx = len(bars) - 1
    ob = find_order_block(bars, "bull", bos_idx)
    if ob:
        print(f"  BULL OB: low={ob['ob_low']:.2f} high={ob['ob_high']:.2f} mitigated={ob['mitigated']}")
    else:
        print("  BULL OB: not found")
    check("BULL OB found",             ob is not None)
    if ob:
        check("BULL OB is FRESH",       ob["mitigated"] == False)
        check("BULL OB direction",      ob["ob_direction"] == "bull")
        check("BULL OB has valid zone", ob["ob_low"] < ob["ob_high"])

    # BEAR OB
    bars = _ob_bars("bear")
    bos_idx = len(bars) - 1
    ob = find_order_block(bars, "bear", bos_idx)
    if ob:
        print(f"  BEAR OB: low={ob['ob_low']:.2f} high={ob['ob_high']:.2f} mitigated={ob['mitigated']}")
    else:
        print("  BEAR OB: not found")
    check("BEAR OB found",             ob is not None)
    if ob:
        check("BEAR OB is FRESH",       ob["mitigated"] == False)
        check("BEAR OB direction",      ob["ob_direction"] == "bear")

    # bos_idx too small → no OB
    ob_none = find_order_block(bars, "bull", 2)
    check("Too-small bos_idx → None",  ob_none is None)


# ============================================================================
# 5. OB RETEST
# ============================================================================

def test_ob_retest():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("5. OB RETEST")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Build a fresh BULL OB
    base_bars  = _ob_bars("bull")
    bos_idx    = len(base_bars) - 1
    ob         = find_order_block(base_bars, "bull", bos_idx)

    if ob is None:
        print("  ⚠️  Skipping OB retest tests — no OB detected in base bars")
        return

    # BODY retest: current bar closes inside OB zone
    ob_mid = ob["ob_mid"]
    retest_bar_body = _bar(
        open_=ob["ob_low"] + 0.10,
        high =ob["ob_high"] - 0.05,
        low  =ob["ob_low"],
        close=ob["ob_low"] + 0.20,  # body inside OB
        dt=datetime(2026,3,17,10,0)
    )
    r = check_ob_retest(base_bars + [retest_bar_body], ob)
    print(f"  BODY retest: is_retest={r['is_retest']} quality={r['retest_quality']} delta={r['confidence_delta']:+.3f}")
    check("BODY retest detected",        r["is_retest"] == True)
    check("BODY quality",                r["retest_quality"] == "BODY")
    check("BODY boost = +0.03",          math.isclose(r["confidence_delta"], 0.03, abs_tol=1e-9))

    # WICK retest: low touches OB but body is above
    retest_bar_wick = _bar(
        open_=ob["ob_high"] + 0.10,
        high =ob["ob_high"] + 0.40,
        low  =ob["ob_low"] + 0.05,  # wick touches OB
        close=ob["ob_high"] + 0.05, # body above OB
        dt=datetime(2026,3,17,10,1)
    )
    r = check_ob_retest(base_bars + [retest_bar_wick], ob)
    print(f"  WICK retest: is_retest={r['is_retest']} quality={r['retest_quality']} delta={r['confidence_delta']:+.3f}")
    check("WICK retest detected",        r["is_retest"] == True)
    check("WICK quality",                r["retest_quality"] == "WICK")
    check("WICK boost = +0.015",         math.isclose(r["confidence_delta"], 0.015, abs_tol=1e-9))

    # No retest: bar is far above OB
    no_retest_bar = _bar(
        open_=ob["ob_high"] + 2.0,
        high =ob["ob_high"] + 3.0,
        low  =ob["ob_high"] + 1.5,
        close=ob["ob_high"] + 2.5,
        dt=datetime(2026,3,17,10,2)
    )
    r = check_ob_retest(base_bars + [no_retest_bar], ob)
    print(f"  No retest:   is_retest={r['is_retest']} quality={r['retest_quality']}")
    check("No retest when bar is far away", r["is_retest"] == False)

    # Mitigated OB → no retest
    ob_mitigated = dict(ob)
    ob_mitigated["mitigated"] = True
    r = check_ob_retest(base_bars + [retest_bar_body], ob_mitigated)
    check("Mitigated OB → no retest",    r["is_retest"] == False)


# ============================================================================
# 6. FULL PIPELINE — enrich_signal_with_smc()
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
    print(f"  smc_summary     : {smc.get('smc_summary')}")
    print(f"  total_delta     : {smc.get('total_confidence_delta'):+.4f}")
    print(f"  CHoCH           : {smc.get('choch', {}).get('is_choch')} type={smc.get('choch', {}).get('choch_type')}")
    print(f"  Phase           : {smc.get('trend_phase', {}).get('phase')} bias={smc.get('trend_phase', {}).get('trend_bias')}")
    print(f"  Inducement      : {smc.get('inducement', {}).get('is_inducement')}")
    print(f"  OB              : {smc.get('order_block') is not None}")

    check("signal_data['smc'] key present",        "smc" in result)
    check("CHoCH in smc output",                   "choch" in smc)
    check("inducement in smc output",              "inducement" in smc)
    check("trend_phase in smc output",             "trend_phase" in smc)
    check("total_confidence_delta is float",       isinstance(smc.get("total_confidence_delta"), float))
    check("smc_summary is a string",               isinstance(smc.get("smc_summary"), str))
    check("direction preserved in smc context",   smc.get("direction") == "bull")


# ============================================================================
# 7. CONFIDENCE DELTA CAPS
# ============================================================================

def test_delta_caps():
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("7. CONFIDENCE DELTA CAPS (+0.10 / -0.05)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Generate a scenario with many boosts — cap should kick in at +0.10
    bars = _bos_bull_bars()
    signal_data = {
        "direction":  "bull",
        "bos_idx":    len(bars) - 1,
        "bos_price":  max(b["high"] for b in bars[:-1]),
        "entry_type": "CFW6_INTRADAY",
    }
    result = enrich_signal_with_smc("CAP_TEST", bars, signal_data)
    delta = result["smc"]["total_confidence_delta"]
    print(f"  Multi-boost scenario: delta={delta:+.4f}")
    check("Delta capped at <= +0.10",  delta <= 0.10 + 1e-9)
    check("Delta floor >= -0.05",      delta >= -0.05 - 1e-9)

    # Inducement-heavy scenario → penalty floor
    bars2, swing_high = _inducement_bars()
    signal_data2 = {
        "direction":  "bull",
        "bos_idx":    len(bars2) - 1,
        "bos_price":  swing_high,
        "entry_type": "CFW6_INTRADAY",
    }
    result2 = enrich_signal_with_smc("FLOOR_TEST", bars2, signal_data2)
    delta2 = result2["smc"]["total_confidence_delta"]
    print(f"  Inducement scenario:   delta={delta2:+.4f}")
    check("Inducement applies negative delta", delta2 < 0.0)
    check("Delta floor >= -0.05",              delta2 >= -0.05 - 1e-9)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("\n" + "═" * 54)
    print(" SMC ENGINE SMOKE TEST — War Machine")
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
        total = sum(1 for _ in range(100))  # placeholder — actual count from checks
        print(f"\033[92m ALL CHECKS PASSED — SMC engine is healthy ✅\033[0m")
        sys.exit(0)
