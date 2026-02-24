#!/usr/bin/env python3
"""
AI Learning State Analyzer

Diagnoses performance issues in the AI learning engine by breaking down:
  - Per-ticker win rates and confidence multipliers
  - Per-grade performance (A+/A/A-)
  - Exit reason breakdown (stops vs targets)
  - Underperforming patterns and recommended fixes

Usage:
  python analyze_learning_state.py
  python analyze_learning_state.py --ticker AAPL
  python analyze_learning_state.py --show-trades
"""
import argparse
from collections import defaultdict
from ai_learning import learning_engine


def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyze AI learning engine state"
    )
    parser.add_argument(
        "--ticker",
        type=str,
        help="Deep-dive analysis for specific ticker"
    )
    parser.add_argument(
        "--show-trades",
        action="store_true",
        help="Show individual trade details"
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=5,
        help="Minimum trades to include in ticker analysis (default: 5)"
    )
    return parser.parse_args()


def analyze_ticker_performance(trades: list, min_trades: int = 5):
    """
    Break down performance by ticker, showing win rate, P&L, and multipliers.
    """
    ticker_stats = defaultdict(lambda: {
        "trades": 0, "wins": 0, "pnl": 0.0,
        "grades": defaultdict(int),
        "directions": defaultdict(int),
        "avg_win": [], "avg_loss": []
    })
    
    for trade in trades:
        ticker = trade["ticker"]
        pnl = trade["pnl"]
        win = trade["win"]
        grade = trade["grade"]
        direction = trade["direction"]
        
        ticker_stats[ticker]["trades"] += 1
        ticker_stats[ticker]["pnl"] += pnl
        if win:
            ticker_stats[ticker]["wins"] += 1
            ticker_stats[ticker]["avg_win"].append(pnl)
        else:
            ticker_stats[ticker]["avg_loss"].append(pnl)
        
        ticker_stats[ticker]["grades"][grade] += 1
        ticker_stats[ticker]["directions"][direction] += 1
    
    # Filter tickers with enough trades
    filtered = {
        t: s for t, s in ticker_stats.items()
        if s["trades"] >= min_trades
    }
    
    # Sort by P&L (worst first)
    sorted_tickers = sorted(
        filtered.items(),
        key=lambda x: x[1]["pnl"]
    )
    
    print("\n" + "="*80)
    print("TICKER PERFORMANCE BREAKDOWN")
    print("="*80)
    print(f"{'Ticker':<8} {'Trades':<8} {'WR':<8} {'P&L':<12} {'Multiplier':<12} {'Grades':<20}")
    print("-"*80)
    
    for ticker, stats in sorted_tickers:
        trades = stats["trades"]
        wins = stats["wins"]
        wr = wins / trades * 100 if trades > 0 else 0
        pnl = stats["pnl"]
        multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)
        
        # Grade summary
        grade_str = ", ".join(
            f"{g}:{c}" for g, c in sorted(stats["grades"].items())
        )
        
        # Color coding
        if pnl > 0:
            pnl_str = f"${pnl:+,.0f} ✅"
        else:
            pnl_str = f"${pnl:+,.0f} ❌"
        
        print(f"{ticker:<8} {trades:<8} {wr:>6.1f}% {pnl_str:<12} {multiplier:>6.2f}x      {grade_str}")
    
    print("="*80)
    
    # Identify problem tickers
    print("\n🚨 UNDERPERFORMING TICKERS (WR < 50% and losses):")
    problem_tickers = [
        (ticker, stats) for ticker, stats in sorted_tickers
        if stats["wins"] / stats["trades"] < 0.5 and stats["pnl"] < 0
    ]
    
    if problem_tickers:
        for ticker, stats in problem_tickers:
            trades = stats["trades"]
            wins = stats["wins"]
            wr = wins / trades * 100
            pnl = stats["pnl"]
            
            print(f"\n  {ticker}: {trades} trades, {wr:.1f}% WR, ${pnl:+,.0f}")
            
            # Direction bias
            directions = stats["directions"]
            if len(directions) > 0:
                print(f"    Directions: ", end="")
                for d, count in directions.items():
                    print(f"{d}={count} ", end="")
                print()
            
            # Grade distribution
            grades = stats["grades"]
            if len(grades) > 0:
                print(f"    Grades: ", end="")
                for g, count in grades.items():
                    print(f"{g}={count} ", end="")
                print()
            
            # Avg win/loss
            avg_win = sum(stats["avg_win"]) / len(stats["avg_win"]) if stats["avg_win"] else 0
            avg_loss = sum(stats["avg_loss"]) / len(stats["avg_loss"]) if stats["avg_loss"] else 0
            print(f"    Avg Win: ${avg_win:+.0f} | Avg Loss: ${avg_loss:+.0f}")
            
            # Diagnosis
            print(f"    🔧 Recommendation: ", end="")
            if wr < 30:
                print(f"Consider removing {ticker} from watchlist or blocking A- signals")
            elif avg_loss < -200:
                print(f"Stops too wide — review stop placement logic for {ticker}")
            elif grades.get("A-", 0) > grades.get("A+", 0):
                print(f"Low-quality signals — raise MIN_CONFIDENCE_BY_GRADE['A-']")
            else:
                print(f"Monitor for 10 more trades before action")
    else:
        print("  ✅ No major issues detected")
    
    print()


def analyze_grade_performance(trades: list):
    """
    Break down performance by signal grade (A+/A/A-).
    """
    grade_stats = defaultdict(lambda: {
        "trades": 0, "wins": 0, "pnl": 0.0,
        "avg_win": [], "avg_loss": []
    })
    
    for trade in trades:
        grade = trade["grade"]
        pnl = trade["pnl"]
        win = trade["win"]
        
        grade_stats[grade]["trades"] += 1
        grade_stats[grade]["pnl"] += pnl
        if win:
            grade_stats[grade]["wins"] += 1
            grade_stats[grade]["avg_win"].append(pnl)
        else:
            grade_stats[grade]["avg_loss"].append(pnl)
    
    print("\n" + "="*80)
    print("GRADE PERFORMANCE BREAKDOWN")
    print("="*80)
    print(f"{'Grade':<8} {'Trades':<8} {'Win Rate':<12} {'Total P&L':<12} {'Avg Win':<12} {'Avg Loss'}")
    print("-"*80)
    
    for grade in ["A+", "A", "A-"]:
        if grade not in grade_stats:
            continue
        
        stats = grade_stats[grade]
        trades = stats["trades"]
        wins = stats["wins"]
        wr = wins / trades * 100 if trades > 0 else 0
        pnl = stats["pnl"]
        avg_win = sum(stats["avg_win"]) / len(stats["avg_win"]) if stats["avg_win"] else 0
        avg_loss = sum(stats["avg_loss"]) / len(stats["avg_loss"]) if stats["avg_loss"] else 0
        
        print(f"{grade:<8} {trades:<8} {wr:>6.1f}%     ${pnl:>+8.0f}    ${avg_win:>+8.0f}    ${avg_loss:>+8.0f}")
    
    print("="*80)
    
    # Grade recommendations
    print("\n🔧 GRADE TUNING RECOMMENDATIONS:")
    for grade in ["A+", "A", "A-"]:
        if grade not in grade_stats:
            continue
        
        stats = grade_stats[grade]
        trades = stats["trades"]
        wins = stats["wins"]
        wr = wins / trades * 100 if trades > 0 else 0
        pnl = stats["pnl"]
        
        if grade == "A+" and wr < 60:
            print(f"  {grade}: WR too low ({wr:.1f}%) — confirmation layers may be too loose")
        elif grade == "A" and wr < 50:
            print(f"  {grade}: Below 50% WR — consider raising MIN_CONFIDENCE_OR/INTRADAY")
        elif grade == "A-" and (wr < 40 or pnl < 0):
            print(f"  {grade}: Unprofitable ({wr:.1f}% WR, ${pnl:+.0f}) — block from intraday path or raise floor to 0.95")
        else:
            print(f"  {grade}: Performing as expected ({wr:.1f}% WR)")
    
    print()


def deep_dive_ticker(ticker: str, trades: list):
    """
    Show all trades for a specific ticker with full details.
    """
    ticker_trades = [t for t in trades if t["ticker"] == ticker]
    
    if not ticker_trades:
        print(f"\n❌ No trades found for {ticker}")
        return
    
    print(f"\n{'='*80}")
    print(f"DEEP DIVE: {ticker} ({len(ticker_trades)} trades)")
    print(f"{'='*80}")
    
    for i, trade in enumerate(ticker_trades, 1):
        timestamp = trade.get("timestamp", "unknown")[:10]
        direction = trade["direction"]
        grade = trade["grade"]
        entry = trade["entry"]
        exit_px = trade["exit"]
        pnl = trade["pnl"]
        win = "✅" if trade["win"] else "❌"
        
        print(f"\n  [{i}] {timestamp} | {direction.upper()} {grade} | {win}")
        print(f"      Entry: ${entry:.2f} → Exit: ${exit_px:.2f} = ${pnl:+.2f}")
        
        # Additional metadata if available
        if "fvg_size" in trade and trade["fvg_size"] > 0:
            print(f"      FVG Size: {trade['fvg_size']*100:.2f}%")
        if "or_break_size" in trade and trade["or_break_size"] > 0:
            print(f"      OR Break: {trade['or_break_size']*100:.2f}%")
    
    # Summary
    wins = sum(1 for t in ticker_trades if t["win"])
    wr = wins / len(ticker_trades) * 100
    total_pnl = sum(t["pnl"] for t in ticker_trades)
    multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)
    
    print(f"\n{'='*80}")
    print(f"SUMMARY: {len(ticker_trades)} trades | {wr:.1f}% WR | ${total_pnl:+,.0f} | {multiplier:.2f}x multiplier")
    print(f"{'='*80}\n")


def main():
    args = parse_args()
    
    trades = learning_engine.data.get("trades", [])
    
    if not trades:
        print("\n❌ No trades in AI learning engine. Run seed_learning_engine.py first.\n")
        return
    
    print(f"\n{'='*80}")
    print(f"AI LEARNING STATE ANALYSIS")
    print(f"{'='*80}")
    print(f"Total Trades: {len(trades)}")
    wins = sum(1 for t in trades if t["win"])
    print(f"Overall Win Rate: {wins / len(trades) * 100:.1f}%")
    print(f"Total P&L: ${sum(t['pnl'] for t in trades):+,.2f}")
    print(f"{'='*80}")
    
    # Ticker-specific analysis
    if args.ticker:
        deep_dive_ticker(args.ticker.upper(), trades)
    else:
        analyze_ticker_performance(trades, min_trades=args.min_trades)
    
    # Grade analysis
    analyze_grade_performance(trades)
    
    # Show individual trades if requested
    if args.show_trades and not args.ticker:
        print(f"\n{'='*80}")
        print("RECENT TRADES (Last 10)")
        print(f"{'='*80}")
        for trade in trades[-10:]:
            timestamp = trade.get("timestamp", "unknown")[:10]
            ticker = trade["ticker"]
            direction = trade["direction"]
            grade = trade["grade"]
            pnl = trade["pnl"]
            win = "✅" if trade["win"] else "❌"
            print(f"  {timestamp} | {ticker:<6} {direction.upper():<5} {grade:<3} | ${pnl:>+8.2f} {win}")
        print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
