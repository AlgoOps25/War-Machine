#!/usr/bin/env python3
"""
Walk-Forward Backtest Engine — War Machine (47.P4-1)

Replays 90 days of EODHD 5m bars through the production signal pipeline
(compute_opening_range_from_bars -> detect_breakout_after_or ->
 detect_fvg_after_break -> passes_vwap_gate -> compute_stop_and_targets)
and simulates trade outcomes bar-by-bar.

Outputs:
  backtests/results/<ticker>_trades.csv       — every trade with full detail
  backtests/results/<ticker>_summary.json     — aggregate stats
  backtests/results/hourly_win_rates.json     — feeds 47.P4-2 (replaces fabricated data)
  backtests/results/walk_forward_folds.json   — per-fold equity curve

Usage:
  python scripts/backtesting/walk_forward_backtest.py --tickers SPY,QQQ,AAPL --days 90
  python scripts/backtesting/walk_forward_backtest.py --tickers SPY --days 90 --out backtests/results
  python scripts/backtesting/walk_forward_backtest.py --tickers SPY --days 30  # quick smoke test
"""

import sys
import os
import json
import logging
import argparse
import csv
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import numpy as np

# ── Project root on path ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

_ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("wf_backtest")

# ── Production pipeline imports ─────────────────────────────────────────────
try:
    from app.core.sniper import (
        compute_opening_range_from_bars,
        detect_breakout_after_or,
        detect_fvg_after_break,
        compute_vwap,
        passes_vwap_gate,
        compute_stop_and_targets,
    )
    PIPELINE_OK = True
    log.info("✅ Production pipeline loaded")
except Exception as e:
    PIPELINE_OK = False
    log.error(f"❌ Pipeline import failed: {e}")
    sys.exit(1)

try:
    from app.validation.cfw6_confirmation import grade_signal_with_confirmations
    GRADE_OK = True
except Exception:
    GRADE_OK = False

try:
    from utils import config as cfg
except Exception:
    cfg = None


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

OR_END_MINUTE  = 45          # 9:30 → 9:45 opening range
EOD_CLOSE_HOUR = 15
EOD_CLOSE_MIN  = 55
COMMISSION     = 1.0         # $ per fill (round-trip = 2x)
SLIPPAGE_PCT   = 0.0002      # 0.02% per fill

# Default params (overridden from config if available)
FVG_MIN_SIZE_PCT = getattr(cfg, "FVG_MIN_SIZE_PCT", 0.003)  # 0.3%
OR_MIN_RANGE_PCT = getattr(cfg, "OR_MIN_RANGE_PCT", 0.003)
MIN_CONFIDENCE   = getattr(cfg, "MIN_CONFIDENCE",   0.45)


# ═══════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════

class EODHDFetcher:
    """Fetch 5m intraday bars from EODHD (cache-first via PostgreSQL if available)."""

    BASE_URL = "https://eodhd.com/api/intraday/{ticker}.US"

    def __init__(self):
        self.api_key = os.getenv("EODHD_API_KEY", "")
        if not self.api_key:
            log.warning("EODHD_API_KEY not set — will try local DB cache only")

    def fetch(self, ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
        df = self._from_cache(ticker, start, end)
        if df.empty and self.api_key:
            df = self._from_eodhd(ticker, start, end)
        if df.empty:
            log.error(f"No data available for {ticker} {start.date()} – {end.date()}")
        return df

    def _from_cache(self, ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
        try:
            from app.data.db_connection import get_conn, return_conn, dict_cursor, ph
            p = ph()
            conn = get_conn()
            cur  = dict_cursor(conn)
            cur.execute(
                f"SELECT datetime, open, high, low, close, volume "
                f"FROM intraday_bars "
                f"WHERE ticker={p} AND datetime>={p} AND datetime<={p} "
                f"ORDER BY datetime",
                (ticker, start, end)
            )
            rows = cur.fetchall()
            return_conn(conn)
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame([dict(r) for r in rows])
            df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_localize(None)
            log.info(f"  cache: {len(df)} bars for {ticker}")
            return df
        except Exception as e:
            log.debug(f"Cache miss ({ticker}): {e}")
            return pd.DataFrame()

    def _from_eodhd(self, ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
        url    = self.BASE_URL.format(ticker=ticker)
        params = {
            "api_token": self.api_key,
            "interval":  "5m",
            "from":      int(start.timestamp()),
            "to":        int(end.timestamp()),
            "fmt":       "json",
        }
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code != 200:
                log.error(f"EODHD {r.status_code} for {ticker}")
                return pd.DataFrame()
            data = r.json()
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s").dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.tz_localize(None)
            df = df[["datetime","open","high","low","close","volume"]].copy()
            log.info(f"  EODHD: {len(df)} bars for {ticker}")
            return df
        except Exception as e:
            log.error(f"EODHD fetch error ({ticker}): {e}")
            return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════
# BAR UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def split_into_sessions(df: pd.DataFrame) -> List[pd.DataFrame]:
    """Split a multi-day DataFrame into individual session DataFrames."""
    df = df.copy()
    # Drop bars with NaN in any OHLC column before splitting
    df = df.dropna(subset=["open", "high", "low", "close"])
    # Fill NaN volume with 0
    df["volume"] = df["volume"].fillna(0)
    df["date"] = df["datetime"].dt.date
    sessions = []
    for d, grp in df.groupby("date"):
        grp = grp.sort_values("datetime").reset_index(drop=True)
        # Keep only RTH bars: 9:30 – 16:00
        grp = grp[
            (grp["datetime"].dt.hour * 60 + grp["datetime"].dt.minute >= 570) &
            (grp["datetime"].dt.hour * 60 + grp["datetime"].dt.minute <  960)
        ]
        if len(grp) >= 20:  # skip sessions with too few bars
            sessions.append(grp.reset_index(drop=True))
    return sessions


def bars_to_sniper_format(df: pd.DataFrame) -> List[Dict]:
    """Convert DataFrame rows to the bar dict format sniper functions expect."""
    bars = []
    for _, row in df.iterrows():
        # Skip any residual NaN OHLC rows
        if pd.isna(row["open"]) or pd.isna(row["high"]) or pd.isna(row["low"]) or pd.isna(row["close"]):
            continue
        vol = row["volume"]
        bars.append({
            "time":   row["datetime"],
            "open":   float(row["open"]),
            "high":   float(row["high"]),
            "low":    float(row["low"]),
            "close":  float(row["close"]),
            "volume": int(vol) if not pd.isna(vol) else 0,
        })
    return bars


def _unpack_or_result(raw) -> Optional[Dict]:
    """
    compute_opening_range_from_bars can return either:
      - a dict: {"or_high": .., "or_low": .., "valid": True, ...}
      - a tuple: (or_high, or_low)  or  (or_high, or_low, meta_dict)
    Normalize to dict form. Returns None if the result is falsy or invalid.
    """
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw if raw.get("valid", True) else None
    if isinstance(raw, (tuple, list)):
        if len(raw) >= 2:
            or_high, or_low = float(raw[0]), float(raw[1])
            extra = raw[2] if len(raw) > 2 else {}
            if isinstance(extra, dict):
                result = {"or_high": or_high, "or_low": or_low, "valid": True, **extra}
            else:
                result = {"or_high": or_high, "or_low": or_low, "valid": True}
            return result if or_high > or_low else None
    return None


def _session_first_time(session_df: pd.DataFrame) -> Optional[object]:
    """Safely get the datetime of the first bar in a session DataFrame."""
    if session_df is None or len(session_df) == 0:
        return None
    return session_df.iloc[0]["datetime"]


# ═══════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION
# ═══════════════════════════════════════════════════════════════════════════

def simulate_trade(
    entry_bar_idx: int,
    bars: List[Dict],
    direction: str,
    entry_price: float,
    stop_price:  float,
    t1_price:    float,
    t2_price:    float,
) -> Dict:
    """
    Replay bars from entry_bar_idx forward.
    Returns a dict with exit_price, exit_reason, pnl_pts, r_multiple.

    Scale-out logic mirrors production:
      - Hit T1: close 50% at T1, move stop to breakeven
      - Hit T2 (after T1): close remainder at T2
      - Hit stop: full loss
      - EOD (15:55): close at last bar price
    """
    entry_price  = float(entry_price)
    stop_price   = float(stop_price)
    t1_price     = float(t1_price)
    t2_price     = float(t2_price)
    risk         = abs(entry_price - stop_price)

    t1_hit       = False
    be_stop      = stop_price
    entry_time   = bars[entry_bar_idx]["time"]

    slippage     = entry_price * SLIPPAGE_PCT
    actual_entry = entry_price + slippage if direction == "bull" else entry_price - slippage

    for bar in bars[entry_bar_idx + 1:]:
        t   = bar["time"]
        hi  = float(bar["high"])
        lo  = float(bar["low"])
        eod = (t.hour == EOD_CLOSE_HOUR and t.minute >= EOD_CLOSE_MIN) or t.hour > EOD_CLOSE_HOUR

        if eod:
            exit_p = float(bar["close"])
            pnl    = (exit_p - actual_entry) if direction == "bull" else (actual_entry - exit_p)
            return {
                "exit_price":  round(exit_p, 4),
                "exit_reason": "EOD",
                "exit_time":   t,
                "entry_time":  entry_time,
                "pnl_pts":     round(pnl, 4),
                "r_multiple":  round(pnl / risk, 2) if risk else 0.0,
            }

        if direction == "bull":
            if lo <= be_stop:
                exit_p = be_stop
                pnl    = exit_p - actual_entry
                return {
                    "exit_price":  round(exit_p, 4),
                    "exit_reason": "STOP",
                    "exit_time":   t,
                    "entry_time":  entry_time,
                    "pnl_pts":     round(pnl, 4),
                    "r_multiple":  round(pnl / risk, 2) if risk else 0.0,
                }
            if not t1_hit and hi >= t1_price:
                t1_hit  = True
                be_stop = actual_entry
            if t1_hit and hi >= t2_price:
                exit_p = t2_price
                pnl    = exit_p - actual_entry
                return {
                    "exit_price":  round(exit_p, 4),
                    "exit_reason": "T2",
                    "exit_time":   t,
                    "entry_time":  entry_time,
                    "pnl_pts":     round(pnl, 4),
                    "r_multiple":  round(pnl / risk, 2) if risk else 0.0,
                }
        else:  # bear
            if hi >= be_stop:
                exit_p = be_stop
                pnl    = actual_entry - exit_p
                return {
                    "exit_price":  round(exit_p, 4),
                    "exit_reason": "STOP",
                    "exit_time":   t,
                    "entry_time":  entry_time,
                    "pnl_pts":     round(pnl, 4),
                    "r_multiple":  round(pnl / risk, 2) if risk else 0.0,
                }
            if not t1_hit and lo <= t1_price:
                t1_hit  = True
                be_stop = actual_entry
            if t1_hit and lo <= t2_price:
                exit_p = t2_price
                pnl    = actual_entry - exit_p
                return {
                    "exit_price":  round(exit_p, 4),
                    "exit_reason": "T2",
                    "exit_time":   t,
                    "entry_time":  entry_time,
                    "pnl_pts":     round(pnl, 4),
                    "r_multiple":  round(pnl / risk, 2) if risk else 0.0,
                }

    exit_p = float(bars[-1]["close"])
    pnl    = (exit_p - actual_entry) if direction == "bull" else (actual_entry - exit_p)
    return {
        "exit_price":  round(exit_p, 4),
        "exit_reason": "EOD",
        "exit_time":   bars[-1]["time"],
        "entry_time":  entry_time,
        "pnl_pts":     round(pnl, 4),
        "r_multiple":  round(pnl / risk, 2) if risk else 0.0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SESSION RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_session(ticker: str, session_bars: pd.DataFrame) -> Optional[Dict]:
    """
    Run one trading session (one day) through the production pipeline.
    Returns a trade dict if a signal fired, else None.
    """
    bars = bars_to_sniper_format(session_bars)
    if len(bars) < 10:
        return None

    session_date = bars[0]["time"].date()

    # ── Step 1: Opening Range ───────────────────────────────────────────────
    try:
        raw_or = compute_opening_range_from_bars(bars)
        or_result = _unpack_or_result(raw_or)
    except Exception as e:
        log.debug(f"  OR failed {session_date}: {e}")
        return None

    if not or_result:
        return None

    or_high = or_result["or_high"]
    or_low  = or_result["or_low"]
    or_range_pct = (or_high - or_low) / or_low
    if or_range_pct < OR_MIN_RANGE_PCT:
        return None

    # ── Step 2: Breakout detection ──────────────────────────────────────────
    try:
        breakout = detect_breakout_after_or(bars, or_result)
    except Exception as e:
        log.debug(f"  Breakout failed {session_date}: {e}")
        return None

    if not breakout:
        return None
    if isinstance(breakout, dict) and not breakout.get("detected", True):
        return None

    if isinstance(breakout, dict):
        direction      = breakout.get("direction", "bull")
        breakout_idx   = breakout.get("bar_index", 0)
        breakout_price = breakout.get("price", or_high if direction == "bull" else or_low)
    else:
        direction      = str(breakout[0]) if len(breakout) > 0 else "bull"
        breakout_idx   = int(breakout[1]) if len(breakout) > 1 else 0
        breakout_price = float(breakout[2]) if len(breakout) > 2 else or_high

    # ── Step 3: FVG after breakout ──────────────────────────────────────────
    try:
        fvg = detect_fvg_after_break(bars, breakout)
    except Exception as e:
        log.debug(f"  FVG failed {session_date}: {e}")
        fvg = None

    if not fvg:
        return None
    if isinstance(fvg, dict) and not fvg.get("detected", True):
        return None

    if isinstance(fvg, dict):
        fvg_mid  = fvg.get("fvg_mid", breakout_price)
        fvg_size = fvg.get("fvg_size_pct", 0.0)
    else:
        fvg_mid  = breakout_price
        fvg_size = FVG_MIN_SIZE_PCT

    if fvg_size < FVG_MIN_SIZE_PCT:
        return None

    # ── Step 4: VWAP gate ───────────────────────────────────────────────────
    try:
        vwap_data = compute_vwap(bars[:breakout_idx + 1])
        if not passes_vwap_gate(breakout_price, direction, vwap_data):
            return None
    except Exception:
        pass

    # ── Step 5: Stop & targets ──────────────────────────────────────────────
    try:
        levels = compute_stop_and_targets(
            bars, direction, breakout_price, or_result, fvg
        )
    except Exception as e:
        log.debug(f"  Levels failed {session_date}: {e}")
        return None

    if not levels:
        return None

    if isinstance(levels, dict):
        stop = levels.get("stop")
        t1   = levels.get("t1")
        t2   = levels.get("t2")
    elif isinstance(levels, (tuple, list)) and len(levels) >= 3:
        stop, t1, t2 = float(levels[0]), float(levels[1]), float(levels[2])
    else:
        return None

    conf = breakout.get("confidence", 0.5) if isinstance(breakout, dict) else 0.5

    if not all([stop, t1, t2]):
        return None
    if conf < MIN_CONFIDENCE:
        return None

    # ── Step 6: Grade ───────────────────────────────────────────────────────
    grade = "A"
    if GRADE_OK:
        try:
            signal = {
                "ticker": ticker, "direction": direction,
                "confidence": conf, "or_high": or_high, "or_low": or_low,
                "fvg_mid": fvg_mid, "fvg_size_pct": fvg_size,
            }
            graded = grade_signal_with_confirmations(signal, bars)
            grade  = graded.get("grade", "A")
            conf   = graded.get("confidence", conf)
        except Exception:
            pass

    # ── Step 7: Simulate outcome ────────────────────────────────────────────
    if isinstance(fvg, dict):
        entry_bar_idx = fvg.get("entry_bar_index", breakout_idx)
        entry_price   = fvg.get("entry_price", bars[entry_bar_idx]["close"])
    else:
        entry_bar_idx = breakout_idx
        entry_price   = bars[entry_bar_idx]["close"]

    if entry_bar_idx >= len(bars) - 1:
        return None

    outcome = simulate_trade(
        entry_bar_idx, bars, direction,
        entry_price, stop, t1, t2
    )

    entry_hour = bars[entry_bar_idx]["time"].hour
    entry_min  = bars[entry_bar_idx]["time"].minute

    return {
        "ticker":       ticker,
        "date":         str(session_date),
        "direction":    direction,
        "grade":        grade,
        "confidence":   round(conf, 4),
        "or_high":      round(or_high, 4),
        "or_low":       round(or_low, 4),
        "or_range_pct": round(or_range_pct * 100, 3),
        "fvg_size_pct": round(fvg_size * 100, 3),
        "entry_price":  round(entry_price, 4),
        "stop_price":   round(stop, 4),
        "t1_price":     round(t1, 4),
        "t2_price":     round(t2, 4),
        "entry_time":   str(outcome["entry_time"]),
        "exit_time":    str(outcome["exit_time"]),
        "exit_price":   outcome["exit_price"],
        "exit_reason":  outcome["exit_reason"],
        "pnl_pts":      outcome["pnl_pts"],
        "r_multiple":   outcome["r_multiple"],
        "win":          1 if outcome["pnl_pts"] > 0 else 0,
        "entry_hour":   entry_hour,
        "entry_minute": entry_min,
    }


# ═══════════════════════════════════════════════════════════════════════════
# WALK-FORWARD LOGIC
# ═══════════════════════════════════════════════════════════════════════════

def build_walk_forward_folds(
    sessions: List[pd.DataFrame], fold_size: int = 30
) -> List[Dict]:
    """
    Split sessions into walk-forward folds.
    Each fold: train on `fold_size` days, test on next day.
    """
    folds = []
    for i in range(fold_size, len(sessions)):
        train_start_t = _session_first_time(sessions[i - fold_size])
        train_end_t   = _session_first_time(sessions[i - 1])
        test_t        = _session_first_time(sessions[i])
        folds.append({
            "train_start": train_start_t.date() if train_start_t is not None else None,
            "train_end":   train_end_t.date()   if train_end_t   is not None else None,
            "test_date":   test_t.date()         if test_t        is not None else None,
            "test_idx":    i,
        })
    return folds


# ═══════════════════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════════════════

def compute_stats(trades: List[Dict]) -> Dict:
    if not trades:
        return {"total_trades": 0}

    wins   = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    rs     = [t["r_multiple"] for t in trades]

    win_rate  = len(wins) / len(trades) * 100
    avg_r     = np.mean(rs)
    median_r  = np.median(rs)
    avg_win_r = np.mean([t["r_multiple"] for t in wins])  if wins   else 0.0
    avg_los_r = np.mean([t["r_multiple"] for t in losses]) if losses else 0.0
    max_dd    = _max_drawdown(rs)
    profit_f  = sum(t["r_multiple"] for t in wins) / abs(sum(t["r_multiple"] for t in losses)) if losses else float("inf")

    by_reason = defaultdict(int)
    for t in trades:
        by_reason[t["exit_reason"]] += 1

    return {
        "total_trades":   len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate_pct":   round(win_rate, 1),
        "avg_r":          round(avg_r, 3),
        "median_r":       round(median_r, 3),
        "avg_win_r":      round(avg_win_r, 3),
        "avg_loss_r":     round(avg_los_r, 3),
        "profit_factor":  round(profit_f, 2),
        "max_drawdown_r": round(max_dd, 3),
        "exit_reasons":   dict(by_reason),
    }


def _max_drawdown(rs: List[float]) -> float:
    """Max peak-to-trough R drawdown from cumulative R curve."""
    cum = np.cumsum(rs)
    peak = cum[0]
    max_dd = 0.0
    for v in cum:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


def build_hourly_win_rates(trades: List[Dict]) -> Dict:
    by_hour = defaultdict(list)
    for t in trades:
        by_hour[t["entry_hour"]].append(t["win"])

    result = {}
    for hour in range(9, 16):
        bucket = by_hour.get(hour, [])
        if len(bucket) >= 3:
            result[str(hour)] = {
                "win_rate":    round(sum(bucket) / len(bucket) * 100, 1),
                "sample_size": len(bucket),
            }
        else:
            result[str(hour)] = {"win_rate": None, "sample_size": len(bucket)}
    return result


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def run(tickers: List[str], days: int, out_dir: str, fold_size: int = 30):
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    fetcher   = EODHDFetcher()
    all_trades: List[Dict] = []

    end_dt   = datetime.now()
    start_dt = end_dt - timedelta(days=days)

    for ticker in tickers:
        log.info(f"\n{'='*60}")
        log.info(f"  {ticker}  |  {start_dt.date()} → {end_dt.date()}")
        log.info(f"{'='*60}")

        df = fetcher.fetch(ticker, start_dt, end_dt)
        if df.empty:
            log.warning(f"  Skipping {ticker} — no data")
            continue

        sessions = split_into_sessions(df)
        log.info(f"  {len(sessions)} trading sessions loaded")

        if len(sessions) < fold_size + 1:
            log.warning(f"  Not enough sessions for walk-forward ({len(sessions)} < {fold_size+1}), running flat")
            folds = None
        else:
            folds = build_walk_forward_folds(sessions, fold_size)
            log.info(f"  {len(folds)} walk-forward folds")

        ticker_trades: List[Dict] = []
        wf_fold_results = []

        if folds:
            for fold in folds:
                trade = run_session(ticker, sessions[fold["test_idx"]])
                if trade:
                    ticker_trades.append(trade)
                    wf_fold_results.append({
                        "test_date":  str(fold["test_date"]),
                        "train_days": fold_size,
                        "r_multiple": trade["r_multiple"],
                        "win":        trade["win"],
                    })
        else:
            for session in sessions:
                trade = run_session(ticker, session)
                if trade:
                    ticker_trades.append(trade)

        log.info(f"  {len(ticker_trades)} signals fired out of {len(sessions)} sessions")

        if ticker_trades:
            stats = compute_stats(ticker_trades)
            log.info(f"  Win rate: {stats['win_rate_pct']}%  |  Avg R: {stats['avg_r']}  |  PF: {stats['profit_factor']}")

            csv_path = out_path / f"{ticker}_trades.csv"
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=ticker_trades[0].keys())
                writer.writeheader()
                writer.writerows(ticker_trades)
            log.info(f"  Trades saved → {csv_path}")

            summary = {"ticker": ticker, "days": days, **stats}
            json_path = out_path / f"{ticker}_summary.json"
            json_path.write_text(json.dumps(summary, indent=2))
            log.info(f"  Summary saved → {json_path}")

            if wf_fold_results:
                wf_path = out_path / f"{ticker}_walk_forward_folds.json"
                wf_path.write_text(json.dumps(wf_fold_results, indent=2))

        all_trades.extend(ticker_trades)

    if all_trades:
        agg_stats = compute_stats(all_trades)
        agg_path  = out_path / "aggregate_summary.json"
        agg_path.write_text(json.dumps({"tickers": tickers, "days": days, **agg_stats}, indent=2))
        log.info(f"\nAggregate summary → {agg_path}")
        log.info(f"Total trades across all tickers: {agg_stats['total_trades']}")
        log.info(f"Overall win rate: {agg_stats['win_rate_pct']}%  |  Avg R: {agg_stats['avg_r']}")

        hourly = build_hourly_win_rates(all_trades)
        hourly_path = out_path / "hourly_win_rates.json"
        hourly_path.write_text(json.dumps(hourly, indent=2))
        log.info(f"Hourly win rates → {hourly_path}  (feeds entry_timing.py 47.P4-2)")
    else:
        log.warning("No trades generated. Check EODHD_API_KEY and pipeline imports.")


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Backtest — War Machine")
    parser.add_argument("--tickers", default="SPY",  help="Comma-separated tickers (default: SPY)")
    parser.add_argument("--days",    type=int, default=90, help="Lookback days (default: 90)")
    parser.add_argument("--out",     default="backtests/results", help="Output directory")
    parser.add_argument("--fold",    type=int, default=30, help="Walk-forward fold size in days (default: 30)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    run(tickers, args.days, args.out, args.fold)


if __name__ == "__main__":
    main()
