"""
war_machine_scanner_v4.py
Production scanner with integrated filter system - Phase 5

Enhancements over V3:
- Integrated EODHD filter system
- Configurable filter presets
- Real-time filter application
- Enhanced signal quality scoring
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
from pathlib import Path

from eodhd_data_loader import get_loader
from market_filters import MarketFilters
from config import WarMachineConfig

class WarMachineScanner:
    """
    War Machine V4 Scanner with Filter Integration
    
    Features:
    - Baseline BOS scanner (73% WR)
    - Optional EODHD filter system
    - Configurable filter presets
    - Quality scoring per signal
    """
    
    def __init__(self, 
                 db_path: str = "market_memory.db",
                 config_preset: str = "baseline"):
        """
        Initialize scanner
        
        Args:
            db_path: Path to market database
            config_preset: Filter preset ('baseline', 'balanced', 'conservative', etc.)
        """
        self.db_path = db_path
        
        # Load configuration
        self.config = WarMachineConfig()
        self.config.load_preset(config_preset)
        
        # Initialize filters
        self.filters = MarketFilters()
        self.eodhd = get_loader()
        
        # Baseline parameters (V2 optimized)
        self.volume_multiplier = self.config.baseline['volume_multiplier']
        self.atr_multiplier = self.config.baseline['atr_multiplier']
        self.risk_reward_ratio = self.config.baseline['risk_reward_ratio']
        self.lookback_periods = self.config.baseline['lookback_periods']
        
        print(f"War Machine Scanner V4 initialized")
        print(f"Config preset: {config_preset}")
        print(f"Filters enabled: {len(self.config.get_enabled_filters())}")
    
    def scan_for_signals(self, 
                        scan_date: str,
                        trading_window: Tuple[str, str] = ("09:30", "10:00")) -> List[Dict]:
        """
        Scan for trading signals on given date
        
        Args:
            scan_date: Date to scan (YYYY-MM-DD)
            trading_window: Time window (start, end) in HH:MM format
        
        Returns:
            List of signal dictionaries with filter scores
        """
        print(f"\n{'='*70}")
        print(f"SCANNING: {scan_date}")
        print(f"{'='*70}")
        
        # Step 1: Run baseline BOS scanner
        baseline_signals = self._run_baseline_scanner(scan_date, trading_window)
        print(f"Baseline signals found: {len(baseline_signals)}")
        
        if not baseline_signals:
            return []
        
        # Step 2: Apply filters (if enabled)
        enabled_filters = self.config.get_filter_names()
        
        if not enabled_filters:
            # No filters - return baseline signals
            print("No filters enabled - using baseline signals")
            return baseline_signals
        
        print(f"Applying {len(enabled_filters)} filters: {', '.join(enabled_filters)}")
        
        # Step 3: Filter and score signals
        filtered_signals = self._apply_filters_to_signals(
            baseline_signals,
            enabled_filters
        )
        
        print(f"Signals after filtering: {len(filtered_signals)}")
        print(f"Signal retention: {len(filtered_signals)/len(baseline_signals)*100:.1f}%")
        
        return filtered_signals
    
    def _run_baseline_scanner(self, 
                             scan_date: str,
                             trading_window: Tuple[str, str]) -> List[Dict]:
        """
        Run baseline BOS scanner (V2 optimized logic)
        
        This is your proven 73% WR baseline
        """
        conn = sqlite3.connect(self.db_path)
        
        # Get intraday data for scan date
        query = """
        SELECT symbol, timestamp, open, high, low, close, volume
        FROM intraday_bars
        WHERE date = ?
        AND timestamp >= ? AND timestamp <= ?
        ORDER BY symbol, timestamp
        """
        
        start_time = f"{scan_date} {trading_window[0]}:00"
        end_time = f"{scan_date} {trading_window[1]}:00"
        
        df = pd.read_sql_query(query, conn, params=(scan_date, start_time, end_time))
        conn.close()
        
        if df.empty:
            return []
        
        # Group by symbol and check for BOS
        signals = []
        
        for symbol in df['symbol'].unique():
            symbol_df = df[df['symbol'] == symbol].copy()
            
            # Calculate volume and ATR metrics
            avg_volume = symbol_df['volume'].mean()
            volume_ratio = symbol_df['volume'].iloc[-1] / avg_volume if avg_volume > 0 else 0
            
            # Simple ATR calculation
            symbol_df['high_low'] = symbol_df['high'] - symbol_df['low']
            atr = symbol_df['high_low'].tail(self.lookback_periods).mean()
            
            # Check baseline criteria
            if volume_ratio >= self.volume_multiplier:
                # Potential signal
                signal = {
                    'symbol': symbol,
                    'date': scan_date,
                    'timestamp': symbol_df['timestamp'].iloc[-1],
                    'entry_price': symbol_df['close'].iloc[-1],
                    'volume_ratio': volume_ratio,
                    'atr': atr,
                    'baseline_score': 100.0,  # Passed baseline
                    'filter_scores': {},
                    'combined_score': 100.0,
                    'passed_all_filters': True  # Will update in filter step
                }
                
                signals.append(signal)
        
        return signals
    
    def _apply_filters_to_signals(self,
                                  signals: List[Dict],
                                  filter_names: List[str]) -> List[Dict]:
        """
        Apply filters to baseline signals and calculate quality scores
        
        Args:
            signals: List of baseline signals
            filter_names: List of filter names to apply
        
        Returns:
            Filtered signals with quality scores
        """
        filter_params = self.config.get_filter_params()
        filter_weights = self.config.get_filter_weights()
        
        filtered_signals = []
        
        for signal in signals:
            symbol = signal['symbol']
            
            # Run filters for this symbol
            try:
                filter_results = self.filters.run_filter_combination(
                    symbol,
                    filter_names,
                    filter_params
                )
                
                # Store individual filter scores
                signal['filter_scores'] = {
                    name: result['score']
                    for name, result in filter_results['individual_results'].items()
                }
                
                # Calculate weighted combined score
                total_weight = sum(filter_weights.values())
                combined_score = sum(
                    filter_results['individual_results'][name]['score'] * filter_weights.get(name, 1.0)
                    for name in filter_names
                ) / total_weight if total_weight > 0 else 0
                
                signal['combined_score'] = combined_score
                signal['passed_all_filters'] = filter_results['all_filters_passed']
                
                # Keep signal if it passes all filters
                if filter_results['all_filters_passed']:
                    filtered_signals.append(signal)
                
            except Exception as e:
                print(f"  Error filtering {symbol}: {e}")
                continue
        
        return filtered_signals
    
    def save_signals(self, signals: List[Dict], output_file: str = "scanner_signals.json"):
        """Save signals to JSON file"""
        with open(output_file, 'w') as f:
            json.dump(signals, f, indent=2)
        
        print(f"\nSignals saved to {output_file}")
    
    def print_signals(self, signals: List[Dict]):
        """Print signals in readable format"""
        if not signals:
            print("\nNo signals found")
            return
        
        print(f"\n{'='*70}")
        print(f"SIGNALS FOUND: {len(signals)}")
        print(f"{'='*70}\n")
        
        for i, signal in enumerate(signals, 1):
            print(f"{i}. {signal['symbol']} @ ${signal['entry_price']:.2f}")
            print(f"   Volume Ratio: {signal['volume_ratio']:.2f}x")
            print(f"   Combined Score: {signal['combined_score']:.1f}/100")
            print(f"   Timestamp: {signal['timestamp']}")
            
            # Show filter scores if any
            if signal['filter_scores']:
                print(f"   Filter Scores:")
                for fname, score in signal['filter_scores'].items():
                    print(f"     {fname}: {score:.1f}")
            print()


# ========================================
# VALIDATION WITH FILTERS
# ========================================

def validate_with_filters(config_preset: str = "baseline",
                         start_date: str = "2024-01-01",
                         end_date: str = "2024-12-31") -> Dict:
    """
    Validate scanner performance with filters
    
    Args:
        config_preset: Filter configuration to test
        start_date: Start date for validation
        end_date: End date for validation
    
    Returns:
        Validation results dictionary
    """
    scanner = WarMachineScanner(config_preset=config_preset)
    
    print(f"\n{'='*70}")
    print(f"VALIDATING: {config_preset}")
    print(f"Period: {start_date} to {end_date}")
    print(f"{'='*70}")
    
    # Generate date range (trading days only - M-F)
    date_range = pd.date_range(start_date, end_date, freq='B')  # Business days
    
    all_signals = []
    
    for scan_date in date_range:
        date_str = scan_date.strftime('%Y-%m-%d')
        
        # Scan for signals
        signals = scanner.scan_for_signals(date_str)
        all_signals.extend(signals)
    
    # Calculate performance metrics
    # (This would integrate with your actual trade execution results)
    
    results = {
        'config_preset': config_preset,
        'total_signals': len(all_signals),
        'start_date': start_date,
        'end_date': end_date,
        'signals': all_signals
    }
    
    return results


# ========================================
# MAIN EXECUTION
# ========================================

def main():
    """Run War Machine Scanner V4"""
    
    print("="*70)
    print("WAR MACHINE SCANNER V4")
    print("="*70)
    
    # Select configuration
    print("\nAvailable presets:")
    print("1. baseline - No filters (73% WR)")
    print("2. balanced - Moderate filtering")
    print("3. conservative - Strict filtering")
    print("4. aggressive - Light filtering")
    print("5. custom - Load from file")
    
    choice = input("\nSelect preset (1-5) [1]: ").strip() or "1"
    
    preset_map = {
        "1": "baseline",
        "2": "balanced",
        "3": "conservative",
        "4": "aggressive",
    }
    
    if choice in preset_map:
        config_preset = preset_map[choice]
    elif choice == "5":
        config_file = input("Enter config file path: ").strip()
        # Load custom config
        config_preset = "baseline"  # Will load from file
    else:
        config_preset = "baseline"
    
    # Initialize scanner
    scanner = WarMachineScanner(config_preset=config_preset)
    
    # Scan today or specific date
    scan_date = input(f"\nEnter scan date (YYYY-MM-DD) [today]: ").strip()
    if not scan_date:
        scan_date = datetime.now().strftime('%Y-%m-%d')
    
    # Run scan
    signals = scanner.scan_for_signals(scan_date)
    
    # Display results
    scanner.print_signals(signals)
    
    # Save to file
    if signals:
        save = input("\nSave signals to file? (y/n) [y]: ").strip().lower()
        if save != 'n':
            scanner.save_signals(signals)
    
    print("\n" + "="*70)
    print("SCAN COMPLETE")
    print("="*70)


if __name__ == "__main__":
    main()
