#!/usr/bin/env python3
"""
Comprehensive Backtest Engine - Fixed Version

Tests multiple parameter combinations across historical data.
Uses intraday_bars table (not candle_cache).

Usage:
    python comprehensive_backtest_fixed.py
    
Output:
    - backtest_results.csv: All parameter combinations
    - top_configs.json: Top 10 configurations
    - backtest_summary.txt: Detailed analysis
"""
import sys
import logging
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import pandas as pd
import json
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import War Machine components
try:
    from data_manager import DataManager
    from db_connection import get_conn, ph, dict_cursor
except ImportError as e:
    logger.error(f"Import error: {e}")
    logger.error("Make sure you're running from War-Machine directory")
    sys.exit(1)

ET = ZoneInfo("America/New_York")

# Ticker list - same as build_cache.py
TICKERS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMD",
    "GOOGL", "AMZN", "NFLX", "DIS", "INTC", "BABA", "BA", "JPM",
    "V", "MA", "PYPL", "SQ", "COIN", "PLTR", "SOFI", "RBLX",
    "GME", "AMC", "SNAP", "UBER", "LYFT", "SHOP", "ZM", "ROKU",
    "DKNG", "PENN", "ABNB", "DASH", "HOOD", "RIVN", "LCID", "F",
    "GM", "NIO", "XPEV", "LI", "PLUG", "FCEL", "BLNK", "CHPT",
    "ENPH", "SEDG", "RUN", "SPWR", "CSIQ", "JKS", "NOVA", "SOL",
    "TAN", "ICLN", "PBW", "QCLN", "SMOG", "ACES", "FAN", "GRID"
]

class BacktestEngine:
    """
    Comprehensive backtesting engine for War Machine signals.
    """
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.data_manager = DataManager(db_path)
        
        # Date range for backtest (last 30 days)
        now_et = datetime.now(ET)
        self.end_date = now_et.date()
        self.start_date = (now_et - timedelta(days=30)).date()
        
        logger.info(f"Backtest period: {self.start_date} to {self.end_date}")
        logger.info(f"Testing {len(TICKERS)} tickers")
        
        # PERFORMANCE FIX: Load all bars into memory at startup
        logger.info("\n⏳ Loading all bars into memory...")
        self.bars_cache = {}
        for i, ticker in enumerate(TICKERS, 1):
            bars = self._load_bars_from_db(ticker)
            if bars:
                self.bars_cache[ticker] = bars
                logger.info(f"  [{i}/{len(TICKERS)}] {ticker}: {len(bars)} bars")
            else:
                logger.info(f"  [{i}/{len(TICKERS)}] {ticker}: No data")
        
        logger.info(f"\n✅ Cached {len(self.bars_cache)} tickers with {sum(len(b) for b in self.bars_cache.values()):,} total bars")
    
    def _load_bars_from_db(self, ticker: str) -> List[Dict]:
        """
        Load historical bars from intraday_bars table.
        Called ONCE per ticker at startup.
        """
        try:
            conn = get_conn(self.db_path)
            cur = dict_cursor(conn)
            
            query = f"""
            SELECT datetime, open, high, low, close, volume
            FROM intraday_bars
            WHERE ticker = {ph()}
              AND datetime >= {ph()}
              AND datetime <= {ph()}
            ORDER BY datetime
            """
            
            cur.execute(query, (ticker, self.start_date, self.end_date))
            rows = cur.fetchall()
            
            conn.close()
            
            if not rows:
                return []
            
            # Convert to dict list
            bars = []
            for row in rows:
                dt = row["datetime"]
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                
                bars.append({
                    "datetime": dt,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"])
                })
            
            return bars
            
        except Exception as e:
            logger.error(f"DB load error for {ticker}: {e}")
            return []
    
    def detect_signals(self, ticker: str, bars: List[Dict], 
                      fvg_threshold: float, confidence_grade: str) -> List[Dict]:
        """
        Detect BOS/FVG signals from historical bars.
        
        Simplified signal detection logic:
        - Fair Value Gap (FVG): Gap between bars
        - Breakout of Structure (BOS): New high/low
        """
        if len(bars) < 20:
            return []
        
        signals = []
        
        for i in range(10, len(bars) - 1):
            current = bars[i]
            prev = bars[i-1]
            
            # Look for FVG (gap up/down)
            gap_up = (current["low"] - prev["high"]) / prev["close"]
            gap_down = (prev["low"] - current["high"]) / prev["close"]
            
            # Long signal: Gap up
            if gap_up >= fvg_threshold:
                signals.append({
                    "ticker": ticker,
                    "datetime": current["datetime"],
                    "direction": "long",
                    "entry_price": current["close"],
                    "grade": confidence_grade,
                    "signal_type": "fvg_gap_up"
                })
            
            # Short signal: Gap down
            elif abs(gap_down) >= fvg_threshold:
                signals.append({
                    "ticker": ticker,
                    "datetime": current["datetime"],
                    "direction": "short",
                    "entry_price": current["close"],
                    "grade": confidence_grade,
                    "signal_type": "fvg_gap_down"
                })
        
        return signals
    
    def simulate_trade(self, signal: Dict, bars: List[Dict], 
                      stop_loss_pct: float) -> Dict:
        """
        Simulate a trade from signal to exit.
        
        Exit conditions:
        1. Stop loss hit
        2. Target hit (2R)
        3. End of day
        """
        entry_idx = next((i for i, b in enumerate(bars) 
                         if b["datetime"] == signal["datetime"]), None)
        
        if entry_idx is None or entry_idx >= len(bars) - 1:
            return None
        
        entry_price = signal["entry_price"]
        direction = signal["direction"]
        
        # Calculate stop loss and target
        if direction == "long":
            stop_loss = entry_price * (1 - stop_loss_pct)
            target = entry_price * (1 + stop_loss_pct * 2)  # 2R
        else:
            stop_loss = entry_price * (1 + stop_loss_pct)
            target = entry_price * (1 - stop_loss_pct * 2)  # 2R
        
        # Simulate forward from entry
        for i in range(entry_idx + 1, min(entry_idx + 30, len(bars))):
            bar = bars[i]
            
            if direction == "long":
                # Check stop loss
                if bar["low"] <= stop_loss:
                    return {
                        "exit_price": stop_loss,
                        "exit_reason": "stop_loss",
                        "pnl": stop_loss - entry_price,
                        "pnl_pct": (stop_loss - entry_price) / entry_price,
                        "bars_held": i - entry_idx
                    }
                # Check target
                if bar["high"] >= target:
                    return {
                        "exit_price": target,
                        "exit_reason": "target",
                        "pnl": target - entry_price,
                        "pnl_pct": (target - entry_price) / entry_price,
                        "bars_held": i - entry_idx
                    }
            else:  # short
                # Check stop loss
                if bar["high"] >= stop_loss:
                    return {
                        "exit_price": stop_loss,
                        "exit_reason": "stop_loss",
                        "pnl": entry_price - stop_loss,
                        "pnl_pct": (entry_price - stop_loss) / entry_price,
                        "bars_held": i - entry_idx
                    }
                # Check target
                if bar["low"] <= target:
                    return {
                        "exit_price": target,
                        "exit_reason": "target",
                        "pnl": entry_price - target,
                        "pnl_pct": (entry_price - target) / entry_price,
                        "bars_held": i - entry_idx
                    }
        
        # End of data - close at last price
        last_bar = bars[min(entry_idx + 30, len(bars) - 1)]
        exit_price = last_bar["close"]
        
        if direction == "long":
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price
        
        return {
            "exit_price": exit_price,
            "exit_reason": "eod",
            "pnl": pnl,
            "pnl_pct": pnl / entry_price,
            "bars_held": min(30, len(bars) - entry_idx - 1)
        }
    
    def run_parameter_test(self, confidence_grade: str, fvg_threshold: float, 
                          stop_loss_pct: float) -> Dict:
        """
        Test a single parameter combination across all tickers.
        OPTIMIZED: Uses in-memory bars_cache instead of DB queries.
        """
        results = {
            "confidence_grade": confidence_grade,
            "fvg_threshold": fvg_threshold,
            "stop_loss_pct": stop_loss_pct,
            "trades": [],
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0,
            "win_rate": 0,
            "avg_pnl": 0
        }
        
        # Use cached bars instead of loading from DB
        for ticker, bars in self.bars_cache.items():
            # Detect signals
            signals = self.detect_signals(ticker, bars, fvg_threshold, confidence_grade)
            
            # Simulate each trade
            for signal in signals:
                trade_result = self.simulate_trade(signal, bars, stop_loss_pct)
                
                if trade_result:
                    results["trades"].append({
                        "ticker": ticker,
                        "entry": signal["entry_price"],
                        "exit": trade_result["exit_price"],
                        "pnl": trade_result["pnl"],
                        "pnl_pct": trade_result["pnl_pct"],
                        "direction": signal["direction"],
                        "exit_reason": trade_result["exit_reason"]
                    })
        
        # Calculate stats
        if results["trades"]:
            results["total_trades"] = len(results["trades"])
            results["winning_trades"] = sum(1 for t in results["trades"] if t["pnl"] > 0)
            results["losing_trades"] = sum(1 for t in results["trades"] if t["pnl"] <= 0)
            results["total_pnl"] = sum(t["pnl"] for t in results["trades"])
            results["win_rate"] = (results["winning_trades"] / results["total_trades"]) * 100
            results["avg_pnl"] = results["total_pnl"] / results["total_trades"]
        
        return results
    
    def run_comprehensive_backtest(self) -> pd.DataFrame:
        """
        Test all parameter combinations.
        """
        # Parameter grid
        confidence_grades = ["A+", "A", "A-", "B+", "B"]
        fvg_thresholds = [0.001, 0.002, 0.003, 0.005, 0.01]
        stop_loss_pcts = [0.01, 0.015, 0.02, 0.025, 0.03]
        
        total_tests = len(confidence_grades) * len(fvg_thresholds) * len(stop_loss_pcts)
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing {total_tests} parameter combinations...")
        logger.info(f"{'='*60}\n")
        
        all_results = []
        test_num = 0
        
        import time
        start_time = time.time()
        
        for conf in confidence_grades:
            for fvg in fvg_thresholds:
                for sl in stop_loss_pcts:
                    test_num += 1
                    test_start = time.time()
                    
                    result = self.run_parameter_test(conf, fvg, sl)
                    all_results.append(result)
                    
                    test_duration = time.time() - test_start
                    elapsed = time.time() - start_time
                    avg_time = elapsed / test_num
                    remaining = (total_tests - test_num) * avg_time
                    
                    logger.info(
                        f"[{test_num}/{total_tests}] conf={conf} fvg={fvg:.3f} sl={sl:.2f} | "
                        f"Trades: {result['total_trades']} | "
                        f"Time: {test_duration:.1f}s | "
                        f"ETA: {remaining/60:.1f}m"
                    )
                    
                    # Save partial results every 25 tests
                    if test_num % 25 == 0:
                        df = pd.DataFrame(all_results)
                        df.to_csv(f"backtest_results_partial_{test_num}.csv", index=False)
                        logger.info(f"💾 Saved partial results to backtest_results_partial_{test_num}.csv")
        
        logger.info("\n✅ Backtest complete!")
        return pd.DataFrame(all_results)


def main():
    """
    Main backtest runner.
    """
    logger.info("="*60)
    logger.info("COMPREHENSIVE BACKTEST ENGINE - OPTIMIZED")
    logger.info("="*60)
    
    # Initialize engine (this caches all bars)
    engine = BacktestEngine()
    
    # Run backtest
    results_df = engine.run_comprehensive_backtest()
    
    # Save full results
    results_df.to_csv("backtest_results.csv", index=False)
    logger.info(f"\n💾 Saved results to backtest_results.csv")
    
    # Find top configurations
    if len(results_df) > 0:
        # Filter for profitable configs
        profitable = results_df[results_df["total_pnl"] > 0]
        
        if len(profitable) > 0:
            # Sort by total PnL
            top_10 = profitable.nlargest(10, "total_pnl")
            
            # Save top configs
            top_configs = top_10.to_dict("records")
            with open("top_configs.json", "w") as f:
                json.dump(top_configs, f, indent=2)
            
            # Print summary
            print("\n" + "="*60)
            print("TOP 10 CONFIGURATIONS")
            print("="*60)
            for idx, config in enumerate(top_configs, 1):
                print(f"\n#{idx}")
                print(f"  Confidence: {config['confidence_grade']}")
                print(f"  FVG Threshold: {config['fvg_threshold']}")
                print(f"  Stop Loss: {config['stop_loss_pct']*100}%")
                print(f"  Total Trades: {config['total_trades']}")
                print(f"  Win Rate: {config['win_rate']:.1f}%")
                print(f"  Total PnL: ${config['total_pnl']:.2f}")
                print(f"  Avg PnL: ${config['avg_pnl']:.2f}")
        else:
            logger.warning("⚠️  No profitable configurations found!")
    
    # Create summary report
    with open("backtest_summary.txt", "w") as f:
        f.write("COMPREHENSIVE BACKTEST SUMMARY\n")
        f.write("="*60 + "\n\n")
        f.write(f"Total configurations tested: {len(results_df)}\n")
        if len(profitable) > 0:
            f.write(f"Profitable configurations: {len(profitable)}\n")
            f.write(f"Best total PnL: ${results_df['total_pnl'].max():.2f}\n")
            f.write(f"Best win rate: {results_df['win_rate'].max():.1f}%\n")
    
    print("\n" + "="*60)
    print("✅ BACKTEST COMPLETE!")
    print("="*60)
    print("\nCheck these files:")
    print("  - backtest_results.csv (all results)")
    print("  - top_configs.json (top 10 configs)")
    print("  - backtest_summary.txt (detailed report)\n")


if __name__ == "__main__":
    main()
