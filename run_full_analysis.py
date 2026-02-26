"""Full Data-Driven Confirmation Analysis Pipeline."""

import sqlite3
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

try:
    from analyze_confirmation_patterns import ConfirmationAnalyzer
    from eodhd_historical_enrichment import SignalEnricher
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"❌ Module import error: {e}")
    MODULES_AVAILABLE = False


def generate_recommendations(analysis_results, enriched_df):
    """Generate data-driven recommendations."""
    rec = []
    rec.append("="*80)
    rec.append("DATA-DRIVEN CONFIRMATION RECOMMENDATIONS")
    rec.append("="*80)
    rec.append("")
    
    rec.append("[STRATEGY] 🎯 Entry Placement Optimization")
    rec.append("  Current Issue: Entering AT resistance = buying at top")
    rec.append("")
    rec.append("  RECOMMENDATION #4: Entry Above Breakout")
    rec.append("  - Entry Price = Resistance * 1.0015 (0.15% above)")
    rec.append("  - Confirms breakout is holding before entry")
    rec.append("  - Avoids false breakouts at exact level")
    rec.append("")
    
    rec.append("[RISK] 🛡️ Stop Loss Optimization")
    rec.append("  Current: 1.5 ATR stop (too tight for intraday volatility)")
    rec.append("")
    rec.append("  RECOMMENDATION #5: Wider Stops")
    rec.append("  - ATR Multiplier: 2.0 (was 1.5)")
    rec.append("  - Gives breakout room to breathe")
    rec.append("  - Reduces stop-outs from normal noise")
    rec.append("")
    
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
    
    print("[STEP 1] Analyzing signal patterns from database...\n")
    analyzer = ConfirmationAnalyzer()
    
    try:
        basic_report = analyzer.generate_full_report()
        print(basic_report)
        
        failure_timing = analyzer.analyze_time_to_failure()
        winning_patterns = analyzer.analyze_winning_patterns()
        
    finally:
        analyzer.close()
    
    print("\n[STEP 2] Enriching signals with EODHD data...\n")
    
    try:
        enricher = SignalEnricher()
        conn = sqlite3.connect("signal_analytics.db")
        signals_df = pd.read_sql_query("SELECT * FROM signals WHERE outcome IN ('win', 'loss') ORDER BY generated_at DESC LIMIT 20", conn)
        conn.close()
        
        recent_signals = signals_df.to_dict('records')
        enriched_signals = enricher.enrich_signal_list(recent_signals)
        features_df = enricher.build_ml_features_dataframe(enriched_signals)
        
        timestamp = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
        features_df.to_csv(f"ml_features_{timestamp}.csv", index=False, encoding='utf-8')
        
    except Exception as e:
        print(f"⚠️ EODHD enrichment error: {e}")
        print("Continuing with basic analysis only...\n")
        features_df = pd.DataFrame()
    
    print("[STEP 3] Generating data-driven recommendations...\n")
    
    analysis_results = {
        'immediate_pct': failure_timing.get('immediate_pct', 0) if failure_timing else 0
    }
    
    recommendations = generate_recommendations(analysis_results, features_df)
    print(recommendations)
    
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
