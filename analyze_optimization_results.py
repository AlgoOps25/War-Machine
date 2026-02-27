#!/usr/bin/env python3
"""
Comprehensive Optimization Results Analyzer

Analyzes focused_optimization_results.csv to identify optimal parameters.
Run this after focused_optimization.py completes.

Usage:
    python analyze_optimization_results.py
"""

import pandas as pd
import json
from pathlib import Path
from datetime import datetime


class OptimizationAnalyzer:
    """
    Analyzes optimization results to find optimal trading parameters.
    """
    
    def __init__(self, results_file="focused_optimization_results.csv"):
        self.results_file = results_file
        self.df = None
        self.quality = None
        self.winner = None
        
        print("\n" + "="*70)
        print("OPTIMIZATION RESULTS ANALYZER")
        print("="*70)
        print()
    
    def load_results(self):
        """Load results CSV."""
        if not Path(self.results_file).exists():
            print(f"❌ ERROR: {self.results_file} not found!")
            print(f"   Make sure focused_optimization.py completed successfully.")
            return False
        
        self.df = pd.read_csv(self.results_file)
        print(f"✅ Loaded {len(self.df)} configuration results")
        print()
        return True
    
    def stage1_initial_filtering(self):
        """Apply quality gates to filter configurations."""
        print("="*70)
        print("STAGE 1: INITIAL FILTERING")
        print("="*70)
        print()
        
        print("Quality Gate Criteria:")
        print("  • Minimum trades: 20 (statistical significance)")
        print("  • Maximum trades: 100 (avoid over-trading)")
        print("  • Minimum win rate: 45% (better than coin flip)")
        print("  • Minimum profit factor: 1.5 (making more than losing)")
        print("  • Total P&L: Positive")
        print()
        
        # Apply filters
        self.quality = self.df[
            (self.df["trades"] >= 20) &
            (self.df["trades"] <= 100) &
            (self.df["win_rate"] >= 45) &
            (self.df["profit_factor"] >= 1.5) &
            (self.df["total_pnl"] > 0)
        ].copy()
        
        total = len(self.df)
        passed = len(self.quality)
        
        print(f"📊 Results:")
        print(f"   Configurations Tested: {total}")
        print(f"   Quality Configs: {passed} ({passed/total*100:.1f}%)")
        print()
        
        if passed == 0:
            print("⚠️  WARNING: No configurations met quality criteria!")
            print("   Showing best available results instead...")
            print()
            
            # Fallback: Show best by profit factor
            self.quality = self.df[self.df["trades"] >= 10].copy()
            if len(self.quality) == 0:
                self.quality = self.df.copy()
        
        return len(self.quality) > 0
    
    def stage2_ranking_analysis(self):
        """Identify top performers by multiple metrics."""
        print("="*70)
        print("STAGE 2: RANKING ANALYSIS")
        print("="*70)
        print()
        
        # Top by profit factor
        top_by_pf = self.quality.nlargest(10, "profit_factor")
        
        # Top by win rate
        top_by_wr = self.quality.nlargest(10, "win_rate")
        
        # Top by total P&L
        top_by_pnl = self.quality.nlargest(10, "total_pnl")
        
        print("🥇 TOP 10 BY PROFIT FACTOR:")
        print()
        for i, (idx, row) in enumerate(top_by_pf.head(10).iterrows(), 1):
            print(f"{i}. Vol={row['volume_multiplier']}x | "
                  f"ATR={row['atr_stop_multiplier']}x | "
                  f"RR={row['target_rr']}R | "
                  f"LB={row['lookback']}")
            print(f"   PF: {row['profit_factor']:.2f} | "
                  f"WR: {row['win_rate']:.1f}% | "
                  f"Trades: {row['trades']:.0f} | "
                  f"P&L: ${row['total_pnl']:.2f}")
            print()
        
        print("🎯 TOP 10 BY WIN RATE:")
        print()
        for i, (idx, row) in enumerate(top_by_wr.head(10).iterrows(), 1):
            print(f"{i}. Vol={row['volume_multiplier']}x | "
                  f"ATR={row['atr_stop_multiplier']}x | "
                  f"RR={row['target_rr']}R | "
                  f"LB={row['lookback']}")
            print(f"   WR: {row['win_rate']:.1f}% | "
                  f"PF: {row['profit_factor']:.2f} | "
                  f"Trades: {row['trades']:.0f} | "
                  f"P&L: ${row['total_pnl']:.2f}")
            print()
        
        print("💰 TOP 10 BY TOTAL P&L:")
        print()
        for i, (idx, row) in enumerate(top_by_pnl.head(10).iterrows(), 1):
            print(f"{i}. Vol={row['volume_multiplier']}x | "
                  f"ATR={row['atr_stop_multiplier']}x | "
                  f"RR={row['target_rr']}R | "
                  f"LB={row['lookback']}")
            print(f"   P&L: ${row['total_pnl']:.2f} | "
                  f"PF: {row['profit_factor']:.2f} | "
                  f"WR: {row['win_rate']:.1f}% | "
                  f"Trades: {row['trades']:.0f}")
            print()
    
    def stage3_pattern_recognition(self):
        """Identify parameter patterns in top performers."""
        print("="*70)
        print("STAGE 3: PATTERN RECOGNITION")
        print("="*70)
        print()
        
        # Get top 20 configs by composite score
        top20 = self.quality.nlargest(20, "profit_factor")
        
        print("📈 Parameter Patterns in Top 20 Performers:")
        print()
        
        print("Volume Multiplier Distribution:")
        vol_counts = top20["volume_multiplier"].value_counts().sort_index()
        for vol, count in vol_counts.items():
            pct = count / len(top20) * 100
            bar = "█" * int(pct / 5)
            print(f"  {vol}x: {count:2d} ({pct:5.1f}%) {bar}")
        print()
        
        print("ATR Stop Multiplier Distribution:")
        atr_counts = top20["atr_stop_multiplier"].value_counts().sort_index()
        for atr, count in atr_counts.items():
            pct = count / len(top20) * 100
            bar = "█" * int(pct / 5)
            print(f"  {atr}x: {count:2d} ({pct:5.1f}%) {bar}")
        print()
        
        print("Target R:R Distribution:")
        rr_counts = top20["target_rr"].value_counts().sort_index()
        for rr, count in rr_counts.items():
            pct = count / len(top20) * 100
            bar = "█" * int(pct / 5)
            print(f"  {rr}R: {count:2d} ({pct:5.1f}%) {bar}")
        print()
        
        print("Lookback Period Distribution:")
        lb_counts = top20["lookback"].value_counts().sort_index()
        for lb, count in lb_counts.items():
            pct = count / len(top20) * 100
            bar = "█" * int(pct / 5)
            print(f"  {lb} bars: {count:2d} ({pct:5.1f}%) {bar}")
        print()
    
    def stage4_filter_effectiveness(self):
        """Analyze which filters improve quality."""
        print("="*70)
        print("STAGE 4: FILTER EFFECTIVENESS ANALYSIS")
        print("="*70)
        print()
        
        print("🔍 Momentum Filter Performance:")
        for momentum in ['none', 'weak', 'strong']:
            subset = self.quality[self.quality["momentum_filter"] == momentum]
            if len(subset) > 0:
                print(f"  {momentum:8s}: {len(subset):3d} configs | "
                      f"Avg WR: {subset['win_rate'].mean():5.1f}% | "
                      f"Avg PF: {subset['profit_factor'].mean():.2f} | "
                      f"Avg Trades: {subset['trades'].mean():.0f}")
        print()
        
        print("⏰ Time Filter Performance:")
        for timefilter in ['all', 'open', 'mid', 'power']:
            subset = self.quality[self.quality["time_filter"] == timefilter]
            if len(subset) > 0:
                print(f"  {timefilter:8s}: {len(subset):3d} configs | "
                      f"Avg WR: {subset['win_rate'].mean():5.1f}% | "
                      f"Avg PF: {subset['profit_factor'].mean():.2f} | "
                      f"Avg Trades: {subset['trades'].mean():.0f}")
        print()
        
        print("📊 Trend Filter Performance:")
        for trend in ['none', 'aligned']:
            subset = self.quality[self.quality["trend_filter"] == trend]
            if len(subset) > 0:
                print(f"  {trend:8s}: {len(subset):3d} configs | "
                      f"Avg WR: {subset['win_rate'].mean():5.1f}% | "
                      f"Avg PF: {subset['profit_factor'].mean():.2f} | "
                      f"Avg Trades: {subset['trades'].mean():.0f}")
        print()
    
    def stage5_tradeoff_analysis(self):
        """Compare conservative vs aggressive approaches."""
        print("="*70)
        print("STAGE 5: TRADE-OFF ANALYSIS")
        print("="*70)
        print()
        
        # Conservative: Lower volume, tighter stops, lower R:R
        conservative = self.quality[
            (self.quality["volume_multiplier"] <= 3.0) &
            (self.quality["atr_stop_multiplier"] <= 2.5) &
            (self.quality["target_rr"] <= 2.5)
        ]
        
        # Aggressive: Higher volume, wider stops, higher R:R
        aggressive = self.quality[
            (self.quality["volume_multiplier"] >= 4.0) &
            (self.quality["atr_stop_multiplier"] >= 2.5) &
            (self.quality["target_rr"] >= 3.0)
        ]
        
        # Moderate: Middle ground
        moderate = self.quality[
            (self.quality["volume_multiplier"].between(3.0, 4.0)) &
            (self.quality["atr_stop_multiplier"].between(2.0, 2.5)) &
            (self.quality["target_rr"].between(2.5, 3.0))
        ]
        
        print(f"🛡️  CONSERVATIVE APPROACH ({len(conservative)} configs):")
        print(f"   Parameters: Vol ≤3.0x, ATR ≤2.5x, RR ≤2.5R")
        if len(conservative) > 0:
            print(f"   Avg Trades: {conservative['trades'].mean():.0f}")
            print(f"   Avg Win Rate: {conservative['win_rate'].mean():.1f}%")
            print(f"   Avg Profit Factor: {conservative['profit_factor'].mean():.2f}")
            print(f"   Avg Total P&L: ${conservative['total_pnl'].mean():.2f}")
        else:
            print("   No configs match criteria")
        print()
        
        print(f"⚖️  MODERATE APPROACH ({len(moderate)} configs):")
        print(f"   Parameters: Vol 3-4x, ATR 2-2.5x, RR 2.5-3R")
        if len(moderate) > 0:
            print(f"   Avg Trades: {moderate['trades'].mean():.0f}")
            print(f"   Avg Win Rate: {moderate['win_rate'].mean():.1f}%")
            print(f"   Avg Profit Factor: {moderate['profit_factor'].mean():.2f}")
            print(f"   Avg Total P&L: ${moderate['total_pnl'].mean():.2f}")
        else:
            print("   No configs match criteria")
        print()
        
        print(f"⚔️  AGGRESSIVE APPROACH ({len(aggressive)} configs):")
        print(f"   Parameters: Vol ≥4.0x, ATR ≥2.5x, RR ≥3.0R")
        if len(aggressive) > 0:
            print(f"   Avg Trades: {aggressive['trades'].mean():.0f}")
            print(f"   Avg Win Rate: {aggressive['win_rate'].mean():.1f}%")
            print(f"   Avg Profit Factor: {aggressive['profit_factor'].mean():.2f}")
            print(f"   Avg Total P&L: ${aggressive['total_pnl'].mean():.2f}")
        else:
            print("   No configs match criteria")
        print()
    
    def stage6_final_selection(self):
        """Choose the optimal configuration."""
        print("="*70)
        print("STAGE 6: FINAL SELECTION")
        print("="*70)
        print()
        
        print("🧮 Calculating Composite Scores...")
        print("   Weighting: 40% Profit Factor, 30% Win Rate, 20% Trade Count, 10% Total P&L")
        print()
        
        # Composite scoring
        self.quality["composite_score"] = (
            self.quality["profit_factor"].rank(pct=True) * 0.40 +
            self.quality["win_rate"].rank(pct=True) * 0.30 +
            self.quality["trades"].rank(pct=True) * 0.20 +
            self.quality["total_pnl"].rank(pct=True) * 0.10
        )
        
        # Get winner
        self.winner = self.quality.nlargest(1, "composite_score").iloc[0]
        
        print("🏆 OPTIMAL CONFIGURATION:")
        print()
        print("  Core Parameters:")
        print(f"    Volume Multiplier:    {self.winner['volume_multiplier']}x")
        print(f"    ATR Stop Multiplier:  {self.winner['atr_stop_multiplier']}x")
        print(f"    Target Risk:Reward:   {self.winner['target_rr']}R")
        print(f"    Lookback Period:      {self.winner['lookback']} bars")
        print()
        
        print("  Filters:")
        print(f"    Momentum Filter:      {self.winner['momentum_filter']}")
        print(f"    Trend Filter:         {self.winner['trend_filter']}")
        print(f"    Time Filter:          {self.winner['time_filter']}")
        print()
        
        print("  Performance Metrics:")
        print(f"    Total Trades:         {self.winner['trades']:.0f}")
        print(f"    Win Rate:             {self.winner['win_rate']:.1f}%")
        print(f"    Profit Factor:        {self.winner['profit_factor']:.2f}")
        print(f"    Average Win:          ${self.winner['avg_win']:.2f}")
        print(f"    Average Loss:         ${self.winner['avg_loss']:.2f}")
        print(f"    Total P&L:            ${self.winner['total_pnl']:.2f}")
        print(f"    Composite Score:      {self.winner['composite_score']:.3f}")
        print()
    
    def save_recommendations(self):
        """Save optimal configuration to JSON."""
        print("="*70)
        print("SAVING RECOMMENDATIONS")
        print("="*70)
        print()
        
        # Create recommendation dict
        recommendation = {
            "timestamp": datetime.now().isoformat(),
            "optimal_config": {
                "volume_multiplier": float(self.winner['volume_multiplier']),
                "atr_stop_multiplier": float(self.winner['atr_stop_multiplier']),
                "target_rr": float(self.winner['target_rr']),
                "lookback": int(self.winner['lookback']),
                "momentum_filter": str(self.winner['momentum_filter']),
                "trend_filter": str(self.winner['trend_filter']),
                "time_filter": str(self.winner['time_filter'])
            },
            "performance": {
                "trades": int(self.winner['trades']),
                "win_rate": float(self.winner['win_rate']),
                "profit_factor": float(self.winner['profit_factor']),
                "avg_win": float(self.winner['avg_win']),
                "avg_loss": float(self.winner['avg_loss']),
                "total_pnl": float(self.winner['total_pnl']),
                "composite_score": float(self.winner['composite_score'])
            },
            "next_steps": [
                "1. Update signal generator with optimal parameters",
                "2. Run paper trading session to validate",
                "3. Monitor first 10-20 trades for consistency",
                "4. Adjust position sizing based on account size"
            ]
        }
        
        # Save to file
        output_file = "optimal_config_recommendation.json"
        with open(output_file, 'w') as f:
            json.dump(recommendation, f, indent=2)
        
        print(f"✅ Saved optimal configuration to: {output_file}")
        print()
        
        # Also save top 20 configs
        top20 = self.quality.nlargest(20, "composite_score")
        top20.to_csv("top_20_configurations.csv", index=False)
        print(f"✅ Saved top 20 configurations to: top_20_configurations.csv")
        print()
    
    def run_full_analysis(self):
        """Run complete analysis pipeline."""
        if not self.load_results():
            return False
        
        if not self.stage1_initial_filtering():
            print("❌ ERROR: No valid configurations to analyze!")
            return False
        
        self.stage2_ranking_analysis()
        self.stage3_pattern_recognition()
        self.stage4_filter_effectiveness()
        self.stage5_tradeoff_analysis()
        self.stage6_final_selection()
        self.save_recommendations()
        
        print("="*70)
        print("✅ ANALYSIS COMPLETE")
        print("="*70)
        print()
        print("Next Steps:")
        print("  1. Review optimal_config_recommendation.json")
        print("  2. Examine top_20_configurations.csv for alternatives")
        print("  3. Update your signal generator with chosen parameters")
        print("  4. Run paper trading to validate before going live")
        print()
        
        return True


def main():
    analyzer = OptimizationAnalyzer()
    success = analyzer.run_full_analysis()
    
    if not success:
        print("\n⚠️  Analysis could not complete. Check that optimization finished successfully.")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
