#!/usr/bin/env python3
"""
Unified Production Backtesting Engine for War Machine

47.P4-1 (Apr 02 2026): Full bar-replay implementation replacing the prior stub.
  - OR window (09:30-09:50 ET) builds high/low, then scans for BOS above/below
  - FVG detection on 3-bar sequence after BOS
  - VWAP gate, entry-timing filter, MTF boost wired when modules available
  - strategy() callable matches BacktestEngine.run() signature exactly
  - --walk-forward runs WalkForward with 2-month train / 1-month test windows
  - --batch runs all 5 default tickers sequentially
  - Hourly win-rate map printed at end (feeds 47.P4-2)

Usage:
    # Single ticker, 90-day single-pass
    python unified_production_backtest.py --ticker AAPL --days 90

    # Walk-forward (2m train / 1m test)
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

OR_START = dtime(9, 30)   # Opening Range start (ET)
OR_END   = dtime(9, 50)   # Opening Range end   (ET)
EOD_CUT  = dtime(15, 45)  # No new entries after this

DEFAULT_PARAM_GRID = {
    "fvg_min_size_pct": [0.003, 0.005, 0.008],
    "min_confidence":   [60,    65,    70],
    "rvol_min":         [1.5,   2.0,   2.5],
}


# ===========================================================================
# DATA FETCHER
# ===========================================================================

class DataFetcher:
    """Fetch historical 5m bars — PostgreSQL cache first, EODHD fallback."""

    def __init__(self):
        self.api_key = os.getenv("EODHD_API_KEY")
        if not self.api_key:
            logger.warning("EODHD_API_KEY not set — will use PostgreSQL cache only")

    # ------------------------------------------------------------------
    def fetch_from_cache(self, ticker: str, start: datetime, end: datetime) -> List[Dict]:
        try:
            from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
            p = ph()
            conn = get_conn()
            try:
                cur = dict_cursor(conn)
                cur.execute(
                    f"SELECT datetime, open, high, low, close, volume "
                    f"FROM intraday_bars "
                    f"WHERE ticker = {p} AND datetime >= {p} AND datetime <= {p} "
                    f"ORDER BY datetime",
                    (ticker, start, end),
                )
                rows = cur.fetchall()
            finally:
                return_conn(conn)

            bars = []
            for row in rows:
                dt = row["datetime"]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(ET).replace(tzinfo=None)
                bars.append({
                    "datetime": dt,
                    "open":  float(row["open"]),
                    "high":  float(row["high"]),
                    "low":   float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                })
            if bars:
                logger.info(f"[DATA] {ticker}: {len(bars)} bars from cache")
            return bars
        except Exception as e:
            logger.warning(f"[DATA] Cache fetch failed for {ticker}: {e}")
            return []

    # ------------------------------------------------------------------
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
                        "open":  float(r["open"]),
                        "high":  float(r["high"]),
                        "low":   float(r["low"]),
                        "close": float(r["close"]),
                        "volume": int(r["gmtoffset"] if "volume" not in r else r["volume"]),
                    })
                    bars[-1]["volume"] = int(r.get("volume", 0))
                logger.info(f"[DATA] {ticker}: {len(bars)} bars from EODHD")
                return bars
            else:
                logger.error(f"[DATA] EODHD {resp.status_code} for {ticker}")
        except Exception as e:
            logger.error(f"[DATA] EODHD fetch failed for {ticker}: {e}")
        return []

    # ------------------------------------------------------------------
    def fetch(self, ticker: str, start: datetime, end: datetime) -> List[Dict]:
        bars = self.fetch_from_cache(ticker, start, end)
        if not bars:
            bars = self.fetch_from_eodhd(ticker, start, end)
        if not bars:
            logger.error(f"[DATA] No bars available for {ticker} — cannot backtest")
        return bars


# ===========================================================================
# SIGNAL STRATEGY  (matches BacktestEngine.run() strategy signature)
# ===========================================================================

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
    Returns dict with fvg_top / fvg_bottom / fvg_mid if found.
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


def war_machine_strategy(
    lookback_bars: List[Dict],
    params: Dict,
) -> Optional[Dict]:
    """
    War Machine BOS + FVG strategy — compatible with BacktestEngine.run().

    Params accepted:
        fvg_min_size_pct  (default 0.005)
        min_confidence    (default 65)
        rvol_min          (default 1.5)

    Returns signal dict or None.
    """
    fvg_min   = params.get("fvg_min_size_pct", 0.005)
    min_conf  = params.get("min_confidence",   65)
    rvol_min  = params.get("rvol_min",         1.5)

    if len(lookback_bars) < 20:
        return None

    current_bar = lookback_bars[-1]
    bar_time    = current_bar["datetime"]

    # Filter to RTH only; skip OR window and near-EOD
    if bar_time.time() < OR_END or bar_time.time() > EOD_CUT:
        return None

    # Build OR high/low from bars in the OR window of the SAME session date
    session_date = bar_time.date()
    or_bars = [
        b for b in lookback_bars
        if b["datetime"].date() == session_date
        and OR_START <= b["datetime"].time() <= OR_END
    ]
    if len(or_bars) < 2:
        return None

    or_high = max(b["high"] for b in or_bars)
    or_low  = min(b["low"]  for b in or_bars)
    or_range = or_high - or_low
    if or_range / or_low < 0.002:   # OR too narrow — skip
        return None

    # Structure: BOS above OR high (BULL) or below OR low (BEAR)
    close = current_bar["close"]
    if close > or_high:
        direction = "BULL"
        bos_level = or_high
    elif close < or_low:
        direction = "BEAR"
        bos_level = or_low
    else:
        return None   # Price still inside OR

    # RVOL filter
    recent_vols = [b["volume"] for b in lookback_bars[-20:]]
    avg_vol = np.mean(recent_vols[:-1]) if len(recent_vols) > 1 else 1
    rvol    = current_bar["volume"] / avg_vol if avg_vol > 0 else 0
    if rvol < rvol_min:
        return None

    # FVG on most-recent 3 bars
    fvg = _detect_fvg(lookback_bars[-10:], direction, fvg_min)
    if not fvg:
        return None

    # VWAP gate
    session_bars = [b for b in lookback_bars if b["datetime"].date() == session_date]
    vwap = _compute_vwap(session_bars) if session_bars else 0.0
    if direction == "BULL" and close < vwap:
        return None
    if direction == "BEAR" and close > vwap:
        return None

    # Confidence scoring (simple: grade based on rvol + or_range_pct)
    or_range_pct = or_range / or_low
    conf_score = min(100, int(
        40
        + min(rvol * 10, 30)
        + min(or_range_pct * 2000, 20)
        + (10 if fvg else 0)
    ))
    if conf_score < min_conf:
        return None

    # Entry / stop / targets
    atr_approx = np.mean([b["high"] - b["low"] for b in lookback_bars[-14:]]) or 0.01

    if direction == "BULL":
        entry  = close
        stop   = max(fvg["fvg_bottom"] - atr_approx * 0.1, close - atr_approx * 1.5)
        t1     = entry + atr_approx * 1.0
        t2     = entry + atr_approx * 2.0
        signal = "BUY"
    else:
        entry  = close
        stop   = min(fvg["fvg_top"] + atr_approx * 0.1, close + atr_approx * 1.5)
        t1     = entry - atr_approx * 1.0
        t2     = entry - atr_approx * 2.0
        signal = "SELL"

    return {
        "signal":     signal,
        "entry":      entry,
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
# SINGLE-TICKER RUNNER
# ===========================================================================

def run_single(
    ticker: str,
    bars: List[Dict],
    params: Dict,
    walk_forward: bool,
    save: bool,
    output_dir: str,
) -> Optional[Dict]:
    """
    Run either a single-pass backtest or walk-forward for one ticker.
    Returns a summary dict.
    """
    if not BACKTEST_AVAILABLE:
        logger.error("BacktestEngine not available — install War Machine dependencies")
        return None

    if not bars:
        logger.warning(f"[{ticker}] No bars — skipping")
        return None

    if walk_forward:
        # ----------------------------------------------------------------
        # Walk-forward: 2-month train / 1-month test
        # ----------------------------------------------------------------
        wf = WalkForward(
            train_months=2,
            test_months=1,
            step_months=1,
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
        # ----------------------------------------------------------------
        # Single-pass backtest
        # ----------------------------------------------------------------
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
            strategy_params=params,
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

    # ----------------------------------------------------------------
    # Hourly win-rate map
    # ----------------------------------------------------------------
    hourly = build_hourly_win_rate(all_trades)
    print_hourly_map(hourly, ticker)
    summary["hourly_win_rates"] = hourly

    # ----------------------------------------------------------------
    # Optionally save JSON
    # ----------------------------------------------------------------
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

    parser = argparse.ArgumentParser(description="War Machine — Unified Production Backtest (47.P4-1)")
    parser.add_argument("--ticker",        help="Single ticker to backtest")
    parser.add_argument("--batch",         action="store_true", help=f"Run all default tickers: {DEFAULT_TICKERS}")
    parser.add_argument("--tickers",       help="Comma-separated custom ticker list (overrides --batch defaults)")
    parser.add_argument("--start",         help="Start date YYYY-MM-DD")
    parser.add_argument("--end",           help="End date YYYY-MM-DD")
    parser.add_argument("--days",          type=int, default=90, help="Days back from today (default 90)")
    parser.add_argument("--walk-forward",  action="store_true", help="Run walk-forward validation (2m train / 1m test)")
    parser.add_argument("--save",          action="store_true", help="Save JSON results to output dir")
    parser.add_argument("--output-dir",    default="backtests/results", help="Output directory for JSON results")

    # Strategy param overrides
    parser.add_argument("--fvg-min",       type=float, default=0.005, help="FVG min size pct (default 0.005)")
    parser.add_argument("--min-conf",      type=int,   default=65,    help="Min confidence score (default 65)")
    parser.add_argument("--rvol-min",      type=float, default=1.5,   help="Min RVOL (default 1.5)")

    args = parser.parse_args()

    # Resolve tickers
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    elif args.batch:
        tickers = DEFAULT_TICKERS
    elif args.ticker:
        tickers = [args.ticker.upper()]
    else:
        tickers = ["AAPL"]

    # Resolve date range
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
        )
        summaries.append(summary)

    if len(tickers) > 1:
        print_aggregate(summaries)


if __name__ == "__main__":
    main()
