#!/usr/bin/env python3
"""
debug_comprehensive.py - Comprehensive BOS/FVG signal flow debug

Replaces stale aggressive_bos_detector reference with app.mtf.scan_bos_fvg.
Shows every bar where a signal is generated with full detail.
Run from repo root:
    python scripts/debug_comprehensive.py [TICKER] [days_back]
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
except ImportError:
    pass

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List

from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
from app.mtf.bos_fvg_engine import scan_bos_fvg

ET = ZoneInfo("America/New_York")


def get_bars(ticker: str, days_back: int = 5) -> List[Dict]:
    end_date   = datetime.now(ET)
    start_date = end_date - timedelta(days=days_back)
    p    = ph()
    conn = get_conn()
    try:
        cursor = dict_cursor(conn)
        cursor.execute(f"""
            SELECT datetime, open, high, low, close, volume
            FROM intraday_bars
            WHERE ticker = {p}
              AND datetime >= {p}
              AND datetime <= {p}
            ORDER BY datetime ASC
        """, (ticker, start_date, end_date))
        bars = []
        for row in cursor.fetchall():
            dt = row["datetime"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if getattr(dt, 'tzinfo', None) is not None:
                dt = dt.replace(tzinfo=None)
            bars.append({
                "datetime": dt,
                "open":     float(row["open"]),
                "high":     float(row["high"]),
                "low":      float(row["low"]),
                "close":    float(row["close"]),
                "volume":   int(row["volume"]),
            })
        return bars
    finally:
        return_conn(conn)


def main():
    ticker    = sys.argv[1] if len(sys.argv) > 1 else 'AAPL'
    days_back = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    print(f"\n{'='*80}")
    print(f"DEBUG COMPREHENSIVE BOS/FVG  —  {ticker}  ({days_back}d)")
    print(f"{'='*80}\n")

    bars = get_bars(ticker, days_back=days_back)
    if not bars:
        print("No bars found in DB for this ticker/range.")
        return

    print(f"Loaded {len(bars):,} bars")
    print(f"Range : {bars[0]['datetime']}  →  {bars[-1]['datetime']}\n")

    signals_found = 0
    signal_log    = []

    for idx in range(50, len(bars)):
        current_bars = bars[:idx + 1]
        signal = scan_bos_fvg(ticker, current_bars)
        if signal:
            signals_found += 1
            signal_log.append(signal)
            ts    = signal.get('timestamp') or current_bars[-1]['datetime']
            dir_  = signal.get('direction', '?').upper()
            entry = signal.get('entry_price', 0)
            stop  = signal.get('stop_price', 0)
            t1    = signal.get('target_1', 0)
            t2    = signal.get('target_2', 0)
            grade = signal.get('confirmation_grade', signal.get('grade', '?'))
            score = signal.get('confirmation_score', signal.get('score', '?'))
            bos   = signal.get('bos_strength', 0)
            fvg   = signal.get('fvg_size_pct', 0)
            ctype = signal.get('candle_type', '?')

            print(f"\n✅ SIGNAL #{signals_found} @ {ts}")
            print(f"   Direction   : {dir_}")
            print(f"   Entry       : ${entry:.2f}  |  Stop : ${stop:.2f}")
            print(f"   T1          : ${t1:.2f}    |  T2   : ${t2:.2f}")
            print(f"   Grade/Score : {grade} / {score}")
            print(f"   BOS Strength: {bos*100:.2f}%  |  FVG: {fvg:.3f}%")
            print(f"   Candle Type : {ctype}")

    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Bars scanned  : {len(bars) - 50:,}")
    print(f"Signals found : {signals_found}")

    if signal_log:
        bull = sum(1 for s in signal_log if s.get('direction') == 'bull')
        bear = sum(1 for s in signal_log if s.get('direction') == 'bear')
        print(f"  Bull: {bull}  |  Bear: {bear}")
    print()


if __name__ == "__main__":
    main()
