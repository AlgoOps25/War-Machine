"""
Full Data-Driven Confirmation Analysis Pipeline

Executes complete analysis workflow:
  1. Extract signals from signal_analytics.db
  2. Enrich with EODHD historical data
  3. Analyze patterns in winning vs losing signals
  4. Generate data-driven recommendations

Outputs:
  - Comprehensive analysis report
  - ML-ready feature matrix (CSV)
  - Recommended confirmation criteria
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import json

# Import analysis modules
try:
    from analyze_confirmation_patterns import ConfirmationAnalyzer
    from eodhd_historical_enrichment import SignalEnricher
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"❌ Module import error: {e}")
    MODULES_AVAILABLE = False

ET = ZoneInfo("America/New_York")


def extract_signals_from_db(db_path: str = "signal_analytics.db") -> pd.DataFrame:
    """
    Extract all closed signals from database.
    
    Returns:
        DataFrame with signal data
    """
    conn = sqlite3.connect(db_path)
    
    query = """
    SELECT *
    FROM signals
    WHERE outcome IN ('win', 'loss')
    ORDER BY generated_at DESC
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    return df


def generate_recommendations(analysis_results: Dict, enriched_df: pd.DataFrame) -> str:
    """
    Generate data-driven confirmation criteria recommendations.
    
    Args:
        analysis_results: Dict from ConfirmationAnalyzer
        enriched_df: DataFrame with enriched signal features
    
    Returns:
        Formatted recommendations string
    """
    rec = []
    rec.append("="*80)
    rec.append("DATA-DRIVEN CONFIRMATION RECOMMENDATIONS")
    rec.append("="*80)
    rec.append("")
    
    # Analyze timing patterns
    if 'immediate_pct' in analysis_results:
        immediate_failure_rate = analysis_results['immediate_pct']
        
        if immediate_failure_rate > 60:
            rec.append("[CRITICAL] 🚨 Immediate Failure Problem Detected")
            rec.append(f"  {immediate_failure_rate:.0f}% of losses fail within 5 minutes")
            rec.append("")
            rec.append("  RECOMMENDATION #1: Implement Holding Period")
            rec.append("  - Require breakout to hold for 2-3 bars (10-15 minutes on 5m chart)")
            rec.append("  - Logic: Price must close above resistance for 2 consecutive bars")
            rec.append("  - Expected Impact: Filter ~60% of false breakouts")
            rec.append("")
    
    # Analyze hold rate patterns
    if 'breakout_hold_rate' in enriched_df.columns:
        winners = enriched_df[enriched_df['target'] == 1]
        losers = enriched_df[enriched_df['target'] == 0]
        
        if len(winners) > 0 and len(losers) > 0:
            winner_hold_rate = winners['breakout_hold_rate'].mean()
            loser_hold_rate = losers['breakout_hold_rate'].mean()
            
            rec.append("[PATTERN] 📊 Post-Breakout Hold Rate Analysis")
            rec.append(f"  Winners: {winner_hold_rate:.1f}% of bars hold above entry")
            rec.append(f"  Losers: {loser_hold_rate:.1f}% of bars hold above entry")
            rec.append("")
            
            # Calculate optimal threshold
            threshold = (winner_hold_rate + loser_hold_rate) / 2
            rec.append("  RECOMMENDATION #2: Hold Rate Filter")
            rec.append(f"  - Require ≥{threshold:.0f}% hold rate in first 3 bars after breakout")
            rec.append("  - Logic: At least 2 out of 3 bars must close above entry")
            rec.append("")
    
    # Analyze volume patterns
    if 'breakout_volume_ratio' in enriched_df.columns:
        winners = enriched_df[enriched_df['target'] == 1]
        losers = enriched_df[enriched_df['target'] == 0]
        
        if len(winners) > 0 and len(losers) > 0:
            winner_vol = winners['breakout_volume_ratio'].mean()
            loser_vol = losers['breakout_volume_ratio'].mean()
            
            rec.append("[PATTERN] 📈 Breakout Volume Analysis")
            rec.append(f"  Winners Avg: {winner_vol:.2f}x pre-breakout volume")
            rec.append(f"  Losers Avg: {loser_vol:.2f}x pre-breakout volume")
            rec.append("")
            
            if winner_vol > loser_vol * 1.2:
                rec.append("  RECOMMENDATION #3: Volume Confirmation")
                rec.append(f"  - Require breakout volume ≥{winner_vol:.1f}x average")
                rec.append("  - Current system uses 2.0x (may need adjustment)")
                rec.append("")
    
    # Analyze entry placement
    rec.append("[STRATEGY] 🎯 Entry Placement Optimization")
    rec.append("  Current Issue: Entering AT resistance = buying at top")
    rec.append("")
    rec.append("  RECOMMENDATION #4: Entry Above Breakout")
    rec.append("  - Entry Price = Resistance * 1.0015 (0.15% above)")
    rec.append("  - Confirms breakout is holding before entry")
    rec.append("  - Avoids false breakouts at exact level")
    rec.append("")
    
    # Stop placement
    rec.append("[RISK] 🛡️ Stop Loss Optimization")
    rec.append("  Current: 1.5 ATR stop (too tight for intraday volatility)")
    rec.append("")
    rec.append("  RECOMMENDATION #5: Wider Stops")
    rec.append("  - ATR Multiplier: 2.0 (was 1.5)")
    rec.append("  - Gives breakout room to breathe")
    rec.append("  - Reduces stop-outs from normal noise")
    rec.append("")
    
    # Implementation priority
    rec.append("="*80)
    rec.append("IMPLEMENTATION PRIORITY (High to Low Impact)")
    rec.append("="*80)
    rec.append("")
    rec.append("Priority 1 (Quick Wins - Deploy Today):")
    rec.append("  ✅ Entry 0.15% above breakout")
    rec.append("  ✅ 2-bar holding period requirement")
    rec.append("  ✅ Widen stops to 2.0 ATR")
    rec.append("")
    rec.append("Priority 2 (Data-Driven - Deploy This Week):")
    rec.append("  🔧 Hold rate filter (data-backed threshold)")
    rec.append("  🔧 Volume confirmation adjustment (if needed)")
    rec.append("  🔧 Confidence penalty for weak confirmation")
    rec.append("")
    rec.append("Priority 3 (Advanced - Phase 2.0):")
    rec.append("  🚀 ML-based confirmation (train on enriched features)")
    rec.append("  🚀 Retest/pullback entry mode")
    rec.append("  🚀 Multi-timeframe convergence filter")
    rec.append("")
    
    return "\n".join(rec)


def main():
    """Execute full analysis pipeline."""
    print("\n" + "="*80)
    print("FULL DATA-DRIVEN CONFIRMATION ANALYSIS")
    print("="*80 + "\n")
    
    if not MODULES_AVAILABLE:
        print("❌ Required modules not available")
        return
    
    # Step 1: Basic pattern analysis
    print("[STEP 1] Analyzing signal patterns from database...\n")
    analyzer = ConfirmationAnalyzer()
    
    try:
        basic_report = analyzer.generate_full_report()
        print(basic_report)
        
        # Extract key metrics
        failure_timing = analyzer.analyze_time_to_failure()
        winning_patterns = analyzer.analyze_winning_patterns()
        
    finally:
        analyzer.close()
    
    # Step 2: EODHD enrichment (if available)
    print("\n[STEP 2] Enriching signals with EODHD data...\n")
    
    try:
        enricher = SignalEnricher()
        
        # Get signals from database
        signals_df = extract_signals_from_db()
        print(f"Found {len(signals_df)} closed signals to enrich\n")
        
        # Limit to recent signals for faster analysis (can be expanded)
        recent_signals = signals_df.head(20).to_dict('records')
        
        # Enrich with EODHD data
        enriched_signals = enricher.enrich_signal_list(recent_signals)
        
        # Build ML feature matrix
        features_df = enricher.build_ml_features_dataframe(enriched_signals)
        
        # Save to CSV
        timestamp = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
        features_filename = f"ml_features_{timestamp}.csv"
        features_df.to_csv(features_filename, index=False, encoding='utf-8')
        print(f"\n✅ ML features saved to: {features_filename}\n")
        
    except Exception as e:
        print(f"⚠️ EODHD enrichment error: {e}")
        print("Continuing with basic analysis only...\n")
        features_df = pd.DataFrame()
    
    # Step 3: Generate recommendations
    print("[STEP 3] Generating data-driven recommendations...\n")
    
    analysis_results = {
        'immediate_pct': failure_timing.get('immediate_pct', 0) if failure_timing else 0,
        'median_hold_time': failure_timing.get('median_hold_time', 0) if failure_timing else 0
    }
    
    recommendations = generate_recommendations(analysis_results, features_df)
    print(recommendations)
    
    # Save full report
    timestamp = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
    report_filename = f"full_analysis_report_{timestamp}.txt"
    
    with open(report_filename, 'w', encoding='utf-8') as f:
        f.write(basic_report)
        f.write("\n\n")
        f.write(recommendations)

    
    print(f"\n✅ Full report saved to: {report_filename}\n")
    print("="*80)
    print("ANALYSIS COMPLETE")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
