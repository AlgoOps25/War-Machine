"""
Insider Transactions Filter for War Machine
Uses EODHD Insider Transactions API to boost confidence when insiders are buying

EODHD API Endpoint: https://eodhd.com/api/insider-transactions
Documentation: https://eodhd.com/financial-apis/insider-transactions-api

Integration:
- Track insider buying vs selling activity
- Boost confidence when insiders are bullish (buying > selling)
- Cache insider data for 1 day (updates infrequently)
- No filtering - only confidence boosts
"""

import requests
import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import config


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

INSIDER_CACHE_TTL = 86400  # 24 hours (insider data changes slowly)
LOOKBACK_DAYS = 90  # Analyze last 90 days of transactions

# Confidence multiplier thresholds
STRONG_BUY_RATIO = 0.7  # 70%+ buying → 10% boost
MILD_BUY_RATIO = 0.6    # 60%+ buying → 5% boost
BALANCED_RATIO = 0.4    # 40-60% buying → neutral

# Minimum transaction count to be meaningful
MIN_TRANSACTIONS = 3


# ══════════════════════════════════════════════════════════════════════════════
# CACHING
# ══════════════════════════════════════════════════════════════════════════════

_insider_cache: Dict[str, Dict] = {}  # ticker -> {data, timestamp}


def _is_cache_valid(ticker: str) -> bool:
    """Check if cached insider data is still valid"""
    if ticker not in _insider_cache:
        return False
    return (time.time() - _insider_cache[ticker]['timestamp']) < INSIDER_CACHE_TTL


# ══════════════════════════════════════════════════════════════════════════════
# EODHD INSIDER TRANSACTIONS API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_insider_transactions(ticker: str) -> Optional[list]:
    """
    Fetch insider transactions from EODHD

    Args:
        ticker: Stock ticker symbol

    Returns:
        List of insider transactions or None if error
    """
    try:
        url = f"https://eodhd.com/api/insider-transactions"
        params = {
            'api_token': config.EODHD_API_KEY,
            'code': f'{ticker}.US',
            'limit': 100  # Get plenty of data
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        transactions = response.json()

        # Filter to lookback period
        cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
        recent_txns = []

        for txn in transactions:
            # Parse date (format: YYYY-MM-DD)
            txn_date_str = txn.get('date', '')
            if txn_date_str:
                txn_date = datetime.strptime(txn_date_str, '%Y-%m-%d')
                if txn_date >= cutoff:
                    recent_txns.append(txn)

        return recent_txns

    except Exception as e:
        print(f"[INSIDER] Error fetching transactions for {ticker}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# INSIDER ACTIVITY ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_insider_activity(transactions: list) -> Dict:
    """
    Analyze insider buying vs selling activity

    Returns:
        {
            'buy_count': int,
            'sell_count': int,
            'total_count': int,
            'buy_ratio': float (0.0-1.0),
            'buy_value': float (total $),
            'sell_value': float (total $),
            'net_value': float (buy - sell $)
        }
    """
    if not transactions:
        return {
            'buy_count': 0,
            'sell_count': 0,
            'total_count': 0,
            'buy_ratio': 0.5,  # Neutral
            'buy_value': 0.0,
            'sell_value': 0.0,
            'net_value': 0.0
        }

    buy_count = 0
    sell_count = 0
    buy_value = 0.0
    sell_value = 0.0

    for txn in transactions:
        txn_type = txn.get('transactionType', '').lower()
        value = txn.get('transactionValue', 0) or 0

        # Classify as buy or sell
        if any(x in txn_type for x in ['buy', 'purchase', 'acquisition']):
            buy_count += 1
            buy_value += abs(value)
        elif any(x in txn_type for x in ['sell', 'sale', 'disposition']):
            sell_count += 1
            sell_value += abs(value)

    total = buy_count + sell_count
    buy_ratio = buy_count / total if total > 0 else 0.5
    net_value = buy_value - sell_value

    return {
        'buy_count': buy_count,
        'sell_count': sell_count,
        'total_count': total,
        'buy_ratio': buy_ratio,
        'buy_value': buy_value,
        'sell_value': sell_value,
        'net_value': net_value
    }


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FILTER FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def get_insider_confidence_multiplier(ticker: str) -> Tuple[float, str]:
    """
    Get confidence multiplier based on insider activity

    Args:
        ticker: Stock ticker

    Returns:
        (confidence_multiplier, reason)

    Examples:
        (1.10, "Strong insider buying (75% buy ratio)")
        (1.05, "Mild insider buying (65% buy ratio)")
        (1.0, "Balanced insider activity")
        (1.0, "Insufficient insider data")
    """
    # Check cache first
    if _is_cache_valid(ticker):
        cached = _insider_cache[ticker]['data']
        return cached['multiplier'], cached['reason']

    # Fetch fresh data
    transactions = fetch_insider_transactions(ticker)

    # If no data or API error, return neutral
    if not transactions:
        result = {
            'multiplier': 1.0,
            'reason': 'No insider data available'
        }
        _insider_cache[ticker] = {'data': result, 'timestamp': time.time()}
        return result['multiplier'], result['reason']

    # Analyze activity
    activity = analyze_insider_activity(transactions)

    # Require minimum transactions for meaningful signal
    if activity['total_count'] < MIN_TRANSACTIONS:
        result = {
            'multiplier': 1.0,
            'reason': f"Insufficient insider data ({activity['total_count']} txns)"
        }

    # Strong buying signal
    elif activity['buy_ratio'] >= STRONG_BUY_RATIO:
        result = {
            'multiplier': 1.10,  # 10% boost
            'reason': f"Strong insider buying ({activity['buy_ratio']:.0%} buy ratio, "
                     f"{activity['buy_count']} buys vs {activity['sell_count']} sells)"
        }

    # Mild buying signal
    elif activity['buy_ratio'] >= MILD_BUY_RATIO:
        result = {
            'multiplier': 1.05,  # 5% boost
            'reason': f"Mild insider buying ({activity['buy_ratio']:.0%} buy ratio, "
                     f"{activity['buy_count']} buys vs {activity['sell_count']} sells)"
        }

    # Balanced or selling - neutral (no penalty, just no boost)
    else:
        result = {
            'multiplier': 1.0,
            'reason': f"Balanced/selling activity ({activity['buy_ratio']:.0%} buy ratio)"
        }

    # Cache result
    _insider_cache[ticker] = {'data': result, 'timestamp': time.time()}

    return result['multiplier'], result['reason']


# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def get_insider_summary(ticker: str) -> Dict:
    """Get full insider activity summary"""
    transactions = fetch_insider_transactions(ticker)

    if not transactions:
        return {'error': 'No insider data available'}

    activity = analyze_insider_activity(transactions)
    multiplier, reason = get_insider_confidence_multiplier(ticker)

    return {
        'ticker': ticker,
        'lookback_days': LOOKBACK_DAYS,
        'activity': activity,
        'confidence_multiplier': multiplier,
        'reason': reason,
        'recent_transactions': transactions[:5]  # Show 5 most recent
    }


def clear_insider_cache():
    """Clear all cached insider data"""
    _insider_cache.clear()
    print("[INSIDER] Cache cleared")


# ══════════════════════════════════════════════════════════════════════════════
# TESTING
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test with sample tickers
    test_tickers = ["AAPL", "TSLA", "NVDA"]

    print("\n=== INSIDER FILTER TEST ===\n")

    for ticker in test_tickers:
        print(f"\n--- {ticker} ---")
        multiplier, reason = get_insider_confidence_multiplier(ticker)
        print(f"Confidence Multiplier: {multiplier:.2f}x")
        print(f"Reason: {reason}")

        # Get full summary
        summary = get_insider_summary(ticker)
        if 'activity' in summary:
            act = summary['activity']
            print(f"Transactions: {act['total_count']} "
                  f"(Buy: {act['buy_count']}, Sell: {act['sell_count']})")
            print(f"Buy Ratio: {act['buy_ratio']:.1%}")
            if act['buy_value'] > 0 or act['sell_value'] > 0:
                print(f"Net Value: ${act['net_value']:,.0f}")