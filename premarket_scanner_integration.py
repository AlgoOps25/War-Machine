"""
Pre-Market Scanner Integration Layer
Connects premarket_scanner_pro.py with existing watchlist_funnel.py infrastructure.

This module:
  1. Fetches fundamental data (ATR, market cap, float) from EODHD
  2. Combines real-time price/volume from WebSocket/DB
  3. Runs professional 3-tier scoring
  4. Returns results in format compatible with watchlist_funnel.py

Backwards Compatible:
  - Drop-in replacement for momentum_screener_optimized.py
  - Same function signatures and return formats
  - Caching for 3-minute TTL (pre-market is slow-moving)
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
import statistics

import config
import premarket_scanner_pro as pro_scanner

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

class ScannerCache:
    """Caches professional scan results and fundamental data."""
    
    def __init__(self, ttl_seconds: int = 180):  # 3-minute TTL
        self.scan_cache: Dict[str, Dict] = {}
        self.fundamental_cache: Dict[str, Dict] = {}  # ATR, float, market cap
        self.ttl_seconds = ttl_seconds
    
    def get_scan(self, ticker: str) -> Optional[Dict]:
        """Get cached scan result if valid."""
        if ticker not in self.scan_cache:
            return None
        
        cached = self.scan_cache[ticker]
        age = (datetime.now() - cached['timestamp']).total_seconds()
        
        if age > self.ttl_seconds:
            del self.scan_cache[ticker]
            return None
        
        return cached
    
    def set_scan(self, ticker: str, result: Dict):
        """Cache scan result."""
        result['timestamp'] = datetime.now()
        self.scan_cache[ticker] = result
    
    def get_fundamental(self, ticker: str) -> Optional[Dict]:
        """Get cached fundamental data (lasts entire session)."""
        return self.fundamental_cache.get(ticker)
    
    def set_fundamental(self, ticker: str, data: Dict):
        """Cache fundamental data (ATR, float, market cap)."""
        self.fundamental_cache[ticker] = data
    
    def clear(self):
        """Clear all caches."""
        self.scan_cache = {}
        # Keep fundamentals cached for entire session
    
    def get_stats(self) -> Dict:
        """Return cache statistics."""
        valid_scans = sum(
            1 for data in self.scan_cache.values()
            if (datetime.now() - data['timestamp']).total_seconds() <= self.ttl_seconds
        )
        return {
            'scan_cache_entries': len(self.scan_cache),
            'valid_scans': valid_scans,
            'fundamental_cache_entries': len(self.fundamental_cache),
            'ttl_seconds': self.ttl_seconds
        }


# Global cache instance
_scanner_cache = ScannerCache(ttl_seconds=180)

# Previous close cache
_prev_close_cache: Dict[str, float] = {}


# ══════════════════════════════════════════════════════════════════════════════
# FUNDAMENTAL DATA FETCHING (ATR, MARKET CAP, FLOAT)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_fundamental_data(ticker: str) -> Dict:
    """
    Fetch fundamental data needed for professional scoring.
    
    Data needed:
      - ATR (Average True Range) - 14-day default
      - Market Cap
      - Float (shares outstanding)
      - Average Daily Volume (20-day)
    
    Source: EODHD Fundamentals API
    Cached for entire session (slow-changing data)
    """
    # Check cache first
    cached = _scanner_cache.get_fundamental(ticker)
    if cached:
        return cached
    
    try:
        # Get fundamentals from EODHD
        url = f"https://eodhd.com/api/fundamentals/{ticker}.US?api_token={config.EODHD_API_KEY}&fmt=json"
        
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return _get_default_fundamentals(ticker)
        
        data = response.json()
        
        # Extract key data
        highlights = data.get('Highlights', {})
        technicals = data.get('Technicals', {})
        shares_stats = data.get('SharesStats', {})
        
        market_cap = highlights.get('MarketCapitalization', 0) or 0
        float_shares = shares_stats.get('SharesFloat', 0) or shares_stats.get('SharesOutstanding', 0) or 0
        
        # ATR from technicals (if available)
        atr = technicals.get('AverageTrueRange14', 0) or 0
        
        # Average daily volume
        avg_volume = highlights.get('AverageDailyVolume', 0) or 0
        
        # If ATR not available, calculate from recent bars
        if atr == 0:
            atr = _calculate_atr_from_bars(ticker)
        
        # If average volume not available, use fallback
        if avg_volume == 0:
            avg_volume = _get_average_volume_from_bars(ticker)
        
        fundamentals = {
            'ticker': ticker,
            'market_cap': market_cap,
            'float_shares': float_shares,
            'atr': atr,
            'avg_daily_volume': avg_volume,
            'timestamp': datetime.now().isoformat()
        }
        
        # Cache for session
        _scanner_cache.set_fundamental(ticker, fundamentals)
        
        return fundamentals
    
    except Exception as e:
        print(f"[PRO-SCAN] Error fetching fundamentals for {ticker}: {e}")
        return _get_default_fundamentals(ticker)


def _calculate_atr_from_bars(ticker: str, period: int = 14) -> float:
    """
    Calculate ATR from recent bars if not available from API.
    
    ATR = Average of True Range over N periods
    True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
    """
    if not WS_AVAILABLE:
        return 0.0
    
    try:
        # Get last 20 daily bars
        start_date = datetime.now() - timedelta(days=30)
        bars = data_manager.get_bars(ticker, timeframe='1d', start_date=start_date, limit=20)
        
        if not bars or len(bars) < period:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(bars)):
            curr_bar = bars[i]
            prev_bar = bars[i-1]
            
            high = curr_bar['high']
            low = curr_bar['low']
            prev_close = prev_bar['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if not true_ranges:
            return 0.0
        
        atr = statistics.mean(true_ranges[-period:])
        return round(atr, 2)
    
    except Exception as e:
        return 0.0


def _get_average_volume_from_bars(ticker: str, period: int = 20) -> int:
    """Calculate average volume from recent bars."""
    if not WS_AVAILABLE:
        return 0
    
    try:
        start_date = datetime.now() - timedelta(days=30)
        bars = data_manager.get_bars(ticker, timeframe='1d', start_date=start_date, limit=period)
        
        if not bars:
            return 0
        
        volumes = [bar['volume'] for bar in bars if bar.get('volume', 0) > 0]
        
        if not volumes:
            return 0
        
        return int(statistics.mean(volumes))
    
    except Exception:
        return 0


def _get_default_fundamentals(ticker: str) -> Dict:
    """Return default fundamentals when API fails."""
    # Conservative defaults for unknown stocks
    return {
        'ticker': ticker,
        'market_cap': 1_000_000_000,  # Assume $1B
        'float_shares': 50_000_000,    # Assume 50M
        'atr': 1.0,                    # Assume $1 ATR
        'avg_daily_volume': 1_000_000, # Assume 1M volume
        'timestamp': datetime.now().isoformat()
    }


# ══════════════════════════════════════════════════════════════════════════════
# REAL-TIME DATA FETCHING (PRICE, VOLUME)
# ══════════════════════════════════════════════════════════════════════════════

def get_current_bar_data(ticker: str) -> Optional[Dict]:
    """Get current bar from WebSocket or database."""
    if not WS_AVAILABLE:
        return None
    
    try:
        # Try WebSocket first
        bar = get_current_bar(ticker)
        if bar:
            return {
                'current_price': bar['close'],
                'volume': bar['volume'],
                'timestamp': bar.get('timestamp', datetime.now().isoformat())
            }
    except Exception:
        pass
    
    # Fallback to database
    try:
        bars = data_manager.get_bars_from_memory(ticker, limit=1)
        if bars:
            bar = bars[-1]
            return {
                'current_price': bar['close'],
                'volume': bar['volume'],
                'timestamp': bar.get('timestamp', datetime.now().isoformat())
            }
    except Exception:
        pass
    
    return None


def get_prev_close(ticker: str) -> Optional[float]:
    """Get previous day close price."""
    global _prev_close_cache
    
    # Check cache
    if ticker in _prev_close_cache:
        return _prev_close_cache[ticker]
    
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
            prev_close = prev_day_bars[-1]['close']
            _prev_close_cache[ticker] = prev_close
            return prev_close
    except Exception:
        pass
    
    # Fallback to EODHD API
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
        if response.status_code == 200:
            data = response.json()
            if data and len(data) >= 1:
                prev_close = data[-1].get('adjusted_close', 0)
                _prev_close_cache[ticker] = prev_close
                return prev_close
    except Exception:
        pass
    
    return None


# ══════════════════════════════════════════════════════════════════════════════
# PROFESSIONAL SCANNER (MAIN FUNCTION)
# ══════════════════════════════════════════════════════════════════════════════

def run_professional_screener(
    candidate_tickers: List[str],
    min_composite_score: float = 50.0,
    use_cache: bool = True
) -> List[Dict]:
    """
    Run professional pre-market screener on candidate tickers.
    
    Returns list of scored tickers matching format:
      {
          'ticker': str,
          'composite_score': float,
          'gap_pct': float,
          'volume': int,
          'rvol': float,
          'atr_normalized_gap': float,
          'direction': str ("bull"/"bear"),
          ...
      }
    
    Compatible with watchlist_funnel.py expectations.
    """
    print(f"[PRO-SCAN] Running professional screener on {len(candidate_tickers)} tickers...")
    
    scored_tickers = []
    cache_hits = 0
    new_scores = 0
    api_calls_fundamentals = 0
    
    # Get current time percentage (for RVOL calculation)
    time_pct = pro_scanner.get_premarket_time_percentage()
    
    for ticker in candidate_tickers:
        # Check cache first
        if use_cache:
            cached = _scanner_cache.get_scan(ticker)
            if cached and cached.get('composite_score', 0) >= min_composite_score:
                scored_tickers.append(cached)
                cache_hits += 1
                continue
        
        # Get real-time bar data
        bar_data = get_current_bar_data(ticker)
        if not bar_data:
            continue
        
        # Get previous close
        prev_close = get_prev_close(ticker)
        if not prev_close or prev_close == 0:
            continue
        
        # Get fundamental data
        fundamentals = fetch_fundamental_data(ticker)
        api_calls_fundamentals += 1 if not _scanner_cache.get_fundamental(ticker) else 0
        
        # Run professional 3-tier scoring
        result = pro_scanner.calculate_professional_score(
            ticker=ticker,
            current_price=bar_data['current_price'],
            prev_close=prev_close,
            current_volume=bar_data['volume'],
            avg_daily_volume=fundamentals['avg_daily_volume'],
            market_cap=fundamentals['market_cap'],
            atr=fundamentals['atr'],
            float_shares=fundamentals['float_shares'],
            time_pct=time_pct
        )
        
        # Convert to watchlist_funnel compatible format
        if result['composite_score'] >= min_composite_score:
            formatted_result = {
                'ticker': ticker,
                'composite_score': result['composite_score'],
                'gap_pct': result['tier_metrics']['gap']['gap_pct'],
                'gap_abs': result['tier_metrics']['gap']['gap_abs'],
                'volume': result['tier_metrics']['volume']['current_volume'],
                'rvol': result['tier_metrics']['volume']['rvol'],
                'dollar_volume': result['tier_metrics']['volume']['dollar_volume'],
                'atr_normalized_gap': result['tier_metrics']['gap']['atr_normalized'],
                'direction': result['tier_metrics']['gap']['direction'],
                'bias': result['tier_metrics']['gap']['direction'],  # Alias for compatibility
                'current_price': bar_data['current_price'],
                'market_cap': fundamentals['market_cap'],
                'float_millions': fundamentals['float_shares'] / 1_000_000 if fundamentals['float_shares'] else None,
                'pass_threshold': result['pass_threshold'],
                'tier_scores': result['tier_scores'],
                'timestamp': datetime.now().isoformat()
            }
            
            scored_tickers.append(formatted_result)
            new_scores += 1
            
            # Cache result
            if use_cache:
                _scanner_cache.set_scan(ticker, formatted_result)
    
    # Sort by composite score
    scored_tickers.sort(key=lambda x: x['composite_score'], reverse=True)
    
    print(f"[PRO-SCAN] ✅ {len(scored_tickers)} tickers passed min score {min_composite_score}")
    print(f"[PRO-SCAN] 📊 New scores: {new_scores} | Cache hits: {cache_hits}")
    if api_calls_fundamentals > 0:
        print(f"[PRO-SCAN] ⚠️  {api_calls_fundamentals} fundamental API calls")
    
    return scored_tickers


# ══════════════════════════════════════════════════════════════════════════════
# BACKWARDS COMPATIBILITY (Drop-in for momentum_screener_optimized.py)
# ══════════════════════════════════════════════════════════════════════════════

def run_momentum_screener(
    candidate_tickers: List[str],
    min_composite_score: float = 50.0,
    use_cache: bool = True
) -> List[Dict]:
    """Alias for backwards compatibility with watchlist_funnel.py."""
    return run_professional_screener(candidate_tickers, min_composite_score, use_cache)


def get_top_n_movers(scored_tickers: List[Dict], n: int = 10) -> List[str]:
    """Extract top N ticker symbols."""
    return [t['ticker'] for t in scored_tickers[:n]]


def print_momentum_summary(scored_tickers: List[Dict], top_n: int = 10):
    """Print formatted results (delegates to professional printer)."""
    pro_scanner.print_professional_summary(scored_tickers, top_n)


def get_cache_stats() -> Dict:
    """Return cache statistics."""
    return _scanner_cache.get_stats()


def clear_momentum_cache():
    """Clear all caches."""
    global _prev_close_cache
    _scanner_cache.clear()
    _prev_close_cache = {}
    print("[PRO-SCAN] Cache cleared")


if __name__ == "__main__":
    # Test professional screener integration
    test_tickers = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "META", "GOOGL"]
    
    print("Testing Professional Scanner Integration...\n")
    
    results = run_professional_screener(test_tickers, min_composite_score=40)
    pro_scanner.print_professional_summary(results, top_n=5)
    
    stats = get_cache_stats()
    print(f"\n📊 Cache Stats: {stats}")
