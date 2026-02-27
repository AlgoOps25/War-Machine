#!/usr/bin/env python3
"""
Focused Parameter Optimization - ~1000 High-Quality Combinations

FIXED: PDH/PDL loading now uses correct date format for SQL queries.
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

ET = ZoneInfo("America/New_York")

print("\n" + "="*70)
print("FOCUSED PARAMETER OPTIMIZATION - 1000 SMART COMBINATIONS")
print("="*70)


class FocusedOptimizer:
    """
    Tests ~1000 carefully selected parameter combinations.
    Focuses on realistic trading scenarios with smart filtering.
    """
    
    def __init__(self):
        self.db_path = "market_memory.db"
        self.cache_dir = Path("backtest_cache")
        self.cache_dir.mkdir(exist_ok=True)
        
        # Test period
        self.test_days = 10
        self.end_date = datetime.now(ET).date()
        self.start_date = self.end_date - timedelta(days=self.test_days)
        
        # Liquid tickers
        self.tickers = [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
            "TSLA", "META", "AMD", "GOOGL", "AMZN",
            "NFLX", "INTC", "PLTR", "COIN", "SOFI"
        ]
        
        # Cache
        self.bars_cache = {}
        self.pdh_pdl_cache = {}
        
        print(f"Period: {self.start_date} to {self.end_date}")
        print(f"Tickers: {len(self.tickers)}")
        print(f"Cache: {self.cache_dir}")
        print("="*70)
        print()
    
    def load_bars_from_db(self, ticker: str, start_date=None, end_date=None) -> List[Dict]:
        """Load bars directly from database."""
        if start_date is None:
            start_date = self.start_date
        if end_date is None:
            end_date = self.end_date
            
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
            cur.execute(query, (ticker, start_date, end_date))
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
    
    def load_all_bars(self):
        """Pre-load all bars into memory."""
        print("⏳ Loading bars into memory...")
        total_bars = 0
        
        for ticker in self.tickers:
            bars = self.load_bars_from_db(ticker)
            
            if bars:
                self.bars_cache[ticker] = bars
                total_bars += len(bars)
                print(f"  ✅ {ticker}: {len(bars):,} bars")
            else:
                print(f"  ⚠️  {ticker}: No data")
        
        print(f"\n✅ Cached {len(self.bars_cache)} tickers with {total_bars:,} total bars\n")
    
    def load_pdh_pdl(self):
        """Load previous day high/low using date() SQL function."""
        print("⏳ Loading previous day OHLC data...")
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Try to find a previous trading day going back up to 10 days
        for days_back in range(1, 11):
            prev_date = self.start_date - timedelta(days=days_back)
            prev_date_str = prev_date.isoformat()
            
            found_any = False
            
            for ticker in self.tickers:
                if ticker not in self.bars_cache:
                    continue
                
                # Only process if we haven't found this ticker yet
                if ticker in self.pdh_pdl_cache:
                    continue
                
                # Query using date() function for proper comparison
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
                    print(f"  Error querying {ticker} for {prev_date}: {e}")
                    continue
            
            # If we found data for any ticker on this date, we're done
            if found_any:
                print(f"  Using prior day: {prev_date} ({prev_date.strftime('%A')})")
                print()
                for ticker in sorted(self.pdh_pdl_cache.keys()):
                    pdh = self.pdh_pdl_cache[ticker]["pdh"]
                    pdl = self.pdh_pdl_cache[ticker]["pdl"]
                    print(f"  ✅ {ticker:6} PDH: ${pdh:7.2f} PDL: ${pdl:7.2f}")
                break
        
        cur.close()
        conn.close()
        
        if not self.pdh_pdl_cache:
            print("  ⚠️ Warning: Could not load PDH/PDL for any ticker!")
        
        print()
    
    def generate_parameter_grid(self) -> List[Dict]:
        """
        Generate focused parameter grid with smart filtering.
        Target: ~1000 realistic combinations.
        """
        grid = []
        
        # FOCUSED RANGES - proven effective ranges
        volume_multipliers = [2.0, 3.0, 4.0, 5.0, 6.0]
        atr_stops = [1.5, 2.0, 2.5, 3.0, 4.0]
        risk_rewards = [2.0, 2.5, 3.0, 3.5, 4.0]
        lookbacks = [8, 10, 12, 16, 20]
        momentum_filters = ['none', 'weak', 'strong']
        trend_filters = ['none', 'aligned']
        time_filters = ['all', 'open', 'mid', 'power']
        
        for vol in volume_multipliers:
            for atr in atr_stops:
                for rr in risk_rewards:
                    # SMART FILTER 1: Skip extreme target distances
                    if atr * rr > 15:  # Max 15 ATR target
                        continue
                    
                    # SMART FILTER 2: High R:R needs wider stops
                    if rr >= 3.5 and atr < 2.0:
                        continue
                    
                    # SMART FILTER 3: High volume needs wider stops
                    if vol >= 5.0 and atr < 2.0:
                        continue
                    
                    # SMART FILTER 4: Limit lookback variations
                    # Test extremes (8, 12, 20) more than middle values
                    lookback_sample = [8, 12, 20] if vol >= 4.0 else lookbacks
                    
                    for lb in lookback_sample:
                        for momentum in momentum_filters:
                            for trend in trend_filters:
                                # SMART FILTER 5: Time filter sampling
                                # Test 'all' and 'open' for every combo
                                # Test 'mid' and 'power' only for high-volume setups
                                if vol >= 4.0:
                                    time_sample = time_filters
                                else:
                                    time_sample = ['all', 'open']
                                
                                for timefilter in time_sample:
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
        """Generate cache key."""
        return f"vol{params['volume_multiplier']}_atr{params['atr_stop_multiplier']}_rr{params['target_rr']}_lb{params['lookback']}_mom{params['momentum_filter']}_trend{params['trend_filter']}_time{params['time_filter']}"
    
    def load_cached_result(self, cache_key: str) -> Optional[Dict]:
        """Load cached result."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except:
                return None
        
        return None
    
    def save_cached_result(self, cache_key: str, result: Dict):
        """Save cached result."""
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
    
    def check_time_filter(self, dt: datetime, timefilter: str) -> bool:
        """Check time filter."""
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
        """Run backtest."""
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
                
                # ATR
                atr = self.calculate_atr(bars, i)
                if atr == 0:
                    continue
                
                # Momentum filter
                momentum = self.calculate_momentum(bars, i)
                
                if params["momentum_filter"] == 'weak':
                    if abs(momentum) < 0.002:
                        continue
                elif params["momentum_filter"] == 'strong':
                    if abs(momentum) < 0.005:
                        continue
                
                # LONG setup
                if self.detect_bos(bars, i, params["lookback"], "LONG"):
                    if pdh_pdl["pdh"] > 0 and current["close"] > pdh_pdl["pdh"]:
                        if params["trend_filter"] == 'aligned':
                            if momentum <= 0:
                                continue
                        
                        entry = current["close"]
                        stop = entry - (atr * params["atr_stop_multiplier"])
                        target = entry + (atr * params["atr_stop_multiplier"] * params["target_rr"])
                        
                        outcome = self.simulate_trade(bars, i+1, "LONG", entry, stop, target)
                        if outcome:
                            trades.append(outcome)
                
                # SHORT setup
                elif self.detect_bos(bars, i, params["lookback"], "SHORT"):
                    if pdh_pdl["pdl"] > 0 and current["close"] < pdh_pdl["pdl"]:
                        if params["trend_filter"] == 'aligned':
                            if momentum >= 0:
                                continue
                        
                        entry = current["close"]
                        stop = entry + (atr * params["atr_stop_multiplier"])
                        target = entry - (atr * params["atr_stop_multiplier"] * params["target_rr"])
                        
                        outcome = self.simulate_trade(bars, i+1, "SHORT", entry, stop, target)
                        if outcome:
                            trades.append(outcome)
        
        # Calculate metrics
        if not trades:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0
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
        """Simulate trade."""
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
        """Run optimization."""
        self.load_all_bars()
        self.load_pdh_pdl()
        
        print("="*70)
        print("BUILDING FOCUSED PARAMETER GRID")
        print("="*70)
        print()
        
        param_grid = self.generate_parameter_grid()
        print(f"✅ Generated {len(param_grid)} smart combinations")
        
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
            
            cached = self.load_cached_result(cache_key)
            if cached:
                result = cached
                status = "⚡ CACHED"
            else:
                result = self.backtest_parameters(params)
                self.save_cached_result(cache_key, result)
                status = "✅ TESTED"
            
            results.append({**params, **result})
            
            # Progress every 10
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
        
        # Save
        df = pd.DataFrame(results)
        df.to_csv("focused_optimization_results.csv", index=False)
        
        # Report
        self.generate_report(df)
    
    def generate_report(self, df: pd.DataFrame):
        """Generate report."""
        print("\n" + "="*70)
        print("OPTIMIZATION COMPLETE")
        print("="*70)
        print()
        
        quality = df[
            (df["trades"] >= 20) & 
            (df["trades"] <= 100) &
            (df["win_rate"] >= 45) &
            (df["profit_factor"] >= 1.5)
        ].copy()
        
        quality = quality.sort_values("profit_factor", ascending=False)
        
        print(f"📊 Total Configurations: {len(df)}")
        print(f"✅ Quality Setups: {len(quality)}")
        print()
        
        if len(quality) > 0:
            print("🏆 TOP 10 SETUPS:")
            print()
            
            for i, (idx, row) in enumerate(quality.head(10).iterrows(), 1):
                print(f"{i}. Vol={row['volume_multiplier']}x | "
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
            print("⚠️  No configurations met criteria")
            print("   Best by profit factor:")
            print()
            
            best = df.sort_values("profit_factor", ascending=False).head(10)
            for i, (idx, row) in enumerate(best.iterrows(), 1):
                print(f"{i}. Vol={row['volume_multiplier']}x | "
                      f"ATR={row['atr_stop_multiplier']}x | "
                      f"RR={row['target_rr']}R | "
                      f"LB={row['lookback']}")
                print(f"   Trades: {row['trades']:.0f} | "
                      f"WR: {row['win_rate']:.1f}% | "
                      f"PF: {row['profit_factor']:.2f}")
                print()
        
        print("="*70)
        print("✅ Results: focused_optimization_results.csv")
        print("="*70)
        print()


def main():
    optimizer = FocusedOptimizer()
    optimizer.run_optimization()


if __name__ == "__main__":
    main()
