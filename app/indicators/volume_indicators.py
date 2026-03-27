"""
Volume-Based Technical Indicators

Local (non-API) calculations from raw price/volume bars.
Optimised for intraday use, backtesting, and real-time signal validation.

Indicators
----------
- MFI  (Money Flow Index)     – volume-weighted RSI
- OBV  (On-Balance Volume)    – cumulative volume direction
- RVOL (Relative Volume)      – today vs same-time yesterday
- Confluence scoring          – MFI + OBV aligned check

VWAP note
---------
calculate_vwap() and calculate_vwap_deviation() are provided below as
thin re-export shims that delegate to the canonical VWAPCalculator in
vwap_calculator.py.  Import them from here for backwards-compatibility,
but prefer using VWAPCalculator directly for new code.

History
-------
MOVED:   app/analytics/volume_indicators.py → app/indicators/volume_indicators.py
Phase 1 (Mar 26 2026):
  - Removed duplicate calculate_vwap() / calculate_vwap_deviation() bodies;
    replaced with re-export shims pointing to vwap_calculator.VWAPCalculator.
  - Migrated check_rvol() here from technical_indicators.py (it is a volume
    metric and does not belong in the EODHD API fetch module).
  - technical_indicators.check_rvol() is now a shim that calls this function.
"""

from typing import List, Dict, Optional, Tuple
import logging
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# VWAP  (re-export shims — canonical implementation: vwap_calculator.py)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_vwap(bars: List[Dict]) -> float:
    """
    Volume-Weighted Average Price.

    Re-export shim: delegates to VWAPCalculator.calculate_session_vwap().
    Use VWAPCalculator directly for new code (supports bands, anchored VWAP,
    intraday reset, etc.).

    Args:
        bars: List of OHLCV bar dicts (keys: high, low, close, volume)

    Returns:
        VWAP float, or last close if volume is zero.
    """
    if not bars:
        return 0.0
    try:
        from app.indicators.vwap_calculator import VWAPCalculator
        calc = VWAPCalculator()
        result = calc.calculate_session_vwap(bars)
        return result.get('vwap', 0.0)
    except Exception:
        # Fallback: inline calculation if vwap_calculator unavailable
        total_tp_vol = 0.0
        total_vol = 0
        for bar in bars:
            tp = (bar['high'] + bar['low'] + bar['close']) / 3
            total_tp_vol += tp * bar['volume']
            total_vol += bar['volume']
        return total_tp_vol / total_vol if total_vol > 0 else bars[-1]['close']


def calculate_vwap_deviation(bars: List[Dict]) -> float:
    """
    Percentage deviation from VWAP.

    Re-export shim: computes via calculate_vwap() above.

    Positive = trading above VWAP (bullish)
    Negative = trading below VWAP (bearish)

    Args:
        bars: List of OHLCV bar dicts

    Returns:
        % deviation, e.g. 2.5 means price is 2.5 % above VWAP.
    """
    if not bars:
        return 0.0
    vwap = calculate_vwap(bars)
    current_price = bars[-1]['close']
    return ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# MFI
# ─────────────────────────────────────────────────────────────────────────────

def calculate_mfi(bars: List[Dict], period: int = 14) -> float:
    """
    Money Flow Index – volume-weighted RSI.
    Measures buying/selling pressure with volume consideration.

    Args:
        bars: OHLCV bar list (needs at least period + 1 bars)
        period: Lookback period (default 14)

    Returns:
        0-100 scale:
          > 80 overbought (potential reversal down)
          < 20 oversold   (potential reversal up)
          50   neutral
    """
    if not bars or len(bars) < period + 1:
        return 50.0

    typical_prices = []
    money_flows = []

    for bar in bars:
        tp = (bar['high'] + bar['low'] + bar['close']) / 3
        typical_prices.append(tp)
        money_flows.append(tp * bar['volume'])

    positive_flow = 0.0
    negative_flow = 0.0

    for i in range(len(typical_prices) - period, len(typical_prices)):
        if i < 1:
            continue
        if typical_prices[i] > typical_prices[i - 1]:
            positive_flow += money_flows[i]
        elif typical_prices[i] < typical_prices[i - 1]:
            negative_flow += money_flows[i]

    if negative_flow == 0:
        return 100.0

    money_ratio = positive_flow / negative_flow
    return 100 - (100 / (1 + money_ratio))


# ─────────────────────────────────────────────────────────────────────────────
# OBV
# ─────────────────────────────────────────────────────────────────────────────

def calculate_obv(bars: List[Dict]) -> List[float]:
    """
    On-Balance Volume – cumulative volume direction indicator.
    Tracks smart money flow by adding volume on up days, subtracting on down.

    Args:
        bars: OHLCV bar list

    Returns:
        List of OBV values (one per bar, starting at 0).
    """
    if not bars or len(bars) < 2:
        return [0.0]

    obv_values = [0.0]
    current_obv = 0.0

    for i in range(1, len(bars)):
        if bars[i]['close'] > bars[i - 1]['close']:
            current_obv += bars[i]['volume']
        elif bars[i]['close'] < bars[i - 1]['close']:
            current_obv -= bars[i]['volume']
        obv_values.append(current_obv)

    return obv_values


def calculate_obv_trend(bars: List[Dict], lookback: int = 5) -> str:
    """
    OBV trend direction over lookback period.

    Args:
        bars: OHLCV bar list
        lookback: Number of bars to analyse (default 5)

    Returns:
        'bullish' | 'bearish' | 'neutral'
    """
    if not bars or len(bars) < lookback + 1:
        return 'neutral'

    obv_values = calculate_obv(bars)
    recent_obv = obv_values[-lookback:]

    if len(recent_obv) < 2:
        return 'neutral'

    mid = len(recent_obv) // 2
    first_half_avg  = sum(recent_obv[:mid]) / mid if mid > 0 else 0
    second_half_avg = sum(recent_obv[mid:]) / (len(recent_obv) - mid)

    change_pct = (
        ((second_half_avg - first_half_avg) / abs(first_half_avg)) * 100
        if first_half_avg != 0 else 0
    )

    if change_pct > 5:
        return 'bullish'
    elif change_pct < -5:
        return 'bearish'
    return 'neutral'


# ─────────────────────────────────────────────────────────────────────────────
# RVOL  (migrated from technical_indicators.py – Phase 1, Mar 26 2026)
# ─────────────────────────────────────────────────────────────────────────────

def check_rvol(
    ticker: str,
    bars_today: list,
    min_rvol: float = 1.2
) -> Tuple[Optional[float], bool]:
    """
    Relative Volume – today's cumulative volume vs the same number of bars
    from the same time yesterday.

    RVOL > 1.0  = more active than usual at this time of day
    RVOL > 1.5  = significantly elevated (institutional interest)
    RVOL > 2.0  = exceptional (news / catalyst likely)

    Args:
        ticker:     Stock symbol (used to look up yesterday's bars)
        bars_today: Today's bars (oldest-first or any order; sorted internally)
        min_rvol:   Minimum RVOL to flag as elevated (default 1.2)

    Returns:
        (rvol_value, is_elevated)
          rvol_value:  float or None if yesterday's data unavailable
          is_elevated: True when rvol_value >= min_rvol

    Notes:
        Both today's and yesterday's bar lists are sorted oldest-first before
        the cumulative volume comparison so the comparison always covers the
        same number of bars from session open (M6 sort guard pattern).

    Migration:
        Moved from technical_indicators.py (Phase 1, Mar 26 2026).
        technical_indicators.check_rvol() is a backwards-compatible shim
        that delegates here.
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

        # Sort both lists oldest-first (M6 sort guard)
        def _sort_oldest_first(bars):
            sample = bars[0] if bars else {}
            key = 'datetime' if 'datetime' in sample else ('date' if 'date' in sample else None)
            if not key:
                return bars
            try:
                return sorted(bars, key=lambda b: b[key])
            except Exception:
                return bars

        sorted_today     = _sort_oldest_first(bars_today)
        sorted_yesterday = _sort_oldest_first(bars_yesterday)

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


# ─────────────────────────────────────────────────────────────────────────────
# CONFLUENCE
# ─────────────────────────────────────────────────────────────────────────────

def check_indicator_confluence(bars: List[Dict], direction: str = 'bullish') -> Dict:
    """
    Check if VWAP, MFI, and OBV all confirm the same direction.

    Args:
        bars:      OHLCV bar list
        direction: 'bullish' or 'bearish'

    Returns:
        Dict with:
          confluence_score: 0.0–1.0  (0 = none, 1.0 = all three confirm)
          signals:          Individual indicator values and pass/fail flags
    """
    if not bars or len(bars) < 14:
        return {'confluence_score': 0.0, 'signals': {}}

    vwap_dev  = calculate_vwap_deviation(bars)
    mfi       = calculate_mfi(bars, period=14)
    obv_trend = calculate_obv_trend(bars, lookback=5)

    signals = {
        'vwap_deviation': vwap_dev,
        'mfi':            mfi,
        'obv_trend':      obv_trend
    }

    if direction == 'bullish':
        vwap_ok = vwap_dev > 0
        mfi_ok  = 20 <= mfi <= 80
        obv_ok  = obv_trend == 'bullish'
    else:
        vwap_ok = vwap_dev < 0
        mfi_ok  = 20 <= mfi <= 80
        obv_ok  = obv_trend == 'bearish'

    signals['vwap_confirms'] = vwap_ok
    signals['mfi_confirms']  = mfi_ok
    signals['obv_confirms']  = obv_ok

    confirmations    = sum([vwap_ok, mfi_ok, obv_ok])
    confluence_score = confirmations / 3.0

    return {'confluence_score': confluence_score, 'signals': signals}


def validate_signal_with_volume_indicators(
    bars: List[Dict],
    signal_direction: str,
    params: Dict = None
) -> Tuple[bool, Dict]:
    """
    Validate a trading signal using VWAP, MFI, and OBV.

    Args:
        bars:             OHLCV bar list
        signal_direction: 'CALL' or 'PUT'
        params:           Optional threshold overrides:
          vwap_min_deviation  – min % above/below VWAP (default 0.0)
          mfi_overbought      – MFI overbought threshold  (default 80)
          mfi_oversold        – MFI oversold threshold    (default 20)
          obv_lookback        – OBV trend lookback bars   (default 5)
          require_vwap_confirm – hard-fail on VWAP?       (default False)
          require_mfi_confirm  – hard-fail on MFI?        (default False)
          require_obv_confirm  – hard-fail on OBV?        (default False)

    Returns:
        (passes_validation, details_dict)
    """
    if params is None:
        params = {}

    vwap_min_dev   = params.get('vwap_min_deviation', 0.0)
    mfi_overbought = params.get('mfi_overbought', 80)
    mfi_oversold   = params.get('mfi_oversold', 20)
    obv_lookback   = params.get('obv_lookback', 5)
    require_vwap   = params.get('require_vwap_confirm', False)
    require_mfi    = params.get('require_mfi_confirm', False)
    require_obv    = params.get('require_obv_confirm', False)

    vwap_dev  = calculate_vwap_deviation(bars)
    mfi       = calculate_mfi(bars, period=14)
    obv_trend = calculate_obv_trend(bars, lookback=obv_lookback)

    details = {
        'vwap_deviation': round(vwap_dev, 2),
        'mfi':            round(mfi, 1),
        'obv_trend':      obv_trend,
        'vwap_pass':      True,
        'mfi_pass':       True,
        'obv_pass':       True
    }

    if require_vwap:
        if signal_direction == 'CALL' and vwap_dev < vwap_min_dev:
            details['vwap_pass']   = False
            details['vwap_reason'] = f'Price only {vwap_dev:.1f}% above VWAP (need >{vwap_min_dev}%)'
        elif signal_direction == 'PUT' and vwap_dev > -vwap_min_dev:
            details['vwap_pass']   = False
            details['vwap_reason'] = f'Price only {vwap_dev:.1f}% below VWAP (need <-{vwap_min_dev}%)'

    if require_mfi:
        if signal_direction == 'CALL' and mfi > mfi_overbought:
            details['mfi_pass']   = False
            details['mfi_reason'] = f'MFI overbought at {mfi:.0f} (>{mfi_overbought})'
        elif signal_direction == 'PUT' and mfi < mfi_oversold:
            details['mfi_pass']   = False
            details['mfi_reason'] = f'MFI oversold at {mfi:.0f} (<{mfi_oversold})'

    if require_obv:
        if signal_direction == 'CALL' and obv_trend != 'bullish':
            details['obv_pass']   = False
            details['obv_reason'] = f'OBV trend is {obv_trend}, not bullish'
        elif signal_direction == 'PUT' and obv_trend != 'bearish':
            details['obv_pass']   = False
            details['obv_reason'] = f'OBV trend is {obv_trend}, not bearish'

    passes = details['vwap_pass'] and details['mfi_pass'] and details['obv_pass']
    return passes, details


if __name__ == '__main__':
    test_bars = [
        {'high': 100, 'low': 98,  'close': 99,  'volume': 1_000_000},
        {'high': 101, 'low': 99,  'close': 100, 'volume': 1_100_000},
        {'high': 102, 'low': 100, 'close': 101, 'volume': 1_200_000},
        {'high': 103, 'low': 101, 'close': 102, 'volume': 1_300_000},
        {'high': 104, 'low': 102, 'close': 103, 'volume': 1_400_000},
    ]
    logger.info('Testing volume indicators...')
    logger.info(f'VWAP: ${calculate_vwap(test_bars):.2f}')
    logger.info(f'VWAP Dev: {calculate_vwap_deviation(test_bars):.2f}%')
    logger.info(f'MFI: {calculate_mfi(test_bars, period=3):.1f}')
    logger.info(f'OBV: {calculate_obv(test_bars)}')
    logger.info(f'OBV Trend: {calculate_obv_trend(test_bars, lookback=3)}')
    c = check_indicator_confluence(test_bars, direction='bullish')
    logger.info(f'Confluence: {c["confluence_score"]:.0%}')
