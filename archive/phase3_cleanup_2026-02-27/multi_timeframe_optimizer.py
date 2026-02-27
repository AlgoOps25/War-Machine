#!/usr/bin/env python3
"""
Multi-Timeframe Optimizer

Compares 1-min bars (baseline) vs 5-min bars for BOS detection.
Tests whether higher timeframes produce cleaner signals with less noise.

Baseline (1-min):
- Lookback: 16 bars = 16 minutes
- Expected: 37 trades, 73% WR, 2.74 PF

5-Min Tests:
- Lookback variations: 10, 16, 20 bars
- 10 bars = 50 min, 16 bars = 80 min, 20 bars = 100 min
- Expected: Fewer trades, higher quality
"""

import sys
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import sqlite3
import pandas as pd

ET = ZoneInfo("America/New_York")

print("\n" + "="*70)
print("MULTI-TIMEFRAME OPTIMIZER")
print("Testing 5-min bars vs 1-min baseline")
print("="*70)
print()


class MultiTimeframeOptimizer:
    """
    Tests different timeframes to find optimal BOS detection period.
    """
    
    def __init__(self):
        self.db_path = "market_memory.db"
        
        # BASE CONFIG (V2 Winner)
        self.base_config = {
            "volume_multiplier": 2.0,
            "atr_stop_multiplier": 4.0,
            "target_rr": 2.5,
            "momentum_threshold": 0.002,  # 0.2%
        }
        
        # Test period (30 days)
        self.end_date = datetime(2026, 2, 27, tzinfo=ET).date()
        self.start_date = self.end_date - timedelta(days=30)
        
        # Tickers
        self.tickers = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
        
        # Cache
        self.bars_cache_1min = {}
        self.bars_cache_5min = {}
        self.pdh_pdl_cache = {}
        
        print(f"Base Config: Vol={self.base_config['volume_multiplier']}x | "
              f"ATR={self.base_config['atr_stop_multiplier']}x | "
              f"RR={self.base_config['target_rr']}R")
        print(f"Test Period: {self.start_date} to {self.end_date} (30 days)")
        print(f"Tickers: {', '.join(self.tickers)}")
        print("="*70)
        print()
    
    def load_bars_from_db(self, ticker: str) -> List[Dict]:
        """Load 1-min bars from database."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        query = """
            SELECT datetime, open, high, low, close, volume
            FROM intraday_bars
            WHERE ticker = ?
              AND datetime >= ?
              AND datetime <= ?
            ORDER BY datetime ASC
        """
        
        try:
            cur.execute(query, (ticker, self.start_date, self.end_date))
            rows = cur.fetchall()
            
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
            print(f"  Error loading {ticker}: {e}")
            return []
        
        finally:
            cur.close()
            conn.close()
    
    def aggregate_to_5min(self, bars_1min: List[Dict]) -> List[Dict]:
        """Aggregate 1-min bars into 5-min bars."""
        if not bars_1min:
            return []
        
        bars_5min = []
        current_5min = None
        
        for bar in bars_1min:
            minute = bar["datetime"].minute
            
            # Start new 5-min bar at 0, 5, 10, 15, etc.
            if minute % 5 == 0 or current_5min is None:
                if current_5min is not None:
                    bars_5min.append(current_5min)
                
                current_5min = {
                    "datetime": bar["datetime"],
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"]
                }
            else:
                # Update current 5-min bar
                current_5min["high"] = max(current_5min["high"], bar["high"])
                current_5min["low"] = min(current_5min["low"], bar["low"])
                current_5min["close"] = bar["close"]
                current_5min["volume"] += bar["volume"]
        
        # Add final bar
        if current_5min is not None:
            bars_5min.append(current_5min)
        
        return bars_5min
    
    def load_all_data(self):
        """Load all bars and convert to different timeframes."""
        print("⏳ Loading and aggregating data...")
        
        for ticker in self.tickers:
            bars_1min = self.load_bars_from_db(ticker)
            
            if bars_1min:
                self.bars_cache_1min[ticker] = bars_1min
                
                # Aggregate to 5-min
                bars_5min = self.aggregate_to_5min(bars_1min)
                self.bars_cache_5min[ticker] = bars_5min
                
                print(f"  ✅ {ticker}: {len(bars_1min):,} (1-min) → {len(bars_5min):,} (5-min)")
            else:
                print(f"  ⚠️  {ticker}: No data")
        
        print()
        
        # Load PDH/PDL
        self.load_pdh_pdl()
    
    def load_pdh_pdl(self):
        """Load previous day high/low."""
        print("⏳ Loading PDH/PDL data...")
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        for days_back in range(1, 11):
            prev_date = self.start_date - timedelta(days=days_back)
            prev_date_str = prev_date.isoformat()
            
            found_any = False
            
            for ticker in self.tickers:
                if ticker not in self.bars_cache_1min:
                    continue
                
                query = """
                    SELECT datetime, high, low
                    FROM intraday_bars
                    WHERE ticker = ?
                      AND date(datetime) = ?
                    ORDER BY datetime
                """
                
                try:
                    cur.execute(query, (ticker, prev_date_str))
                    rows = cur.fetchall()
                    
                    if rows:
                        pdh = max(float(r["high"]) for r in rows)
                        pdl = min(float(r["low"]) for r in rows)
                        self.pdh_pdl_cache[ticker] = {"pdh": pdh, "pdl": pdl}
                        found_any = True
                
                except Exception as e:
                    continue
            
            if found_any:
                print(f"  Using prior day: {prev_date}\n")
                break
        
        cur.close()
        conn.close()
    
    def find_swing_high(self, bars: List[Dict], idx: int, swing_window: int = 2) -> bool:
        """Identify swing high."""
        if idx < swing_window or idx >= len(bars) - swing_window:
            return False
        
        current_high = bars[idx]["high"]
        
        for i in range(idx - swing_window, idx):
            if bars[i]["high"] >= current_high:
                return False
        
        for i in range(idx + 1, min(idx + swing_window + 1, len(bars))):
            if bars[i]["high"] >= current_high:
                return False
        
        return True
    
    def find_swing_low(self, bars: List[Dict], idx: int, swing_window: int = 2) -> bool:
        """Identify swing low."""
        if idx < swing_window or idx >= len(bars) - swing_window:
            return False
        
        current_low = bars[idx]["low"]
        
        for i in range(idx - swing_window, idx):
            if bars[i]["low"] <= current_low:
                return False
        
        for i in range(idx + 1, min(idx + swing_window + 1, len(bars))):
            if bars[i]["low"] <= current_low:
                return False
        
        return True
    
    def detect_bos(self, bars: List[Dict], idx: int, lookback: int, direction: str) -> bool:
        """Detect break of structure."""
        if idx < lookback + 10:
            return False
        
        current = bars[idx]
        
        if direction == "LONG":
            for i in range(idx - lookback, idx - 5):
                if i < 0:
                    continue
                if self.find_swing_high(bars, i):
                    last_swing_high = bars[i]["high"]
                    return current["high"] > last_swing_high
            return False
        
        else:  # SHORT
            for i in range(idx - lookback, idx - 5):
                if i < 0:
                    continue
                if self.find_swing_low(bars, i):
                    last_swing_low = bars[i]["low"]
                    return current["low"] < last_swing_low
            return False
    
    def calculate_atr(self, bars: List[Dict], idx: int, period: int = 14) -> float:
        """Calculate ATR."""
        if idx < period + 1:
            return 0.0
        
        recent = bars[max(0, idx-period-1):idx+1]
        
        true_ranges = []
        for i in range(1, len(recent)):
            high = recent[i]["high"]
            low = recent[i]["low"]
            prev_close = recent[i-1]["close"]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
    
    def calculate_momentum(self, bars: List[Dict], idx: int, period: int = 5) -> float:
        """Calculate momentum."""
        if idx < period:
            return 0.0
        
        current = bars[idx]["close"]
        past = bars[idx - period]["close"]
        
        return (current - past) / past if past != 0 else 0.0
    
    def check_time_filter(self, dt: datetime) -> bool:
        """Check if within opening range (9:30-10:00 AM)."""
        t = dt.time()
        return dtime(9, 30) <= t < dtime(10, 0)
    
    def simulate_trade(self, bars: List[Dict], start_idx: int, direction: str,
                      entry: float, stop: float, target: float) -> Optional[Dict]:
        """Simulate trade outcome."""
        if start_idx >= len(bars):
            return None
        
        future_bars = bars[start_idx:min(start_idx + 30, len(bars))]
        
        for i, bar in enumerate(future_bars, 1):
            if direction == "LONG":
                if bar["low"] <= stop:
                    return {"pnl": stop - entry, "bars": i, "exit": "stop"}
                if bar["high"] >= target:
                    return {"pnl": target - entry, "bars": i, "exit": "target"}
            else:
                if bar["high"] >= stop:
                    return {"pnl": entry - stop, "bars": i, "exit": "stop"}
                if bar["low"] <= target:
                    return {"pnl": entry - target, "bars": i, "exit": "target"}
        
        # Timeout
        if future_bars:
            final_bar = future_bars[-1]
            pnl = (final_bar["close"] - entry) if direction == "LONG" else (entry - final_bar["close"])
            return {"pnl": pnl, "bars": len(future_bars), "exit": "timeout"}
        
        return None
    
    def run_backtest(self, timeframe: str, lookback: int) -> Dict:
        """Run backtest on specific timeframe and lookback."""
        # Select bar cache
        if timeframe == "1min":
            bars_cache = self.bars_cache_1min
        else:  # 5min
            bars_cache = self.bars_cache_5min
        
        trades = []
        
        for ticker in self.tickers:
            if ticker not in bars_cache:
                continue
            
            bars = bars_cache[ticker]
            pdh_pdl = self.pdh_pdl_cache.get(ticker, {"pdh": 0, "pdl": 0})
            
            for i in range(lookback + 20, len(bars) - 5):
                current = bars[i]
                
                # Time filter (Opening range)
                if not self.check_time_filter(current["datetime"]):
                    continue
                
                # Volume filter
                recent = bars[max(0, i-20):i]
                avg_volume = sum(b["volume"] for b in recent) / len(recent) if recent else 0
                
                if avg_volume == 0 or current["volume"] < avg_volume * self.base_config["volume_multiplier"]:
                    continue
                
                # ATR
                atr = self.calculate_atr(bars, i)
                if atr == 0:
                    continue
                
                # Momentum filter
                momentum = self.calculate_momentum(bars, i)
                
                if abs(momentum) < self.base_config["momentum_threshold"]:
                    continue
                
                # LONG setup
                if self.detect_bos(bars, i, lookback, "LONG"):
                    if pdh_pdl["pdh"] > 0 and current["close"] > pdh_pdl["pdh"]:
                        entry = current["close"]
                        stop = entry - (atr * self.base_config["atr_stop_multiplier"])
                        target = entry + (atr * self.base_config["atr_stop_multiplier"] * self.base_config["target_rr"])
                        
                        outcome = self.simulate_trade(bars, i+1, "LONG", entry, stop, target)
                        if outcome:
                            trades.append({"pnl": outcome["pnl"], "direction": "LONG"})
                
                # SHORT setup
                elif self.detect_bos(bars, i, lookback, "SHORT"):
                    if pdh_pdl["pdl"] > 0 and current["close"] < pdh_pdl["pdl"]:
                        entry = current["close"]
                        stop = entry + (atr * self.base_config["atr_stop_multiplier"])
                        target = entry - (atr * self.base_config["atr_stop_multiplier"] * self.base_config["target_rr"])
                        
                        outcome = self.simulate_trade(bars, i+1, "SHORT", entry, stop, target)
                        if outcome:
                            trades.append({"pnl": outcome["pnl"], "direction": "SHORT"})
        
        # Calculate metrics
        if not trades:
            return {
                "timeframe": timeframe,
                "lookback": lookback,
                "trades": 0,
                "winners": 0,
                "losers": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "total_pnl": 0,
                "avg_win": 0,
                "avg_loss": 0
            }
        
        winners = [t for t in trades if t["pnl"] > 0]
        losers = [t for t in trades if t["pnl"] <= 0]
        
        total_pnl = sum(t["pnl"] for t in trades)
        win_rate = len(winners) / len(trades) * 100 if trades else 0
        
        total_wins = sum(t["pnl"] for t in winners) if winners else 0
        total_losses = abs(sum(t["pnl"] for t in losers)) if losers else 0
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        avg_win = sum(t["pnl"] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t["pnl"] for t in losers) / len(losers) if losers else 0
        
        return {
            "timeframe": timeframe,
            "lookback": lookback,
            "trades": len(trades),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss
        }
    
    def test_all_timeframes(self) -> List[Dict]:
        """Test all timeframe and lookback combinations."""
        print("="*70)
        print("RUNNING MULTI-TIMEFRAME TESTS")
        print("="*70)
        print()
        
        results = []
        
        # 1-MIN BASELINE
        print("[1/5] Testing 1-min (16 bars = 16 min lookback)...")
        result = self.run_backtest("1min", lookback=16)
        results.append(result)
        
        # 5-MIN VARIATIONS
        print("[2/5] Testing 5-min (8 bars = 40 min lookback)...")
        result = self.run_backtest("5min", lookback=8)
        results.append(result)
        
        print("[3/5] Testing 5-min (10 bars = 50 min lookback)...")
        result = self.run_backtest("5min", lookback=10)
        results.append(result)
        
        print("[4/5] Testing 5-min (16 bars = 80 min lookback)...")
        result = self.run_backtest("5min", lookback=16)
        results.append(result)
        
        print("[5/5] Testing 5-min (20 bars = 100 min lookback)...")
        result = self.run_backtest("5min", lookback=20)
        results.append(result)
        
        print()
        return results
    
    def generate_report(self, results: List[Dict]):
        """Generate comparison report."""
        baseline = results[0]
        
        print("\n" + "="*70)
        print("MULTI-TIMEFRAME COMPARISON")
        print("="*70)
        print()
        
        print(f"📊 BASELINE: 1-MIN (16 bars = 16 minutes)")
        print(f"   Trades: {baseline['trades']}")
        print(f"   Win Rate: {baseline['win_rate']:.1f}%")
        print(f"   Profit Factor: {baseline['profit_factor']:.2f}")
        print(f"   Total P&L: ${baseline['total_pnl']:.2f}")
        print(f"   Avg Win: ${baseline['avg_win']:.2f} | Avg Loss: ${baseline['avg_loss']:.2f}")
        print()
        print("="*70)
        print()
        
        for result in results[1:]:
            trade_delta = result['trades'] - baseline['trades']
            trade_delta_pct = (trade_delta / baseline['trades'] * 100) if baseline['trades'] > 0 else 0
            
            wr_delta = result['win_rate'] - baseline['win_rate']
            pf_delta = result['profit_factor'] - baseline['profit_factor']
            pnl_delta = result['total_pnl'] - baseline['total_pnl']
            
            lookback_minutes = result['lookback'] * 5  # 5-min bars
            
            # Determine verdict
            if result['trades'] < 10:
                verdict = "⚠️  TOO FEW TRADES"
            elif result['win_rate'] > baseline['win_rate'] + 3 and result['profit_factor'] > baseline['profit_factor'] + 0.3:
                verdict = "✅ SIGNIFICANTLY BETTER"
            elif result['win_rate'] > baseline['win_rate'] and result['profit_factor'] > baseline['profit_factor']:
                verdict = "✅ BETTER"
            elif result['win_rate'] < baseline['win_rate'] - 5 or result['profit_factor'] < baseline['profit_factor'] - 0.3:
                verdict = "❌ WORSE"
            else:
                verdict = "⚪ NEUTRAL"
            
            print(f"🔍 5-MIN ({result['lookback']} bars = {lookback_minutes} minutes)")
            print(f"   Trades: {result['trades']} ({trade_delta:+d}, {trade_delta_pct:+.0f}%)")
            print(f"   Win Rate: {result['win_rate']:.1f}% ({wr_delta:+.1f}%)")
            print(f"   Profit Factor: {result['profit_factor']:.2f} ({pf_delta:+.2f})")
            print(f"   Total P&L: ${result['total_pnl']:.2f} (${pnl_delta:+.2f})")
            print(f"   Verdict: {verdict}")
            print()
        
        print("="*70)
        print()
        
        # Find best performer
        best = max(results, key=lambda x: x['profit_factor'] if x['trades'] >= 10 else 0)
        
        if best['timeframe'] == '1min':
            print("✅ RECOMMENDATION: STICK WITH 1-MIN BASELINE")
            print("   5-min bars did not improve performance.")
        else:
            print("✅ RECOMMENDATION: SWITCH TO 5-MIN BARS")
            print(f"   Best config: {best['lookback']} bars = {best['lookback']*5} minutes")
            print(f"   WR: {best['win_rate']:.1f}% | PF: {best['profit_factor']:.2f} | P&L: ${best['total_pnl']:.2f}")
        
        print()
        print("="*70)
        print()


def main():
    optimizer = MultiTimeframeOptimizer()
    optimizer.load_all_data()
    results = optimizer.test_all_timeframes()
    optimizer.generate_report(results)


if __name__ == "__main__":
    main()
