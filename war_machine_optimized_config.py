"""
War Machine - Optimized Filter Configuration
Based on 2-phase parameter optimization results

Performance (Validation Set):
- Win Rate: 90.9% (20W / 2L)
- Profit Factor: 3.23
- Improvement: +17.9% vs baseline (73.0%)
- Signals Retained: 34.9%

Optimization Date: 2026-02-27
"""

OPTIMIZED_FILTERS = {
    'price_range': {
        'enabled': True,
        'min_price': 1,
        'max_price': 200,
        'description': 'Filter stocks between $1-$200 (eliminates expensive mega-caps)'
    },
    'bollinger_position': {
        'enabled': True,
        'period': 10,
        'std_dev': 1.5,
        'min_position': 0.2,
        'max_position': 1.0,
        'description': 'Catch stocks in lower 20%-100% of Bollinger Bands (mean reversion setup)'
    }
}

# Alternative configurations if you want more signals

ALTERNATIVE_CONFIG_1 = {
    # 83.9% WR, 31 signals (49.2% retention)
    'price_range': {
        'enabled': True,
        'min_price': 1,
        'max_price': 200
    },
    'rsi_threshold': {
        'enabled': True,
        'min_rsi': 35,
        'max_rsi': 65,
        'period': 20,
        'description': 'RSI between 35-65 (not oversold/overbought)'
    }
}

ALTERNATIVE_CONFIG_2 = {
    # 86.7% WR, 30 signals (47.6% retention)
    'rsi_threshold': {
        'enabled': True,
        'min_rsi': 35,
        'max_rsi': 65,
        'period': 20
    },
    'bollinger_position': {
        'enabled': True,
        'period': 10,
        'std_dev': 1.5,
        'min_position': 0.2,
        'max_position': 1.0
    }
}


def apply_optimized_filters(symbol: str, market_filters) -> bool:
    """
    Apply optimized filter configuration to a symbol
    
    Args:
        symbol: Stock ticker
        market_filters: MarketFilters instance
        
    Returns:
        True if symbol passes all filters
    """
    results = market_filters.run_filter_combination(
        symbol=symbol,
        filter_names=['price_range', 'bollinger_position'],
        filter_params=OPTIMIZED_FILTERS
    )
    
    return results['all_filters_passed']


# Integration example
if __name__ == "__main__":
    from market_filters import MarketFilters
    
    print("="*70)
    print("WAR MACHINE - OPTIMIZED FILTER CONFIGURATION")
    print("="*70)
    print("\n🏆 Optimal Configuration:")
    print(f"Filters: price_range + bollinger_position")
    print(f"Win Rate: 90.9%")
    print(f"Profit Factor: 3.23")
    print(f"\nParameters:")
    for filter_name, config in OPTIMIZED_FILTERS.items():
        print(f"\n{filter_name}:")
        for key, value in config.items():
            if key != 'description':
                print(f"  {key}: {value}")
    
    # Test on a symbol
    filters = MarketFilters()
    test_symbol = "AAPL"
    
    print(f"\n{'='*70}")
    print(f"Testing on {test_symbol}...")
    
    passed = apply_optimized_filters(test_symbol, filters)
    print(f"Result: {'✅ PASS' if passed else '❌ FAIL'}")
    
    # Show individual filter results
    results = filters.run_filter_combination(
        test_symbol,
        ['price_range', 'bollinger_position'],
        OPTIMIZED_FILTERS
    )
    
    print(f"\nIndividual Results:")
    for fname, result in results['individual_results'].items():
        print(f"  {fname}: {'✅ PASS' if result else '❌ FAIL'}")
