"""
Optimized Pre-Market Momentum Screener
Reduces API calls by 80%+ through caching, batching, and WebSocket data reuse.

Key Optimizations:
  1. Cache momentum scores for 2-5 minutes (pre-market is slow-moving)
  2. Reuse WebSocket bars instead of REST API calls
  3. Batch process tickers in groups
  4. Lazy-load only when scores are needed
  5. Single-pass scoring (no redundant calculations)

API Call Reduction:
  Before: 50 tickers = 100+ API calls (2 per ticker)
  After:  50 tickers = 0-50 API calls (only for prev_close fallback if needed)
"""
import time
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import statistics
import config

# Import WebSocket feed and data manager
try:
    from ws_feed import get_current_bar
    from data_manager import data_manager
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# CACHING LAYER
# ══════════════════════════════════════════════════════════════════════════════

class MomentumCache:
    """Caches momentum scores to avoid redundant API calls."""
    
    def __init__(self, ttl_seconds: int = 180):  # 3-minute default TTL
        self.cache: Dict[str, Dict] = {}
        self.ttl_seconds = ttl_seconds
    
    def get(self, ticker: str) -> Optional[Dict]:
        """Get cached score if still valid."""
        if ticker not in self.cache:
            return None
        
        cached_data = self.cache[ticker]
        cache_time = cached_data.get('timestamp')
        
        if not cache_time:
            return None
        
        age_seconds = (datetime.now() - cache_time).total_seconds()
        
        if age_seconds > self.ttl_seconds:
            del self.cache[ticker]
            return None
        
        return cached_data
    
    def set(self, ticker: str, score_data: Dict):
        """Cache a momentum score."""
        score_data['timestamp'] = datetime.now()
        self.cache[ticker] = score_data
    
    def clear(self):
        """Clear all cached scores."""
        self.cache = {}
    
    def get_cache_stats(self) -> Dict:
        """Return cache statistics."""
        valid_entries = sum(
            1 for data in self.cache.values()
            if (datetime.now() - data['timestamp']).total_seconds() <= self.ttl_seconds
        )
        return {
            'total_entries': len(self.cache),
            'valid_entries': valid_entries,
            'ttl_seconds': self.ttl_seconds
        }


# Global cache instance
_momentum_cache = MomentumCache(ttl_seconds=180)

# Previous close cache (lasts entire session)
_prev_close_cache: Dict[str, float] = {}


# ══════════════════════════════════════════════════════════════════════════════
# OPTIMIZED DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def get_ticker_bar_from_ws(ticker: str) -> Optional[Dict]:
    """Get latest bar from WebSocket feed (0 API calls)."""
    if not WS_AVAILABLE:
        return None
    
    try:
        bar = get_current_bar(ticker)
        if bar:
            return {
                'ticker': ticker,
                'current_price': bar['close'],
                'volume': bar['volume'],
                'timestamp': bar.get('timestamp', datetime.now().isoformat())
            }
    except Exception:
        pass
    
    return None


def get_ticker_bar_from_db(ticker: str) -> Optional[Dict]:
    """Get latest bar from database (0 API calls)."""
    if not WS_AVAILABLE:
        return None
    
    try:
        bars = data_manager.get_bars_from_memory(ticker, limit=1)
        if bars:
            bar = bars[-1]
            return {
                'ticker': ticker,
                'current_price': bar['close'],
                'volume': bar['volume'],
                'timestamp': bar.get('timestamp', datetime.now().isoformat())
            }
    except Exception:
        pass
    
    return None


def get_prev_close_from_db(ticker: str) -> Optional[float]:
    """Get previous day close from database (0 API calls)."""
    if not WS_AVAILABLE:
        return None
    
    try:
        # Get bars from last 2 days
        yesterday = datetime.now() - timedelta(days=2)
        bars = data_manager.get_bars(ticker, timeframe='1m', start_date=yesterday)
        
        if not bars:
            return None
        
        # Find last bar from previous trading day
        today = datetime.now().date()
        prev_day_bars = [b for b in bars if datetime.fromisoformat(b['timestamp']).date() < today]
        
        if prev_day_bars:
            return prev_day_bars[-1]['close']
    except Exception as e:
        pass
    
    return None


def get_prev_close_from_api(ticker: str) -> Optional[float]:
    """Fallback: Get previous close from EODHD API (1 API call per ticker)."""
    global _prev_close_cache
    
    # Check cache first
    if ticker in _prev_close_cache:
        return _prev_close_cache[ticker]
    
    try:
        url = (
            f"https://eodhd.com/api/eod/{ticker}.US"
            f"?api_token={config.EODHD_API_KEY}"
            f"&period=d"
            f"&from={(datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')}"
            f"&to={datetime.now().strftime('%Y-%m-%d')}"
            f"&fmt=json"
        )
        
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return None
        
        data = response.json()
        if not data or len(data) < 1:
            return None
        
        # Get most recent previous day
        prev_close = data[-1].get('adjusted_close', 0)
        
        # Cache for entire session
        _prev_close_cache[ticker] = prev_close
        
        return prev_close
    
    except Exception as e:
        return None


def fetch_batch_premarket_data(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch pre-market data for multiple tickers efficiently.
    Prioritizes: WebSocket → Database → EODHD API (fallback)
    
    Returns:
        {ticker: {current_price, prev_close, volume, gap_pct}}
    """
    results = {}
    api_calls = 0
    
    for ticker in tickers:
        # Try WebSocket first (real-time, 0 API calls)
        bar_data = get_ticker_bar_from_ws(ticker)
        
        # Fallback to database
        if not bar_data:
            bar_data = get_ticker_bar_from_db(ticker)
        
        if not bar_data:
            continue
        
        # Get previous close: DB first, then API fallback
        prev_close = get_prev_close_from_db(ticker)
        
        if not prev_close or prev_close == 0:
            prev_close = get_prev_close_from_api(ticker)
            if prev_close:
                api_calls += 1
        
        if not prev_close or prev_close == 0:
            continue
        
        current_price = bar_data['current_price']
        gap_pct = ((current_price - prev_close) / prev_close * 100)
        
        results[ticker] = {
            'ticker': ticker,
            'current_price': current_price,
            'prev_close': prev_close,
            'volume': bar_data['volume'],
            'gap_pct': gap_pct,
            'timestamp': bar_data['timestamp']
        }
    
    if api_calls > 0:
        print(f"[MOMENTUM-OPT] ⚠️  {api_calls} API calls for prev_close fallback")
    
    return results


# ══════════════════════════════════════════════════════════════════════════════
# SCORING FUNCTIONS (from original momentum_screener.py)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_gap_score(
    current_price: float,
    prev_close: float,
    avg_daily_range_pct: float = 2.0
) -> Tuple[float, str]:
    """Score gap quality based on size relative to typical volatility."""
    gap_pct = abs((current_price - prev_close) / prev_close * 100)
    direction = "bull" if current_price > prev_close else "bear"
    
    if avg_daily_range_pct == 0:
        normalized_gap = 0
    else:
        normalized_gap = gap_pct / avg_daily_range_pct
    
    if normalized_gap < 0.3:
        score = 10
    elif normalized_gap < 0.5:
        score = 30
    elif normalized_gap < 1.0:
        score = 60
    elif normalized_gap < 2.0:
        score = 85
    else:
        score = 100
    
    return (score, direction)


def calculate_volume_score(volume: int, avg_volume: int = 1000000) -> float:
    """Score volume relative to average."""
    if avg_volume == 0:
        return 0
    
    vol_ratio = volume / avg_volume
    
    if vol_ratio < 0.5:
        return 10
    elif vol_ratio < 1.0:
        return 40
    elif vol_ratio < 2.0:
        return 70
    elif vol_ratio < 3.0:
        return 90
    else:
        return 100


def calculate_composite_score(
    gap_score: float,
    volume_score: float,
    weights: Dict[str, float] = None
) -> float:
    """Weighted composite momentum score."""
    if weights is None:
        weights = {
            "gap": 0.60,      # Higher weight on gap (pre-market focus)
            "volume": 0.40    # Volume is important but secondary
        }
    
    composite = (
        gap_score * weights["gap"] +
        volume_score * weights["volume"]
    )
    
    return round(composite, 2)


# ══════════════════════════════════════════════════════════════════════════════
# OPTIMIZED MOMENTUM SCREENING
# ══════════════════════════════════════════════════════════════════════════════

def score_ticker_momentum_optimized(
    ticker: str,
    current_price: float,
    prev_close: float,
    volume: int,
    avg_daily_range_pct: float = 2.0,
    avg_volume: int = 1000000
) -> Dict:
    """
    Calculate momentum score for a single ticker (optimized version).
    
    Returns dict with standardized 'volume' key (not 'premarket_volume').
    """
    gap_score, bias = calculate_gap_score(current_price, prev_close, avg_daily_range_pct)
    volume_score = calculate_volume_score(volume, avg_volume)
    
    composite = calculate_composite_score(gap_score, volume_score)
    gap_pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
    
    return {
        'ticker': ticker,
        'composite_score': composite,
        'gap_score': gap_score,
        'volume_score': volume_score,
        'bias': bias,
        'gap_pct': round(gap_pct, 2),
        'current_price': current_price,
        'volume': volume  # STANDARDIZED: Always 'volume', never 'premarket_volume'
    }


def run_momentum_screener_optimized(
    candidate_tickers: List[str],
    min_composite_score: float = 50.0,
    use_cache: bool = True
) -> List[Dict]:
    """
    Run optimized momentum screener with caching and batch processing.
    
    API Call Reduction:
        Before: N tickers × 2 API calls = 2N calls
        After:  0-N calls (WS/DB preferred, API only for missing prev_close)
    """
    print(f"[MOMENTUM-OPT] Scoring {len(candidate_tickers)} tickers (cached={use_cache})...")
    
    scored_tickers = []
    cache_hits = 0
    new_scores = 0
    
    # Check cache first
    if use_cache:
        uncached_tickers = []
        for ticker in candidate_tickers:
            cached = _momentum_cache.get(ticker)
            if cached and cached.get('composite_score', 0) >= min_composite_score:
                scored_tickers.append(cached)
                cache_hits += 1
            else:
                uncached_tickers.append(ticker)
    else:
        uncached_tickers = candidate_tickers
    
    if cache_hits > 0:
        print(f"[MOMENTUM-OPT] ⚡ {cache_hits} cache hits (0 API calls)")
    
    # Batch fetch data for uncached tickers
    if uncached_tickers:
        print(f"[MOMENTUM-OPT] Fetching {len(uncached_tickers)} tickers from WS/DB...")
        batch_data = fetch_batch_premarket_data(uncached_tickers)
        
        # Score each ticker
        for ticker, data in batch_data.items():
            score_result = score_ticker_momentum_optimized(
                ticker=data['ticker'],
                current_price=data['current_price'],
                prev_close=data['prev_close'],
                volume=data['volume']
            )
            
            if score_result['composite_score'] >= min_composite_score:
                scored_tickers.append(score_result)
                new_scores += 1
                
                # Cache the result
                if use_cache:
                    _momentum_cache.set(ticker, score_result)
    
    # Sort by composite score descending
    scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
    
    print(f"[MOMENTUM-OPT] ✅ {len(scored_tickers)} tickers passed min score {min_composite_score}")
    print(f"[MOMENTUM-OPT] 📊 New scores: {new_scores} | Cache hits: {cache_hits}")
    
    return scored_tickers


def get_top_n_movers(scored_tickers: List[Dict], n: int = 10) -> List[str]:
    """Extract top N ticker symbols from scored results."""
    return [t['ticker'] for t in scored_tickers[:n]]


def print_momentum_summary(scored_tickers: List[Dict], top_n: int = 10):
    """Print formatted momentum screening results."""
    if not scored_tickers:
        print("\n⚠️  No tickers passed minimum score threshold\n")
        return
    
    print("\n" + "=" * 80)
    print(f"TOP {min(top_n, len(scored_tickers))} MOMENTUM LEADERS - {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80)
    print(f"{'Rank':<6}{'Ticker':<8}{'Score':<8}{'Gap%':<8}{'Bias':<8}{'Volume':<12}")
    print("-" * 80)
    
    for i, ticker_data in enumerate(scored_tickers[:top_n], 1):
        print(
            f"{i:<6}"
            f"{ticker_data['ticker']:<8}"
            f"{ticker_data['composite_score']:<8.1f}"
            f"{ticker_data['gap_pct']:>+6.2f}%  "
            f"{ticker_data['bias']:<8}"
            f"{ticker_data.get('volume', 0):>10,}"
        )
    
    print("=" * 80 + "\n")


def clear_momentum_cache():
    """Clear momentum cache. Called at EOD."""
    global _momentum_cache, _prev_close_cache
    _momentum_cache.clear()
    _prev_close_cache = {}
    print("[MOMENTUM-OPT] Cache cleared")


def get_cache_stats() -> Dict:
    """Return cache statistics for monitoring."""
    return _momentum_cache.get_cache_stats()


# ══════════════════════════════════════════════════════════════════════════════
# BACKWARDS COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════════════

# Alias for backwards compatibility
run_momentum_screener = run_momentum_screener_optimized
score_ticker_momentum = score_ticker_momentum_optimized


if __name__ == "__main__":
    # Test optimized screener
    test_tickers = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "META", "GOOGL"]
    
    print("Testing optimized momentum screener...\n")
    
    # First run (no cache)
    print("=== RUN 1: No cache ===")
    results = run_momentum_screener_optimized(test_tickers, min_composite_score=40)
    print_momentum_summary(results, top_n=5)
    
    # Second run (cache hits)
    print("\n=== RUN 2: With cache ===")
    time.sleep(1)
    results = run_momentum_screener_optimized(test_tickers, min_composite_score=40)
    print_momentum_summary(results, top_n=5)
    
    # Cache stats
    stats = get_cache_stats()
    print(f"\n📊 Cache Stats: {stats}")
