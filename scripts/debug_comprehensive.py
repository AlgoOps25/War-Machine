#!/usr/bin/env python3
"""
Debug Comprehensive Detector - See confidence grading
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
    print(f"DEBUG AGGRESSIVE BOS DETECTOR (WITH STATE)")
    print(f"{'='*80}\n")
    
    bars = get_bars(ticker, days_back=5)
    
    if not bars:
        print("No bars loaded!")
        return
    
    print(f"Loaded {len(bars):,} bars")
    print(f"Date range: {bars[0]['datetime']} to {bars[-1]['datetime']}\n")
    
    # Create ONE detector instance and reuse it
    detector = get_aggressive_detector()
    
    signals_found = 0
    fvg_tracking = []
    
    # Scan through bars progressively
    for idx in range(50, len(bars)):
        current_bars = bars[:idx+1]
        
        # Call scan with progressively longer bar history
        signal = detector.scan(ticker, current_bars)
        
        # Track FVG state
        if detector.active_fvg is not None:
            if not fvg_tracking or fvg_tracking[-1]['idx'] != detector.fvg_found_at:
                fvg_tracking.append({
                    'idx': detector.fvg_found_at,
                    'time': bars[detector.fvg_found_at]['datetime'],
                    'direction': detector.active_fvg['direction'],
                    'fvg_low': detector.active_fvg['fvg_low'],
                    'fvg_high': detector.active_fvg['fvg_high'],
                    'confirmed': False
                })
        
        if signal:
            signals_found += 1
            
            # Mark FVG as confirmed
            if fvg_tracking:
                fvg_tracking[-1]['confirmed'] = True
            
            print(f"\n✅ SIGNAL #{signals_found} at {signal['timestamp']}")
            print(f"  Direction: {signal['direction'].upper()}")
            print(f"  Entry: ${signal['entry_price']:.2f}")
            print(f"  Stop: ${signal['stop_price']:.2f}")
            print(f"  T1: ${signal['target_1']:.2f} (1.5R)")
            print(f"  T2: ${signal['target_2']:.2f} (2.5R)")
            print(f"  BOS Strength: {signal['bos_strength']*100:.2f}%")
            print(f"  FVG Size: {signal['fvg_size_pct']:.3f}%")
            print(f"  Confirmation: {signal['confirmation_grade']} ({signal['confirmation_score']})")
            print(f"  Candle Type: {signal['candle_type']}")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Bars scanned: {len(bars) - 50:,}")
    print(f"FVGs tracked: {len(fvg_tracking)}")
    print(f"FVGs confirmed: {sum(1 for f in fvg_tracking if f['confirmed'])}")
    print(f"Signals generated: {signals_found}")
    
    if fvg_tracking:
        print(f"\nFVG Tracking Details:")
        for i, fvg in enumerate(fvg_tracking, 1):
            status = "✅" if fvg['confirmed'] else "⏳"
            print(f"  {status} FVG #{i}: {fvg['direction']} at {fvg['time']} | Range: {fvg['fvg_low']:.2f}-{fvg['fvg_high']:.2f}")
    
    print()


if __name__ == "__main__":
    main()
