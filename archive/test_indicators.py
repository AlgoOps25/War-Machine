#!/usr/bin/env python3
"""
Technical Indicators Test Suite

Comprehensive testing for all indicator modules:
  1. technical_indicators.py - EODHD API integration
  2. vpvr_calculator.py - Volume Profile calculation
  3. signal_validator.py - Multi-indicator validation

Usage:
  python test_indicators.py [ticker]
  
Example:
  python test_indicators.py AAPL
"""
import sys
import time
from datetime import datetime
from typing import List

# Import all modules to test
import technical_indicators as ti
import vpvr_calculator as vpvr
from signal_validator import SignalValidator
import data_manager


# ANSI color codes for pretty output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str):
    """Print formatted section header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(80)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.END}\n")


def print_success(text: str):
    """Print success message."""
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")


def print_error(text: str):
    """Print error message."""
    print(f"{Colors.RED}❌ {text}{Colors.END}")


def print_warning(text: str):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")


def print_info(text: str):
    """Print info message."""
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.END}")


def test_technical_indicators(ticker: str):
    """Test technical_indicators.py module."""
    print_header("TEST 1: Technical Indicators (EODHD API)")
    
    start_time = time.time()
    results = {}
    
    # Test ADX (Trend Strength)
    print(f"{Colors.BOLD}Testing ADX (Trend Strength)...{Colors.END}")
    try:
        is_trending, adx_value = ti.check_trend_strength(ticker, min_adx=25.0)
        if adx_value:
            results['adx'] = {'value': adx_value, 'trending': is_trending}
            print_success(f"ADX: {adx_value:.1f} - {'Strong Trend' if is_trending else 'Weak Trend'}")
        else:
            print_error("ADX data not available")
    except Exception as e:
        print_error(f"ADX test failed: {e}")
    
    # Test Average Volume
    print(f"\n{Colors.BOLD}Testing Average Volume...{Colors.END}")
    try:
        avgvol_data = ti.fetch_avgvol(ticker)
        if avgvol_data:
            avg_volume = ti.get_latest_value(avgvol_data, 'avgvol')
            results['avgvol'] = {'value': avg_volume}
            print_success(f"Average Volume: {avg_volume:,.0f}")
        else:
            print_error("Average Volume data not available")
    except Exception as e:
        print_error(f"Average Volume test failed: {e}")
    
    # Test Bollinger Bands
    print(f"\n{Colors.BOLD}Testing Bollinger Bands...{Colors.END}")
    try:
        is_squeezed, band_width = ti.check_bollinger_squeeze(ticker, threshold=0.04)
        if band_width:
            results['bbands'] = {'width': band_width, 'squeezed': is_squeezed}
            status = "SQUEEZE" if is_squeezed else "NORMAL"
            print_success(f"Band Width: {band_width*100:.2f}% - {status}")
        else:
            print_error("Bollinger Bands data not available")
    except Exception as e:
        print_error(f"Bollinger Bands test failed: {e}")
    
    # Test DMI (Trend Direction)
    print(f"\n{Colors.BOLD}Testing DMI (Trend Direction)...{Colors.END}")
    try:
        direction = ti.get_trend_direction(ticker)
        if direction:
            results['dmi'] = {'direction': direction}
            emoji = "🟢" if direction == 'BULLISH' else "🔴"
            print_success(f"{emoji} Trend Direction: {direction}")
        else:
            print_error("DMI data not available")
    except Exception as e:
        print_error(f"DMI test failed: {e}")
    
    # Test CCI (Momentum)
    print(f"\n{Colors.BOLD}Testing CCI (Momentum)...{Colors.END}")
    try:
        cci_data = ti.fetch_cci(ticker)
        if cci_data:
            cci_value = ti.get_latest_value(cci_data, 'cci')
            results['cci'] = {'value': cci_value}
            
            if cci_value > 100:
                status = "OVERBOUGHT"
            elif cci_value < -100:
                status = "OVERSOLD"
            else:
                status = "NEUTRAL"
            
            print_success(f"CCI: {cci_value:.1f} - {status}")
        else:
            print_error("CCI data not available")
    except Exception as e:
        print_error(f"CCI test failed: {e}")
    
    elapsed_time = time.time() - start_time
    
    # Cache Statistics
    print(f"\n{Colors.BOLD}Cache Performance:{Colors.END}")
    cache_stats = ti.get_cache_stats()
    print_info(f"Total Entries: {cache_stats['total_entries']}")
    print_info(f"Valid Entries: {cache_stats['valid_entries']}")
    print_info(f"Current TTL: {cache_stats['current_ttl']}s")
    print_info(f"Elapsed Time: {elapsed_time:.2f}s")
    
    return results


def test_vpvr_calculator(ticker: str):
    """Test vpvr_calculator.py module."""
    print_header("TEST 2: VPVR Calculator (Volume Profile)")
    
    start_time = time.time()
    
    # Get today's bars
    print(f"{Colors.BOLD}Fetching bar data for {ticker}...{Colors.END}")
    bars = data_manager.data_manager.get_today_session_bars(ticker)
    
    if not bars:
        print_error(f"No bar data available for {ticker}")
        print_warning("VPVR requires intraday bar data. Make sure:")
        print("  1. WebSocket feed is connected")
        print("  2. Ticker is in today's watchlist")
        print("  3. Bars have been stored to database")
        return None
    
    print_success(f"Loaded {len(bars)} bars for today's session")
    
    # Calculate regular session profile
    print(f"\n{Colors.BOLD}Calculating Regular Session Profile (9:30-16:00)...{Colors.END}")
    calculator = vpvr.VPVRCalculator(price_buckets=50)
    profile = calculator.calculate_session_profile(ticker, session_type="regular")
    
    if not profile:
        print_error("Failed to calculate VPVR profile")
        return None
    
    # Display profile
    print_success("VPVR Profile calculated successfully\n")
    
    print(f"{Colors.BOLD}📊 Volume Profile Summary:{Colors.END}")
    print(f"  🎯 POC (Point of Control): ${profile['poc_price']:.2f}")
    print(f"     Volume at POC: {profile['poc_volume']:,}")
    print(f"\n  📈 Value Area (70% volume):")
    print(f"     High: ${profile['value_area_high']:.2f}")
    print(f"     Low:  ${profile['value_area_low']:.2f}")
    print(f"     Width: ${profile['value_area_high'] - profile['value_area_low']:.2f}")
    print(f"\n  🟢 High Volume Nodes (HVN): {len(profile['hvn_levels'])} levels")
    if profile['hvn_levels']:
        hvn_str = ', '.join(f"${p:.2f}" for p in profile['hvn_levels'][:5])
        print(f"     {hvn_str}")
    print(f"\n  🔴 Low Volume Nodes (LVN): {len(profile['lvn_levels'])} levels")
    if profile['lvn_levels']:
        lvn_str = ', '.join(f"${p:.2f}" for p in profile['lvn_levels'][:5])
        print(f"     {lvn_str}")
    print(f"\n  📊 Total Volume: {profile['total_volume']:,}")
    
    # Test signal context
    print(f"\n{Colors.BOLD}Testing Signal Context...{Colors.END}")
    current_price = profile['poc_price'] * 1.01  # 1% above POC
    
    context = vpvr.get_vpvr_signal_context(ticker, current_price, direction="BUY")
    
    if context:
        print_success("Signal context generated\n")
        print(f"  Current Price: ${current_price:.2f}")
        print(f"  Near POC: {'✅' if context['near_poc'] else '❌'}")
        print(f"  In Value Area: {'✅' if context['in_value_area'] else '❌'}")
        print(f"  Distance to POC: {context['distance_to_poc_pct']:.2f}%")
        print(f"  Recommendation: {context['recommendation']}")
    
    elapsed_time = time.time() - start_time
    print_info(f"\nElapsed Time: {elapsed_time:.2f}s (zero API calls)")
    
    return profile


def test_signal_validator(ticker: str, results: dict, profile: dict):
    """Test signal_validator.py module."""
    print_header("TEST 3: Signal Validator (Multi-Indicator Confirmation)")
    
    start_time = time.time()
    
    # Create validator
    validator = SignalValidator(
        min_adx=20.0,
        min_volume_ratio=1.3,
        enable_vpvr=True,
        strict_mode=False
    )
    
    # Simulate a CFW6 signal
    print(f"{Colors.BOLD}Simulating BUY signal for {ticker}...{Colors.END}\n")
    
    # Get current price from profile or use mock
    if profile:
        test_price = profile['poc_price'] * 1.005  # Just above POC
    else:
        test_price = 175.50  # Mock price
    
    # Get volume from results or use mock
    if 'avgvol' in results:
        test_volume = int(results['avgvol']['value'] * 1.8)  # 1.8x average
    else:
        test_volume = 5_000_000  # Mock volume
    
    test_confidence = 0.75  # CFW6 base confidence
    test_direction = "BUY"
    
    print(f"  Ticker: {ticker}")
    print(f"  Direction: {test_direction}")
    print(f"  Price: ${test_price:.2f}")
    print(f"  Volume: {test_volume:,}")
    print(f"  Base Confidence: {test_confidence*100:.1f}%")
    
    # Run validation
    print(f"\n{Colors.BOLD}Running Multi-Indicator Validation...{Colors.END}\n")
    
    should_pass, adjusted_conf, metadata = validator.validate_signal(
        ticker=ticker,
        signal_direction=test_direction,
        current_price=test_price,
        current_volume=test_volume,
        base_confidence=test_confidence
    )
    
    # Display results
    summary = metadata['summary']
    
    if should_pass:
        print_success(f"SIGNAL PASSED VALIDATION")
    else:
        print_error(f"SIGNAL FILTERED")
    
    print(f"\n{Colors.BOLD}Validation Summary:{Colors.END}")
    print(f"  Adjusted Confidence: {adjusted_conf*100:.1f}% ({summary['confidence_adjustment']:+.1%})")
    print(f"  Check Score: {summary['check_score']}")
    
    if summary['passed_checks']:
        print(f"\n  {Colors.GREEN}✓ Passed Checks:{Colors.END}")
        for check in summary['passed_checks']:
            print(f"    • {check}")
    
    if summary['failed_checks']:
        print(f"\n  {Colors.RED}✗ Failed Checks:{Colors.END}")
        for check in summary['failed_checks']:
            print(f"    • {check}")
    
    # Detailed check results
    print(f"\n{Colors.BOLD}Detailed Check Results:{Colors.END}")
    
    for check_name, check_data in metadata['checks'].items():
        print(f"\n  {check_name.upper()}:")
        
        if 'error' in check_data:
            print_error(f"    Error: {check_data['error']}")
        else:
            for key, value in check_data.items():
                if isinstance(value, dict):
                    print(f"    {key}: {{...}}")
                elif isinstance(value, bool):
                    print(f"    {key}: {'✅' if value else '❌'}")
                else:
                    print(f"    {key}: {value}")
    
    # Validator statistics
    print(f"\n{Colors.BOLD}Validator Statistics:{Colors.END}")
    stats = validator.get_validation_stats()
    print(f"  Total Validated: {stats['total_validated']}")
    print(f"  Pass Rate: {stats.get('pass_rate', 0)*100:.1f}%")
    print(f"  Filter Rate: {stats.get('filter_rate', 0)*100:.1f}%")
    print(f"  Boost Rate: {stats.get('boost_rate', 0)*100:.1f}%")
    
    elapsed_time = time.time() - start_time
    print_info(f"\nElapsed Time: {elapsed_time:.2f}s")
    
    return should_pass, adjusted_conf, metadata


def main():
    """Main test execution."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}WAR MACHINE - TECHNICAL INDICATORS TEST SUITE{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}{Colors.END}")
    
    # Get ticker from command line or use default
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
    else:
        ticker = "AAPL"  # Default test ticker
        print_warning(f"No ticker specified, using default: {ticker}")
        print(f"Usage: python test_indicators.py [TICKER]\n")
    
    print(f"{Colors.BOLD}Testing ticker: {ticker}{Colors.END}")
    
    overall_start = time.time()
    
    # Test 1: Technical Indicators
    try:
        results = test_technical_indicators(ticker)
    except Exception as e:
        print_error(f"Technical Indicators test crashed: {e}")
        results = {}
    
    # Test 2: VPVR Calculator
    try:
        profile = test_vpvr_calculator(ticker)
    except Exception as e:
        print_error(f"VPVR Calculator test crashed: {e}")
        profile = None
    
    # Test 3: Signal Validator (integrates both)
    try:
        should_pass, adjusted_conf, metadata = test_signal_validator(ticker, results, profile)
    except Exception as e:
        print_error(f"Signal Validator test crashed: {e}")
    
    # Final Summary
    overall_time = time.time() - overall_start
    
    print_header("TEST SUITE COMPLETE")
    
    print(f"{Colors.BOLD}Summary:{Colors.END}")
    print(f"  Ticker: {ticker}")
    print(f"  Total Time: {overall_time:.2f}s")
    print(f"  Modules Tested: 3/3")
    
    # Check if all tests passed
    all_passed = bool(results) and bool(profile) and 'should_pass' in locals()
    
    if all_passed:
        print_success("\nAll modules operational! ✨")
        print_info("Ready to integrate into signal_generator.py")
    else:
        print_warning("\nSome tests failed or returned no data")
        print_info("Check error messages above for details")
    
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.END}\n")


if __name__ == "__main__":
    main()
