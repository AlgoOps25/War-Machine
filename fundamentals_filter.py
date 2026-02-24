"""
Fundamentals Filter for War Machine
Uses EODHD Fundamentals API to filter illiquid stocks and boost quality names

EODHD API Endpoint: https://eodhd.com/api/fundamentals/{ticker}
Documentation: https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds

Integration:
- Filter stocks with low float (hard to trade)
- Filter stocks with insufficient volume (slippage risk)
- Boost confidence for strong institutional backing
- Cache fundamentals for 24 hours (changes slowly)
"""

import requests
import time
from typing import Dict, Optional, Tuple
import config


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

FUNDAMENTALS_CACHE_TTL = 86400  # 24 hours (fundamentals change slowly)

# Filter thresholds (HARD filters - signal dropped if violated)
MIN_FLOAT_MILLION = 10      # Minimum 10M shares float
MIN_AVG_VOLUME = 500_000    # Minimum 500K avg daily volume
MIN_MARKET_CAP_MILLION = 500  # Minimum $500M market cap (avoid penny stocks)

# Confidence boost thresholds (SOFT boosts)
HIGH_INSTITUTIONAL_PCT = 70  # 70%+ institutional → 5% boost
MID_INSTITUTIONAL_PCT = 50   # 50-70% institutional → 2.5% boost


# ══════════════════════════════════════════════════════════════════════════════
# CACHING
# ══════════════════════════════════════════════════════════════════════════════

_fundamentals_cache: Dict[str, Dict] = {}  # ticker -> {data, timestamp}


def _is_cache_valid(ticker: str) -> bool:
    """Check if cached fundamentals are still valid"""
    if ticker not in _fundamentals_cache:
        return False
    return (time.time() - _fundamentals_cache[ticker]['timestamp']) < FUNDAMENTALS_CACHE_TTL


# ══════════════════════════════════════════════════════════════════════════════
# EODHD FUNDAMENTALS API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_fundamentals(ticker: str) -> Optional[Dict]:
    """
    Fetch fundamental data from EODHD

    Args:
        ticker: Stock ticker symbol

    Returns:
        Fundamentals dict or None if error
    """
    try:
        url = f"https://eodhd.com/api/fundamentals/{ticker}.US"
        params = {
            'api_token': config.EODHD_API_KEY,
            'fmt': 'json'
        }

        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()

        data = response.json()
        return data

    except Exception as e:
        print(f"[FUNDAMENTALS] Error fetching data for {ticker}: {e}")
        return None


def extract_key_metrics(fundamentals: Dict) -> Dict:
    """
    Extract the metrics we care about from EODHD response

    Returns:
        {
            'float_shares': float (millions),
            'avg_volume': float,
            'market_cap': float (millions),
            'institutional_pct': float (0-100),
            'shares_outstanding': float (millions)
        }
    """
    try:
        # Navigate EODHD data structure
        highlights = fundamentals.get('Highlights', {})
        share_stats = fundamentals.get('SharesStats', {})
        holders = fundamentals.get('Holders', {})

        # Extract metrics with safe defaults
        shares_outstanding = share_stats.get('SharesOutstanding', 0) / 1_000_000  # Convert to millions
        float_shares = share_stats.get('SharesFloat', shares_outstanding)  # Default to shares outstanding
        avg_volume = highlights.get('AverageVolume', 0)
        market_cap = highlights.get('MarketCapitalization', 0) / 1_000_000  # Convert to millions

        # Institutional ownership
        institutions = holders.get('Institutions', [])
        if institutions:
            # Sum up institutional holdings
            institutional_pct = sum(inst.get('percentHeld', 0) for inst in institutions)
        else:
            institutional_pct = 0

        return {
            'float_shares': float_shares,
            'avg_volume': avg_volume,
            'market_cap': market_cap,
            'institutional_pct': institutional_pct,
            'shares_outstanding': shares_outstanding
        }

    except Exception as e:
        print(f"[FUNDAMENTALS] Error extracting metrics: {e}")
        return {
            'float_shares': 0,
            'avg_volume': 0,
            'market_cap': 0,
            'institutional_pct': 0,
            'shares_outstanding': 0
        }


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FILTER FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def check_fundamentals(ticker: str) -> Tuple[bool, float, str]:
    """
    Check fundamental metrics and return filter decision + confidence multiplier

    Args:
        ticker: Stock ticker

    Returns:
        (should_proceed, confidence_multiplier, reason)

    Examples:
        (True, 1.05, "Strong institutional backing (75%)")
        (True, 1.0, "Meets liquidity requirements")
        (False, 0.0, "Low float (8M shares)")
        (False, 0.0, "Insufficient volume (200K avg)")
    """
    # Check cache first
    if _is_cache_valid(ticker):
        cached = _fundamentals_cache[ticker]['data']
        return cached['should_proceed'], cached['multiplier'], cached['reason']

    # Fetch fresh data
    fundamentals = fetch_fundamentals(ticker)

    # If no data or API error, proceed with neutral stance (don't block)
    if not fundamentals:
        result = {
            'should_proceed': True,
            'multiplier': 1.0,
            'reason': 'No fundamental data available (proceeding)'
        }
        _fundamentals_cache[ticker] = {'data': result, 'timestamp': time.time()}
        return result['should_proceed'], result['multiplier'], result['reason']

    # Extract metrics
    metrics = extract_key_metrics(fundamentals)

    # HARD FILTERS (drop signal if violated)

    # Check float
    if 0 < metrics['float_shares'] < MIN_FLOAT_MILLION:
        result = {
            'should_proceed': False,
            'multiplier': 0.0,
            'reason': f"Low float ({metrics['float_shares']:.1f}M shares, min {MIN_FLOAT_MILLION}M)"
        }
        _fundamentals_cache[ticker] = {'data': result, 'timestamp': time.time()}
        return result['should_proceed'], result['multiplier'], result['reason']

    # Check volume
    if 0 < metrics['avg_volume'] < MIN_AVG_VOLUME:
        result = {
            'should_proceed': False,
            'multiplier': 0.0,
            'reason': f"Low volume ({metrics['avg_volume']:,.0f} avg, min {MIN_AVG_VOLUME:,})"
        }
        _fundamentals_cache[ticker] = {'data': result, 'timestamp': time.time()}
        return result['should_proceed'], result['multiplier'], result['reason']

    # Check market cap (avoid penny stocks)
    if 0 < metrics['market_cap'] < MIN_MARKET_CAP_MILLION:
        result = {
            'should_proceed': False,
            'multiplier': 0.0,
            'reason': f"Low market cap (${metrics['market_cap']:.0f}M, min ${MIN_MARKET_CAP_MILLION}M)"
        }
        _fundamentals_cache[ticker] = {'data': result, 'timestamp': time.time()}
        return result['should_proceed'], result['multiplier'], result['reason']

    # SOFT BOOSTS (confidence multipliers)

    # Strong institutional backing
    if metrics['institutional_pct'] >= HIGH_INSTITUTIONAL_PCT:
        result = {
            'should_proceed': True,
            'multiplier': 1.05,  # 5% boost
            'reason': f"Strong institutional backing ({metrics['institutional_pct']:.0f}%)"
        }

    # Mid-level institutional backing
    elif metrics['institutional_pct'] >= MID_INSTITUTIONAL_PCT:
        result = {
            'should_proceed': True,
            'multiplier': 1.025,  # 2.5% boost
            'reason': f"Good institutional backing ({metrics['institutional_pct']:.0f}%)"
        }

    # Passes all filters but no special qualities
    else:
        result = {
            'should_proceed': True,
            'multiplier': 1.0,
            'reason': f"Meets liquidity requirements (Float: {metrics['float_shares']:.0f}M, "
                     f"Vol: {metrics['avg_volume']:,.0f}, MCap: ${metrics['market_cap']:.0f}M)"
        }

    # Cache result
    _fundamentals_cache[ticker] = {'data': result, 'timestamp': time.time()}

    return result['should_proceed'], result['multiplier'], result['reason']


# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def get_fundamentals_summary(ticker: str) -> Dict:
    """Get full fundamentals summary"""
    fundamentals = fetch_fundamentals(ticker)

    if not fundamentals:
        return {'error': 'No fundamentals data available'}

    metrics = extract_key_metrics(fundamentals)
    should_proceed, multiplier, reason = check_fundamentals(ticker)

    return {
        'ticker': ticker,
        'metrics': metrics,
        'filter_decision': {
            'should_proceed': should_proceed,
            'confidence_multiplier': multiplier,
            'reason': reason
        },
        'thresholds': {
            'min_float_million': MIN_FLOAT_MILLION,
            'min_avg_volume': MIN_AVG_VOLUME,
            'min_market_cap_million': MIN_MARKET_CAP_MILLION
        }
    }


def clear_fundamentals_cache():
    """Clear all cached fundamental data"""
    _fundamentals_cache.clear()
    print("[FUNDAMENTALS] Cache cleared")


# ══════════════════════════════════════════════════════════════════════════════
# TESTING
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test with sample tickers (mix of large/small cap)
    test_tickers = ["AAPL", "TSLA", "NVDA", "SPY"]

    print("\n=== FUNDAMENTALS FILTER TEST ===\n")

    for ticker in test_tickers:
        print(f"\n--- {ticker} ---")
        should_proceed, multiplier, reason = check_fundamentals(ticker)
        print(f"Should Proceed: {should_proceed}")
        print(f"Confidence Mult: {multiplier:.3f}x")
        print(f"Reason: {reason}")

        # Get full summary
        summary = get_fundamentals_summary(ticker)
        if 'metrics' in summary:
            m = summary['metrics']
            print(f"Float: {m['float_shares']:.1f}M | "
                  f"Avg Vol: {m['avg_volume']:,.0f} | "
                  f"MCap: ${m['market_cap']:.0f}M | "
                  f"Inst: {m['institutional_pct']:.0f}%")