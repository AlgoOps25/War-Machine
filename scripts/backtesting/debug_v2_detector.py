#!/usr/bin/env python3
"""
Debug V2 Detector - See Why Signals Are Rejected

Runs V1 (original) and V2 (enhanced) side-by-side to see:
1. How many signals V1 finds
2. Which V2 filters reject them
3. Where the bottleneck is
"""

import sys
sys.path.append('.')

import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List
from collections import Counter

from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
from app.signals.enhanced_bos_fvg_v2 import get_enhanced_detector_v2

ET = ZoneInfo("America/New_York")


def get_bars(ticker: str, days_back: int = 30) -> List[Dict]:
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


def aggregate_to_5min(bars_1min: List[Dict]) -> List[Dict]:
    if not bars_1min:
        return []
    
    bars_5min = []
    i = 0
    
    while i < len(bars_1min):
        start_bar = bars_1min[i]
        start_time = start_bar['datetime']
        
        period_bars = [start_bar]
        j = i + 1
        
        while j < len(bars_1min) and j < i + 5:
            next_bar = bars_1min[j]
            if (next_bar['datetime'] - start_time).seconds < 300:
                period_bars.append(next_bar)
                j += 1
            else:
                break
        
        bar_5min = {
            'datetime': start_time,
            'open': period_bars[0]['open'],
            'high': max(b['high'] for b in period_bars),
            'low': min(b['low'] for b in period_bars),
            'close': period_bars[-1]['close'],
            'volume': sum(b['volume'] for b in period_bars)
        }
        
        bars_5min.append(bar_5min)
        i = j
    
    return bars_5min


def detect_v1_simple(bars: List[Dict], idx: int) -> Dict:
    """
    Simple V1 detection (like original backtest)
    """
    if idx < 20 or idx >= len(bars) - 5:
        return None
    
    current_bar = bars[idx]
    timestamp = current_bar['datetime']
    
    # Check market hours ONLY (no trend filtering)
    if timestamp.hour < 9 or (timestamp.hour == 9 and timestamp.minute < 30):
        return {'reason': 'pre_market'}
    
    if timestamp.hour >= 16:
        return {'reason': 'after_hours'}
    
    lookback = bars[max(0, idx-20):idx]
    
    if len(lookback) < 10:
        return None
    
    highs = [b['high'] for b in lookback]
    lows = [b['low'] for b in lookback]
    swing_high = max(highs)
    swing_low = min(lows)
    
    # Volume
    recent_volumes = [b['volume'] for b in lookback[-10:]]
    avg_volume = np.mean(recent_volumes) if recent_volumes else 0
    
    if avg_volume == 0:
        return None
    
    volume_ratio = current_bar['volume'] / avg_volume
    
    if volume_ratio < 2.0:
        return {'reason': 'low_volume', 'volume_ratio': volume_ratio}
    
    # Bullish BOS
    if current_bar['close'] > swing_high:
        strength = (current_bar['close'] - swing_high) / swing_high
        
        if strength >= 0.010:
            return {
                'signal': 'CALL_BOS',
                'strength': strength,
                'volume_ratio': volume_ratio,
                'timestamp': timestamp
            }
        else:
            return {'reason': 'weak_breakout', 'strength': strength}
    
    # Bearish BOS
    if current_bar['close'] < swing_low:
        strength = (swing_low - current_bar['close']) / swing_low
        
        if strength >= 0.010:
            return {
                'signal': 'PUT_BOS',
                'strength': strength,
                'volume_ratio': volume_ratio,
                'timestamp': timestamp
            }
        else:
            return {'reason': 'weak_breakout', 'strength': strength}
    
    return None


def debug_ticker(ticker: str, days_back: int = 30):
    print(f"\n{'='*80}")
    print(f"DEBUG: {ticker} (past {days_back} days)")
    print(f"{'='*80}\n")
    
    # Get bars
    bars_1min = get_bars(ticker, days_back)
    
    if not bars_1min or len(bars_1min) < 500:
        print(f"[ERROR] Insufficient data for {ticker}\n")
        return
    
    print(f"[DATA] Loaded {len(bars_1min):,} 1min bars")
    
    bars_5min = aggregate_to_5min(bars_1min)
    print(f"[DATA] Aggregated to {len(bars_5min):,} 5min bars\n")
    
    # V1 scan
    print("[V1] Scanning with simple detector (no trend filtering)...")
    v1_signals = []
    v1_rejections = Counter()
    
    for idx in range(50, len(bars_1min) - 10):
        result = detect_v1_simple(bars_1min, idx)
        
        if result and 'signal' in result:
            v1_signals.append(result)
        elif result and 'reason' in result:
            v1_rejections[result['reason']] += 1
    
    print(f"[V1] Found {len(v1_signals)} signals")
    print(f"[V1] Rejection reasons: {dict(v1_rejections)}\n")
    
    # V2 scan
    print("[V2] Scanning with enhanced detector (trend + VWAP)...")
    detector_v2 = get_enhanced_detector_v2()
    v2_signals = []
    
    for idx in range(50, len(bars_1min) - 10):
        signal = detector_v2.detect_signals(bars_1min, bars_5min, idx)
        
        if signal:
            v2_signals.append(signal)
    
    print(f"[V2] Found {len(v2_signals)} signals\n")
    
    # Compare
    print(f"{'='*80}")
    print("COMPARISON")
    print(f"{'='*80}")
    print(f"V1 (simple):   {len(v1_signals)} signals")
    print(f"V2 (enhanced): {len(v2_signals)} signals")
    print(f"Filtered out:  {len(v1_signals) - len(v2_signals)} signals ({(len(v1_signals) - len(v2_signals))/max(len(v1_signals),1)*100:.1f}%)\n")
    
    if v1_signals:
        print(f"\nV1 Sample Signals (first 5):")
        for i, sig in enumerate(v1_signals[:5], 1):
            print(f"  {i}. {sig['timestamp'].strftime('%Y-%m-%d %H:%M')} - {sig['signal']} - "
                  f"Strength: {sig['strength']:.2%}, Volume: {sig['volume_ratio']:.1f}x")
    
    if v2_signals:
        print(f"\nV2 Sample Signals (first 5):")
        for i, sig in enumerate(v2_signals[:5], 1):
            print(f"  {i}. {sig.timestamp.strftime('%Y-%m-%d %H:%M')} - {sig.direction} {sig.signal_type} - "
                  f"Grade: {sig.grade}, Trend 1m: {sig.trend_1min}, Trend 5m: {sig.trend_5min}")
    
    print()


def main():
    tickers = ['AAPL', 'NVDA', 'TSLA']
    
    for ticker in tickers:
        debug_ticker(ticker, days_back=30)


if __name__ == "__main__":
    main()
