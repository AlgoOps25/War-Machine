#!/usr/bin/env python3
"""
Advanced Multi-Timeframe Multi-Indicator Backtest - FINE-TUNED + VIX FILTER

High-quality signal detection using:
- BOS/FVG on 1-min (entry trigger)
- 5-min trend confirmation (EMA alignment)
- RSI momentum filter
- Volume surge confirmation (2.5x+)
- VIX > 15 filter (only trade in volatile markets)
- Wider ATR-based stops (3.0x)
- More achievable target (2.5R)
- Pullback entry confirmation
- Time-of-day filter (9:30-11:00 AM)

Goal: 40-60% win rate with 20-50 high-quality trades in volatile conditions
"""

import sys
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import pandas as pd
import numpy as np
import sqlite3

ET = ZoneInfo("America/New_York")

print("=" * 80)
print("ADVANCED MTF BACKTEST - FINE-TUNED + VIX FILTER")
print("=" * 80)
print()


class AdvancedMTFBacktest:
    """
    Multi-timeframe, multi-indicator backtest engine with VIX volatility filter.
    
    NEW: VIX > 15 filter ensures we only trade in volatile market conditions
    where BOS/FVG patterns are more reliable.
    """
    
    def __init__(self):
        self.db_path = "market_memory.db"
        
        # Test parameters
        self.test_days = 10
        self.end_date = datetime.now(ET).date()
        self.start_date = self.end_date - timedelta(days=self.test_days)
        
        # Liquid tickers
        self.tickers = [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
            "TSLA", "META", "AMD", "GOOGL", "AMZN"
        ]
        
        # FINE-TUNED PARAMETERS
        self.volume_multiplier = 2.5
        self.atr_stop_multiplier = 3.0
        self.target_rr = 2.5
        self.lookback = 12
        
        # RSI ranges
        self.rsi_long_min = 48
        self.rsi_long_max = 72
        self.rsi_short_min = 28
        self.rsi_short_max = 52
        
        # VIX filter (NEW)
        self.vix_threshold = 15.0
        
        # Time filter
        self.session_start = dtime(9, 30)
        self.session_end = dtime(11, 0)
        
        # VIX data cache
        self.vix_cache = {}
        
        print(f"Backtest Period: {self.start_date} to {self.end_date}")
        print(f"Database: {self.db_path}")
        print(f"Test Tickers: {len(self.tickers)}")
        print(f"Session: {self.session_start.strftime('%H:%M')} - {self.session_end.strftime('%H:%M')} ET")
        print()
        print("PARAMETERS:")
        print(f"  Volume Filter: {self.volume_multiplier}x average")
        print(f"  ATR Stop: {self.atr_stop_multiplier}x")
        print(f"  Target: {self.target_rr}R")
        print(f"  RSI Long: {self.rsi_long_min}-{self.rsi_long_max}")
        print(f"  RSI Short: {self.rsi_short_min}-{self.rsi_short_max}")
        print(f"  VIX Filter: > {self.vix_threshold} (NEW)")
        print(f"  Entry: With pullback confirmation")
        print()
    
    def load_vix_data(self) -> Dict[str, float]:
        """
        Load VIX data from database and create datetime -> vix mapping.
        VIX is stored as ticker '^VIX' in intraday_bars.
        """
        if self.vix_cache:
            return self.vix_cache
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        query = """
            SELECT datetime, close as vix
            FROM intraday_bars
            WHERE ticker = '^VIX'
              AND datetime >= ?
              AND datetime <= ?
            ORDER BY datetime ASC
        """
        
        try:
            cur.execute(query, (self.start_date, self.end_date))
            rows = cur.fetchall()
            
            for row in rows:
                dt = row["datetime"] if isinstance(row["datetime"], datetime) else datetime.fromisoformat(str(row["datetime"]))
                # Round to nearest minute for matching
                dt = dt.replace(second=0, microsecond=0)
                self.vix_cache[dt] = float(row["vix"])
            
            print(f"[VIX] Loaded {len(self.vix_cache)} VIX data points")
            
        except sqlite3.OperationalError:
            print("[VIX] Warning: No VIX data in database, filter disabled")
        except Exception as e:
            print(f"[VIX] Error loading VIX: {e}")
        
        cur.close()
        conn.close()
        return self.vix_cache
    
    def get_vix_at_time(self, dt: datetime) -> Optional[float]:
        """
        Get VIX value at specific datetime.
        Returns most recent VIX value within 5 minutes.
        """
        if not self.vix_cache:
            return None
        
        dt = dt.replace(second=0, microsecond=0)
        
        # Try exact match first
        if dt in self.vix_cache:
            return self.vix_cache[dt]
        
        # Find closest within 5 minutes
        for i in range(5):
            check_dt = dt - timedelta(minutes=i)
            if check_dt in self.vix_cache:
                return self.vix_cache[check_dt]
        
        return None
    
    def calculate_ema(self, bars: List[Dict], period: int) -> List[float]:
        """Calculate EMA from bars."""
        closes = [b["close"] for b in bars]
        ema = []
        multiplier = 2 / (period + 1)
        
        if len(closes) >= period:
            ema.append(sum(closes[:period]) / period)
            
            for i in range(period, len(closes)):
                ema_value = (closes[i] - ema[-1]) * multiplier + ema[-1]
                ema.append(ema_value)
        
        return ema
    
    def calculate_rsi(self, bars: List[Dict], period: int = 14) -> List[float]:
        """Calculate RSI from bars."""
        closes = [b["close"] for b in bars]
        if len(closes) < period + 1:
            return []
        
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [max(c, 0) for c in changes]
        losses = [abs(min(c, 0)) for c in changes]
        
        rsi_values = []
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))
        
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            if avg_loss == 0:
                rsi_values.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100 - (100 / (1 + rs)))
        
        return rsi_values
    
    def calculate_atr(self, bars: List[Dict], period: int = 14) -> List[float]:
        """Calculate ATR from bars."""
        if len(bars) < period + 1:
            return []
        
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i]["high"]
            low = bars[i]["low"]
            prev_close = bars[i-1]["close"]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        atr_values = []
        atr_values.append(sum(true_ranges[:period]) / period)
        
        for i in range(period, len(true_ranges)):
            atr = (atr_values[-1] * (period - 1) + true_ranges[i]) / period
            atr_values.append(atr)
        
        return atr_values
    
    def load_bars(self, ticker: str, timeframe: str = "1m") -> List[Dict]:
        """Load bars from database."""
        table = "intraday_bars" if timeframe == "1m" else "intraday_bars_5m"
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        query = f"""
            SELECT datetime, open, high, low, close, volume
            FROM {table}
            WHERE ticker = ?
              AND datetime >= ?
              AND datetime <= ?
            ORDER BY datetime ASC
        """
        
        try:
            cur.execute(query, (ticker, self.start_date, self.end_date))
            rows = cur.fetchall()
        except sqlite3.OperationalError as e:
            conn.close()
            return []
        
        bars = []
        for row in rows:
            bars.append({
                "datetime": row["datetime"] if isinstance(row["datetime"], datetime) else datetime.fromisoformat(str(row["datetime"])),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]) if row["volume"] else 0
            })
        
        cur.close()
        conn.close()
        return bars
    
    def materialize_5m_bars(self, bars_1m: List[Dict]) -> List[Dict]:
        """Create 5-min bars from 1-min bars (in-memory)."""
        if not bars_1m:
            return []
        
        from collections import defaultdict
        buckets = defaultdict(list)
        
        for bar in bars_1m:
            dt = bar["datetime"]
            minute_floor = (dt.minute // 5) * 5
            bucket_dt = dt.replace(minute=minute_floor, second=0, microsecond=0)
            buckets[bucket_dt].append(bar)
        
        bars_5m = []
        for bucket_dt in sorted(buckets):
            bucket = buckets[bucket_dt]
            bars_5m.append({
                "datetime": bucket_dt,
                "open": bucket[0]["open"],
                "high": max(b["high"] for b in bucket),
                "low": min(b["low"] for b in bucket),
                "close": bucket[-1]["close"],
                "volume": sum(b["volume"] for b in bucket),
                "ticker": bucket[0].get("ticker")
            })
        
        return bars_5m
    
    def check_pullback_entry(self, bars: List[Dict], idx: int, direction: str) -> bool:
        """Check if current bar shows pullback confirmation after BOS."""
        if idx < 3:
            return True
        
        current = bars[idx]
        prev_1 = bars[idx - 1]
        prev_2 = bars[idx - 2]
        
        if direction == "LONG":
            pullback_occurred = prev_1["close"] < prev_2["close"]
            resuming = current["close"] > prev_1["close"]
            return pullback_occurred and resuming
        
        else:  # SHORT
            rally_occurred = prev_1["close"] > prev_2["close"]
            resuming = current["close"] < prev_1["close"]
            return rally_occurred and resuming
    
    def detect_bos_fvg(self, bars_1m: List[Dict], bars_5m: List[Dict], idx: int) -> Optional[Dict]:
        """Detect BOS/FVG setup with multi-timeframe confirmation, pullback entry, and VIX filter."""
        if idx < self.lookback + 20:
            return None
        
        current_bar = bars_1m[idx]
        current_time = current_bar["datetime"].time()
        
        # Time filter
        if not (self.session_start <= current_time <= self.session_end):
            return None
        
        # VIX filter (NEW)
        vix = self.get_vix_at_time(current_bar["datetime"])
        if vix is None:
            # If no VIX data, allow trade (don't want to block everything)
            pass
        elif vix < self.vix_threshold:
            # VIX too low, skip this signal
            return None
        
        recent_1m = bars_1m[max(0, idx-50):idx+1]
        
        rsi_values = self.calculate_rsi(recent_1m, period=14)
        if not rsi_values:
            return None
        
        current_rsi = rsi_values[-1]
        
        atr_values = self.calculate_atr(recent_1m, period=14)
        if not atr_values:
            return None
        
        current_atr = atr_values[-1]
        
        recent_volumes = [b["volume"] for b in recent_1m[-20:]]
        avg_volume = sum(recent_volumes) / len(recent_volumes)
        volume_ratio = current_bar["volume"] / avg_volume if avg_volume > 0 else 0
        
        if volume_ratio < self.volume_multiplier:
            return None
        
        current_5m_bar = None
        for bar_5m in reversed(bars_5m):
            if bar_5m["datetime"] <= current_bar["datetime"]:
                current_5m_bar = bar_5m
                break
        
        if not current_5m_bar:
            return None
        
        try:
            idx_5m = bars_5m.index(current_5m_bar)
        except ValueError:
            return None
        
        if idx_5m < 50:
            return None
        
        recent_5m = bars_5m[max(0, idx_5m-50):idx_5m+1]
        
        ema_9 = self.calculate_ema(recent_5m, 9)
        ema_21 = self.calculate_ema(recent_5m, 21)
        ema_50 = self.calculate_ema(recent_5m, 50)
        
        if not ema_9 or not ema_21 or not ema_50:
            return None
        
        current_price = current_bar["close"]
        ticker = bars_1m[0].get("ticker", "UNKNOWN")
        
        # LONG setup
        if (
            current_rsi > self.rsi_long_min and current_rsi < self.rsi_long_max and
            current_price > ema_9[-1] and
            ema_9[-1] > ema_21[-1] and
            ema_21[-1] > ema_50[-1] and
            current_bar["close"] > current_bar["open"]
        ):
            recent_highs = [b["high"] for b in recent_1m[-self.lookback:-1]]
            if current_bar["high"] > max(recent_highs):
                if not self.check_pullback_entry(bars_1m, idx, "LONG"):
                    return None
                
                stop = current_bar["close"] - (current_atr * self.atr_stop_multiplier)
                target = current_bar["close"] + (current_atr * self.atr_stop_multiplier * self.target_rr)
                
                return {
                    "ticker": ticker,
                    "datetime": current_bar["datetime"],
                    "direction": "LONG",
                    "entry": current_bar["close"],
                    "stop": stop,
                    "target": target,
                    "rsi": current_rsi,
                    "volume_ratio": volume_ratio,
                    "atr": current_atr,
                    "vix": vix if vix else 0.0,
                    "timeframe_confirmation": "5m_ema_aligned",
                    "signal_type": "BOS_LONG_PULLBACK"
                }
        
        # SHORT setup
        if (
            current_rsi < self.rsi_short_max and current_rsi > self.rsi_short_min and
            current_price < ema_9[-1] and
            ema_9[-1] < ema_21[-1] and
            ema_21[-1] < ema_50[-1] and
            current_bar["close"] < current_bar["open"]
        ):
            recent_lows = [b["low"] for b in recent_1m[-self.lookback:-1]]
            if current_bar["low"] < min(recent_lows):
                if not self.check_pullback_entry(bars_1m, idx, "SHORT"):
                    return None
                
                stop = current_bar["close"] + (current_atr * self.atr_stop_multiplier)
                target = current_bar["close"] - (current_atr * self.atr_stop_multiplier * self.target_rr)
                
                return {
                    "ticker": ticker,
                    "datetime": current_bar["datetime"],
                    "direction": "SHORT",
                    "entry": current_bar["close"],
                    "stop": stop,
                    "target": target,
                    "rsi": current_rsi,
                    "volume_ratio": volume_ratio,
                    "atr": current_atr,
                    "vix": vix if vix else 0.0,
                    "timeframe_confirmation": "5m_ema_aligned",
                    "signal_type": "BOS_SHORT_PULLBACK"
                }
        
        return None
    
    def simulate_trade(self, signal: Dict, bars_1m: List[Dict]) -> Optional[Dict]:
        """Simulate trade execution."""
        entry_time = signal["datetime"]
        entry_price = signal["entry"]
        stop_loss = signal["stop"]
        target = signal["target"]
        direction = signal["direction"]
        
        entry_idx = None
        for i, bar in enumerate(bars_1m):
            if bar["datetime"] == entry_time:
                entry_idx = i
                break
        
        if entry_idx is None or entry_idx >= len(bars_1m) - 1:
            return None
        
        future_bars = bars_1m[entry_idx+1:min(entry_idx+31, len(bars_1m))]
        
        for i, bar in enumerate(future_bars, 1):
            if direction == "LONG":
                if bar["low"] <= stop_loss:
                    return {
                        "outcome": "LOSS",
                        "exit_price": stop_loss,
                        "exit_time": bar["datetime"],
                        "pnl": stop_loss - entry_price,
                        "pnl_pct": ((stop_loss - entry_price) / entry_price) * 100,
                        "bars_held": i,
                        "exit_reason": "stop"
                    }
                
                if bar["high"] >= target:
                    return {
                        "outcome": "WIN",
                        "exit_price": target,
                        "exit_time": bar["datetime"],
                        "pnl": target - entry_price,
                        "pnl_pct": ((target - entry_price) / entry_price) * 100,
                        "bars_held": i,
                        "exit_reason": "target"
                    }
            
            else:  # SHORT
                if bar["high"] >= stop_loss:
                    return {
                        "outcome": "LOSS",
                        "exit_price": stop_loss,
                        "exit_time": bar["datetime"],
                        "pnl": entry_price - stop_loss,
                        "pnl_pct": ((entry_price - stop_loss) / entry_price) * 100,
                        "bars_held": i,
                        "exit_reason": "stop"
                    }
                
                if bar["low"] <= target:
                    return {
                        "outcome": "WIN",
                        "exit_price": target,
                        "exit_time": bar["datetime"],
                        "pnl": entry_price - target,
                        "pnl_pct": ((entry_price - target) / entry_price) * 100,
                        "bars_held": i,
                        "exit_reason": "target"
                    }
        
        if future_bars:
            final_bar = future_bars[-1]
            exit_price = final_bar["close"]
            
            if direction == "LONG":
                pnl = exit_price - entry_price
            else:
                pnl = entry_price - exit_price
            
            return {
                "outcome": "WIN" if pnl > 0 else "LOSS",
                "exit_price": exit_price,
                "exit_time": final_bar["datetime"],
                "pnl": pnl,
                "pnl_pct": (pnl / entry_price) * 100,
                "bars_held": len(future_bars),
                "exit_reason": "timeout"
            }
        
        return None
    
    def run_backtest(self) -> List[Dict]:
        """Run complete backtest."""
        print("="*80)
        print("LOADING DATA")
        print("="*80)
        print()
        
        # Load VIX data first
        self.load_vix_data()
        print()
        
        all_trades = []
        
        for ticker in self.tickers:
            print(f"Processing {ticker}...", end=" ")
            
            bars_1m = self.load_bars(ticker, "1m")
            
            if len(bars_1m) < 100:
                print(f"Insufficient data ({len(bars_1m)} bars)")
                continue
            
            bars_5m = self.materialize_5m_bars(bars_1m)
            
            if len(bars_5m) < 50:
                print(f"Insufficient 5m bars ({len(bars_5m)})")
                continue
            
            for bar in bars_1m:
                bar["ticker"] = ticker
            for bar in bars_5m:
                bar["ticker"] = ticker
            
            signals = []
            for i in range(len(bars_1m)):
                signal = self.detect_bos_fvg(bars_1m, bars_5m, i)
                if signal:
                    signals.append(signal)
            
            ticker_trades = 0
            for signal in signals:
                result = self.simulate_trade(signal, bars_1m)
                if result:
                    trade = {**signal, **result}
                    all_trades.append(trade)
                    ticker_trades += 1
            
            print(f"{len(bars_1m)} bars → {len(signals)} signals → {ticker_trades} trades")
        
        print()
        return all_trades
    
    def generate_report(self, trades: List[Dict]):
        """Generate backtest report."""
        if not trades:
            print("❌ No trades found with current filters.")
            print("\nVIX filter may be too restrictive during this period.")
            print("Check VIX levels during test period.")
            return
        
        df = pd.DataFrame(trades)
        
        total_trades = len(trades)
        winners = df[df["outcome"] == "WIN"]
        losers = df[df["outcome"] == "LOSS"]
        
        win_rate = (len(winners) / total_trades) * 100
        avg_win = winners["pnl"].mean() if len(winners) > 0 else 0
        avg_loss = losers["pnl"].mean() if len(losers) > 0 else 0
        total_pnl = df["pnl"].sum()
        
        profit_factor = abs(winners["pnl"].sum() / losers["pnl"].sum()) if len(losers) > 0 and losers["pnl"].sum() != 0 else 0
        
        # VIX stats
        avg_vix = df["vix"].mean()
        
        print("="*80)
        print("ADVANCED MTF BACKTEST - WITH VIX FILTER")
        print("="*80)
        print()
        print(f"Total Trades: {total_trades}")
        print(f"Winners: {len(winners)} ({win_rate:.1f}%)")
        print(f"Losers: {len(losers)} ({100-win_rate:.1f}%)")
        print()
        print(f"Total P&L: ${total_pnl:.2f}")
        print(f"Avg Win: ${avg_win:.2f}")
        print(f"Avg Loss: ${avg_loss:.2f}")
        print(f"Profit Factor: {profit_factor:.2f}")
        print(f"Avg VIX: {avg_vix:.1f}")
        print()
        
        print("Exit Breakdown:")
        exit_counts = df["exit_reason"].value_counts()
        for reason, count in exit_counts.items():
            print(f"  {reason}: {count} ({count/total_trades*100:.1f}%)")
        print()
        
        # Compare to previous run
        print("IMPROVEMENT TRACKING:")
        print("  V1 (Original):     34 trades, 20.6% WR, -$9.44 P&L")
        print("  V2 (Fine-tuned):   17 trades, 35.3% WR, +$7.04 P&L")
        print(f"  V3 (VIX filter):   {total_trades} trades, {win_rate:.1f}% WR, ${total_pnl:.2f} P&L")
        print()
        
        df.to_csv("advanced_mtf_results_vix.csv", index=False)
        print("✅ Results saved to advanced_mtf_results_vix.csv")
        print()
        
        if len(winners) > 0:
            print("="*80)
            print("TOP 5 WINNING TRADES")
            print("="*80)
            top_winners = winners.nlargest(min(5, len(winners)), "pnl")
            for idx, trade in top_winners.iterrows():
                print(f"\n{trade['ticker']} {trade['direction']}:")
                print(f"  Entry: ${trade['entry']:.2f} → Exit: ${trade['exit_price']:.2f}")
                print(f"  P&L: ${trade['pnl']:.2f} ({trade['pnl_pct']:.2f}%)")
                print(f"  RSI: {trade['rsi']:.1f}, Volume: {trade['volume_ratio']:.1f}x, VIX: {trade['vix']:.1f}")
                print(f"  Exit: {trade['exit_reason']} after {trade['bars_held']} bars")
            print()


def main():
    backtest = AdvancedMTFBacktest()
    
    print("Starting FINE-TUNED backtest with VIX filter...")
    print()
    
    trades = backtest.run_backtest()
    
    backtest.generate_report(trades)


if __name__ == "__main__":
    main()
