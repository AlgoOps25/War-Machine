#!/usr/bin/env python3
"""
Realistic Backtest - War Machine BOS/FVG System

Uses actual signal detection logic from breakoutdetector.py:
- BOS (Break of Structure) with volume confirmation
- FVG (Fair Value Gap) detection
- ATR-based stops (1.5x multiplier)
- Structure-based targets (2.0R and 3.5R)
- Proper momentum and trend filters

Usage:
    python realistic_backtest.py

Output:
    - backtest_results.csv: All tested configurations
    - backtest_summary.txt: Performance summary
"""

import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

# Import War Machine modules
from utils.dbconnection import getconn
from breakoutdetector import BreakoutDetector
from technicalindicators import fetch_atr

print("=" * 80)
print("REALISTIC BACKTEST - War Machine BOS/FVG System")
print("=" * 80)
print()


class RealisticBacktest:
    """
    Backtest engine using actual War Machine signal detection.
    """
    
    def __init__(self):
        # Test parameters
        self.test_days = 10  # Last 10 trading days
        self.end_date = datetime.now().date()
        self.start_date = self.end_date - timedelta(days=self.test_days)
        
        # Liquid tickers for faster testing
        self.tickers = [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
            "TSLA", "META", "AMD", "GOOGL", "AMZN",
            "NFLX", "COIN", "PLTR", "SOFI", "RIVN"
        ]
        
        # Parameter grid to test
        self.confidence_grades = ["A+", "A", "A-", "B+", "B"]
        self.volume_multipliers = [1.5, 2.0, 2.5, 3.0]
        self.lookback_periods = [12, 16, 20]
        
        print(f"Backtest Period: {self.start_date} to {self.end_date}")
        print(f"Test Tickers: {len(self.tickers)}")
        print(f"Parameter Combinations: {len(self.confidence_grades) * len(self.volume_multipliers) * len(self.lookback_periods)}")
        print()
    
    def load_bars(self, ticker: str) -> List[Dict]:
        """Load historical bars from database."""
        conn = getconn()
        cur = conn.cursor()
        
        query = """
            SELECT ticker, datetime, open, high, low, close, volume
            FROM bars
            WHERE ticker = %s
              AND datetime >= %s
              AND datetime <= %s
            ORDER BY datetime ASC
        """
        
        cur.execute(query, (ticker, self.start_date, self.end_date))
        rows = cur.fetchall()
        
        bars = []
        for row in rows:
            bars.append({
                "ticker": row[0],
                "datetime": row[1],
                "open": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "close": float(row[5]),
                "volume": int(row[6]) if row[6] else 0
            })
        
        cur.close()
        return bars
    
    def detect_signals(
        self,
        ticker: str,
        bars: List[Dict],
        lookback: int,
        volume_mult: float
    ) -> List[Dict]:
        """
        Detect BOS/FVG signals using actual breakoutdetector logic.
        """
        if len(bars) < lookback + 5:
            return []
        
        detector = BreakoutDetector(
            lookback_bars=lookback,
            volume_multiplier=volume_mult,
            atr_stop_multiplier=1.5,  # Standard 1.5x ATR
            risk_reward_ratio=2.0     # T1 = 2.0R
        )
        
        signals = []
        
        # Scan through bars looking for setups
        for i in range(lookback + 5, len(bars)):
            window = bars[i - lookback:i + 1]
            
            # Check for bullish BOS
            bos_result = detector.detect_breakout(window, ticker)
            if bos_result and bos_result.get("direction") == "BUY":
                signal = {
                    "ticker": ticker,
                    "datetime": bars[i]["datetime"],
                    "direction": "BUY",
                    "entry_price": bars[i]["close"],
                    "stop_loss": bos_result.get("stop"),
                    "target1": bos_result.get("target1"),
                    "target2": bos_result.get("target2", bos_result.get("target1") * 1.75),
                    "confidence": bos_result.get("confidence", 70),
                    "type": "BOS"
                }
                signals.append(signal)
                continue
            
            # Check for bearish BOS
            if bos_result and bos_result.get("direction") == "SELL":
                signal = {
                    "ticker": ticker,
                    "datetime": bars[i]["datetime"],
                    "direction": "SELL",
                    "entry_price": bars[i]["close"],
                    "stop_loss": bos_result.get("stop"),
                    "target1": bos_result.get("target1"),
                    "target2": bos_result.get("target2", bos_result.get("target1") * 0.25),
                    "confidence": bos_result.get("confidence", 70),
                    "type": "BOS"
                }
                signals.append(signal)
                continue
            
            # Check for FVG retest
            fvg_result = detector.detect_retest_entry(
                window,
                level=bars[i]["close"],
                entry_type="BUY",
                ticker=ticker
            )
            
            if fvg_result:
                signal = {
                    "ticker": ticker,
                    "datetime": bars[i]["datetime"],
                    "direction": fvg_result.get("direction", "BUY"),
                    "entry_price": bars[i]["close"],
                    "stop_loss": fvg_result.get("stop"),
                    "target1": fvg_result.get("target1"),
                    "target2": fvg_result.get("target2", fvg_result.get("target1") * 1.75),
                    "confidence": fvg_result.get("confidence", 65),
                    "type": "FVG"
                }
                signals.append(signal)
        
        return signals
    
    def simulate_trade(
        self,
        signal: Dict,
        bars: List[Dict]
    ) -> Optional[Dict]:
        """
        Simulate trade execution and outcome.
        """
        entry_time = signal["datetime"]
        entry_price = signal["entry_price"]
        stop_loss = signal["stop_loss"]
        target1 = signal["target1"]
        target2 = signal["target2"]
        direction = signal["direction"]
        
        # Find bars after entry
        future_bars = [b for b in bars if b["datetime"] > entry_time]
        if not future_bars:
            return None
        
        # Track trade outcome
        for bar in future_bars[:20]:  # Max 20 bars (100 minutes)
            high = bar["high"]
            low = bar["low"]
            
            if direction == "BUY":
                # Check stop loss
                if low <= stop_loss:
                    return {
                        "outcome": "LOSS",
                        "exit_price": stop_loss,
                        "exit_time": bar["datetime"],
                        "pnl_pct": ((stop_loss - entry_price) / entry_price) * 100,
                        "bars_held": future_bars.index(bar) + 1
                    }
                
                # Check target 1 (50% position)
                if high >= target1:
                    return {
                        "outcome": "WIN_T1",
                        "exit_price": target1,
                        "exit_time": bar["datetime"],
                        "pnl_pct": ((target1 - entry_price) / entry_price) * 100,
                        "bars_held": future_bars.index(bar) + 1
                    }
                
                # Check target 2 (full position)
                if high >= target2:
                    return {
                        "outcome": "WIN_T2",
                        "exit_price": target2,
                        "exit_time": bar["datetime"],
                        "pnl_pct": ((target2 - entry_price) / entry_price) * 100,
                        "bars_held": future_bars.index(bar) + 1
                    }
            
            else:  # SELL
                # Check stop loss
                if high >= stop_loss:
                    return {
                        "outcome": "LOSS",
                        "exit_price": stop_loss,
                        "exit_time": bar["datetime"],
                        "pnl_pct": ((entry_price - stop_loss) / entry_price) * 100,
                        "bars_held": future_bars.index(bar) + 1
                    }
                
                # Check target 1
                if low <= target1:
                    return {
                        "outcome": "WIN_T1",
                        "exit_price": target1,
                        "exit_time": bar["datetime"],
                        "pnl_pct": ((entry_price - target1) / entry_price) * 100,
                        "bars_held": future_bars.index(bar) + 1
                    }
                
                # Check target 2
                if low <= target2:
                    return {
                        "outcome": "WIN_T2",
                        "exit_price": target2,
                        "exit_time": bar["datetime"],
                        "pnl_pct": ((entry_price - target2) / entry_price) * 100,
                        "bars_held": future_bars.index(bar) + 1
                    }
        
        # No target or stop hit within 20 bars - exit at close
        final_bar = future_bars[19] if len(future_bars) >= 20 else future_bars[-1]
        exit_price = final_bar["close"]
        
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100 if direction == "BUY" else ((entry_price - exit_price) / entry_price) * 100
        
        return {
            "outcome": "TIMEOUT_WIN" if pnl_pct > 0 else "TIMEOUT_LOSS",
            "exit_price": exit_price,
            "exit_time": final_bar["datetime"],
            "pnl_pct": pnl_pct,
            "bars_held": len(future_bars[:20])
        }
    
    def run_parameter_test(
        self,
        conf_grade: str,
        volume_mult: float,
        lookback: int
    ) -> Dict:
        """
        Test a single parameter configuration.
        """
        all_trades = []
        
        for ticker in self.tickers:
            # Load bars
            bars = self.load_bars(ticker)
            if len(bars) < lookback + 10:
                continue
            
            # Detect signals
            signals = self.detect_signals(ticker, bars, lookback, volume_mult)
            
            # Filter by confidence grade
            min_conf = {"A+": 85, "A": 80, "A-": 75, "B+": 70, "B": 65}.get(conf_grade, 65)
            signals = [s for s in signals if s.get("confidence", 0) >= min_conf]
            
            # Simulate each trade
            for signal in signals:
                result = self.simulate_trade(signal, bars)
                if result:
                    all_trades.append({
                        **signal,
                        **result
                    })
        
        # Calculate metrics
        if not all_trades:
            return {
                "conf_grade": conf_grade,
                "volume_mult": volume_mult,
                "lookback": lookback,
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "total_pnl": 0.0
            }
        
        wins = [t for t in all_trades if t["outcome"].startswith("WIN")]
        losses = [t for t in all_trades if "LOSS" in t["outcome"]]
        
        win_rate = (len(wins) / len(all_trades)) * 100 if all_trades else 0.0
        avg_win = sum([t["pnl_pct"] for t in wins]) / len(wins) if wins else 0.0
        avg_loss = sum([t["pnl_pct"] for t in losses]) / len(losses) if losses else 0.0
        total_pnl = sum([t["pnl_pct"] for t in all_trades])
        
        return {
            "conf_grade": conf_grade,
            "volume_mult": volume_mult,
            "lookback": lookback,
            "total_trades": len(all_trades),
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "total_pnl": round(total_pnl, 2),
            "wins": len(wins),
            "losses": len(losses)
        }
    
    def run_comprehensive_backtest(self) -> pd.DataFrame:
        """
        Test all parameter combinations.
        """
        results = []
        total_tests = len(self.confidence_grades) * len(self.volume_multipliers) * len(self.lookback_periods)
        test_num = 0
        
        print("Testing parameter combinations...")
        print()
        
        for conf in self.confidence_grades:
            for vol in self.volume_multipliers:
                for lookback in self.lookback_periods:
                    test_num += 1
                    
                    print(f"Progress: {test_num}/{total_tests} ({(test_num/total_tests)*100:.1f}%)")
                    print(f"Testing: Grade={conf}, Volume={vol}x, Lookback={lookback}")
                    
                    result = self.run_parameter_test(conf, vol, lookback)
                    results.append(result)
                    
                    print(f"  Trades: {result['total_trades']}, Win Rate: {result['win_rate']}%, Total P&L: {result['total_pnl']}%")
                    print()
        
        return pd.DataFrame(results)


def main():
    """Main backtest runner."""
    print("Initializing backtest engine...")
    print()
    
    engine = RealisticBacktest()
    
    # Run backtest
    results_df = engine.run_comprehensive_backtest()
    
    # Save results
    results_df.to_csv("backtest_results.csv", index=False)
    print(f"✓ Saved results to backtest_results.csv")
    
    # Sort by win rate and total P&L
    top_configs = results_df.sort_values(
        by=["win_rate", "total_pnl"],
        ascending=False
    ).head(10)
    
    # Generate summary
    with open("backtest_summary.txt", "w") as f:
        f.write("=" * 80 + "\n")
        f.write("REALISTIC BACKTEST SUMMARY\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total Configurations Tested: {len(results_df)}\n")
        f.write(f"Date Range: {engine.start_date} to {engine.end_date}\n")
        f.write(f"Tickers: {len(engine.tickers)}\n\n")
        f.write("=" * 80 + "\n")
        f.write("TOP 10 CONFIGURATIONS\n")
        f.write("=" * 80 + "\n\n")
        f.write(top_configs.to_string(index=False))
        f.write("\n\n")
    
    print(f"✓ Saved summary to backtest_summary.txt")
    print()
    print("=" * 80)
    print("BACKTEST COMPLETE!")
    print("=" * 80)
    print()
    print("Results:")
    print(f"  - backtest_results.csv: All {len(results_df)} configurations")
    print(f"  - backtest_summary.txt: Top 10 performers")
    print()
    print("Top Configuration:")
    print(top_configs.head(1).to_string(index=False))
    print()


if __name__ == "__main__":
    main()
