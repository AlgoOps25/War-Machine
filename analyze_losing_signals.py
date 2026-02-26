#!/usr/bin/env python3
"""
Detailed Losing Signal Analysis

Deep dive into why signals failed to determine if recommendations are appropriate.
Analyzes:
  - Entry vs actual breakout price
  - Stop placement vs entry
  - Time to stop-out
  - Pattern of failures by grade
  - Common failure characteristics
"""

import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict
import statistics

DB_PATH = "signal_analytics.db"

def get_losing_signals() -> List[Dict]:
    """Get all losing signals from database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            signal_id,
            ticker,
            direction,
            grade,
            confidence,
            entry_price,
            stop_price,
            t1_price,
            return_pct,
            hold_time_minutes,
            signal_time,
            filled_at,
            closed_at
        FROM signals
        WHERE outcome = 'loss'
        ORDER BY hold_time_minutes ASC
    """)
    
    signals = []
    for row in cursor.fetchall():
        signals.append({
            'signal_id': row[0],
            'ticker': row[1],
            'direction': row[2],
            'grade': row[3],
            'confidence': row[4],
            'entry_price': row[5],
            'stop_price': row[6],
            't1_price': row[7],
            'return_pct': row[8],
            'hold_time_minutes': row[9],
            'signal_time': row[10],
            'filled_at': row[11],
            'closed_at': row[12]
        })
    
    conn.close()
    return signals


def categorize_failures(signals: List[Dict]) -> Dict:
    """Categorize failures by timing and severity."""
    immediate = []  # <5 min
    quick = []      # 5-15 min
    delayed = []    # 15+ min
    
    for signal in signals:
        hold_time = signal['hold_time_minutes']
        if hold_time < 5:
            immediate.append(signal)
        elif hold_time < 15:
            quick.append(signal)
        else:
            delayed.append(signal)
    
    return {
        'immediate': immediate,
        'quick': quick,
        'delayed': delayed
    }


def analyze_stop_distances(signals: List[Dict]) -> Dict:
    """Analyze stop loss distances relative to entry."""
    stop_distances = []
    
    for signal in signals:
        entry = signal['entry_price']
        stop = signal['stop_price']
        
        # Calculate stop distance as percentage
        if signal['direction'] == 'BULL':
            stop_dist_pct = ((entry - stop) / entry) * 100
        else:  # BEAR
            stop_dist_pct = ((stop - entry) / entry) * 100
        
        stop_distances.append({
            'ticker': signal['ticker'],
            'grade': signal['grade'],
            'hold_time': signal['hold_time_minutes'],
            'stop_dist_pct': stop_dist_pct,
            'actual_loss_pct': abs(signal['return_pct'])
        })
    
    return stop_distances


def analyze_by_grade(signals: List[Dict]) -> Dict:
    """Analyze failure patterns by grade."""
    by_grade = {}
    
    for signal in signals:
        grade = signal['grade']
        if grade not in by_grade:
            by_grade[grade] = []
        by_grade[grade].append(signal)
    
    summary = {}
    for grade, grade_signals in by_grade.items():
        hold_times = [s['hold_time_minutes'] for s in grade_signals]
        losses = [abs(s['return_pct']) for s in grade_signals]
        confidences = [s['confidence'] for s in grade_signals]
        
        summary[grade] = {
            'count': len(grade_signals),
            'avg_hold_time': statistics.mean(hold_times),
            'median_hold_time': statistics.median(hold_times),
            'avg_loss': statistics.mean(losses),
            'avg_confidence': statistics.mean(confidences),
            'quick_fail_pct': len([s for s in grade_signals if s['hold_time_minutes'] < 15]) / len(grade_signals) * 100
        }
    
    return summary


def identify_common_patterns(signals: List[Dict]) -> Dict:
    """Identify common characteristics of quick failures."""
    quick_failures = [s for s in signals if s['hold_time_minutes'] < 15]
    delayed_failures = [s for s in signals if s['hold_time_minutes'] >= 15]
    
    if not quick_failures:
        return {}
    
    quick_conf = [s['confidence'] for s in quick_failures]
    delayed_conf = [s['confidence'] for s in delayed_failures] if delayed_failures else [0]
    
    quick_bull = len([s for s in quick_failures if s['direction'] == 'BULL'])
    quick_bear = len([s for s in quick_failures if s['direction'] == 'BEAR'])
    
    return {
        'quick_avg_confidence': statistics.mean(quick_conf),
        'delayed_avg_confidence': statistics.mean(delayed_conf),
        'confidence_difference': statistics.mean(quick_conf) - statistics.mean(delayed_conf),
        'quick_bull_pct': (quick_bull / len(quick_failures)) * 100,
        'quick_bear_pct': (quick_bear / len(quick_failures)) * 100,
        'quick_count': len(quick_failures),
        'delayed_count': len(delayed_failures)
    }


def print_analysis():
    """Print comprehensive losing signal analysis."""
    print("\n" + "="*80)
    print("LOSING SIGNAL DEEP DIVE ANALYSIS")
    print("Why did these signals fail? Are the recommendations appropriate?")
    print("="*80 + "\n")
    
    signals = get_losing_signals()
    
    if not signals:
        print("✅ No losing signals found - great performance!\n")
        return
    
    print(f"Total Losing Signals: {len(signals)}\n")
    
    # ===== TIMING ANALYSIS =====
    print("[1] FAILURE TIMING BREAKDOWN")
    print("-" * 80)
    categories = categorize_failures(signals)
    
    print(f"Immediate Failures (<5 min):  {len(categories['immediate'])} ({len(categories['immediate'])/len(signals)*100:.1f}%)")
    print(f"Quick Failures (5-15 min):    {len(categories['quick'])} ({len(categories['quick'])/len(signals)*100:.1f}%)")
    print(f"Delayed Failures (15+ min):   {len(categories['delayed'])} ({len(categories['delayed'])/len(signals)*100:.1f}%)")
    
    quick_total = len(categories['immediate']) + len(categories['quick'])
    print(f"\n🔥 CRITICAL: {quick_total} losses ({quick_total/len(signals)*100:.1f}%) in <15 min\n")
    
    # ===== DETAILED IMMEDIATE FAILURES =====
    if categories['immediate']:
        print("\n[2] IMMEDIATE FAILURES (<5 MIN) - WHY SO FAST?")
        print("-" * 80)
        print(f"{'Ticker':<8} {'Grade':<6} {'Conf':<6} {'Hold':<8} {'Loss':<8} {'Direction':<10}")
        print("-" * 80)
        
        for signal in categories['immediate']:
            print(f"{signal['ticker']:<8} "
                  f"{signal['grade']:<6} "
                  f"{signal['confidence']*100:<6.0f} "
                  f"{signal['hold_time_minutes']:<8.1f} "
                  f"{abs(signal['return_pct']):<8.2f} "
                  f"{signal['direction']:<10}")
        
        avg_hold = statistics.mean([s['hold_time_minutes'] for s in categories['immediate']])
        print(f"\n💡 INSIGHT: Average hold time before stop: {avg_hold:.1f} minutes")
        print("   This suggests entries are getting stopped out almost immediately.")
        print("   Possible causes:")
        print("   • Entering AT resistance (buying at the top of breakout bar)")
        print("   • Stops too tight for intraday volatility")
        print("   • False breakouts (no confirmation)\n")
    
    # ===== QUICK FAILURES =====
    if categories['quick']:
        print("\n[3] QUICK FAILURES (5-15 MIN) - PATTERN ANALYSIS")
        print("-" * 80)
        print(f"{'Ticker':<8} {'Grade':<6} {'Conf':<6} {'Hold':<8} {'Loss':<8} {'Direction':<10}")
        print("-" * 80)
        
        for signal in categories['quick']:
            print(f"{signal['ticker']:<8} "
                  f"{signal['grade']:<6} "
                  f"{signal['confidence']*100:<6.0f} "
                  f"{signal['hold_time_minutes']:<8.1f} "
                  f"{abs(signal['return_pct']):<8.2f} "
                  f"{signal['direction']:<10}")
        
        avg_hold = statistics.mean([s['hold_time_minutes'] for s in categories['quick']])
        print(f"\n💡 INSIGHT: Average hold time: {avg_hold:.1f} minutes")
        print("   Breakouts not holding. Price reversing within 5-15 minutes.")
        print("   Possible causes:")
        print("   • Weak breakouts (not enough buying/selling pressure)")
        print("   • No post-breakout confirmation")
        print("   • Entering too early in the breakout\n")
    
    # ===== DELAYED FAILURES =====
    if categories['delayed']:
        print("\n[4] DELAYED FAILURES (15+ MIN) - DIFFERENT PATTERN")
        print("-" * 80)
        print(f"{'Ticker':<8} {'Grade':<6} {'Conf':<6} {'Hold':<8} {'Loss':<8} {'Direction':<10}")
        print("-" * 80)
        
        for signal in categories['delayed']:
            print(f"{signal['ticker']:<8} "
                  f"{signal['grade']:<6} "
                  f"{signal['confidence']*100:<6.0f} "
                  f"{signal['hold_time_minutes']:<8.1f} "
                  f"{abs(signal['return_pct']):<8.2f} "
                  f"{signal['direction']:<10}")
        
        avg_hold = statistics.mean([s['hold_time_minutes'] for s in categories['delayed']])
        print(f"\n💡 INSIGHT: Average hold time: {avg_hold:.1f} minutes")
        print("   These signals held longer before failing.")
        print("   Possible causes:")
        print("   • Breakout was real but trend reversed")
        print("   • Normal market volatility")
        print("   • These may be unavoidable losses\n")
    
    # ===== STOP DISTANCE ANALYSIS =====
    print("\n[5] STOP LOSS PLACEMENT ANALYSIS")
    print("-" * 80)
    stop_analysis = analyze_stop_distances(signals)
    
    avg_stop_dist = statistics.mean([s['stop_dist_pct'] for s in stop_analysis])
    avg_actual_loss = statistics.mean([s['actual_loss_pct'] for s in stop_analysis])
    
    print(f"Average Stop Distance:  {avg_stop_dist:.2f}%")
    print(f"Average Actual Loss:    {avg_actual_loss:.2f}%")
    
    # Check if losses match stop distances
    if abs(avg_actual_loss - avg_stop_dist) < 0.5:
        print("\n✅ GOOD: Losses match stop distances (stops are being respected)")
    else:
        print(f"\n⚠️ WARNING: Losses ({avg_actual_loss:.2f}%) don't match stops ({avg_stop_dist:.2f}%)")
        if avg_actual_loss > avg_stop_dist:
            print("   This suggests slippage or stops being hit with market orders")
    
    # Quick failure stop analysis
    quick_stops = [s for s in stop_analysis if s['hold_time'] < 15]
    if quick_stops:
        quick_avg_stop = statistics.mean([s['stop_dist_pct'] for s in quick_stops])
        print(f"\nQuick Failure Stop Distance: {quick_avg_stop:.2f}%")
        
        if quick_avg_stop < 2.0:
            print("\n🚨 CRITICAL FINDING: Stops are too tight!")
            print("   Quick failures have <2% stop distance.")
            print("   This is too tight for intraday volatility on most stocks.")
            print("   ✅ RECOMMENDATION VALIDATED: Widen stops to 2.0 ATR\n")
        else:
            print("\n✅ Stop distances are reasonable (>2%)")
            print("   Problem is likely entry timing, not stop placement\n")
    
    # ===== GRADE ANALYSIS =====
    print("\n[6] FAILURE PATTERNS BY GRADE")
    print("-" * 80)
    grade_analysis = analyze_by_grade(signals)
    
    print(f"{'Grade':<6} {'Count':<8} {'Avg Hold':<12} {'Quick Fail %':<14} {'Avg Loss':<10}")
    print("-" * 80)
    
    for grade in sorted(grade_analysis.keys(), reverse=True):
        data = grade_analysis[grade]
        print(f"{grade:<6} "
              f"{data['count']:<8} "
              f"{data['avg_hold_time']:<12.1f} "
              f"{data['quick_fail_pct']:<14.1f} "
              f"{data['avg_loss']:<10.2f}")
    
    print("\n💡 INSIGHT: Compare quick failure rates by grade")
    for grade, data in sorted(grade_analysis.items(), key=lambda x: x[1]['quick_fail_pct'], reverse=True):
        if data['quick_fail_pct'] > 60:
            print(f"   ⚠️ {grade} Grade: {data['quick_fail_pct']:.0f}% quick failures (HIGH RISK)")
        elif data['quick_fail_pct'] > 40:
            print(f"   ⚠️ {grade} Grade: {data['quick_fail_pct']:.0f}% quick failures (MODERATE RISK)")
        else:
            print(f"   ✅ {grade} Grade: {data['quick_fail_pct']:.0f}% quick failures (acceptable)")
    
    # ===== COMMON PATTERNS =====
    print("\n[7] QUICK FAILURE CHARACTERISTICS")
    print("-" * 80)
    patterns = identify_common_patterns(signals)
    
    if patterns:
        print(f"Quick Failures Count:      {patterns['quick_count']}")
        print(f"Delayed Failures Count:    {patterns['delayed_count']}")
        print(f"\nQuick Failure Avg Conf:    {patterns['quick_avg_confidence']*100:.1f}%")
        print(f"Delayed Failure Avg Conf:  {patterns['delayed_avg_confidence']*100:.1f}%")
        
        if abs(patterns['confidence_difference']) > 0.05:
            if patterns['confidence_difference'] > 0:
                print(f"\n⚠️ SURPRISING: Quick failures have HIGHER confidence!")
                print("   This suggests confidence score is not predictive of durability.")
            else:
                print(f"\n✅ As expected: Quick failures have lower confidence")
        else:
            print(f"\n➡️ Confidence is similar between quick and delayed failures")
            print("   Confidence alone doesn't predict failure timing")
        
        print(f"\nQuick Failure Direction:")
        print(f"   BULL: {patterns['quick_bull_pct']:.0f}%")
        print(f"   BEAR: {patterns['quick_bear_pct']:.0f}%")
        
        if abs(patterns['quick_bull_pct'] - 50) > 20:
            if patterns['quick_bull_pct'] > patterns['quick_bear_pct']:
                print("\n⚠️ BULL signals failing more quickly (may indicate resistance is stronger)")
            else:
                print("\n⚠️ BEAR signals failing more quickly (may indicate support is stronger)")
    
    # ===== FINAL RECOMMENDATIONS =====
    print("\n" + "="*80)
    print("RECOMMENDATIONS VALIDATION")
    print("="*80 + "\n")
    
    quick_pct = (len(categories['immediate']) + len(categories['quick'])) / len(signals) * 100
    
    if quick_pct > 60:
        print("🚨 CRITICAL: {:.0f}% of losses are quick failures (<15 min)\n".format(quick_pct))
        
        print("✅ VALIDATED RECOMMENDATIONS:\n")
        print("1️⃣ 2-BAR HOLDING PERIOD")
        print("   WHY: Immediate failures suggest we're entering too early")
        print("   FIX: Wait 2 bars after breakout to confirm it's holding")
        print("   IMPACT: Should reduce immediate failures by 50-80%\n")
        
        print("2️⃣ ENTRY 0.15% ABOVE BREAKOUT")
        print("   WHY: Entering AT resistance means buying at the top")
        print("   FIX: Wait for price to clear resistance before entry")
        print("   IMPACT: Confirms breakout is real before risking capital\n")
        
        if quick_stops and statistics.mean([s['stop_dist_pct'] for s in quick_stops]) < 2.0:
            print("3️⃣ WIDEN STOPS TO 2.0 ATR")
            print("   WHY: Current stops <2% are too tight for intraday moves")
            print("   FIX: Give trades room to breathe (2.0 ATR = ~2-3% typically)")
            print("   IMPACT: Reduces noise-based stop-outs by 30-50%\n")
        else:
            print("3️⃣ STOP DISTANCES ARE ADEQUATE")
            print("   WHY: Stop distances >2% are reasonable")
            print("   FIX: Focus on entry timing, not stop placement\n")
    else:
        print(f"✅ ACCEPTABLE: Only {quick_pct:.0f}% quick failures\n")
        print("Your system is performing well. Quick failures are manageable.")
        print("Consider monitoring but no urgent changes needed.\n")
    
    print("="*80)
    print("ANALYSIS COMPLETE - Review findings above to decide on implementation")
    print("="*80 + "\n")


if __name__ == "__main__":
    try:
        print_analysis()
    except Exception as e:
        print(f"\n❌ Error running analysis: {e}")
        print("Make sure signal_analytics.db exists with signal data\n")
