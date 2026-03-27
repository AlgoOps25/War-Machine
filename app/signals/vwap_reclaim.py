"""
VWAP Reclaim Signal Module
Detects VWAP reclaim setups where price dips below VWAP and reclaims it
with a valid CFW6-style confirmation candle.

FIX 43.M-10 (Mar 19 2026): Synthetic FVG zone was hardcoded at ±0.15% around
  VWAP, ignoring the per-ticker adaptive threshold computed by
  get_adaptive_fvg_threshold() in app/risk/trade_calculator.py.
  A high-priced ticker (e.g. $500) would get a $1.50 zone each side;
  a $10 ticker would get $0.015 — both using the same 0.15% regardless
  of ATR or price regime. Fixed to call get_adaptive_fvg_threshold() and
  use its result as the half-width of the synthetic FVG zone.

FIX (Mar 27 2026):
  - print() calls in detect_vwap_reclaim() replaced with logger.info().
    Raw stdout bypassed Railway structured logging entirely (no timestamp,
    no log level). Now captured consistently with all other [VWAP-RECLAIM] logs.
"""
import logging
from typing import Dict, List, Optional, Tuple
from utils import config

logger = logging.getLogger(__name__)


def _get_adaptive_threshold(ticker: str, current_price: float, bars: List[Dict]) -> float:
    """
    Retrieve adaptive FVG threshold from trade_calculator.
    Falls back to config.FVG_MIN_SIZE_PCT * current_price if unavailable.
    """
    try:
        from app.risk.trade_calculator import get_adaptive_fvg_threshold
        return get_adaptive_fvg_threshold(ticker, current_price, bars)
    except Exception:
        return current_price * getattr(config, 'FVG_MIN_SIZE_PCT', 0.0015)


def build_synthetic_fvg_zone(
    vwap: float,
    ticker: str,
    current_price: float,
    bars: List[Dict],
) -> Tuple[float, float]:
    """
    Build a synthetic FVG zone centred on VWAP using the adaptive threshold
    as the half-width.

    FIX 43.M-10: Previously hardcoded half-width = vwap * 0.0015 (0.15%).
    Now uses get_adaptive_fvg_threshold() so zone width scales with ATR /
    price regime.

    Returns:
        (zone_low, zone_high)
    """
    half_width = _get_adaptive_threshold(ticker, current_price, bars)
    return vwap - half_width, vwap + half_width


def detect_vwap_reclaim(
    ticker: str,
    bars: List[Dict],
    direction: str,
    vwap: float,
) -> Optional[Dict]:
    """
    Detect a VWAP reclaim setup.

    Criteria (bull):
      1. A recent bar dipped below VWAP (sweep)
      2. Close recovered above VWAP
      3. Close is within the adaptive synthetic FVG zone above VWAP

    Args:
        ticker:    Stock symbol
        bars:      List of OHLCV bar dicts (chronological)
        direction: 'bull' or 'bear'
        vwap:      Current VWAP level

    Returns:
        dict with zone, entry_price, grade  OR  None
    """
    if not bars or len(bars) < 3 or vwap <= 0:
        return None

    current_price = bars[-1]['close']
    zone_low, zone_high = build_synthetic_fvg_zone(vwap, ticker, current_price, bars)

    lookback = bars[-6:]

    for bar in lookback:
        if direction == 'bull':
            swept   = bar['low'] < vwap
            reclaim = bar['close'] > vwap
            in_zone = zone_low <= bar['close'] <= zone_high
            if swept and reclaim and in_zone:
                logger.info(
                    f"[VWAP-RECLAIM] {ticker} BULL reclaim @ ${bar['close']:.2f} "
                    f"| zone ${zone_low:.2f}\u2013${zone_high:.2f} | VWAP ${vwap:.2f}"
                )
                return {
                    'direction':   direction,
                    'entry_price': bar['close'],
                    'vwap':        vwap,
                    'zone_low':    zone_low,
                    'zone_high':   zone_high,
                    'grade':       'A',
                }
        elif direction == 'bear':
            swept   = bar['high'] > vwap
            reclaim = bar['close'] < vwap
            in_zone = zone_low <= bar['close'] <= zone_high
            if swept and reclaim and in_zone:
                logger.info(
                    f"[VWAP-RECLAIM] {ticker} BEAR reclaim @ ${bar['close']:.2f} "
                    f"| zone ${zone_low:.2f}\u2013${zone_high:.2f} | VWAP ${vwap:.2f}"
                )
                return {
                    'direction':   direction,
                    'entry_price': bar['close'],
                    'vwap':        vwap,
                    'zone_low':    zone_low,
                    'zone_high':   zone_high,
                    'grade':       'A',
                }

    return None
