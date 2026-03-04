#!/usr/bin/env python3
"""
Historical Advisor - Validate DTE decisions against actual position outcomes
Reviews past positions to see if DTE choices led to optimal results.
"""

import sys
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from position_manager import Position
from dte_selector import DTESelector, DTEConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class HistoricalAdvisor:
    """Analyze historical positions to validate DTE strategy"""
    
    def __init__(self, config: DTEConfig):
        self.dte_selector = DTESelector(config)
        self.analyses: List[Dict[str, Any]] = []
    
    def load_position_history(self, csv_path: str) -> pd.DataFrame:
        """
        Load historical position data from CSV
        Expected columns: entry_time, exit_time, symbol, strike, dte, 
                         entry_price, exit_price, pnl, pnl_pct
        """
        try:
            df = pd.read_csv(csv_path)
            df['entry_time'] = pd.to_datetime(df['entry_time'])
            df['exit_time'] = pd.to_datetime(df['exit_time'])
            logger.info(f"Loaded {len(df)} historical positions from {csv_path}")
            return df
        except Exception as e:
            logger.error(f"Error loading position history: {e}")
            return pd.DataFrame()
    
    def analyze_position(self, position_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a single historical position
        """
        entry_time = position_data['entry_time']
        actual_dte = position_data['dte']
        pnl_pct = position_data['pnl_pct']
        
        # What DTE would selector have chosen?
        recommended_dte = self.dte_selector.select_dte(entry_time)
        
        # Calculate time in trade
        exit_time = position_data['exit_time']
        hold_duration = (exit_time - entry_time).total_seconds() / 60  # minutes
        
        analysis = {
            'entry_time': entry_time,
            'symbol': position_data['symbol'],
            'actual_dte': actual_dte,
            'recommended_dte': recommended_dte,
            'dte_match': actual_dte == recommended_dte,
            'pnl_pct': pnl_pct,
            'hold_duration_min': hold_duration,
            'outcome': 'WIN' if pnl_pct > 0 else 'LOSS'
        }
        
        # Determine if DTE choice was optimal
        analysis['dte_assessment'] = self._assess_dte_choice(
            entry_time, actual_dte, recommended_dte, pnl_pct, hold_duration
        )
        
        return analysis
    
    def _assess_dte_choice(self, entry_time: datetime, actual_dte: int,
                          recommended_dte: int, pnl_pct: float, 
                          hold_duration: float) -> str:
        """
        Assess if the DTE choice was optimal for the trade outcome
        """
        hour = entry_time.hour
        minute = entry_time.minute
        is_wednesday = entry_time.weekday() == 2
        
        # Quick scalp (< 5 min) - 0DTE is optimal
        if hold_duration < 5:
            if actual_dte == 0:
                return "OPTIMAL - Quick scalp with 0DTE"
            else:
                return f"INEFFICIENT - Quick scalp used {actual_dte}DTE (should be 0DTE)"
        
        # Hold > 2 hours - needs higher DTE
        if hold_duration > 120:
            if actual_dte >= 2:
                return "OPTIMAL - Long hold with sufficient DTE"
            else:
                return f"RISKY - Long hold with only {actual_dte}DTE (time decay risk)"
        
        # Wednesday 0DTE check
        if is_wednesday and actual_dte == 0 and self.dte_selector.config.avoid_wed_0dte:
            if pnl_pct < 0:
                return "AVOIDED CORRECTLY - Wed 0DTE resulted in loss"
            else:
                return "LUCKY - Wed 0DTE worked but violated rule"
        
        # Pre-10 AM trades
        if hour < 10:
            if actual_dte == 0 and pnl_pct > 0:
                return "OPTIMAL - Early 0DTE winner"
            elif actual_dte > 0:
                return f"CONSERVATIVE - Used {actual_dte}DTE early (0DTE available)"
        
        # Standard assessment
        if actual_dte == recommended_dte:
            return "MATCHED - Used recommended DTE"
        elif pnl_pct > 0:
            return f"SUCCESS - Non-standard DTE={actual_dte} worked (rec={recommended_dte})"
        else:
            return f"QUESTION - Loss with DTE={actual_dte} (rec={recommended_dte})"
    
    def analyze_all_positions(self, positions_df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze all historical positions
        """
        logger.info(f"Analyzing {len(positions_df)} historical positions")
        
        for idx, row in positions_df.iterrows():
            analysis = self.analyze_position(row.to_dict())
            self.analyses.append(analysis)
        
        results_df = pd.DataFrame(self.analyses)
        logger.info("Analysis complete")
        
        return results_df
    
    def generate_report(self, results_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate comprehensive report on DTE effectiveness
        """
        total_trades = len(results_df)
        
        # Win rate by actual DTE
        win_rate_by_dte = results_df.groupby('actual_dte').apply(
            lambda x: (x['outcome'] == 'WIN').sum() / len(x) * 100
        ).to_dict()
        
        # Average PnL by DTE
        avg_pnl_by_dte = results_df.groupby('actual_dte')['pnl_pct'].mean().to_dict()
        
        # DTE match analysis
        dte_matches = results_df['dte_match'].sum()
        match_rate = dte_matches / total_trades * 100
        
        # Win rate when matched vs not matched
        matched_wins = results_df[results_df['dte_match'] == True]['outcome'].value_counts()
        unmatched_wins = results_df[results_df['dte_match'] == False]['outcome'].value_counts()
        
        matched_win_rate = matched_wins.get('WIN', 0) / matched_wins.sum() * 100 if len(matched_wins) > 0 else 0
        unmatched_win_rate = unmatched_wins.get('WIN', 0) / unmatched_wins.sum() * 100 if len(unmatched_wins) > 0 else 0
        
        # Assessment categories
        assessment_counts = results_df['dte_assessment'].value_counts().to_dict()
        
        return {
            'total_trades': total_trades,
            'dte_match_rate': match_rate,
            'matched_trades': dte_matches,
            'win_rate_by_dte': win_rate_by_dte,
            'avg_pnl_by_dte': avg_pnl_by_dte,
            'matched_win_rate': matched_win_rate,
            'unmatched_win_rate': unmatched_win_rate,
            'assessment_breakdown': assessment_counts,
            'date_range': {
                'start': results_df['entry_time'].min(),
                'end': results_df['entry_time'].max()
            }
        }
    
    def print_report(self, report: Dict[str, Any]) -> None:
        """
        Print formatted report
        """
        print("\n" + "="*70)
        print("HISTORICAL DTE ADVISOR REPORT")
        print("="*70)
        print(f"\nAnalyzed {report['total_trades']} historical trades")
        print(f"Date Range: {report['date_range']['start']} to {report['date_range']['end']}")
        
        print(f"\nDTE Recommendation Match Rate: {report['dte_match_rate']:.1f}%")
        print(f"  Trades matching recommendation: {report['matched_trades']}")
        print(f"  Win rate when matched: {report['matched_win_rate']:.1f}%")
        print(f"  Win rate when not matched: {report['unmatched_win_rate']:.1f}%")
        
        print("\nWin Rate by DTE:")
        for dte in sorted(report['win_rate_by_dte'].keys()):
            win_rate = report['win_rate_by_dte'][dte]
            avg_pnl = report['avg_pnl_by_dte'][dte]
            print(f"  {dte} DTE: {win_rate:.1f}% win rate, {avg_pnl:+.2f}% avg PnL")
        
        print("\nDTE Assessment Breakdown:")
        for assessment, count in sorted(report['assessment_breakdown'].items()):
            pct = count / report['total_trades'] * 100
            print(f"  {assessment}: {count} ({pct:.1f}%)")
        
        print("\n" + "="*70)
        
        # Key insights
        print("\nKEY INSIGHTS:")
        if report['matched_win_rate'] > report['unmatched_win_rate']:
            diff = report['matched_win_rate'] - report['unmatched_win_rate']
            print(f"  ✓ Following DTE recommendations improved win rate by {diff:.1f}%")
        else:
            print(f"  ⚠ Manual DTE choices outperformed recommendations")
        
        best_dte = max(report['win_rate_by_dte'].items(), key=lambda x: x[1])
        print(f"  ✓ Best performing DTE: {best_dte[0]} with {best_dte[1]:.1f}% win rate")
        
        print("\n" + "="*70 + "\n")

def main():
    """Run historical advisor"""
    
    # Configure (match your production settings)
    config = DTEConfig(
        default_dte=0,
        pre_1000_dte=0,
        post_1000_dte=1,
        post_1030_dte=2,
        avoid_wed_0dte=True,
        min_time_value=0.05
    )
    
    advisor = HistoricalAdvisor(config)
    
    # Load your position history
    positions_df = advisor.load_position_history('backtests/position_history.csv')
    
    if positions_df.empty:
        logger.error("No position history loaded - check CSV path")
        return
    
    # Analyze all positions
    results_df = advisor.analyze_all_positions(positions_df)
    
    # Save detailed results
    results_df.to_csv('backtests/historical_advisor_results.csv', index=False)
    logger.info("Detailed results saved to backtests/historical_advisor_results.csv")
    
    # Generate and print report
    report = advisor.generate_report(results_df)
    advisor.print_report(report)

if __name__ == '__main__':
    main()