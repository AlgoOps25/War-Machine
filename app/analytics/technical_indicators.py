"""
Technical Indicators Module - EODHD API Integration

Fetches pre-calculated technical indicators from EODHD API.
Includes aggressive caching to minimize API calls (each indicator = 5 API credits).

Supported Indicators:
  - ADX  - trend strength (>25 trending, >40 strong)
  - BB   - Bollinger Bands, volatility and squeeze detection
  - AVGVOL- volume confirmation
  - CCI  - momentum oscillator
  - DMI  - trend direction (plus_di vs minus_di)
  - MACD - trend following + crossover detection
  - SAR  - Parabolic SAR trailing stops
  - STOCH- Stochastic oscillator + crossover detection
  - RSI  - Relative Strength Index (>70 overbought, <30 oversold)
  - RSI DIVERGENCE - Bearish/Bullish divergence detection [NEW]
  - EMA  - Exponential Moving Average (50, 200 period filters)

Cache Strategy:
  - Pre-market  (4:00-9:30):  5-minute TTL
  - Market hours(9:30-16:00): 2-minute TTL
  - After hours:              10-minute TTL

Fine-Tuning Notes:
  - ADX threshold raised to 25 (was 20) – filters more choppy markets
  - Volume ratio threshold raised to 1.5 (was 1.3) – stronger confirmation
  - RSI replaces CCI as primary momentum oscillator (more widely tested)
  - EMA 50/200 added as macro trend filter layer
  - MACD crossover detects momentum shifts vs raw MACD value
  - Stochastic crossover detects precise K/D inflection points
  - RVOL (relative volume) added: today volume vs same time yesterday
  - RSI divergence warns of exhaustion before reversal

M6 FIX (Mar 10 2026): Added _ensure_oldest_first() defensive sort guard.
  Raw bar lists from data_manager have no guaranteed sort order.
  check_rsi_divergence() and check_rvol() now normalise to oldest-first
  before any index-based high/low or volume lookups.
"""
import requests
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from utils import config

ET = ZoneInfo("America/New_York")


# ══════════════════════════════════════════════════════════════════════════════
# BAR SORT GUARD  (M6)
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_oldest_first(bars: list) -> list:
    """
    Return a copy of *bars* sorted oldest → newest.

    data_manager returns bars with no guaranteed ordering; callers that do
    index-based arithmetic (high/low lookups, cumulative volume) must call
    this first.  The sort key prefers the 'datetime' field and falls back to
    'date'.  If neither key is present the list is returned as-is so callers
    degrade gracefully rather than crash.
    """
    if not bars:
        return bars

    sample = bars[0]
    if 'datetime' in sample:
        key = 'datetime'
    elif 'date' in sample:
        key = 'date'
    else:
        return bars  # no sortable key — return unchanged

    try:
        return sorted(bars, key=lambda b: b[key])
    except Exception:
        return bars  # sorting failed — return unchanged


# ══════════════════════════════════════════════════════════════════════════════
# CACHING LAYER
# ══════════════════════════════════════════════════════════════════════════════

class IndicatorCache:
    """Time-aware cache for technical indicators with adaptive TTL."""

    def __init__(self):
        self.cache: Dict[str, Dict] = {}

    def _get_ttl_seconds(self) -> int:
        """Return TTL based on time of day."""
        now = datetime.now(ET).time()
        if dtime(4, 0) <= now < dtime(9, 30):
            return 300   # 5 min pre-market
        elif dtime(9, 30) <= now < dtime(16, 0):
            return 120   # 2 min during session
        else:
            return 600   # 10 min after hours

    def get(self, cache_key: str) -> Optional[Any]:
        if cache_key not in self.cache:
            return None
        entry = self.cache[cache_key]
        age   = (datetime.now(ET) - entry['timestamp']).total_seconds()
        if age > self._get_ttl_seconds():
            del self.cache[cache_key]
            return None
        return entry['data']

    def set(self, cache_key: str, data: Any):
        self.cache[cache_key] = {'data': data, 'timestamp': datetime.now(ET)}

    def clear(self):
        self.cache = {}
        print("[INDICATORS] Cache cleared")

    def get_stats(self) -> Dict:
        now = datetime.now(ET)
        ttl = self._get_ttl_seconds()
        valid = sum(
            1 for e in self.cache.values()
            if (now - e['timestamp']).total_seconds() <= ttl
        )
        return {'total_entries': len(self.cache), 'valid_entries': valid, 'current_ttl': ttl}


_indicator_cache = IndicatorCache()


# ══════════════════════════════════════════════════════════════════════════════
# CORE FETCH
# ══════════════════════════════════════════════════════════════════════════════

def fetch_technical_indicator(
    ticker: str,
    function: str,
    use_cache: bool = True,
    **params
) -> Optional[List[Dict]]:
    """
    Fetch technical indicator from EODHD API.
    Returns list in DESCENDING order (newest first) due to order=d param.
    """
    param_str = '_'.join(f"{k}={v}" for k, v in sorted(params.items()))
    cache_key = f"{ticker}_{function}_{param_str}"

    if use_cache:
        cached = _indicator_cache.get(cache_key)
        if cached is not None:
            return cached

    url = f"https://eodhd.com/api/technical/{ticker}.US"
    api_params = {
        'api_token': config.EODHD_API_KEY,
        'function': function,
        'fmt': 'json',
        'order': 'd',
        **params
    }

    try:
        response = requests.get(url, params=api_params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list):
            return None
        if use_cache:
            _indicator_cache.set(cache_key, data)
        return data
    except requests.exceptions.HTTPError as e:
        print(f"[INDICATORS] API error for {ticker} {function}: {e}")
        return None
    except Exception as e:
        print(f"[INDICATORS] Unexpected error for {ticker} {function}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# EXISTING INDICATOR WRAPPERS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_adx(ticker: str, period: int = 14, use_cache: bool = True) -> Optional[List[Dict]]:
    """ADX – trend strength. Values: 0-100 (>25 trending, >40 strong trend)."""
    return fetch_technical_indicator(ticker, 'adx', use_cache=use_cache, period=period)


def fetch_bbands(ticker: str, period: int = 20, deviation: float = 2.0, use_cache: bool = True) -> Optional[List[Dict]]:
    """Bollinger Bands – uband, mband, lband."""
    return fetch_technical_indicator(
        ticker, 'bbands', use_cache=use_cache, period=period, deviation=deviation
    )


def fetch_avgvol(ticker: str, period: int = 20, use_cache: bool = True) -> Optional[List[Dict]]:
    """Average Volume – avgvol key."""
    return fetch_technical_indicator(ticker, 'avgvol', use_cache=use_cache, period=period)


def fetch_cci(ticker: str, period: int = 20, use_cache: bool = True) -> Optional[List[Dict]]:
    """CCI – momentum oscillator. >100 overbought, <-100 oversold."""
    return fetch_technical_indicator(ticker, 'cci', use_cache=use_cache, period=period)


def fetch_dmi(ticker: str, period: int = 14, use_cache: bool = True) -> Optional[List[Dict]]:
    """DMI – plus_di vs minus_di for trend direction."""
    return fetch_technical_indicator(ticker, 'dmi', use_cache=use_cache, period=period)


def fetch_macd(
    ticker: str,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    use_cache: bool = True
) -> Optional[List[Dict]]:
    """MACD – macd, signal, histogram keys."""
    return fetch_technical_indicator(
        ticker, 'macd', use_cache=use_cache,
        fast_period=fast_period, slow_period=slow_period, signal_period=signal_period
    )


def fetch_sar(
    ticker: str,
    acceleration: float = 0.02,
    maximum: float = 0.20,
    use_cache: bool = True
) -> Optional[List[Dict]]:
    """Parabolic SAR – sar key."""
    return fetch_technical_indicator(
        ticker, 'sar', use_cache=use_cache,
        acceleration=acceleration, maximum=maximum
    )


def fetch_stochastic(
    ticker: str,
    fast_kperiod: int = 14,
    slow_kperiod: int = 3,
    slow_dperiod: int = 3,
    use_cache: bool = True
) -> Optional[List[Dict]]:
    """Stochastic – k and d keys. >80 overbought, <20 oversold."""
    return fetch_technical_indicator(
        ticker, 'stochastic', use_cache=use_cache,
        fast_kperiod=fast_kperiod, slow_kperiod=slow_kperiod, slow_dperiod=slow_dperiod
    )


# ══════════════════════════════════════════════════════════════════════════════
# NEW INDICATORS – RSI, EMA
# ══════════════════════════════════════════════════════════════════════════════

def fetch_rsi(ticker: str, period: int = 14, use_cache: bool = True) -> Optional[List[Dict]]:
    """
    Fetch RSI (Relative Strength Index) – preferred momentum indicator.

    More reliable than CCI for day/swing trading:
      - Standard period: 14
      - >70 = overbought (avoid longs / look for shorts)
      - <30 = oversold  (avoid shorts / look for longs)
      - 40-60 = neutral zone

    Returns:
        List of dicts with keys: date, rsi
    """
    return fetch_technical_indicator(ticker, 'rsi', use_cache=use_cache, period=period)


def fetch_ema(
    ticker: str,
    period: int = 50,
    use_cache: bool = True
) -> Optional[List[Dict]]:
    """
    Fetch EMA (Exponential Moving Average).

    Key periods:
      - 9  EMA : intraday momentum
      - 20 EMA : short-term trend
      - 50 EMA : medium-term trend (used as macro filter)
      - 200 EMA: long-term trend   (used as macro filter)

    Returns:
        List of dicts with keys: date, ema
    """
    return fetch_technical_indicator(ticker, 'ema', use_cache=use_cache, period=period)


# ══════════════════════════════════════════════════════════════════════════════
# BATCH FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def batch_fetch_indicators(
    tickers: List[str],
    indicators: List[str],
    use_cache: bool = True
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch multiple indicators for multiple tickers.
    Returns {ticker: {indicator_name: data_list}}
    """
    results = {}
    indicator_map = {
        'adx': fetch_adx,
        'bbands': fetch_bbands,
        'avgvol': fetch_avgvol,
        'cci': fetch_cci,
        'dmi': fetch_dmi,
        'macd': fetch_macd,
        'sar': fetch_sar,
        'stochastic': fetch_stochastic,
        'rsi': fetch_rsi,
        'ema': fetch_ema,
    }

    for ticker in tickers:
        results[ticker] = {}
        for name in indicators:
            func = indicator_map.get(name)
            if not func:
                print(f"[INDICATORS] Unknown indicator: {name}")
                continue
            try:
                results[ticker][name] = func(ticker, use_cache=use_cache)
            except Exception as e:
                print(f"[INDICATORS] Error fetching {name} for {ticker}: {e}")
                results[ticker][name] = None

    return results


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS HELPERS – existing
# ══════════════════════════════════════════════════════════════════════════════

def get_latest_value(indicator_data: Optional[List[Dict]], key: str) -> Optional[float]:
    """
    Extract latest value from indicator data (descending order → index 0).
    """
    if not indicator_data or not isinstance(indicator_data, list):
        return None
    latest = indicator_data[0]
    return float(latest.get(key, 0)) if latest.get(key) is not None else None


def check_bollinger_squeeze(
    ticker: str, threshold: float = 0.04
) -> Tuple[bool, Optional[float]]:
    """
    Check for Bollinger Band squeeze (low volatility / pre-breakout setup).
    threshold: band_width < 4% of midband signals a squeeze.
    """
    bbands_data = fetch_bbands(ticker)
    if not bbands_data:
        return False, None
    latest = bbands_data[0]
    upper, lower, middle = latest.get('uband'), latest.get('lband'), latest.get('mband')
    if not all([upper, lower, middle]):
        return False, None
    band_width = (upper - lower) / middle
    return band_width < threshold, round(band_width, 4)


def check_trend_strength(
    ticker: str, min_adx: float = 25.0
) -> Tuple[bool, Optional[float]]:
    """
    Check trend strength via ADX.
    Fine-tuned threshold: 25 (was 20) – filters choppy range-bound markets.
    """
    adx_data = fetch_adx(ticker)
    if not adx_data:
        return False, None
    latest_adx = get_latest_value(adx_data, 'adx')
    if latest_adx is None:
        return False, None
    return latest_adx >= min_adx, round(latest_adx, 2)


def check_volume_confirmation(
    ticker: str, current_volume: int, min_ratio: float = 1.5
) -> Tuple[bool, Optional[float]]:
    """
    Check volume vs 20-day average.
    Fine-tuned threshold: 1.5x (was 1.3x) – stronger institutional confirmation.
    """
    avgvol_data = fetch_avgvol(ticker)
    if not avgvol_data:
        return False, None
    avg_volume = get_latest_value(avgvol_data, 'avgvol')
    if not avg_volume or avg_volume == 0:
        return False, None
    volume_ratio = current_volume / avg_volume
    return volume_ratio >= min_ratio, round(volume_ratio, 2)


def get_trend_direction(ticker: str) -> Optional[str]:
    """
    Trend direction via DMI (+DI vs -DI).
    Returns 'BULLISH', 'BEARISH', or None.
    """
    dmi_data = fetch_dmi(ticker)
    if not dmi_data:
        return None
    latest   = dmi_data[0]
    plus_di  = latest.get('plus_di')
    minus_di = latest.get('minus_di')
    if plus_di is None or minus_di is None:
        return None
    if plus_di > minus_di:
        return 'BULLISH'
    elif minus_di > plus_di:
        return 'BEARISH'
    return None


# ══════════════════════════════════════════════════════════════════════════════
# NEW ANALYSIS HELPERS – RSI, EMA, MACD crossover, Stochastic crossover, RVOL
# ══════════════════════════════════════════════════════════════════════════════

def check_rsi_zone(
    ticker: str,
    signal_direction: str,
    overbought: float = 70.0,
    oversold: float = 30.0
) -> Tuple[Optional[str], Optional[float]]:
    """
    Check RSI zone relative to signal direction.

    Replaces CCI as the primary momentum filter – RSI is better-tested
    for day/swing trading setups and more universally respected.

    Args:
        ticker: Stock symbol
        signal_direction: 'BUY' or 'SELL'
        overbought: RSI threshold for overbought (default 70)
        oversold:   RSI threshold for oversold  (default 30)

    Returns:
        (zone_result, rsi_value)
        zone_result: 'FAVORABLE' | 'UNFAVORABLE' | 'NEUTRAL'
          - BUY  + oversold  (<30) → FAVORABLE   (+confidence)
          - BUY  + overbought(>70) → UNFAVORABLE (-confidence)
          - SELL + overbought(>70) → FAVORABLE   (+confidence)
          - SELL + oversold  (<30) → UNFAVORABLE (-confidence)
    """
    rsi_data = fetch_rsi(ticker)
    if not rsi_data:
        return None, None

    rsi_value = get_latest_value(rsi_data, 'rsi')
    if rsi_value is None:
        return None, None

    if signal_direction == 'BUY':
        if rsi_value < oversold:
            return 'FAVORABLE', round(rsi_value, 2)
        elif rsi_value > overbought:
            return 'UNFAVORABLE', round(rsi_value, 2)
    else:  # SELL
        if rsi_value > overbought:
            return 'FAVORABLE', round(rsi_value, 2)
        elif rsi_value < oversold:
            return 'UNFAVORABLE', round(rsi_value, 2)

    return 'NEUTRAL', round(rsi_value, 2)


def check_rsi_divergence(
    ticker: str,
    signal_direction: str,
    lookback_bars: int = 10
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Detect RSI divergence – early warning of trend exhaustion/reversal.

    Divergence occurs when price makes a new high/low but RSI does NOT confirm,
    indicating weakening momentum before the actual reversal appears in price.

    Types:
      - Bearish Divergence: Price makes higher high, RSI makes lower high
        → Warns of uptrend exhaustion, favor SELL signals
      
      - Bullish Divergence: Price makes lower low, RSI makes higher low
        → Warns of downtrend exhaustion, favor BUY signals

    Args:
        ticker: Stock symbol
        signal_direction: 'BUY' or 'SELL'
        lookback_bars: Number of bars to scan for divergence (default 10)

    Returns:
        (divergence_result, details_dict)
        divergence_result: 'BEARISH_DIV' | 'BULLISH_DIV' | 'NO_DIV' | None
        
        This is a SOFT signal (warning), not a hard filter.
        Use to BOOST counter-trend signals or WARN on exhausted trends.

    Usage in validation:
      - BUY signal + BULLISH_DIV  → +confidence (reversal setup)
      - BUY signal + BEARISH_DIV  → -confidence (buying into exhaustion)
      - SELL signal + BEARISH_DIV → +confidence (reversal setup)
      - SELL signal + BULLISH_DIV → -confidence (selling into exhaustion)
    """
    try:
        from app.data.data_manager import data_manager
        raw_bars = data_manager.get_bars_from_memory(ticker, limit=lookback_bars + 1)
        if not raw_bars or len(raw_bars) < lookback_bars:
            return None, None

        # M6: normalise to oldest-first before index-based high/low lookups
        bars = _ensure_oldest_first(raw_bars)

        rsi_data = fetch_rsi(ticker)
        if not rsi_data or len(rsi_data) < lookback_bars:
            return None, None

        # RSI from EODHD is newest-first; reverse to match oldest-first bars
        recent_rsi_desc = rsi_data[:lookback_bars]
        recent_rsi = list(reversed(recent_rsi_desc))

        recent_bars = bars[-lookback_bars:]

        # Extract prices and RSI values
        prices     = [b['close'] for b in recent_bars]
        rsi_values = [r.get('rsi') for r in recent_rsi if r.get('rsi') is not None]

        if len(prices) != len(rsi_values) or len(prices) < lookback_bars:
            return None, None

        # Find price highs/lows and RSI highs/lows
        price_high_idx = prices.index(max(prices))
        price_low_idx  = prices.index(min(prices))
        rsi_high_idx   = rsi_values.index(max(rsi_values))
        rsi_low_idx    = rsi_values.index(min(rsi_values))

        details = {
            'price_high': round(prices[price_high_idx], 2),
            'price_low':  round(prices[price_low_idx], 2),
            'rsi_high':   round(rsi_values[rsi_high_idx], 2),
            'rsi_low':    round(rsi_values[rsi_low_idx], 2),
            'lookback_bars': lookback_bars
        }

        # BEARISH DIVERGENCE: Price higher high, RSI lower high
        # In oldest-first order: higher index = more recent
        if price_high_idx > rsi_high_idx:
            if prices[price_high_idx] > prices[rsi_high_idx]:
                if rsi_values[price_high_idx] < rsi_values[rsi_high_idx]:
                    details['type']    = 'BEARISH_DIV'
                    details['warning'] = 'Price new high, RSI lower high (uptrend exhaustion)'
                    return 'BEARISH_DIV', details

        # BULLISH DIVERGENCE: Price lower low, RSI higher low
        if price_low_idx > rsi_low_idx:
            if prices[price_low_idx] < prices[rsi_low_idx]:
                if rsi_values[price_low_idx] > rsi_values[rsi_low_idx]:
                    details['type']    = 'BULLISH_DIV'
                    details['warning'] = 'Price new low, RSI higher low (downtrend exhaustion)'
                    return 'BULLISH_DIV', details

        details['type'] = 'NO_DIV'
        return 'NO_DIV', details

    except Exception as e:
        print(f"[INDICATORS] RSI divergence error for {ticker}: {e}")
        return None, None


def check_ema_position(
    ticker: str,
    current_price: float,
    signal_direction: str,
    period: int = 50
) -> Tuple[Optional[bool], Optional[float]]:
    """
    Check whether price is above or below a key EMA.

    Used as a macro trend filter:
      - BUY  signal: price should be ABOVE EMA (trend support)
      - SELL signal: price should be BELOW EMA (trend resistance)

    Recommended periods:
      - 50  EMA: medium-term trend filter (default)
      - 200 EMA: long-term bias filter

    Args:
        ticker: Stock symbol
        current_price: Current stock price
        signal_direction: 'BUY' or 'SELL'
        period: EMA period (default 50)

    Returns:
        (is_aligned, ema_value)
        is_aligned: True if price-vs-EMA matches signal direction
    """
    ema_data = fetch_ema(ticker, period=period)
    if not ema_data:
        return None, None

    ema_value = get_latest_value(ema_data, 'ema')
    if ema_value is None:
        return None, None

    if signal_direction == 'BUY':
        is_aligned = current_price > ema_value
    else:  # SELL
        is_aligned = current_price < ema_value

    return is_aligned, round(ema_value, 4)


def check_macd_crossover(
    ticker: str,
    signal_direction: str,
    lookback: int = 3
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Detect recent MACD signal-line crossover within lookback bars.

    More actionable than raw MACD value – crossovers mark the actual
    momentum shift that precedes directional moves.

    Args:
        ticker: Stock symbol
        signal_direction: 'BUY' or 'SELL'
        lookback: Number of recent bars to check for crossover (default 3)

    Returns:
        (crossover_result, details_dict)
        crossover_result: 'BULLISH_CROSS' | 'BEARISH_CROSS' | 'ABOVE_ZERO' |
                          'BELOW_ZERO' | 'NO_CROSS' | None
    """
    macd_data = fetch_macd(ticker)
    if not macd_data or len(macd_data) < lookback + 1:
        return None, None

    # Newest first (index 0 = latest)
    recent  = macd_data[:lookback]
    prev    = macd_data[lookback]

    latest_macd   = recent[0].get('macd')
    latest_signal = recent[0].get('signal')
    prev_macd     = prev.get('macd')
    prev_signal   = prev.get('signal')

    if None in (latest_macd, latest_signal, prev_macd, prev_signal):
        return None, None

    details = {
        'macd':           round(latest_macd, 4),
        'signal':         round(latest_signal, 4),
        'histogram':      round(latest_macd - latest_signal, 4),
        'prev_histogram': round(prev_macd - prev_signal, 4)
    }

    prev_below    = prev_macd < prev_signal
    current_above = latest_macd > latest_signal
    prev_above    = prev_macd > prev_signal
    current_below = latest_macd < latest_signal

    if prev_below and current_above:
        result = 'BULLISH_CROSS'
    elif prev_above and current_below:
        result = 'BEARISH_CROSS'
    elif latest_macd > 0 and latest_signal > 0:
        result = 'ABOVE_ZERO'
    elif latest_macd < 0 and latest_signal < 0:
        result = 'BELOW_ZERO'
    else:
        result = 'NO_CROSS'

    return result, details


def check_stochastic_crossover(
    ticker: str,
    signal_direction: str,
    overbought: float = 80.0,
    oversold: float = 20.0,
    lookback: int = 3
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Detect Stochastic K/D crossover in overbought/oversold zones.

    More precise than raw stochastic values – crossovers inside extreme
    zones identify high-probability reversal or continuation entries.

    Args:
        ticker: Stock symbol
        signal_direction: 'BUY' or 'SELL'
        overbought: K threshold for overbought zone (default 80)
        oversold:   K threshold for oversold zone  (default 20)
        lookback:   Bars to scan for crossover       (default 3)

    Returns:
        (crossover_result, details_dict)
        crossover_result: 'BULLISH_CROSS_OVERSOLD' | 'BEARISH_CROSS_OVERBOUGHT' |
                          'OVERSOLD' | 'OVERBOUGHT' | 'NEUTRAL' | None
    """
    stoch_data = fetch_stochastic(ticker)
    if not stoch_data or len(stoch_data) < lookback + 1:
        return None, None

    recent = stoch_data[:lookback]
    prev   = stoch_data[lookback]

    k_current = recent[0].get('k')
    d_current = recent[0].get('d')
    k_prev    = prev.get('k')
    d_prev    = prev.get('d')

    if None in (k_current, d_current, k_prev, d_prev):
        return None, None

    details = {
        'k': round(k_current, 2),
        'd': round(d_current, 2),
    }

    bullish_cross = (k_prev < d_prev) and (k_current > d_current) and (k_current < oversold + 10)
    bearish_cross = (k_prev > d_prev) and (k_current < d_current) and (k_current > overbought - 10)

    if bullish_cross:
        result = 'BULLISH_CROSS_OVERSOLD'
    elif bearish_cross:
        result = 'BEARISH_CROSS_OVERBOUGHT'
    elif k_current < oversold:
        result = 'OVERSOLD'
    elif k_current > overbought:
        result = 'OVERBOUGHT'
    else:
        result = 'NEUTRAL'

    return result, details


def check_rvol(
    ticker: str,
    bars_today: list,
    min_rvol: float = 1.2
) -> Tuple[Optional[float], bool]:
    """
    Calculate Relative Volume (RVOL) – today's volume vs same time yesterday.

    RVOL > 1.0 = more active than usual at this time of day
    RVOL > 1.5 = significantly elevated (institutional interest)
    RVOL > 2.0 = exceptional (news/catalyst likely)

    Args:
        ticker: Stock symbol
        bars_today: Today's bars (from data_manager)
        min_rvol: Minimum RVOL to flag as elevated (default 1.2)

    Returns:
        (rvol_value, is_elevated)

    M6: Both bars_today and bars_yesterday are normalised to oldest-first
    before taking cumulative volume so the comparison uses the same number
    of bars from the START of each session regardless of how data_manager
    returns them.
    """
    if not bars_today:
        return None, False

    try:
        from app.data.data_manager import data_manager
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        yesterday = (datetime.now(et) - timedelta(days=1)).strftime('%Y-%m-%d')

        bars_yesterday = data_manager.get_bars_for_date(ticker, yesterday)
        if not bars_yesterday:
            return None, False

        # M6: sort both lists oldest-first before comparing
        sorted_today     = _ensure_oldest_first(bars_today)
        sorted_yesterday = _ensure_oldest_first(bars_yesterday)

        n = len(sorted_today)
        bars_yesterday_same = sorted_yesterday[:n]

        if not bars_yesterday_same:
            return None, False

        vol_today     = sum(b.get('volume', 0) for b in sorted_today)
        vol_yesterday = sum(b.get('volume', 0) for b in bars_yesterday_same)

        if vol_yesterday == 0:
            return None, False

        rvol        = vol_today / vol_yesterday
        is_elevated = rvol >= min_rvol

        return round(rvol, 2), is_elevated

    except Exception:
        return None, False


# ══════════════════════════════════════════════════════════════════════════════
# CACHE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def clear_indicator_cache():
    """Clear all cached indicators. Call at EOD."""
    _indicator_cache.clear()


def get_cache_stats() -> Dict:
    """Get cache statistics for monitoring."""
    return _indicator_cache.get_stats()


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_ticker = "AAPL"
    test_price  = 175.50
    print(f"Testing technical indicators for {test_ticker}...\n")

    is_trending, adx = check_trend_strength(test_ticker)
    print(f"ADX: {adx} | {'✅ TRENDING' if is_trending else '❌ WEAK'} (threshold: 25)")

    rsi_zone, rsi_val = check_rsi_zone(test_ticker, 'BUY')
    print(f"RSI: {rsi_val} | Zone: {rsi_zone}")

    div_result, div_details = check_rsi_divergence(test_ticker, 'BUY')
    print(f"RSI Divergence: {div_result}")
    if div_details:
        print(f"  Details: {div_details}")

    ema_aligned, ema_val = check_ema_position(test_ticker, test_price, 'BUY', period=50)
    print(f"EMA50: {ema_val} | Aligned: {ema_aligned}")

    ema200_aligned, ema200_val = check_ema_position(test_ticker, test_price, 'BUY', period=200)
    print(f"EMA200: {ema200_val} | Aligned: {ema200_aligned}")

    macd_result, macd_details = check_macd_crossover(test_ticker, 'BUY')
    print(f"MACD: {macd_result} | {macd_details}")

    stoch_result, stoch_details = check_stochastic_crossover(test_ticker, 'BUY')
    print(f"Stoch: {stoch_result} | {stoch_details}")

    is_squeezed, bw = check_bollinger_squeeze(test_ticker)
    print(f"BB Squeeze: {is_squeezed} | Width: {bw}")

    direction = get_trend_direction(test_ticker)
    print(f"DMI Direction: {direction}")

    print(f"\nCache: {get_cache_stats()}")
