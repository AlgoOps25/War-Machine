"""
Multi-Timeframe (MTF) Integration Module
Real BOS+FVG pattern detection across multiple timeframes

From video transcript (3:33-4:07):
"If you have a 1-minute, 2-minute, 3-minute, and 5-minute [signal],
you will go for the 5-minute. The highest time frame is going to be
the most powerful one. So if you have a few opportunities, a few
different FVG gaps, you will play the one that's on the highest time frame."

Implementation:
- Scans 1m, 2m, 3m, 5m charts for 9:30-9:45 OR breakout + FVG
- Detects when SAME pattern appears across multiple timeframes
- Prioritizes highest TF (5m strongest)
- Boosts confidence when lower TFs confirm the 5m signal

Confirmation Candle Types (2:02-3:22):
1. A+ (Strongest): Clean directional candle, minimal wicks
2. A (Strong): Opens opposite color, flips to signal direction
3. A- (Valid): Long rejection wick but doesn't fully close signal direction

Also contains Step 8.5 MTF Trend Validator (run_mtf_trend_step).
Moved here from app/core/sniper_mtf_trend_patch.py.

FIX 40.H-4 (MAR 19, 2026): STALE INTRA-DAY MTF CACHE
  - enhance_signal_with_mtf() keyed cache by `f"{ticker}_{direction}"` only.
    A 9:35 result was returned unchanged at 11:00 all session because the
    key never included bar count — no new bars ever invalidated the entry.
  - Fix: cache_key = f"{ticker}_{direction}_{len(bars_session)}" so any new
    bar causes a cache miss and a fresh MTF computation.

FIX 40.M-7 (MAR 19, 2026): ADAPTIVE FVG THRESHOLD NOT PROPAGATED TO MTF
  - detect_fvg() and scan_tf_for_signal() hardcoded config.FVG_MIN_SIZE_PCT,
    ignoring the per-call adaptive threshold supplied by sniper.py.
  - Fix: both functions accept an optional fvg_min_pct kwarg (default:
    config.FVG_MIN_SIZE_PCT). enhance_signal_with_mtf() accepts and forwards
    fvg_min_pct from its **kwargs so callers can pass the adaptive value.

FIX 40.M-9 (MAR 19, 2026): MTF OR WINDOW MISMATCHED WITH MAIN OR WINDOW
  - compute_or() used 9:30-9:40 (10 min) while the main OR window in
    opening_range.py uses 9:30-9:45 (15 min). MTF was computing a shorter
    OR, producing slightly different high/low levels and misaligned breakout
    detection vs. the main pipeline.
  - Fix: upper bound changed from time(9, 40) to time(9, 45).
"""
import logging
from datetime import datetime, time
from typing import List, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from utils import config

from .mtf_compression import compress_bars, compress_to_3m, compress_to_2m, compress_to_1m

ET = ZoneInfo("America/New_York")

logger = logging.getLogger(__name__)

GRADE_RANK: Dict[str, int] = {'A+': 0, 'A': 1, 'A-': 2}


def _is_better_grade(candidate: str, current_best: Optional[str]) -> bool:
    if current_best is None:
        return True
    return GRADE_RANK.get(candidate, 99) < GRADE_RANK.get(current_best, 99)


_mtf_stats = {
    'analyzed': 0,
    'convergence_found': 0,
    'timeframe_breakdown': {'5m_only': 0, '5m_3m': 0, '5m_3m_2m': 0, '5m_3m_2m_1m': 0},
    'confirmation_grades': {'A+': 0, 'A': 0, 'A-': 0},
    'total_boost': 0.0
}

_mtf_stats_lock = __import__('threading').Lock()

_cache_date = None
_mtf_cache = {}


def _check_cache_rollover():
    global _cache_date, _mtf_cache
    today = datetime.now(ET).date()
    if _cache_date != today:
        _mtf_cache.clear()
        _cache_date = today


# ── Opening Range ───────────────────────────────────────────────────────────────

def _bar_time(bar: dict) -> Optional[time]:
    bt = bar.get("datetime")
    if bt is None:
        return None
    return bt.time() if hasattr(bt, "time") else bt


def compute_or(bars: List[dict]) -> Tuple[Optional[float], Optional[float]]:
    # FIX 40.M-9: changed upper bound from time(9, 40) → time(9, 45) to match
    # the main 15-min OR window in opening_range.py (was 5 min shorter).
    or_bars = [b for b in bars if _bar_time(b) and time(9, 30) <= _bar_time(b) < time(9, 45)]
    if len(or_bars) < 2:
        return None, None
    return max(b["high"] for b in or_bars), min(b["low"] for b in or_bars)


# ── BOS+FVG Detection ───────────────────────────────────────────────────────────

def detect_breakout(bars, or_high, or_low):
    for i, bar in enumerate(bars):
        bt = _bar_time(bar)
        if bt is None or bt < time(9, 45):
            continue
        if bar["close"] > or_high * (1 + config.ORB_BREAK_THRESHOLD):
            return "bull", i
        if bar["close"] < or_low * (1 - config.ORB_BREAK_THRESHOLD):
            return "bear", i
    return None, None


def detect_fvg(bars, breakout_idx, direction,
               fvg_min_pct: float = None):
    """
    FIX 40.M-7: Accept optional fvg_min_pct so callers can pass the
    adaptive threshold from sniper.py instead of always using the
    config default. Falls back to config.FVG_MIN_SIZE_PCT if not supplied.
    """
    if fvg_min_pct is None:
        fvg_min_pct = config.FVG_MIN_SIZE_PCT

    for i in range(breakout_idx + 3, len(bars)):
        if i < 2:
            continue
        c0, c2 = bars[i - 2], bars[i]
        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= fvg_min_pct:
                return c0["high"], c2["low"]
        else:
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= fvg_min_pct:
                return c2["high"], c0["low"]
    return None, None


def grade_confirmation_candle(bar: dict, direction: str) -> Optional[str]:
    body = abs(bar['close'] - bar['open'])
    bar_range = bar['high'] - bar['low']
    if bar_range == 0:
        return None
    body_ratio = body / bar_range
    is_green = bar['close'] > bar['open']
    is_red   = bar['close'] < bar['open']
    if direction == 'bull':
        if is_green and body_ratio > 0.80:
            return 'A+'
        lower_wick = bar['close'] - bar['low']
        wick_ratio = lower_wick / bar_range
        if is_green and wick_ratio > 0.30 and body_ratio > 0.40:
            return 'A'
        if is_red and wick_ratio > 0.50:
            return 'A-'
    else:
        if is_red and body_ratio > 0.80:
            return 'A+'
        upper_wick = bar['high'] - bar['close']
        wick_ratio = upper_wick / bar_range
        if is_red and wick_ratio > 0.30 and body_ratio > 0.40:
            return 'A'
        if is_green and wick_ratio > 0.50:
            return 'A-'
    return None


def scan_tf_for_signal(bars: List[dict], tf_name: str,
                       fvg_min_pct: float = None) -> Optional[Dict]:
    """
    FIX 40.M-7: Accept optional fvg_min_pct and forward to detect_fvg()
    so the adaptive threshold from sniper.py propagates into all TF scans.
    """
    if len(bars) < 20:
        return None
    or_high, or_low = compute_or(bars)
    if or_high is None:
        return None
    direction, breakout_idx = detect_breakout(bars, or_high, or_low)
    if direction is None:
        return None
    fvg_low, fvg_high = detect_fvg(bars, breakout_idx, direction,
                                    fvg_min_pct=fvg_min_pct)
    if fvg_low is None:
        return None
    best_grade = None
    for i in range(breakout_idx + 3, min(breakout_idx + 10, len(bars))):
        bar = bars[i]
        if direction == 'bull':
            if bar['low'] <= fvg_high and bar['low'] >= fvg_low:
                grade = grade_confirmation_candle(bar, direction)
                if grade and _is_better_grade(grade, best_grade):
                    best_grade = grade
        else:
            if bar['high'] >= fvg_low and bar['high'] <= fvg_high:
                grade = grade_confirmation_candle(bar, direction)
                if grade and _is_better_grade(grade, best_grade):
                    best_grade = grade
    if best_grade is None:
        return None
    return {
        'timeframe': tf_name, 'direction': direction,
        'or_high': or_high, 'or_low': or_low, 'breakout_idx': breakout_idx,
        'fvg_low': fvg_low, 'fvg_high': fvg_high, 'confirmation_grade': best_grade
    }


# ── MTF Convergence ──────────────────────────────────────────────────────────────

def check_mtf_convergence(ticker: str, direction: str, bars_5m: List[dict],
                          fvg_min_pct: float = None) -> Dict:
    if len(bars_5m) < 30:
        return {
            'convergence': False, 'timeframes': ['5m'],
            'convergence_score': 0.25, 'boost': 0.0,
            'best_grade': None, 'reason': 'Insufficient bars for MTF analysis'
        }
    confirmed_timeframes = ['5m']
    confirmed_signals    = [{'timeframe': '5m', 'direction': direction}]
    best_confirmation_grade = None
    bars_3m = compress_bars(bars_5m, 3)
    bars_2m = compress_bars(bars_5m, 2)
    bars_1m = compress_bars(bars_5m, 1)
    for tf_bars, tf_name in [(bars_3m, '3m'), (bars_2m, '2m'), (bars_1m, '1m')]:
        signal = scan_tf_for_signal(tf_bars, tf_name, fvg_min_pct=fvg_min_pct)
        if signal and signal['direction'] == direction:
            confirmed_signals.append(signal)
            confirmed_timeframes.append(tf_name)
            if _is_better_grade(signal['confirmation_grade'], best_confirmation_grade):
                best_confirmation_grade = signal['confirmation_grade']
    num_timeframes = len(confirmed_timeframes)
    convergence    = num_timeframes > 1
    boost_map = {1: 0.00, 2: 0.02, 3: 0.03, 4: 0.05}
    boost = boost_map[num_timeframes]

    with _mtf_stats_lock:
        if convergence:
            _mtf_stats['convergence_found'] += 1
            _mtf_stats['total_boost'] += boost
            key = {2: '5m_3m', 3: '5m_3m_2m', 4: '5m_3m_2m_1m'}.get(num_timeframes)
            if key:
                _mtf_stats['timeframe_breakdown'][key] += 1
            if best_confirmation_grade:
                _mtf_stats['confirmation_grades'][best_confirmation_grade] += 1
        else:
            _mtf_stats['timeframe_breakdown']['5m_only'] += 1

    return {
        'convergence': convergence, 'timeframes': confirmed_timeframes,
        'convergence_score': num_timeframes / 4.0, 'boost': boost,
        'best_grade': best_confirmation_grade, 'signals': confirmed_signals,
        'reason': (
            f"BOS+FVG confirmed on {', '.join(confirmed_timeframes)}"
            if convergence else "5m signal only (no lower TF convergence)"
        )
    }


# ── Public API ───────────────────────────────────────────────────────────────────

def enhance_signal_with_mtf(ticker, direction, bars_session, **kwargs) -> Dict:
    """
    Enhance 5m BOS+FVG signal with multi-timeframe convergence.
    Called from sniper.py Step 8.2.

    FIX 40.H-4: Cache key now includes len(bars_session) so any new bar
    invalidates the cached result. Previously keyed only by ticker+direction,
    returning a stale 9:35 result at 11:00 for the entire session.

    FIX 40.M-7: Accepts fvg_min_pct from **kwargs and forwards it to
    check_mtf_convergence() so the adaptive threshold from sniper.py
    propagates into all sub-TF scans.
    """
    _check_cache_rollover()
    with _mtf_stats_lock:
        _mtf_stats['analyzed'] += 1

    cache_key = f"{ticker}_{direction}_{len(bars_session) if bars_session else 0}"
    if cache_key in _mtf_cache:
        return _mtf_cache[cache_key]

    fvg_min_pct = kwargs.get('fvg_min_pct', None)

    if not bars_session or len(bars_session) < 30:
        result = {
            'enabled': True, 'convergence': False, 'timeframes': ['5m'],
            'convergence_score': 0.25, 'boost': 0.0,
            'best_grade': None, 'reason': 'Insufficient bars for MTF'
        }
        _mtf_cache[cache_key] = result
        return result

    result = check_mtf_convergence(ticker, direction, bars_session,
                                   fvg_min_pct=fvg_min_pct)
    result['enabled'] = True
    _mtf_cache[cache_key] = result
    return result


def print_mtf_stats():
    if _mtf_stats['analyzed'] == 0:
        return
    conv_rate = (_mtf_stats['convergence_found'] / _mtf_stats['analyzed']) * 100
    avg_boost = _mtf_stats['total_boost'] / _mtf_stats['analyzed']
    logger.info("=" * 80)
    logger.info("MTF CONVERGENCE - DAILY STATISTICS")
    logger.info("=" * 80)
    logger.info("Session Date:         %s", _cache_date)
    logger.info("Signals Analyzed:     %d", _mtf_stats['analyzed'])
    logger.info("MTF Convergence:      %d (%.1f%%)", _mtf_stats['convergence_found'], conv_rate)
    logger.info("Average Boost:        %.2f%%", avg_boost * 100)
    logger.info("Timeframe Breakdown:")
    for k, label in [('5m_only', '5m only'), ('5m_3m', '5m + 3m'),
                     ('5m_3m_2m', '5m + 3m + 2m'), ('5m_3m_2m_1m', '5m + 3m + 2m + 1m')]:
        logger.info("  %-22s %d", label, _mtf_stats['timeframe_breakdown'][k])
    logger.info("Confirmation Grades:")
    for g, label in [('A+', 'A+ (Strongest)'), ('A', 'A (Strong)'), ('A-', 'A- (Valid)')]:
        logger.info("  %-18s %d", label, _mtf_stats['confirmation_grades'][g])


def reset_daily_stats():
    global _mtf_stats
    _mtf_stats = {
        'analyzed': 0, 'convergence_found': 0,
        'timeframe_breakdown': {'5m_only': 0, '5m_3m': 0, '5m_3m_2m': 0, '5m_3m_2m_1m': 0},
        'confirmation_grades': {'A+': 0, 'A': 0, 'A-': 0},
        'total_boost': 0.0
    }
    # Clear SMC context cache so stale CHoCH/OB/phase data doesn't bleed
    # into the next trading session.
    try:
        from app.mtf.smc_engine import clear_smc_cache
        clear_smc_cache()
    except Exception:
        pass


# ── Step 8.5: MTF Trend Validator ────────────────────────────────────────────────

try:
    from app.mtf.mtf_validator import validate_signal_mtf as _validate_signal_mtf
    _MTF_TREND_ENABLED = True
    logger.info("[MTF] MTF trend validator wired (Step 8.5)")
except ImportError as e:
    _MTF_TREND_ENABLED = False
    logger.warning("[MTF] MTF trend validator not available: %s", e)
    def _validate_signal_mtf(ticker, direction, entry_price=0.0):
        return {'passes': True, 'confidence_boost': 0.0, 'overall_score': 0.0,
                'divergences': [], 'summary': 'MTF trend disabled'}


def run_mtf_trend_step(
    ticker: str,
    direction: str,
    entry_price: float,
    confidence: float,
    signal_data: Dict,
) -> tuple:
    """
    Step 8.5 — MTF trend alignment check.
    Absorbed from app/core/sniper_mtf_trend_patch.py.
    Returns updated (confidence, signal_data). Never raises.
    """
    if not _MTF_TREND_ENABLED:
        return confidence, signal_data
    try:
        result = _validate_signal_mtf(ticker, direction, entry_price)
        boost  = result.get('confidence_boost', 0.0)
        signal_data['mtf_trend'] = {
            'score':       result.get('overall_score', 0.0),
            'passes':      result.get('passes', True),
            'boost':       boost,
            'divergences': result.get('divergences', []),
            'summary':     result.get('summary', ''),
            'tf_scores':   result.get('tf_scores', {}),
        }
        if result.get('passes', True) and boost > 0:
            confidence = min(0.95, confidence + boost)
            logger.info(
                "[STEP-8.5] %s MTF trend score=%.1f boost=+%.0f%% new_conf=%.3f",
                ticker, result['overall_score'], boost * 100, confidence
            )
        elif not result.get('passes', True):
            logger.info(
                "[STEP-8.5] %s MTF trend below threshold score=%.1f | %s",
                ticker, result['overall_score'], result.get('summary', '')
            )
        else:
            logger.debug(
                "[STEP-8.5] %s MTF trend neutral score=%.1f",
                ticker, result['overall_score']
            )
    except Exception as exc:
        logger.warning("[STEP-8.5] %s MTF trend error (non-fatal): %s", ticker, exc)
    return confidence, signal_data


logger.info("[MTF] Strategy: Scans 5m/3m/2m/1m for same OR breakout + FVG pattern")
logger.info("[MTF] Boost: +2%% (2 TFs), +3%% (3 TFs), +5%% (4 TFs - A+ setup)")
