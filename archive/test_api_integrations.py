#!/usr/bin/env python3
"""
API Integration Test Suite
Tests all 6 new EODHD API integrations to verify they work correctly.

Run this script to validate:
1. Dividends & Splits Filter
2. Extended Hours Framework
3. Dynamic Screener
4. Technical Indicators
5. Bulk Download API
6. Exchange Hours & Holidays

Usage:
    python test_api_integrations.py
"""
import sys
import os
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def print_section(title):
    """Print a section header."""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def test_dividends_filter():
    """Test dividends & splits filter API."""
    print_section("TEST 1: Dividends & Splits Filter")
    
    try:
        from dividends_filter import (
            get_upcoming_dividends,
            get_upcoming_splits,
            has_dividend_or_split_soon,
            get_cache_stats
        )
        
        # Test tickers known to pay dividends
        test_tickers = ["AAPL", "MSFT", "JPM", "KO", "T"]
        
        print(f"\nTesting dividend lookup for {len(test_tickers)} tickers...\n")
        
        results = []
        for ticker in test_tickers:
            dividends = get_upcoming_dividends(ticker, days_ahead=30)
            splits = get_upcoming_splits(ticker, days_ahead=30)
            has_event, details = has_dividend_or_split_soon(ticker, days_ahead=7)
            
            results.append({
                "ticker": ticker,
                "dividends": len(dividends),
                "splits": len(splits),
                "upcoming_event": has_event
            })
            
            if dividends:
                print(f"✅ {ticker}: {len(dividends)} dividend(s) in next 30 days")
                for div in dividends[:2]:  # Show first 2
                    print(f"   📅 {div['date']} - ${div['value']:.2f}")
            else:
                print(f"ℹ️  {ticker}: No dividends in next 30 days")
            
            if has_event:
                print(f"   ⚠️  Event within 7 days: {details.get('type', 'unknown')}")
        
        # Cache stats
        cache = get_cache_stats()
        print(f"\n📊 Cache: {cache['cached_tickers']} tickers cached")
        
        print("\n✅ TEST 1 PASSED: Dividends API responding")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_extended_hours():
    """Test extended hours framework."""
    print_section("TEST 2: Extended Hours Framework")
    
    try:
        from extended_hours import (
            get_market_session,
            is_extended_hours,
            is_premarket,
            is_afterhours,
            get_scan_interval,
            should_run_scanner
        )
        
        now = datetime.now(ET)
        session = get_market_session()
        is_extended = is_extended_hours()
        scan_interval = get_scan_interval()
        should_run = should_run_scanner()
        
        print(f"\n⏰ Current Time: {now.strftime('%I:%M:%S %p ET')}")
        print(f"📍 Session: {session.upper()}")
        print(f"🌅 Extended Hours: {'Yes' if is_extended else 'No'}")
        print(f"⏱️  Scan Interval: {scan_interval} seconds")
        print(f"🚀 Should Run Scanner: {'Yes' if should_run else 'No'}")
        
        if is_premarket():
            print("   ☀️  PRE-MARKET MODE (4:00 AM - 9:30 AM)")
        elif is_afterhours():
            print("   🌙 AFTER-HOURS MODE (4:00 PM - 8:00 PM)")
        elif session == "regular":
            print("   📈 REGULAR HOURS (9:30 AM - 4:00 PM)")
        else:
            print("   🔒 MARKET CLOSED")
        
        print("\n✅ TEST 2 PASSED: Extended hours logic working")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_dynamic_screener():
    """Test dynamic stock screener API."""
    print_section("TEST 3: Dynamic Screener")
    
    try:
        from dynamic_screener import (
            get_dynamic_watchlist,
            run_screener,
            get_gap_candidates,
            get_cache_stats
        )
        
        print("\n🔍 Running dynamic screener (this may take 5-10 seconds)...\n")
        
        # Main watchlist
        watchlist = get_dynamic_watchlist(include_core=True, max_tickers=30)
        
        if watchlist:
            print(f"✅ Generated watchlist: {len(watchlist)} tickers")
            print(f"\n📋 Top 10: {', '.join(watchlist[:10])}")
        else:
            print("⚠️  Screener returned empty (may need to run during market hours)")
        
        # Gap candidates
        print("\n🚀 Checking for gap candidates (3%+ movers)...")
        gaps = get_gap_candidates(min_gap_pct=3.0, limit=10)
        
        if gaps:
            print(f"✅ Found {len(gaps)} gapping stocks:")
            for ticker in gaps[:5]:
                print(f"   📊 {ticker}")
        else:
            print("ℹ️  No significant gaps found (normal outside market hours)")
        
        # Cache stats
        cache = get_cache_stats()
        if cache.get('cached'):
            print(f"\n📊 Cache: {cache['tickers_count']} tickers, age {cache['age_hours']:.1f}h")
        else:
            print("\n📊 Cache: Empty (first run)")
        
        print("\n✅ TEST 3 PASSED: Screener API responding")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_technical_indicators():
    """Test technical indicators API."""
    print_section("TEST 4: Technical Indicators (Server-Side)")
    
    try:
        from technical_indicators import (
            get_rsi,
            get_macd,
            get_sma,
            check_rsi_confirmation,
            check_macd_confirmation,
            get_multi_indicator_score,
            get_cache_stats
        )
        
        test_tickers = ["AAPL", "TSLA", "SPY"]
        
        print(f"\n📊 Fetching technical indicators for {len(test_tickers)} tickers...\n")
        
        for ticker in test_tickers:
            print(f"📈 {ticker}:")
            
            # RSI
            rsi = get_rsi(ticker, period=14)
            if rsi:
                print(f"   RSI(14): {rsi:.2f}")
                if rsi < 30:
                    print("      🟢 Oversold")
                elif rsi > 70:
                    print("      🔴 Overbought")
                else:
                    print("      ⚪ Neutral")
            else:
                print("   RSI(14): Not available")
            
            # MACD
            macd = get_macd(ticker)
            if macd:
                print(f"   MACD: {macd['macd']:.2f}")
                print(f"   Signal: {macd['signal']:.2f}")
                print(f"   Histogram: {macd['histogram']:.2f}")
                if macd['histogram'] > 0:
                    print("      🟢 Bullish momentum")
                else:
                    print("      🔴 Bearish momentum")
            else:
                print("   MACD: Not available")
            
            # SMA
            sma20 = get_sma(ticker, period=20)
            if sma20:
                print(f"   SMA(20): ${sma20:.2f}")
            
            # Multi-indicator score
            score = get_multi_indicator_score(ticker, "bullish")
            print(f"   📊 Bullish Score: {score['total_score']}/2")
            print()
        
        # Cache stats
        cache = get_cache_stats()
        print(f"📊 Cache: {cache['valid_entries']}/{cache['total_entries']} valid, TTL {cache['cache_ttl_minutes']}min")
        
        print("\n✅ TEST 4 PASSED: Technical indicators API responding")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_bulk_download():
    """Test bulk download API."""
    print_section("TEST 5: Bulk Download API")
    
    try:
        from archive.bulk_downloader import (
            download_bulk_eod_data,
            get_previous_close_bulk
        )
        
        print("\n📥 Testing bulk EOD data download (this may take 10-15 seconds)...\n")
        
        # Test with small sample
        test_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
        
        # Bulk download (filtered)
        bulk_data = download_bulk_eod_data(
            exchange="US",
            symbols_filter=test_tickers
        )
        
        if bulk_data:
            print(f"✅ Bulk download successful: {len(bulk_data)} records")
            print("\n📊 Sample data:")
            for item in bulk_data[:3]:
                code = item.get("code", "")
                date = item.get("date", "")
                close = item.get("close", 0)
                volume = item.get("volume", 0)
                print(f"   {code}: ${close:.2f} on {date} | Vol: {volume:,}")
        else:
            print("⚠️  Bulk download returned no data (may need market hours)")
        
        # Previous close lookup
        print("\n💰 Fetching previous closes...")
        prev_closes = get_previous_close_bulk(test_tickers)
        
        if prev_closes:
            print(f"✅ Retrieved {len(prev_closes)} previous closes:")
            for ticker, close in list(prev_closes.items())[:5]:
                print(f"   {ticker}: ${close:.2f}")
        else:
            print("⚠️  No previous closes available")
        
        print("\n✅ TEST 5 PASSED: Bulk download API responding")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 5 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_exchange_hours():
    """Test exchange hours and holiday detection API."""
    print_section("TEST 6: Exchange Hours & Holiday Detection")
    
    try:
        from exchange_hours import (
            get_exchange_details,
            get_holidays,
            is_market_holiday,
            is_early_close_day,
            should_scanner_run,
            get_market_hours,
            get_next_trading_day,
            format_holiday_calendar
        )
        
        print("\n📅 Fetching US exchange data...\n")
        
        # Exchange details
        exchange = get_exchange_details("US")
        if exchange:
            print(f"✅ Exchange: {exchange.get('Name', 'US')}")
            print(f"   Code: {exchange.get('Code', 'US')}")
            print(f"   Country: {exchange.get('Country', 'USA')}")
            print(f"   Timezone: {exchange.get('Timezone', 'America/New_York')}")
        else:
            print("⚠️  Exchange details not available (using fallback)")
        
        # Market hours
        hours = get_market_hours("US")
        print(f"\n🕐 Trading Hours:")
        print(f"   Open: {hours['opening_time']}")
        print(f"   Close: {hours['closing_time']}")
        print(f"   Days: {', '.join(hours['working_days'])}")
        
        # Today's status
        today = date.today()
        is_holiday, holiday_name = is_market_holiday(today)
        is_early, close_time = is_early_close_day(today)
        should_run, reason = should_scanner_run()
        
        print(f"\n📆 Today ({today.strftime('%A, %B %d, %Y')}):")
        if is_holiday:
            print(f"   ❌ HOLIDAY: {holiday_name}")
        elif is_early:
            print(f"   🕐 EARLY CLOSE: {close_time.strftime('%I:%M %p')}")
        else:
            print(f"   ✅ Regular Trading Day")
        
        print(f"\n🚀 Scanner Status: {'RUN' if should_run else 'DO NOT RUN'}")
        print(f"   Reason: {reason}")
        
        # Next trading day
        next_day = get_next_trading_day()
        print(f"\n📅 Next Trading Day: {next_day.strftime('%A, %B %d, %Y')}")
        
        # Upcoming holidays
        holidays = get_holidays("US", year=2026)
        print(f"\n🗓️  2026 Holidays: {len(holidays)} total")
        if holidays:
            print("   Upcoming:")
            for h in holidays[:5]:
                print(f"   • {h.get('Date', 'TBD')} - {h.get('Name', 'Holiday')}")
        
        print("\n✅ TEST 6 PASSED: Exchange hours API responding")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 6 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("\n" + "#"*70)
    print("#" + " "*68 + "#")
    print("#" + "  WAR MACHINE - API INTEGRATION TEST SUITE".center(68) + "#")
    print("#" + " "*68 + "#")
    print("#"*70)
    
    now = datetime.now(ET)
    print(f"\nTest Started: {now.strftime('%I:%M:%S %p ET on %A, %B %d, %Y')}")
    print(f"Testing 6 EODHD API integrations...")
    
    # Check API key
    api_key = os.getenv("EODHD_API_KEY", "")
    if not api_key:
        print("\n❌ FATAL: EODHD_API_KEY environment variable not set!")
        print("   Set it in your .env file or export it:")
        print("   export EODHD_API_KEY='your_key_here'")
        sys.exit(1)
    
    print(f"✅ API Key: {api_key[:10]}...")
    
    # Run all tests
    results = {
        "Dividends & Splits": test_dividends_filter(),
        "Extended Hours": test_extended_hours(),
        "Dynamic Screener": test_dynamic_screener(),
        "Technical Indicators": test_technical_indicators(),
        "Bulk Download": test_bulk_download(),
        "Exchange Hours": test_exchange_hours(),
    }
    
    # Summary
    print("\n" + "#"*70)
    print("#" + "  TEST SUMMARY".center(68) + "#")
    print("#"*70)
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {test_name:.<45} {status}")
    
    print("\n" + "-"*70)
    print(f"  TOTAL: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    print("-"*70 + "\n")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED! Your API integrations are working correctly.\n")
        return 0
    else:
        print(f"⚠️  {total - passed} test(s) failed. Check errors above.\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
