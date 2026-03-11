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
* Feature parity     — 20-feature vector matches MLSignalScorerV2._build_features().
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

Bug fixes applied
-----------------
* BUG 1: Skip intraday endpoint when interval='d' (EODHD 422).
* BUG 2: _safe_float() handles EODHD null volume/price fields.
* BUG 3: Daily-calibrated thresholds (RVOL_MIN_DAILY=1.3, MIN_SIGNAL_BARS_DAILY=5).
* BUG 4: Filter after-hours zero-volume bars (136 per 120d window on AAPL).
         EODHD sends post-market bars with null volume and flat OHLC — these
         generate false breakout signals that all label as LOSS and destroy
         model accuracy. Now dropped in _eodhd_intraday() via market-hours gate.
* BUG 5: _rvol() and _vwap_distance() guard against zero-volume bars in averages.
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
DEFAULT_TIMEOUT_BARS  = 12    # 60 min on 5m data — tighter than old 20-bar window
MIN_SIGNAL_BARS       = 30    # min bars before scanning (intraday)
MIN_SIGNAL_BARS_DAILY = 5     # min bars for daily
STOP_MULT             = 1.0   # stop_loss = entry - ATR * STOP_MULT  (1×ATR)
TARGET_MULT           = 1.5   # target    = entry + ATR * TARGET_MULT (1:1.5 R:R)
                               # Tighter than old 2.0 — must be a real directional
                               # move, not noise-driven drift, to label WIN.
RVOL_MIN_DAILY        = 1.3   # lower RVOL threshold for daily bars

# Market hours in UTC: 09:30–16:00 ET = 14:30–21:00 UTC
MARKET_OPEN_UTC_H  = 14
MARKET_OPEN_UTC_M  = 30
MARKET_CLOSE_UTC_H = 21
MARKET_CLOSE_UTC_M = 0

# EODHD intraday endpoint only accepts these intervals.
_INTRADAY_INTERVALS = {'1m', '5m', '15m', '1h'}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — data cleaning
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    """
    Safely convert a value to float.
    BUG-2: EODHD returns {"volume": null}; b.get('volume', 0) returns None
    (not 0) when the key exists with a null value.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_market_hours(dt_str: str) -> bool:
    """
    BUG-4 FIX: Returns True only for bars within regular market hours.
    EODHD intraday includes pre/post-market bars with null volume and
    flat OHLC — these are after-hours prints, not tradeable bars.

    EODHD datetime format: '2026-03-10 14:35:00' (UTC)
    Market hours UTC: 14:30–21:00 (= 09:30–16:00 ET)
    """
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
    """
    Fetch intraday OHLCV bars from EODHD, market hours only.

    Applies two filters:
    1. _is_market_hours() — drops pre/post-market bars by UTC time
    2. volume > 0        — drops any remaining null-volume bars (BUG-4)
    """
    if interval not in _INTRADAY_INTERVALS:  # BUG-1
        return []
    if not _REQUESTS_OK:
        return []

    params: Dict = {
        'api_token': api_key,
        'fmt':       'json',
        'interval':  interval,
    }
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

        bars = []
        skipped_hours = 0
        skipped_vol   = 0
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

            bars.append({
                'timestamp': dt_str,
                'open':   o,
                'high':   h,
                'low':    l,
                'close':  c,
                'volume': v,
            })

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
    params: Dict = {
        'api_token': api_key,
        'fmt':       'json',
        'period':    'd',
    }
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


def _rvol(bars: List[Dict], lookback: int = 20) -> float:
    """
    Relative volume: current bar volume vs avg of prior `lookback` bars.
    BUG-5: Only include bars with volume > 0 in the lookback average.
    """
    if len(bars) < 2:
        return 1.0
    recent = [b for b in bars[-(lookback + 1):-1] if b['volume'] > 0]
    if not recent:
        return 1.0
    avg = sum(b['volume'] for b in recent) / len(recent)
    cur_vol = bars[-1]['volume']
    return cur_vol / avg if avg > 0 else 1.0


def _resistance(bars: List[Dict], lookback: int = 12) -> float:
    window = bars[-lookback - 1:-1]
    return max(b['high'] for b in window) if window else bars[-1]['high']


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
    """
    Distance of last close from session VWAP as a fraction of close.
    BUG-5: Guard against all-zero volume window.
    """
    vol_bars = [b for b in bars if b['volume'] > 0]
    if not vol_bars:
        return 0.0
    tp_vol = sum((b['high'] + b['low'] + b['close']) / 3 * b['volume'] for b in vol_bars)
    vol    = sum(b['volume'] for b in vol_bars)
    vwap   = tp_vol / vol if vol > 0 else bars[-1]['close']
    return (bars[-1]['close'] - vwap) / vwap if vwap > 0 else 0.0


def _or_range(bars: List[Dict], or_bars: int = 6) -> float:
    """
    Opening Range as % of price: high-low of first `or_bars` bars of session.
    Uses first 6 bars = first 30 minutes on 5m data (09:30–10:00 ET).
    """
    window = bars[:or_bars] if len(bars) >= or_bars else bars
    if not window:
        return 0.01
    hi = max(b['high'] for b in window)
    lo = min(b['low']  for b in window)
    mid = (hi + lo) / 2
    return (hi - lo) / mid if mid > 0 else 0.01


def _regime(spy_bars: List[Dict]) -> str:
    """Crude regime: BULL if SPY close > 20-bar SMA, else BEAR."""
    if len(spy_bars) < 20:
        return 'NEUTRAL'
    sma = sum(b['close'] for b in spy_bars[-20:]) / 20
    return 'BULL' if spy_bars[-1]['close'] > sma else 'BEAR'


# ─────────────────────────────────────────────────────────────────────────────
# Signal detector (mirrors BreakoutDetector logic)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_signal(
    bars:      List[Dict],
    spy_bars:  List[Dict],
    rvol_min:  float = 2.0,
    lookback:  int   = 12,
    is_daily:  bool  = False,
) -> Optional[Dict]:
    """Returns a signal dict if a breakout is detected on the last bar, else None."""
    min_bars = MIN_SIGNAL_BARS_DAILY if is_daily else MIN_SIGNAL_BARS
    if len(bars) < min_bars:
        return None

    latest = bars[-1]
    rv     = _rvol(bars)
    resist = _resistance(bars, lookback)

    if latest['close'] <= resist or rv < rvol_min:
        return None

    atr = _atr(bars)
    if atr == 0:
        return None

    entry     = latest['close']
    stop_loss = entry - atr * STOP_MULT
    target    = entry + atr * TARGET_MULT
    adx       = _adx_approx(bars)
    vwap_dist = _vwap_distance(bars)
    regime    = _regime(spy_bars) if spy_bars else 'NEUTRAL'
    hour      = _parse_hour(latest['timestamp'])
    atr_pct   = atr / entry
    or_range  = _or_range(bars)
    confidence = min(0.5 + (rv - rvol_min) * 0.05 + adx * 0.003, 0.95)
    score      = int(confidence * 100)
    rr_ratio   = (target - entry) / (entry - stop_loss) if (entry - stop_loss) > 0 else TARGET_MULT

    return {
        'entry':                 entry,
        'stop_loss':             stop_loss,
        'target':                target,
        'bar_index':             len(bars) - 1,
        'timestamp':             latest['timestamp'],
        'confidence':            confidence,
        'grade':                 _score_to_grade(score),
        'rvol':                  rv,
        'score':                 score,
        'ivr':                   0.5,
        'gex_multiplier':        1.0,
        'uoa_multiplier':        1.0,
        'ivr_multiplier':        1.0,
        'mtf_boost':             0.0,
        'mtf_convergence':       False,
        'mtf_convergence_count': 0,
        'vwap_distance':         vwap_dist,
        'or_range_pct':          or_range,
        'adx':                   adx,
        'atr_pct':               atr_pct,
        'signal_type':           'BREAKOUT',
        'direction':             'bull',
        'hour':                  hour,
        'rr_ratio':              rr_ratio,
        'explosive_mover':       rv > 4.0,
        'regime':                regime,
        'vix_level':             20.0,
        'pattern':               'BOS',
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
    * WIN     — high >= target  before low <= stop_loss
    * LOSS    — low  <= stop_loss before high >= target
    * TIMEOUT — neither hit within timeout_bars bars (12 = 60 min on 5m)
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
# Feature vector builder (matches MLSignalScorerV2)
# ─────────────────────────────────────────────────────────────────────────────

GRADE_MAP = {'A+': 9, 'A': 8, 'A-': 7, 'B+': 6, 'B': 5,
             'B-': 4, 'C+': 3, 'C': 2, 'C-': 1}

FEATURE_NAMES = [
    'confidence', 'grade_norm', 'rvol', 'score_norm',
    'ivr', 'gex_multiplier', 'uoa_multiplier', 'ivr_multiplier',
    'mtf_boost', 'mtf_convergence', 'mtf_convergence_count',
    'vwap_distance', 'or_range_pct', 'adx_norm', 'atr_pct',
    'is_or_signal', 'is_bull', 'hour_norm',
    'rr_ratio_norm', 'explosive_mover',
]


def _signal_to_features(sig: Dict) -> List[float]:
    return [
        sig.get('confidence', 0.70),
        GRADE_MAP.get(sig.get('grade', 'B'), 5) / 9.0,
        sig.get('rvol', 1.0),
        sig.get('score', 50) / 100.0,
        sig.get('ivr', 0.5),
        sig.get('gex_multiplier', 1.0),
        sig.get('uoa_multiplier', 1.0),
        sig.get('ivr_multiplier', 1.0),
        sig.get('mtf_boost', 0.0),
        float(sig.get('mtf_convergence', False)),
        sig.get('mtf_convergence_count', 0) / 4.0,
        sig.get('vwap_distance', 0.0),
        sig.get('or_range_pct', 0.01),
        sig.get('adx', 20.0) / 50.0,
        sig.get('atr_pct', 0.01),
        1.0 if sig.get('signal_type') == 'CFW6_OR' else 0.0,
        1.0 if sig.get('direction') == 'bull' else 0.0,
        sig.get('hour', 14) / 21.0,
        sig.get('rr_ratio', 2.0) / 5.0,
        float(sig.get('explosive_mover', False)),
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

        logger.info(
            f"[HIST-TRAINER] Fetching {ticker} "
            f"({from_dt.date()} → {to_dt.date()}, interval={iv})"
        )

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
        """Replay signal detection bar-by-bar and label outcomes."""
        if not bars:
            return []

        effective_rvol = RVOL_MIN_DAILY if is_daily else self.rvol_min
        spy_ref        = spy_bars or []
        signals        = []
        seen_idx       = set()
        min_bars       = MIN_SIGNAL_BARS_DAILY if is_daily else MIN_SIGNAL_BARS

        for i in range(min_bars, len(bars)):
            window  = bars[:i + 1]
            spy_win = spy_ref[:i + 1] if spy_ref else []

            sig = _detect_signal(
                window, spy_win,
                rvol_min=effective_rvol,
                lookback=self.lookback,
                is_daily=is_daily,
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

        include_timeout=True (default): TIMEOUT signals are included as LOSS.
        A signal that stalls for 60 min without hitting target or stop is a
        failed trade and the most valuable negative example for the model.
        Set include_timeout=False only if you want pure WIN/LOSS datasets.
        """
        if not _PANDAS_OK:
            raise ImportError("pandas required for build_dataset()")

        iv       = interval_override or self.interval
        is_daily = iv not in _INTRADAY_INTERVALS

        if is_daily:
            logger.info(
                f"[HIST-TRAINER] Daily mode — "
                f"RVOL_MIN={RVOL_MIN_DAILY}, MIN_SIGNAL_BARS={MIN_SIGNAL_BARS_DAILY}"
            )

        spy_bars = self.fetch_bars(spy_ticker, months_back, interval=iv)
        time.sleep(rate_limit_s)

        all_signals: List[Dict] = []

        for ticker in tickers:
            if ticker == spy_ticker:
                bars = spy_bars
            else:
                bars = self.fetch_bars(ticker, months_back, interval=iv)
                time.sleep(rate_limit_s)

            sigs = self.replay_ticker(ticker, bars, spy_bars, is_daily=is_daily)
            all_signals.extend(sigs)

        if not all_signals:
            logger.warning(
                "[HIST-TRAINER] No signals generated — check EODHD key / tickers / thresholds"
            )
            return pd.DataFrame()

        rows = []
        timeout_count = 0
        for sig in all_signals:
            outcome = sig['outcome']
            if outcome == 'TIMEOUT':
                if not include_timeout:
                    continue
                timeout_count += 1
                outcome = 'LOSS'  # stalled = failed trade

            features = _signal_to_features(sig)
            row = {
                'ticker':         sig.get('ticker', ''),
                'timestamp':      sig.get('timestamp', ''),
                'outcome':        sig['outcome'],   # raw label (TIMEOUT preserved)
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

    def walk_forward_split(
        self,
        df,
        val_fraction: float = 0.25,
    ) -> Tuple:
        """Temporal train/val split — no random shuffle to avoid look-ahead."""
        if not _PANDAS_OK or df.empty:
            return df, df

        df_sorted = df.sort_values('timestamp').reset_index(drop=True)
        split_idx = int(len(df_sorted) * (1 - val_fraction))
        train_df  = df_sorted.iloc[:split_idx]
        val_df    = df_sorted.iloc[split_idx:]

        logger.info(
            f"[HIST-TRAINER] Walk-forward split: "
            f"{len(train_df)} train / {len(val_df)} val"
        )
        return train_df, val_df

    def summary(self, df) -> str:
        """Human-readable dataset summary."""
        if not _PANDAS_OK or df.empty:
            return "Empty dataset"
        lines = [
            f"Total signals : {len(df)}",
            f"Tickers       : {df['ticker'].nunique()} "
            f"({', '.join(sorted(df['ticker'].unique()))})",
            f"Date range    : {df['timestamp'].min()} → {df['timestamp'].max()}",
            f"WIN           : {(df['outcome']=='WIN').sum()} "
            f"({(df['outcome']=='WIN').mean()*100:.1f}%)",
            f"LOSS          : {(df['outcome']=='LOSS').sum()} "
            f"({(df['outcome']=='LOSS').mean()*100:.1f}%)",
            f"TIMEOUT→LOSS  : {(df['outcome']=='TIMEOUT').sum()}",
            f"Avg RVOL      : {df['rvol'].mean():.2f}",
            f"Avg confidence: {df['confidence'].mean():.2%}",
        ]
        return "\n".join(lines)
