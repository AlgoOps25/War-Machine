"""
app/backtesting/historical_trainer.py

Historical ML Training Pipeline
================================
Fetches OHLCV data from EODHD, replays War Machine signal logic bar-by-bar,
labels every signal WIN / LOSS / TIMEOUT by walking forward from the entry bar,
and returns a labelled DataFrame ready for ML training.

Design principles
-----------------
* No look-ahead bias  — labelling only uses bars strictly AFTER the entry bar.
* Walk-forward splits — train on early period, validate on recent period.
* Feature parity     — 15-feature vector matches MLSignalScorerV2._build_features().
* Self-contained     — no live DB required; all data comes from EODHD REST API.

Label quality fixes (Mar 2026)
------------------------------
* TARGET_MULT 2.0 → 1.5: tighter target requires a real directional
  move, not noise-driven drift. Reduces false WIN labels on choppy days.
* DEFAULT_TIMEOUT_BARS 20 → 12: 60-min window on 5m data. A breakout
  that hasn't resolved in 60 minutes is a failed trade.
* include_timeout default True: TIMEOUT signals are now included as LOSS
  rather than silently dropped. Stalling patterns are the most valuable
  negative examples for the model to learn from.

Feature audit fixes (Mar 2026)
------------------------------
* Dropped 9 permanently-dead features (zero variance, options-data deps).
* Dropped 4 redundant/near-zero-correlation features (BUG-11):
    is_bull         — constant 1.0 (direction always 'bull'), NaN corr
    explosive_mover — redundant binary of continuous rvol, corr=0.024
    grade_norm      — redundant transform of confidence/score, corr=0.051
    mtf_boost       — redundant float of mtf_convergence_count, corr=0.068
* Added 4 outcome-correlated features (BUG-11):
    vwap_side        — +1/-1 sign of vwap_distance (above/below VWAP)
    atr_ratio        — current ATR / 20-bar avg ATR (volatility expansion)
    time_bucket      — session period: 0=open, 1=mid, 2=close (norm /2)
    resist_proximity — (close - resistance) / atr (breakout decisiveness)
* MTF: slope-based convergence across 5m/15m/60m (BUG-10).
* is_or_signal: True when breakout bar falls within first OR_WINDOW_BARS.
* pattern: 'FVG' when Fair Value Gap on prior 3 bars, else 'BOS'.
* Feature count: 15 real, discriminative, non-redundant features.

Bug fixes applied
-----------------
* BUG 1:  Skip intraday endpoint when interval='d' (EODHD 422).
* BUG 2:  _safe_float() handles EODHD null volume/price fields.
* BUG 3:  Daily-calibrated thresholds.
* BUG 4:  Filter after-hours zero-volume bars.
* BUG 5:  _rvol() and _vwap_distance() guard against zero-volume bars.
* BUG 6:  _or_range() uses session_bars not full history window.
* BUG 7:  _mtf_convergence() slices MTF_LOOKBACK_BARS before resampling.
* BUG 8:  is_or_signal uses session bar count not absolute index.
* BUG 9:  MTF asks direction-aware bull confirmation not all-same test.
* BUG 10: MTF uses SMA slope (sma_now > sma_prev) not price position.
* BUG 11: Dropped 4 dead/redundant features; added 4 outcome-correlated.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False
    logger.error("[HIST-TRAINER] pandas/numpy not installed — historical training unavailable")

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False
    logger.error("[HIST-TRAINER] requests not installed")


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
EODHD_BASE            = "https://eodhd.com/api"
DEFAULT_TIMEOUT_BARS  = 12    # 60 min on 5m data
MIN_SIGNAL_BARS       = 30    # min bars before scanning (intraday)
MIN_SIGNAL_BARS_DAILY = 5     # min bars for daily
STOP_MULT             = 1.0   # stop_loss = entry - ATR * STOP_MULT
TARGET_MULT           = 1.5   # target    = entry + ATR * TARGET_MULT
RVOL_MIN_DAILY        = 1.3

OR_WINDOW_BARS    = 12   # first 60 min of session on 5m data
MTF_LOOKBACK_BARS = 180  # ~3 sessions of 5m bars for MTF resampling

# Market hours UTC: 14:30–21:00 (= 09:30–16:00 ET)
MARKET_OPEN_UTC_H  = 14
MARKET_OPEN_UTC_M  = 30
MARKET_CLOSE_UTC_H = 21
MARKET_CLOSE_UTC_M = 0

_INTRADAY_INTERVALS = {'1m', '5m', '15m', '1h'}

# Session time buckets (UTC hours)
# 0 = open  : 14:30–16:00 UTC (09:30–11:00 ET)
# 1 = mid   : 16:00–19:00 UTC (11:00–14:00 ET)
# 2 = close : 19:00–21:00 UTC (14:00–16:00 ET)
_TIME_BUCKET_BOUNDARIES = [(14, 16), (16, 19), (19, 21)]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — data cleaning
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    """BUG-2: EODHD returns null; .get('volume', 0) returns None not 0."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_market_hours(dt_str: str) -> bool:
    """BUG-4: Returns True only for bars within regular market hours (UTC)."""
    if not dt_str or not isinstance(dt_str, str):
        return True
    try:
        dt_str_clean = dt_str.replace('T', ' ').split('.')[0]
        dt = datetime.strptime(dt_str_clean, '%Y-%m-%d %H:%M:%S')
        open_mins  = MARKET_OPEN_UTC_H  * 60 + MARKET_OPEN_UTC_M
        close_mins = MARKET_CLOSE_UTC_H * 60 + MARKET_CLOSE_UTC_M
        bar_mins   = dt.hour * 60 + dt.minute
        return open_mins <= bar_mins < close_mins
    except (ValueError, AttributeError):
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — EODHD data fetching
# ─────────────────────────────────────────────────────────────────────────────

def _eodhd_intraday(
    ticker:   str,
    api_key:  str,
    interval: str = '5m',
    from_dt:  Optional[datetime] = None,
    to_dt:    Optional[datetime] = None,
) -> List[Dict]:
    """Fetch intraday OHLCV bars from EODHD, market hours only (BUG-4)."""
    if interval not in _INTRADAY_INTERVALS:  # BUG-1
        return []
    if not _REQUESTS_OK:
        return []

    params: Dict = {'api_token': api_key, 'fmt': 'json', 'interval': interval}
    if from_dt:
        params['from'] = int(from_dt.timestamp())
    if to_dt:
        params['to']   = int(to_dt.timestamp())

    url = f"{EODHD_BASE}/intraday/{ticker}.US"
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        if not isinstance(raw, list):
            logger.warning(f"[HIST-TRAINER] Unexpected intraday response for {ticker}: {type(raw)}")
            return []

        bars, skipped_hours, skipped_vol = [], 0, 0
        for b in raw:
            dt_str = b.get('datetime') or b.get('date', '')
            if not _is_market_hours(dt_str):
                skipped_hours += 1
                continue
            o = _safe_float(b.get('open'))
            h = _safe_float(b.get('high'))
            l = _safe_float(b.get('low'))
            c = _safe_float(b.get('close'))
            v = _safe_float(b.get('volume'))
            if c == 0.0 or v == 0.0:
                skipped_vol += 1
                continue
            bars.append({'timestamp': dt_str, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v})

        logger.debug(
            f"[HIST-TRAINER] {ticker}: {len(bars)} market-hours bars kept, "
            f"{skipped_hours} off-hours dropped, {skipped_vol} zero-vol dropped"
        )
        return bars
    except Exception as exc:
        logger.warning(f"[HIST-TRAINER] EODHD intraday fetch failed for {ticker}: {exc}")
        return []


def _eodhd_eod(
    ticker:  str,
    api_key: str,
    from_dt: Optional[datetime] = None,
    to_dt:   Optional[datetime] = None,
) -> List[Dict]:
    """Fetch daily OHLCV bars from EODHD EOD endpoint."""
    if not _REQUESTS_OK:
        return []
    params: Dict = {'api_token': api_key, 'fmt': 'json', 'period': 'd'}
    if from_dt:
        params['from'] = from_dt.strftime('%Y-%m-%d')
    if to_dt:
        params['to']   = to_dt.strftime('%Y-%m-%d')

    url = f"{EODHD_BASE}/eod/{ticker}.US"
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        if not isinstance(raw, list):
            logger.warning(f"[HIST-TRAINER] Unexpected EOD response for {ticker}: {type(raw)}")
            return []
        bars = []
        for b in raw:
            c = _safe_float(b.get('adjusted_close') or b.get('close'))
            if c == 0.0:
                continue
            bars.append({
                'timestamp': b.get('date', ''),
                'open':   _safe_float(b.get('open')),
                'high':   _safe_float(b.get('high')),
                'low':    _safe_float(b.get('low')),
                'close':  c,
                'volume': _safe_float(b.get('volume')),
            })
        return bars
    except Exception as exc:
        logger.warning(f"[HIST-TRAINER] EODHD EOD fetch failed for {ticker}: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Technical indicator helpers
# ─────────────────────────────────────────────────────────────────────────────

def _atr(bars: List[Dict], period: int = 14) -> float:
    """Average True Range over last `period` bars."""
    if len(bars) < 2:
        return bars[-1]['high'] - bars[-1]['low'] if bars else 0.01
    trs = []
    for i in range(max(1, len(bars) - period), len(bars)):
        b, prev = bars[i], bars[i - 1]
        trs.append(max(
            b['high'] - b['low'],
            abs(b['high'] - prev['close']),
            abs(b['low']  - prev['close']),
        ))
    return sum(trs) / len(trs) if trs else 0.01


def _atr_avg(bars: List[Dict], period: int = 14, lookback: int = 20) -> float:
    """
    Average of ATR computed at each of the last `lookback` positions.
    Used to compute atr_ratio = current_atr / avg_atr (BUG-11).
    Expanding atr_ratio >1.0 signals a trend day; contracting <1.0 signals chop.
    """
    if len(bars) < period + lookback:
        return _atr(bars, period)
    atrs = [_atr(bars[:-(lookback - i - 1)] if i < lookback - 1 else bars, period)
            for i in range(lookback)]
    return sum(atrs) / len(atrs) if atrs else 0.01


def _rvol(bars: List[Dict], lookback: int = 20) -> float:
    """Relative volume vs avg of prior `lookback` bars. BUG-5."""
    if len(bars) < 2:
        return 1.0
    recent = [b for b in bars[-(lookback + 1):-1] if b['volume'] > 0]
    if not recent:
        return 1.0
    avg = sum(b['volume'] for b in recent) / len(recent)
    return bars[-1]['volume'] / avg if avg > 0 else 1.0


def _resistance(bars: List[Dict], lookback: int = 20) -> float:
    """
    Resistance = highest high over lookback bars, but only if price
    has stayed below it for at least 3 of the last 5 bars (confluence test).
    Falls back to raw high if no confluence found.
    """
    window = bars[-lookback - 1:-1]
    if not window:
        return bars[-1]['high']
    
    level = max(b['high'] for b in window)
    
    # Require price to have respected this level (not just grazed it once)
    recent = bars[-6:-1]
    rejections = sum(1 for b in recent if b['high'] < level * 0.999)
    if rejections >= 3:
        return level
    
    # Fallback: use a longer lookback for a more established level
    wider = bars[-40:-1] if len(bars) >= 40 else window
    return max(b['high'] for b in wider)


def _adx_approx(bars: List[Dict], period: int = 14) -> float:
    """Approximate ADX (0–100) using Wilder smoothing."""
    if len(bars) < period + 2:
        return 20.0
    slice_ = bars[-(period * 2):]
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(slice_)):
        b, p = slice_[i], slice_[i - 1]
        up   = b['high'] - p['high']
        down = p['low']  - b['low']
        plus_dm.append(up   if up > down and up > 0   else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr_list.append(max(
            b['high'] - b['low'],
            abs(b['high'] - p['close']),
            abs(b['low']  - p['close']),
        ))

    def wilder(lst, n):
        s = sum(lst[:n])
        res = [s]
        for v in lst[n:]:
            s = s - s / n + v
            res.append(s)
        return res

    if len(tr_list) < period:
        return 20.0
    atr14  = wilder(tr_list,  period)
    pdi14  = wilder(plus_dm,  period)
    mdi14  = wilder(minus_dm, period)
    dx_list = []
    for a, p2, m in zip(atr14, pdi14, mdi14):
        if a == 0:
            continue
        pdi = 100 * p2 / a
        mdi = 100 * m  / a
        dx  = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0
        dx_list.append(dx)
    return sum(dx_list) / len(dx_list) if dx_list else 20.0


def _vwap_distance(bars: List[Dict]) -> float:
    """Distance of last close from session VWAP as fraction of close. BUG-5."""
    vol_bars = [b for b in bars if b['volume'] > 0]
    if not vol_bars:
        return 0.0
    tp_vol = sum((b['high'] + b['low'] + b['close']) / 3 * b['volume'] for b in vol_bars)
    vol    = sum(b['volume'] for b in vol_bars)
    vwap   = tp_vol / vol if vol > 0 else bars[-1]['close']
    return (bars[-1]['close'] - vwap) / vwap if vwap > 0 else 0.0


def _or_range(session_bars: List[Dict], or_bars: int = 6) -> float:
    """
    Opening Range as % of price: high-low of first `or_bars` bars of session.
    BUG-6 FIX: uses session_bars not full history.
    """
    window = session_bars[:or_bars] if len(session_bars) >= or_bars else session_bars
    if not window:
        return 0.01
    hi  = max(b['high'] for b in window)
    lo  = min(b['low']  for b in window)
    mid = (hi + lo) / 2
    return (hi - lo) / mid if mid > 0 else 0.01


def _regime(spy_bars: List[Dict]) -> str:
    """Crude regime: BULL if SPY close > 20-bar SMA, else BEAR."""
    if len(spy_bars) < 20:
        return 'NEUTRAL'
    sma = sum(b['close'] for b in spy_bars[-20:]) / 20
    return 'BULL' if spy_bars[-1]['close'] > sma else 'BEAR'


def _sma(bars: List[Dict], period: int) -> float:
    """Simple moving average of close over last `period` bars."""
    window = [b['close'] for b in bars[-period:] if b['close'] > 0]
    return sum(window) / len(window) if window else 0.0


def _is_bull_trend_slope(bars: List[Dict], sma_period: int, slope_bars: int) -> bool:
    """
    BUG-10: Returns True if the SMA is currently RISING (momentum test).
    sma_now > sma_prev — detects accelerating momentum regardless of regime.
    """
    if len(bars) < sma_period + slope_bars:
        return False
    sma_now  = _sma(bars,               sma_period)
    sma_prev = _sma(bars[:-slope_bars], sma_period)
    return sma_now > sma_prev if (sma_now > 0 and sma_prev > 0) else False


def _time_bucket(hour_utc: int) -> int:
    """
    BUG-11: Classify UTC hour into intraday session bucket.
    0 = open  (14:30–16:00 UTC / 09:30–11:00 ET)
    1 = mid   (16:00–19:00 UTC / 11:00–14:00 ET)
    2 = close (19:00–21:00 UTC / 14:00–16:00 ET)
    Returns 1 (mid) for any out-of-range hour.
    """
    for bucket, (start, end) in enumerate(_TIME_BUCKET_BOUNDARIES):
        if start <= hour_utc < end:
            return bucket
    return 1


def _mtf_convergence(bars: List[Dict]) -> Tuple[bool, int]:
    """
    Multi-timeframe SMA-slope momentum convergence.
    BUG-10: slope-based (sma_now > sma_prev) not position-based (close > SMA).
    BUG-11: removed mtf_boost return value (redundant float of count).

    Returns
    -------
    mtf_convergence       : bool  True when all 3 TF SMAs are rising
    mtf_convergence_count : int   0–3 timeframes with rising SMA
    """
    if len(bars) < 13:
        return False, 0

    recent = bars[-MTF_LOOKBACK_BARS:]  # BUG-7: avoid month-old SMA drag

    bull_5m = _is_bull_trend_slope(recent, sma_period=10, slope_bars=3)

    def _resample(bars_5m: List[Dict], n: int) -> List[Dict]:
        out = []
        for i in range(0, len(bars_5m) - n + 1, n):
            chunk = bars_5m[i:i + n]
            out.append({
                'open':   chunk[0]['open'],
                'high':   max(b['high']  for b in chunk),
                'low':    min(b['low']   for b in chunk),
                'close':  chunk[-1]['close'],
                'volume': sum(b['volume'] for b in chunk),
            })
        return out

    bars_15m = _resample(recent, 3)
    bull_15m = _is_bull_trend_slope(bars_15m, sma_period=5, slope_bars=2) if bars_15m else False

    bars_60m = _resample(recent, 12)
    bull_60m = _is_bull_trend_slope(bars_60m, sma_period=3, slope_bars=1) if bars_60m else False

    count = sum([bull_5m, bull_15m, bull_60m])
    return count == 3, count


def _find_swing_high(bars: List[Dict], lookback: int = 10) -> Optional[float]:
    """
    True swing high: bar[i].high > all bars within ±lookback/2 window.
    Mirrors bos_fvg_engine.find_swing_points() logic exactly.
    """
    recent = bars[-(lookback * 3):]
    swing_high = None
    half = lookback // 2
    for i in range(half, len(recent) - half):
        window = recent[i - half: i + half + 1]
        bar = recent[i]
        if bar['high'] == max(b['high'] for b in window):
            if swing_high is None or bar['high'] > swing_high:
                swing_high = bar['high']
    return swing_high


def _find_swing_low(bars: List[Dict], lookback: int = 10) -> Optional[float]:
    """
    True swing low: bar[i].low < all bars within ±lookback/2 window.
    """
    recent = bars[-(lookback * 3):]
    swing_low = None
    half = lookback // 2
    for i in range(half, len(recent) - half):
        window = recent[i - half: i + half + 1]
        bar = recent[i]
        if bar['low'] == min(b['low'] for b in window):
            if swing_low is None or bar['low'] < swing_low:
                swing_low = bar['low']
    return swing_low


def _find_fvg(bars: List[Dict], direction: str,
              bos_idx: int) -> Optional[Dict]:
    """
    Scan forward from BOS index for first valid FVG.
    Bull FVG: bars[i-2].high < bars[i].low  (gap above)
    Bear FVG: bars[i-2].low  > bars[i].high (gap below)
    Mirrors bos_fvg_engine.find_fvg_after_bos() exactly.
    """
    search_start = max(0, bos_idx - 5)
    search_bars  = bars[search_start:]
    for i in range(2, len(search_bars)):
        c0, c2 = search_bars[i - 2], search_bars[i]
        if direction == 'bull':
            gap = c2['low'] - c0['high']
            if gap > 0:
                return {
                    'fvg_high':     c2['low'],
                    'fvg_low':      c0['high'],
                    'fvg_mid':      (c2['low'] + c0['high']) / 2,
                    'fvg_size':     gap,
                    'fvg_size_pct': gap / c0['high'] if c0['high'] > 0 else 0.0,
                }
        elif direction == 'bear':
            gap = c0['low'] - c2['high']
            if gap > 0:
                return {
                    'fvg_high':     c0['low'],
                    'fvg_low':      c2['high'],
                    'fvg_mid':      (c0['low'] + c2['high']) / 2,
                    'fvg_size':     gap,
                    'fvg_size_pct': gap / c0['low'] if c0['low'] > 0 else 0.0,
                }
    return None


def _classify_confirmation_candle(bar: Dict, direction: str) -> float:
    """
    Grade the FVG retest candle. Mirrors bos_fvg_engine.classify_confirmation_candle().
    Returns normalised score: 1.0=A+, 0.85=A, 0.70=A-, 0.0=no confirmation.
    """
    o, h, l, c = bar['open'], bar['high'], bar['low'], bar['close']
    body        = abs(c - o)
    total_range = h - l
    if total_range == 0:
        return 0.0

    if direction == 'bull':
        lower_wick = (o - l) if c >= o else (c - l)
        is_green   = c > o
        is_red     = c < o
        if is_green and (lower_wick / total_range) < 0.20:
            return 1.00   # A+
        if is_green and (lower_wick / total_range) >= 0.30:
            return 0.85   # A
        if is_red   and (lower_wick / total_range) >= 0.50:
            return 0.70   # A-
    elif direction == 'bear':
        upper_wick = (h - o) if c <= o else (h - c)
        is_red     = c < o
        is_green   = c > o
        if is_red   and (upper_wick / total_range) < 0.20:
            return 1.00   # A+
        if is_red   and (upper_wick / total_range) >= 0.30:
            return 0.85   # A
        if is_green and (upper_wick / total_range) >= 0.50:
            return 0.70   # A-
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Signal detector (mirrors BreakoutDetector logic)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_signal(
    bars:          List[Dict],
    spy_bars:      List[Dict],
    rvol_min:      float = 2.0,
    lookback:      int   = 12,
    is_daily:      bool  = False,
    session_bars:  Optional[List[Dict]] = None,
) -> Optional[Dict]:
    """
    BOS + FVG + retest + confirmation entry logic.
    Mirrors bos_fvg_engine.scan_bos_fvg() exactly so training data
    reflects actual live entry quality.

    Flow:
      1. Detect BOS (close > swing high OR close < swing low)
      2. Find FVG after BOS
      3. Check previous bar retested FVG zone
      4. Grade confirmation candle (A+/A/A-)
      5. Entry = current bar (next bar after confirmation)
    """
    min_bars = MIN_SIGNAL_BARS_DAILY if is_daily else MIN_SIGNAL_BARS
    if len(bars) < min_bars + 2:
        return None

    # Need at least prev bar (confirmation) + current bar (entry)
    rv = _rvol(bars)
    if rv < rvol_min:
        return None

    # ── Step 1: BOS detection ─────────────────────────────────────────────
    # Use bars[:-1] to find structure, then check if bars[-1] breaks it
    structure_bars = bars[:-1]
    latest         = bars[-1]
    prev           = bars[-2]

    swing_high = _find_swing_high(structure_bars, lookback=10)
    swing_low  = _find_swing_low(structure_bars,  lookback=10)

    direction    = None
    bos_price    = None
    bos_strength = 0.0

    if swing_high and latest['close'] > swing_high:
        direction    = 'bull'
        bos_price    = swing_high
        bos_strength = (latest['close'] - swing_high) / swing_high
    elif swing_low and latest['close'] < swing_low:
        direction    = 'bear'
        bos_price    = swing_low
        bos_strength = (swing_low - latest['close']) / swing_low

    if direction is None:
        return None

    # ── Step 2: Find FVG after BOS ────────────────────────────────────────
    bos_idx = len(bars) - 1
    fvg     = _find_fvg(bars, direction, bos_idx)
    if fvg is None:
        return None

    # ── Step 3: Check previous bar retested FVG zone ─────────────────────
    price_in_fvg = False
    if direction == 'bull':
        if prev['low'] <= fvg['fvg_high'] and prev['close'] >= fvg['fvg_low']:
            price_in_fvg = True
    elif direction == 'bear':
        if prev['high'] >= fvg['fvg_low'] and prev['close'] <= fvg['fvg_high']:
            price_in_fvg = True

    if not price_in_fvg:
        return None

    # ── Step 4: Grade confirmation candle (prev bar) ──────────────────────
    conf_score = _classify_confirmation_candle(prev, direction)
    if conf_score == 0.0:
        return None   # No valid confirmation — skip

    # ── Step 5: Entry = current bar (next bar after confirmation) ─────────
    entry = latest['open']   # Enter at open of bar after confirmation
    atr   = _atr(bars)
    if atr == 0:
        return None

    # FVG-based stop (mirrors bos_fvg_engine.compute_0dte_stops_and_targets)
    fvg_size = fvg['fvg_size']
    buffer   = fvg_size * 0.20
    if direction == 'bull':
        stop_loss = fvg['fvg_low'] - buffer
    else:
        stop_loss = fvg['fvg_high'] + buffer

    risk   = abs(entry - stop_loss)
    target = (entry + risk * 1.5) if direction == 'bull' else (entry - risk * 1.5)

    # ── Compute remaining features ────────────────────────────────────────
    adx       = _adx_approx(bars)
    vwap_dist = _vwap_distance(bars)
    hour      = _parse_hour(latest['timestamp'])
    atr_pct   = atr / entry if entry > 0 else 0.0
    avg_atr   = _atr_avg(bars, period=14, lookback=20)
    atr_ratio = (atr / avg_atr) if avg_atr > 0 else 1.0
    vwap_side = 1.0 if vwap_dist >= 0 else -1.0
    tb        = _time_bucket(hour)

    sess         = session_bars if session_bars else bars
    or_range_pct = _or_range(sess)
    is_or        = len(sess) <= OR_WINDOW_BARS

    resist_prox  = min(bos_strength * 100, 3.0) / 3.0   # reuse bos_strength as breakout decisiveness

    mtf_conv, mtf_count = _mtf_convergence(bars)

    confidence = min(0.5 + (rv - rvol_min) * 0.05 + adx * 0.003 + conf_score * 0.1, 0.95)
    score      = int(confidence * 100)

    # SPY EMA regime
    spy_regime_val = 0.0
    if spy_bars and len(spy_bars) >= 50:
        spy_closes = [b['close'] for b in spy_bars]
        def _ema_local(vals, p):
            k = 2.0 / (p + 1)
            r = [vals[0]]
            for v in vals[1:]:
                r.append(v * k + r[-1] * (1 - k))
            return r
        e20   = _ema_local(spy_closes, 20)
        e50   = _ema_local(spy_closes, 50)
        slope = e20[-1] - e20[-6] if len(e20) >= 6 else 0
        if e20[-1] > e50[-1] and slope > 0:
            spy_regime_val = 1.0
        elif e20[-1] < e50[-1] and slope < 0:
            spy_regime_val = -1.0

    return {
        'entry':                 entry,
        'stop_loss':             stop_loss,
        'target':                target,
        'bar_index':             len(bars) - 1,
        'timestamp':             latest['timestamp'],
        'direction':             direction,
        'confidence':            confidence,
        'rvol':                  rv,
        'score':                 score,
        'mtf_convergence':       mtf_conv,
        'mtf_convergence_count': mtf_count,
        'vwap_distance':         vwap_dist,
        'vwap_side':             vwap_side,
        'or_range_pct':          or_range_pct,
        'adx':                   adx,
        'atr_pct':               atr_pct,
        'atr_ratio':             atr_ratio,
        'signal_type':           'CFW6_OR' if is_or else 'BREAKOUT',
        'hour':                  hour,
        'time_bucket':           tb,
        'resist_proximity':      resist_prox,
        'conf_score':            conf_score,          # NEW: candle grade
        'fvg_size_pct':          fvg['fvg_size_pct'], # NEW: FVG quality
        'bos_strength':          bos_strength,        # NEW: breakout decisiveness
        'spy_regime':            spy_regime_val,
    }

def _parse_hour(ts) -> int:
    """Extract UTC hour from EODHD datetime string or epoch int."""
    try:
        if isinstance(ts, (int, float)):
            return datetime.utcfromtimestamp(ts).hour
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(str(ts), fmt).hour
            except ValueError:
                continue
    except Exception:
        pass
    return 14


def _score_to_grade(score: int) -> str:
    if score >= 90: return 'A+'
    if score >= 85: return 'A'
    if score >= 80: return 'A-'
    if score >= 75: return 'B+'
    if score >= 70: return 'B'
    if score >= 65: return 'B-'
    if score >= 60: return 'C+'
    if score >= 55: return 'C'
    return 'C-'


# ─────────────────────────────────────────────────────────────────────────────
# Outcome labeller (strict no-look-ahead)
# ─────────────────────────────────────────────────────────────────────────────

def _label_outcome(
    signal:       Dict,
    all_bars:     List[Dict],
    timeout_bars: int = DEFAULT_TIMEOUT_BARS,
) -> str:
    """
    Walk forward from entry bar and label WIN / LOSS / TIMEOUT.
    WIN     — high >= target  before low <= stop_loss
    LOSS    — low  <= stop_loss before high >= target
    TIMEOUT — neither hit within timeout_bars bars
    """
    entry_idx = signal['bar_index']
    target    = signal['target']
    stop_loss = signal['stop_loss']
    future    = all_bars[entry_idx + 1: entry_idx + 1 + timeout_bars]
    for bar in future:
        if bar['high'] >= target:
            return 'WIN'
        if bar['low']  <= stop_loss:
            return 'LOSS'
    return 'TIMEOUT'


# ─────────────────────────────────────────────────────────────────────────────
# Feature vector builder — 15 real, non-redundant features
# ─────────────────────────────────────────────────────────────────────────────

# Dropped (BUG-11):
#   grade_norm      — redundant transform of confidence/score_norm
#   mtf_boost       — redundant float encoding of mtf_convergence_count
#   is_bull         — constant 1.0 (always 'bull'), NaN correlation
#   explosive_mover — redundant binary bucket of continuous rvol
#
# Added (BUG-11):
#   vwap_side        — sign of vwap_distance (+1 above / -1 below VWAP)
#   atr_ratio        — current ATR / 20-bar avg ATR (volatility expansion)
#   time_bucket_norm — session period 0/1/2 normalised to [0,1]
#   resist_proximity — (close - resistance) / atr, clipped [0,3]/3
FEATURE_NAMES = [
    'confidence',
    'rvol',
    'score_norm',
    'mtf_convergence',
    'mtf_convergence_count',
    'vwap_distance',
    'vwap_side',
    'or_range_pct',
    'adx_norm',
    'atr_pct',
    'atr_ratio',
    'is_or_signal',
    'hour_norm',
    'time_bucket_norm',
    'resist_proximity',
    'ticker_win_rate',
    'spy_regime',
    'conf_score',
    'fvg_size_pct',
    'bos_strength',
]


def _signal_to_features(sig: Dict) -> List[float]:
    return [
        sig.get('confidence', 0.70),
        sig.get('rvol', 1.0),
        sig.get('score', 50) / 100.0,
        float(sig.get('mtf_convergence', False)),
        sig.get('mtf_convergence_count', 0) / 3.0,
        sig.get('vwap_distance', 0.0),
        sig.get('vwap_side', 1.0),
        sig.get('or_range_pct', 0.01),
        sig.get('adx', 20.0) / 50.0,
        sig.get('atr_pct', 0.01),
        min(sig.get('atr_ratio', 1.0), 3.0) / 3.0,
        1.0 if sig.get('signal_type') == 'CFW6_OR' else 0.0,
        sig.get('hour', 14) / 21.0,
        sig.get('time_bucket', 1) / 2.0,
        sig.get('resist_proximity', 0.0),
        # new features (neutral fallbacks so current dataset still works)
        sig.get('ticker_win_rate', 0.40),
        sig.get('spy_regime', 0.0),
        sig.get('conf_score', 0.0),
        min(sig.get('fvg_size_pct', 0.0), 0.02) / 0.02,
        min(sig.get('bos_strength', 0.0), 0.01) / 0.01,
    ]

# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class HistoricalMLTrainer:
    """
    Builds a labelled ML training dataset from EODHD historical OHLCV data.
    """

    def __init__(
        self,
        eodhd_api_key: Optional[str] = None,
        interval:      str   = '5m',
        rvol_min:      float = 2.0,
        lookback:      int   = 12,
        timeout_bars:  int   = DEFAULT_TIMEOUT_BARS,
    ):
        self.api_key      = eodhd_api_key or os.getenv('EODHD_API_KEY', '')
        self.interval     = interval
        self.rvol_min     = rvol_min
        self.lookback     = lookback
        self.timeout_bars = timeout_bars
        if not self.api_key:
            logger.warning("[HIST-TRAINER] No EODHD_API_KEY — data fetches will fail")

    def fetch_bars(
        self,
        ticker:      str,
        months_back: int = 12,
        interval:    Optional[str] = None,
    ) -> List[Dict]:
        """Fetch historical bars, routing to the correct EODHD endpoint."""
        iv      = interval or self.interval
        to_dt   = datetime.now(timezone.utc).replace(tzinfo=None)
        from_dt = to_dt - timedelta(days=months_back * 30)
        logger.info(f"[HIST-TRAINER] Fetching {ticker} ({from_dt.date()} → {to_dt.date()}, interval={iv})")

        if iv in _INTRADAY_INTERVALS:
            bars = _eodhd_intraday(ticker, self.api_key, iv, from_dt, to_dt)
            if not bars:
                logger.info(f"[HIST-TRAINER] Intraday empty for {ticker} — falling back to EOD")
                bars = _eodhd_eod(ticker, self.api_key, from_dt, to_dt)
        else:
            bars = _eodhd_eod(ticker, self.api_key, from_dt, to_dt)

        logger.info(f"[HIST-TRAINER] {ticker}: {len(bars)} bars fetched (market hours only)")
        return bars

    def replay_ticker(
        self,
        ticker:   str,
        bars:     List[Dict],
        spy_bars: Optional[List[Dict]] = None,
        is_daily: bool = False,
    ) -> List[Dict]:
        """
        Replay signal detection bar-by-bar and label outcomes.
        session_bars slice passed to _detect_signal() for BUG-6/8 fixes.
        """
        if not bars:
            return []

        effective_rvol  = RVOL_MIN_DAILY if is_daily else self.rvol_min
        spy_ref         = spy_bars or []
        signals         = []
        seen_idx        = set()
        min_bars        = MIN_SIGNAL_BARS_DAILY if is_daily else MIN_SIGNAL_BARS
        current_date    = None
        session_start_i = 0

        for i in range(min_bars, len(bars)):
            window  = bars[:i + 1]
            spy_win = spy_ref[:i + 1] if spy_ref else []

            bar_date = str(bars[i]['timestamp'])[:10]
            if bar_date != current_date:
                current_date    = bar_date
                session_start_i = i

            session_bars_window = bars[session_start_i:i + 1]

            sig = _detect_signal(
                window, spy_win,
                rvol_min     = effective_rvol,
                lookback     = self.lookback,
                is_daily     = is_daily,
                session_bars = session_bars_window,
            )
            if sig is None:
                continue

            bar_idx = sig['bar_index']
            if bar_idx in seen_idx:
                continue
            seen_idx.add(bar_idx)

            outcome        = _label_outcome(sig, bars, self.timeout_bars)
            sig['ticker']  = ticker
            sig['outcome'] = outcome
            signals.append(sig)

        wins     = sum(1 for s in signals if s['outcome'] == 'WIN')
        losses   = sum(1 for s in signals if s['outcome'] == 'LOSS')
        timeouts = sum(1 for s in signals if s['outcome'] == 'TIMEOUT')
        logger.info(
            f"[HIST-TRAINER] {ticker}: {len(signals)} signals — "
            f"WIN={wins} LOSS={losses} TIMEOUT={timeouts}"
        )
        return signals

    def build_dataset(
        self,
        tickers:           List[str],
        months_back:       int   = 4,
        include_timeout:   bool  = True,
        spy_ticker:        str   = 'SPY',
        rate_limit_s:      float = 0.5,
        interval_override: Optional[str] = None,
    ):
        """
        Full pipeline: fetch → replay → label → DataFrame.
        include_timeout=True (default): TIMEOUT signals counted as LOSS.
        """
        if not _PANDAS_OK:
            raise ImportError("pandas required for build_dataset()")

        iv       = interval_override or self.interval
        is_daily = iv not in _INTRADAY_INTERVALS

        if is_daily:
            logger.info(f"[HIST-TRAINER] Daily mode — RVOL_MIN={RVOL_MIN_DAILY}, MIN_SIGNAL_BARS={MIN_SIGNAL_BARS_DAILY}")

        spy_bars = self.fetch_bars(spy_ticker, months_back, interval=iv)
        time.sleep(rate_limit_s)

        all_signals: List[Dict] = []
        for ticker in tickers:
            bars = spy_bars if ticker == spy_ticker else self.fetch_bars(ticker, months_back, interval=iv)
            if ticker != spy_ticker:
                time.sleep(rate_limit_s)
            sigs = self.replay_ticker(ticker, bars, spy_bars, is_daily=is_daily)
            all_signals.extend(sigs)

        if not all_signals:
            logger.warning("[HIST-TRAINER] No signals generated — check EODHD key / tickers / thresholds")
            return pd.DataFrame()

                # ── Compute per-ticker win rates from this dataset ────────────────────
        from collections import defaultdict
        ticker_wins   = defaultdict(int)
        ticker_totals = defaultdict(int)
        for _s in all_signals:
            if _s['outcome'] in ('WIN', 'LOSS'):
                ticker_totals[_s['ticker']] += 1
                if _s['outcome'] == 'WIN':
                    ticker_wins[_s['ticker']] += 1
        ticker_win_rates = {
            t: ticker_wins[t] / ticker_totals[t]
            for t in ticker_totals if ticker_totals[t] > 0
        }

        rows = []
        timeout_count = 0
        for sig in all_signals:
            outcome = sig['outcome']
            if outcome == 'TIMEOUT':
                if not include_timeout:
                    continue
                timeout_count += 1
                outcome = 'LOSS'

                sig['ticker_win_rate'] = ticker_win_rates.get(sig.get('ticker', ''), 0.40)
            features = _signal_to_features(sig)

            row = {
                'ticker':         sig.get('ticker', ''),
                'timestamp':      sig.get('timestamp', ''),
                'outcome':        sig['outcome'],
                'outcome_binary': 1 if outcome == 'WIN' else 0,
                'regime':         sig.get('regime', 'NEUTRAL'),
                'pattern':        sig.get('pattern', 'BOS'),
            }
            for name, val in zip(FEATURE_NAMES, features):
                row[name] = val
            rows.append(row)

        df = pd.DataFrame(rows)
        win_n  = (df['outcome_binary'] == 1).sum()
        loss_n = (df['outcome_binary'] == 0).sum()
        logger.info(
            f"[HIST-TRAINER] Dataset: {len(df)} labelled signals from {len(tickers)} tickers "
            f"(WIN={win_n} {win_n/len(df)*100:.1f}%, LOSS={loss_n} {loss_n/len(df)*100:.1f}%, "
            f"TIMEOUT→LOSS={timeout_count})"
        )
        return df

    def walk_forward_split(self, df, val_fraction: float = 0.25) -> Tuple:
        """Temporal train/val split — no random shuffle to avoid look-ahead."""
        if not _PANDAS_OK or df.empty:
            return df, df
        df_sorted = df.sort_values('timestamp').reset_index(drop=True)
        split_idx = int(len(df_sorted) * (1 - val_fraction))
        train_df  = df_sorted.iloc[:split_idx]
        val_df    = df_sorted.iloc[split_idx:]
        logger.info(f"[HIST-TRAINER] Walk-forward split: {len(train_df)} train / {len(val_df)} val")
        return train_df, val_df

    def summary(self, df) -> str:
        """Human-readable dataset summary."""
        if not _PANDAS_OK or df.empty:
            return "Empty dataset"
        lines = [
            f"Total signals : {len(df)}",
            f"Tickers       : {df['ticker'].nunique()} ({', '.join(sorted(df['ticker'].unique()))})",
            f"Date range    : {df['timestamp'].min()} → {df['timestamp'].max()}",
            f"WIN           : {(df['outcome']=='WIN').sum()} ({(df['outcome']=='WIN').mean()*100:.1f}%)",
            f"LOSS          : {(df['outcome']=='LOSS').sum()} ({(df['outcome']=='LOSS').mean()*100:.1f}%)",
            f"TIMEOUT→LOSS  : {(df['outcome']=='TIMEOUT').sum()}",
            f"Avg RVOL      : {df['rvol'].mean():.2f}",
            f"Avg confidence: {df['confidence'].mean():.2%}",
            f"MTF converged : {df['mtf_convergence'].sum()} ({df['mtf_convergence'].mean()*100:.1f}%)",
            f"OR signals    : {df['is_or_signal'].sum()} ({df['is_or_signal'].mean()*100:.1f}%)",
            f"FVG patterns  : {(df['pattern']=='FVG').sum()} ({(df['pattern']=='FVG').mean()*100:.1f}%)",
            f"Avg ATR ratio : {df['atr_ratio'].mean():.2f}",
            f"VWAP above    : {(df['vwap_side']>0).sum()} ({(df['vwap_side']>0).mean()*100:.1f}%)",
        ]
        return "\n".join(lines)
