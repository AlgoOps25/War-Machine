#!/usr/bin/env python3
"""
Debug BOS Scan - See what the detector is finding
"""

import sys
sys.path.append('.')

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List

from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
from app.signals.aggressive_bos_detector import get_aggressive_detector

ET = ZoneInfo("America/New_York")

def get_bars(ticker: str, days_back: int = 5) -> List[Dict]:
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=days_back)
    
    p = ph()
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
        
        rows = cursor.fetchall()
        
        bars = []
        for row in rows:
            dt = row["datetime"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            
            bars.append({
                "datetime": dt,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"])
            })
        
        return bars
    
    finally:
        return_conn(conn)


def main():
    ticker = 'AAPL'
    print(f"\n{'='*80}")
    print(f"DEBUG BOS SCAN: {ticker}")
    print(f"{'='*80}\n")
    
    bars = get_bars(ticker, days_back=5)
    
    if not bars:
        print("No bars loaded!")
        return
    
    print(f"Loaded {len(bars):,} bars")
    print(f"Date range: {bars[0]['datetime']} to {bars[-1]['datetime']}\n")
    
    detector = get_aggressive_detector()
    
    # Scan through bars and track what happens
    breakouts_found = 0
    fvgs_found = 0
    confirmations_found = 0
    signals_found = 0
    
    for idx in range(50, len(bars)):
        current_bars = bars[:idx+1]
        
        # Check for breakout
        breakout = detector.detect_breakout(current_bars)
        if breakout:
            breakouts_found += 1
            print(f"\n[{idx}] BREAKOUT DETECTED:")
            print(f"  Time: {bars[idx]['datetime']}")
            print(f"  Direction: {breakout['direction']}")
            print(f"  Level: {breakout['breakout_level']:.2f}")
            print(f"  Price: {breakout['break_price']:.2f}")
            print(f"  Strength: {breakout['strength']*100:.2f}%")
            
            # Check for FVG
            fvg = detector.find_fvg(current_bars, breakout['bar_idx'], breakout['direction'])
            if fvg:
                fvgs_found += 1
                print(f"  ✓ FVG FOUND:")
                print(f"    FVG Range: {fvg['fvg_low']:.2f} - {fvg['fvg_high']:.2f}")
                print(f"    FVG Size: {fvg['fvg_size_pct']:.3f}%")
                
                # Check for confirmation
                confirmation = detector.check_confirmation(current_bars, fvg)
                if confirmation:
                    confirmations_found += 1
                    print(f"    ✓ CONFIRMATION:")
                    print(f"      Grade: {confirmation['grade']}")
                    print(f"      Score: {confirmation['score']}")
                    print(f"      Entry: {confirmation['entry_price']:.2f}")
                    
                    signals_found += 1
                else:
                    print(f"    ✗ No confirmation yet")
            else:
                print(f"  ✗ No FVG found")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Bars scanned: {len(bars) - 50:,}")
    print(f"Breakouts found: {breakouts_found}")
    print(f"FVGs found: {fvgs_found}")
    print(f"Confirmations found: {confirmations_found}")
    print(f"Complete signals: {signals_found}")
    print()


if __name__ == "__main__":
    main()
