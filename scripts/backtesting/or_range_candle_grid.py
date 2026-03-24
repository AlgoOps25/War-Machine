#!/usr/bin/env python3
"""
or_range_candle_grid.py
-----------------------
Candle-driven OR Range grid search for War Machine.

Pulls 1-min bars from the candle_cache table (same DB used by candle_cache.py),
computes real OR range from the first 30 minutes of each session, detects
BOS/FVG breakouts, applies full Phase 1.37 filters, simulates trades with ATR
stops + multi-R targets, then sweeps or_range_min_pct and or_range_max_pct
across a grid and ranks all combos by Total R.

Usage:
    python scripts/backtesting/or_range_candle_grid.py
    python scripts/backtesting/or_range_candle_grid.py --days 90
    python scripts/backtesting/or_range_candle_grid.py --days 60 --csv-out backtests/results/or_candle_grid.csv
    python scripts/backtesting/or_range_candle_grid.py --tickers NVDA AAPL TSLA
    python scripts/backtesting/or_range_candle_grid.py --db market_memory.db --timeframe 1m
"""

import argparse
import sys
sys.path.append('.')

import numpy as np
from datetime import datetime, timedelta, time as dtime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
from itertools import product
from collections import defaultdict

import pandas as pd

from app.data.db_connection import get_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Phase 1.37 baseline config (everything except OR range)
# ---------------------------------------------------------------------------
CFG = {
    "rvol_gate":        1.2,
    "confidence_gate":  0.50,
    "fvg_size_min_pct": 0.01,
    "dead_zone_start":  dtime(9, 30),
    "dead_zone_end":    dtime(9, 45),
    "eod_cutoff":       dtime(15, 30),
    "atr_mult":         2.0,
    "t1_mult":          2.0,
    "t2_mult":          3.5,
    "or_minutes":       30,
    "days_back":        90,
}

OR_MIN_VALUES = [0.0, 0.1, 0.2, 0.3, 0.5]
OR_MAX_VALUES = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 99.0]
CURRENT_MIN   = 0.2
CURRENT_MAX   = 3.0

# ---------------------------------------------------------------------------
# DB helpers  (candle_cache table)
# ---------------------------------------------------------------------------

def get_all_tickers(db_path: str, timeframe: str = "1m") -> List[str]:
    p = ph()
    conn = get_conn(db_path)
    try:
        cur = dict_cursor(conn)
        cur.execute(
            f"SELECT DISTINCT ticker FROM candle_cache WHERE timeframe={p} ORDER BY ticker",
            (timeframe,)
        )
        rows = cur.fetchall()
        # dict_cursor returns Row objects for SQLite — handle both
        return [r["ticker"] if isinstance(r, dict) else r[0] for r in rows]
    finally:
        conn.close()


def get_bars(ticker: str, start: datetime, end: datetime,
             db_path: str, timeframe: str = "1m") -> List[Dict]:
    p = ph()
    conn = get_conn(db_path)
    try:
        cur = dict_cursor(conn)
        cur.execute(
            f"SELECT datetime,open,high,low,close,volume FROM candle_cache"
            f" WHERE ticker={p} AND timeframe={p}"
            f" AND datetime>={p} AND datetime<={p}"
            f" ORDER BY datetime ASC",
            (ticker, timeframe, start, end)
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    bars = []
    for r in rows:
        # Support both dict (psycopg2 RealDictCursor) and sqlite3.Row
        if isinstance(r, dict):
            dt, o, h, l, c, v = r["datetime"], r["open"], r["high"], r["low"], r["close"], r["volume"]
        else:
            dt, o, h, l, c, v = r[0], r[1], r[2], r[3], r[4], r[5]

        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc).astimezone(ET)
        else:
            dt = dt.astimezone(ET)

        bars.append({"datetime": dt, "open": float(o), "high": float(h),
                     "low": float(l), "close": float(c), "volume": int(v)})
    return bars


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def calc_atr(bars: List[Dict], period: int = 14) -> float:
    if len(bars) < period + 1:
        return bars[-1]["close"] * 0.01 if bars else 0.01
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs[-period:]))


def calc_rvol(bars: List[Dict], lookback: int = 20) -> float:
    if len(bars) < lookback + 1:
        return 0.0
    avg = np.mean([b["volume"] for b in bars[-lookback-1:-1]])
    return bars[-1]["volume"] / avg if avg > 0 else 0.0


def calc_confidence(bars: List[Dict], direction: str) -> float:
    if len(bars) < 20:
        return 0.5
    closes = [b["close"] for b in bars[-15:]]
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    gains  = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_g  = np.mean(gains)  if gains  else 0
    avg_l  = np.mean(losses) if losses else 1e-9
    rsi    = 100 - 100 / (1 + avg_g / avg_l)
    score  = 0.5
    if direction == "bull" and rsi < 40:
        score += 0.15
    elif direction == "bear" and rsi > 60:
        score += 0.15
    if calc_rvol(bars) >= 1.5:
        score += 0.10
    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Opening Range
# ---------------------------------------------------------------------------

def compute_or_range(session_bars: List[Dict], or_minutes: int = 30) -> Optional[Dict]:
    first = session_bars[0]["datetime"]
    cutoff = first.replace(hour=9, minute=30 + or_minutes, second=0, microsecond=0)
    or_bars = [b for b in session_bars if b["datetime"] < cutoff]
    if not or_bars:
        return None
    or_high = max(b["high"] for b in or_bars)
    or_low  = min(b["low"]  for b in or_bars)
    mid     = (or_high + or_low) / 2
    if mid == 0:
        return None
    return {"or_high": or_high, "or_low": or_low,
            "or_range_pct": (or_high - or_low) / mid * 100}


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def detect_signals_in_session(session_bars, or_info, ticker, date) -> List[Dict]:
    signals = []
    or_high, or_low = or_info["or_high"], or_info["or_low"]
    or_range_pct    = or_info["or_range_pct"]
    post_or = [b for b in session_bars
               if b["datetime"].time() >= dtime(9, 30 + CFG["or_minutes"])]

    for i, bar in enumerate(post_or):
        t = bar["datetime"].time()
        if CFG["dead_zone_start"] <= t < CFG["dead_zone_end"]:
            continue
        if t >= CFG["eod_cutoff"]:
            break

        try:
            idx_in_session = session_bars.index(bar)
        except ValueError:
            continue
        bars_so_far = session_bars[:idx_in_session + 1]
        if len(bars_so_far) < 10:
            continue

        prev = post_or[i - 1] if i > 0 else None

        # Bullish BOS breakout
        if bar["close"] > or_high and (prev is None or prev["close"] <= or_high):
            fvg_size = 0.0
            if i >= 2:
                fl, fh = post_or[i-2]["high"], bar["low"]
                if fh > fl:
                    fvg_size = (fh - fl) / fl * 100
            signals.append({"ticker": ticker, "date": date, "direction": "bull",
                             "entry_price": bar["close"], "entry_bar": bar,
                             "entry_idx": idx_in_session, "or_range_pct": or_range_pct,
                             "fvg_size_pct": fvg_size, "bars_so_far": bars_so_far})
            break

        # Bearish BOS breakout
        if bar["close"] < or_low and (prev is None or prev["close"] >= or_low):
            fvg_size = 0.0
            if i >= 2:
                fh, fl = post_or[i-2]["low"], bar["high"]
                if fh > fl:
                    fvg_size = (fh - fl) / fh * 100
            signals.append({"ticker": ticker, "date": date, "direction": "bear",
                             "entry_price": bar["close"], "entry_bar": bar,
                             "entry_idx": idx_in_session, "or_range_pct": or_range_pct,
                             "fvg_size_pct": fvg_size, "bars_so_far": bars_so_far})
            break

    return signals


# ---------------------------------------------------------------------------
# Trade simulation
# ---------------------------------------------------------------------------

def simulate_trade(sig: Dict, session_bars: List[Dict]) -> Optional[Dict]:
    entry_price = sig["entry_price"]
    direction   = sig["direction"]
    entry_idx   = sig["entry_idx"]

    atr = calc_atr(sig["bars_so_far"])
    if atr == 0:
        return None

    stop_dist = atr * CFG["atr_mult"]
    if direction == "bull":
        stop = entry_price - stop_dist
        t1   = entry_price + stop_dist * CFG["t1_mult"]
        t2   = entry_price + stop_dist * CFG["t2_mult"]
    else:
        stop = entry_price + stop_dist
        t1   = entry_price - stop_dist * CFG["t1_mult"]
        t2   = entry_price - stop_dist * CFG["t2_mult"]

    future_bars = session_bars[entry_idx + 1:]
    exit_price  = future_bars[-1]["close"] if future_bars else entry_price
    exit_reason = "EOD"

    for bar in future_bars:
        if bar["datetime"].time() >= dtime(15, 55):
            exit_price, exit_reason = bar["close"], "EOD"
            break
        if direction == "bull":
            if bar["low"] <= stop:   exit_price, exit_reason = stop, "STOP"; break
            if bar["high"] >= t2:    exit_price, exit_reason = t2,   "T2";   break
            if bar["high"] >= t1:    exit_price, exit_reason = t1,   "T1";   break
        else:
            if bar["high"] >= stop:  exit_price, exit_reason = stop, "STOP"; break
            if bar["low"] <= t2:     exit_price, exit_reason = t2,   "T2";   break
            if bar["low"] <= t1:     exit_price, exit_reason = t1,   "T1";   break

    r = ((exit_price - entry_price) / stop_dist
         if direction == "bull"
         else (entry_price - exit_price) / stop_dist)

    return {
        "ticker":       sig["ticker"],
        "date":         sig["date"],
        "direction":    direction,
        "entry_price":  entry_price,
        "exit_price":   exit_price,
        "exit_reason":  exit_reason,
        "r_multiple":   round(r, 4),
        "win":          int(r > 0),
        "or_range_pct": sig["or_range_pct"],
        "fvg_size_pct": sig["fvg_size_pct"],
        "rvol":         calc_rvol(sig["bars_so_far"]),
        "confidence":   calc_confidence(sig["bars_so_far"], direction),
        "entry_hour":   sig["entry_bar"]["datetime"].hour,
        "entry_minute": sig["entry_bar"]["datetime"].minute,
    }


# ---------------------------------------------------------------------------
# Baseline filters (all except OR range)
# ---------------------------------------------------------------------------

def passes_baseline_filters(trade: Dict) -> bool:
    if trade["rvol"] < CFG["rvol_gate"]:
        return False
    if trade["confidence"] < CFG["confidence_gate"]:
        return False
    if trade["fvg_size_pct"] < CFG["fvg_size_min_pct"]:
        return False
    t = dtime(trade["entry_hour"], trade["entry_minute"])
    if CFG["dead_zone_start"] <= t < CFG["dead_zone_end"]:
        return False
    if t >= CFG["eod_cutoff"]:
        return False
    return True


def stats(trades: List[Dict]) -> Dict:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0}
    rs   = [t["r_multiple"] for t in trades]
    wins = sum(t["win"] for t in trades)
    return {"trades": len(trades),
            "win_rate": round(wins / len(trades) * 100, 1),
            "avg_r":    round(float(np.mean(rs)), 3),
            "total_r":  round(float(np.sum(rs)), 2)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Candle-driven OR range grid search")
    parser.add_argument("--db",         default="market_memory.db")
    parser.add_argument("--timeframe",  default="1m",
                        help="Candle timeframe stored in candle_cache (default: 1m)")
    parser.add_argument("--days",       type=int, default=CFG["days_back"])
    parser.add_argument("--tickers",    nargs="+", default=None)
    parser.add_argument("--csv-out",    default=None)
    parser.add_argument("--min-trades", type=int, default=10)
    args = parser.parse_args()

    end_dt   = datetime.now(ET)
    start_dt = end_dt - timedelta(days=args.days)

    tickers = args.tickers or get_all_tickers(args.db, args.timeframe)
    if not tickers:
        print(f"[ERROR] No tickers found in candle_cache for timeframe='{args.timeframe}'.")
        print(f"        Check that market_memory.db exists and has data.")
        sys.exit(1)

    print(f"Scanning {len(tickers)} tickers | {args.days} days | timeframe={args.timeframe}\n")

    all_trades: List[Dict] = []

    for ticker in tickers:
        bars = get_bars(ticker, start_dt, end_dt, args.db, args.timeframe)
        if not bars:
            continue

        by_date: Dict[str, List[Dict]] = defaultdict(list)
        for b in bars:
            by_date[b["datetime"].date().isoformat()].append(b)

        for date_str, session in sorted(by_date.items()):
            if len(session) < CFG["or_minutes"] + 30:
                continue
            or_info = compute_or_range(session, CFG["or_minutes"])
            if or_info is None:
                continue
            for sig in detect_signals_in_session(session, or_info, ticker, date_str):
                trade = simulate_trade(sig, session)
                if trade:
                    all_trades.append(trade)

    print(f"Total simulated trades (no filters): {len(all_trades)}")

    if not all_trades:
        print("\n[ERROR] No trades found. Is candle_cache populated?")
        print("        Run the main scanner to populate it, then retry.")
        sys.exit(1)

    base_filtered = [t for t in all_trades if passes_baseline_filters(t)]
    print(f"After baseline filters (no OR gate):  {len(base_filtered)}\n")

    current   = [t for t in base_filtered
                 if CURRENT_MIN <= t["or_range_pct"] <= CURRENT_MAX]
    cur_stats = stats(current)

    results = []
    for or_min, or_max in product(OR_MIN_VALUES, OR_MAX_VALUES):
        if or_min >= or_max:
            continue
        subset = [t for t in base_filtered
                  if or_min <= t["or_range_pct"] <= or_max]
        s = stats(subset)
        if s["trades"] < args.min_trades:
            continue
        results.append({
            "or_min": or_min, "or_max": or_max, **s,
            "delta_total_r": round(s["total_r"] - cur_stats["total_r"], 2),
            "delta_trades":  s["trades"] - cur_stats["trades"],
            "delta_avg_r":   round(s["avg_r"] - cur_stats["avg_r"], 3),
        })

    if not results:
        print("[ERROR] No grid combinations met the min-trades threshold. Try --min-trades 5")
        sys.exit(1)

    results_df = pd.DataFrame(results).sort_values("total_r", ascending=False).reset_index(drop=True)

    print("=" * 85)
    print(" OR RANGE CANDLE GRID SEARCH  —  sorted by Total R")
    print(f" {len(tickers)} tickers × {args.days} days | all Phase 1.37 filters ON (except OR gate)")
    print("=" * 85)
    print(f"  Current : or_min={CURRENT_MIN}  or_max={CURRENT_MAX}  →  "
          f"{cur_stats['trades']} trades | {cur_stats['win_rate']:.1f}% WR | "
          f"{cur_stats['avg_r']:+.3f} avg R | {cur_stats['total_r']:+.2f} total R")
    print()
    print(f"  {'Rank':<5} {'or_min':>7} {'or_max':>7} {'Trades':>7} {'WR%':>7} "
          f"{'Avg R':>8} {'Total R':>9} {'ΔTrades':>8} {'ΔAvgR':>8} {'ΔTotalR':>9}")
    print("-" * 85)

    for i, row in results_df.iterrows():
        marker    = " ← current" if (row["or_min"] == CURRENT_MIN and row["or_max"] == CURRENT_MAX) else ""
        max_label = "∞" if row["or_max"] >= 99 else f"{row['or_max']:.1f}"
        print(f"  {i+1:<5} {row['or_min']:>7.2f} {max_label:>7} "
              f"{int(row['trades']):>7} {row['win_rate']:>6.1f}% "
              f"{row['avg_r']:>+8.3f} {row['total_r']:>+9.2f} "
              f"{int(row['delta_trades']):>+8} {row['delta_avg_r']:>+8.3f} "
              f"{row['delta_total_r']:>+9.2f}{marker}")

    print("=" * 85)
    best_total = results_df.iloc[0]
    best_avg   = results_df.loc[results_df["avg_r"].idxmax()]
    print(f"\n  Best Total R : or_min={best_total['or_min']}  or_max={best_total['or_max']}  "
          f"→ {best_total['total_r']:+.2f} Total R | {int(best_total['trades'])} trades")
    print(f"  Best Avg R   : or_min={best_avg['or_min']}  or_max={best_avg['or_max']}  "
          f"→ {best_avg['avg_r']:+.3f} Avg R | {int(best_avg['trades'])} trades")
    print()

    ranges = [t["or_range_pct"] for t in base_filtered]
    if ranges:
        print("  OR Range distribution (filtered universe):")
        for lo, hi in [(0,1),(1,2),(2,3),(3,5),(5,99)]:
            bucket = [r for r in ranges if lo <= r < hi]
            label  = f"{lo}–{hi}%" if hi < 99 else f">{lo}%"
            print(f"    {label:>8}: {len(bucket):>4} trades ({len(bucket)/len(ranges)*100:.1f}%)")
        print()

    if args.csv_out:
        results_df.to_csv(args.csv_out, index=False)
        print(f"  Results saved to: {args.csv_out}\n")


if __name__ == "__main__":
    main()
