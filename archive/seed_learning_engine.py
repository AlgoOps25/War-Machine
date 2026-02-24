#!/usr/bin/env python3
"""
Backtest-to-AI-Learning Pipeline

Seeds the AI learning engine with real historical backtest data instead of
starting from zero or using synthetic test trades.

Workflow:
  1. Run backtest on your watchlist (last 30-60 days)
  2. Extract completed trades with full context
  3. Convert to AI learning format with proper metadata
  4. Import into learning engine, replacing any synthetic data
  5. Recalculate confidence multipliers based on real win rates
  6. Generate initial baseline report

Usage:
  python seed_learning_engine.py --tickers AAPL,SPY,NVDA,TSLA --days 30
  python seed_learning_engine.py --use-watchlist --days 60
  python seed_learning_engine.py --use-fallback --days 30 --reset
"""
import argparse
import sys
from datetime import datetime, timedelta
from typing import List
import config
from archive.backtesting_engine import Backtest
from ai_learning import learning_engine
import json


def parse_args():
    parser = argparse.ArgumentParser(
        description="Seed AI learning engine with backtest data"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated ticker list (e.g., AAPL,SPY,NVDA)"
    )
    group.add_argument(
        "--use-watchlist",
        action="store_true",
        help="Use live dynamic screener watchlist from dynamic_screener.py"
    )
    group.add_argument(
        "--use-fallback",
        action="store_true",
        help="Use the built-in fallback watchlist (no API call required)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of historical data to backtest (default: 30)"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=5000,
        help="Starting capital for backtest (default: 5000)"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing learning data before seeding"
    )
    return parser.parse_args()


def get_watchlist_tickers() -> List[str]:
    """
    Load tickers from dynamic_screener.py.
    Falls back to FALLBACK_WATCHLIST if the live screener API call fails.
    """
    try:
        from dynamic_screener import get_dynamic_watchlist, FALLBACK_WATCHLIST
        print("[SEED] Calling dynamic screener API...")
        tickers = get_dynamic_watchlist(include_core=True, max_tickers=50)
        if tickers:
            return tickers
        print("[SEED] ⚠️  Screener returned 0 results — using FALLBACK_WATCHLIST")
        return list(FALLBACK_WATCHLIST)
    except ImportError as e:
        print(f"[ERROR] Could not import dynamic_screener: {e}")
        sys.exit(1)


def get_fallback_tickers() -> List[str]:
    """Return the static fallback watchlist without making any API calls."""
    try:
        from dynamic_screener import FALLBACK_WATCHLIST
        return list(FALLBACK_WATCHLIST)
    except ImportError:
        # Hardcoded last-resort fallback
        return [
            "SPY", "QQQ", "IWM", "DIA",
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD",  "NFLX", "ADBE",  "CRM",  "ORCL", "SNOW", "PLTR",
            "JPM",  "BAC",  "GS",    "MS",   "WFC",
            "UNH",  "JNJ",  "PFE",   "ABBV", "MRK",
            "WMT",  "HD",   "COST",  "NKE",  "MCD",
            "XOM",  "CVX",  "OXY",
            "QCOM", "MU",   "INTC",  "AMAT", "LRCX",
        ]


def assign_grade_to_trade(trade: dict, signals_map: dict) -> str:
    """
    Assign a grade (A+, A, A-) to a backtest trade based on signal quality.

    Grading criteria:
      A+: T1 hit + profitable + strong OR range (>0.5%)
      A:  Profitable or T1 hit
      A-: Loss without T1 hit

    In a full implementation you'd call
    cfw6_confirmation.grade_signal_with_confirmations() on historical bars.
    For seeding purposes we use outcome-based heuristics.
    """
    pnl    = trade["pnl"]
    t1_hit = trade.get("t1_hit", False)

    # Try to fetch signal metadata if available
    signal_key   = f"{trade['ticker']}_{trade.get('date', 'unknown')}"
    signal       = signals_map.get(signal_key, {})
    or_range_pct = 0.0
    if signal:
        or_high = signal.get("or_high", 0)
        or_low  = signal.get("or_low",  0)
        if or_high > 0 and or_low > 0:
            or_range_pct = (or_high - or_low) / or_low

    if pnl > 0 and t1_hit and or_range_pct > 0.005:
        return "A+"
    elif pnl > 0 or t1_hit:
        return "A"
    else:
        return "A-"


def convert_backtest_trade_to_learning_format(trade: dict, signal: dict) -> dict:
    """
    Convert a backtest trade dict to AI learning engine format.

    Backtest format:
      {"ticker", "date", "direction", "entry", "exit", "pnl", "exit_reason", "t1_hit"}

    Learning format:
      {"timestamp", "ticker", "direction", "grade", "entry", "exit", "pnl", "win",
       "hold_duration", "fvg_size", "or_break_size", "confirmations", "timeframe"}
    """
    entry     = trade["entry"]
    direction = trade["direction"]

    # FVG size from signal metadata
    fvg_size = 0.0
    if signal:
        fvg_high = signal.get("fvg_high", 0)
        fvg_low  = signal.get("fvg_low",  0)
        if fvg_high > 0 and fvg_low > 0 and entry > 0:
            fvg_size = abs(fvg_high - fvg_low) / entry

    # OR breakout size from signal metadata
    or_break_size = 0.0
    if signal:
        or_high = signal.get("or_high", 0)
        or_low  = signal.get("or_low",  0)
        if direction == "bull" and or_high > 0:
            or_break_size = (entry - or_high) / or_high
        elif direction == "bear" and or_low > 0:
            or_break_size = (or_low - entry) / or_low

    return {
        "timestamp":     trade.get("date", datetime.now().isoformat()),
        "ticker":        trade["ticker"],
        "direction":     direction,
        "grade":         trade["grade"],
        "entry":         entry,
        "exit":          trade["exit"],
        "pnl":           trade["pnl"],
        "win":           trade["pnl"] > 0,
        "hold_duration": 0,          # Backtest doesn't track minutes held
        "fvg_size":      round(fvg_size,      4),
        "or_break_size": round(or_break_size, 4),
        "confirmations": {},          # Historical confirmation data not available
        "timeframe":     "1m"
    }


def seed_learning_engine(backtest: Backtest, signals_map: dict, reset: bool = False):
    """
    Import backtest trades into the AI learning engine.

    Args:
        backtest:    Completed Backtest instance with .trades populated.
        signals_map: Dict mapping "TICKER_YYYY-MM-DD" -> signal metadata dict.
        reset:       If True, clears ALL existing learning data before import.
    """
    if reset:
        print("\n[SEED] Resetting AI learning engine...")
        learning_engine.data = {
            "trades": [],
            "pattern_performance":  {},
            "ticker_performance":   {},
            "timeframe_performance": {},
            "confirmation_weights": {
                "vwap": 1.0, "prev_day": 1.0,
                "institutional": 1.0, "options_flow": 1.0
            },
            "fvg_size_optimal":             0.002,
            "or_break_threshold_optimal":   0.001,
            "last_update": None
        }
        learning_engine.save_data()
        print("[SEED] ✅ Learning data cleared")

    if not backtest.trades:
        print("[SEED] ⚠️  No backtest trades to import. "
              "Try a longer --days window or more liquid tickers.")
        return

    print(f"\n[SEED] Importing {len(backtest.trades)} backtest trades...")

    # Assign grades to all trades first
    for trade in backtest.trades:
        trade["grade"] = assign_grade_to_trade(trade, signals_map)

    # Convert and import each trade
    imported = 0
    for trade in backtest.trades:
        signal_key    = f"{trade['ticker']}_{trade.get('date', 'unknown')}"
        signal        = signals_map.get(signal_key, {})
        learning_trade = convert_backtest_trade_to_learning_format(trade, signal)
        learning_engine.data["trades"].append(learning_trade)
        learning_engine.update_performance_metrics(learning_trade)
        imported += 1

    learning_engine.save_data()
    print(f"[SEED] ✅ Imported {imported} trades")

    # Re-optimize parameters from real data
    print("\n[SEED] Recalibrating confidence multipliers...")
    learning_engine.optimize_confirmation_weights()
    learning_engine.optimize_fvg_threshold()

    # Baseline performance report
    print("\n[SEED] AI Learning Engine Baseline Report:")
    print(learning_engine.generate_performance_report())

    # Per-ticker multiplier summary
    print("\n[SEED] Ticker Confidence Multipliers:")
    tickers = sorted(set(t["ticker"] for t in backtest.trades))
    for ticker in tickers:
        multiplier    = learning_engine.get_ticker_confidence_multiplier(ticker)
        ticker_trades = [t for t in learning_engine.data["trades"] if t["ticker"] == ticker]
        wins          = sum(1 for t in ticker_trades if t["win"])
        wr            = wins / len(ticker_trades) * 100 if ticker_trades else 0
        flag          = "✅" if multiplier >= 1.0 else "⚠️"
        print(f"  {ticker:<6} {multiplier:.2f}x  ({len(ticker_trades)} trades, {wr:.1f}% WR) {flag}")


def main():
    args = parse_args()

    # ── Resolve ticker list ───────────────────────────────────────────────────
    if args.use_watchlist:
        tickers = get_watchlist_tickers()
        print(f"[SEED] Using dynamic screener watchlist: {len(tickers)} tickers")
    elif args.use_fallback:
        tickers = get_fallback_tickers()
        print(f"[SEED] Using fallback watchlist: {len(tickers)} tickers")
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
        print(f"[SEED] Using manual ticker list: {tickers}")
    else:
        # Default: use fallback so script always works without extra args
        print("[SEED] No ticker source specified — defaulting to --use-fallback")
        tickers = get_fallback_tickers()

    # ── Date range ────────────────────────────────────────────────────────────
    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print(f"\n{'='*70}")
    print(f"SEEDING AI LEARNING ENGINE FROM BACKTEST")
    print(f"{'='*70}")
    print(f"Period:  {start_date} → {end_date} ({args.days} days)")
    print(f"Tickers: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")
    print(f"Capital: ${args.capital:,.2f}")
    print(f"Reset:   {args.reset}")
    print(f"{'='*70}\n")

    # ── Run backtest ──────────────────────────────────────────────────────────
    backtest    = Backtest(start_date, end_date, initial_capital=args.capital)
    signals_map = {}

    print("[SEED] Running backtest...\n")
    for idx, ticker in enumerate(tickers, 1):
        print(f"[{idx}/{len(tickers)}] Processing {ticker}...")
        try:
            bars = backtest.fetch_historical_bars(ticker)
            print(f"  → {len(bars)} bars fetched")

            signals = backtest.detect_cfw6_signals(ticker, bars)
            print(f"  → {len(signals)} signals detected")

            for signal in signals:
                key = f"{ticker}_{signal.get('date', 'unknown')}"
                signals_map[key] = signal
                backtest.execute_backtest_trade(signal)

        except Exception as e:
            print(f"  → Error fetching {ticker}: {e}")
            continue

    backtest.calculate_metrics()

    # ── Seed engine ───────────────────────────────────────────────────────────
    seed_learning_engine(backtest, signals_map, reset=args.reset)

    print("\n[SEED] ✅ Seeding complete. AI learning engine ready for live trading.\n")


if __name__ == "__main__":
    main()
