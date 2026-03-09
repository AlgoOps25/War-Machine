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
from app.signals.comprehensive_detector import get_comprehensive_detector

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


def aggregate_bars(bars_1min: List[Dict], period_mins: int) -> List[Dict]:
    if not bars_1min:
        return []
    
    bars_agg = []
    i = 0
    
    while i < len(bars_1min):
        start_bar = bars_1min[i]
        start_time = start_bar['datetime']
        
        period_bars = [start_bar]
        j = i + 1
        
        while j < len(bars_1min) and j < i + period_mins:
            next_bar = bars_1min[j]
            if (next_bar['datetime'] - start_time).seconds < period_mins * 60:
                period_bars.append(next_bar)
                j += 1
            else:
                break
        
        bar_agg = {
            'datetime': start_time,
            'open': period_bars[0]['open'],
            'high': max(b['high'] for b in period_bars),
            'low': min(b['low'] for b in period_bars),
            'close': period_bars[-1]['close'],
            'volume': sum(b['volume'] for b in period_bars)
        }
        
        bars_agg.append(bar_agg)
        i = j
    
    return bars_agg


def main():
    ticker = 'AAPL'
    print(f"\n{'='*80}")
    print(f"DEBUG COMPREHENSIVE DETECTOR: {ticker}")
    print(f"{'='*80}\n")
    
    bars_1min = get_bars(ticker, days_back=5)
    
    if not bars_1min:
        print("No bars loaded!")
        return
    
    print(f"Loaded {len(bars_1min):,} 1min bars")
    
    bars_5min = aggregate_bars(bars_1min, 5)
    bars_15min = aggregate_bars(bars_1min, 15)
    
    print(f"Aggregated {len(bars_5min):,} 5min bars")
    print(f"Aggregated {len(bars_15min):,} 15min bars\n")
    
    detector = get_comprehensive_detector()
    
    signals_detected = 0
    signals_passed = 0
    
    # Temporarily lower confidence threshold to see ALL signals
    original_threshold = detector.params['min_confidence_to_signal']
    detector.params['min_confidence_to_signal'] = 0.0  # See everything
    
    for idx in range(50, len(bars_1min)):
        current_bars_1min = bars_1min[:idx+1]
        current_time = bars_1min[idx]['datetime']
        current_bars_5min = [b for b in bars_5min if b['datetime'] <= current_time]
        current_bars_15min = [b for b in bars_15min if b['datetime'] <= current_time]
        
        signal = detector.detect_signals(
            ticker, current_bars_1min, current_bars_5min, current_bars_15min
        )
        
        if signal:
            signals_detected += 1
            
            passed_original = signal.confidence >= original_threshold
            if passed_original:
                signals_passed += 1
            
            status = "✅ PASS" if passed_original else "❌ REJECT"
            
            print(f"\n[{idx}] {status} Signal at {signal.timestamp}")
            print(f"  Direction: {signal.direction}")
            print(f"  Entry: {signal.entry_price:.2f}")
            print(f"  Grade: {signal.grade}")
            print(f"  Confidence: {signal.confidence:.1%}")
            print(f"  \nBreakdown:")
            print(f"    Confirmation: {signal.confirmation_grade} ({signal.confirmation_score})")
            print(f"    BOS Strength: {signal.bos_strength*100:.2f}%")
            print(f"    Volume Ratio: {signal.volume_ratio:.2f}x")
            print(f"    VWAP Band: {signal.vwap_band}")
            print(f"    VP Zone: {signal.volume_profile_zone}")
            print(f"    OR: {signal.or_classification} (+{signal.or_boost:.1%})")
            print(f"    MTF Score: {signal.mtf_score:.1f}/10")
            print(f"    Trends: 1m={signal.trend_1min}, 5m={signal.trend_5min}, 15m={signal.trend_15min}")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Bars scanned: {len(bars_1min) - 50:,}")
    print(f"Signals detected: {signals_detected}")
    print(f"Signals passed {original_threshold:.0%} threshold: {signals_passed}")
    print(f"Rejection rate: {(1 - signals_passed/signals_detected)*100 if signals_detected else 0:.1f}%")
    print()


if __name__ == "__main__":
    main()
