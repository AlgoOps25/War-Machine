#!/usr/bin/env python3
"""
Unified Production Backtesting Engine for War Machine

47.P4-1 (Apr 02 2026): Full bar-replay implementation replacing the prior stub.
  - OR window (09:30-09:50 ET) builds high/low, then scans for BOS above/below
  - FVG detection on 3-bar sequence after BOS
  - VWAP gate, entry-timing filter, MTF boost wired when modules available
  - strategy() callable matches BacktestEngine.run() signature exactly
  - --walk-forward runs WalkForward with auto-scaled window params
  - --batch runs all 5 default tickers sequentially
  - Hourly win-rate map printed at end (feeds 47.P4-2)

BUG-BT-1 (Apr 02 2026): fetch_from_cache() queried intraday_bars (1m, ~39k bars).
  With BacktestEngine's 100-bar lookback window, most slices lacked OR bars
  entirely (or_bars < 2), causing the strategy to return None on every call.
  Fix: query intraday_bars_5m first; if empty, resample 1m bars to 5m.

BUG-BT-2 (Apr 02 2026): Add first-bar datetime diagnostic to surface
  UTC-vs-ET timezone issues immediately on fetch.

BUG-BT-3 (Apr 02 2026): AAPL/MSFT 0 trades.
  OR range threshold was 0.2% (0.002). Low-vol tickers (AAPL/MSFT) have
  typical OR ranges of 0.10-0.15%, so the filter killed every session.
  Lowered to 0.1% (0.001). Also: VWAP was computed on all session_bars
  including pre-market (04:00-09:29) — now scoped to RTH bars (>=09:30)
  so pre-market volume does not skew the gate.

BUG-BT-4 (Apr 02 2026): Inverted R:R on NVDA/AMD (avg loss > avg win).
  ATR was computed on last 14 bars regardless of session — pre-market bars
  have inflated ranges due to gap open, making ATR ~2x the true RTH range.
  Stop = close - ATR*1.5 placed stops $3-4 below entry on $100+ stocks,
  while T1 = entry + ATR*1.0 was a shorter distance — inverted risk.
  Fix: compute ATR on RTH bars only. Tighten stop multiplier to 1.0
  (stop = ATR*1.0 away from entry). T1=ATR*1.0, T2=ATR*2.0 — R:R is
  now 1:1 at T1 and 1:2 at T2, never inverted.

BUG-BT-5 (Apr 02 2026): FVG scan window bars[-10:] can include pre-market.
  Fix: filter to RTH bars only before passing to _detect_fvg.

BUG-BT-6 (Apr 02 2026): RVOL avg_vol baseline included pre-market bars
  (04:00-09:29) which have near-zero volume, deflating the denominator and
  making RVOL appear artificially high (suppressing real signals via threshold
  mismatch) or artificially low (filtering valid setups). Fix: restrict the
  20-bar volume history used for avg_vol to RTH bars only.

BUG-BT-7 (Apr 02 2026): rvol_min=1.5 is a global default that blocks AAPL
  and MSFT entirely — their intraday RVOL on 5m bars rarely exceeds 1.3 in
  normal sessions. Added TICKER_PARAMS per-ticker override table. Strategy
  now accepts an optional _ticker kwarg (injected by run_single) and merges
  ticker-specific overrides over CLI params before evaluating any signal.

BUG-BT-8 (Apr 02 2026): Walk-forward produced 0 windows on --days 90.
  Data started 2026-02-02 (~60 calendar days of bars). train_months=2 +
  test_months=1 needs 90 contiguous calendar days but the dataset ends before
  the first test window closes. Fix: auto-scale window params based on data
  span: >=120 days -> 2m/1m; 60-119 days -> 1m/1m; <60 days -> warn+skip.

Usage:
    # Single ticker, 90-day single-pass
    python unified_production_backtest.py --ticker AAPL --days 90

    # Walk-forward (auto-scales window to data span)
    python unified_production_backtest.py --ticker AAPL --days 90 --walk-forward

    # Batch all 5 default tickers
    python unified_production_backtest.py --batch --days 90

    # Custom date range
    python unified_production_backtest.py --ticker NVDA --start 2025-10-01 --end 2026-01-01

    # Save JSON results
    python unified_production_backtest.py --batch --days 90 --save
"""

import sys
import os
import json
import logging
import requests
from datetime import datetime, timedelta, date, time as dtime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Project root on path
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional production module imports
# ---------------------------------------------------------------------------
try:
    from app.backtesting.backtest_engine import BacktestEngine, BacktestResults
    from app.backtesting.walk_forward import WalkForward, WalkForwardResults
    BACKTEST_AVAILABLE = True
except ImportError as e:
    BACKTEST_AVAILABLE = False
    logger.warning(f"Backtest modules not available: {e}")

try:
    from app.validation.entry_timing import get_entry_timing_validator
    ENTRY_TIMING_AVAILABLE = True
except ImportError:
    ENTRY_TIMING_AVAILABLE = False

try:
    from app.mtf.mtf_integration import enhance_signal_with_mtf
    MTF_AVAILABLE = True
except ImportError:
    MTF_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TICKERS = ["AAPL", "TSLA", "NVDA", "MSFT", "AMD"]

OR_START  = dtime(9, 30)   # Opening Range start (ET)
OR_END    = dtime(9, 50)   # Opening Range end   (ET)
RTH_START = dtime(9, 30)   # Regular Trading Hours start
EOD_CUT   = dtime(15, 45)  # No new entries after this

# BUG-BT-3: lowered from 0.002 (0.2%) to 0.001 (0.1%) to allow
# low-vol tickers (AAPL, MSFT) whose OR ranges average ~0.10-0.15%.
OR_MIN_RANGE_PCT = 0.001

# BUG-BT-7: Hard cap on stop distance as % of entry price.
# Prevents high-ATR tickers (NVDA, AMD) from placing $3-4 stops on
# $100 entries while T1 is only $1-2 away (inverted R:R).
MAX_STOP_PCT = 0.01  # 1.0% of entry price

# BUG-BT-7: Per-ticker parameter overrides.
# Keys must be uppercase. Values override CLI defaults for that ticker only.
# Rationale:
#   AAPL / MSFT: low intraday RVOL (rarely exceeds 1.3 on 5m), tight OR ranges
#                -> lower rvol_min + smaller fvg threshold
#   TSLA:        high intraday RVOL, wide gaps -> default params are fine
#   NVDA / AMD:  high RVOL but wide ATR; rvol_min=1.3 to catch setups without
#                inflating position risk via the stop cap
TICKER_PARAMS: Dict[str, Dict] = {
    "AAPL": {"rvol_min": 1.2, "fvg_min_size_pct": 0.003},
    "MSFT": {"rvol_min": 1.2, "fvg_min_size_pct": 0.003},
    "TSLA": {"rvol_min": 1.5, "fvg_min_size_pct": 0.005},
    "NVDA": {"rvol_min": 1.3, "fvg_min_size_pct": 0.004},
    "AMD":  {"rvol_min": 1.3, "fvg_min_size_pct": 0.004},
}

DEFAULT_PARAM_GRID = {
    "fvg_min_size_pct": [0.003, 0.005, 0.008],
    "min_confidence":   [60,    65,    70],
    "rvol_min":         [1.2,   1.5,   2.0],
}


# ===========================================================================
# 1m → 5m RESAMPLER  (BUG-BT-1 fallback)
# ===========================================================================

def resample_1m_to_5m(bars_1m: List[Dict]) -> List[Dict]:
    """
    Aggregate 1-minute bars into 5-minute bars.
    Groups by floor(minute / 5) bucket on a per-session basis.
    Returns bars sorted by datetime.
    """
    if not bars_1m:
        return []

    buckets: Dict[datetime, Dict] = {}
    for b in bars_1m:
        dt = b["datetime"]
        floored = dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)
        if floored not in buckets:
            buckets[floored] = {
                "datetime": floored,
                "open":     b["open"],
                "high":     b["high"],
                "low":      b["low"],
                "close":    b["close"],
                "volume":   b["volume"],
            }
        else:
            bucket = buckets[floored]
            bucket["high"]   = max(bucket["high"],  b["high"])
            bucket["low"]    = min(bucket["low"],   b["low"])
            bucket["close"]  = b["close"]
            bucket["volume"] += b["volume"]

    return sorted(buckets.values(), key=lambda x: x["datetime"])


# ===========================================================================
# DATA FETCHER
# ===========================================================================

class DataFetcher:
    """
    Fetch historical 5m bars for backtesting.

    Priority:
      1. intraday_bars_5m  (materialized 5m table)
      2. intraday_bars     (1m table) resampled to 5m  [BUG-BT-1 fallback]
      3. EODHD API         (5m interval)
    """

    def __init__(self):
        self.api_key = os.getenv("EODHD_API_KEY")
        if not self.api_key:
            logger.warning("EODHD_API_KEY not set — will use PostgreSQL cache only")

    def _rows_to_bars(self, rows, source_label: str) -> List[Dict]:
        """Convert DB rows to normalized bar dicts with ET-naive datetimes."""
        bars = []
        for row in rows:
            dt = row["datetime"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if dt.tzinfo is not None:
                dt = dt.astimezone(ET).replace(tzinfo=None)
            bars.append({
                "datetime": dt,
                "open":     float(row["open"]),
                "high":     float(row["high"]),
                "low":      float(row["low"]),
                "close":    float(row["close"]),
                "volume":   int(row["volume"]),
            })
        return bars

    def fetch_from_cache(self, ticker: str, start: datetime, end: datetime) -> List[Dict]:
        """BUG-BT-1: query intraday_bars_5m first, fallback to 1m resample."""
        try:
            from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
            p    = ph()
            conn = get_conn()
            try:
                cur = dict_cursor(conn)

                cur.execute(
                    f"SELECT datetime, open, high, low, close, volume "
                    f"FROM intraday_bars_5m "
                    f"WHERE ticker = {p} AND datetime >= {p} AND datetime <= {p} "
                    f"ORDER BY datetime",
                    (ticker, start, end),
                )
                rows_5m = cur.fetchall()

                if rows_5m:
                    bars = self._rows_to_bars(rows_5m, "5m cache")
                    logger.info(f"[DATA] {ticker}: {len(bars)} bars from intraday_bars_5m")
                    self._log_bar_diagnostic(ticker, bars)
                    return bars

                logger.info(
                    f"[DATA] {ticker}: intraday_bars_5m empty — "
                    f"falling back to 1m resample"
                )
                cur.execute(
                    f"SELECT datetime, open, high, low, close, volume "
                    f"FROM intraday_bars "
                    f"WHERE ticker = {p} AND datetime >= {p} AND datetime <= {p} "
                    f"ORDER BY datetime",
                    (ticker, start, end),
                )
                rows_1m = cur.fetchall()

            finally:
                return_conn(conn)

            if rows_1m:
                bars_1m = self._rows_to_bars(rows_1m, "1m cache")
                bars_5m = resample_1m_to_5m(bars_1m)
                logger.info(
                    f"[DATA] {ticker}: resampled {len(bars_1m)} 1m bars "
                    f"→ {len(bars_5m)} 5m bars"
                )
                self._log_bar_diagnostic(ticker, bars_5m)
                return bars_5m

            return []

        except Exception as e:
            logger.warning(f"[DATA] Cache fetch failed for {ticker}: {e}")
            return []

    def _log_bar_diagnostic(self, ticker: str, bars: List[Dict]):
        """BUG-BT-2: Log first 3 + last bar datetimes to surface TZ issues."""
        if not bars:
            return
        sample = bars[:3] + (bars[-1:] if len(bars) > 3 else [])
        times  = [b["datetime"].strftime("%Y-%m-%d %H:%M") for b in sample]
        logger.info(f"[DATA] {ticker} bar datetimes (ET-naive): {times}")

    def fetch_from_eodhd(self, ticker: str, start: datetime, end: datetime) -> List[Dict]:
        if not self.api_key:
            return []
        url = f"https://eodhd.com/api/intraday/{ticker}.US"
        params = {
            "api_token": self.api_key,
            "interval":  "5m",
            "from":      int(start.timestamp()),
            "to":        int(end.timestamp()),
            "fmt":       "json",
        }
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                raw = resp.json()
                bars = []
                for r in raw:
                    dt = datetime.utcfromtimestamp(r["timestamp"]).astimezone(ET).replace(tzinfo=None)
                    bars.append({
                        "datetime": dt,
                        "open":   float(r["open"]),
                        "high":   float(r["high"]),
                        "low":    float(r["low"]),
                        "close":  float(r["close"]),
                        "volume": int(r.get("volume", 0)),
                    })
                logger.info(f"[DATA] {ticker}: {len(bars)} bars from EODHD")
                self._log_bar_diagnostic(ticker, bars)
                return bars
            else:
                logger.error(f"[DATA] EODHD {resp.status_code} for {ticker}")
        except Exception as e:
            logger.error(f"[DATA] EODHD fetch failed for {ticker}: {e}")
        return []

    def fetch(self, ticker: str, start: datetime, end: datetime) -> List[Dict]:
        bars = self.fetch_from_cache(ticker, start, end)
        if not bars:
            bars = self.fetch_from_eodhd(ticker, start, end)
        if not bars:
            logger.error(f"[DATA] No bars available for {ticker} — cannot backtest")
        return bars


# ===========================================================================
# STRATEGY HELPERS
# ===========================================================================

def _rth_bars(bars: List[Dict]) -> List[Dict]:
    """
    Return only Regular Trading Hours bars (>= 09:30 ET).
    BUG-BT-3/4/5/6: Pre-market bars pollute ATR, VWAP, FVG detection, and RVOL.
    """
    return [b for b in bars if b["datetime"].time() >= RTH_START]


def _compute_vwap(bars: List[Dict]) -> float:
    """Cumulative VWAP from bar list."""
    cum_tp_vol = sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in bars)
    cum_vol    = sum(b["volume"] for b in bars)
    return cum_tp_vol / cum_vol if cum_vol > 0 else 0.0


def _detect_fvg(bars: List[Dict], direction: str, min_size_pct: float) -> Optional[Dict]:
    """
    Scan most-recent 3-bar sequence for a Fair Value Gap.
    direction='BULL': c1.high < c3.low  (gap up)
    direction='BEAR': c1.low  > c3.high (gap down)
    """
    if len(bars) < 3:
        return None
    c1, _, c3 = bars[-3], bars[-2], bars[-1]
    if direction == "BULL":
        if c3["low"] > c1["high"]:
            size = (c3["low"] - c1["high"]) / c1["high"]
            if size >= min_size_pct:
                return {"fvg_top": c3["low"], "fvg_bottom": c1["high"],
                        "fvg_mid": (c3["low"] + c1["high"]) / 2}
    else:
        if c3["high"] < c1["low"]:
            size = (c1["low"] - c3["high"]) / c1["low"]
            if size >= min_size_pct:
                return {"fvg_top": c1["low"], "fvg_bottom": c3["high"],
                        "fvg_mid": (c1["low"] + c3["high"]) / 2}
    return None


# ===========================================================================
# SIGNAL STRATEGY  (matches BacktestEngine.run() strategy signature)
# ===========================================================================

def war_machine_strategy(
    lookback_bars: List[Dict],
    params: Dict,
) -> Optional[Dict]:
    """
    War Machine BOS + FVG strategy — compatible with BacktestEngine.run().

    Params accepted:
        fvg_min_size_pct  (default 0.005; TICKER_PARAMS may override)
        min_confidence    (default 65)
        rvol_min          (default 1.5; TICKER_PARAMS may override)
        _ticker           (optional; injected by run_single for per-ticker overrides)

    BacktestEngine passes lookback_bars = bars[max(0, i-100) : i+1] (last 100 bars).
    At 5m resolution that covers ~500 minutes / ~1.3 sessions, so OR bars
    from the current session are always present in the lookback window.

    Returns signal dict or None.
    """
    # BUG-BT-7: merge per-ticker overrides over CLI params
    ticker = params.get("_ticker", "").upper()
    effective_params = dict(params)
    if ticker and ticker in TICKER_PARAMS:
        # Only override if the caller didn't explicitly set a non-default value.
        # We treat the TICKER_PARAMS values as calibrated minimums — apply them
        # unconditionally so the per-ticker tuning always takes effect in batch mode.
        effective_params.update(TICKER_PARAMS[ticker])

    fvg_min   = effective_params.get("fvg_min_size_pct", 0.005)
    min_conf  = effective_params.get("min_confidence",   65)
    rvol_min  = effective_params.get("rvol_min",         1.5)

    if len(lookback_bars) < 20:
        return None

    current_bar = lookback_bars[-1]
    bar_time    = current_bar["datetime"]

    # RTH only; skip OR window and near-EOD
    if bar_time.time() < OR_END or bar_time.time() > EOD_CUT:
        return None

    session_date = bar_time.date()

    # Build OR high/low from OR bars of the current session
    or_bars = [
        b for b in lookback_bars
        if b["datetime"].date() == session_date
        and OR_START <= b["datetime"].time() <= OR_END
    ]
    if len(or_bars) < 2:
        return None

    or_high  = max(b["high"] for b in or_bars)
    or_low   = min(b["low"]  for b in or_bars)
    or_range = or_high - or_low

    # BUG-BT-3: was 0.002; lowered to 0.001 to allow low-vol tickers
    if or_range / or_low < OR_MIN_RANGE_PCT:
        return None

    # BOS: price has closed beyond the OR
    close = current_bar["close"]
    if close > or_high:
        direction = "BULL"
        bos_level = or_high
    elif close < or_low:
        direction = "BEAR"
        bos_level = or_low
    else:
        return None

    # BUG-BT-6: RVOL baseline uses RTH bars only to exclude pre-market
    # near-zero volume bars that deflate avg_vol and distort the ratio.
    rth_lookback = _rth_bars(lookback_bars)
    rth_vols = [b["volume"] for b in rth_lookback[-20:]]
    avg_vol = np.mean(rth_vols[:-1]) if len(rth_vols) > 1 else 1
    rvol    = current_bar["volume"] / avg_vol if avg_vol > 0 else 0
    if rvol < rvol_min:
        return None

    # BUG-BT-5: FVG scan on RTH bars only to exclude pre-market candles
    fvg = _detect_fvg(rth_lookback[-10:], direction, fvg_min)
    if not fvg:
        return None

    # BUG-BT-3: VWAP on RTH bars only (exclude pre-market volume)
    session_rth_bars = [
        b for b in rth_lookback
        if b["datetime"].date() == session_date
    ]
    vwap = _compute_vwap(session_rth_bars) if session_rth_bars else 0.0
    if direction == "BULL" and close < vwap:
        return None
    if direction == "BEAR" and close > vwap:
        return None

    # Confidence scoring
    or_range_pct = or_range / or_low
    conf_score = min(100, int(
        40
        + min(rvol * 10, 30)
        + min(or_range_pct * 2000, 20)
        + (10 if fvg else 0)
    ))
    if conf_score < min_conf:
        return None

    # BUG-BT-4: ATR on RTH bars only — pre-market inflated range
    # Stop tightened to ATR*1.0 (was 1.5). T1=ATR*1.0, T2=ATR*2.0.
    # R:R is now 1:1 at T1, 1:2 at T2 — no longer inverted.
    rth_for_atr = _rth_bars(lookback_bars[-30:])  # last 30 bars, RTH only
    atr_approx  = np.mean([b["high"] - b["low"] for b in rth_for_atr[-14:]]) if rth_for_atr else 0.01
    atr_approx  = max(atr_approx, 0.01)  # floor to avoid zero-size stop

    # BUG-BT-7: hard cap — stop distance cannot exceed MAX_STOP_PCT of entry.
    # Prevents NVDA/AMD wide-body candles from placing $3-4 stops on $100 entries
    # while T1 is only ATR*1.0 away, which inverts R:R despite BUG-BT-4 fix.
    max_stop_distance = close * MAX_STOP_PCT

    if direction == "BULL":
        raw_stop   = max(fvg["fvg_bottom"] - atr_approx * 0.1,
                         close - atr_approx * 1.0)
        stop       = max(raw_stop, close - max_stop_distance)  # cap at 1% below entry
        t1         = close + atr_approx * 1.0                  # T1 at 1R
        t2         = close + atr_approx * 2.0                  # T2 at 2R
        signal_key = "BUY"
    else:
        raw_stop   = min(fvg["fvg_top"] + atr_approx * 0.1,
                         close + atr_approx * 1.0)
        stop       = min(raw_stop, close + max_stop_distance)  # cap at 1% above entry
        t1         = close - atr_approx * 1.0
        t2         = close - atr_approx * 2.0
        signal_key = "SELL"

    return {
        "signal":     signal_key,
        "entry":      close,
        "stop":       stop,
        "t1":         t1,
        "t2":         t2,
        "confidence": conf_score,
        "direction":  direction,
        "rvol":       round(rvol, 2),
        "fvg_mid":    fvg["fvg_mid"],
        "bos_level":  bos_level,
    }


# ===========================================================================
# HOURLY WIN-RATE MAP  (feeds 47.P4-2)
# ===========================================================================

def build_hourly_win_rate(trades) -> Dict[int, Dict]:
    """
    Compute per-hour win rate from a list of Trade objects.
    Returns {hour: {'wins': int, 'total': int, 'win_rate': float}}
    """
    buckets: Dict[int, Dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    for t in trades:
        h = t.entry_time.hour if hasattr(t.entry_time, "hour") else 0
        buckets[h]["total"] += 1
        if t.pnl > 0:
            buckets[h]["wins"] += 1
    result = {}
    for h in sorted(buckets):
        total = buckets[h]["total"]
        wins  = buckets[h]["wins"]
        result[h] = {
            "wins":     wins,
            "total":    total,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
        }
    return result


def print_hourly_map(hourly: Dict[int, Dict], ticker: str = ""):
    prefix = f"[{ticker}] " if ticker else ""
    logger.info(f"{prefix}--- Hourly Win-Rate Map (feeds P4-2) ---")
    for h, d in hourly.items():
        bar = "█" * int(d["win_rate"] / 5)
        logger.info(
            f"  {h:02d}:xx  {d['win_rate']:5.1f}%  "
            f"({d['wins']:>3}/{d['total']:<3})  {bar}"
        )


# ===========================================================================
# WALK-FORWARD WINDOW PARAMS  (BUG-BT-8)
# ===========================================================================

def _wf_params_for_span(days: int) -> Optional[Dict]:
    """
    BUG-BT-8: Auto-scale walk-forward window params based on data span.

    The data actually starts from the earliest bar in intraday_bars_5m which
    may be significantly less than --days. We use the requested days as a proxy
    since we don't know the actual span before fetching.

    Returns dict with train_months/test_months/step_months, or None if
    insufficient data for even the smallest valid window.
    """
    if days >= 120:
        return {"train_months": 2, "test_months": 1, "step_months": 1}
    elif days >= 60:
        logger.info(
            f"[WALK-FORWARD] Data span {days}d < 120d — using 1m/1m windows "
            f"(train=1m test=1m). Use --days 180 for 2m/1m windows."
        )
        return {"train_months": 1, "test_months": 1, "step_months": 1}
    else:
        logger.warning(
            f"[WALK-FORWARD] Data span {days}d < 60d — insufficient for "
            f"any walk-forward window. Re-run with --days 120 or more."
        )
        return None


# ===========================================================================
# SINGLE-TICKER RUNNER
# ===========================================================================

def run_single(
    ticker: str,
    bars: List[Dict],
    params: Dict,
    walk_forward: bool,
    save: bool,
    output_dir: str,
    days: int = 90,
) -> Optional[Dict]:
    """
    Run either a single-pass backtest or walk-forward for one ticker.
    Returns a summary dict.

    BUG-BT-7: Injects _ticker into params so war_machine_strategy can apply
    per-ticker overrides from TICKER_PARAMS at signal evaluation time.
    """
    if not BACKTEST_AVAILABLE:
        logger.error("BacktestEngine not available — install War Machine dependencies")
        return None

    if not bars:
        logger.warning(f"[{ticker}] No bars — skipping")
        return None

    # BUG-BT-7: inject ticker so strategy can look up TICKER_PARAMS
    run_params = dict(params)
    run_params["_ticker"] = ticker

    if walk_forward:
        # BUG-BT-8: auto-scale window params to data span
        wf_kwargs = _wf_params_for_span(days)
        if wf_kwargs is None:
            logger.warning(f"[{ticker}] Walk-forward skipped — data span too short")
            return None

        wf = WalkForward(
            train_months=wf_kwargs["train_months"],
            test_months=wf_kwargs["test_months"],
            step_months=wf_kwargs["step_months"],
            optimization_metric="sharpe_ratio",
            min_train_bars=500,
        )
        results: WalkForwardResults = wf.run(
            ticker=ticker,
            bars=bars,
            strategy=war_machine_strategy,
            param_grid=DEFAULT_PARAM_GRID,
            initial_capital=10_000,
        )
        logger.info(results.summary())

        all_trades = results.all_test_trades
        summary = {
            "ticker":         ticker,
            "mode":           "walk_forward",
            "windows":        results.total_windows,
            "total_trades":   len(all_trades),
            "win_rate":       results.win_rate,
            "net_pnl":        results.net_pnl,
            "profit_factor":  results.profit_factor,
            "sharpe_ratio":   results.sharpe_ratio,
            "expectancy":     results.expectancy,
        }

    else:
        start_date = bars[0]["datetime"]
        end_date   = bars[-1]["datetime"]

        engine = BacktestEngine(
            initial_capital=10_000,
            commission_per_trade=0.50,
            slippage_pct=0.05,
            risk_per_trade_pct=1.0,
            enable_t1_t2_exits=True,
        )
        results: BacktestResults = engine.run(
            ticker=ticker,
            bars=bars,
            strategy=war_machine_strategy,
            strategy_params=run_params,
        )
        logger.info(results.summary())

        all_trades = results.trades
        summary = {
            "ticker":         ticker,
            "mode":           "single_pass",
            "start":          start_date.isoformat(),
            "end":            end_date.isoformat(),
            "total_trades":   results.total_trades,
            "win_rate":       results.win_rate,
            "net_pnl":        results.net_pnl,
            "profit_factor":  results.profit_factor,
            "sharpe_ratio":   results.sharpe_ratio,
            "expectancy":     results.expectancy,
            "max_drawdown":   results.max_drawdown,
        }

    hourly = build_hourly_win_rate(all_trades)
    print_hourly_map(hourly, ticker)
    summary["hourly_win_rates"] = hourly

    if save and all_trades:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        fname = Path(output_dir) / f"{ticker}_{date.today().isoformat()}.json"
        with open(fname, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        logger.info(f"[{ticker}] Results saved → {fname}")

    return summary


# ===========================================================================
# AGGREGATE SUMMARY
# ===========================================================================

def print_aggregate(summaries: List[Dict]):
    valid = [s for s in summaries if s and s.get("total_trades", 0) > 0]
    if not valid:
        logger.info("[AGGREGATE] No trades across any ticker")
        return

    total_trades = sum(s["total_trades"] for s in valid)
    avg_wr  = np.mean([s["win_rate"]      for s in valid])
    avg_pf  = np.mean([s["profit_factor"] for s in valid])
    tot_pnl = sum(s["net_pnl"]            for s in valid)

    logger.info("=" * 80)
    logger.info("AGGREGATE BATCH RESULTS")
    logger.info("=" * 80)
    logger.info(f"  Tickers run:    {len(valid)}")
    logger.info(f"  Total trades:   {total_trades}")
    logger.info(f"  Avg win rate:   {avg_wr:.1f}%")
    logger.info(f"  Avg prof factor:{avg_pf:.2f}")
    logger.info(f"  Net P&L (sum):  ${tot_pnl:,.2f}")
    logger.info("")
    logger.info(f"  {'Ticker':<8} {'Trades':>7} {'WR%':>7} {'PF':>6} {'PnL':>12}")
    logger.info(f"  {'-'*8} {'-'*7} {'-'*7} {'-'*6} {'-'*12}")
    for s in sorted(valid, key=lambda x: x["net_pnl"], reverse=True):
        logger.info(
            f"  {s['ticker']:<8} {s['total_trades']:>7} "
            f"{s['win_rate']:>6.1f}% {s['profit_factor']:>6.2f} "
            f"${s['net_pnl']:>10,.2f}"
        )
    logger.info("=" * 80)


# ===========================================================================
# CLI
# ===========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="War Machine — Unified Production Backtest (47.P4-1 / BUG-BT-1-8)"
    )
    parser.add_argument("--ticker",        help="Single ticker to backtest")
    parser.add_argument("--batch",         action="store_true",
                        help=f"Run all default tickers: {DEFAULT_TICKERS}")
    parser.add_argument("--tickers",       help="Comma-separated custom ticker list")
    parser.add_argument("--start",         help="Start date YYYY-MM-DD")
    parser.add_argument("--end",           help="End date YYYY-MM-DD")
    parser.add_argument("--days",          type=int, default=90,
                        help="Days back from today (default 90)")
    parser.add_argument("--walk-forward",  action="store_true",
                        help="Run walk-forward validation (auto-scales window to data span)")
    parser.add_argument("--save",          action="store_true",
                        help="Save JSON results to output dir")
    parser.add_argument("--output-dir",    default="backtests/results",
                        help="Output directory for JSON results")

    parser.add_argument("--fvg-min",  type=float, default=0.005)
    parser.add_argument("--min-conf", type=int,   default=65)
    parser.add_argument("--rvol-min", type=float, default=1.5)

    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    elif args.batch:
        tickers = DEFAULT_TICKERS
    elif args.ticker:
        tickers = [args.ticker.upper()]
    else:
        tickers = ["AAPL"]

    end_dt   = datetime.strptime(args.end,   "%Y-%m-%d") if args.end   else datetime.now()
    start_dt = datetime.strptime(args.start, "%Y-%m-%d") if args.start else end_dt - timedelta(days=args.days)

    params = {
        "fvg_min_size_pct": args.fvg_min,
        "min_confidence":   args.min_conf,
        "rvol_min":         args.rvol_min,
    }

    fetcher   = DataFetcher()
    summaries = []

    for ticker in tickers:
        logger.info(f"\n{'='*80}")
        logger.info(f"  BACKTESTING {ticker}  |  {start_dt.date()} → {end_dt.date()}")
        logger.info(f"{'='*80}\n")

        bars = fetcher.fetch(ticker, start_dt, end_dt)
        summary = run_single(
            ticker=ticker,
            bars=bars,
            params=params,
            walk_forward=args.walk_forward,
            save=args.save,
            output_dir=args.output_dir,
            days=args.days,
        )
        summaries.append(summary)

    if len(tickers) > 1:
        print_aggregate(summaries)


if __name__ == "__main__":
    main()
