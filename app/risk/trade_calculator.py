"""
Trade Calculator - Consolidated Stop Loss, Targets, and Adaptive Parameters
Replaces: targets.py, adaptive_parameters.py
Implements CFW6 stop/target logic + ATR-based adaptive thresholds

FIXED M8 (Mar 10 2026):
    calculate_stop_loss_by_grade() used or_low/or_high in the OR stop
    comparison even when they were 0.0 (opening range not yet formed —
    pre-10:00 AM signals). For bear direction this caused:
        or_stop = or_high * 1.001 = 0.0
        stop_price = min(atr_stop, 0.0) = 0.0
    A $0.00 stop blows up sizing math (infinite contracts) or causes
    the R:R guard in position_manager to reject a valid signal entirely.
    Fix: when or_low <= 0 or or_high <= 0, skip the OR boundary
    comparison and use the ATR stop exclusively.

FIXED Mar 13 2026:
    Low-vol FVG threshold lowered from 0.15% to 0.08%.
    On tight tape days (ATR < 1%), gaps rarely exceed 0.15% so watches
    expired on every ticker without ever finding an FVG. 0.08% matches
    the actual gap sizes seen on low-volatility sessions.

UPDATED Mar 19 2026 (47.P6-2 Sprint 1):
    get_adaptive_fvg_threshold() now uses get_atr_for_breakout() (live
    Wilder intraday ATR) for volatility bucket selection instead of the
    internal calculate_atr() which used session-filtered bars designed
    for stop/target math.  atr_source is logged for observability.
    compute_stop_and_targets() is unchanged — continues to use
    calculate_atr() for the TR-series stop calculations.
"""
from utils import config
import numpy as np
from datetime import time as dtime
from typing import List, Dict, Tuple
import logging
logger = logging.getLogger(__name__)

# ============================================================================
# ATR & VOLATILITY CALCULATIONS
# ============================================================================

def _filter_session_bars(bars: List[Dict]) -> List[Dict]:
    """
    Filter bars to regular session hours only (09:30 - 16:00 ET).
    Pre-market and after-hours bars have artificially wide spreads that
    inflate ATR and push stops too far from entry.
    Falls back to all bars if none pass the filter.
    """
    SESSION_START = dtime(9, 30)
    SESSION_END   = dtime(16, 0)
    filtered = []
    for b in bars:
        dt = b.get("datetime")
        if dt is None:
            continue
        t = dt.time() if hasattr(dt, "time") else None
        if t is not None and SESSION_START <= t <= SESSION_END:
            filtered.append(b)
    return filtered if filtered else bars


def calculate_atr(bars: List[Dict], period: int = 14) -> float:
    """Calculate Average True Range using session-only bars (09:30-16:00 ET).

    Pre-market candles are excluded so wide overnight spreads do not
    inflate the ATR and push stops artificially far from entry.

    NOTE: This function is intentionally kept for stop/target math in
    compute_stop_and_targets().  For volatility bucket selection
    (FVG thresholds, dynamic confidence thresholds) use
    get_atr_for_breakout() from app.data.intraday_atr instead.
    """
    session_bars = _filter_session_bars(bars)
    if len(session_bars) < period:
        return 0

    true_ranges = []
    for i in range(1, len(session_bars)):
        high       = session_bars[i]["high"]
        low        = session_bars[i]["low"]
        prev_close = session_bars[i-1]["close"]
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low  - prev_close)
        )
        true_ranges.append(tr)

    return np.mean(true_ranges[-period:]) if true_ranges else 0

# ============================================================================
# ADAPTIVE FVG THRESHOLDS
# ============================================================================

def get_adaptive_fvg_threshold(bars: List[Dict], ticker: str, rvol: float = None) -> Tuple[float, float]:
    """
    CFW6 OPTIMIZATION: Adaptive FVG size based on ticker volatility.

    47.P6-2 (Mar 19 2026): Uses get_atr_for_breakout() (Wilder intraday
    ATR on today's 1m session bars) for volatility bucket selection.
    Falls back to calculate_atr() (session-filtered bars) if intraday
    ATR returns 0 or errors.

    Returns: (fvg_threshold, confidence_adjustment)
    - High volatility (ATR > 2.0%): 0.30% minimum FVG, 0.95x confidence
    - Medium volatility (ATR 1.0-2.0%): 0.20% minimum FVG, 1.0x confidence
    - Low volatility (ATR < 1.0%): 0.08% minimum FVG, 1.05x confidence
      (lowered from 0.15% — tight tape days rarely produce gaps > 0.15%)
    """
    # 47.P6-2: primary ATR source — live Wilder intraday ATR
    atr_val    = 0.0
    atr_source = "NONE"
    try:
        from app.data.intraday_atr import get_atr_for_breakout
        atr_val, atr_source = get_atr_for_breakout(bars, ticker)
    except Exception as _atr_err:
        logger.info(f"[ADAPTIVE] {ticker} intraday ATR error (falling back): {_atr_err}")

    # Fallback: session-filtered ATR if intraday ATR returned 0
    if atr_val <= 0:
        atr_val    = calculate_atr(bars, period=14)
        atr_source = "SESSION_FILTERED"

    current_price = bars[-1]["close"] if bars else 0
    atr_pct       = (atr_val / current_price) * 100 if current_price > 0 else 0

    # RVOL-based threshold reduction for high momentum tickers
    if rvol is not None:
        _rvol = rvol
    else:
        try:
            from app.screening.watchlist_funnel import get_watchlist_with_metadata
            _wl = get_watchlist_with_metadata(force_refresh=False)
            _rvol = next(
                (t.get('rvol', 1.0) for t in _wl.get('all_tickers_with_scores', [])
                if t.get('ticker') == ticker), 1.0
            )
        except Exception:
            _rvol = 1.0

    if atr_pct > 2.0:
        fvg_threshold         = 0.003
        confidence_adjustment = 0.95
        volatility_label      = "HIGH"
    elif atr_pct > 1.0:
        fvg_threshold         = 0.002
        confidence_adjustment = 1.0
        volatility_label      = "MEDIUM"
    else:
        fvg_threshold         = 0.0008  # FIXED: was 0.0015 — too high for low-vol tape
        confidence_adjustment = 1.05
        volatility_label      = "LOW"

    # Lower threshold for high RVOL tickers (gap day movers)
    if _rvol >= 5.0:
        fvg_threshold = min(fvg_threshold, 0.001)
        logger.info(f"[ADAPTIVE] {ticker} HIGH RVOL ({_rvol:.1f}x) — FVG threshold lowered to {fvg_threshold*100:.2f}%")

    logger.info(
        f"[ADAPTIVE] {ticker} ATR={atr_val:.4f} ({atr_pct:.2f}% / {atr_source}) "
        f"— {volatility_label} volatility"
    )
    logger.info(f"  FVG threshold: {fvg_threshold*100:.2f}% | Confidence adj: {confidence_adjustment:.2f}x")
    return fvg_threshold, confidence_adjustment

# ============================================================================
# ADAPTIVE ORB THRESHOLDS
# ============================================================================

def calculate_volume_multiplier(bars: List[Dict], breakout_idx: int) -> float:
    """Calculate volume multiplier at breakout candle"""
    if breakout_idx < 20 or len(bars) <= breakout_idx:
        return 1.0
    avg_volume      = np.mean([b["volume"] for b in bars[breakout_idx-20:breakout_idx]])
    breakout_volume = bars[breakout_idx]["volume"]
    return breakout_volume / avg_volume if avg_volume > 0 else 1.0


def get_adaptive_orb_threshold(bars: List[Dict], breakout_idx: int) -> float:
    """
    CFW6 OPTIMIZATION: Volume-weighted ORB breakout confirmation
    - High volume breakout (2x+ avg): 0.08% threshold
    - Standard volume (1.5-2x avg):   0.10% threshold
    - Low volume (<1.5x avg):         0.15% threshold
    """
    volume_multiplier = calculate_volume_multiplier(bars, breakout_idx)
    if volume_multiplier >= 2.0:
        orb_threshold = 0.0008
        logger.info(f"[ADAPTIVE] High volume breakout ({volume_multiplier:.1f}x) - Using 0.08% threshold")
    elif volume_multiplier >= 1.5:
        orb_threshold = 0.001
        logger.info(f"[ADAPTIVE] Standard volume ({volume_multiplier:.1f}x) - Using 0.10% threshold")
    else:
        orb_threshold = 0.0015
        logger.info(f"[ADAPTIVE] Low volume ({volume_multiplier:.1f}x) - Using 0.15% threshold")
    return orb_threshold

# ============================================================================
# CONFIDENCE DECAY
# ============================================================================

def apply_confidence_decay(base_confidence: float, candles_waited: int) -> float:
    """
    CFW6 OPTIMIZATION: Penalize delayed confirmations
    - 0-5 candles:   No penalty
    - 6-10 candles:  -2% per candle
    - 11-15 candles: -3% per candle
    - 16+ candles:   -5% per candle
    """
    if candles_waited <= 5:
        decay = 0
    elif candles_waited <= 10:
        decay = (candles_waited - 5) * 0.02
    elif candles_waited <= 15:
        decay = 0.10 + (candles_waited - 10) * 0.03
    else:
        decay = 0.25 + (candles_waited - 15) * 0.05

    adjusted_confidence = base_confidence * (1 - decay)
    if candles_waited > 5:
        logger.info(f"[DECAY] Waited {candles_waited} candles - Confidence reduced by {decay*100:.1f}%")
        logger.info(f"  {base_confidence:.2%} -> {adjusted_confidence:.2%}")
    return max(adjusted_confidence, 0.50)

# ============================================================================
# STOP LOSS & TARGETS
# ============================================================================

def calculate_stop_loss_by_grade(
    entry_price: float,
    grade: str,
    direction: str,
    or_low: float,
    or_high: float,
    atr: float
) -> float:
    """
    CFW6 OPTIMIZATION: Grade-based stop loss with wider ATR multipliers
    A+: 2.0x ATR | A: 2.5x ATR | A-: 3.0x ATR
    Increased from previous (1.2x, 1.5x, 1.8x) to prevent "too tight" stops.
    Also respects Opening Range boundaries when ORB has formed.

    FIXED M8 (Mar 10 2026): or_low/or_high of 0.0 means the opening range
    has not yet been established (pre-10 AM signal). In that case the OR
    boundary comparison is skipped entirely so a zero stop is never
    produced. Callers do not need to change — passing 0.0 is safe.
    """
    atr_multipliers = {"A+": 2.0, "A": 2.5, "A-": 3.0, "B+": 3.5, "B": 4.0}
    atr_mult        = atr_multipliers.get(grade, 2.5)
    stop_distance   = atr * atr_mult

    # ── M8 FIX: only use OR boundary when the range has actually formed ──
    or_formed = (or_low > 0) and (or_high > 0)

    if direction == "bull":
        atr_stop = entry_price - stop_distance
        if or_formed:
            or_stop    = or_low * 0.999
            stop_price = max(atr_stop, or_stop)
            logger.info(
                f"[STOP] BULL {grade}: Entry ${entry_price:.2f} | "
                f"ATR stop ${atr_stop:.2f} | OR stop ${or_stop:.2f} | "
                f"Using ${stop_price:.2f}"
            )
        else:
            stop_price = atr_stop
            logger.info(
                f"[STOP] BULL {grade}: Entry ${entry_price:.2f} | "
                f"ATR stop ${atr_stop:.2f} | OR not formed — ATR only | "
                f"Using ${stop_price:.2f}"
            )
    else:  # bear
        atr_stop = entry_price + stop_distance
        if or_formed:
            or_stop    = or_high * 1.001
            stop_price = min(atr_stop, or_stop)
            logger.info(
                f"[STOP] BEAR {grade}: Entry ${entry_price:.2f} | "
                f"ATR stop ${atr_stop:.2f} | OR stop ${or_stop:.2f} | "
                f"Using ${stop_price:.2f}"
            )
        else:
            stop_price = atr_stop
            logger.info(
                f"[STOP] BEAR {grade}: Entry ${entry_price:.2f} | "
                f"ATR stop ${atr_stop:.2f} | OR not formed — ATR only | "
                f"Using ${stop_price:.2f}"
            )

    # FIX 10.C-4 (MAR 19 2026): guard against stop at or above entry on bull,
    # or at or below entry on bear — can happen on A+ high-vol tight-OR tape.
    if direction == "bull" and stop_price >= entry_price:
        return None
    elif direction == "bear" and stop_price <= entry_price:
        return None

    return stop_price


def calculate_targets_by_grade(
    entry_price: float,
    stop_price: float,
    grade: str,
    direction: str
) -> Tuple[float, float]:
    """
    T1 = 2R, T2 = 3.5R for all grades (per CFW6 video rules).
    """
    risk        = abs(entry_price - stop_price)
    t1_distance = risk * config.T1_MULTIPLIER
    t2_distance = risk * config.T2_MULTIPLIER

    if direction == "bull":
        t1 = entry_price + t1_distance
        t2 = entry_price + t2_distance
    else:
        t1 = entry_price - t1_distance
        t2 = entry_price - t2_distance

    logger.info(f"[TARGETS] {grade}: T1=${t1:.2f} (2R) | T2=${t2:.2f} (3.5R) | Risk/contract=${risk:.2f}")
    return t1, t2


def compute_stop_and_targets(
    bars: List[Dict],
    direction: str,
    or_high: float,
    or_low: float,
    entry_price: float,
    grade: str = "A"
) -> Tuple[float, float, float]:
    """
    Main entry point: compute stop and targets.
    ATR is derived from session-only bars (09:30-16:00 ET) so pre-market
    volatility does not widen stops.  Uses calculate_atr() (not intraday ATR)
    because stop math requires TR-series smoothing, not just a % bucket.
    Passing or_high=0 / or_low=0 is safe — the OR boundary is skipped
    and ATR stop is used exclusively (M8 fix).
    Returns: (stop_price, t1, t2)
    """
    atr        = calculate_atr(bars, period=14)
    stop_price = calculate_stop_loss_by_grade(
        entry_price, grade, direction, or_low, or_high, atr
    )
    if stop_price is None:
        return None, None, None
    t1, t2 = calculate_targets_by_grade(entry_price, stop_price, grade, direction)
    return stop_price, t1, t2
