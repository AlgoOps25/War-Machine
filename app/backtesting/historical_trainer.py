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

Quick usage
-----------
    from app.backtesting.historical_trainer import HistoricalMLTrainer

    trainer = HistoricalMLTrainer(eodhd_api_key=os.getenv('EODHD_API_KEY'))
    df = trainer.build_dataset(
        tickers=['AAPL', 'TSLA', 'NVDA', 'SPY'],
        months_back=12,
    )
    print(df['outcome'].value_counts())  # WIN / LOSS / TIMEOUT
    train_df, val_df = trainer.walk_forward_split(df, val_fraction=0.25)
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, date
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
EODHD_BASE        = "https://eodhd.com/api"
DEFAULT_TIMEOUT_BARS = 20   # bars before a signal is labelled TIMEOUT
MIN_SIGNAL_BARS   = 30      # minimum bars needed before scanning for signals
STOP_MULT         = 1.0     # stop_loss = entry - ATR * STOP_MULT
TARGET_MULT       = 2.0     # target    = entry + ATR * TARGET_MULT (1:2 R:R)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — EODHD data fetching
# ─────────────────────────────────────────────────────────────────────────────

def _eodhd_intraday(
    ticker: str,
    api_key: str,
    interval: str = '5m',
    from_dt: Optional[datetime] = None,
    to_dt:   Optional[datetime] = None,
) -> List[Dict]:
    """
    Fetch intraday OHLCV bars from EODHD.
    Returns list of dicts: {timestamp, open, high, low, close, volume}
    """
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
        bars = []
        for b in raw:
            bars.append({
                'timestamp': b.get('datetime') or b.get('date'),
                'open':      float(b['open']),
                'high':      float(b['high']),
                'low':       float(b['low']),
                'close':     float(b['close']),
                'volume':    float(b.get('volume', 0)),
            })
        return bars
    except Exception as exc:
        logger.warning(f"[HIST-TRAINER] EODHD fetch failed for {ticker}: {exc}")
        return []


def _eodhd_eod(
    ticker: str,
    api_key: str,
    from_dt: Optional[datetime] = None,
    to_dt:   Optional[datetime] = None,
) -> List[Dict]:
    """Fetch daily OHLCV bars (fallback when intraday quota is exhausted)."""
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
        bars = []
        for b in raw:
            bars.append({
                'timestamp': b['date'],
                'open':      float(b['open']),
                'high':      float(b['high']),
                'low':       float(b['low']),
                'close':     float(b['adjusted_close']),
                'volume':    float(b.get('volume', 0)),
            })
        return bars
    except Exception as exc:
        logger.warning(f"[HIST-TRAINER] EODHD EOD fetch failed for {ticker}: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Technical indicator helpers (no external lib required)
# ─────────────────────────────────────────────────────────────────────────────

def _atr(bars: List[Dict], period: int = 14) -> float:
    """Average True Range over last `period` bars."""
    if len(bars) < 2:
        return bars[-1]['high'] - bars[-1]['low'] if bars else 0.0
    trs = []
    for i in range(max(1, len(bars) - period), len(bars)):
        b, prev = bars[i], bars[i - 1]
        trs.append(max(
            b['high'] - b['low'],
            abs(b['high'] - prev['close']),
            abs(b['low']  - prev['close']),
        ))
    return sum(trs) / len(trs) if trs else 0.0


def _rvol(bars: List[Dict], lookback: int = 20) -> float:
    """Relative volume: current bar volume vs. avg of prior `lookback` bars."""
    if len(bars) < 2:
        return 1.0
    recent = bars[-(lookback + 1):-1]
    avg    = sum(b['volume'] for b in recent) / len(recent) if recent else 1.0
    return bars[-1]['volume'] / avg if avg > 0 else 1.0


def _resistance(bars: List[Dict], lookback: int = 12) -> float:
    return max(b['high'] for b in bars[-lookback - 1:-1])


def _adx_approx(bars: List[Dict], period: int = 14) -> float:
    """
    Approximate ADX (directional strength 0–100) without pandas_ta.
    Uses the classic Wilder smoothing.
    """
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
        tr_list.append(max(b['high'] - b['low'],
                           abs(b['high'] - p['close']),
                           abs(b['low']  - p['close'])))
    def wilder(lst, n):
        s = sum(lst[:n])
        res = [s]
        for v in lst[n:]:
            s = s - s / n + v
            res.append(s)
        return res
    if len(tr_list) < period:
        return 20.0
    atr14   = wilder(tr_list,   period)
    pdi14   = wilder(plus_dm,   period)
    mdi14   = wilder(minus_dm,  period)
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
    """Distance of last close from session VWAP as a fraction of close."""
    tp_vol = sum((b['high'] + b['low'] + b['close']) / 3 * b['volume'] for b in bars)
    vol    = sum(b['volume'] for b in bars)
    vwap   = tp_vol / vol if vol > 0 else bars[-1]['close']
    return (bars[-1]['close'] - vwap) / vwap if vwap > 0 else 0.0


def _regime(spy_bars: List[Dict]) -> str:
    """Crude regime: BULL if SPY close > 20-bar SMA, else BEAR."""
    if len(spy_bars) < 20:
        return 'NEUTRAL'
    sma = sum(b['close'] for b in spy_bars[-20:]) / 20
    return 'BULL' if spy_bars[-1]['close'] > sma else 'BEAR'


# ─────────────────────────────────────────────────────────────────────────────
# Signal detector (simplified breakout — mirrors BreakoutDetector logic)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_signal(
    bars:            List[Dict],
    spy_bars:        List[Dict],
    rvol_min:        float = 2.0,
    lookback:        int   = 12,
) -> Optional[Dict]:
    """
    Returns a signal dict if a breakout is detected on the last bar, else None.
    Signal keys align with MLSignalScorerV2._build_features().
    """
    if len(bars) < MIN_SIGNAL_BARS:
        return None

    latest  = bars[-1]
    rv      = _rvol(bars)
    resist  = _resistance(bars, lookback)

    if latest['close'] <= resist or rv < rvol_min:
        return None

    atr        = _atr(bars)
    entry      = latest['close']
    stop_loss  = entry - atr * STOP_MULT
    target     = entry + atr * TARGET_MULT
    adx        = _adx_approx(bars)
    vwap_dist  = _vwap_distance(bars)
    regime     = _regime(spy_bars) if spy_bars else 'NEUTRAL'
    hour       = _parse_hour(latest['timestamp'])
    atr_pct    = atr / entry if entry > 0 else 0.01
    or_range   = (bars[3]['high'] - bars[3]['low']) / entry if len(bars) > 3 else 0.01

    # Confidence: simple heuristic (0–1)
    confidence = min(0.5 + (rv - rvol_min) * 0.05 + adx * 0.003, 0.95)
    score      = int(confidence * 100)
    rr_ratio   = (target - entry) / (entry - stop_loss) if (entry - stop_loss) > 0 else TARGET_MULT

    return {
        # Labelling keys
        'entry':      entry,
        'stop_loss':  stop_loss,
        'target':     target,
        'bar_index':  len(bars) - 1,
        'timestamp':  latest['timestamp'],
        # Feature keys (must match MLSignalScorerV2._build_features)
        'confidence':        confidence,
        'grade':             _score_to_grade(score),
        'rvol':              rv,
        'score':             score,
        'ivr':               0.5,        # not available in OHLCV — neutral
        'gex_multiplier':    1.0,
        'uoa_multiplier':    1.0,
        'ivr_multiplier':    1.0,
        'mtf_boost':         0.0,
        'mtf_convergence':   False,
        'mtf_convergence_count': 0,
        'vwap_distance':     vwap_dist,
        'or_range_pct':      or_range,
        'adx':               adx,
        'atr_pct':           atr_pct,
        'signal_type':       'BREAKOUT',
        'direction':         'bull',
        'hour':              hour,
        'rr_ratio':          rr_ratio,
        'explosive_mover':   rv > 4.0,
        # Context
        'regime':     regime,
        'vix_level':  20.0,   # not available without VIX feed — neutral
        'pattern':    'BOS',
    }


def _parse_hour(ts) -> int:
    """Extract hour from timestamp string or int epoch."""
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
    return 10  # default mid-morning


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
    signal:        Dict,
    all_bars:      List[Dict],
    timeout_bars:  int = DEFAULT_TIMEOUT_BARS,
) -> str:
    """
    Walk forward from entry bar and label WIN / LOSS / TIMEOUT.
    * WIN     — high >= target  before low <= stop_loss
    * LOSS    — low  <= stop_loss before high >= target
    * TIMEOUT — neither hit within timeout_bars bars
    """
    entry_idx  = signal['bar_index']
    target     = signal['target']
    stop_loss  = signal['stop_loss']
    future     = all_bars[entry_idx + 1: entry_idx + 1 + timeout_bars]

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
        sig.get('hour', 10) / 16.0,
        sig.get('rr_ratio', 2.0) / 5.0,
        float(sig.get('explosive_mover', False)),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class HistoricalMLTrainer:
    """
    Builds a labelled ML training dataset from EODHD historical OHLCV data.

    Parameters
    ----------
    eodhd_api_key : str
        EODHD API key (or set EODHD_API_KEY env var).
    interval : str
        Bar interval passed to EODHD intraday endpoint.  '5m' recommended.
        Use 'd' to fall back to daily bars (much larger history, less granular).
    rvol_min : float
        Minimum relative volume to trigger a signal during replay.
    lookback : int
        Bars of lookback for resistance detection.
    timeout_bars : int
        Bars before an open signal is labelled TIMEOUT.
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
            logger.warning("[HIST-TRAINER] No EODHD_API_KEY set — data fetches will fail")

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def fetch_bars(
        self,
        ticker:     str,
        months_back: int = 12,
    ) -> List[Dict]:
        """
        Fetch historical bars for `ticker` going back `months_back` months.
        Tries intraday first; falls back to daily if intraday returns nothing.
        """
        to_dt   = datetime.utcnow()
        from_dt = to_dt - timedelta(days=months_back * 30)

        logger.info(f"[HIST-TRAINER] Fetching {ticker} bars "
                    f"({from_dt.date()} → {to_dt.date()}, interval={self.interval})")

        bars = _eodhd_intraday(ticker, self.api_key, self.interval, from_dt, to_dt)

        if not bars:
            logger.info(f"[HIST-TRAINER] Intraday empty for {ticker} — trying EOD bars")
            bars = _eodhd_eod(ticker, self.api_key, from_dt, to_dt)

        logger.info(f"[HIST-TRAINER] {ticker}: {len(bars)} bars fetched")
        return bars

    def replay_ticker(
        self,
        ticker:      str,
        bars:        List[Dict],
        spy_bars:    Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """
        Replay signal detection across all bars for a single ticker.
        Returns list of labelled signal dicts (outcome='WIN'/'LOSS'/'TIMEOUT').
        """
        if not bars:
            return []

        spy_ref   = spy_bars or []
        signals   = []
        seen_idx  = set()   # prevent duplicate signals on same bar

        for i in range(MIN_SIGNAL_BARS, len(bars)):
            window   = bars[:i + 1]
            spy_win  = spy_ref[:i + 1] if spy_ref else []

            sig = _detect_signal(window, spy_win, self.rvol_min, self.lookback)
            if sig is None:
                continue

            bar_idx = sig['bar_index']
            if bar_idx in seen_idx:
                continue
            seen_idx.add(bar_idx)

            outcome       = _label_outcome(sig, bars, self.timeout_bars)
            sig['ticker'] = ticker
            sig['outcome'] = outcome
            signals.append(sig)

        logger.info(f"[HIST-TRAINER] {ticker}: {len(signals)} signals — "
                    f"WIN={sum(1 for s in signals if s['outcome']=='WIN')} "
                    f"LOSS={sum(1 for s in signals if s['outcome']=='LOSS')} "
                    f"TIMEOUT={sum(1 for s in signals if s['outcome']=='TIMEOUT')}")
        return signals

    def build_dataset(
        self,
        tickers:     List[str],
        months_back: int  = 12,
        include_timeout: bool = False,
        spy_ticker:  str  = 'SPY',
        rate_limit_s: float = 0.5,
    ):
        """
        Full pipeline: fetch → replay → label → DataFrame.

        Parameters
        ----------
        tickers : list of str
            Tickers to include (e.g. ['AAPL', 'TSLA', 'NVDA']).
        months_back : int
            How many months of history to pull.
        include_timeout : bool
            If False (default), TIMEOUT signals are excluded from the dataset
            (they add noise since outcome is unknown).  Set True to include them
            as LOSS for conservative training.
        spy_ticker : str
            Ticker used to build regime feature.  Fetched once and reused.
        rate_limit_s : float
            Seconds to sleep between EODHD API calls (avoid rate limiting).

        Returns
        -------
        pd.DataFrame  with columns:
            ticker, timestamp, outcome, outcome_binary (1=WIN, 0=LOSS),
            + 20 ML feature columns matching FEATURE_NAMES.
        """
        if not _PANDAS_OK:
            raise ImportError("pandas required for build_dataset()")

        # Fetch SPY for regime feature
        spy_bars = self.fetch_bars(spy_ticker, months_back)
        time.sleep(rate_limit_s)

        all_signals: List[Dict] = []

        for ticker in tickers:
            if ticker == spy_ticker:
                bars = spy_bars
            else:
                bars = self.fetch_bars(ticker, months_back)
                time.sleep(rate_limit_s)

            sigs = self.replay_ticker(ticker, bars, spy_bars)
            all_signals.extend(sigs)

        if not all_signals:
            logger.warning("[HIST-TRAINER] No signals generated — check EODHD key / tickers")
            return pd.DataFrame()

        rows = []
        for sig in all_signals:
            outcome = sig['outcome']
            if outcome == 'TIMEOUT':
                if not include_timeout:
                    continue
                outcome = 'LOSS'   # treat timeout as loss when included

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
        logger.info(f"[HIST-TRAINER] Dataset: {len(df)} labelled signals from {len(tickers)} tickers")
        logger.info(f"[HIST-TRAINER] Class balance: "
                    f"WIN={df['outcome_binary'].sum()} "
                    f"LOSS={(df['outcome_binary']==0).sum()}")
        return df

    def walk_forward_split(
        self,
        df,
        val_fraction: float = 0.25,
    ) -> Tuple:
        """
        Temporal train/validation split (no random shuffle — avoids look-ahead).
        Sorts by timestamp, uses the oldest (1-val_fraction) for training
        and the most recent val_fraction for validation.

        Returns (train_df, val_df)
        """
        if not _PANDAS_OK or df.empty:
            return df, df

        df_sorted   = df.sort_values('timestamp').reset_index(drop=True)
        split_idx   = int(len(df_sorted) * (1 - val_fraction))
        train_df    = df_sorted.iloc[:split_idx]
        val_df      = df_sorted.iloc[split_idx:]

        logger.info(f"[HIST-TRAINER] Walk-forward split: "
                    f"{len(train_df)} train / {len(val_df)} val "
                    f"(split at index {split_idx})")
        return train_df, val_df

    def summary(self, df) -> str:
        """Return a human-readable summary of the dataset."""
        if not _PANDAS_OK or df.empty:
            return "Empty dataset"
        lines = [
            f"Total signals : {len(df)}",
            f"Tickers       : {df['ticker'].nunique()} ({', '.join(sorted(df['ticker'].unique()))})",
            f"Date range    : {df['timestamp'].min()} → {df['timestamp'].max()}",
            f"WIN           : {(df['outcome']=='WIN').sum()} ({(df['outcome']=='WIN').mean()*100:.1f}%)",
            f"LOSS          : {(df['outcome']=='LOSS').sum()} ({(df['outcome']=='LOSS').mean()*100:.1f}%)",
            f"TIMEOUT (excl): {(df['outcome']=='TIMEOUT').sum()}",
            f"Avg RVOL      : {df['rvol'].mean():.2f}",
            f"Avg confidence: {df['confidence'].mean():.2%}",
        ]
        return "\n".join(lines)
