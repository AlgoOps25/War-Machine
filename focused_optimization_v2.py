#!/usr/bin/env python3
"""
Focused Parameter Optimization V2 - With Market Regime Filters

NEW: VIX regime, SPY trend, and VWAP filters to trade only in favorable conditions.
SPEED OPTIMIZED: 5 core tickers + 2 regime combos = ~15 minute runtime
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
print("FOCUSED OPTIMIZATION V2 - WITH MARKET REGIME FILTERS")
print("SPEED OPTIMIZED: 5 Tickers + 2 Regime Combos = ~15min")
print("="*70)


class FocusedOptimizerV2:
    """
    Tests parameter combinations with market regime filtering.
    Only trades when market conditions favor breakout strategies.
    """
    
    def __init__(self):
        self.db_path = "market_memory.db"
        self.cache_dir = Path("backtest_cache_v2")
        self.cache_dir.mkdir(exist_ok=True)
        
        # Test period
        self.test_days = 30  # Extended to 30 days for better sample
        self.end_date = datetime.now(ET).date()
        self.start_date = self.end_date - timedelta(days=self.test_days)
        
        # SPEED OPTIMIZED: Top 5 most liquid tickers
        self.tickers = [
            "SPY",   # Market proxy (required for SPY trend filter)
            "QQQ",   # Tech/Nasdaq proxy
            "AAPL",  # Mega cap tech
            "NVDA",  # High volatility chip stock
            "TSLA"   # Extreme mover
        ]
        
        # Cache
        self.bars_cache = {}
        self.pdh_pdl_cache = {}
        self.vix_value = 0.0
        
        print(f"Period: {self.start_date} to {self.end_date} ({self.test_days} days)")
        print(f"Tickers: {len(self.tickers)} (SPEED OPTIMIZED)")
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
    
    def load_vix(self):
        """Load most recent VIX value."""
        print("⏳ Loading VIX regime...")
        
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        query = """
            SELECT close 
            FROM intraday_bars 
            WHERE ticker = '^VIX' 
            ORDER BY datetime DESC 
            LIMIT 1
        """
        
        try:
            cur.execute(query)
            row = cur.fetchone()
            
            if row:
                self.vix_value = float(row[0])
                
                # Determine regime
                if self.vix_value < 15:
                    regime = "LOW (calm, ranging)"
                elif self.vix_value < 20:
                    regime = "NORMAL (balanced)"
                elif self.vix_value < 30:
                    regime = "ELEVATED (trending)"
                else:
                    regime = "HIGH (panic)"
                
                print(f"  ✅ VIX: {self.vix_value:.2f} - {regime}")
            else:
                print("  ⚠️  VIX data not available - using default")
                self.vix_value = 18.0
        
        except Exception as e:
            print(f"  ⚠️  Error loading VIX: {e}")
            self.vix_value = 18.0
        
        finally:
            cur.close()
            conn.close()
        
        print()
    
    def generate_parameter_grid(self) -> List[Dict]:
        """
        Generate parameter grid with market regime filters.
        SPEED OPTIMIZED: 2 regime combos instead of 3.
        """
        grid = []
        
        # Core parameters
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
                    if atr * rr > 15:
                        continue
                    
                    # SMART FILTER 2: High R:R needs wider stops
                    if rr >= 3.5 and atr < 2.0:
                        continue
                    
                    # SMART FILTER 3: High volume needs wider stops
                    if vol >= 5.0 and atr < 2.0:
                        continue
                    
                    # SMART FILTER 4: Limit lookback variations
                    lookback_sample = [8, 12, 20] if vol >= 4.0 else lookbacks
                    
                    for lb in lookback_sample:
                        for momentum in momentum_filters:
                            for trend in trend_filters:
                                # SMART FILTER 5: Time filter sampling
                                if vol >= 4.0:
                                    time_sample = time_filters
                                else:
                                    time_sample = ['all', 'open']
                                
                                for timefilter in time_sample:
                                    # SPEED OPTIMIZED: Only 2 regime combinations
                                    # Test baseline vs full filtering
                                    
                                    regime_combinations = [
                                        ('any', False, False),     # Baseline: No regime filters
                                        ('elevated', True, True),  # Full filtering: VIX + SPY + VWAP
                                    ]
                                    
                                    for vix_regime, spy_filter, vwap_filter in regime_combinations:
                                        grid.append({
                                            "volume_multiplier": vol,
                                            "atr_stop_multiplier": atr,
                                            "target_rr": rr,
                                            "lookback": lb,
                                            "momentum_filter": momentum,
                                            "trend_filter": trend,
                                            "time_filter": timefilter,
                                            "vix_regime": vix_regime,
                                            "spy_trend_filter": spy_filter,
                                            "vwap_filter": vwap_filter
                                        })
        
        return grid
    
    def get_cache_key(self, params: Dict) -> str:
        """Generate cache key."""
        return (f"vol{params['volume_multiplier']}_"
                f"atr{params['atr_stop_multiplier']}_"
                f"rr{params['target_rr']}_"
                f"lb{params['lookback']}_"
                f"mom{params['momentum_filter']}_"
                f"trend{params['trend_filter']}_"
                f"time{params['time_filter']}_"
                f"vix{params['vix_regime']}_"
                f"spy{params['spy_trend_filter']}_"
                f"vwap{params['vwap_filter']}")
    
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
    
    def check_vix_regime(self, vix: float, regime: str) -> bool:
        """Check if VIX matches desired regime."""
        if regime == 'any':
            return True
        elif regime == 'low':
            return vix < 15
        elif regime == 'normal':
            return 15 <= vix < 20
        elif regime == 'elevated':
            return 20 <= vix < 30
        elif regime == 'high':
            return vix >= 30
        
        return False
    
    def calculate_ema(self, bars: List[Dict], period: int = 20) -> float:
        """Calculate EMA."""
        if len(bars) < period:
            return 0.0
        
        closes = [b["close"] for b in bars[-period:]]
        
        multiplier = 2 / (period + 1)
        ema = closes[0]
        
        for close in closes[1:]:
            ema = (close - ema) * multiplier + ema
        
        return ema
    
    def check_spy_trend(self, bars: List[Dict], idx: int, direction: str) -> bool:
        """Check if SPY trend aligns with trade direction."""
        if "SPY" not in self.bars_cache:
            return True
        
        spy_bars = self.bars_cache["SPY"]
        current_dt = bars[idx]["datetime"]
        
        # Find matching SPY bar
        spy_idx = None
        for i, spy_bar in enumerate(spy_bars):
            if spy_bar["datetime"] >= current_dt:
                spy_idx = i
                break
        
        if spy_idx is None or spy_idx < 20:
            return True
        
        # Calculate SPY 20-EMA
        spy_ema = self.calculate_ema(spy_bars[:spy_idx+1], period=20)
        spy_close = spy_bars[spy_idx]["close"]
        
        if direction == "LONG":
            return spy_close > spy_ema
        else:
            return spy_close < spy_ema
    
    def calculate_vwap(self, bars: List[Dict], idx: int) -> float:
        """Calculate VWAP from start of day."""
        current_dt = bars[idx]["datetime"]
        day_start = current_dt.replace(hour=9, minute=30, second=0)
        
        # Get all bars from market open to now
        day_bars = [b for b in bars[:idx+1] if b["datetime"] >= day_start]
        
        if not day_bars:
            return bars[idx]["close"]
        
        total_pv = sum(b["close"] * b["volume"] for b in day_bars)
        total_volume = sum(b["volume"] for b in day_bars)
        
        return total_pv / total_volume if total_volume > 0 else bars[idx]["close"]
    
    def check_vwap_alignment(self, bars: List[Dict], idx: int, direction: str) -> bool:
        """Check if price aligns with VWAP."""
        vwap = self.calculate_vwap(bars, idx)
        current_price = bars[idx]["close"]
        
        if direction == "LONG":
            return current_price > vwap
        else:
            return current_price < vwap
    
    def find_swing_high(self, bars: List[Dict], idx: int, swing_window: int = 3) -> bool:
        """Identify if current bar is a swing high."""
        if idx < swing_window or idx >= len(bars) - swing_window:
            return False
        
        current_high = bars[idx]["high"]
        
        for i in range(idx - swing_window, idx):
            if bars[i]["high"] >= current_high:
                return False
        
        for i in range(idx + 1, idx + swing_window + 1):
            if bars[i]["high"] >= current_high:
                return False
        
        return True
    
    def find_swing_low(self, bars: List[Dict], idx: int, swing_window: int = 3) -> bool:
        """Identify if current bar is a swing low."""
        if idx < swing_window or idx >= len(bars) - swing_window:
            return False
        
        current_low = bars[idx]["low"]
        
        for i in range(idx - swing_window, idx):
            if bars[i]["low"] <= current_low:
                return False
        
        for i in range(idx + 1, idx + swing_window + 1):
            if bars[i]["low"] <= current_low:
                return False
        
        return True
    
    def detect_bos(self, bars: List[Dict], idx: int, lookback: int, direction: str) -> bool:
        """Detect proper break of structure."""
        if idx < lookback + 10:
            return False
        
        current = bars[idx]
        search_window = bars[max(0, idx - lookback):idx]
        
        if direction == "LONG":
            last_swing_high = None
            
            for i in range(len(search_window) - 1, -1, -1):
                actual_idx = max(0, idx - lookback) + i
                
                if actual_idx > idx - 5:
                    continue
                
                if self.find_swing_high(bars, actual_idx, swing_window=2):
                    last_swing_high = bars[actual_idx]["high"]
                    break
            
            if last_swing_high is not None:
                return current["high"] > last_swing_high
            
            return False
        
        else:
            last_swing_low = None
            
            for i in range(len(search_window) - 1, -1, -1):
                actual_idx = max(0, idx - lookback) + i
                
                if actual_idx > idx - 5:
                    continue
                
                if self.find_swing_low(bars, actual_idx, swing_window=2):
                    last_swing_low = bars[actual_idx]["low"]
                    break
            
            if last_swing_low is not None:
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
        """Run backtest with regime filters."""
        # Check VIX regime first
        if not self.check_vix_regime(self.vix_value, params["vix_regime"]):
            return {
                "trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0
            }
        
        trades = []
        
        for ticker in self.tickers:
            if ticker not in self.bars_cache:
                continue
            
            bars = self.bars_cache[ticker]
            pdh_pdl = self.pdh_pdl_cache.get(ticker, {"pdh": 0, "pdl": 0})
            
            for i in range(params["lookback"] + 20, len(bars) - 5):
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
                        
                        # NEW: SPY trend filter
                        if params["spy_trend_filter"]:
                            if not self.check_spy_trend(bars, i, "LONG"):
                                continue
                        
                        # NEW: VWAP filter
                        if params["vwap_filter"]:
                            if not self.check_vwap_alignment(bars, i, "LONG"):
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
                        
                        # NEW: SPY trend filter
                        if params["spy_trend_filter"]:
                            if not self.check_spy_trend(bars, i, "SHORT"):
                                continue
                        
                        # NEW: VWAP filter
                        if params["vwap_filter"]:
                            if not self.check_vwap_alignment(bars, i, "SHORT"):
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
        self.load_vix()
        
        print("="*70)
        print("BUILDING PARAMETER GRID WITH REGIME FILTERS")
        print("="*70)
        print()
        
        param_grid = self.generate_parameter_grid()
        print(f"✅ Generated {len(param_grid)} combinations")
        print(f"   SPEED OPTIMIZED: 5 tickers + 2 regime combos")
        print(f"   Expected runtime: ~15 minutes")
        
        # Check cache
        cached_count = 0
        for params in param_grid:
            cache_key = self.get_cache_key(params)
            if self.load_cached_result(cache_key):
                cached_count += 1
        
        print(f"💾 Found {cached_count} cached results")
        print(f"\n🎯 TARGET: 25-75 quality trades @ 50-70% win rate")
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
                status = "✅ NEW"
            
            results.append({**params, **result})
            
            # Progress every 20
            if idx % 20 == 0 or idx == len(param_grid):
                elapsed = time_module.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                eta = (len(param_grid) - idx) / rate if rate > 0 else 0
                
                print(f"[{idx}/{len(param_grid)}] {status} | "
                      f"Vol={params['volume_multiplier']}x "
                      f"ATR={params['atr_stop_multiplier']} "
                      f"RR={params['target_rr']} | "
                      f"VIX={params['vix_regime']} "
                      f"SPY={params['spy_trend_filter']} "
                      f"VWAP={params['vwap_filter']} | "
                      f"Trades: {result['trades']} "
                      f"WR: {result['win_rate']:.1f}% "
                      f"PF: {result['profit_factor']:.2f} | "
                      f"ETA: {eta/60:.1f}m")
        
        # Save
        df = pd.DataFrame(results)
        df.to_csv("focused_optimization_v2_results.csv", index=False)
        
        # Report
        self.generate_report(df)
    
    def generate_report(self, df: pd.DataFrame):
        """Generate report."""
        print("\n" + "="*70)
        print("OPTIMIZATION V2 COMPLETE")
        print("="*70)
        print()
        
        quality = df[
            (df["trades"] >= 25) & 
            (df["trades"] <= 100) &
            (df["win_rate"] >= 50) &
            (df["profit_factor"] >= 1.8)
        ].copy()
        
        quality = quality.sort_values("profit_factor", ascending=False)
        
        print(f"📊 Total Configurations: {len(df)}")
        print(f"✅ Quality Setups (25-100 trades, 50%+ WR, 1.8+ PF): {len(quality)}")
        print()
        
        if len(quality) > 0:
            print("🏆 TOP 10 SETUPS:")
            print()
            
            for i, (idx, row) in enumerate(quality.head(10).iterrows(), 1):
                print(f"{i}. Vol={row['volume_multiplier']}x | "
                      f"ATR={row['atr_stop_multiplier']}x | "
                      f"RR={row['target_rr']}R | "
                      f"LB={row['lookback']} | "
                      f"VIX={row['vix_regime']} | "
                      f"SPY={row['spy_trend_filter']} | "
                      f"VWAP={row['vwap_filter']}")
                print(f"   Trades: {row['trades']:.0f} | "
                      f"WR: {row['win_rate']:.1f}% | "
                      f"PF: {row['profit_factor']:.2f} | "
                      f"P&L: ${row['total_pnl']:.2f}")
                print()
        else:
            print("⚠️  No configurations met strict criteria")
            print("   Showing best by profit factor (min 10 trades):")
            print()
            
            best = df[df["trades"] >= 10].sort_values("profit_factor", ascending=False).head(10)
            for i, (idx, row) in enumerate(best.iterrows(), 1):
                print(f"{i}. Vol={row['volume_multiplier']}x | "
                      f"ATR={row['atr_stop_multiplier']}x | "
                      f"RR={row['target_rr']}R | "
                      f"VIX={row['vix_regime']} | "
                      f"SPY={row['spy_trend_filter']}")
                print(f"   Trades: {row['trades']:.0f} | "
                      f"WR: {row['win_rate']:.1f}% | "
                      f"PF: {row['profit_factor']:.2f}")
                print()
        
        print("="*70)
        print("✅ Results: focused_optimization_v2_results.csv")
        print("="*70)
        print()


def main():
    optimizer = FocusedOptimizerV2()
    optimizer.run_optimization()


if __name__ == "__main__":
    main()
