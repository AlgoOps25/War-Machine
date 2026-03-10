# Original content preserved - fixing fundamentals fetch
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

PHASE 1.18 (MAR 10, 2026) - Session lock:
  - ScannerCache.lock_until_eod(): sets TTL to 23h so per-ticker scan cache
    never expires mid-session after market open
  - lock_scanner_cache(): module-level helper called by watchlist_funnel
    at first live build to prevent mid-day re-scoring
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import statistics
import requests

from utils import config

# Import existing modules (optional - for optimization only)
try:
    from app.data.ws_feed import get_current_bar
    from app.data.data_manager import data_manager
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("[PREMARKET] WS/DB modules not available - using REST API only")

# TASK 12: Import v2 modules
try:
    from app.screening.gap_analyzer import analyze_gap
    from app.screening.news_catalyst import detect_catalyst
    from app.screening.sector_rotation import get_hot_sectors, is_hot_sector_stock
    V2_ENABLED = True
    print("[PREMARKET] v2 modules loaded (gap analyzer, news catalyst, sector rotation)")
except ImportError as e:
    V2_ENABLED = False
    print(f"[PREMARKET] v2 modules not available: {e}")


# ===============================================================================
# CACHING LAYER
# ===============================================================================

class ScannerCache:
    """Caches professional scan results and fundamental data."""

    def __init__(self, ttl_seconds: int = 180):  # 3-minute TTL pre-market
        self.scan_cache: Dict[str, Dict] = {}
        self.fundamental_cache: Dict[str, Dict] = {}  # ATR, float, market cap
        self.ttl_seconds = ttl_seconds
        self._locked = False  # PHASE 1.18: session lock flag

    def lock_until_eod(self):
        """
        PHASE 1.18: Lock the cache for the rest of the session.
        Sets TTL to 23 hours so no per-ticker scan entry ever expires
        during market hours. Called once at market open (9:30 ET).
        """
        self._locked = True
        self.ttl_seconds = 23 * 3600  # effectively EOD
        print(f"[PREMARKET] Scanner cache LOCKED until EOD — TTL extended to {self.ttl_seconds}s")

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
        self._locked = False
        self.ttl_seconds = 180

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
            'ttl_seconds': self.ttl_seconds,
            'locked': self._locked  # PHASE 1.18
        }


# Global cache instance
_scanner_cache = ScannerCache(ttl_seconds=180)


# ===============================================================================
# TIER 1: VOLUME SPIKE DETECTION
# ===============================================================================

def calculate_relative_volume(
    current_volume: int,
    avg_daily_volume: int,
    time_elapsed_pct: float = 0.25  # 25% of day (pre-market)
) -> float:
    """
    Calculate RVOL (Relative Volume) - Professional standard metric.

    Formula: (Current Volume / Expected Volume at this time)
    Expected Volume = Avg Daily Volume x Time Elapsed %

    Example: If 9:00 AM (25% of trading day), and stock normally does 1M volume/day:
      Expected volume = 1M x 0.25 = 250K
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


# ===============================================================================
# FUNDAMENTAL DATA FETCHING (ATR, MARKET CAP, FLOAT)
# ===============================================================================

def fetch_fundamental_data(ticker: str) -> Dict:
    """
    Fetch fundamental data needed for professional scoring.

    Data needed:
      - ATR (Average True Range) - 14-day calculated from EOD data
      - Market Cap
      - Float (shares outstanding)
      - Average Daily Volume (20-day calculated from EOD data)
      - Previous close (for gap calculation)

    Source: EODHD EOD API (historical daily bars)
    Cached for entire session (slow-changing data)
    """
    # Check cache first
    cached = _scanner_cache.get_fundamental(ticker)
    if cached:
        return cached

    try:
        # Fetch last 30 days of EOD data to calculate ADV and ATR
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        url = f"https://eodhd.com/api/eod/{ticker}.US"
        params = {
            'api_token': config.EODHD_API_KEY,
            'period': 'd',
            'from': start_date.strftime('%Y-%m-%d'),
            'to': end_date.strftime('%Y-%m-%d'),
            'fmt': 'json'
        }

        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            print(f"[PREMARKET] {ticker}: EOD API HTTP {response.status_code}")
            return _get_default_fundamentals(ticker)

        eod_data = response.json()
        if not eod_data or len(eod_data) < 14:
            print(f"[PREMARKET] {ticker}: Insufficient EOD data ({len(eod_data)} bars)")
            return _get_default_fundamentals(ticker)
        
        # Calculate 20-day ADV
        volumes = [bar['volume'] for bar in eod_data[-20:]]
        avg_volume = int(statistics.mean(volumes)) if volumes else 0
        
        # Calculate 14-day ATR
        atr = _calculate_atr_from_eod(eod_data[-14:])
        
        # Get previous close (most recent bar)
        prev_close = eod_data[-1]['close'] if eod_data else 0
        
        # Try to get market cap from fundamentals API (lightweight call)
        market_cap = 0
        float_shares = 0
        try:
            fund_url = f"https://eodhd.com/api/fundamentals/{ticker}.US?api_token={config.EODHD_API_KEY}&fmt=json"
            fund_resp = requests.get(fund_url, timeout=5)
            if fund_resp.status_code == 200:
                fund_data = fund_resp.json()
                highlights = fund_data.get('Highlights', {})
                shares_stats = fund_data.get('SharesStats', {})
                market_cap = highlights.get('MarketCapitalization', 0) or 0
                float_shares = shares_stats.get('SharesFloat', 0) or shares_stats.get('SharesOutstanding', 0) or 0
        except:
            pass

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
        print(f"[PREMARKET] {ticker}: Fundamentals - ADV={avg_volume:,}, ATR={atr:.2f}")
        return fundamentals

    except Exception as e:
        print(f"[PREMARKET] Error fetching fundamentals for {ticker}: {e}")
        return _get_default_fundamentals(ticker)


def _calculate_atr_from_eod(bars: List[Dict], periods: int = 14) -> float:
    """
    Calculate ATR from EOD bars.
    
    Args:
        bars: List of daily bars with 'high', 'low', 'close'
        periods: Number of periods for ATR (default 14)
    
    Returns:
        ATR value
    """
    if not bars or len(bars) < 2:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1]['close']
        curr_high = bars[i]['high']
        curr_low = bars[i]['low']
        tr = max(
            curr_high - curr_low,
            abs(curr_high - prev_close),
            abs(curr_low - prev_close)
        )
        true_ranges.append(tr)
    
    return statistics.mean(true_ranges) if true_ranges else 0.0


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


# ===============================================================================
# PUBLIC API
# ===============================================================================

def scan_ticker(ticker: str) -> Optional[Dict]:
    """
    Scan a single ticker with professional 3-tier scoring + v2 enhancements.
    Returns scan result or None if ticker doesn't qualify.
    Compatible with watchlist_funnel.py.
    
    TASK 12: Now includes gap quality, news catalyst, and sector rotation.

    Bar resolution order:
      1. WS get_current_bar()          - real-time, preferred (if available)
      2. data_manager session bars[-1] - DB fallback for subscribed tickers
      3. EODHD real-time REST quote    - fallback for unsubscribed tickers (PRIMARY for screener)
    """
    print(f"[PREMARKET] Scanning {ticker}...")
    
    cached = _scanner_cache.get_scan(ticker)
    if cached:
        print(f"[PREMARKET] {ticker}: Using cached scan (score={cached.get('composite_score', 0):.1f})")
        return cached

    fundamentals = fetch_fundamental_data(ticker)
    print(f"[PREMARKET] {ticker}: Fundamentals - ADV={fundamentals['avg_daily_volume']:,}, ATR={fundamentals['atr']:.2f}")

    current_bar = None
    
    # Try WS first (optimization for subscribed tickers)
    if WS_AVAILABLE:
        try:
            current_bar = get_current_bar(ticker)
            if current_bar:
                print(f"[PREMARKET] {ticker}: WS bar found")
        except Exception as e:
            print(f"[PREMARKET] {ticker}: WS lookup error: {e}")
            pass

    # Fallback 1: DB session bars (for subscribed tickers)
    if not current_bar and WS_AVAILABLE:
        try:
            bars = data_manager.get_today_session_bars(ticker)
            if bars:
                current_bar = bars[-1]
                print(f"[PREMARKET] {ticker}: DB bar used")
        except Exception as e:
            print(f"[PREMARKET] {ticker}: DB lookup error: {e}")
            pass

    # Fallback 2: EODHD REST API (PRIMARY for unsubscribed screener tickers)
    if not current_bar:
        try:
            rt_url = (
                f"https://eodhd.com/api/real-time/{ticker}.US"
                f"?api_token={config.EODHD_API_KEY}&fmt=json"
            )
            rt_resp = requests.get(rt_url, timeout=5)
            if rt_resp.status_code == 200:
                rt = rt_resp.json()
                current_bar = {
                    'close':  rt.get('close') or rt.get('previousClose', 0),
                    'volume': rt.get('volume', 0)
                }
                print(f"[PREMARKET] {ticker}: REST bar used")
            else:
                print(f"[PREMARKET] {ticker}: REST API failed (HTTP {rt_resp.status_code})")
        except Exception as e:
            print(f"[PREMARKET] {ticker}: REST API error: {e}")
            pass

    if not current_bar:
        print(f"[PREMARKET] {ticker}: No data available (all sources failed)")
        return None

    price  = current_bar.get('close', 0)
    volume = current_bar.get('volume', 0)
    
    print(f"[PREMARKET] {ticker}: Bar resolved - price={price:.2f}, volume={volume:,}")

    # Tier 1: Volume score (60% weight)
    volume_score, volume_metrics = score_volume_quality(
        volume,
        fundamentals['avg_daily_volume'],
        price
    )
    
    print(f"[PREMARKET] {ticker}: Volume score={volume_score:.1f}, RVOL={volume_metrics['rvol']:.2f}x")
    
    # TASK 12: Tier 2 - Gap quality (25% weight)
    gap_score = 0
    gap_data = None
    if V2_ENABLED and fundamentals['prev_close'] > 0:
        try:
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
            print(f"[PREMARKET] {ticker}: Gap analysis error: {e}")
    
    # TASK 12: Tier 3 - News catalyst (15% weight)
    catalyst_score = 0
    catalyst_data = None
    if V2_ENABLED:
        try:
            catalyst = detect_catalyst(ticker)
            if catalyst:
                catalyst_score = min(100, catalyst.weight * 4)
                catalyst_data = catalyst.to_dict()
                print(f"[PREMARKET] {ticker}: Catalyst detected - {catalyst.catalyst_type} (weight={catalyst.weight}, score={catalyst_score:.1f})")
            else:
                print(f"[PREMARKET] {ticker}: No catalyst detected")
        except Exception as e:
            print(f"[PREMARKET] {ticker}: Catalyst detection error: {e}")
    
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
            print(f"[PREMARKET] {ticker}: Sector check error: {e}")
    
    # Composite score (weighted)
    composite_score = (
        volume_score * 0.60 +
        gap_score * 0.25 +
        catalyst_score * 0.15 +
        sector_bonus
    )
    
    print(f"[PREMARKET] {ticker}: Composite score={composite_score:.1f} (vol={volume_score:.1f}, gap={gap_score:.1f}, catalyst={catalyst_score:.1f}, sector={sector_bonus:.1f})")

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
    print(f"[PREMARKET] Scanning {len(tickers)} tickers with min_score={min_score}...")
    results = []

    for ticker in tickers:
        try:
            scan_result = scan_ticker(ticker)
            if scan_result:
                if scan_result['composite_score'] >= min_score:
                    results.append(scan_result)
                    print(f"[PREMARKET] {ticker}: PASS score={scan_result['composite_score']:.1f} >= {min_score}")
                else:
                    print(f"[PREMARKET] {ticker}: FILTERED score={scan_result['composite_score']:.1f} < {min_score}")
            else:
                print(f"[PREMARKET] {ticker}: SKIPPED (scan returned None)")
        except Exception as e:
            print(f"[PREMARKET] Error scanning {ticker}: {e}")
            continue

    results.sort(key=lambda x: x['composite_score'], reverse=True)
    print(f"[PREMARKET] Scan complete: {len(results)}/{len(tickers)} tickers passed")
    return results


def get_cache_stats() -> Dict:
    """Return cache statistics for monitoring."""
    return _scanner_cache.get_stats()


def clear_cache():
    """Clear all scanner caches."""
    _scanner_cache.clear()
    print("[PREMARKET] All caches cleared")


def lock_scanner_cache():
    """
    PHASE 1.18: Lock the scanner cache for the rest of the session.
    Called by watchlist_funnel._build_live_watchlist() at market open.
    Extends per-ticker TTL to ~23h so entries never expire mid-day.
    """
    _scanner_cache.lock_until_eod()


# ===============================================================================
# COMPATIBILITY STUBS (for watchlist_funnel.py)
# ===============================================================================

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
    print(f"[PREMARKET] run_momentum_screener() called with {len(tickers)} tickers, min_score={min_composite_score}")
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
    
    if V2_ENABLED:
        try:
            hot_sectors = get_hot_sectors()
            if hot_sectors:
                print("\n" + "="*80)
                print("HOT SECTORS")
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
        gap_data = ticker_data.get('gap_data', {})
        gap_str = f"{gap_data.get('size_pct', 0):+.1f}%" if gap_data else "N/A"
        catalyst_data = ticker_data.get('catalyst_data', {})
        if catalyst_data:
            catalyst_str = catalyst_data.get('type', 'N/A')[:10]
        else:
            catalyst_str = "-"
        print(f"{rank:<6} {ticker:<8} {score:<8.1f} {rvol:<8.2f} {gap_str:<8} {catalyst_str:<12} ${price:<9.2f}")
    
    print(f"{'='*80}\n")
