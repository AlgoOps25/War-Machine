#!/usr/bin/env python3
"""
or_range_candle_grid.py
-----------------------
Candle-driven OR Range grid search for War Machine.

Difference from or_range_grid.py:
  - Pulls raw 1-min bars from intraday_bars (production DB)
  - Computes real OR range from the actual first-30-min candles each day
  - Detects BOS/FVG signals using the same logic as backtest_optimized_params.py
  - Applies full Phase 1.37 filters (RVOL, Grade-proxy, confidence, dead zone,
    EOD cutoff, FVG size)
  - Simulates trade outcomes with ATR stops + multi-R targets
  - Sweeps or_range_min_pct and or_range_max_pct across a grid
  - Ranks all combos by Total R; prints table + optional CSV

Usage:
    python scripts/backtesting/or_range_candle_grid.py
    python scripts/backtesting/or_range_candle_grid.py --days 90
    python scripts/backtesting/or_range_candle_grid.py --days 60 --csv-out backtests/results/or_candle_grid.csv
    python scripts/backtesting/or_range_candle_grid.py --tickers NVDA AAPL TSLA
"""

import argparse
import sys
sys.path.append('.')

import numpy as np
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple
from itertools import product
from collections import defaultdict

import pandas as pd

from app.data.db_connection import get_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Phase 1.37 baseline config (everything except OR range)
# ---------------------------------------------------------------------------
CFG = {
    "rvol_gate":            1.2,    # intraday RVOL vs 20-bar avg
    "confidence_gate":      0.50,   # composite confidence score
    "fvg_size_min_pct":     0.01,   # % of price
    "dead_zone_start":      dtime(9, 30),
    "dead_zone_end":        dtime(9, 45),
    "eod_cutoff":           dtime(15, 30),
    "atr_mult":             2.0,    # stop = atr_mult * ATR
    "t1_mult":              2.0,    # T1 target
    "t2_mult":              3.5,    # T2 target
    "or_minutes":           30,     # opening range = first N minutes
    "days_back":            90,
}

# Grid values
OR_MIN_VALUES = [0.0, 0.1, 0.2, 0.3, 0.5]
OR_MAX_VALUES = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 99.0]
CURRENT_MIN   = 0.2
CURRENT_MAX   = 3.0

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_all_tickers(db_path: str) -> List[str]:
    p = ph()
    conn = get_conn(db_path)
    try:
        cur = dict_cursor(conn)
        cur.execute("SELECT DISTINCT ticker FROM intraday_bars ORDER BY ticker")
        return [r["ticker"] for r in cur.fetchall()]
    finally:
        conn.close()


def get_bars(ticker: str, start: datetime, end: datetime, db_path: str) -> List[Dict]:
    p = ph()
    conn = get_conn(db_path)
    try:
        cur = dict_cursor(conn)
        cur.execute(
            f"SELECT datetime,open,high,low,close,volume FROM intraday_bars"
            f" WHERE ticker={p} AND datetime>={p} AND datetime<={p}"
            f" ORDER BY datetime ASC",
            (ticker, start, end)
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    bars = []
    for r in rows:
        dt = r["datetime"]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc).astimezone(ET)
        else:
            dt = dt.astimezone(ET)
        bars.append({"datetime": dt, "open": float(r["open"]),
                     "high": float(r["high"]), "low": float(r["low"]),
                     "close": float(r["close"]), "volume": int(r["volume"])})
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
    """Current bar volume / avg of previous lookback bars."""
    if len(bars) < lookback + 1:
        return 0.0
    avg = np.mean([b["volume"] for b in bars[-lookback-1:-1]])
    return bars[-1]["volume"] / avg if avg > 0 else 0.0


def calc_confidence(bars: List[Dict], direction: str) -> float:
    """Simplified confidence matching Phase 1.37 scorer."""
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
    rvol = calc_rvol(bars)
    if rvol >= 1.5:
        score += 0.10
    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Opening Range per day
# ---------------------------------------------------------------------------

def compute_or_range(session_bars: List[Dict], or_minutes: int = 30) -> Optional[Dict]:
    """Return OR high, low, and range % from first or_minutes of session."""
    cutoff = (session_bars[0]["datetime"].replace(
        hour=9, minute=30 + or_minutes, second=0, microsecond=0
    ))
    or_bars = [b for b in session_bars if b["datetime"] < cutoff]
    if not or_bars:
        return None
    or_high = max(b["high"] for b in or_bars)
    or_low  = min(b["low"]  for b in or_bars)
    mid     = (or_high + or_low) / 2
    if mid == 0:
        return None
    return {
        "or_high":      or_high,
        "or_low":       or_low,
        "or_range_pct": (or_high - or_low) / mid * 100,
    }


# ---------------------------------------------------------------------------
# Signal detection (BOS / FVG breakout of OR)
# ---------------------------------------------------------------------------

def detect_signals_in_session(
    session_bars: List[Dict],
    or_info: Dict,
    ticker: str,
    date: str,
) -> List[Dict]:
    """
    After OR closes, look for BOS/FVG breakouts of the OR high/low.
    Returns list of candidate trade dicts.
    """
    signals = []
    or_high = or_info["or_high"]
    or_low  = or_info["or_low"]
    or_range_pct = or_info["or_range_pct"]

    # Only look at post-OR bars
    post_or = [b for b in session_bars if b["datetime"].time() >= dtime(9, 30 + CFG["or_minutes"])]

    for i, bar in enumerate(post_or):
        t = bar["datetime"].time()
        # Dead zone
        if CFG["dead_zone_start"] <= t < CFG["dead_zone_end"]:
            continue
        # EOD cutoff
        if t >= CFG["eod_cutoff"]:
            break

        bars_so_far = session_bars[:session_bars.index(bar) + 1]
        if len(bars_so_far) < 10:
            continue

        prev = post_or[i - 1] if i > 0 else None

        # Bullish BOS: close breaks above OR high
        if bar["close"] > or_high and (prev is None or prev["close"] <= or_high):
            # FVG check: gap between bar[-2] and current
            fvg_size = 0.0
            if i >= 2:
                fvg_low  = post_or[i-2]["high"]
                fvg_high = bar["low"]
                if fvg_high > fvg_low:
                    fvg_size = (fvg_high - fvg_low) / fvg_low * 100
            signals.append({
                "ticker":        ticker,
                "date":          date,
                "direction":     "bull",
                "entry_price":   bar["close"],
                "entry_bar":     bar,
                "entry_idx":     session_bars.index(bar),
                "or_range_pct":  or_range_pct,
                "fvg_size_pct":  fvg_size,
                "bars_so_far":   bars_so_far,
            })
            break  # one trade per session per direction

        # Bearish BOS: close breaks below OR low
        if bar["close"] < or_low and (prev is None or prev["close"] >= or_low):
            fvg_size = 0.0
            if i >= 2:
                fvg_high = post_or[i-2]["low"]
                fvg_low  = bar["high"]
                if fvg_high > fvg_low:
                    fvg_size = (fvg_high - fvg_low) / fvg_high * 100
            signals.append({
                "ticker":        ticker,
                "date":          date,
                "direction":     "bear",
                "entry_price":   bar["close"],
                "entry_bar":     bar,
                "entry_idx":     session_bars.index(bar),
                "or_range_pct":  or_range_pct,
                "fvg_size_pct":  fvg_size,
                "bars_so_far":   bars_so_far,
            })
            break

    return signals


# ---------------------------------------------------------------------------
# Trade simulation
# ---------------------------------------------------------------------------

def simulate_trade(sig: Dict, all_session_bars: List[Dict]) -> Optional[Dict]:
    """Simulate a trade from signal bar to EOD or stop/target hit."""
    entry_price = sig["entry_price"]
    direction   = sig["direction"]
    entry_idx   = sig["entry_idx"]

    atr = calc_atr(sig["bars_so_far"])
    if atr == 0:
        return None

    stop_dist = atr * CFG["atr_mult"]
    t1_dist   = stop_dist * CFG["t1_mult"]
    t2_dist   = stop_dist * CFG["t2_mult"]

    if direction == "bull":
        stop = entry_price - stop_dist
        t1   = entry_price + t1_dist
        t2   = entry_price + t2_dist
    else:
        stop = entry_price + stop_dist
        t1   = entry_price - t1_dist
        t2   = entry_price - t2_dist

    future_bars = all_session_bars[entry_idx + 1:]
    exit_price  = future_bars[-1]["close"] if future_bars else entry_price
    exit_reason = "EOD"

    for bar in future_bars:
        t = bar["datetime"].time()
        if t >= dtime(15, 55):
            exit_price  = bar["close"]
            exit_reason = "EOD"
            break
        if direction == "bull":
            if bar["low"] <= stop:
                exit_price, exit_reason = stop, "STOP"
                break
            if bar["high"] >= t2:
                exit_price, exit_reason = t2, "T2"
                break
            if bar["high"] >= t1:
                exit_price, exit_reason = t1, "T1"
                break
        else:
            if bar["high"] >= stop:
                exit_price, exit_reason = stop, "STOP"
                break
            if bar["low"] <= t2:
                exit_price, exit_reason = t2, "T2"
                break
            if bar["low"] <= t1:
                exit_price, exit_reason = t1, "T1"
                break

    if direction == "bull":
        r = (exit_price - entry_price) / stop_dist
    else:
        r = (entry_price - exit_price) / stop_dist

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
# Non-OR baseline filters
# ---------------------------------------------------------------------------

def passes_baseline_filters(trade: Dict) -> bool:
    if trade["rvol"] < CFG["rvol_gate"]:
        return False
    if trade["confidence"] < CFG["confidence_gate"]:
        return False
    if trade["fvg_size_pct"] < CFG["fvg_size_min_pct"]:
        return False
    h, m = trade["entry_hour"], trade["entry_minute"]
    t = dtime(h, m)
    if CFG["dead_zone_start"] <= t < CFG["dead_zone_end"]:
        return False
    if t >= CFG["eod_cutoff"]:
        return False
    return True


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def stats(trades: List[Dict]) -> Dict:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0}
    rs = [t["r_multiple"] for t in trades]
    wins = sum(t["win"] for t in trades)
    return {
        "trades":   len(trades),
        "win_rate": round(wins / len(trades) * 100, 1),
        "avg_r":    round(float(np.mean(rs)), 3),
        "total_r":  round(float(np.sum(rs)), 2),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Candle-driven OR range grid search")
    parser.add_argument("--db", default="market_memory.db")
    parser.add_argument("--days", type=int, default=CFG["days_back"])
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Override ticker list (default: all in DB)")
    parser.add_argument("--csv-out", default=None)
    parser.add_argument("--min-trades", type=int, default=10)
    args = parser.parse_args()

    end_dt   = datetime.now(ET)
    start_dt = end_dt - timedelta(days=args.days)

    tickers = args.tickers or get_all_tickers(args.db)
    print(f"Scanning {len(tickers)} tickers over past {args.days} days...\n")

    # ── Build raw trade universe ────────────────────────────────────────────
    all_trades: List[Dict] = []

    for ticker in tickers:
        bars = get_bars(ticker, start_dt, end_dt, args.db)
        if not bars:
            continue

        # Group into sessions (trading days)
        by_date: Dict[str, List[Dict]] = defaultdict(list)
        for b in bars:
            by_date[b["datetime"].date().isoformat()].append(b)

        for date_str, session in sorted(by_date.items()):
            # Need at least OR minutes + 30 more bars to be useful
            if len(session) < CFG["or_minutes"] + 30:
                continue

            or_info = compute_or_range(session, CFG["or_minutes"])
            if or_info is None:
                continue

            signals = detect_signals_in_session(session, or_info, ticker, date_str)
            for sig in signals:
                trade = simulate_trade(sig, session)
                if trade:
                    all_trades.append(trade)

    print(f"Total simulated trades (no filters): {len(all_trades)}")

    if not all_trades:
        print("\n[ERROR] No trades found. Check that intraday_bars has data.")
        sys.exit(1)

    # ── Apply baseline filters (all except OR range) ────────────────────────
    base_filtered = [t for t in all_trades if passes_baseline_filters(t)]
    print(f"After baseline filters (no OR gate):  {len(base_filtered)}")
    print()

    # ── Current setting reference ───────────────────────────────────────────
    current = [t for t in base_filtered
               if CURRENT_MIN <= t["or_range_pct"] <= CURRENT_MAX]
    cur_stats = stats(current)

    # ── Grid search ─────────────────────────────────────────────────────────
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
            "or_min":         or_min,
            "or_max":         or_max,
            **s,
            "delta_total_r":  round(s["total_r"]  - cur_stats["total_r"],  2),
            "delta_trades":   s["trades"] - cur_stats["trades"],
            "delta_avg_r":    round(s["avg_r"] - cur_stats["avg_r"], 3),
        })

    results_df = pd.DataFrame(results).sort_values("total_r", ascending=False).reset_index(drop=True)

    # ── Print report ────────────────────────────────────────────────────────
    print("=" * 85)
    print(" OR RANGE CANDLE GRID SEARCH  —  sorted by Total R")
    print(f" {len(tickers)} tickers × {args.days} days | all Phase 1.37 filters ON (except OR gate)")
    print("=" * 85)
    print(f"  Current setting : or_min={CURRENT_MIN}  or_max={CURRENT_MAX}")
    print(f"  Current result  : {cur_stats['trades']} trades | "
          f"{cur_stats['win_rate']:.1f}% WR | "
          f"{cur_stats['avg_r']:+.3f} avg R | "
          f"{cur_stats['total_r']:+.2f} total R")
    print()
    print(f"  {'Rank':<5} {'or_min':>7} {'or_max':>7} {'Trades':>7} {'WR%':>7} "
          f"{'Avg R':>8} {'Total R':>9} {'ΔTrades':>8} {'ΔAvgR':>8} {'ΔTotalR':>9}")
    print("-" * 85)

    for i, row in results_df.iterrows():
        marker = " ← current" if (
            row["or_min"] == CURRENT_MIN and row["or_max"] == CURRENT_MAX
        ) else ""
        max_label = "∞" if row["or_max"] >= 99 else f"{row['or_max']:.1f}"
        print(
            f"  {i+1:<5} {row['or_min']:>7.2f} {max_label:>7} "
            f"{int(row['trades']):>7} {row['win_rate']:>6.1f}% "
            f"{row['avg_r']:>+8.3f} {row['total_r']:>+9.2f} "
            f"{int(row['delta_trades']):>+8} {row['delta_avg_r']:>+8.3f} "
            f"{row['delta_total_r']:>+9.2f}{marker}"
        )

    print("=" * 85)

    best_total = results_df.iloc[0]
    best_avg   = results_df.loc[results_df["avg_r"].idxmax()]
    print(f"\n  Best Total R : or_min={best_total['or_min']}  or_max={best_total['or_max']}  "
          f"→ {best_total['total_r']:+.2f} Total R | {int(best_total['trades'])} trades")
    print(f"  Best Avg R   : or_min={best_avg['or_min']}  or_max={best_avg['or_max']}  "
          f"→ {best_avg['avg_r']:+.3f} Avg R | {int(best_avg['trades'])} trades")
    print()

    # OR range distribution breakdown (for reference)
    ranges = [t["or_range_pct"] for t in base_filtered]
    if ranges:
        print("  OR Range distribution (filtered universe):")
        for lo, hi in [(0, 1), (1, 2), (2, 3), (3, 5), (5, 99)]:
            bucket = [r for r in ranges if lo <= r < hi]
            label = f"{lo}–{hi}%" if hi < 99 else f">{lo}%"
            print(f"    {label:>8}: {len(bucket):>4} trades ({len(bucket)/len(ranges)*100:.1f}%)")
        print()

    if args.csv_out:
        results_df.to_csv(args.csv_out, index=False)
        print(f"  Results saved to: {args.csv_out}\n")


if __name__ == "__main__":
    main()
