#!/usr/bin/env python3
"""
Test Script - Breakout Signal Generator

Tests the breakout detector with live data from your database.
Run this to verify signals before integrating into scanner.py

Usage:
    python test_signals.py
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from signal_generator import signal_generator, format_signal_message
from data_manager import data_manager

ET = ZoneInfo("America/New_York")


def test_with_live_data(tickers: list, use_5m: bool = True):
    """
    Test signal generator with live data from database.
    
    Args:
        tickers: List of tickers to test
        use_5m: Use 5-minute bars (True) or 1-minute bars (False)
    """
    print("\n" + "="*70)
    print("BREAKOUT SIGNAL GENERATOR - TEST MODE")
    print("="*70)
    print(f"Time: {datetime.now(ET).strftime('%Y-%m-%d %I:%M:%S %p ET')}")
    print(f"Timeframe: {'5-minute' if use_5m else '1-minute'} bars")
    print(f"Testing {len(tickers)} tickers")
    print("="*70 + "\n")
    
    signals_found = 0
    tickers_with_data = 0
    
    for ticker in tickers:
        try:
            # Get bars from database
            if use_5m:
                bars = data_manager.get_today_5m_bars(ticker)
                timeframe = "5m"
            else:
                bars = data_manager.get_today_session_bars(ticker)
                timeframe = "1m"
            
            if not bars:
                print(f"[{ticker}] No {timeframe} bars in database")
                continue
            
            tickers_with_data += 1
            bar_count = len(bars)
            latest_bar = bars[-1]
            latest_time = latest_bar['datetime'].strftime('%H:%M ET')
            
            print(f"[{ticker}] {bar_count} bars | Latest: {latest_time} | "
                  f"Price: ${latest_bar['close']:.2f} | Volume: {latest_bar['volume']:,}")
            
            # Check for breakout signal
            signal = signal_generator.check_ticker(ticker, use_5m=use_5m)
            
            if signal:
                signals_found += 1
                print("\n" + "="*70)
                print(f"🚨 SIGNAL DETECTED: {ticker}")
                print("="*70)
                print(format_signal_message(ticker, signal))
                print("="*70 + "\n")
                
                # Calculate position size for different account sizes
                print("\nPosition Sizing Examples:")
                print("-" * 70)
                
                for account_balance in [5000, 10000, 25000, 50000]:
                    shares = signal_generator.detector.calculate_position_size(
                        account_balance=account_balance,
                        risk_percent=1.0,  # Risk 1%
                        entry=signal['entry'],
                        stop=signal['stop']
                    )
                    
                    total_cost = shares * signal['entry']
                    total_risk = shares * signal['risk']
                    total_reward = shares * signal['reward']
                    
                    print(f"${account_balance:,} account (1% risk):")
                    print(f"  - Buy {shares} shares @ ${signal['entry']:.2f} = ${total_cost:,.0f}")
                    print(f"  - Max risk: ${total_risk:.0f} | Potential profit: ${total_reward:.0f}")
                    print()
            
        except Exception as e:
            print(f"[{ticker}] Error: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tickers scanned: {len(tickers)}")
    print(f"Tickers with data: {tickers_with_data}")
    print(f"Signals detected: {signals_found}")
    
    if signals_found == 0:
        print("\n👀 No signals found. This is normal if:")
        print("   1. Market hasn't had strong breakouts yet today")
        print("   2. Volume hasn't spiked 2x average")
        print("   3. You're testing during low-volatility periods")
        print("\n💡 Try:")
        print("   - Testing during market hours (9:30-16:00 ET)")
        print("   - Testing on high-volume tickers (SPY, QQQ, TSLA, NVDA)")
        print("   - Lowering volume_multiplier in signal_generator.py")
    
    print("="*70 + "\n")


def check_database_status():
    """Check if database has today's bars."""
    print("\n" + "="*70)
    print("DATABASE STATUS CHECK")
    print("="*70)
    
    test_tickers = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]
    
    for ticker in test_tickers:
        try:
            bars_1m = data_manager.get_today_session_bars(ticker)
            bars_5m = data_manager.get_today_5m_bars(ticker)
            
            if bars_1m:
                latest_1m = bars_1m[-1]['datetime'].strftime('%H:%M ET')
                print(f"[{ticker}] 1m bars: {len(bars_1m)} | Latest: {latest_1m}")
            else:
                print(f"[{ticker}] 1m bars: 0 | No data")
            
            if bars_5m:
                latest_5m = bars_5m[-1]['datetime'].strftime('%H:%M ET')
                print(f"[{ticker}] 5m bars: {len(bars_5m)} | Latest: {latest_5m}")
            else:
                print(f"[{ticker}] 5m bars: 0 | No data")
            
            print()
        except Exception as e:
            print(f"[{ticker}] Error: {e}\n")
    
    print("="*70 + "\n")


if __name__ == "__main__":
    # Check database first
    check_database_status()
    
    # Test with current watchlist (or fallback tickers)
    test_tickers = [
        "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD",
        "GOOGL", "AMZN", "NFLX", "PLTR", "SOFI", "INTC", "ORCL"
    ]
    
    print("\nSelect test mode:")
    print("1. Test with 5-minute bars (recommended)")
    print("2. Test with 1-minute bars (more sensitive)")
    print("3. Test both timeframes")
    print("4. Exit")
    
    try:
        choice = input("\nEnter choice (1-4): ").strip()
        
        if choice == "1":
            test_with_live_data(test_tickers, use_5m=True)
        elif choice == "2":
            test_with_live_data(test_tickers, use_5m=False)
        elif choice == "3":
            print("\n" + "#"*70)
            print("# TESTING WITH 5-MINUTE BARS")
            print("#"*70)
            test_with_live_data(test_tickers, use_5m=True)
            
            print("\n" + "#"*70)
            print("# TESTING WITH 1-MINUTE BARS")
            print("#"*70)
            test_with_live_data(test_tickers, use_5m=False)
        elif choice == "4":
            print("Exiting...")
            sys.exit(0)
        else:
            print("Invalid choice. Exiting...")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n\nTest interrupted. Exiting...")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
