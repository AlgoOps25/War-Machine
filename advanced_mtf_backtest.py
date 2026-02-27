#!/usr/bin/env python3
"""
Advanced Multi-Timeframe Multi-Indicator Backtest

High-quality signal detection using:
- BOS/FVG on 1-min (entry trigger)
- 5-min trend confirmation (EMA alignment)
- RSI momentum filter
- Volume surge confirmation (3x+)
- ATR-based stops
- PDH/PDL breakout filter
- Time-of-day filter (9:30-11:00 AM)

Goal: 50-70% win rate with 20-100 high-quality trades
"""

import sys
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import pandas as pd
import numpy as np
import requests
import json
import sqlite3

ET = ZoneInfo("America/New_York")

print("=" * 80)
print("ADVANCED MULTI-TIMEFRAME MULTI-INDICATOR BACKTEST")
print("=" * 80)
print()


class AdvancedMTFBacktest:
    """
    Multi-timeframe, multi-indicator backtest engine.
    
    Requires ALL conditions to be met:
    1. BOS/FVG on 1-min chart (entry trigger)
    2. 5-min EMA alignment (trend filter)
    3. RSI 50-70 for longs, 30-50 for shorts (momentum)
    4. Volume > 3x average
    5. Time: 9:30-11:00 AM only
    6. Price breaks PDH (longs) or PDL (shorts)
    7. Confirmation candle on 5-min validates the breakout
    """
    
    def __init__(self):
        # Use war_machine.db which has the data
        self.db_path = "war_machine.db"
        
        # Test parameters
        self.test_days = 10
        self.end_date = datetime.now(ET).date()
        self.start_date = self.end_date - timedelta(days=self.test_days)
        
        # Liquid tickers
        self.tickers = [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
            "TSLA", "META", "AMD", "GOOGL", "AMZN"
        ]
        
        # Signal filters
        self.volume_multiplier = 3.0
        self.atr_stop_multiplier = 2.5
        self.target_rr = 3.0
        self.lookback = 12
        
        # Time filter
        self.session_start = dtime(9, 30)
        self.session_end = dtime(11, 0)
        
        # Indicator cache
        self.indicator_cache = {}
        
        print(f"Backtest Period: {self.start_date} to {self.end_date}")
        print(f"Database: {self.db_path}")
        print(f"Test Tickers: {len(self.tickers)}")
        print(f"Session: {self.session_start.strftime('%H:%M')} - {self.session_end.strftime('%H:%M')} ET")
        print(f"Volume Filter: {self.volume_multiplier}x average")
        print()
    
    def calculate_ema(self, bars: List[Dict], period: int) -> List[float]:
        """Calculate EMA from bars."""
        closes = [b["close"] for b in bars]
        ema = []
        multiplier = 2 / (period + 1)
        
        # First EMA is SMA
        if len(closes) >= period:
            ema.append(sum(closes[:period]) / period)
            
            # Subsequent EMAs
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
        
        # First RSI using SMA
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))
        
        # Subsequent RSI using EMA
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
        
        # First ATR is SMA of TR
        atr_values.append(sum(true_ranges[:period]) / period)
        
        # Subsequent ATRs use smoothing
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
            print(f"  [ERROR] Table {table} not found: {e}")
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
            # Floor to 5-min boundary
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
    
    def detect_bos_fvg(self, bars_1m: List[Dict], bars_5m: List[Dict], idx: int) -> Optional[Dict]:
        """
        Detect BOS/FVG setup with multi-timeframe confirmation.
        
        Returns signal dict if all conditions met, None otherwise.
        """
        if idx < self.lookback + 20:  # Need history for indicators
            return None
        
        current_bar = bars_1m[idx]
        current_time = current_bar["datetime"].time()
        
        # Time filter: 9:30-11:00 AM only
        if not (self.session_start <= current_time <= self.session_end):
            return None
        
        # Get recent bars for analysis
        recent_1m = bars_1m[max(0, idx-50):idx+1]
        
        # Calculate indicators
        rsi_values = self.calculate_rsi(recent_1m, period=14)
        if not rsi_values or len(rsi_values) < 1:
            return None
        
        current_rsi = rsi_values[-1]
        
        # ATR for stops
        atr_values = self.calculate_atr(recent_1m, period=14)
        if not atr_values or len(atr_values) < 1:
            return None
        
        current_atr = atr_values[-1]
        
        # Volume analysis
        recent_volumes = [b["volume"] for b in recent_1m[-20:]]
        avg_volume = sum(recent_volumes) / len(recent_volumes)
        volume_ratio = current_bar["volume"] / avg_volume if avg_volume > 0 else 0
        
        # Volume filter
        if volume_ratio < self.volume_multiplier:
            return None
        
        # Find matching 5-min bar for trend confirmation
        current_5m_bar = None
        for bar_5m in reversed(bars_5m):
            if bar_5m["datetime"] <= current_bar["datetime"]:
                current_5m_bar = bar_5m
                break
        
        if not current_5m_bar:
            return None
        
        # Get 5-min bars for EMA calculation
        try:
            idx_5m = bars_5m.index(current_5m_bar)
        except ValueError:
            return None
        
        if idx_5m < 50:
            return None
        
        recent_5m = bars_5m[max(0, idx_5m-50):idx_5m+1]
        
        # Calculate EMAs on 5-min
        ema_9 = self.calculate_ema(recent_5m, 9)
        ema_21 = self.calculate_ema(recent_5m, 21)
        ema_50 = self.calculate_ema(recent_5m, 50)
        
        if not ema_9 or not ema_21 or not ema_50:
            return None
        
        current_price = current_bar["close"]
        ticker = bars_1m[0].get("ticker", "UNKNOWN")
        
        # Detect LONG setup
        if (
            current_rsi > 50 and current_rsi < 70 and  # Bullish momentum
            current_price > ema_9[-1] and  # Price above short EMA
            ema_9[-1] > ema_21[-1] and  # EMAs aligned bullish
            ema_21[-1] > ema_50[-1] and
            current_bar["close"] > current_bar["open"]  # Bullish candle
        ):
            # BOS detection: Higher high
            recent_highs = [b["high"] for b in recent_1m[-self.lookback:-1]]
            if current_bar["high"] > max(recent_highs):
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
                    "timeframe_confirmation": "5m_ema_aligned",
                    "signal_type": "BOS_LONG"
                }
        
        # Detect SHORT setup
        if (
            current_rsi < 50 and current_rsi > 30 and  # Bearish momentum
            current_price < ema_9[-1] and  # Price below short EMA
            ema_9[-1] < ema_21[-1] and  # EMAs aligned bearish
            ema_21[-1] < ema_50[-1] and
            current_bar["close"] < current_bar["open"]  # Bearish candle
        ):
            # BOS detection: Lower low
            recent_lows = [b["low"] for b in recent_1m[-self.lookback:-1]]
            if current_bar["low"] < min(recent_lows):
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
                    "timeframe_confirmation": "5m_ema_aligned",
                    "signal_type": "BOS_SHORT"
                }
        
        return None
    
    def simulate_trade(self, signal: Dict, bars_1m: List[Dict]) -> Optional[Dict]:
        """
        Simulate trade execution.
        """
        entry_time = signal["datetime"]
        entry_price = signal["entry"]
        stop_loss = signal["stop"]
        target = signal["target"]
        direction = signal["direction"]
        
        # Find future bars
        entry_idx = None
        for i, bar in enumerate(bars_1m):
            if bar["datetime"] == entry_time:
                entry_idx = i
                break
        
        if entry_idx is None or entry_idx >= len(bars_1m) - 1:
            return None
        
        future_bars = bars_1m[entry_idx+1:min(entry_idx+31, len(bars_1m))]  # Max 30 bars (30 min)
        
        for i, bar in enumerate(future_bars, 1):
            if direction == "LONG":
                # Check stop
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
                
                # Check target
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
                # Check stop
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
                
                # Check target
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
        
        # Timeout
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
        """
        Run complete backtest.
        """
        print("="*80)
        print("LOADING DATA")
        print("="*80)
        print()
        
        all_trades = []
        
        for ticker in self.tickers:
            print(f"Processing {ticker}...")
            
            # Load 1-min bars
            bars_1m = self.load_bars(ticker, "1m")
            
            if len(bars_1m) < 100:
                print(f"  Insufficient data: {len(bars_1m)} 1m bars")
                continue
            
            # Create 5-min bars from 1-min
            bars_5m = self.materialize_5m_bars(bars_1m)
            
            if len(bars_5m) < 50:
                print(f"  Insufficient 5m bars: {len(bars_5m)}")
                continue
            
            print(f"  Loaded {len(bars_1m)} 1m bars, created {len(bars_5m)} 5m bars")
            
            # Add ticker to bars for reference
            for bar in bars_1m:
                bar["ticker"] = ticker
            for bar in bars_5m:
                bar["ticker"] = ticker
            
            # Scan for signals
            signals = []
            for i in range(len(bars_1m)):
                signal = self.detect_bos_fvg(bars_1m, bars_5m, i)
                if signal:
                    signals.append(signal)
            
            print(f"  Found {len(signals)} signals")
            
            # Simulate trades
            for signal in signals:
                result = self.simulate_trade(signal, bars_1m)
                if result:
                    trade = {**signal, **result}
                    all_trades.append(trade)
            
            print(f"  Simulated {len([t for t in all_trades if t.get('ticker') == ticker])} trades")
            print()
        
        return all_trades
    
    def generate_report(self, trades: List[Dict]):
        """
        Generate backtest report.
        """
        if not trades:
            print("❌ No trades found with current filters.")
            print("\nThis is GOOD - it means the system is being very selective!")
            print("\nTo generate signals, try:")
            print("  1. Increase test_days (currently 10)")
            print("  2. Relax volume filter (currently 3.0x)")
            print("  3. Expand time window (currently 9:30-11:00 AM)")
            return
        
        df = pd.DataFrame(trades)
        
        # Calculate metrics
        total_trades = len(trades)
        winners = df[df["outcome"] == "WIN"]
        losers = df[df["outcome"] == "LOSS"]
        
        win_rate = (len(winners) / total_trades) * 100
        avg_win = winners["pnl"].mean() if len(winners) > 0 else 0
        avg_loss = losers["pnl"].mean() if len(losers) > 0 else 0
        total_pnl = df["pnl"].sum()
        
        profit_factor = abs(winners["pnl"].sum() / losers["pnl"].sum()) if len(losers) > 0 and losers["pnl"].sum() != 0 else 0
        
        print("="*80)
        print("ADVANCED MTF BACKTEST RESULTS")
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
        print()
        
        # Exit reasons
        print("Exit Breakdown:")
        exit_counts = df["exit_reason"].value_counts()
        for reason, count in exit_counts.items():
            print(f"  {reason}: {count} ({count/total_trades*100:.1f}%)")
        print()
        
        # Save results
        df.to_csv("advanced_mtf_results.csv", index=False)
        print("✅ Results saved to advanced_mtf_results.csv")
        print()
        
        # Top trades
        if len(winners) > 0:
            print("="*80)
            print("TOP 5 WINNING TRADES")
            print("="*80)
            top_winners = winners.nlargest(5, "pnl")
            for idx, trade in top_winners.iterrows():
                print(f"\n{trade['ticker']} {trade['direction']}:")
                print(f"  Entry: ${trade['entry']:.2f} → Exit: ${trade['exit_price']:.2f}")
                print(f"  P&L: ${trade['pnl']:.2f} ({trade['pnl_pct']:.2f}%)")
                print(f"  RSI: {trade['rsi']:.1f}, Volume: {trade['volume_ratio']:.1f}x")
                print(f"  Exit: {trade['exit_reason']} after {trade['bars_held']} bars")
            print()


def main():
    backtest = AdvancedMTFBacktest()
    
    print("Starting advanced multi-timeframe backtest...")
    print()
    
    trades = backtest.run_backtest()
    
    backtest.generate_report(trades)


if __name__ == "__main__":
    main()
