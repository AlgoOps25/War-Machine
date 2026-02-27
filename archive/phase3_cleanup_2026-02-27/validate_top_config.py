#!/usr/bin/env python3
"""
Validate Top V2 Configuration

Tests the winning config from V2 optimization:
- Volume: 2.0x
- ATR Stop: 4.0x
- Target R:R: 2.5
- Lookback: 16
- Momentum: Weak (>0.2%)
- Time: Opening Range (9:30-10:00 AM)

Expected Results: 73% WR, 2.74 PF, ~1.2 trades/day
"""

import sys
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import sqlite3

ET = ZoneInfo("America/New_York")

print("\n" + "="*70)
print("TOP CONFIG VALIDATOR - V2 WINNER")
print("="*70)
print()


class TopConfigValidator:
    """
    Validates the top performing configuration from V2 optimization.
    """
    
    def __init__(self):
        self.db_path = "market_memory.db"
        
        # WINNING CONFIG from V2
        self.config = {
            "volume_multiplier": 2.0,
            "atr_stop_multiplier": 4.0,
            "target_rr": 2.5,
            "lookback": 16,
            "momentum_filter": "weak",  # >0.2% momentum
            "trend_filter": "none",
            "time_filter": "open",      # 9:30-10:00 AM only
        }
        
        # Test period (last 5 trading days for out-of-sample validation)
        self.test_days = 5
        self.end_date = datetime.now(ET).date()
        self.start_date = self.end_date - timedelta(days=7)  # 7 calendar days to get 5 trading days
        
        # Tickers (same as V2)
        self.tickers = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
        
        # Cache
        self.bars_cache = {}
        self.pdh_pdl_cache = {}
        
        print(f"Config: Vol={self.config['volume_multiplier']}x | "
              f"ATR={self.config['atr_stop_multiplier']}x | "
              f"RR={self.config['target_rr']}R | "
              f"LB={self.config['lookback']}")
        print(f"Momentum: {self.config['momentum_filter']} | "
              f"Time: {self.config['time_filter']} (9:30-10:00 AM)")
        print()
        print(f"Validation Period: {self.start_date} to {self.end_date} ({self.test_days} trading days)")
        print(f"Tickers: {', '.join(self.tickers)}")
        print("="*70)
        print()
    
    def load_bars_from_db(self, ticker: str, start_date=None, end_date=None) -> List[Dict]:
        """Load bars from database."""
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
        print("⏳ Loading validation data...")
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
    
    def load_pdh_pdl(self):
        """Load previous day high/low."""
        print("⏳ Loading PDH/PDL data...")
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Find previous trading day
        for days_back in range(1, 11):
            prev_date = self.start_date - timedelta(days=days_back)
            prev_date_str = prev_date.isoformat()
            
            found_any = False
            
            for ticker in self.tickers:
                if ticker not in self.bars_cache:
                    continue
                
                if ticker in self.pdh_pdl_cache:
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
                print(f"  Using prior day: {prev_date}")
                print()
                for ticker in sorted(self.pdh_pdl_cache.keys()):
                    pdh = self.pdh_pdl_cache[ticker]["pdh"]
                    pdl = self.pdh_pdl_cache[ticker]["pdl"]
                    print(f"  ✅ {ticker:6} PDH: ${pdh:7.2f} PDL: ${pdl:7.2f}")
                break
        
        cur.close()
        conn.close()
        print()
    
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
    
    def validate(self):
        """Run validation with winning config."""
        self.load_all_bars()
        self.load_pdh_pdl()
        
        print("="*70)
        print("RUNNING VALIDATION")
        print("="*70)
        print()
        
        trades = []
        
        for ticker in self.tickers:
            if ticker not in self.bars_cache:
                continue
            
            bars = self.bars_cache[ticker]
            pdh_pdl = self.pdh_pdl_cache.get(ticker, {"pdh": 0, "pdl": 0})
            
            for i in range(self.config["lookback"] + 20, len(bars) - 5):
                current = bars[i]
                
                # Time filter (CRITICAL: Opening range only)
                if not self.check_time_filter(current["datetime"]):
                    continue
                
                # Volume filter
                recent = bars[max(0, i-20):i]
                avg_volume = sum(b["volume"] for b in recent) / len(recent) if recent else 0
                
                if avg_volume == 0 or current["volume"] < avg_volume * self.config["volume_multiplier"]:
                    continue
                
                # ATR
                atr = self.calculate_atr(bars, i)
                if atr == 0:
                    continue
                
                # Momentum filter (weak = >0.2%)
                momentum = self.calculate_momentum(bars, i)
                
                if self.config["momentum_filter"] == "weak":
                    if abs(momentum) < 0.002:
                        continue
                
                # LONG setup
                if self.detect_bos(bars, i, self.config["lookback"], "LONG"):
                    if pdh_pdl["pdh"] > 0 and current["close"] > pdh_pdl["pdh"]:
                        entry = current["close"]
                        stop = entry - (atr * self.config["atr_stop_multiplier"])
                        target = entry + (atr * self.config["atr_stop_multiplier"] * self.config["target_rr"])
                        
                        outcome = self.simulate_trade(bars, i+1, "LONG", entry, stop, target)
                        if outcome:
                            trades.append({
                                "ticker": ticker,
                                "direction": "LONG",
                                "entry_time": current["datetime"],
                                "entry": entry,
                                "stop": stop,
                                "target": target,
                                "pnl": outcome["pnl"],
                                "bars_held": outcome["bars"],
                                "exit": outcome["exit"]
                            })
                
                # SHORT setup
                elif self.detect_bos(bars, i, self.config["lookback"], "SHORT"):
                    if pdh_pdl["pdl"] > 0 and current["close"] < pdh_pdl["pdl"]:
                        entry = current["close"]
                        stop = entry + (atr * self.config["atr_stop_multiplier"])
                        target = entry - (atr * self.config["atr_stop_multiplier"] * self.config["target_rr"])
                        
                        outcome = self.simulate_trade(bars, i+1, "SHORT", entry, stop, target)
                        if outcome:
                            trades.append({
                                "ticker": ticker,
                                "direction": "SHORT",
                                "entry_time": current["datetime"],
                                "entry": entry,
                                "stop": stop,
                                "target": target,
                                "pnl": outcome["pnl"],
                                "bars_held": outcome["bars"],
                                "exit": outcome["exit"]
                            })
        
        # Generate report
        self.generate_report(trades)
    
    def generate_report(self, trades: List[Dict]):
        """Generate validation report."""
        print("\n" + "="*70)
        print("VALIDATION RESULTS")
        print("="*70)
        print()
        
        if not trades:
            print("❌ No trades generated with this config")
            print("   Possible reasons:")
            print("   - Not enough data in validation period")
            print("   - Opening range filter too restrictive")
            print("   - No BOS signals detected")
            return
        
        winners = [t for t in trades if t["pnl"] > 0]
        losers = [t for t in trades if t["pnl"] <= 0]
        
        total_pnl = sum(t["pnl"] for t in trades)
        win_rate = len(winners) / len(trades) * 100 if trades else 0
        
        total_wins = sum(t["pnl"] for t in winners) if winners else 0
        total_losses = abs(sum(t["pnl"] for t in losers)) if losers else 0
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        avg_win = sum(t["pnl"] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t["pnl"] for t in losers) / len(losers) if losers else 0
        
        print(f"📊 PERFORMANCE METRICS")
        print(f"   Total Trades: {len(trades)}")
        print(f"   Winners: {len(winners)} | Losers: {len(losers)}")
        print(f"   Win Rate: {win_rate:.1f}%")
        print(f"   Profit Factor: {profit_factor:.2f}")
        print(f"   Total P&L: ${total_pnl:.2f}")
        print(f"   Avg Win: ${avg_win:.2f}")
        print(f"   Avg Loss: ${avg_loss:.2f}")
        print()
        
        # Compare to V2 expectations
        print(f"📈 COMPARISON TO V2 BACKTEST")
        print(f"   Expected WR: 73.0% | Actual: {win_rate:.1f}% | Delta: {win_rate - 73.0:+.1f}%")
        print(f"   Expected PF: 2.74 | Actual: {profit_factor:.2f} | Delta: {profit_factor - 2.74:+.2f}")
        print()
        
        if win_rate >= 65 and profit_factor >= 2.0:
            print("✅ VALIDATION PASSED - Config performs well out-of-sample!")
        elif win_rate >= 55 and profit_factor >= 1.5:
            print("⚠️  VALIDATION MARGINAL - Config works but degraded slightly")
        else:
            print("❌ VALIDATION FAILED - Config may be overfit to training data")
        
        print()
        print("="*70)
        print("TRADE LOG")
        print("="*70)
        print()
        
        for i, trade in enumerate(trades, 1):
            result = "WIN" if trade["pnl"] > 0 else "LOSS"
            emoji = "✅" if trade["pnl"] > 0 else "❌"
            
            print(f"{emoji} Trade {i}: {trade['ticker']} {trade['direction']}")
            print(f"   Entry: {trade['entry_time'].strftime('%Y-%m-%d %H:%M')}")
            print(f"   Entry: ${trade['entry']:.2f} | Stop: ${trade['stop']:.2f} | Target: ${trade['target']:.2f}")
            print(f"   P&L: ${trade['pnl']:.2f} | Exit: {trade['exit']} | Bars: {trade['bars_held']}")
            print()
        
        print("="*70)
        print()


def main():
    validator = TopConfigValidator()
    validator.validate()


if __name__ == "__main__":
    main()
