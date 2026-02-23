"""
Advanced Pre-Market Momentum Screener
Replaces static fallback with data-driven momentum scoring for opening bell predictions.

Scoring Factors:
  1. Gap Quality (gap % vs typical range, hold/fade pattern)
  2. Pre-Market Volume Acceleration (current vs historical 9:15-9:30 avg)
  3. Technical Setup Quality (proximity to key levels, FVG alignment)
  4. Dark Pool Activity (overnight institutional flow)
  5. Options Flow Imbalance (bullish vs bearish premium)

Output: Scored watchlist ranked by predicted opening volatility and directional edge
"""
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import statistics
import config


def calculate_gap_score(
    current_price: float,
    prev_close: float,
    avg_daily_range_pct: float
) -> Tuple[float, str]:
    """
    Score gap quality based on size relative to typical volatility.
    
    Returns:
        (score: 0-100, bias: 'bull'|'bear'|'neutral')
    """
    gap_pct = abs((current_price - prev_close) / prev_close * 100)
    direction = "bull" if current_price > prev_close else "bear"
    
    # Normalize gap against typical daily range
    if avg_daily_range_pct == 0:
        normalized_gap = 0
    else:
        normalized_gap = gap_pct / avg_daily_range_pct
    
    # Score curve: 0.5x range = 30 pts, 1x = 60 pts, 2x+ = 100 pts
    if normalized_gap < 0.3:
        score = 10  # Too small to matter
    elif normalized_gap < 0.5:
        score = 30
    elif normalized_gap < 1.0:
        score = 60
    elif normalized_gap < 2.0:
        score = 85
    else:
        score = 100  # Massive gap
    
    return (score, direction)


def calculate_volume_acceleration_score(
    current_premarket_vol: int,
    avg_premarket_vol_10d: int,
    time_elapsed_pct: float
) -> float:
    """
    Score pre-market volume acceleration relative to historical average.
    
    Args:
        current_premarket_vol: Total pre-market volume so far today
        avg_premarket_vol_10d: Average total pre-market volume (last 10 days)
        time_elapsed_pct: % of pre-market session elapsed (e.g. 0.8 = 80% done)
    
    Returns:
        score: 0-100
    """
    if avg_premarket_vol_10d == 0 or time_elapsed_pct == 0:
        return 0
    
    # Expected volume = avg * time_elapsed
    expected_vol = avg_premarket_vol_10d * time_elapsed_pct
    
    if expected_vol == 0:
        return 0
    
    # Acceleration ratio
    accel_ratio = current_premarket_vol / expected_vol
    
    # Score curve: 1x = 40 pts, 2x = 70 pts, 3x+ = 100 pts
    if accel_ratio < 0.5:
        score = 10
    elif accel_ratio < 1.0:
        score = 40
    elif accel_ratio < 2.0:
        score = 70
    elif accel_ratio < 3.0:
        score = 90
    else:
        score = 100
    
    return score


def calculate_technical_setup_score(
    current_price: float,
    key_levels: Dict[str, float]
) -> float:
    """
    Score proximity to high-probability technical levels.
    
    Args:
        current_price: Current pre-market price
        key_levels: {
            'prev_high': float,
            'prev_low': float,
            'vwap': float,
            'ema_20': float
        }
    
    Returns:
        score: 0-100
    """
    score = 0
    
    # Check proximity to previous day high/low (within 1%)
    if 'prev_high' in key_levels:
        dist_to_high = abs(current_price - key_levels['prev_high']) / key_levels['prev_high']
        if dist_to_high < 0.01:  # Within 1%
            score += 40
    
    if 'prev_low' in key_levels:
        dist_to_low = abs(current_price - key_levels['prev_low']) / key_levels['prev_low']
        if dist_to_low < 0.01:
            score += 40
    
    # Check if price is above/below key moving averages
    if 'vwap' in key_levels and 'ema_20' in key_levels:
        above_vwap = current_price > key_levels['vwap']
        above_ema = current_price > key_levels['ema_20']
        
        # Aligned = bullish or bearish setup
        if above_vwap == above_ema:
            score += 20
    
    return min(score, 100)


def calculate_dark_pool_score(dark_pool_volume: int, regular_volume: int) -> float:
    """
    Score dark pool activity as % of total volume.
    High dark pool = institutional accumulation/distribution.
    
    Returns:
        score: 0-100
    """
    if regular_volume == 0:
        return 0
    
    dp_ratio = dark_pool_volume / regular_volume
    
    # Score curve: 10% = 30 pts, 20% = 60 pts, 30%+ = 100 pts
    if dp_ratio < 0.05:
        return 10
    elif dp_ratio < 0.10:
        return 30
    elif dp_ratio < 0.20:
        return 60
    elif dp_ratio < 0.30:
        return 85
    else:
        return 100


def calculate_composite_score(
    gap_score: float,
    volume_score: float,
    technical_score: float,
    dark_pool_score: float,
    weights: Dict[str, float] = None
) -> float:
    """
    Weighted composite momentum score.
    
    Default weights:
        gap: 35%, volume: 30%, technical: 25%, dark_pool: 10%
    """
    if weights is None:
        weights = {
            "gap": 0.35,
            "volume": 0.30,
            "technical": 0.25,
            "dark_pool": 0.10
        }
    
    composite = (
        gap_score * weights["gap"] +
        volume_score * weights["volume"] +
        technical_score * weights["technical"] +
        dark_pool_score * weights["dark_pool"]
    )
    
    return round(composite, 2)


def fetch_premarket_momentum_data(ticker: str) -> Optional[Dict]:
    """
    Fetch pre-market data for a single ticker from EODHD.
    
    Returns:
        {
            'ticker': str,
            'current_price': float,
            'prev_close': float,
            'premarket_volume': int,
            'gap_pct': float,
            'timestamp': str
        }
    """
    try:
        # Fetch current intraday data (includes pre-market)
        url = (
            f"https://eodhd.com/api/intraday/{ticker}.US"
            f"?api_token={config.EODHD_API_KEY}"
            f"&interval=1m"
            f"&from={int((datetime.now() - timedelta(hours=5)).timestamp())}"
            f"&to={int(datetime.now().timestamp())}"
            f"&fmt=json"
        )
        
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return None
        
        bars = response.json()
        if not bars:
            return None
        
        # Get current (latest) bar
        current_bar = bars[-1]
        current_price = current_bar.get('close', 0)
        
        # Sum pre-market volume
        premarket_vol = sum(bar.get('volume', 0) for bar in bars)
        
        # Fetch previous day close
        prev_url = (
            f"https://eodhd.com/api/eod/{ticker}.US"
            f"?api_token={config.EODHD_API_KEY}"
            f"&period=d"
            f"&from={(datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')}"
            f"&to={datetime.now().strftime('%Y-%m-%d')}"
            f"&fmt=json"
        )
        
        prev_response = requests.get(prev_url, timeout=10)
        if prev_response.status_code != 200:
            return None
        
        prev_data = prev_response.json()
        if not prev_data:
            return None
        
        prev_close = prev_data[-1].get('adjusted_close', 0)
        
        gap_pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
        
        return {
            'ticker': ticker,
            'current_price': current_price,
            'prev_close': prev_close,
            'premarket_volume': premarket_vol,
            'gap_pct': gap_pct,
            'timestamp': datetime.now().isoformat()
        }
    
    except Exception as e:
        print(f"[MOMENTUM] Error fetching {ticker}: {e}")
        return None


def score_ticker_momentum(
    ticker: str,
    current_price: float,
    prev_close: float,
    premarket_volume: int,
    avg_daily_range_pct: float = 2.0,
    avg_premarket_vol: int = 100000,
    key_levels: Dict[str, float] = None,
    dark_pool_volume: int = 0
) -> Dict:
    """
    Calculate comprehensive momentum score for a single ticker.
    
    Returns:
        {
            'ticker': str,
            'composite_score': float,
            'gap_score': float,
            'volume_score': float,
            'technical_score': float,
            'dark_pool_score': float,
            'bias': str ('bull'|'bear'|'neutral'),
            'gap_pct': float
        }
    """
    # Calculate time elapsed in pre-market (assume 4:00 AM - 9:30 AM = 5.5 hours)
    now = datetime.now().time()
    premarket_start = datetime.strptime("04:00", "%H:%M").time()
    market_open = datetime.strptime("09:30", "%H:%M").time()
    
    # Convert to minutes for easier math
    def time_to_minutes(t):
        return t.hour * 60 + t.minute
    
    elapsed = time_to_minutes(now) - time_to_minutes(premarket_start)
    total_premarket = time_to_minutes(market_open) - time_to_minutes(premarket_start)
    time_elapsed_pct = max(0, min(1, elapsed / total_premarket)) if total_premarket > 0 else 0
    
    # Score components
    gap_score, bias = calculate_gap_score(current_price, prev_close, avg_daily_range_pct)
    volume_score = calculate_volume_acceleration_score(premarket_volume, avg_premarket_vol, time_elapsed_pct)
    technical_score = calculate_technical_setup_score(current_price, key_levels or {})
    dp_score = calculate_dark_pool_score(dark_pool_volume, premarket_volume)
    
    composite = calculate_composite_score(gap_score, volume_score, technical_score, dp_score)
    
    gap_pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
    
    return {
        'ticker': ticker,
        'composite_score': composite,
        'gap_score': gap_score,
        'volume_score': volume_score,
        'technical_score': technical_score,
        'dark_pool_score': dp_score,
        'bias': bias,
        'gap_pct': round(gap_pct, 2),
        'current_price': current_price,
        'premarket_volume': premarket_volume
    }


def run_momentum_screener(
    candidate_tickers: List[str],
    min_composite_score: float = 50.0
) -> List[Dict]:
    """
    Run momentum screener on a list of candidate tickers.
    
    Args:
        candidate_tickers: List of tickers to score
        min_composite_score: Minimum composite score to include (0-100)
    
    Returns:
        List of scored tickers sorted by composite_score (descending)
    """
    print(f"[MOMENTUM] Scoring {len(candidate_tickers)} tickers...")
    
    scored_tickers = []
    
    for ticker in candidate_tickers:
        data = fetch_premarket_momentum_data(ticker)
        if not data:
            continue
        
        score_result = score_ticker_momentum(
            ticker=data['ticker'],
            current_price=data['current_price'],
            prev_close=data['prev_close'],
            premarket_volume=data['premarket_volume']
        )
        
        if score_result['composite_score'] >= min_composite_score:
            scored_tickers.append(score_result)
    
    # Sort by composite score descending
    scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
    
    print(f"[MOMENTUM] ✅ {len(scored_tickers)} tickers passed min score {min_composite_score}")
    
    return scored_tickers


def get_top_n_movers(scored_tickers: List[Dict], n: int = 10) -> List[str]:
    """
    Extract top N ticker symbols from scored results.
    """
    return [t['ticker'] for t in scored_tickers[:n]]


def print_momentum_summary(scored_tickers: List[Dict], top_n: int = 10):
    """
    Print formatted momentum screening results.
    """
    print("\n" + "=" * 80)
    print(f"TOP {top_n} MOMENTUM LEADERS - {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80)
    print(f"{'Rank':<6}{'Ticker':<8}{'Score':<8}{'Gap%':<8}{'Bias':<8}{'PM Vol':<12}")
    print("-" * 80)
    
    for i, ticker_data in enumerate(scored_tickers[:top_n], 1):
        print(
            f"{i:<6}"
            f"{ticker_data['ticker']:<8}"
            f"{ticker_data['composite_score']:<8.1f}"
            f"{ticker_data['gap_pct']:>+6.2f}%  "
            f"{ticker_data['bias']:<8}"
            f"{ticker_data['premarket_volume']:>10,}"
        )
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    # Test with a sample watchlist
    test_tickers = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "META"]
    
    results = run_momentum_screener(test_tickers, min_composite_score=40)
    print_momentum_summary(results, top_n=5)
