#!/usr/bin/env python3
"""
Filter Effectiveness Tester

Tests individual filters against baseline to determine which (if any) improve performance.

Baseline Config (V2 Winner):
- Volume: 2.0x
- ATR Stop: 4.0x
- Target R:R: 2.5
- Lookback: 16
- Momentum: Weak (>0.2%)
- Time: Opening Range (9:30-10:00 AM)
- NO additional filters

Tests each filter individually to measure impact on:
- Trade count
- Win rate
- Profit factor
- Total P&L
"""

import sys
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional, Tuple
import sqlite3
import pandas as pd

ET = ZoneInfo("America/New_York")

print("\n" + "="*70)
print("FILTER EFFECTIVENESS TESTER")
print("="*70)
print()


class FilterEffectivenessTester:
    """
    Tests individual filters against baseline to measure effectiveness.
    """
    
    def __init__(self):
        self.db_path = "market_memory.db"
        
        # BASELINE CONFIG (V2 Winner - NO filters except built-ins)
        self.base_config = {
            "volume_multiplier": 2.0,
            "atr_stop_multiplier": 4.0,
            "target_rr": 2.5,
            "lookback": 16,
            "momentum_threshold": 0.002,  # 0.2% (built-in)
            "time_filter": "open",  # 9:30-10:00 AM (built-in)
        }
        
        # Test period (same as V2 - 30 days)
        self.end_date = datetime(2026, 2, 27, tzinfo=ET).date()
        self.start_date = self.end_date - timedelta(days=30)
        
        # Tickers
        self.tickers = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
        
        # Cache
        self.bars_cache = {}
        self.pdh_pdl_cache = {}
        
        print(f"Baseline Config: Vol={self.base_config['volume_multiplier']}x | "
              f"ATR={self.base_config['atr_stop_multiplier']}x | "
              f"RR={self.base_config['target_rr']}R | "
              f"LB={self.base_config['lookback']}")
        print(f"Built-in Filters: Momentum={self.base_config['momentum_threshold']*100:.1f}% | "
              f"Time={self.base_config['time_filter']} (9:30-10:00 AM)")
        print()
        print(f"Test Period: {self.start_date} to {self.end_date} (30 days)")
        print(f"Tickers: {', '.join(self.tickers)}")
        print("="*70)
        print()
    
    def load_bars_from_db(self, ticker: str) -> List[Dict]:
        """Load bars from database."""
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
    
    def load_all_data(self):
        """Load all bars and PDH/PDL data."""
        print("⏳ Loading test data...")
        total_bars = 0
        
        for ticker in self.tickers:
            bars = self.load_bars_from_db(ticker)
            
            if bars:
                self.bars_cache[ticker] = bars
                total_bars += len(bars)
                print(f"  ✅ {ticker}: {len(bars):,} bars")
            else:
                print(f"  ⚠️  {ticker}: No data")
        
        print(f"\n✅ Loaded {len(self.bars_cache)} tickers with {total_bars:,} total bars\n")
        
        # Load PDH/PDL
        self.load_pdh_pdl()
    
    def load_pdh_pdl(self):
        """Load previous day high/low."""
        print("⏳ Loading PDH/PDL data...")
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Find previous trading day before start
        for days_back in range(1, 11):
            prev_date = self.start_date - timedelta(days=days_back)
            prev_date_str = prev_date.isoformat()
            
            found_any = False
            
            for ticker in self.tickers:
                if ticker not in self.bars_cache:
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
    
    def find_swing_high(self, bars: List[Dict], idx: int, swing_window: int = 3) -> bool:
        """Identify swing high."""
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
        """Identify swing low."""
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
        """Detect break of structure."""
        if idx < lookback + 10:
            return False
        
        current = bars[idx]
        
        if direction == "LONG":
            last_swing_high = None
            
            for i in range(idx - lookback, idx - 5):
                if self.find_swing_high(bars, i, swing_window=2):
                    last_swing_high = bars[i]["high"]
                    break
            
            if last_swing_high is not None:
                return current["high"] > last_swing_high
            
            return False
        
        else:
            last_swing_low = None
            
            for i in range(idx - lookback, idx - 5):
                if self.find_swing_low(bars, i, swing_window=2):
                    last_swing_low = bars[i]["low"]
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
    
    def calculate_rsi(self, bars: List[Dict], idx: int, period: int = 14) -> float:
        """Calculate RSI."""
        if idx < period:
            return 50.0
        
        recent = bars[idx-period:idx+1]
        
        gains = []
        losses = []
        
        for i in range(1, len(recent)):
            change = recent[i]["close"] - recent[i-1]["close"]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
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
    
    def check_gap_size_filter(self, bars: List[Dict], idx: int, min_gap_pct: float = 0.5) -> bool:
        """Gap size filter: Require minimum gap %."""
        if idx < 1:
            return True
        
        current_day = bars[idx]["datetime"].date()
        
        # Find market open bar
        open_bar = None
        prev_close = None
        
        for i in range(idx, max(0, idx-10), -1):
            bar_date = bars[i]["datetime"].date()
            bar_time = bars[i]["datetime"].time()
            
            if bar_date == current_day and bar_time == dtime(9, 30):
                open_bar = bars[i]
            elif bar_date < current_day:
                prev_close = bars[i]["close"]
                break
        
        if open_bar is None or prev_close is None:
            return True
        
        gap_pct = abs((open_bar["open"] - prev_close) / prev_close * 100)
        return gap_pct >= min_gap_pct
    
    def check_rsi_regime_filter(self, bars: List[Dict], idx: int,
                                min_rsi: float = 30, max_rsi: float = 70) -> bool:
        """RSI regime filter: Trade only in neutral zone."""
        rsi = self.calculate_rsi(bars, idx)
        return min_rsi <= rsi <= max_rsi
    
    def check_day_of_week_filter(self, dt: datetime, excluded_days: List[int]) -> bool:
        """Day of week filter: Exclude specific days."""
        return dt.weekday() not in excluded_days
    
    def run_backtest(self, filter_name: str = "BASELINE", filter_func=None) -> Dict:
        """Run backtest with optional filter."""
        trades = []
        
        for ticker in self.tickers:
            if ticker not in self.bars_cache:
                continue
            
            bars = self.bars_cache[ticker]
            pdh_pdl = self.pdh_pdl_cache.get(ticker, {"pdh": 0, "pdl": 0})
            
            for i in range(self.base_config["lookback"] + 20, len(bars) - 5):
                current = bars[i]
                
                # Built-in time filter (Opening range)
                if not self.check_time_filter(current["datetime"]):
                    continue
                
                # Apply additional filter if provided
                if filter_func is not None:
                    if not filter_func(bars, i, current):
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
                
                # Built-in momentum filter
                momentum = self.calculate_momentum(bars, i)
                
                if abs(momentum) < self.base_config["momentum_threshold"]:
                    continue
                
                # LONG setup
                if self.detect_bos(bars, i, self.base_config["lookback"], "LONG"):
                    if pdh_pdl["pdh"] > 0 and current["close"] > pdh_pdl["pdh"]:
                        entry = current["close"]
                        stop = entry - (atr * self.base_config["atr_stop_multiplier"])
                        target = entry + (atr * self.base_config["atr_stop_multiplier"] * self.base_config["target_rr"])
                        
                        outcome = self.simulate_trade(bars, i+1, "LONG", entry, stop, target)
                        if outcome:
                            trades.append({"pnl": outcome["pnl"], "direction": "LONG"})
                
                # SHORT setup
                elif self.detect_bos(bars, i, self.base_config["lookback"], "SHORT"):
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
                "filter_name": filter_name,
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
            "filter_name": filter_name,
            "trades": len(trades),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss
        }
    
    def test_all_filters(self) -> List[Dict]:
        """Test all filters individually."""
        print("="*70)
        print("RUNNING FILTER TESTS")
        print("="*70)
        print()
        
        results = []
        
        # 1. BASELINE (no additional filters)
        print("[1/6] Testing BASELINE (no additional filters)...")
        baseline = self.run_backtest("BASELINE", filter_func=None)
        results.append(baseline)
        
        # 2. GAP SIZE FILTER (>0.5%)
        print("[2/6] Testing Gap Size Filter (>0.5%)...")
        gap_filter = lambda bars, idx, current: self.check_gap_size_filter(bars, idx, min_gap_pct=0.5)
        gap_result = self.run_backtest("Gap Size (>0.5%)", filter_func=gap_filter)
        results.append(gap_result)
        
        # 3. GAP SIZE FILTER (>1.0%)
        print("[3/6] Testing Gap Size Filter (>1.0%)...")
        gap_filter_strict = lambda bars, idx, current: self.check_gap_size_filter(bars, idx, min_gap_pct=1.0)
        gap_result_strict = self.run_backtest("Gap Size (>1.0%)", filter_func=gap_filter_strict)
        results.append(gap_result_strict)
        
        # 4. RSI REGIME (30-70)
        print("[4/6] Testing RSI Regime Filter (30-70)...")
        rsi_filter = lambda bars, idx, current: self.check_rsi_regime_filter(bars, idx, min_rsi=30, max_rsi=70)
        rsi_result = self.run_backtest("RSI Regime (30-70)", filter_func=rsi_filter)
        results.append(rsi_result)
        
        # 5. RSI REGIME (40-60) - More strict
        print("[5/6] Testing RSI Regime Filter (40-60)...")
        rsi_filter_strict = lambda bars, idx, current: self.check_rsi_regime_filter(bars, idx, min_rsi=40, max_rsi=60)
        rsi_result_strict = self.run_backtest("RSI Regime (40-60)", filter_func=rsi_filter_strict)
        results.append(rsi_result_strict)
        
        # 6. DAY OF WEEK (Exclude Monday)
        print("[6/6] Testing Day of Week Filter (No Monday)...")
        dow_filter = lambda bars, idx, current: self.check_day_of_week_filter(current["datetime"], excluded_days=[0])
        dow_result = self.run_backtest("No Monday", filter_func=dow_filter)
        results.append(dow_result)
        
        print()
        return results
    
    def generate_report(self, results: List[Dict]):
        """Generate comparison report."""
        baseline = results[0]
        
        print("\n" + "="*70)
        print("FILTER EFFECTIVENESS REPORT")
        print("="*70)
        print()
        
        print(f"📊 BASELINE (No Additional Filters)")
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
            
            # Determine if better or worse
            if result['trades'] < 10:
                verdict = "⚠️  TOO FEW TRADES"
            elif result['win_rate'] > baseline['win_rate'] and result['profit_factor'] > baseline['profit_factor']:
                verdict = "✅ BETTER"
            elif result['win_rate'] < baseline['win_rate'] - 5 or result['profit_factor'] < baseline['profit_factor'] - 0.3:
                verdict = "❌ WORSE"
            else:
                verdict = "⚪ NEUTRAL"
            
            print(f"🔍 {result['filter_name']}")
            print(f"   Trades: {result['trades']} ({trade_delta:+d}, {trade_delta_pct:+.0f}%)")
            print(f"   Win Rate: {result['win_rate']:.1f}% ({wr_delta:+.1f}%)")
            print(f"   Profit Factor: {result['profit_factor']:.2f} ({pf_delta:+.2f})")
            print(f"   Total P&L: ${result['total_pnl']:.2f} (${pnl_delta:+.2f})")
            print(f"   Verdict: {verdict}")
            print()
        
        print("="*70)
        print()
        
        # Summary
        better_filters = [r for r in results[1:] if r['win_rate'] > baseline['win_rate'] and r['profit_factor'] > baseline['profit_factor'] and r['trades'] >= 10]
        
        if better_filters:
            print("✅ FILTERS THAT IMPROVED PERFORMANCE:")
            for f in better_filters:
                print(f"   • {f['filter_name']}: {f['win_rate']:.1f}% WR, {f['profit_factor']:.2f} PF")
        else:
            print("❌ NO FILTERS IMPROVED PERFORMANCE")
            print("   Recommendation: Use BASELINE config (no additional filters)")
        
        print()
        print("="*70)
        print()


def main():
    tester = FilterEffectivenessTester()
    tester.load_all_data()
    results = tester.test_all_filters()
    tester.generate_report(results)


if __name__ == "__main__":
    main()
