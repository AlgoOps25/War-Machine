#!/usr/bin/env python3
"""
Full MTF Infrastructure Integration Test

Tests all three MTF modules together:
- mtf_data_manager: Multi-timeframe data fetching
- mtf_fvg_engine: Pattern detection and convergence
- mtf_convergence: Signal scoring and confidence boost

Run this to validate MTF infrastructure before sniper.py integration.

Usage:
  python test_mtf_full.py
  python test_mtf_full.py --tickers SPY QQQ AAPL NVDA  # Custom ticker list
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from mtf_data_manager import mtf_data_manager
from mtf_fvg_engine import mtf_fvg_engine
from mtf_convergence import mtf_convergence_scorer

ET = ZoneInfo("America/New_York")


def print_header(text: str):
    """Print formatted header."""
    print("\n" + "="*80)
    print(text)
    print("="*80 + "\n")


def print_section(text: str):
    """Print formatted section."""
    print("\n" + "─"*80)
    print(text)
    print("─"*80)


def main():
    """Run full MTF infrastructure test."""
    
    print_header("FULL MTF INFRASTRUCTURE TEST")
    print(f"Date: {datetime.now(ET).strftime('%A, %B %d, %Y %I:%M %p ET')}\n")
    
    # Parse command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == '--tickers':
        tickers = [t.upper() for t in sys.argv[2:]]
    else:
        # Default ticker list (mix of indices and high-volume stocks)
        tickers = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD', 'GOOGL']
    
    print(f"🔍 Scanning {len(tickers)} tickers: {', '.join(tickers)}\n")
    
    # ────────────────────────────────────────
    # STEP 1: Fetch Data
    # ────────────────────────────────────────
    
    print("[1/3] Fetching multi-timeframe data...")
    import time
    start_time = time.time()
    
    results = mtf_data_manager.batch_update(tickers)
    successful = sum(1 for success in results.values() if success)
    
    fetch_time = time.time() - start_time
    print(f"\n✅ Data fetch complete: {successful}/{len(tickers)} tickers successful in {fetch_time:.2f}s")
    
    # Show data summary
    print("\nData Summary:")
    for ticker in tickers[:3]:  # Show first 3 tickers
        data = mtf_data_manager.get_all_timeframes(ticker)
        bar_counts = {tf: len(bars) for tf, bars in data.items()}
        print(f"  {ticker}: {bar_counts}")
    if len(tickers) > 3:
        print(f"  ... and {len(tickers) - 3} more tickers")
    
    # ────────────────────────────────────────
    # STEP 2: Detect Signals
    # ────────────────────────────────────────
    
    print("\n[2/3] Scanning for FVG convergence...")
    start_time = time.time()
    
    signals = mtf_fvg_engine.scan_multiple_tickers(tickers)
    
    scan_time = time.time() - start_time
    print(f"\n✅ Scan complete: {len(signals)} MTF signals found in {scan_time:.2f}s")
    
    if len(signals) == 0:
        print("\n⚠️  No signals found (strict convergence not met)")
        print("   This is normal during choppy market conditions.")
        print("   Try testing during volatile periods or with different tickers.")
    
    # ────────────────────────────────────────
    # STEP 3: Score Signals
    # ────────────────────────────────────────
    
    if signals:
        print("\n[3/3] Scoring signal quality...\n")
        
        scored_signals = []
        for signal in signals:
            score = mtf_convergence_scorer.calculate_convergence_score(signal)
            boost = mtf_convergence_scorer.get_confidence_boost(signal)
            is_high_quality = mtf_convergence_scorer.is_high_quality(signal)
            
            scored_signals.append({
                'signal': signal,
                'score': score,
                'boost': boost,
                'high_quality': is_high_quality
            })
        
        # Sort by score (best first)
        scored_signals.sort(key=lambda x: x['score'], reverse=True)
        
        # Display signals
        print("Signal Quality Ranking:\n")
        for i, item in enumerate(scored_signals, 1):
            signal = item['signal']
            score = item['score']
            boost = item['boost']
            
            # Quality indicator
            if score >= 0.80:
                quality = "⭐ HIGH"
            elif score >= 0.60:
                quality = "✅ GOOD"
            else:
                quality = "⚠️  WEAK"
            
            # Direction arrow
            arrow = "🟢" if signal['direction'] == 'bull' else "🔴"
            
            print(f"{i}. {quality} | {signal['ticker']:>6} {arrow} {signal['direction']:>4} | "
                  f"{signal['timeframes_aligned']}/4 TFs | "
                  f"Score: {score:.3f} | "
                  f"Boost: +{boost*100:>5.1f}% | "
                  f"Zone: ${signal['zone_low']:.2f}-${signal['zone_high']:.2f}")
    
    # ────────────────────────────────────────
    # STATISTICS
    # ────────────────────────────────────────
    
    print_section("PERFORMANCE STATISTICS")
    
    # Data Manager Stats
    data_stats = mtf_data_manager.get_stats()
    print("\nData Manager:")
    print(f"  API Calls:         {data_stats['api_calls']}")
    print(f"  Cache Hits:        {data_stats['cache_hits']}")
    print(f"  Cache Misses:      {data_stats['cache_misses']}")
    print(f"  Hit Rate:          {data_stats['hit_rate']:.1f}%")
    print(f"  Cached Tickers:    {data_stats['cached_tickers']}")
    
    # FVG Engine Stats
    fvg_stats = mtf_fvg_engine.get_stats()
    print("\nFVG Detection Engine:")
    print(f"  Signals Detected:      {fvg_stats['signals_detected']}")
    print(f"  Convergence Passed:    {fvg_stats['convergence_passed']}")
    print(f"  Convergence Failed:    {fvg_stats['convergence_failed']}")
    print(f"  Pass Rate:             {fvg_stats['convergence_pass_rate']:.1f}%")
    
    # Convergence Scorer Stats
    conv_stats = mtf_convergence_scorer.get_stats()
    print("\nConvergence Scorer:")
    print(f"  Signals Scored:        {conv_stats['signals_scored']}")
    print(f"  High Quality Signals:  {conv_stats['high_quality_signals']}")
    print(f"  High Quality Rate:     {conv_stats['high_quality_rate']:.1f}%")
    print(f"  Average Score:         {conv_stats['avg_score']:.3f}")
    
    # ────────────────────────────────────────
    # VALIDATION
    # ────────────────────────────────────────
    
    print_section("VALIDATION CHECKLIST")
    
    checks = []
    
    # Check 1: Data fetching
    checks.append((
        "Data Manager fetches all 4 timeframes",
        successful == len(tickers)
    ))
    
    # Check 2: Cache working
    checks.append((
        "Cache system operational",
        data_stats['cached_tickers'] > 0
    ))
    
    # Check 3: FVG detection
    checks.append((
        "FVG engine detects patterns",
        fvg_stats['convergence_passed'] > 0 or fvg_stats['convergence_failed'] > 0
    ))
    
    # Check 4: Scoring works
    checks.append((
        "Convergence scorer operational",
        conv_stats['signals_scored'] > 0 if signals else True  # OK if no signals
    ))
    
    # Check 5: Reasonable boost values
    if signals:
        boosts = [mtf_convergence_scorer.get_confidence_boost(s) for s in signals]
        checks.append((
            "Confidence boosts in valid range (0.05-0.15)",
            all(0.05 <= b <= 0.15 for b in boosts)
        ))
    
    # Check 6: No crashes
    checks.append((
        "No errors or crashes",
        True  # If we got here, no crashes
    ))
    
    print()
    all_passed = True
    for check_name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {check_name}")
        if not passed:
            all_passed = False
    
    # ────────────────────────────────────────
    # CONCLUSION
    # ────────────────────────────────────────
    
    print_header("TEST RESULTS")
    
    if all_passed:
        print("✅ ✅ ✅ ALL CHECKS PASSED \u2705 ✅ ✅\n")
        print("MTF Infrastructure is READY FOR INTEGRATION with sniper.py!\n")
        print("Next Steps:")
        print("  1. Review MTF_TESTING_GUIDE.md for integration instructions")
        print("  2. Modify sniper.py to use MTF engine instead of single-TF detection")
        print("  3. Add MTF tracking to signal_analytics.py")
        print("  4. Update monitoring_dashboard.py with MTF metrics")
    else:
        print("❌ SOME CHECKS FAILED\n")
        print("Please review the validation checklist above and:")
        print("  1. Check MTF_TESTING_GUIDE.md troubleshooting section")
        print("  2. Verify EODHD_API_KEY is valid in config.py")
        print("  3. Ensure market is open or use historical data")
        print("  4. Try with different tickers or time periods")
    
    print("\n" + "="*80)
    print("🎉 Test complete!")
    print("="*80 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
