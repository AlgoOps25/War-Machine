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

PHASE 1.23 (MAR 12, 2026) - RVOL fix:
  - calculate_time_elapsed_pct(): real elapsed market minutes / 390,
    replaces hardcoded time_pct=0.25 assumption.
  - get_intraday_cumulative_volume(): sums all session bars from
    data_manager so RVOL is against full intraday volume, not a
    single 1-min bar snapshot.

PHASE 1.23a (MAR 13, 2026) - REST bar RVOL clamp:
  - REST bars from EODHD real-time API return full prior-day cumulative
    volume, not pre-market volume. This causes extreme artificial RVOL
    (e.g. RF 163x, SSL 309x) which triggers false high-priority signals.
  - RVOL from REST-sourced bars is now clamped to 10x max pre-market.

PHASE 1.24 (MAR 13, 2026):
  - FIX: Removed duplicate fundamentals log in scan_ticker().
    fetch_fundamental_data() already prints it; scan_ticker() was
    printing the same line again immediately after the call.
  - FIX: Early RVOL exit gate added after bar resolution.
    Tickers with RVOL < 0.10x are skipped before running
    gap analysis, news catalyst fetch, and sector rotation —
    saving 3-4 EODHD API calls per dead ticker per premarket run.

PHASE 1.28 (MAR 14, 2026) - Gap zero fix + duplicate catalyst call:
  - FIX: Gap was always 0.0% for REST-sourced bars because both
    `price` and `fundamentals['prev_close']` resolved to the same
    EODHD previousClose value (EODHD real-time `close` = prior close
    pre-market, not a live trade price).
    Solution: REST bar now captures `open` (pre-market indicated price)
    as the gap price, and `previousClose` as the reference close.
    When `open` is unavailable, falls back to `close`. The REST-derived
    prev_close is stored separately as `rest_prev_close` and used in
    gap analysis instead of the fundamentals EOD value, which can lag
    by a day on early-morning fetches.
  - FIX: detect_catalyst() was called twice per ticker — once in Tier 2
    (to derive has_earnings/has_news flags) and again identically in
    Tier 3 for the catalyst score. The Tier 2 result is now reused in
    Tier 3, eliminating one redundant API call per ticker per scan cycle.

PHASE 1.29 (MAR 16, 2026) - Ghost 12.9 score fix:
  - ROOT CAUSE: When fetch_fundamental_data() fails (EODHD HTTP error,
    <14 bars, timeout), _get_default_fundamentals() returns avg_daily_volume=0.
    calculate_relative_volume() with avg_daily_volume=0 returns 0.0, producing
    rvol_score=20, dollar_score=25, volume_score=21.5, then the early-exit
    path fires and returns composite_score = 21.5 * 0.60 = 12.9. This ghost
    score is just above the watchlist_funnel floor, polluting the watchlist
    with tickers that have no real ADV data.
  - FIX: After fundamentals fetch, if avg_daily_volume == 0 (failed fetch),
    return None immediately. scan_watchlist() already handles None gracefully
    by logging SKIPPED and moving on. No ghost scores enter the watchlist.
  - SECONDARY: Also return None when price == 0 (bar resolved but no price),
    which was another silent path to nonsense scores.
"""
from datetime import datetime, timedelta, time as dt_time
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

# Minimum RVOL required before running expensive API calls (gap/news/sector).
# Tickers below this threshold are dead volume and will never make the watchlist.
EARLY_EXIT_RVOL_MIN = 0.10


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
# PHASE 1.23: TIME-ELAPSED + CUMULATIVE VOLUME HELPERS
# ===============================================================================

def calculate_time_elapsed_pct(now: Optional[datetime] = None) -> float:
    """
    Return the fraction of the regular trading session (9:30-16:00 ET)
    that has elapsed as of `now`.

    Pre-market  (<9:30): returns a small value (0.01) so RVOL isn't
                         inflated when very little session volume exists.
    Post-market (>16:00): capped at 1.0 (full day).
    Intraday:   elapsed_minutes / 390.0
    """
    if now is None:
        now = datetime.utcnow()
        now = now.replace(tzinfo=None) - timedelta(hours=4)

    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    total_minutes = 390.0

    if now <= market_open:
        return 0.01
    if now >= market_close:
        return 1.0

    elapsed = (now - market_open).total_seconds() / 60.0
    return max(0.01, min(1.0, elapsed / total_minutes))


def get_intraday_cumulative_volume(ticker: str, single_bar_volume: int) -> int:
    """
    Return cumulative intraday volume by summing all session bars.
    Falls back to single_bar_volume if WS/DB unavailable.
    """
    if not WS_AVAILABLE:
        return single_bar_volume

    try:
        bars = data_manager.get_today_session_bars(ticker)
        if bars and len(bars) > 0:
            cumulative = sum(b.get('volume', 0) for b in bars)
            if cumulative > single_bar_volume:
                return cumulative
    except Exception:
        pass

    return single_bar_volume


# ===============================================================================
# TIER 1: VOLUME SPIKE DETECTION
# ===============================================================================

def calculate_relative_volume(
    current_volume: int,
    avg_daily_volume: int,
    time_elapsed_pct: float = 0.25
) -> float:
    if avg_daily_volume == 0:
        return 0.0
    expected_volume = avg_daily_volume * time_elapsed_pct
    if expected_volume == 0:
        return 0.0
    return current_volume / expected_volume


def calculate_dollar_volume(price: float, volume: int) -> float:
    return price * volume


def score_volume_quality(
    current_volume: int,
    avg_daily_volume: int,
    price: float,
    time_pct: float = 0.25
) -> Tuple[float, Dict]:
    rvol = calculate_relative_volume(current_volume, avg_daily_volume, time_pct)
    dollar_vol = calculate_dollar_volume(price, current_volume)

    if rvol >= 5.0:
        rvol_score = 100
    elif rvol >= 3.0:
        rvol_score = 90
    elif rvol >= 2.0:
        rvol_score = 75
    elif rvol >= 1.5:
        rvol_score = 60
    elif rvol >= 1.0:
        rvol_score = 40
    else:
        rvol_score = 20

    if dollar_vol >= 10_000_000:
        dollar_score = 100
    elif dollar_vol >= 5_000_000:
        dollar_score = 75
    elif dollar_vol >= 2_000_000:
        dollar_score = 50
    else:
        dollar_score = 25

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
    Result is cached for the full session.
    Logs fundamentals exactly once per ticker (cache hits are silent).
    """
    cached = _scanner_cache.get_fundamental(ticker)
    if cached:
        # FIX 1.24: do NOT re-log on cache hit — this was the source of the duplicate
        return cached

    try:
        end_date   = datetime.now()
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

        volumes    = [bar['volume'] for bar in eod_data[-20:]]
        avg_volume = int(statistics.mean(volumes)) if volumes else 0
        atr        = _calculate_atr_from_eod(eod_data[-14:])

        # PHASE 1.28: use eod_data[-1] close as prev_close (yesterday's close)
        prev_close = eod_data[-1]['close'] if eod_data else 0

        market_cap   = 0
        float_shares = 0
        try:
            fund_url  = f"https://eodhd.com/api/fundamentals/{ticker}.US?api_token={config.EODHD_API_KEY}&fmt=json"
            fund_resp = requests.get(fund_url, timeout=5)
            if fund_resp.status_code == 200:
                fund_data    = fund_resp.json()
                highlights   = fund_data.get('Highlights', {})
                shares_stats = fund_data.get('SharesStats', {})
                market_cap   = highlights.get('MarketCapitalization', 0) or 0
                float_shares = shares_stats.get('SharesFloat', 0) or shares_stats.get('SharesOutstanding', 0) or 0
        except Exception:
            pass

        fundamentals = {
            'ticker':           ticker,
            'market_cap':       market_cap,
            'float_shares':     float_shares,
            'atr':              atr,
            'avg_daily_volume': avg_volume,
            'prev_close':       prev_close,
            'timestamp':        datetime.now().isoformat()
        }

        _scanner_cache.set_fundamental(ticker, fundamentals)
        # Log once here — scan_ticker() must NOT log this again
        print(f"[PREMARKET] {ticker}: Fundamentals - ADV={avg_volume:,}, ATR={atr:.2f}, prev_close={prev_close:.2f}")
        return fundamentals

    except Exception as e:
        print(f"[PREMARKET] Error fetching fundamentals for {ticker}: {e}")
        return _get_default_fundamentals(ticker)


def _calculate_atr_from_eod(bars: List[Dict], periods: int = 14) -> float:
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


def _get_default_fundamentals(ticker: str) -> Dict:
    return {
        'ticker':           ticker,
        'market_cap':       0,
        'float_shares':     0,
        'atr':              0,
        'avg_daily_volume': 0,  # sentinel — scan_ticker() treats 0 as failed fetch
        'prev_close':       0,
        'timestamp':        datetime.now().isoformat()
    }


def _calculate_atr_from_bars(ticker: str, periods: int = 14) -> float:
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

# PHASE 1.23a: Max RVOL for REST-sourced bars pre-market.
REST_BAR_RVOL_MAX = 10.0


def scan_ticker(ticker: str) -> Optional[Dict]:
    """
    Scan a single ticker with professional 3-tier scoring + v2 enhancements.

    PHASE 1.24 changes:
      - Duplicate fundamentals log removed (fetch_fundamental_data() logs once).
      - Early RVOL exit: tickers with RVOL < EARLY_EXIT_RVOL_MIN skip the
        expensive gap/news/sector API chain entirely.

    PHASE 1.28 changes:
      - REST bar now captures `open` as the pre-market price (gap price) and
        `previousClose` as the gap reference.
      - rest_prev_close stored separately; used in gap analysis when available.
      - detect_catalyst() result from Tier 2 reused in Tier 3.

    PHASE 1.29 changes:
      - FIX #8: Return None immediately when avg_daily_volume == 0 (failed
        fundamentals fetch). Previously this produced a deterministic ghost
        score of 12.9 (rvol=0 → rvol_score=20 → volume_score=21.5 →
        composite=21.5*0.60=12.9) which leaked into the watchlist.
      - FIX #8b: Return None when price == 0 (bar resolved but no price data).
    """
    print(f"[PREMARKET] Scanning {ticker}...")

    cached = _scanner_cache.get_scan(ticker)
    if cached:
        print(f"[PREMARKET] {ticker}: Using cached scan (score={cached.get('composite_score', 0):.1f})")
        return cached

    # fetch_fundamental_data() logs once on first fetch; silent on cache hit
    fundamentals = fetch_fundamental_data(ticker)

    # ── PHASE 1.29: FIX #8 — bail out if fundamentals fetch failed ────────────
    # avg_daily_volume=0 is the sentinel from _get_default_fundamentals().
    # Without ADV we cannot compute a meaningful RVOL, so any score would be
    # fabricated. Return None so scan_watchlist() logs SKIPPED and moves on.
    if fundamentals['avg_daily_volume'] == 0:
        print(
            f"[PREMARKET] {ticker}: SKIPPED — fundamentals fetch failed "
            f"(ADV=0, no EOD data). Returning None to avoid ghost score."
        )
        return None

    current_bar     = None
    bar_source      = None
    rest_prev_close = None  # PHASE 1.28: captured from REST response

    if WS_AVAILABLE:
        try:
            current_bar = get_current_bar(ticker)
            if current_bar:
                bar_source = "WS"
        except Exception:
            pass

    if not current_bar and WS_AVAILABLE:
        try:
            bars = data_manager.get_today_session_bars(ticker)
            if bars:
                current_bar = bars[-1]
                bar_source  = "DB"
                print(f"[PREMARKET] {ticker}: DB bar used")
        except Exception:
            pass

    if not current_bar:
        try:
            rt_url  = (
                f"https://eodhd.com/api/real-time/{ticker}.US"
                f"?api_token={config.EODHD_API_KEY}&fmt=json"
            )
            rt_resp = requests.get(rt_url, timeout=5)
            if rt_resp.status_code == 200:
                rt = rt_resp.json()

                # PHASE 1.28: EODHD real-time fields pre-market:
                #   open  = pre-market indicated / last extended-hours price
                #   close = previousClose (prior session close) — NOT a live price
                # Use `open` as the gap price; fall back to `close` only if open absent.
                premarket_price = rt.get('open') or rt.get('close') or rt.get('previousClose', 0)
                rest_prev_close = rt.get('previousClose') or rt.get('close', 0)

                current_bar = {
                    'close':  premarket_price,
                    'volume': rt.get('volume', 0)
                }
                bar_source = "REST"
                print(
                    f"[PREMARKET] {ticker}: REST bar used "
                    f"(open={rt.get('open')}, previousClose={rest_prev_close})"
                )
            else:
                print(f"[PREMARKET] {ticker}: REST API failed (HTTP {rt_resp.status_code})")
        except Exception as e:
            print(f"[PREMARKET] {ticker}: REST API error: {e}")

    if not current_bar:
        print(f"[PREMARKET] {ticker}: No data available (all sources failed)")
        return None

    price          = current_bar.get('close', 0)
    single_bar_vol = current_bar.get('volume', 0)

    # ── PHASE 1.29: FIX #8b — bail out on zero price ─────────────────────────
    if not price or price <= 0:
        print(f"[PREMARKET] {ticker}: SKIPPED — bar resolved but price=0. Returning None.")
        return None

    volume   = get_intraday_cumulative_volume(ticker, single_bar_vol)
    time_pct = calculate_time_elapsed_pct()

    print(f"[PREMARKET] {ticker}: Bar resolved - price={price:.2f}, volume={volume:,} (cumulative), time_pct={time_pct:.2f}")

    # Tier 1: Volume score
    volume_score, volume_metrics = score_volume_quality(
        volume,
        fundamentals['avg_daily_volume'],
        price,
        time_pct=time_pct
    )

    # PHASE 1.23a: Clamp RVOL for REST-sourced bars
    if bar_source == "REST" and volume_metrics['rvol'] > REST_BAR_RVOL_MAX:
        print(
            f"[PREMARKET] {ticker}: REST bar RVOL clamped "
            f"{volume_metrics['rvol']:.1f}x \u2192 {REST_BAR_RVOL_MAX:.1f}x "
            f"(prior-day volume artifact)"
        )
        volume_metrics['rvol'] = REST_BAR_RVOL_MAX
        rvol_score   = 100 if REST_BAR_RVOL_MAX >= 5.0 else 90
        dollar_score = volume_metrics.get('dollar_score', 25)
        volume_score = round((rvol_score * 0.7) + (dollar_score * 0.3), 1)

    print(f"[PREMARKET] {ticker}: Volume score={volume_score:.1f}, RVOL={volume_metrics['rvol']:.2f}x")

    # ──────────────────────────────────────────────────────────────────────────
    # Early RVOL exit gate (FIX 1.24)
    # Note: this path is now only reachable when ADV > 0 (guaranteed above),
    # so any score produced here reflects real volume data, not a ghost.
    # ──────────────────────────────────────────────────────────────────────────
    if volume_metrics['rvol'] < EARLY_EXIT_RVOL_MIN:
        composite_score = volume_score * 0.60
        print(
            f"[PREMARKET] {ticker}: EARLY EXIT — RVOL={volume_metrics['rvol']:.2f}x "
            f"< {EARLY_EXIT_RVOL_MIN}x — skipping gap/news/sector (score={composite_score:.1f})"
        )
        result = {
            'ticker':           ticker,
            'price':            price,
            'volume':           volume,
            'volume_score':     volume_score,
            'gap_score':        0,
            'catalyst_score':   0,
            'sector_bonus':     0,
            'composite_score':  round(composite_score, 1),
            'rvol':             volume_metrics['rvol'],
            'dollar_volume':    volume_metrics['dollar_volume'],
            'atr':              fundamentals['atr'],
            'market_cap':       fundamentals['market_cap'],
            'float':            fundamentals['float_shares'],
            'avg_daily_volume': fundamentals['avg_daily_volume'],
            'gap_data':         None,
            'catalyst_data':    None,
            'sector_data':      None,
            'timestamp':        datetime.now()
        }
        _scanner_cache.set_scan(ticker, result)
        return result

    # PHASE 1.28: determine best prev_close for gap calculation.
    gap_prev_close = rest_prev_close if rest_prev_close and rest_prev_close > 0 \
                     else fundamentals['prev_close']

    # ──────────────────────────────────────────────────────────────────────────
    # Tier 2: Gap quality (25% weight) + catalyst detection (shared with Tier 3)
    # PHASE 1.28: detect_catalyst() called ONCE here; result reused in Tier 3.
    # ──────────────────────────────────────────────────────────────────────────
    gap_score = 0
    gap_data  = None
    catalyst  = None  # shared across Tier 2 + Tier 3

    if V2_ENABLED:
        try:
            catalyst = detect_catalyst(ticker)
        except Exception as e:
            print(f"[PREMARKET] {ticker}: Catalyst detection error: {e}")

    if V2_ENABLED and gap_prev_close > 0:
        try:
            has_earnings = catalyst is not None and catalyst.catalyst_type == 'earnings'
            has_news     = catalyst is not None
            gap_result   = analyze_gap(
                ticker,
                gap_prev_close,
                price,
                fundamentals['atr'],
                has_earnings,
                has_news
            )
            gap_score = gap_result.quality_score
            gap_data  = gap_result.to_dict()
            print(
                f"[PREMARKET] {ticker}: Gap={gap_data.get('size_pct', 0):+.2f}% "
                f"({gap_data.get('tier','?')}) score={gap_score:.1f} "
                f"[prev_close={gap_prev_close:.2f}, price={price:.2f}]"
            )
        except Exception as e:
            print(f"[PREMARKET] {ticker}: Gap analysis error: {e}")
    elif V2_ENABLED and gap_prev_close == 0:
        print(f"[PREMARKET] {ticker}: Gap skipped — prev_close unavailable")

    # ──────────────────────────────────────────────────────────────────────────
    # Tier 3: News catalyst score (15% weight) — reuses catalyst from Tier 2
    # ──────────────────────────────────────────────────────────────────────────
    catalyst_score = 0
    catalyst_data  = None
    if V2_ENABLED:
        if catalyst:
            catalyst_score = min(100, catalyst.weight * 4)
            catalyst_data  = catalyst.to_dict()
            print(f"[PREMARKET] {ticker}: Catalyst — {catalyst.catalyst_type} (weight={catalyst.weight}, score={catalyst_score:.1f})")
        else:
            print(f"[PREMARKET] {ticker}: No catalyst detected")

    # Sector rotation bonus (+15 pts if hot sector)
    sector_bonus = 0
    sector_data  = None
    if V2_ENABLED:
        try:
            is_hot, sector_name = is_hot_sector_stock(ticker)
            if is_hot:
                sector_bonus = 15
                sector_data  = {'sector': sector_name, 'is_hot': True}
        except Exception as e:
            print(f"[PREMARKET] {ticker}: Sector check error: {e}")

    composite_score = (
        volume_score   * 0.60 +
        gap_score      * 0.25 +
        catalyst_score * 0.15 +
        sector_bonus
    )

    print(f"[PREMARKET] {ticker}: Composite score={composite_score:.1f} (vol={volume_score:.1f}, gap={gap_score:.1f}, catalyst={catalyst_score:.1f}, sector={sector_bonus:.1f})")

    result = {
        'ticker':           ticker,
        'price':            price,
        'volume':           volume,
        'volume_score':     volume_score,
        'gap_score':        gap_score,
        'catalyst_score':   catalyst_score,
        'sector_bonus':     sector_bonus,
        'composite_score':  round(composite_score, 1),
        'rvol':             volume_metrics['rvol'],
        'dollar_volume':    volume_metrics['dollar_volume'],
        'atr':              fundamentals['atr'],
        'market_cap':       fundamentals['market_cap'],
        'float':            fundamentals['float_shares'],
        'avg_daily_volume': fundamentals['avg_daily_volume'],
        'gap_data':         gap_data,
        'catalyst_data':    catalyst_data,
        'sector_data':      sector_data,
        'timestamp':        datetime.now()
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
    return _scanner_cache.get_stats()


def clear_cache():
    _scanner_cache.clear()
    print("[PREMARKET] All caches cleared")


def lock_scanner_cache():
    """
    PHASE 1.18: Lock the scanner cache for the rest of the session.
    Called by watchlist_funnel._build_live_watchlist() at market open.
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
    print(f"[PREMARKET] run_momentum_screener() called with {len(tickers)} tickers, min_score={min_composite_score}")
    return scan_watchlist(tickers, min_score=min_composite_score)


def get_top_n_movers(scored_tickers: List[Dict], n: int = 10) -> List[str]:
    sorted_tickers = sorted(
        scored_tickers,
        key=lambda x: x.get('composite_score', x.get('volume_score', 0)),
        reverse=True
    )
    return [t['ticker'] for t in sorted_tickers[:n]]


def print_momentum_summary(scored_tickers: List[Dict], top_n: int = 10):
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
        rank          = f"#{i}"
        ticker        = ticker_data.get('ticker', 'N/A')
        score         = ticker_data.get('composite_score', ticker_data.get('volume_score', 0))
        rvol          = ticker_data.get('rvol', 0)
        price         = ticker_data.get('price', 0)
        gap_data      = ticker_data.get('gap_data', {})
        gap_str       = f"{gap_data.get('size_pct', 0):+.1f}%" if gap_data else "N/A"
        catalyst_data = ticker_data.get('catalyst_data', {})
        catalyst_str  = catalyst_data.get('type', 'N/A')[:10] if catalyst_data else "-"
        print(f"{rank:<6} {ticker:<8} {score:<8.1f} {rvol:<8.2f} {gap_str:<8} {catalyst_str:<12} ${price:<9.2f}")

    print(f"{'='*80}\n")
