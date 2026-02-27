#!/usr/bin/env python3
"""
Comprehensive BOS/FVG Parameter Optimization - EXPANDED GRID (900+ COMBINATIONS)

Tests 900+ parameter combinations to find optimal settings:
- Volume multipliers: 1.5x to 8.0x (10 values)
- ATR stop multipliers: 1.0x to 6.0x (10 values)
- Risk:reward ratios: 1.5R to 6.0R (9 values)
- Lookback periods: 6, 8, 10, 12, 14, 16, 20 (7 values)
- Momentum filters: none, weak, strong (3 values)
- Trend filters: none, aligned (2 values)
- Time filters: all, open, mid, power (4 values)

After filtering unrealistic combinations: ~900-1000 tests

Goal: Find optimal balance between:
- Win rate (target 45-65%)
- Trade count (target 20-100 trades)
- Profit factor (target >1.5)
- Risk:Reward alignment
"""

import sys
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
import sqlite3
import json
from pathlib import Path
import time as time_module
from itertools import product

from data_manager import DataManager

ET = ZoneInfo("America/New_York")

print("\n" + "="*70)
print("COMPREHENSIVE PARAMETER OPTIMIZATION - EXPANDED GRID (900+)")
print("="*70)


class ComprehensiveOptimizer:
    """
    Tests 900+ parameter combinations to find optimal BOS/FVG settings.
    Uses caching to avoid re-running same tests.
    """
    
    def __init__(self):
        self.dm = DataManager()
        self.cache_dir = Path("backtest_cache")
        self.cache_dir.mkdir(exist_ok=True)
        
        # Test period
        self.test_days = 10
        self.end_date = datetime.now(ET).date()
        self.start_date = self.end_date - timedelta(days=self.test_days)
        
        # Expanded ticker universe
        self.tickers = [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
            "TSLA", "META", "AMD", "GOOGL", "AMZN",
            "NFLX", "INTC", "PLTR", "COIN", "SOFI"
        ]
        
        # Cache loaded bars
        self.bars_cache = {}
        self.pdh_pdl_cache = {}
        
        print(f"Period: {self.start_date} to {self.end_date}")
        print(f"Tickers: {len(self.tickers)}")
        print(f"Cache: {self.cache_dir}")
        print("="*70)
        print()
    
    def load_all_bars(self):
        """Pre-load all bars into memory for speed."""
        print("⏳ Loading bars into memory...")
        total_bars = 0
        
        for ticker in self.tickers:
            bars = self.dm.get_bars_between(
                ticker=ticker,
                start=self.start_date,
                end=self.end_date
            )
            
            if bars:
                self.bars_cache[ticker] = bars
                total_bars += len(bars)
                print(f"  ✅ {ticker}: {len(bars):,} bars")
            else:
                print(f"  ⚠️  {ticker}: No data")
        
        print(f"\n✅ Cached {len(self.bars_cache)} tickers with {total_bars:,} total bars\n")
    
    def load_pdh_pdl(self):
        """Load previous day high/low for each ticker."""
        print("⏳ Loading previous day OHLC data...")
        
        for ticker in self.tickers:
            if ticker not in self.bars_cache:
                continue
            
            # Get bars from day before test period
            prev_date = self.start_date - timedelta(days=1)
            bars = self.dm.get_bars_between(ticker, prev_date, prev_date)
            
            if bars:
                pdh = max(b["high"] for b in bars)
                pdl = min(b["low"] for b in bars)
                self.pdh_pdl_cache[ticker] = {"pdh": pdh, "pdl": pdl}
                print(f"  ✅ {ticker} PDH: ${pdh:.2f} PDL: ${pdl:.2f}")
        
        print()
    
    def get_vix_level(self) -> float:
        """Get current VIX level from database."""
        conn = sqlite3.connect("market_memory.db")
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT close FROM intraday_bars
                WHERE ticker = '^VIX'
                ORDER BY datetime DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                return float(row[0])
        except:
            pass
        finally:
            cur.close()
            conn.close()
        
        return 0.0
    
    def generate_parameter_grid(self) -> List[Dict]:
        """
        Generate expanded parameter grid (900+ combinations).
        
        Returns:
            List of parameter dicts
        """
        grid = []
        
        # EXPANDED RANGES with finer granularity
        volume_multipliers = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 8.0]
        atr_stops = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]
        risk_rewards = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]
        lookbacks = [6, 8, 10, 12, 14, 16, 20]
        momentum_filters = ['none', 'weak', 'strong']
        trend_filters = ['none', 'aligned']
        time_filters = ['all', 'open', 'mid', 'power']
        
        for vol in volume_multipliers:
            for atr in atr_stops:
                for rr in risk_rewards:
                    for lb in lookbacks:
                        for momentum in momentum_filters:
                            for trend in trend_filters:
                                for timefilter in time_filters:
                                    # Skip unrealistic combinations
                                    if atr * rr > 25:  # Skip if target is >25 ATRs away
                                        continue
                                    if vol > 6.0 and atr < 2.0:  # High volume needs wider stops
                                        continue
                                    if rr > 4.0 and atr < 2.0:  # High R:R needs wider stops
                                        continue
                                    
                                    grid.append({
                                        "volume_multiplier": vol,
                                        "atr_stop_multiplier": atr,
                                        "target_rr": rr,
                                        "lookback": lb,
                                        "momentum_filter": momentum,
                                        "trend_filter": trend,
                                        "time_filter": timefilter
                                    })
        
        return grid
    
    def get_cache_key(self, params: Dict) -> str:
        """Generate cache key from parameters."""
        return f"vol{params['volume_multiplier']}_atr{params['atr_stop_multiplier']}_rr{params['target_rr']}_lb{params['lookback']}_mom{params['momentum_filter']}_trend{params['trend_filter']}_time{params['time_filter']}"
    
    def load_cached_result(self, cache_key: str) -> Optional[Dict]:
        """Load cached backtest result if exists."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except:
                return None
        
        return None
    
    def save_cached_result(self, cache_key: str, result: Dict):
        """Save backtest result to cache."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        try:
            with open(cache_file, 'w') as f:
                json.dump(result, f)
        except:
            pass
    
    def detect_bos(self, bars: List[Dict], idx: int, lookback: int, direction: str) -> bool:
        """Detect break of structure."""
        if idx < lookback:
            return False
        
        current = bars[idx]
        recent = bars[idx-lookback:idx]
        
        if direction == "LONG":
            recent_highs = [b["high"] for b in recent]
            return current["high"] > max(recent_highs)
        else:
            recent_lows = [b["low"] for b in recent]
            return current["low"] < min(recent_lows)
    
    def calculate_atr(self, bars: List[Dict], idx: int, period: int = 14) -> float:
        """Calculate ATR at specific index."""
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
        """Calculate momentum (rate of change)."""
        if idx < period:
            return 0.0
        
        current = bars[idx]["close"]
        past = bars[idx - period]["close"]
        
        return (current - past) / past if past != 0 else 0.0
    
    def check_time_filter(self, dt: datetime, timefilter: str) -> bool:
        """Check if time matches filter."""
        if timefilter == 'all':
            return True
        
        t = dt.time()
        
        if timefilter == 'open':
            return dtime(9, 30) <= t < dtime(10, 0)
        elif timefilter == 'mid':
            return dtime(11, 0) <= t < dtime(14, 0)
        elif timefilter == 'power':
            return dtime(15, 30) <= t <= dtime(16, 0)
        
        return False
    
    def backtest_parameters(self, params: Dict) -> Dict:
        """Run backtest with specific parameters."""
        trades = []
        
        for ticker in self.tickers:
            if ticker not in self.bars_cache:
                continue
            
            bars = self.bars_cache[ticker]
            pdh_pdl = self.pdh_pdl_cache.get(ticker, {"pdh": 0, "pdl": 0})
            
            for i in range(params["lookback"] + 20, len(bars)):
                current = bars[i]
                
                # Time filter
                if not self.check_time_filter(current["datetime"], params["time_filter"]):
                    continue
                
                # Volume filter
                recent = bars[max(0, i-20):i]
                avg_volume = sum(b["volume"] for b in recent) / len(recent) if recent else 0
                
                if avg_volume == 0 or current["volume"] < avg_volume * params["volume_multiplier"]:
                    continue
                
                # ATR calculation
                atr = self.calculate_atr(bars, i)
                if atr == 0:
                    continue
                
                # Momentum filter
                momentum = self.calculate_momentum(bars, i)
                
                if params["momentum_filter"] == 'weak':
                    if abs(momentum) < 0.002:  # 0.2%
                        continue
                elif params["momentum_filter"] == 'strong':
                    if abs(momentum) < 0.005:  # 0.5%
                        continue
                
                # Detect LONG setup
                if self.detect_bos(bars, i, params["lookback"], "LONG"):
                    if pdh_pdl["pdh"] > 0 and current["close"] > pdh_pdl["pdh"]:
                        # Trend filter
                        if params["trend_filter"] == 'aligned':
                            if momentum <= 0:
                                continue
                        
                        entry = current["close"]
                        stop = entry - (atr * params["atr_stop_multiplier"])
                        target = entry + (atr * params["atr_stop_multiplier"] * params["target_rr"])
                        
                        # Simulate outcome
                        outcome = self.simulate_trade(bars, i+1, "LONG", entry, stop, target)
                        if outcome:
                            trades.append(outcome)
                
                # Detect SHORT setup
                elif self.detect_bos(bars, i, params["lookback"], "SHORT"):
                    if pdh_pdl["pdl"] > 0 and current["close"] < pdh_pdl["pdl"]:
                        # Trend filter
                        if params["trend_filter"] == 'aligned':
                            if momentum >= 0:
                                continue
                        
                        entry = current["close"]
                        stop = entry + (atr * params["atr_stop_multiplier"])
                        target = entry - (atr * params["atr_stop_multiplier"] * params["target_rr"])
                        
                        # Simulate outcome
                        outcome = self.simulate_trade(bars, i+1, "SHORT", entry, stop, target)
                        if outcome:
                            trades.append(outcome)
        
        # Calculate metrics
        if not trades:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_pnl": 0.0
            }
        
        winners = [t for t in trades if t["pnl"] > 0]
        losers = [t for t in trades if t["pnl"] <= 0]
        
        total_pnl = sum(t["pnl"] for t in trades)
        win_rate = len(winners) / len(trades) * 100 if trades else 0
        
        total_wins = sum(t["pnl"] for t in winners) if winners else 0
        total_losses = abs(sum(t["pnl"] for t in losers)) if losers else 0
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        return {
            "trades": len(trades),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "avg_win": sum(t["pnl"] for t in winners) / len(winners) if winners else 0,
            "avg_loss": sum(t["pnl"] for t in losers) / len(losers) if losers else 0
        }
    
    def simulate_trade(self, bars: List[Dict], start_idx: int, direction: str, 
                      entry: float, stop: float, target: float) -> Optional[Dict]:
        """Simulate trade execution."""
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
    
    def run_optimization(self):
        """Run comprehensive parameter optimization."""
        # Pre-load data
        self.load_all_bars()
        self.load_pdh_pdl()
        
        vix = self.get_vix_level()
        if vix > 0:
            vix_desc = "High" if vix > 20 else "Normal" if vix > 15 else "Low"
            print(f"📉 Current VIX: {vix:.2f} ({vix_desc} volatility)\n")
        
        # Generate parameter grid
        print("="*70)
        print("BUILDING EXPANDED PARAMETER GRID")
        print("="*70)
        print()
        
        param_grid = self.generate_parameter_grid()
        print(f"✅ Generated {len(param_grid)} parameter combinations")
        
        # Check cache
        cached_count = 0
        for params in param_grid:
            cache_key = self.get_cache_key(params)
            if self.load_cached_result(cache_key):
                cached_count += 1
        
        print(f"💾 Found {cached_count} cached results")
        print(f"\n🎯 TARGET: 20-100 quality trades @ 45-65% win rate")
        print()
        
        # Run tests
        print("="*70)
        print("TESTING PARAMETERS")
        print("="*70)
        print()
        
        results = []
        start_time = time_module.time()
        
        for idx, params in enumerate(param_grid, 1):
            cache_key = self.get_cache_key(params)
            
            # Try cache first
            cached = self.load_cached_result(cache_key)
            if cached:
                result = cached
                status = "⚡ CACHED"
            else:
                result = self.backtest_parameters(params)
                self.save_cached_result(cache_key, result)
                status = "✅ TESTED"
            
            results.append({**params, **result})
            
            # Print progress every 10 tests
            if idx % 10 == 0 or idx == len(param_grid):
                elapsed = time_module.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                eta = (len(param_grid) - idx) / rate if rate > 0 else 0
                
                print(f"[{idx}/{len(param_grid)}] {status} | "
                      f"Vol={params['volume_multiplier']}x "
                      f"ATR={params['atr_stop_multiplier']} "
                      f"RR={params['target_rr']} "
                      f"LB={params['lookback']} | "
                      f"Trades: {result['trades']} "
                      f"WR: {result['win_rate']:.1f}% "
                      f"PF: {result['profit_factor']:.2f} | "
                      f"ETA: {eta/60:.1f}m")
        
        # Save results
        df = pd.DataFrame(results)
        df.to_csv("comprehensive_optimization_results.csv", index=False)
        
        # Generate report
        self.generate_report(df)
    
    def generate_report(self, df: pd.DataFrame):
        """Generate optimization report."""
        print("\n" + "="*70)
        print("OPTIMIZATION COMPLETE")
        print("="*70)
        print()
        
        # Filter for quality setups
        quality = df[
            (df["trades"] >= 20) & 
            (df["trades"] <= 100) &
            (df["win_rate"] >= 45) &
            (df["profit_factor"] >= 1.5)
        ].copy()
        
        quality = quality.sort_values("profit_factor", ascending=False)
        
        print(f"📊 Total Configurations Tested: {len(df)}")
        print(f"✅ Quality Setups Found: {len(quality)}")
        print()
        
        if len(quality) > 0:
            print("🏆 TOP 10 PARAMETER SETS:")
            print()
            
            for idx, row in quality.head(10).iterrows():
                print(f"{idx+1}. Vol={row['volume_multiplier']}x | "
                      f"ATR={row['atr_stop_multiplier']}x | "
                      f"RR={row['target_rr']}R | "
                      f"LB={row['lookback']} | "
                      f"Mom={row['momentum_filter']} | "
                      f"Trend={row['trend_filter']} | "
                      f"Time={row['time_filter']}")
                print(f"   Trades: {row['trades']:.0f} | "
                      f"WR: {row['win_rate']:.1f}% | "
                      f"PF: {row['profit_factor']:.2f} | "
                      f"P&L: ${row['total_pnl']:.2f}")
                print()
        else:
            print("⚠️  No configurations met quality criteria")
            print("   Showing best by profit factor:")
            print()
            
            best = df.sort_values("profit_factor", ascending=False).head(10)
            for idx, row in best.iterrows():
                print(f"{idx+1}. Vol={row['volume_multiplier']}x | "
                      f"ATR={row['atr_stop_multiplier']}x | "
                      f"RR={row['target_rr']}R | "
                      f"LB={row['lookback']}")
                print(f"   Trades: {row['trades']:.0f} | "
                      f"WR: {row['win_rate']:.1f}% | "
                      f"PF: {row['profit_factor']:.2f}")
                print()
        
        print("="*70)
        print("✅ Results saved to: comprehensive_optimization_results.csv")
        print("="*70)
        print()


def main():
    optimizer = ComprehensiveOptimizer()
    optimizer.run_optimization()


if __name__ == "__main__":
    main()
