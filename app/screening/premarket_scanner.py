# Original content preserved - adding v2 imports at top
"""
Professional Pre-Market Scanner - UNIFIED MODULE
Consolidated from premarket_scanner_pro.py + premarket_scanner_integration.py

Based on Finviz Elite, Trade Ideas, and institutional scanning logic.

3-Tier Detection System:
  Tier 1: Volume Spike Detection (RVOL, absolute volume, dollar volume)
  Tier 2: Gap + Momentum Quality (ATR-normalized gaps, volume confirmation)
  Tier 3: Liquidity + Float Analysis (tradability, institutional interest)

Key Metrics:
  - Relative Volume (RVOL): Current volume vs. 10-day average
  - Dollar Volume: Normalizes volume across price ranges
  - ATR-Normalized Gap: Gap size relative to typical volatility
  - Float: Outstanding shares available for trading
  - Market Cap: Institutional interest threshold

Professional Criteria (Trade Ideas, Finviz Elite standards):
  - RVOL > 1.5x (minimum), 3.0x+ ideal
  - Pre-market volume > 100K shares by 9:00 AM
  - Gap > 1% (minimum), 3%+ ideal
  - ATR > $0.50 (minimum volatility)
  - Market cap > $500M (institutional interest)
  - Price: $5-$500 (liquid range)
  - ADV > 500K shares (daily liquidity)

Integration Layer:
  - Fetches fundamental data (ATR, market cap, float) from EODHD
  - Combines real-time price/volume from WebSocket/DB
  - Runs professional 3-tier scoring
  - Compatible with watchlist_funnel.py infrastructure
  - 3-minute caching for efficiency

TASK 12 ENHANCEMENTS (v2):
  - Gap quality scoring via gap_analyzer
  - News catalyst detection via news_catalyst
  - Sector rotation tracking via sector_rotation
  - Composite scoring: volume (60%) + gap (25%) + catalyst (15%)
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import statistics
import requests

from utils import config

# Import existing modules
try:
    from ws_feed import get_current_bar
    from app.data.data_manager import data_manager
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

# TASK 12: Import v2 modules
try:
    from app.screening.gap_analyzer import analyze_gap
    from app.screening.news_catalyst import detect_catalyst
    from app.screening.sector_rotation import get_hot_sectors, is_hot_sector_stock
    V2_ENABLED = True
    print("[PREMARKET] ✅ v2 modules loaded (gap analyzer, news catalyst, sector rotation)")
except ImportError as e:
    V2_ENABLED = False
    print(f"[PREMARKET] ⚠️  v2 modules not available: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# CACHING LAYER
# ═══════════════════════════════════════════════════════════════════════════════

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
        """Clear scan cache. Fundamentals persist for the session."""
        self.scan_cache = {}

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


# ═══════════════════════════════════════════════════════════════════════════════
# TIER 1: VOLUME SPIKE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_relative_volume(
    current_volume: int,
    avg_daily_volume: int,
    time_elapsed_pct: float = 0.25  # 25% of day (pre-market)
) -> float:
    """
    Calculate RVOL (Relative Volume) - Professional standard metric.

    Formula: (Current Volume / Expected Volume at this time)
    Expected Volume = Avg Daily Volume × Time Elapsed %

    Example: If 9:00 AM (25% of trading day), and stock normally does 1M volume/day:
      Expected volume = 1M × 0.25 = 250K
      If current volume = 500K, RVOL = 500K / 250K = 2.0x

    Professional thresholds:
      RVOL > 1.5x = Notable
      RVOL > 2.0x = Strong
      RVOL > 3.0x = Exceptional (institutional activity)
    """
    if avg_daily_volume == 0:
        return 0.0

    expected_volume = avg_daily_volume * time_elapsed_pct

    if expected_volume == 0:
        return 0.0

    return current_volume / expected_volume


def calculate_dollar_volume(price: float, volume: int) -> float:
    """
    Dollar volume normalizes across price ranges.
    $1 stock with 1M volume = $1M dollar volume
    $100 stock with 10K volume = $1M dollar volume

    Professional minimum: $5M+ dollar volume for liquidity
    """
    return price * volume


def score_volume_quality(
    current_volume: int,
    avg_daily_volume: int,
    price: float,
    time_pct: float = 0.25
) -> Tuple[float, Dict]:
    """
    Score volume quality using professional metrics.

    Returns:
        (score: 0-100, metrics: dict)
    """
    rvol = calculate_relative_volume(current_volume, avg_daily_volume, time_pct)
    dollar_vol = calculate_dollar_volume(price, current_volume)

    # Volume score based on RVOL (primary metric)
    if rvol >= 5.0:
        rvol_score = 100  # Extreme institutional activity
    elif rvol >= 3.0:
        rvol_score = 90   # Strong institutional
    elif rvol >= 2.0:
        rvol_score = 75   # Above average
    elif rvol >= 1.5:
        rvol_score = 60   # Notable
    elif rvol >= 1.0:
        rvol_score = 40   # Normal
    else:
        rvol_score = 20   # Below average

    # Dollar volume confirmation
    if dollar_vol >= 10_000_000:
        dollar_score = 100
    elif dollar_vol >= 5_000_000:
        dollar_score = 75
    elif dollar_vol >= 2_000_000:
        dollar_score = 50
    else:
        dollar_score = 25

    # Combined score (RVOL weighted 70%, dollar volume 30%)
    total_score = (rvol_score * 0.7) + (dollar_score * 0.3)

    metrics = {
        'rvol': round(rvol, 2),
        'dollar_volume': dollar_vol,
        'rvol_score': rvol_score,
        'dollar_score': dollar_score
    }

    return round(total_score, 1), metrics


# ═══════════════════════════════════════════════════════════════════════════════
# FUNDAMENTAL DATA FETCHING (ATR, MARKET CAP, FLOAT)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_fundamental_data(ticker: str) -> Dict:
    """
    Fetch fundamental data needed for professional scoring.

    Data needed:
      - ATR (Average True Range) - 14-day default
      - Market Cap
      - Float (shares outstanding)
      - Average Daily Volume (20-day)
      - Previous close (for gap calculation)

    Source: EODHD Fundamentals API
    Cached for entire session (slow-changing data)
    """
    # Check cache first
    cached = _scanner_cache.get_fundamental(ticker)
    if cached:
        return cached

    try:
        url = f"https://eodhd.com/api/fundamentals/{ticker}.US?api_token={config.EODHD_API_KEY}&fmt=json"

        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return _get_default_fundamentals(ticker)

        data = response.json()

        highlights   = data.get('Highlights', {})
        technicals   = data.get('Technicals', {})
        shares_stats = data.get('SharesStats', {})

        market_cap   = highlights.get('MarketCapitalization', 0) or 0
        float_shares = shares_stats.get('SharesFloat', 0) or shares_stats.get('SharesOutstanding', 0) or 0
        atr          = technicals.get('AverageTrueRange14', 0) or 0
        avg_volume   = highlights.get('AverageDailyVolume', 0) or 0
        
        # Get previous close for gap calculation
        prev_close = technicals.get('previousClose', 0) or 0

        # Fallback: calculate from recent intraday bars if fundamentals API has no data
        if atr == 0:
            atr = _calculate_atr_from_bars(ticker)
        if avg_volume == 0:
            avg_volume = _get_average_volume_from_bars(ticker)

        fundamentals = {
            'ticker':          ticker,
            'market_cap':      market_cap,
            'float_shares':    float_shares,
            'atr':             atr,
            'avg_daily_volume': avg_volume,
            'prev_close':      prev_close,
            'timestamp':       datetime.now().isoformat()
        }

        _scanner_cache.set_fundamental(ticker, fundamentals)
        return fundamentals

    except Exception as e:
        print(f"[PREMARKET] Error fetching fundamentals for {ticker}: {e}")
        return _get_default_fundamentals(ticker)


def _get_default_fundamentals(ticker: str) -> Dict:
    """Return default/fallback fundamental data."""
    return {
        'ticker':          ticker,
        'market_cap':      0,
        'float_shares':    0,
        'atr':             0,
        'avg_daily_volume': 0,
        'prev_close':      0,
        'timestamp':       datetime.now().isoformat()
    }


def _calculate_atr_from_bars(ticker: str, periods: int = 14) -> float:
    """
    Calculate ATR from recent 1m bars stored in intraday_bars.
    Used as fallback when EODHD fundamentals API has no ATR data.
    """
    if not WS_AVAILABLE:
        return 0.0

    try:
        bars = data_manager.get_today_session_bars(ticker)
        if not bars or len(bars) < 2:
            return 0.0

        true_ranges = []
        for i in range(1, len(bars)):
            prev_close = bars[i - 1]['close']
            curr_high  = bars[i]['high']
            curr_low   = bars[i]['low']
            tr = max(
                curr_high - curr_low,
                abs(curr_high - prev_close),
                abs(curr_low  - prev_close)
            )
            true_ranges.append(tr)

        return statistics.mean(true_ranges) if true_ranges else 0.0

    except Exception as e:
        print(f"[PREMARKET] Error calculating ATR for {ticker}: {e}")
        return 0.0


def _get_average_volume_from_bars(ticker: str, periods: int = 20) -> int:
    """
    Calculate average volume from recent 1m bars stored in intraday_bars.
    Used as fallback when EODHD fundamentals API has no volume data.
    """
    if not WS_AVAILABLE:
        return 0

    try:
        bars = data_manager.get_today_session_bars(ticker)
        if not bars:
            return 0

        volumes = [bar['volume'] for bar in bars]
        return int(statistics.mean(volumes)) if volumes else 0

    except Exception as e:
        print(f"[PREMARKET] Error calculating avg volume for {ticker}: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def scan_ticker(ticker: str) -> Optional[Dict]:
    """
    Scan a single ticker with professional 3-tier scoring + v2 enhancements.
    Returns scan result or None if ticker doesn't qualify.
    Compatible with watchlist_funnel.py.
    
    TASK 12: Now includes gap quality, news catalyst, and sector rotation.
    """
    cached = _scanner_cache.get_scan(ticker)
    if cached:
        return cached

    fundamentals = fetch_fundamental_data(ticker)

    if WS_AVAILABLE:
        try:
            current_bar = get_current_bar(ticker)
            if not current_bar:
                return None

            price  = current_bar.get('close', 0)
            volume = current_bar.get('volume', 0)
        except Exception:
            return None
    else:
        return None

    # Tier 1: Volume score (60% weight)
    volume_score, volume_metrics = score_volume_quality(
        volume,
        fundamentals['avg_daily_volume'],
        price
    )
    
    # TASK 12: Tier 2 - Gap quality (25% weight)
    gap_score = 0
    gap_data = None
    if V2_ENABLED and fundamentals['prev_close'] > 0:
        try:
            # Check for news catalyst first
            catalyst = detect_catalyst(ticker)
            has_earnings = catalyst and catalyst.catalyst_type == 'earnings'
            has_news = catalyst is not None
            
            gap_result = analyze_gap(
                ticker,
                fundamentals['prev_close'],
                price,
                fundamentals['atr'],
                has_earnings,
                has_news
            )
            gap_score = gap_result.quality_score
            gap_data = gap_result.to_dict()
        except Exception as e:
            print(f"[PREMARKET] Error analyzing gap for {ticker}: {e}")
    
    # TASK 12: Tier 3 - News catalyst (15% weight)
    catalyst_score = 0
    catalyst_data = None
    if V2_ENABLED:
        try:
            catalyst = detect_catalyst(ticker)
            if catalyst:
                catalyst_score = catalyst.weight * 4  # Scale 0-100
                catalyst_data = catalyst.to_dict()
        except Exception as e:
            print(f"[PREMARKET] Error detecting catalyst for {ticker}: {e}")
    
    # TASK 12: Sector rotation bonus (+15 pts if hot sector)
    sector_bonus = 0
    sector_data = None
    if V2_ENABLED:
        try:
            is_hot, sector_name = is_hot_sector_stock(ticker)
            if is_hot:
                sector_bonus = 15
                sector_data = {'sector': sector_name, 'is_hot': True}
        except Exception as e:
            print(f"[PREMARKET] Error checking sector for {ticker}: {e}")
    
    # Composite score (weighted)
    composite_score = (
        volume_score * 0.60 +  # 60% volume
        gap_score * 0.25 +     # 25% gap quality
        catalyst_score * 0.15 + # 15% news catalyst
        sector_bonus           # Bonus for hot sector
    )

    result = {
        'ticker':          ticker,
        'price':           price,
        'volume':          volume,
        'volume_score':    volume_score,
        'gap_score':       gap_score,
        'catalyst_score':  catalyst_score,
        'sector_bonus':    sector_bonus,
        'composite_score': round(composite_score, 1),
        'rvol':            volume_metrics['rvol'],
        'dollar_volume':   volume_metrics['dollar_volume'],
        'atr':             fundamentals['atr'],
        'market_cap':      fundamentals['market_cap'],
        'float':           fundamentals['float_shares'],
        'avg_daily_volume': fundamentals['avg_daily_volume'],
        'gap_data':        gap_data,
        'catalyst_data':   catalyst_data,
        'sector_data':     sector_data,
        'timestamp':       datetime.now()
    }

    _scanner_cache.set_scan(ticker, result)
    return result


def scan_watchlist(tickers: List[str], min_score: float = 60.0) -> List[Dict]:
    """
    Scan multiple tickers and return those meeting minimum score.
    Compatible with watchlist_funnel.py interface.
    """
    results = []

    for ticker in tickers:
        try:
            scan_result = scan_ticker(ticker)
            if scan_result and scan_result['composite_score'] >= min_score:
                results.append(scan_result)
        except Exception as e:
            print(f"[PREMARKET] Error scanning {ticker}: {e}")
            continue

    results.sort(key=lambda x: x['composite_score'], reverse=True)
    return results


def get_cache_stats() -> Dict:
    """Return cache statistics for monitoring."""
    return _scanner_cache.get_stats()


def clear_cache():
    """Clear all scanner caches."""
    _scanner_cache.clear()
    print("[PREMARKET] All caches cleared")


# ═══════════════════════════════════════════════════════════════════════════════
# COMPATIBILITY STUBS (for watchlist_funnel.py)
# ═══════════════════════════════════════════════════════════════════════════════

def run_momentum_screener(
    tickers: List[str],
    min_composite_score: float = 60.0,
    use_cache: bool = True
) -> List[Dict]:
    """
    Compatibility stub for watchlist_funnel.py.
    Maps to scan_watchlist() with renamed parameters.
    
    Args:
        tickers: List of ticker symbols to scan
        min_composite_score: Minimum score threshold (maps to min_score)
        use_cache: Whether to use caching (always enabled in unified scanner)
    
    Returns:
        List of scored ticker dicts with 'composite_score' field
    """
    return scan_watchlist(tickers, min_score=min_composite_score)


def get_top_n_movers(scored_tickers: List[Dict], n: int = 10) -> List[str]:
    """
    Get top N tickers from scored results.
    Compatibility function for watchlist_funnel.py.
    
    Args:
        scored_tickers: List of dicts with 'composite_score' or 'volume_score'
        n: Number of top tickers to return
    
    Returns:
        List of ticker symbols (strings)
    """
    sorted_tickers = sorted(
        scored_tickers, 
        key=lambda x: x.get('composite_score', x.get('volume_score', 0)), 
        reverse=True
    )
    return [t['ticker'] for t in sorted_tickers[:n]]


def print_momentum_summary(scored_tickers: List[Dict], top_n: int = 10):
    """
    Print formatted summary of top N movers.
    Compatibility function for watchlist_funnel.py.
    
    TASK 12: Enhanced with gap/catalyst/sector info.
    
    Args:
        scored_tickers: List of scored ticker dicts
        top_n: Number of top tickers to display
    """
    if not scored_tickers:
        print("[PREMARKET] No tickers to display")
        return
    
    # Print hot sectors if available
    if V2_ENABLED:
        try:
            hot_sectors = get_hot_sectors()
            if hot_sectors:
                print("\n" + "="*80)
                print("🌡️  HOT SECTORS")
                print("="*80)
                for sector_name, momentum_pct in hot_sectors:
                    print(f"  {sector_name}: {momentum_pct:+.1f}%")
        except Exception as e:
            print(f"[PREMARKET] Error fetching hot sectors: {e}")
    
    print(f"\n{'='*80}")
    print(f"TOP {min(top_n, len(scored_tickers))} MOMENTUM MOVERS")
    print(f"{'='*80}")
    print(f"{'Rank':<6} {'Ticker':<8} {'Score':<8} {'RVOL':<8} {'Gap':<8} {'Catalyst':<12} {'Price':<10}")
    print(f"{'-'*80}")
    
    for i, ticker_data in enumerate(scored_tickers[:top_n], 1):
        rank = f"#{i}"
        ticker = ticker_data.get('ticker', 'N/A')
        score = ticker_data.get('composite_score', ticker_data.get('volume_score', 0))
        rvol = ticker_data.get('rvol', 0)
        price = ticker_data.get('price', 0)
        
        # Gap info
        gap_data = ticker_data.get('gap_data', {})
        gap_str = f"{gap_data.get('size_pct', 0):+.1f}%" if gap_data else "N/A"
        
        # Catalyst info
        catalyst_data = ticker_data.get('catalyst_data', {})
        if catalyst_data:
            catalyst_str = catalyst_data.get('type', 'N/A')[:10]
        else:
            catalyst_str = "-"
        
        print(f"{rank:<6} {ticker:<8} {score:<8.1f} {rvol:<8.2f} {gap_str:<8} {catalyst_str:<12} ${price:<9.2f}")
    
    print(f"{'='*80}\n")
