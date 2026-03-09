#!/usr/bin/env python3
"""
Signal Pattern Analysis - Identify Winner vs Loser Characteristics
===================================================================

Analyzes individual signals to find patterns that differentiate:
- Winners vs Losers
- A+ vs A vs B grades
- OR vs Intraday performance
- High R-multiple vs Low R-multiple

Author: War Machine Team
Date: March 9, 2026
"""

import sys
sys.path.append('.')

import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict


def load_backtest_results(filename='backtest_comprehensive.json'):
    """Load backtest results"""
    path = Path(filename)
    
    if not path.exists():
        print(f"Error: {filename} not found!")
        print("Run backtest_comprehensive.py first.")
        return None
    
    with open(path, 'r') as f:
        return json.load(f)


def analyze_signal_characteristics(signals):
    """
    Analyze signal characteristics and correlate with outcomes.
    """
    # Convert to DataFrame for analysis
    df = pd.DataFrame(signals)
    
    # Add outcome categories
    df['outcome'] = df['result_r'].apply(
        lambda r: 'BIG_WIN' if r >= 1.5 else ('WIN' if r > 0 else 'LOSS')
    )
    df['is_winner'] = df['result_r'] > 0
    
    print("\n" + "="*80)
    print("SIGNAL PATTERN ANALYSIS")
    print("="*80)
    
    # ─────────────────────────────────────────────────────────
    # 1. GRADE ANALYSIS
    # ─────────────────────────────────────────────────────────
    print("\n🎖️  GRADE PERFORMANCE BREAKDOWN:\n")
    
    for grade in ['A+', 'A', 'B']:
        grade_signals = df[df['grade'] == grade]
        
        if len(grade_signals) == 0:
            continue
        
        win_rate = (grade_signals['result_r'] > 0).mean() * 100
        avg_r = grade_signals['result_r'].mean()
        
        winners = grade_signals[grade_signals['result_r'] > 0]
        losers = grade_signals[grade_signals['result_r'] <= 0]
        
        print(f"{grade} Grade ({len(grade_signals)} signals):")
        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Avg R: {avg_r:+.2f}R")
        
        # What makes winners different?
        if len(winners) > 0 and len(losers) > 0:
            print(f"\n  Winners vs Losers:")
            
            # Confidence
            winner_conf = winners['confidence'].mean()
            loser_conf = losers['confidence'].mean()
            print(f"    Confidence: {winner_conf:.1%} vs {loser_conf:.1%} (Δ{(winner_conf-loser_conf)*100:+.1f}%)")
            
            # BOS Strength
            winner_bos = winners['bos_strength'].mean()
            loser_bos = losers['bos_strength'].mean()
            print(f"    BOS Strength: {winner_bos:.2%} vs {loser_bos:.2%} (Δ{(winner_bos-loser_bos)*100:+.2f}%)")
            
            # FVG Size
            winner_fvg = winners['fvg_size_pct'].mean()
            loser_fvg = losers['fvg_size_pct'].mean()
            print(f"    FVG Size: {winner_fvg:.3f}% vs {loser_fvg:.3f}% (Δ{winner_fvg-loser_fvg:+.3f}%)")
            
            # Volume Ratio
            winner_vol = winners['volume_ratio'].mean()
            loser_vol = losers['volume_ratio'].mean()
            print(f"    Volume Ratio: {winner_vol:.2f}x vs {loser_vol:.2f}x (Δ{winner_vol-loser_vol:+.2f}x)")
            
            # MTF Score
            winner_mtf = winners['mtf_score'].mean()
            loser_mtf = losers['mtf_score'].mean()
            print(f"    MTF Score: {winner_mtf:.1f}/10 vs {loser_mtf:.1f}/10 (Δ{winner_mtf-loser_mtf:+.1f})")
        
        print()
    
    # ─────────────────────────────────────────────────────────
    # 2. CONFIRMATION GRADE ANALYSIS
    # ─────────────────────────────────────────────────────────
    print("\n🕯️  CANDLE CONFIRMATION ANALYSIS:\n")
    
    for conf_grade in ['A+', 'A', 'A-']:
        conf_signals = df[df['confirmation_grade'] == conf_grade]
        
        if len(conf_signals) == 0:
            continue
        
        win_rate = (conf_signals['result_r'] > 0).mean() * 100
        avg_r = conf_signals['result_r'].mean()
        
        print(f"{conf_grade} Confirmation ({len(conf_signals)} signals):")
        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Avg R: {avg_r:+.2f}R")
    
    # ─────────────────────────────────────────────────────────
    # 3. SESSION TYPE ANALYSIS
    # ─────────────────────────────────────────────────────────
    print("\n⏰ SESSION TYPE DEEP DIVE:\n")
    
    or_signals = df[df['is_opening_range']]
    intraday_signals = df[~df['is_opening_range']]
    
    print(f"Opening Range (9:30-10:00) - {len(or_signals)} signals:")
    if len(or_signals) > 0:
        print(f"  Win Rate: {(or_signals['result_r'] > 0).mean()*100:.1f}%")
        print(f"  Avg R: {or_signals['result_r'].mean():+.2f}R")
        print(f"  Avg Confidence: {or_signals['confidence'].mean():.1%}")
        print(f"  Avg BOS Strength: {or_signals['bos_strength'].mean():.2%}")
        print(f"  Avg Volume Ratio: {or_signals['volume_ratio'].mean():.2f}x")
    
    print(f"\nIntraday (10:00-15:30) - {len(intraday_signals)} signals:")
    if len(intraday_signals) > 0:
        print(f"  Win Rate: {(intraday_signals['result_r'] > 0).mean()*100:.1f}%")
        print(f"  Avg R: {intraday_signals['result_r'].mean():+.2f}R")
        print(f"  Avg Confidence: {intraday_signals['confidence'].mean():.1%}")
        print(f"  Avg BOS Strength: {intraday_signals['bos_strength'].mean():.2%}")
        print(f"  Avg Volume Ratio: {intraday_signals['volume_ratio'].mean():.2f}x")
    
    # ─────────────────────────────────────────────────────────
    # 4. WINNER CHARACTERISTICS
    # ─────────────────────────────────────────────────────────
    print("\n✅ TOP WINNER CHARACTERISTICS:\n")
    
    winners = df[df['result_r'] > 0]
    losers = df[df['result_r'] <= 0]
    
    if len(winners) > 0 and len(losers) > 0:
        print(f"Comparing {len(winners)} Winners vs {len(losers)} Losers:\n")
        
        # All metrics
        metrics = [
            ('Confidence', 'confidence', '.1%'),
            ('BOS Strength', 'bos_strength', '.2%'),
            ('FVG Size', 'fvg_size_pct', '.3f'),
            ('Volume Ratio', 'volume_ratio', '.2f'),
            ('MTF Score', 'mtf_score', '.1f'),
            ('Confirmation Score', 'confirmation_score', '.0f'),
        ]
        
        for label, col, fmt in metrics:
            winner_val = winners[col].mean()
            loser_val = losers[col].mean()
            diff = winner_val - loser_val
            diff_pct = (diff / loser_val * 100) if loser_val != 0 else 0
            
            winner_str = f"{winner_val:{fmt}}"
            loser_str = f"{loser_val:{fmt}}"
            
            if '%' in fmt:
                diff_str = f"{diff*100:+.2f}%"
            else:
                diff_str = f"{diff:+.2f}"
            
            print(f"  {label:20s}: {winner_str:>8s} vs {loser_str:>8s}  ({diff_str}, {diff_pct:+.1f}%)")
    
    # ─────────────────────────────────────────────────────────
    # 5. VWAP BAND ANALYSIS
    # ─────────────────────────────────────────────────────────
    print("\n📊 VWAP BAND PERFORMANCE:\n")
    
    vwap_bands = df['vwap_band'].value_counts()
    for band in vwap_bands.index:
        band_signals = df[df['vwap_band'] == band]
        win_rate = (band_signals['result_r'] > 0).mean() * 100
        avg_r = band_signals['result_r'].mean()
        
        print(f"{band:15s}: {len(band_signals):3d} signals, {win_rate:5.1f}% WR, {avg_r:+.2f}R")
    
    # ─────────────────────────────────────────────────────────
    # 6. VOLUME PROFILE ZONE ANALYSIS
    # ─────────────────────────────────────────────────────────
    print("\n🔊 VOLUME PROFILE ZONE PERFORMANCE:\n")
    
    vp_zones = df['volume_profile_zone'].value_counts()
    for zone in vp_zones.index:
        zone_signals = df[df['volume_profile_zone'] == zone]
        win_rate = (zone_signals['result_r'] > 0).mean() * 100
        avg_r = zone_signals['result_r'].mean()
        
        print(f"{zone:10s}: {len(zone_signals):3d} signals, {win_rate:5.1f}% WR, {avg_r:+.2f}R")
    
    # ─────────────────────────────────────────────────────────
    # 7. DIRECTION ANALYSIS
    # ─────────────────────────────────────────────────────────
    print("\n🎯 DIRECTION PERFORMANCE:\n")
    
    for direction in ['CALL', 'PUT']:
        dir_signals = df[df['direction'] == direction]
        
        if len(dir_signals) == 0:
            continue
        
        win_rate = (dir_signals['result_r'] > 0).mean() * 100
        avg_r = dir_signals['result_r'].mean()
        
        print(f"{direction:5s}: {len(dir_signals):3d} signals, {win_rate:5.1f}% WR, {avg_r:+.2f}R")
    
    # ─────────────────────────────────────────────────────────
    # 8. TOP 10 BEST AND WORST SIGNALS
    # ─────────────────────────────────────────────────────────
    print("\n🏆 TOP 10 BEST SIGNALS:\n")
    
    best_signals = df.nlargest(10, 'result_r')
    
    for idx, signal in best_signals.iterrows():
        print(f"{signal['ticker']:5s} {signal['timestamp'][:10]} {signal['time'][:5]} | "
              f"{signal['direction']:4s} | Grade: {signal['grade']:2s} | Conf: {signal['confirmation_grade']:2s} | "
              f"Result: {signal['result_r']:+.2f}R")
        print(f"      Confidence: {signal['confidence']:.1%} | BOS: {signal['bos_strength']:.2%} | "
              f"FVG: {signal['fvg_size_pct']:.3f}% | Vol: {signal['volume_ratio']:.2f}x | MTF: {signal['mtf_score']:.1f}/10")
        print()
    
    print("\n💀 TOP 10 WORST SIGNALS:\n")
    
    worst_signals = df.nsmallest(10, 'result_r')
    
    for idx, signal in worst_signals.iterrows():
        print(f"{signal['ticker']:5s} {signal['timestamp'][:10]} {signal['time'][:5]} | "
              f"{signal['direction']:4s} | Grade: {signal['grade']:2s} | Conf: {signal['confirmation_grade']:2s} | "
              f"Result: {signal['result_r']:+.2f}R")
        print(f"      Confidence: {signal['confidence']:.1%} | BOS: {signal['bos_strength']:.2%} | "
              f"FVG: {signal['fvg_size_pct']:.3f}% | Vol: {signal['volume_ratio']:.2f}x | MTF: {signal['mtf_score']:.1f}/10")
        print()
    
    # ─────────────────────────────────────────────────────────
    # 9. RECOMMENDATIONS
    # ─────────────────────────────────────────────────────────
    print("\n" + "="*80)
    print("💡 RECOMMENDATIONS")
    print("="*80 + "\n")
    
    # Analyze what distinguishes winners
    if len(winners) > 0 and len(losers) > 0:
        conf_diff = (winners['confidence'].mean() - losers['confidence'].mean()) * 100
        bos_diff = (winners['bos_strength'].mean() - losers['bos_strength'].mean()) * 100
        vol_diff = winners['volume_ratio'].mean() - losers['volume_ratio'].mean()
        mtf_diff = winners['mtf_score'].mean() - losers['mtf_score'].mean()
        
        print("Based on winner vs loser analysis:\n")
        
        if conf_diff > 5:
            print(f"1. ✅ Raise confidence threshold by {conf_diff:.1f}% (winners have higher confidence)")
        
        if bos_diff > 0.2:
            print(f"2. ✅ Require stronger BOS (winners average {bos_diff:.2f}% stronger breakouts)")
        
        if vol_diff > 0.3:
            print(f"3. ✅ Filter for higher volume (winners have {vol_diff:.2f}x more volume)")
        
        if mtf_diff > 1.0:
            print(f"4. ✅ Weight MTF alignment more heavily (winners score {mtf_diff:.1f} points higher)")
        
        # Session analysis
        or_wr = (or_signals['result_r'] > 0).mean() * 100
        intraday_wr = (intraday_signals['result_r'] > 0).mean() * 100
        
        if or_wr > intraday_wr + 10:
            print(f"\n5. ⭐ FOCUS ON OPENING RANGE ONLY (OR: {or_wr:.1f}% WR vs Intraday: {intraday_wr:.1f}% WR)")
        
        # B grade analysis
        b_signals = df[df['grade'] == 'B']
        if len(b_signals) > 0:
            b_wr = (b_signals['result_r'] > 0).mean() * 100
            b_conf = b_signals['confidence'].mean()
            if b_wr > 70:
                print(f"\n6. 🔍 INVESTIGATE B-GRADE WEIGHTING (B-grade: {b_wr:.1f}% WR, {b_conf:.1%} conf)")
                print(f"   B-grades are OUTPERFORMING - check if grading system is backwards!")
    
    print()


def main():
    results = load_backtest_results()
    
    if not results:
        return
    
    signals = results.get('signals', [])
    
    if not signals:
        print("No signals found in backtest results.")
        return
    
    analyze_signal_characteristics(signals)


if __name__ == "__main__":
    main()
