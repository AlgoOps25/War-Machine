#!/usr/bin/env python3
"""
Extract Historical Signals from War Machine Logs
Parses Railway logs or local log files to create historical_signals.csv
"""

import re
import csv
from datetime import datetime
from pathlib import Path
import argparse

def parse_log_line(line: str) -> dict:
    """
    Parse a log line to extract signal information
    Expected format: YYYY-MM-DD HH:MM:SS.SSS inf SIGNAL {symbol} {type} @ ${price}
    """
    # Pattern for signal detection
    signal_pattern = r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2}).*?SIGNAL.*?([A-Z]{2,5}).*?([A-Z_]+).*?\$?(\d+\.\d+)'
    
    match = re.search(signal_pattern, line)
    if match:
        date_str = match.group(1)
        time_str = match.group(2)
        symbol = match.group(3)
        signal_type = match.group(4)
        price = match.group(5)
        
        timestamp = f"{date_str} {time_str}"
        
        return {
            'timestamp': timestamp,
            'symbol': symbol,
            'signal_type': signal_type,
            'entry_price': float(price)
        }
    
    return None

def extract_signals_from_file(log_file: str, output_csv: str):
    """
    Extract signals from log file and save to CSV
    """
    signals = []
    
    print(f"Reading log file: {log_file}")
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                signal = parse_log_line(line)
                if signal:
                    signals.append(signal)
        
        print(f"Found {len(signals)} signals")
        
        # Write to CSV
        if signals:
            with open(output_csv, 'w', newline='') as csvfile:
                fieldnames = ['timestamp', 'symbol', 'signal_type', 'entry_price']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(signals)
            
            print(f"Saved {len(signals)} signals to {output_csv}")
        else:
            print("No signals found in log file")
    
    except FileNotFoundError:
        print(f"Error: Log file not found: {log_file}")
    except Exception as e:
        print(f"Error processing log file: {e}")

def main():
    parser = argparse.ArgumentParser(description='Extract signals from War Machine logs')
    parser.add_argument('log_file', help='Path to log file')
    parser.add_argument('--output', default='backtests/historical_signals.csv',
                       help='Output CSV file (default: backtests/historical_signals.csv)')
    
    args = parser.parse_args()
    
    extract_signals_from_file(args.log_file, args.output)

if __name__ == '__main__':
    main()
