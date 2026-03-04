#!/usr/bin/env python3
"""
Backtest DTE Logic on Historical Signals
Validates DTE selector decisions against past market data.
"""

import sys
import logging
from datetime import datetime, time, timedelta
from typing import List, Dict, Any
import pandas as pd
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dte_selector import DTESelector, DTEConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DTEBacktest:
    """Backtest DTE selection logic on historical signals"""
    
    def __init__(self, config: DTEConfig):
        self.dte_selector = DTESelector(config)
        self.results: List[Dict[str, Any]] = []
    
    def load_historical_signals(self, csv_path: str) -> pd.DataFrame:
        """
        Load historical signals from CSV
        Expected columns: timestamp, symbol, signal_type, entry_price
        """
        try:
            df = pd.read_csv(csv_path)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            logger.info(f"Loaded {len(df)} historical signals from {csv_path}")
            return df
        except Exception as e:
            logger.error(f"Error loading signals: {e}")
            return pd.DataFrame()
    
    def simulate_signal(self, signal_time: datetime, symbol: str) -> Dict[str, Any]:
        """
        Simulate DTE selection for a historical signal
        """
        # Temporarily override current time for simulation
        selected_dte = self.dte_selector.select_dte(signal_time)
        expiration = self.dte_selector.get_expiration_for_dte(selected_dte, signal_time)
        
        result = {
            'signal_time': signal_time,
            'symbol': symbol,
            'selected_dte': selected_dte,
            'expiration': expiration,
            'time_of_day': signal_time.strftime('%H:%M'),
            'day_of_week': signal_time.strftime('%A'),
            'is_wednesday': signal_time.weekday() == 2
        }
        
        # Analyze decision quality
        result['decision_quality'] = self._evaluate_dte_decision(signal_time, selected_dte)
        
        return result
    
    def _evaluate_dte_decision(self, signal_time: datetime, dte: int) -> str:
        """
        Evaluate if DTE selection was optimal based on time rules
        """
        signal_hour = signal_time.hour
        signal_minute = signal_time.minute
        is_wednesday = signal_time.weekday() == 2
        
        # Check if decision matches expected rules
        if signal_hour < 10:
            expected_dte = self.dte_selector.config.pre_1000_dte
            if dte == expected_dte:
                return "OPTIMAL - Pre-market 0DTE"
            else:
                return f"SUBOPTIMAL - Expected {expected_dte} DTE before 10:00 AM"
        
        elif signal_hour == 10 and signal_minute < 30:
            expected_dte = self.dte_selector.config.post_1000_dte
            if dte == expected_dte:
                return "OPTIMAL - Early session 1DTE"
            else:
                return f"SUBOPTIMAL - Expected {expected_dte} DTE 10:00-10:30 AM"
        
        elif is_wednesday and dte == 0 and self.dte_selector.config.avoid_wed_0dte:
            return "AVOIDED - Wednesday 0DTE correctly avoided"
        
        else:
            expected_dte = self.dte_selector.config.post_1030_dte
            if dte == expected_dte:
                return "OPTIMAL - Standard session DTE"
            else:
                return f"CHECK - Selected {dte} DTE at {signal_time.strftime('%H:%M')}"
    
    def run_backtest(self, signals_df: pd.DataFrame) -> pd.DataFrame:
        """
        Run backtest on all historical signals
        """
        logger.info(f"Starting backtest on {len(signals_df)} signals")
        
        for idx, row in signals_df.iterrows():
            result = self.simulate_signal(row['timestamp'], row['symbol'])
            self.results.append(result)
        
        results_df = pd.DataFrame(self.results)
        logger.info("Backtest complete")
        
        return results_df
    
    def analyze_results(self, results_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyze backtest results
        """
        total_signals = len(results_df)
        
        # Count DTE distribution
        dte_counts = results_df['selected_dte'].value_counts().to_dict()
        
        # Analyze by time of day
        results_df['hour'] = results_df['signal_time'].dt.hour
        by_hour = results_df.groupby('hour')['selected_dte'].value_counts().unstack(fill_value=0)
        
        # Quality analysis
        quality_counts = results_df['decision_quality'].value_counts().to_dict()
        optimal_pct = sum(v for k, v in quality_counts.items() if 'OPTIMAL' in k) / total_signals * 100
        
        return {
            'total_signals': total_signals,
            'dte_distribution': dte_counts,
            'by_hour': by_hour.to_dict(),
            'decision_quality': quality_counts,
            'optimal_percentage': optimal_pct,
            'wednesday_signals': len(results_df[results_df['is_wednesday'] == True]),
            'date_range': {
                'start': results_df['signal_time'].min(),
                'end': results_df['signal_time'].max()
            }
        }
    
    def print_summary(self, analysis: Dict[str, Any]) -> None:
        """
        Print backtest summary
        """
        print("\n" + "="*60)
        print("DTE BACKTEST SUMMARY")
        print("="*60)
        print(f"\nTotal Signals: {analysis['total_signals']}")
        print(f"Date Range: {analysis['date_range']['start']} to {analysis['date_range']['end']}")
        print(f"\nDTE Distribution:")
        for dte, count in sorted(analysis['dte_distribution'].items()):
            pct = count / analysis['total_signals'] * 100
            print(f"  {dte} DTE: {count} signals ({pct:.1f}%)")
        
        print(f"\nDecision Quality:")
        for quality, count in analysis['decision_quality'].items():
            pct = count / analysis['total_signals'] * 100
            print(f"  {quality}: {count} ({pct:.1f}%)")
        
        print(f"\nOptimal Decisions: {analysis['optimal_percentage']:.1f}%")
        print(f"Wednesday Signals: {analysis['wednesday_signals']}")
        print("\n" + "="*60 + "\n")

def main():
    """Run DTE backtest"""
    
    # Configure DTE selector (match your production config)
    config = DTEConfig(
        default_dte=0,
        pre_1000_dte=0,
        post_1000_dte=1,
        post_1030_dte=2,
        avoid_wed_0dte=True,
        min_time_value=0.05,
        enable_smart_routing=True
    )
    
    # Initialize backtest
    backtest = DTEBacktest(config)
    
    # Load historical signals (update path to your data)
    signals_df = backtest.load_historical_signals('backtests/historical_signals.csv')
    
    if signals_df.empty:
        logger.error("No signals loaded - check CSV path and format")
        return
    
    # Run backtest
    results_df = backtest.run_backtest(signals_df)
    
    # Save results
    output_path = 'backtests/dte_backtest_results.csv'
    results_df.to_csv(output_path, index=False)
    logger.info(f"Results saved to {output_path}")
    
    # Analyze and print summary
    analysis = backtest.analyze_results(results_df)
    backtest.print_summary(analysis)
    
    # Additional detailed analysis by hour
    print("\nDTE Selection by Hour:")
    print(results_df.groupby('hour')['selected_dte'].value_counts().unstack(fill_value=0))

if __name__ == '__main__':
    main()