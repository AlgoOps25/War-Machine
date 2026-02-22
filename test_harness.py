"""
test_harness.py — War Machine Component Test Suite

Run before market open to validate all subsystems.

Usage:
    python test_harness.py              # Run all 15 tests (live API included)
    python test_harness.py --skip-api   # Skip EODHD / Options / Discord live calls
    python test_harness.py --only T06   # Run only one test by ID

Each test prints PASS / FAIL / ERROR with detail.
All DB operations use a throwaway temp SQLite file — no production data is touched.
The temp file is deleted automatically on exit.
"""

import os
import sys
import traceback
import tempfile
from datetime import datetime, timedelta, time
from typing import List, Dict
import argparse

# ── Force SQLite mode for isolation (override before any config import) ────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = ""          # empty string → SQLite in db_connection

# ── CLI ────────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="War Machine Component Test Harness")
parser.add_argument("--skip-api", action="store_true",
                    help="Skip live EODHD / Options / Discord API calls")
parser.add_argument("--only", type=str, default=None,
                    help="Run only one test by ID, e.g. --only T06")
args, _ = parser.parse_known_args()
SKIP_API = args.skip_api
ONLY     = args.only

# ── Result tracking ────────────────────────────────────────────────────────────
RESULTS: List[tuple] = []


def run_test(test_id: str, name: str, fn):
    if ONLY and test_id != ONLY:
        return
    sep = "─" * 62
    print(f"\n{sep}")
    print(f"▶  {test_id} | {name}")
    print(sep)
    try:
        fn()
        RESULTS.append((test_id, name, "PASS", None))
        print(f"\n✅  {test_id} PASS")
    except AssertionError as e:
        RESULTS.append((test_id, name, "FAIL", str(e)))
        print(f"\n❌  {test_id} FAIL — {e}")
    except Exception as e:
        RESULTS.append((test_id, name, "ERROR", str(e)))
        print(f"\n💥  {test_id} ERROR — {e}")
        traceback.print_exc()


def assert_eq(a, b, msg=""):
    assert a == b, f"{msg} | expected {b!r}, got {a!r}"


def assert_true(cond, msg=""):
    assert cond, msg or f"Expected True, got {cond!r}"


def assert_between(val, lo, hi, msg=""):
    assert lo <= val <= hi, f"{msg} | {val} not in [{lo}, {hi}]"


# ══════════════════════════════════════════════════════════════════════════════
# SYNTHETIC DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

TODAY = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)


def make_bar(minute_offset: int, open_: float, high: float, low: float,
             close: float, volume: int = 100_000) -> Dict:
    return {
        "datetime": TODAY + timedelta(minutes=minute_offset),
        "open":  open_,
        "high":  high,
        "low":   low,
        "close": close,
        "volume": volume,
    }


def build_or_session(or_high: float = 502.0, or_low: float = 498.0,
                     breakout_price: float = 503.5,
                     direction: str = "bull") -> List[Dict]:
    """
    Synthetic session:
      - 10 OR bars  (9:30-9:39)
      - 1  breakout bar at minute 10  (9:40)
      - 4  consolidation bars
      - 3  FVG candles (clear gap between c0.high and c2.low)
      - 10 trending bars toward T1
    """
    bars = []
    mid = (or_high + or_low) / 2
    for i in range(10):
        bars.append(make_bar(i, mid, or_high - 0.10, or_low + 0.10, mid))

    if direction == "bull":
        bars.append(make_bar(10, or_high, breakout_price + 0.5,
                             or_high, breakout_price, 300_000))
    else:
        bars.append(make_bar(10, or_low, or_low,
                             or_low - 1.5, breakout_price, 300_000))

    for i in range(4):
        bars.append(make_bar(11 + i,
                             breakout_price, breakout_price + 0.2,
                             breakout_price - 0.2, breakout_price))

    # FVG: c0.high=bp+0.3, c2.low=bp+1.1  →  gap=0.8 (bull)
    if direction == "bull":
        bars.append(make_bar(15, breakout_price,       breakout_price + 0.3,
                             breakout_price - 0.1, breakout_price + 0.2))
        bars.append(make_bar(16, breakout_price + 0.5, breakout_price + 1.0,
                             breakout_price + 0.4, breakout_price + 0.9))
        bars.append(make_bar(17, breakout_price + 1.5, breakout_price + 2.0,
                             breakout_price + 1.1, breakout_price + 1.8))
    else:
        bars.append(make_bar(15, breakout_price,       breakout_price + 0.1,
                             breakout_price - 0.3, breakout_price - 0.2))
        bars.append(make_bar(16, breakout_price - 0.5, breakout_price - 0.4,
                             breakout_price - 1.0, breakout_price - 0.9))
        bars.append(make_bar(17, breakout_price - 1.5, breakout_price - 1.1,
                             breakout_price - 2.0, breakout_price - 1.8))

    for i in range(10):
        delta = 0.15 * (i + 1) if direction == "bull" else -0.15 * (i + 1)
        p = (breakout_price + 2.0 + delta if direction == "bull"
             else breakout_price - 2.0 + delta)
        bars.append(make_bar(18 + i, p - 0.05, p + 0.10, p - 0.10, p))

    return bars


def build_bos_session(base: float = 500.0) -> List[Dict]:
    """
    Synthetic intraday session:
      - 10 ranging bars → clear swing high
      - 10 pullback bars
      - 1  BOS bar (breaks swing high)
      - 3  FVG bars
      - 1  retrace bar (enters FVG)
    """
    bars = []
    for i in range(10):
        bars.append(make_bar(i, base, base + 0.5, base - 0.3, base + 0.2))

    bars.append(make_bar(10, base + 0.2, base + 2.0, base + 0.1, base + 1.8, 200_000))

    for i in range(10):
        bars.append(make_bar(11 + i,
                             base + 1.5, base + 1.8, base + 0.8, base + 1.0))

    bars.append(make_bar(21, base + 1.0, base + 2.5, base + 0.9, base + 2.2, 400_000))
    bars.append(make_bar(22, base + 2.2, base + 2.4, base + 2.1, base + 2.3))
    bars.append(make_bar(23, base + 2.5, base + 3.0, base + 2.4, base + 2.8, 300_000))
    bars.append(make_bar(24, base + 3.2, base + 3.5, base + 2.9, base + 3.3))
    bars.append(make_bar(25, base + 3.3, base + 3.4, base + 2.3, base + 2.5))
    return bars


# ══════════════════════════════════════════════════════════════════════════════
# T01 — CONFIG & ENVIRONMENT
# ══════════════════════════════════════════════════════════════════════════════

def test_t01_config():
    import config
    required = [
        "EODHD_API_KEY", "DISCORD_WEBHOOK_URL", "POSITION_RISK",
        "MIN_CONFIDENCE_OR", "MIN_CONFIDENCE_INTRADAY",
        "CONFIDENCE_ABSOLUTE_FLOOR", "MIN_CONFIDENCE_BY_GRADE",
        "MIN_OR_RANGE_PCT", "FVG_MIN_SIZE_PCT",
        "TARGET_DELTA_MIN", "TARGET_DELTA_MAX",
        "ACCOUNT_SIZE", "MAX_CONTRACTS",
    ]
    for attr in required:
        assert_true(hasattr(config, attr), f"config.{attr} missing")

    assert_between(config.MIN_OR_RANGE_PCT,   0.001, 0.020, "MIN_OR_RANGE_PCT")
    assert_between(config.FVG_MIN_SIZE_PCT,   0.0005, 0.010, "FVG_MIN_SIZE_PCT")
    assert_between(config.TARGET_DELTA_MIN,   0.20, 0.60,  "TARGET_DELTA_MIN")
    assert_between(config.TARGET_DELTA_MAX,   0.40, 0.80,  "TARGET_DELTA_MAX")
    assert_between(config.ACCOUNT_SIZE,       1000, 10_000_000, "ACCOUNT_SIZE")
    assert_between(config.MAX_CONTRACTS,      1, 100, "MAX_CONTRACTS")
    assert_between(config.CONFIDENCE_ABSOLUTE_FLOOR, 0.40, 0.80, "ABS_FLOOR")

    print(f"  ACCOUNT_SIZE=${config.ACCOUNT_SIZE:,.0f}  MAX_CONTRACTS={config.MAX_CONTRACTS}")
    print(f"  MIN_CONFIDENCE_OR={config.MIN_CONFIDENCE_OR}  "
          f"INTRADAY={config.MIN_CONFIDENCE_INTRADAY}  "
          f"ABS_FLOOR={config.CONFIDENCE_ABSOLUTE_FLOOR}")
    print(f"  MIN_OR_RANGE_PCT={config.MIN_OR_RANGE_PCT:.3%}  "
          f"FVG_MIN_SIZE_PCT={config.FVG_MIN_SIZE_PCT:.3%}")
    print(f"  EODHD key:   {'***' + config.EODHD_API_KEY[-4:] if config.EODHD_API_KEY else '⚠️  NOT SET'}")
    print(f"  Discord URL: {'set ✓' if config.DISCORD_WEBHOOK_URL else '⚠️  NOT SET'}")


# ══════════════════════════════════════════════════════════════════════════════
# T02 — DB CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

def test_t02_db():
    import db_connection as dbc
    print(f"  USE_POSTGRES={dbc.USE_POSTGRES}")
    print(f"  ph()='{dbc.ph()}'  serial_pk()='{dbc.serial_pk()}'")

    conn   = dbc.get_conn(_TEST_DB)
    cursor = dbc.dict_cursor(conn)
    cursor.execute("CREATE TABLE IF NOT EXISTS _t02 (id INTEGER PRIMARY KEY, val TEXT)")
    p = dbc.ph()
    cursor.execute(f"INSERT INTO _t02 (val) VALUES ({p})", ("hello",))
    conn.commit()
    cursor.execute("SELECT val FROM _t02")
    row = cursor.fetchone()
    conn.close()
    assert_eq(row["val"], "hello", "DB round-trip")
    print("  SQLite round-trip: ✓")

    # Verify upsert SQL generates without error
    sql_1m = dbc.upsert_bar_sql()
    sql_5m = dbc.upsert_bar_5m_sql()
    assert_true("intraday_bars" in sql_1m,   "1m upsert SQL missing table name")
    assert_true("intraday_bars_5m" in sql_5m, "5m upsert SQL missing table name")
    print("  upsert SQL helpers: ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T03 — DATA MANAGER
# ══════════════════════════════════════════════════════════════════════════════

def test_t03_data_manager():
    from data_manager import DataManager
    dm = DataManager(db_path=_TEST_DB)

    bars = build_or_session()
    dm.store_bars("TEST", bars)
    dm.materialize_5m_bars("TEST")

    retrieved = dm.get_today_session_bars("TEST")
    assert_true(len(retrieved) > 0,          "No bars retrieved after store")
    assert_true(len(retrieved) <= len(bars) + 5, "Unexpected bar count")
    print(f"  store_bars: {len(bars)} bars → retrieved {len(retrieved)} session bars ✓")

    bars_5m = dm.get_today_5m_bars("TEST")
    assert_true(len(bars_5m) > 0, "No 5m bars materialized")
    print(f"  materialize_5m_bars: {len(bars_5m)} 5m bars ✓")

    dm.cleanup_old_bars(days_to_keep=0)
    print("  cleanup_old_bars: ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T04 — WS FEED  (offline — no threads started)
# ══════════════════════════════════════════════════════════════════════════════

def test_t04_ws_feed():
    import ws_feed
    now_ms = int(datetime.now().timestamp() * 1000)

    # First tick → opens bar
    ws_feed._on_tick("WTEST", 500.00, 100, now_ms)
    bar = ws_feed.get_current_bar("WTEST")
    assert_true(bar is not None,          "Bar not created after first tick")
    assert_eq(bar["open"],  500.00,       "Bar open price")
    assert_eq(bar["close"], 500.00,       "Bar close price")
    print("  First tick → bar created ✓")

    # Second tick → updates high/close
    ws_feed._on_tick("WTEST", 501.00, 50, now_ms)
    bar = ws_feed.get_current_bar("WTEST")
    assert_eq(bar["high"],  501.00, "Bar high after 2nd tick")
    assert_eq(bar["close"], 501.00, "Bar close after 2nd tick")
    print("  Update tick ✓")

    # Spike > 10% → rejected
    ws_feed._on_tick("WTEST", 600.00, 10, now_ms)
    bar = ws_feed.get_current_bar("WTEST")
    assert_eq(bar["close"], 501.00, "Spike should be rejected")
    print("  Spike filter (>10%): ✓")

    # Zero price → rejected
    ws_feed._on_tick("WTEST", 0.00, 100, now_ms)
    bar = ws_feed.get_current_bar("WTEST")
    assert_eq(bar["close"], 501.00, "Zero price should be rejected")
    print("  Zero-price filter: ✓")

    # Negative volume → rejected
    ws_feed._on_tick("WTEST", 501.50, -5, now_ms)
    bar = ws_feed.get_current_bar("WTEST")
    assert_eq(bar["close"], 501.00, "Negative volume should be rejected")
    print("  Negative volume filter: ✓")

    # Minute rollover → old bar closes, new opens
    next_min_ms = now_ms + 61_000
    ws_feed._on_tick("WTEST", 502.00, 200, next_min_ms)
    new_bar = ws_feed.get_current_bar("WTEST")
    assert_eq(new_bar["open"],  502.00, "New bar open after rollover")
    assert_eq(new_bar["close"], 502.00, "New bar close after rollover")
    print("  Minute rollover: ✓")

    # _started guard: threads must NOT have been launched by these calls
    assert_true(not ws_feed._started, "_started should be False — no threads launched")
    print("  _started guard: ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T05 — TRADE CALCULATOR
# ══════════════════════════════════════════════════════════════════════════════

def test_t05_trade_calculator():
    from trade_calculator import (
        calculate_atr, get_adaptive_fvg_threshold,
        get_adaptive_orb_threshold, apply_confidence_decay,
        calculate_stop_loss_by_grade, calculate_targets_by_grade,
        compute_stop_and_targets,
    )
    bars = build_or_session()

    atr = calculate_atr(bars, period=14)
    assert_true(atr >= 0, "ATR must be non-negative")
    print(f"  ATR(14) = {atr:.4f}")

    threshold, conf_adj = get_adaptive_fvg_threshold(bars, "TEST")
    assert_between(threshold, 0.001, 0.005, "FVG threshold")
    assert_between(conf_adj,  0.90,  1.10,  "Confidence adj")
    print(f"  Adaptive FVG threshold={threshold:.4f}  conf_adj={conf_adj:.2f}")

    orb_thresh = get_adaptive_orb_threshold(bars, breakout_idx=15)
    assert_between(orb_thresh, 0.0005, 0.002, "ORB threshold")
    print(f"  Adaptive ORB threshold={orb_thresh:.4f}")

    # Confidence decay
    no_decay = apply_confidence_decay(0.80, 3)
    assert_eq(no_decay, 0.80, "No decay for ≤5 candles")
    decayed = apply_confidence_decay(0.80, 8)
    assert_true(decayed < 0.80, "Confidence should decay after 5 candles")
    assert_true(decayed >= 0.50, "Decay must not go below floor 0.50")
    print(f"  Decay: 3 candles → {no_decay:.2f} | 8 candles → {decayed:.2f}")

    # Grade-based stops: A+ tightest, A- widest (bull)
    atr_val = atr if atr > 0 else 0.5
    entry, or_low, or_high = 500.0, 497.0, 503.0
    s_ap = calculate_stop_loss_by_grade(entry, "A+", "bull", or_low, or_high, atr_val)
    s_a  = calculate_stop_loss_by_grade(entry, "A",  "bull", or_low, or_high, atr_val)
    s_am = calculate_stop_loss_by_grade(entry, "A-", "bull", or_low, or_high, atr_val)
    assert_true(s_ap >= s_a,  "A+ stop must be ≥ A stop (closer to entry)")
    assert_true(s_a  >= s_am, "A stop must be ≥ A- stop")
    print(f"  Stops — A+:{s_ap:.2f}  A:{s_a:.2f}  A-:{s_am:.2f}")

    # Targets: T1=2R, T2=3.5R
    t1, t2 = calculate_targets_by_grade(500.0, 498.0, "A", "bull")
    risk = 500.0 - 498.0
    assert_eq(round(t1, 6), round(500.0 + risk * 2.0, 6), "T1 must be 2R")
    assert_eq(round(t2, 6), round(500.0 + risk * 3.5, 6), "T2 must be 3.5R")
    print(f"  T1={t1:.2f} (2R)  T2={t2:.2f} (3.5R)  Risk=${risk:.2f}")

    # Full compute
    stop, t1f, t2f = compute_stop_and_targets(bars, "bull", or_high, or_low, 500.0, "A")
    assert_true(stop  < 500.0, "Bull stop must be below entry")
    assert_true(t1f   > 500.0, "Bull T1 must be above entry")
    assert_true(t2f   > t1f,   "T2 must be greater than T1")
    print(f"  compute_stop_and_targets → stop={stop:.2f}  T1={t1f:.2f}  T2={t2f:.2f}")


# ══════════════════════════════════════════════════════════════════════════════
# T06 — BOS + FVG ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def test_t06_bos_fvg():
    from bos_fvg_engine import (
        find_swing_points, detect_bos, find_fvg_after_bos,
        check_fvg_entry, compute_0dte_stops_and_targets,
        scan_bos_fvg, is_valid_entry_time, is_force_close_time,
    )
    bars = build_bos_session()

    swings = find_swing_points(bars)
    assert_true(swings["swing_high"] is not None, "swing_high not detected")
    assert_true(swings["swing_low"]  is not None, "swing_low not detected")
    print(f"  Swing high={swings['swing_high']:.2f}  low={swings['swing_low']:.2f}")

    bos = detect_bos(bars)
    assert_true(bos is not None, "BOS not detected on synthetic session")
    assert_true(bos["direction"] in ("bull", "bear"), "BOS direction invalid")
    print(f"  BOS: {bos['direction'].upper()} @ ${bos['bos_price']:.2f}  "
          f"strength={bos['strength']*100:.3f}%")

    fvg = find_fvg_after_bos(bars, bos["bos_idx"], bos["direction"], min_pct=0.001)
    assert_true(fvg is not None,               "FVG not found after BOS")
    assert_true(fvg["fvg_high"] > fvg["fvg_low"], "FVG high must be > low")
    print(f"  FVG: ${fvg['fvg_low']:.2f}–${fvg['fvg_high']:.2f}  "
          f"size={fvg['fvg_size_pct']:.3f}%")

    entry_trigger = check_fvg_entry(bars[-1], fvg)
    assert_true(entry_trigger is not None, "Entry trigger not detected on retrace bar")
    assert_eq(entry_trigger["entry_type"], "FVG_FILL", "Entry type")
    print(f"  Entry trigger @ ${entry_trigger['entry_price']:.2f} ✓")

    levels = compute_0dte_stops_and_targets(
        entry_trigger["entry_price"], bos["direction"], fvg
    )
    assert_true(levels["risk"] > 0,  "Risk must be positive")
    assert_eq(levels["rr_t1"],  1.5, "T1 R:R must be 1.5")
    assert_eq(levels["rr_t2"],  2.5, "T2 R:R must be 2.5")
    print(f"  0DTE levels — stop={levels['stop']:.2f}  "
          f"T1={levels['t1']:.2f}  T2={levels['t2']:.2f}")

    # Time filters
    valid_bar = {"datetime": TODAY + timedelta(minutes=30)}
    force_bar = {"datetime": TODAY.replace(hour=15, minute=56)}
    after_bar = {"datetime": TODAY.replace(hour=15, minute=46)}
    assert_true(is_valid_entry_time(valid_bar),      "9:30+30m should be valid")
    assert_true(not is_valid_entry_time(after_bar),  "15:46 should be invalid")
    assert_true(is_force_close_time(force_bar),      "15:56 should trigger force close")
    print("  Time filters: is_valid_entry_time + is_force_close_time ✓")

    signal = scan_bos_fvg("TEST", bars, fvg_min_pct=0.001)
    if signal:
        assert_true(signal["entry"] > 0,         "Entry must be positive")
        assert_eq(signal["entry_type"], "BOS+FVG", "Entry type")
        assert_eq(signal["dte"], 0,               "DTE must be 0")
        print(f"  scan_bos_fvg: {signal['direction'].upper()} @ "
              f"${signal['entry']:.2f} ✓")
    else:
        print("  scan_bos_fvg: no signal on this synthetic set "
              "(entry bar not yet retrace-triggered) — OK")


# ══════════════════════════════════════════════════════════════════════════════
# T07 — CFW6 CONFIRMATION
# ══════════════════════════════════════════════════════════════════════════════

def test_t07_cfw6():
    from cfw6_confirmation import (
        analyze_confirmation_candle, wait_for_confirmation,
        calculate_vwap, check_vwap_alignment,
    )

    # ── Bull Type 1 (A+): strong green, wick_ratio < 0.15 ───────────────────
    t1c = {"open": 499.80, "close": 500.50, "high": 500.55, "low": 499.75}
    _, g = analyze_confirmation_candle(t1c, "bull", 499.70, 500.60)
    assert_eq(g, "A+", "Bull Type 1 should grade A+")
    print(f"  Bull Type 1 (A+): {g} ✓")

    # ── Bull Type 2 (A): flip candle, strong lower wick ≥ 0.25 ─────────────
    # open=500.40, close=500.60 (green), low=499.80
    # lower_wick = open - low = 0.60, range = 0.85, ratio = 0.706 ≥ 0.25
    t2c = {"open": 500.40, "close": 500.60, "high": 500.65, "low": 499.80}
    _, g2 = analyze_confirmation_candle(t2c, "bull", 499.70, 500.70)
    assert_eq(g2, "A", f"Bull Type 2 should grade A (got {g2})")
    print(f"  Bull Type 2 (A): {g2} ✓")

    # ── Bull Type 3 (A-): red candle, big lower wick ≥ 0.50 ─────────────────
    # open=500.30, close=500.10 (red), low=499.60
    # lower_wick = close - low = 0.50, range = 0.75, ratio = 0.667 ≥ 0.50
    t3c = {"open": 500.30, "close": 500.10, "high": 500.35, "low": 499.60}
    _, g3 = analyze_confirmation_candle(t3c, "bull", 499.50, 500.40)
    assert_eq(g3, "A-", f"Bull Type 3 should grade A- (got {g3})")
    print(f"  Bull Type 3 (A-): {g3} ✓")

    # ── Bear Type 1 (A+): strong red, upper wick_ratio < 0.15 ───────────────
    b1c = {"open": 500.20, "close": 499.50, "high": 500.25, "low": 499.45}
    _, bg = analyze_confirmation_candle(b1c, "bear", 499.40, 500.30)
    assert_eq(bg, "A+", f"Bear Type 1 should grade A+ (got {bg})")
    print(f"  Bear Type 1 (A+): {bg} ✓")

    # ── Out-of-zone → reject ─────────────────────────────────────────────────
    rej = {"open": 505.0, "close": 506.0, "high": 506.5, "low": 504.5}
    _, rg = analyze_confirmation_candle(rej, "bull", 499.0, 500.0)
    assert_eq(rg, "reject", "Out-of-zone candle must reject")
    print("  Out-of-zone reject: ✓")

    # ── wait_for_confirmation ────────────────────────────────────────────────
    bars = build_or_session()
    found, ep, gr, idx, _ = wait_for_confirmation(
        bars, "bull", (498.0, 500.0), 10, max_wait=15
    )
    if found:
        print(f"  wait_for_confirmation: {gr} @ ${ep:.2f} (bar {idx}) ✓")
    else:
        print("  wait_for_confirmation: no confirm in zone — OK "
              "(synthetic bars are above zone after breakout)")

    # ── VWAP ─────────────────────────────────────────────────────────────────
    vwap = calculate_vwap(bars)
    assert_true(vwap > 0, "VWAP must be positive")
    assert_true(check_vwap_alignment(bars, "bull", vwap + 0.5),
                "Price above VWAP should align bull")
    assert_true(check_vwap_alignment(bars, "bear", vwap - 0.5),
                "Price below VWAP should align bear")
    print(f"  VWAP={vwap:.2f}  bull_align ✓  bear_align ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T08 — POSITION MANAGER
# ══════════════════════════════════════════════════════════════════════════════

def test_t08_position_manager():
    from position_manager import PositionManager
    from db_connection import get_conn, ph
    pm = PositionManager(db_path=_TEST_DB)

    # Open
    pos_id = pm.open_position(
        "SPY", "bull", 499.0, 501.0, 498.0, 502.0,
        500.00, 498.00, 504.00, 507.00, 0.82, "A"
    )
    assert_true(pos_id > 0, "Position ID must be positive")
    open_pos = pm.get_open_positions()
    assert_eq(len(open_pos), 1, "Should have 1 open position")
    assert_eq(open_pos[0]["ticker"], "SPY", "Ticker mismatch")
    print(f"  open_position: ID={pos_id} ✓")

    # Scale out at T1
    pm._scale_out(pos_id, 504.00, 500.00)
    p = pm.get_open_positions()[0]
    assert_true(bool(p["t1_hit"]),    "t1_hit should be 1 after scale-out")
    assert_eq(p["stop_price"], 500.00, "Stop must move to BE")
    assert_true(p["pnl"] > 0,         "Partial PnL must be positive")
    print(f"  _scale_out: t1_hit ✓  stop=BE ✓  partial_pnl=${p['pnl']:.2f}")

    # Close at T2
    pm.close_position(pos_id, 507.00, "TARGET 2")
    assert_eq(len(pm.get_open_positions()), 0, "No open positions after close")
    print("  close_position (T2): ✓")

    # Daily stats — 1 win
    stats = pm.get_daily_stats()
    assert_eq(stats["trades"], 1,     "Should show 1 trade")
    assert_eq(stats["wins"],   1,     "Should show 1 win")
    assert_true(stats["total_pnl"] > 0, "Total PnL must be positive")
    print(f"  get_daily_stats: {stats['trades']} trades | "
          f"{stats['wins']} wins | P&L=${stats['total_pnl']:.2f}")

    # Stop loss path — 1 loss
    sl_id = pm.open_position(
        "NVDA", "bear", 490.0, 492.0, 489.0, 493.0,
        491.00, 493.00, 487.00, 484.00, 0.75, "A-"
    )
    pm.close_position(sl_id, 493.50, "STOP LOSS")
    stats2 = pm.get_daily_stats()
    assert_eq(stats2["losses"], 1, "Should show 1 loss")
    print(f"  close_position (STOP LOSS): losses={stats2['losses']} ✓")

    # Loss streak: 3 consecutive losses
    for _ in range(3):
        lid = pm.open_position(
            "AAPL", "bull", 499.0, 501.0, 498.0, 502.0,
            500.00, 498.00, 504.00, 507.00, 0.70, "A"
        )
        pm.close_position(lid, 497.00, "STOP LOSS")
    assert_true(pm.has_loss_streak(max_consecutive_losses=3),
                "Should detect 3-trade losing streak")
    print("  has_loss_streak (3): ✓")

    # Stale position — insert yesterday's entry_time, re-init should force-close
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 10:30:00")
    conn   = get_conn(_TEST_DB)
    cursor = conn.cursor()
    p_ph   = ph()
    cursor.execute(
        f"""INSERT INTO positions
            (ticker, direction, entry_price, stop_price, t1_price, t2_price,
             contracts, remaining_contracts, grade, confidence, status, entry_time)
            VALUES ({p_ph},{p_ph},{p_ph},{p_ph},{p_ph},{p_ph},
                    {p_ph},{p_ph},{p_ph},{p_ph},'OPEN',{p_ph})""",
        ("STALE", "bull", 100.0, 98.0, 103.0, 105.0, 1, 1, "A", 0.80, yesterday)
    )
    conn.commit(); conn.close()

    pm2 = PositionManager(db_path=_TEST_DB)
    stale_open = [p for p in pm2.get_open_positions() if p["ticker"] == "STALE"]
    assert_eq(len(stale_open), 0, "Stale position must be force-closed on init")
    print("  _close_stale_positions on init: ✓")

    # EOD report
    report = pm2.generate_report()
    assert_true("WAR MACHINE" in report, "Report missing header")
    assert_true("Net P&L"     in report, "Report missing P&L line")
    print("  generate_report: ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T09 — AI LEARNING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def test_t09_ai_learning():
    import json
    from ai_learning import AILearningEngine

    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    tmp.write("{}")
    tmp.close()
    engine = AILearningEngine(db_path=tmp.name)

    for key in ["trades", "confirmation_weights", "fvg_size_optimal",
                "pattern_performance", "ticker_performance"]:
        assert_true(key in engine.data, f"engine.data missing key: {key}")
    print("  Default data structure: ✓")

    # Record a win
    engine.record_trade({
        "ticker": "SPY", "direction": "bull", "grade": "A+",
        "entry": 500.0, "exit": 504.0, "pnl": 400.0, "timeframe": "5m",
        "fvg_size": 0.003, "or_break_size": 0.001,
        "confirmations": {"vwap": True, "prev_day": True, "institutional": True},
    })
    assert_eq(len(engine.data["trades"]), 1, "Should have 1 trade")
    assert_true(engine.data["trades"][0]["win"], "Should be a win")
    print("  record_trade (win): ✓")

    # Record 3 losses
    for _ in range(3):
        engine.record_trade({
            "ticker": "AAPL", "direction": "bear", "grade": "A-",
            "entry": 200.0, "exit": 201.5, "pnl": -150.0, "timeframe": "5m",
            "fvg_size": 0.001, "or_break_size": 0.0005,
            "confirmations": {"vwap": False, "prev_day": False, "institutional": False},
        })
    assert_eq(len(engine.data["trades"]), 4, "Should have 4 trades")
    print("  record_trade (3 losses): ✓")

    # Ticker multiplier with insufficient data
    mult = engine.get_ticker_confidence_multiplier("SPY")
    assert_eq(mult, 1.0, "<5 trades → multiplier must be 1.0")
    print(f"  get_ticker_confidence_multiplier (cold): {mult} ✓")

    # Seed 20 trades with confirmations to unlock weight optimization
    for i in range(20):
        engine.record_trade({
            "ticker": "SPY", "direction": "bull", "grade": "A+",
            "entry": 500.0,
            "exit": 503.0 if i % 3 != 0 else 499.0,
            "pnl":  300.0 if i % 3 != 0 else -100.0,
            "timeframe": "5m", "fvg_size": 0.003, "or_break_size": 0.001,
            "confirmations": {
                "vwap": True, "prev_day": i % 2 == 0, "institutional": i % 4 == 0
            },
        })
    engine.optimize_confirmation_weights()
    weights = engine.data["confirmation_weights"]
    assert_true(weights["vwap"] > 0,     "VWAP weight must be positive")
    assert_true(weights["prev_day"] > 0, "prev_day weight must be positive")
    print(f"  optimize_confirmation_weights: {weights}")

    # Seed enough for FVG threshold optimization (need 30+ with fvg_size > 0)
    for i in range(10):
        engine.record_trade({
            "ticker": "NVDA", "direction": "bull", "grade": "A",
            "entry": 800.0, "exit": 805.0, "pnl": 500.0,
            "timeframe": "5m", "fvg_size": 0.0025, "or_break_size": 0.001,
            "confirmations": {},
        })
    engine.optimize_fvg_threshold()
    assert_true(engine.data["fvg_size_optimal"] > 0, "FVG optimal must be set")
    print(f"  optimize_fvg_threshold: {engine.data['fvg_size_optimal']:.4f} ✓")

    report = engine.generate_performance_report()
    assert_true("Win Rate"     in report, "Report missing Win Rate")
    assert_true("Total Trades" in report, "Report missing Total Trades")
    print("  generate_performance_report: ✓")

    os.unlink(tmp.name)


# ══════════════════════════════════════════════════════════════════════════════
# T10 — SNIPER: OR PATH  (offline)
# ══════════════════════════════════════════════════════════════════════════════

def test_t10_sniper_or_path():
    import sniper
    import config

    sniper.armed_signals.clear()
    sniper.watching_signals.clear()
    sniper._watches_loaded = True   # skip DB load

    bars = build_or_session()

    or_high, or_low = sniper.compute_opening_range_from_bars(bars)
    assert_true(or_high is not None, "OR high not computed")
    assert_true(or_low  is not None, "OR low not computed")
    assert_true(or_high > or_low,    "OR high must be > OR low")
    or_range_pct = (or_high - or_low) / or_low
    print(f"  OR: ${or_low:.2f}–${or_high:.2f} ({or_range_pct:.2%})")

    if or_range_pct < config.MIN_OR_RANGE_PCT:
        print(f"  ⚠️  OR too narrow ({or_range_pct:.2%} < {config.MIN_OR_RANGE_PCT:.2%}) "
              "— intraday BOS fallback would apply")
    else:
        direction, breakout_idx = sniper.detect_breakout_after_or(bars, or_high, or_low)
        assert_true(direction in ("bull", "bear"),
                    f"Expected bull/bear, got {direction!r}")
        assert_true(breakout_idx is not None, "breakout_idx is None")
        print(f"  ORB: {direction.upper()} at bar {breakout_idx} ✓")

        zl, zh = sniper.detect_fvg_after_break(bars, breakout_idx, direction)
        if zl is not None:
            assert_true(zh > zl, "FVG high must be > FVG low")
            print(f"  FVG zone: ${zl:.2f}–${zh:.2f} ✓")
        else:
            print("  No immediate FVG — watch state would be set ✓")

    # Watch DB round-trip
    sniper._watches_loaded = False
    sniper._ensure_watch_db()
    sniper._persist_watch("TWST", {
        "direction":       "bull",
        "breakout_bar_dt": datetime.now(),
        "or_high": 502.0, "or_low": 498.0,
        "signal_type": "CFW6_OR",
    })
    loaded = sniper._load_watches_from_db()
    assert_true("TWST" in loaded, "Watch persist → load failed")
    sniper._remove_watch_from_db("TWST")
    loaded2 = sniper._load_watches_from_db()
    assert_true("TWST" not in loaded2, "Watch remove failed")
    print("  Watch DB persist → load → remove: ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T11 — SNIPER: INTRADAY BOS PATH  (offline)
# ══════════════════════════════════════════════════════════════════════════════

def test_t11_sniper_intraday():
    import sniper
    from bos_fvg_engine import scan_bos_fvg, is_valid_entry_time
    from trade_calculator import get_adaptive_fvg_threshold

    bars = build_bos_session()

    valid = [b for b in bars if is_valid_entry_time(b)]
    assert_true(len(valid) > 0, "No bars in valid entry window (9:40–15:45)")
    print(f"  Bars in valid window: {len(valid)}")

    threshold, conf_adj = get_adaptive_fvg_threshold(bars, "INTRA")
    print(f"  Adaptive threshold={threshold:.4f}  conf_adj={conf_adj:.2f}")

    signal = scan_bos_fvg("INTRA", bars, fvg_min_pct=threshold)
    if signal:
        assert_true(signal["direction"] in ("bull", "bear"), "Direction invalid")
        assert_true(signal["entry"] > 0,  "Entry must be positive")
        assert_true(signal["stop"] > 0,   "Stop must be positive")
        assert_true(signal["t1"] > 0,     "T1 must be positive")
        assert_true(signal["t2"] > 0,     "T2 must be positive")
        assert_eq(signal["entry_type"], "BOS+FVG", "Entry type")
        assert_eq(signal["dte"], 0, "DTE")

        if signal["direction"] == "bull":
            assert_true(signal["stop"] < signal["entry"], "Bull: stop < entry")
            assert_true(signal["t1"]   > signal["entry"], "Bull: T1 > entry")
            assert_true(signal["t2"]   > signal["t1"],    "Bull: T2 > T1")
        else:
            assert_true(signal["stop"] > signal["entry"], "Bear: stop > entry")
            assert_true(signal["t1"]   < signal["entry"], "Bear: T1 < entry")
            assert_true(signal["t2"]   < signal["t1"],    "Bear: T2 < T1")

        print(f"  BOS+FVG signal: {signal['direction'].upper()} "
              f"entry=${signal['entry']:.2f}  stop=${signal['stop']:.2f}  "
              f"T1=${signal['t1']:.2f}  T2=${signal['t2']:.2f} ✓")
    else:
        print("  No BOS+FVG signal on synthetic set "
              "(retrace bar not yet touching FVG in this config) — OK")

    # Correlation helper: empty book → never blocked
    assert_true(
        not sniper._is_highly_correlated("INTRA", []),
        "Empty book should never be correlated"
    )
    print("  _is_highly_correlated (empty book): ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T12 — DISCORD  (payload validation; live send if webhook set and !skip-api)
# ══════════════════════════════════════════════════════════════════════════════

def test_t12_discord():
    from discord_helpers import send_options_signal_alert, send_simple_message
    import config

    # Validate send_options_signal_alert doesn't crash with None options_data
    # (it calls _send_to_discord internally — we just verify no exception)
    if config.DISCORD_WEBHOOK_URL and not SKIP_API:
        send_options_signal_alert(
            ticker="TEST", direction="bull",
            entry=500.0, stop=498.0, t1=504.0, t2=507.0,
            confidence=0.82, timeframe="5m", grade="A+",
            options_data=None
        )
        print("  send_options_signal_alert (no options_data): sent ✓")

        send_simple_message(
            "🧪 **War Machine Test Harness** — T12 Discord check ✓\n"
            "This is an automated test message, safe to dismiss."
        )
        print("  send_simple_message: sent ✓")
    elif SKIP_API:
        print("  --skip-api: skipping live Discord sends")
    else:
        print("  ⚠️  DISCORD_WEBHOOK_URL not set — skipping live send")

    # Always validate _send_to_discord doesn't raise on missing URL
    import config as _cfg
    orig = _cfg.DISCORD_WEBHOOK_URL
    _cfg.DISCORD_WEBHOOK_URL = ""
    try:
        send_simple_message("should silently no-op")
        print("  Missing webhook → silent no-op (no exception): ✓")
    finally:
        _cfg.DISCORD_WEBHOOK_URL = orig


# ══════════════════════════════════════════════════════════════════════════════
# T13 — LEARNING POLICY & CONFIDENCE GATE
# ══════════════════════════════════════════════════════════════════════════════

def test_t13_confidence_gate():
    from learning_policy import compute_confidence
    import config

    # Grade baseline values
    for grade, expected_base in [("A+", 0.85), ("A", 0.70), ("A-", 0.55)]:
        conf = compute_confidence(grade, "5m", "SPY")
        assert_true(0.0 < conf <= 1.0, f"{grade} confidence out of [0,1]")
        print(f"  compute_confidence({grade}, 5m) = {conf:.4f}")

    # Timeframe multiplier: 5m > 1m
    c5m = compute_confidence("A", "5m", "SPY")
    c1m = compute_confidence("A", "1m", "SPY")
    assert_true(c5m > c1m, "5m confidence must exceed 1m")
    print(f"  Timeframe mult: 5m={c5m:.4f} > 1m={c1m:.4f} ✓")

    # Gate replication (mirrors sniper._run_signal_pipeline)
    def gate(confidence, signal_type, grade):
        min_type  = (config.MIN_CONFIDENCE_INTRADAY
                     if signal_type == "CFW6_INTRADAY"
                     else config.MIN_CONFIDENCE_OR)
        min_grade = config.MIN_CONFIDENCE_BY_GRADE.get(grade, min_type)
        eff_min   = max(min_type, min_grade, config.CONFIDENCE_ABSOLUTE_FLOOR)
        return confidence >= eff_min, eff_min

    passed, eff = gate(0.85, "CFW6_OR", "A+")
    assert_true(passed, f"A+/OR/0.85 should PASS (eff_min={eff:.2f})")
    print(f"  Gate: A+/OR/0.85 → PASS (eff_min={eff:.2f}) ✓")

    passed2, eff2 = gate(0.60, "CFW6_INTRADAY", "A-")
    assert_true(not passed2,
                f"A-/INTRADAY/0.60 should FAIL (eff_min={eff2:.2f})")
    print(f"  Gate: A-/INTRADAY/0.60 → FAIL (eff_min={eff2:.2f}) ✓")

    passed3, eff3 = gate(0.55, "CFW6_OR", "A+")
    assert_true(not passed3,
                f"0.55 should fail absolute floor (eff_min={eff3:.2f})")
    print(f"  Gate: absolute floor {config.CONFIDENCE_ABSOLUTE_FLOOR} enforced ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T14 — EOD LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════

def test_t14_eod():
    from position_manager import PositionManager
    from cfw6_confirmation import clear_prev_day_cache, _prev_day_cache
    import sniper

    pm = PositionManager(db_path=_TEST_DB)

    id1 = pm.open_position(
        "SPY",  "bull", 499.0, 502.0, 498.0, 503.0,
        500.0, 498.0, 504.0, 507.0, 0.80, "A"
    )
    id2 = pm.open_position(
        "AAPL", "bear", 199.0, 202.0, 198.0, 203.0,
        200.0, 202.0, 196.0, 193.0, 0.75, "A+"
    )
    assert_eq(len(pm.get_open_positions()), 2, "Should have 2 open positions")
    print("  Opened 2 positions ✓")

    pm.close_all_eod({"SPY": 503.0, "AAPL": 199.0})
    assert_eq(len(pm.get_open_positions()), 0,
              "All positions must close after close_all_eod")
    print("  close_all_eod: ✓")

    stats = pm.get_daily_stats()
    assert_true(stats["trades"] >= 2, "Should have ≥2 today's trades")
    print(f"  EOD stats: {stats['trades']} trades | P&L=${stats['total_pnl']:.2f}")

    # PDH/PDL cache clear
    _prev_day_cache["FAKE"] = {"open": 1, "high": 2, "low": 0.5, "close": 1.5}
    clear_prev_day_cache()
    assert_eq(len(_prev_day_cache), 0, "PDH/PDL cache must be empty after clear")
    print("  clear_prev_day_cache: ✓")

    # Watching signals clear (memory + DB)
    sniper.watching_signals["FAKE"] = {"direction": "bull"}
    sniper.clear_watching_signals()
    assert_eq(len(sniper.watching_signals), 0,
              "watching_signals must be empty after clear")
    print("  clear_watching_signals: ✓")

    # Armed signals clear
    sniper.armed_signals["FAKE"] = {}
    sniper.clear_armed_signals()
    assert_eq(len(sniper.armed_signals), 0,
              "armed_signals must be empty after clear")
    print("  clear_armed_signals: ✓")


# ══════════════════════════════════════════════════════════════════════════════
# T15 — OPTIONS FILTER  (live EODHD API — skippable)
# ══════════════════════════════════════════════════════════════════════════════

def test_t15_options_live():
    import config
    if SKIP_API:
        print("  --skip-api: skipping live options chain test")
        return
    if not config.EODHD_API_KEY:
        print("  ⚠️  EODHD_API_KEY not set — skipping")
        return

    from options_filter import OptionsFilter
    f = OptionsFilter()

    chain = f.get_options_chain("SPY")
    assert_true(chain is not None, "Options chain fetch returned None")
    assert_true("data" in chain,   "Chain response missing 'data' key")
    expirations = list(chain.get("data", {}).keys())
    assert_true(len(expirations) > 0, "No expirations in chain")
    print(f"  SPY chain: {len(expirations)} expirations ✓")

    best = f.find_best_strike("SPY", "bull", 500.0, 504.0, stop_price=498.0)
    if best:
        print(f"  Best strike: ${best['strike']}  DTE={best['dte']}  "
              f"delta={best.get('delta', 0):.2f}  "
              f"IV={best.get('iv', 0)*100:.1f}%")
        ivr = best.get("ivr")
        if ivr is not None and best.get("ivr_reliable"):
            print(f"  IVR={ivr:.0f}  label={best['ivr_label']}  "
                  f"multiplier={best['ivr_multiplier']:.2f}x")
        else:
            print(f"  IVR: {best.get('ivr_label', 'N/A')} "
                  f"({best.get('ivr_obs', 0)} obs)")
        if best.get("uoa_detected"):
            print(f"  UOA: {best['uoa_label']}  "
                  f"multiplier={best['uoa_multiplier']:.2f}x")
        print(f"  GEX: {best.get('gex_label', 'N/A')}  "
              f"multiplier={best.get('gex_multiplier', 1.0):.2f}x")
    else:
        print("  No liquid SPY strike found (normal outside market hours) — OK")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    banner = "═" * 62
    print(f"\n{banner}")
    print("   WAR MACHINE — COMPONENT TEST HARNESS")
    print(banner)
    print(f"   Mode:  {'OFFLINE (--skip-api)' if SKIP_API else 'FULL (live API enabled)'}")
    if ONLY:
        print(f"   Only:  {ONLY}")
    print(f"   DB:    {_TEST_DB}")
    print(banner)

    run_test("T01", "Config & Environment",         test_t01_config)
    run_test("T02", "DB Connection",                test_t02_db)
    run_test("T03", "Data Manager",                 test_t03_data_manager)
    run_test("T04", "WS Feed (tick aggregation)",   test_t04_ws_feed)
    run_test("T05", "Trade Calculator",             test_t05_trade_calculator)
    run_test("T06", "BOS + FVG Engine",             test_t06_bos_fvg)
    run_test("T07", "CFW6 Confirmation",            test_t07_cfw6)
    run_test("T08", "Position Manager",             test_t08_position_manager)
    run_test("T09", "AI Learning Engine",           test_t09_ai_learning)
    run_test("T10", "Sniper: OR Path",              test_t10_sniper_or_path)
    run_test("T11", "Sniper: Intraday BOS",         test_t11_sniper_intraday)
    run_test("T12", "Discord Helpers",              test_t12_discord)
    run_test("T13", "Confidence Gate",              test_t13_confidence_gate)
    run_test("T14", "EOD Lifecycle",                test_t14_eod)
    run_test("T15", "Options Filter (live API)",    test_t15_options_live)

    # ── Summary ───────────────────────────────────────────────────────────────
    passes  = [r for r in RESULTS if r[2] == "PASS"]
    fails   = [r for r in RESULTS if r[2] == "FAIL"]
    errors  = [r for r in RESULTS if r[2] == "ERROR"]
    skipped = 15 - len(RESULTS)

    print(f"\n{banner}")
    print("   RESULTS SUMMARY")
    print(banner)
    for r in RESULTS:
        icon = "✅" if r[2] == "PASS" else ("❌" if r[2] == "FAIL" else "💥")
        print(f"  {icon}  {r[0]:3s} — {r[1]}")
        if r[3]:
            print(f"          → {r[3]}")
    print(f"{'─'*62}")
    print(f"  ✅ PASS: {len(passes)}   ❌ FAIL: {len(fails)}   "
          f"💥 ERROR: {len(errors)}   ⏭  SKIPPED: {skipped}")
    print(banner)

    try:
        os.unlink(_TEST_DB)
    except Exception:
        pass

    sys.exit(0 if not (fails or errors) else 1)
