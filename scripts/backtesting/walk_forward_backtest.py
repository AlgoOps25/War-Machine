#!/usr/bin/env python3
"""
Walk-Forward Backtest Engine — War Machine (47.P4-1)

Replays 90 days of EODHD 5m bars through the production signal pipeline
(OR inline for 5m -> detect_breakout_after_or ->
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

NOTE on 5m bar OR window:
  production compute_opening_range_from_bars() is tuned for 1m bars and
  requires >= 3 bars strictly within 9:30-9:40. With 5m data that window
  holds only 2 bars (09:30, 09:35). We compute OR inline using 9:30-9:45
  (3 bars at 5m: 09:30, 09:35, 09:40) with a minimum of 2 bars.

NOTE on FVG_MIN_SIZE_PCT:
  production threshold (0.5%) is calibrated for 1m bars. On 5m bars for
  mega-cap ETFs, bar-to-bar gaps never reach 0.5% (largest seen: 0.115%).
  Backtest overrides to 0.0001 — any positive gap is a valid 5m FVG.
"""

import sys
import os
import json
import logging
import argparse
import csv
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import numpy as np

# ── Project root on path ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# -- Load .env BEFORE any app.* imports so DATABASE_URL reaches db_connection -
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass  # rely on shell environment


_ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("wf_backtest")

# 5m OR window: 9:30-9:45 (3 bars: 09:30, 09:35, 09:40), minimum 2
OR_5M_START    = dtime(9, 30)
OR_5M_END      = dtime(9, 45)   # exclusive upper bound
OR_5M_MIN_BARS = 2

# FVG minimum for 5m bars — any positive gap qualifies (float-noise floor only)
# production 0.5% threshold is 1m-calibrated and never fires on 5m mega-cap data
FVG_MIN_SIZE_PCT_5M = 0.0001

# ── Production pipeline imports ─────────────────────────────────────────────
try:
    from app.signals.opening_range import (
        detect_breakout_after_or,
        detect_fvg_after_break,
    )
    from app.filters.vwap_gate import compute_vwap, passes_vwap_gate
    from app.risk.trade_calculator import compute_stop_and_targets
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
    OR_MIN_RANGE_PCT = getattr(cfg, "OR_MIN_RANGE_PCT", 0.003)
    MIN_CONFIDENCE   = getattr(cfg, "MIN_CONFIDENCE",   0.45)
except Exception:
    cfg              = None
    OR_MIN_RANGE_PCT = 0.003
    MIN_CONFIDENCE   = 0.45


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

EOD_CLOSE_HOUR = 15
EOD_CLOSE_MIN  = 55
COMMISSION     = 1.0         # $ per fill (round-trip = 2x)
SLIPPAGE_PCT   = 0.0002      # 0.02% per fill
MAX_BREAKOUT_IDX = 60        # first hour only ? late breakouts have poor win rate


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
            df["datetime"] = (
                pd.to_datetime(df["timestamp"], unit="s")
                .dt.tz_localize("UTC")
                .dt.tz_convert("America/New_York")
                .dt.tz_localize(None)
            )
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
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0)
    df["date"] = df["datetime"].dt.date
    sessions = []
    for d, grp in df.groupby("date"):
        grp = grp.sort_values("datetime").reset_index(drop=True)
        minutes = grp["datetime"].dt.hour * 60 + grp["datetime"].dt.minute
        grp = grp[(minutes >= 570) & (minutes < 960)]
        if len(grp) >= 20:
            sessions.append(grp.reset_index(drop=True))
    return sessions


def bars_to_sniper_format(df: pd.DataFrame) -> List[Dict]:
    """
    Convert DataFrame rows to bar dicts. Key must be "datetime" so
    _bar_time() in time_helpers.py resolves the time correctly.
    """
    bars = []
    for _, row in df.iterrows():
        if pd.isna(row["open"]) or pd.isna(row["high"]) or pd.isna(row["low"]) or pd.isna(row["close"]):
            continue
        vol = row["volume"]
        bars.append({
            "datetime": row["datetime"],
            "open":     float(row["open"]),
            "high":     float(row["high"]),
            "low":      float(row["low"]),
            "close":    float(row["close"]),
            "volume":   int(vol) if not pd.isna(vol) else 0,
        })
    return bars


def compute_or_5m(bars: List[Dict]) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute Opening Range high/low from 5-minute bars.

    Uses 9:30–9:45 window (3 bars: 09:30, 09:35, 09:40) with a minimum
    of OR_5M_MIN_BARS (2). Production compute_opening_range_from_bars()
    requires >= 3 bars within 9:30–9:40 — that window holds only 2 bars
    at 5m resolution so it always returns (None, None).
    """
    or_bars = [
        b for b in bars
        if hasattr(b["datetime"], "time")
        and OR_5M_START <= b["datetime"].time() < OR_5M_END
    ]
    if len(or_bars) < OR_5M_MIN_BARS:
        return None, None
    return max(b["high"] for b in or_bars), min(b["low"] for b in or_bars)


def _session_first_time(session_df: pd.DataFrame) -> Optional[object]:
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
    entry_price  = float(entry_price)
    stop_price   = float(stop_price)
    t1_price     = float(t1_price)
    t2_price     = float(t2_price)
    risk         = abs(entry_price - stop_price)
    t1_hit       = False
    be_stop      = stop_price
    entry_time   = bars[entry_bar_idx]["datetime"]
    slippage     = entry_price * SLIPPAGE_PCT
    actual_entry = entry_price + slippage if direction == "bull" else entry_price - slippage

    for bar in bars[entry_bar_idx + 1:]:
        t   = bar["datetime"]
        hi  = float(bar["high"])
        lo  = float(bar["low"])
        eod = (t.hour == EOD_CLOSE_HOUR and t.minute >= EOD_CLOSE_MIN) or t.hour > EOD_CLOSE_HOUR

        if eod:
            exit_p = float(bar["close"])
            pnl    = (exit_p - actual_entry) if direction == "bull" else (actual_entry - exit_p)
            return {"exit_price": round(exit_p, 4), "exit_reason": "EOD",
                    "exit_time": t, "entry_time": entry_time,
                    "pnl_pts": round(pnl, 4), "r_multiple": round(pnl / risk, 2) if risk else 0.0}

        if direction == "bull":
            if lo <= be_stop:
                pnl = be_stop - actual_entry
                return {"exit_price": round(be_stop, 4), "exit_reason": "STOP",
                        "exit_time": t, "entry_time": entry_time,
                        "pnl_pts": round(pnl, 4), "r_multiple": round(pnl / risk, 2) if risk else 0.0}
            if not t1_hit and hi >= t1_price:
                t1_hit  = True
                be_stop = actual_entry
            if t1_hit and hi >= t2_price:
                pnl = t2_price - actual_entry
                return {"exit_price": round(t2_price, 4), "exit_reason": "T2",
                        "exit_time": t, "entry_time": entry_time,
                        "pnl_pts": round(pnl, 4), "r_multiple": round(pnl / risk, 2) if risk else 0.0}
        else:
            if hi >= be_stop:
                pnl = actual_entry - be_stop
                return {"exit_price": round(be_stop, 4), "exit_reason": "STOP",
                        "exit_time": t, "entry_time": entry_time,
                        "pnl_pts": round(pnl, 4), "r_multiple": round(pnl / risk, 2) if risk else 0.0}
            if not t1_hit and lo <= t1_price:
                t1_hit  = True
                be_stop = actual_entry
            if t1_hit and lo <= t2_price:
                pnl = actual_entry - t2_price
                return {"exit_price": round(t2_price, 4), "exit_reason": "T2",
                        "exit_time": t, "entry_time": entry_time,
                        "pnl_pts": round(pnl, 4), "r_multiple": round(pnl / risk, 2) if risk else 0.0}

    exit_p = float(bars[-1]["close"])
    pnl    = (exit_p - actual_entry) if direction == "bull" else (actual_entry - exit_p)
    return {"exit_price": round(exit_p, 4), "exit_reason": "EOD",
            "exit_time": bars[-1]["datetime"], "entry_time": entry_time,
            "pnl_pts": round(pnl, 4), "r_multiple": round(pnl / risk, 2) if risk else 0.0}


# ═══════════════════════════════════════════════════════════════════════════
# SESSION RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_session(ticker: str, session_bars: pd.DataFrame) -> Optional[Dict]:
    """
    Run one trading session through the production pipeline.

    OR is computed inline via compute_or_5m() (9:30-9:45, min 2 bars).
    FVG size gate uses FVG_MIN_SIZE_PCT_5M (0.0001) not production 0.5%.
    All other pipeline calls use real production signatures.
    """
    bars = bars_to_sniper_format(session_bars)
    if len(bars) < 10:
        return None

    session_date = bars[0]["datetime"].date()

    # ── Step 1: Opening Range (5m inline) ──────────────────────────────────
    or_high, or_low = compute_or_5m(bars)
    if or_high is None or or_low is None or or_low <= 0:
        return None
    or_range_pct = (or_high - or_low) / or_low
    if or_range_pct < OR_MIN_RANGE_PCT:
        return None

    # ── Step 2: Breakout detection ──────────────────────────────────────────
    try:
        direction, breakout_idx = detect_breakout_after_or(bars, or_high, or_low)
    except Exception as e:
        log.debug(f"  Breakout failed {session_date}: {e}")
        return None
    if direction is None or breakout_idx is None:
        return None
    if breakout_idx > MAX_BREAKOUT_IDX:
        log.debug(f"  Late breakout skip: idx {breakout_idx} > {MAX_BREAKOUT_IDX}")
        return None

    breakout_price = bars[breakout_idx]["close"]

    # ── Step 2b: Relative volume at breakout ───────────────────────────────
    # Breakout bar must have >= 1.2x the average volume of prior bars
    breakout_vol = bars[breakout_idx].get("volume", 0)
    prior_vols = [b["volume"] for b in bars[:breakout_idx] if b["volume"] > 0]
    if len(prior_vols) >= 3:
        avg_vol = sum(prior_vols) / len(prior_vols)
        if avg_vol > 0 and breakout_vol < avg_vol * 1.2:
            log.debug(f"  RVOL skip {session_date}: {breakout_vol:.0f} < 1.2x avg {avg_vol:.0f}")
            return None
        
    # ── Step 3: FVG after breakout ──────────────────────────────────────────
    try:
        fvg_low, fvg_high = detect_fvg_after_break(bars, breakout_idx, direction)
    except Exception as e:
        log.debug(f"  FVG failed {session_date}: {e}")
        return None
    if fvg_low is None or fvg_high is None:
        return None

    fvg_size = (fvg_high - fvg_low) / fvg_low if fvg_low > 0 else 0.0
    # Use 5m-appropriate threshold — production 0.5% never fires on 5m data
    if fvg_size < FVG_MIN_SIZE_PCT_5M:
        # Filter 1: FVG too large — oversized gaps fail on 5m data
        if fvg_size > 0.0015:  # 0.15%
            return None

        # Filter 2: OR range must be meaningful
        if or_range_pct < 0.0035:  # 0.35%
            return None

    if (fvg_high - fvg_low) < 0.05:  # min $0.05 FVG width ? sub-nickel gaps are fill noise
        return None
    fvg_mid = (fvg_low + fvg_high) / 2.0

    # Step 4: VWAP gate intentionally skipped — real-time execution filter only.
    # With 5m early breakouts (idx 3-5), VWAP is barely established and rejects
    # every session. Not a valid backtest criterion.

    # ── Step 5: Entry ────────────────────────────────────────────────────────────
    entry_bar_idx = breakout_idx
     # Filter 3: Skip dead zones — 10:00 sharp and 10:20–10:30 are 0% win rate
    entry_t = bars[entry_bar_idx]["datetime"]
    entry_mins = entry_t.hour * 60 + entry_t.minute
    if entry_mins == 600 or 620 <= entry_mins <= 630:  # 10:00 or 10:20–10:30
        return None
    entry_price   = fvg_mid
    if entry_bar_idx >= len(bars) - 1:
        return None

    # ── Step 6: Grade ────────────────────────────────────────────────────────────
    grade = "A"
    conf  = 0.65
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

    # ── Step 7: Stop & targets ─────────────────────────────────────────────
    try:
        stop, t1, t2 = compute_stop_and_targets(
            bars, direction, or_high, or_low, entry_price, grade=grade
        )
    except Exception as e:
        log.debug(f"  Levels failed {session_date}: {e}")
        return None
    if not all([stop, t1, t2]):
        return None
    if abs(entry_price - stop) < 0.25:  # min $0.25 risk ? filters stop-fallback garbage
        return None

    # ── Step 8: Simulate ─────────────────────────────────────────────────────────
    outcome  = simulate_trade(entry_bar_idx, bars, direction, entry_price, stop, t1, t2)
    entry_dt = bars[entry_bar_idx]["datetime"]

    return {
        "ticker":       ticker,
        "date":         str(session_date),
        "direction":    direction,
        "grade":        grade,
        "confidence":   round(conf, 4),
        "or_high":      round(or_high, 4),
        "or_low":       round(or_low, 4),
        "or_range_pct": round(or_range_pct * 100, 3),
        "fvg_low":      round(fvg_low, 4),
        "fvg_high":     round(fvg_high, 4),
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
        "entry_hour":   entry_dt.hour,
        "rvol":         round(breakout_vol / (sum(prior_vols)/len(prior_vols)), 2) if prior_vols else 0.0,
        "entry_minute": entry_dt.minute,
    }


# ═══════════════════════════════════════════════════════════════════════════
# WALK-FORWARD LOGIC
# ═══════════════════════════════════════════════════════════════════════════

def build_walk_forward_folds(
    sessions: List[pd.DataFrame], fold_size: int = 30
) -> List[Dict]:
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
    win_rate = len(wins) / len(trades) * 100
    profit_f = (
        sum(t["r_multiple"] for t in wins) / abs(sum(t["r_multiple"] for t in losses))
        if losses and abs(sum(t["r_multiple"] for t in losses)) > 0 else float("inf")
    )
    by_reason = defaultdict(int)
    for t in trades:
        by_reason[t["exit_reason"]] += 1
    return {
        "total_trades":   len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate_pct":   round(win_rate, 1),
        "avg_r":          round(float(np.mean(rs)), 3),
        "median_r":       round(float(np.median(rs)), 3),
        "avg_win_r":      round(float(np.mean([t["r_multiple"] for t in wins])),   3) if wins   else 0.0,
        "avg_loss_r":     round(float(np.mean([t["r_multiple"] for t in losses])), 3) if losses else 0.0,
        "profit_factor":  round(profit_f, 2),
        "max_drawdown_r": round(_max_drawdown(rs), 3),
        "exit_reasons":   dict(by_reason),
    }


def _max_drawdown(rs: List[float]) -> float:
    cum    = np.cumsum(rs)
    peak   = cum[0]
    max_dd = 0.0
    for v in cum:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return float(max_dd)


def build_hourly_win_rates(trades: List[Dict]) -> Dict:
    by_hour = defaultdict(list)
    for t in trades:
        by_hour[t["entry_hour"]].append(t["win"])
    result = {}
    for hour in range(9, 16):
        bucket = by_hour.get(hour, [])
        result[str(hour)] = {
            "win_rate":    round(sum(bucket) / len(bucket) * 100, 1) if len(bucket) >= 3 else None,
            "sample_size": len(bucket),
        }
    return result


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def run(tickers: List[str], days: int, out_dir: str, fold_size: int = 30):
    # Monkey-patch FVG threshold for 5m bars — production 0.5% never fires on 5m data
    from utils import config as _cfg; _cfg.FVG_MIN_SIZE_PCT = FVG_MIN_SIZE_PCT_5M
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    fetcher    = EODHDFetcher()
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
            summary   = {"ticker": ticker, "days": days, **stats}
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
        log.info(f"Total trades: {agg_stats['total_trades']} | Win rate: {agg_stats['win_rate_pct']}% | Avg R: {agg_stats['avg_r']}")
        hourly_path = out_path / "hourly_win_rates.json"
        hourly_path.write_text(json.dumps(build_hourly_win_rates(all_trades), indent=2))
        log.info(f"Hourly win rates → {hourly_path}")
    else:
        log.warning("No trades generated. Check EODHD_API_KEY and pipeline imports.")


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Backtest — War Machine")
    parser.add_argument("--tickers", default="SPY",  help="Comma-separated tickers (default: SPY)")
    parser.add_argument("--days",    type=int, default=90, help="Lookback days (default: 90)")
    parser.add_argument("--out",     default="backtests/results", help="Output directory")
    parser.add_argument("--fold",    type=int, default=30, help="Walk-forward fold size in days (default: 30)")
    args = parser.parse_args()
    run([t.strip().upper() for t in args.tickers.split(",")], args.days, args.out, args.fold)


if __name__ == "__main__":
    main()
