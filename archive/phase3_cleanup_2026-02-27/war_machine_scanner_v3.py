#!/usr/bin/env python3
"""
War Machine Scanner V3 - Production Ready

Real-time BOS scanner using validated V2 winner config:
- Volume: 2.0x
- ATR Stop: 4.0x  
- Target R:R: 2.5
- Lookback: 16
- Time Window: 9:30-10:00 AM (Opening Range)
- Momentum: Weak (>0.2%)

Validated Performance: 83% WR, 7.70 PF
"""

import sys
import os
import time
import json
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional
import sqlite3
import requests
from pathlib import Path

ET = ZoneInfo("America/New_York")

print("\n" + "="*70)
print("WAR MACHINE SCANNER V3 - PRODUCTION MODE")
print("Opening Range BOS Detector (9:30-10:00 AM)")
print("="*70)
print()


class WarMachineScanner:
    """
    Production scanner using validated V2 configuration.
    Monitors opening range (9:30-10:00 AM) for BOS signals.
    """
    
    def __init__(self, discord_webhook: str = None, risk_per_trade: float = 100.0):
        self.db_path = "market_memory.db"
        self.discord_webhook = discord_webhook
        self.risk_per_trade = risk_per_trade
        
        # VALIDATED CONFIG (V2 Winner)
        self.config = {
            "volume_multiplier": 2.0,
            "atr_stop_multiplier": 4.0,
            "target_rr": 2.5,
            "lookback": 16,
            "momentum_threshold": 0.002,  # 0.2% minimum
        }
        
        # Watchlist (same as validation)
        self.tickers = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
        
        # Trading hours (Opening range only)
        self.market_open = dtime(9, 30)
        self.market_close_scan = dtime(10, 0)  # Stop scanning after 10 AM
        
        # Signal tracking (prevent duplicate alerts)
        self.signal_cache = set()
        self.cache_file = Path("signal_cache.json")
        self.load_cache()
        
        print(f"Config: Vol={self.config['volume_multiplier']}x | "
              f"ATR={self.config['atr_stop_multiplier']}x | "
              f"RR={self.config['target_rr']}R")
        print(f"Time Window: {self.market_open.strftime('%H:%M')} - "
              f"{self.market_close_scan.strftime('%H:%M')} EST")
        print(f"Risk Per Trade: ${self.risk_per_trade:.2f}")
        print(f"Watchlist: {', '.join(self.tickers)}")
        print(f"Discord Alerts: {'Enabled' if discord_webhook else 'Disabled'}")
        print("="*70)
        print()
    
    def load_cache(self):
        """Load signal cache to prevent duplicate alerts."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    self.signal_cache = set(data.get("signals", []))
                print(f"💾 Loaded {len(self.signal_cache)} cached signals")
            except:
                pass
    
    def save_cache(self):
        """Save signal cache."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump({"signals": list(self.signal_cache)}, f)
        except:
            pass
    
    def clear_daily_cache(self):
        """Clear cache at start of new trading day."""
        today = datetime.now(ET).date().isoformat()
        
        # Remove signals from previous days
        self.signal_cache = {s for s in self.signal_cache if s.startswith(today)}
        self.save_cache()
    
    def get_cache_key(self, ticker: str, direction: str, entry_time: datetime) -> str:
        """Generate unique cache key for signal."""
        return f"{entry_time.date().isoformat()}_{ticker}_{direction}_{entry_time.strftime('%H:%M')}"
    
    def is_market_hours(self) -> bool:
        """Check if within scanning hours."""
        now = datetime.now(ET)
        current_time = now.time()
        
        # Only scan opening range
        return self.market_open <= current_time < self.market_close_scan
    
    def load_bars_from_db(self, ticker: str, lookback_days: int = 2) -> List[Dict]:
        """Load recent bars for ticker."""
        end_date = datetime.now(ET)
        start_date = end_date - timedelta(days=lookback_days)
        
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
    
    def get_pdh_pdl(self, ticker: str) -> Dict[str, float]:
        """Get previous day high/low."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Find previous trading day
        today = datetime.now(ET).date()
        
        for days_back in range(1, 10):
            prev_date = today - timedelta(days=days_back)
            prev_date_str = prev_date.isoformat()
            
            query = """
                SELECT high, low
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
                    cur.close()
                    conn.close()
                    return {"pdh": pdh, "pdl": pdl}
            
            except Exception as e:
                continue
        
        cur.close()
        conn.close()
        return {"pdh": 0, "pdl": 0}
    
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
    
    def detect_bos(self, bars: List[Dict], lookback: int, direction: str) -> bool:
        """Detect break of structure."""
        idx = len(bars) - 1
        
        if idx < lookback + 10:
            return False
        
        current = bars[idx]
        
        if direction == "LONG":
            # Find last swing high in lookback period
            for i in range(idx - lookback, idx - 5):
                if i < 0:
                    continue
                if self.find_swing_high(bars, i):
                    last_swing_high = bars[i]["high"]
                    return current["high"] > last_swing_high
            
            return False
        
        else:  # SHORT
            # Find last swing low in lookback period
            for i in range(idx - lookback, idx - 5):
                if i < 0:
                    continue
                if self.find_swing_low(bars, i):
                    last_swing_low = bars[i]["low"]
                    return current["low"] < last_swing_low
            
            return False
    
    def calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate ATR."""
        if len(bars) < period + 1:
            return 0.0
        
        recent = bars[-(period+1):]
        
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
    
    def calculate_momentum(self, bars: List[Dict], period: int = 5) -> float:
        """Calculate momentum."""
        if len(bars) < period + 1:
            return 0.0
        
        current = bars[-1]["close"]
        past = bars[-(period+1)]["close"]
        
        return (current - past) / past if past != 0 else 0.0
    
    def calculate_position_size(self, risk_amount: float, stop_distance: float, price: float) -> int:
        """Calculate position size based on risk."""
        if stop_distance <= 0:
            return 0
        
        shares = int(risk_amount / stop_distance)
        return max(shares, 1)  # At least 1 share
    
    def scan_ticker(self, ticker: str) -> Optional[Dict]:
        """Scan single ticker for BOS signal."""
        # Load recent bars
        bars = self.load_bars_from_db(ticker, lookback_days=3)
        
        if len(bars) < self.config["lookback"] + 20:
            return None
        
        # Get PDH/PDL
        pdh_pdl = self.get_pdh_pdl(ticker)
        
        if pdh_pdl["pdh"] == 0 or pdh_pdl["pdl"] == 0:
            return None
        
        current = bars[-1]
        
        # Check if current bar is within opening range time
        current_time = current["datetime"].time()
        if not (self.market_open <= current_time < self.market_close_scan):
            return None
        
        # Volume filter
        recent = bars[-21:-1]
        avg_volume = sum(b["volume"] for b in recent) / len(recent) if recent else 0
        
        if avg_volume == 0 or current["volume"] < avg_volume * self.config["volume_multiplier"]:
            return None
        
        # ATR
        atr = self.calculate_atr(bars)
        if atr == 0:
            return None
        
        # Momentum filter (weak = >0.2%)
        momentum = self.calculate_momentum(bars)
        
        if abs(momentum) < self.config["momentum_threshold"]:
            return None
        
        # Check for LONG setup
        if self.detect_bos(bars, self.config["lookback"], "LONG"):
            if current["close"] > pdh_pdl["pdh"]:
                entry = current["close"]
                stop = entry - (atr * self.config["atr_stop_multiplier"])
                target = entry + (atr * self.config["atr_stop_multiplier"] * self.config["target_rr"])
                
                stop_distance = entry - stop
                position_size = self.calculate_position_size(self.risk_per_trade, stop_distance, entry)
                
                # Check cache to prevent duplicates
                cache_key = self.get_cache_key(ticker, "LONG", current["datetime"])
                if cache_key in self.signal_cache:
                    return None
                
                return {
                    "ticker": ticker,
                    "direction": "LONG",
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "atr": atr,
                    "position_size": position_size,
                    "risk": stop_distance * position_size,
                    "reward": (target - entry) * position_size,
                    "time": current["datetime"],
                    "pdh": pdh_pdl["pdh"],
                    "cache_key": cache_key
                }
        
        # Check for SHORT setup
        elif self.detect_bos(bars, self.config["lookback"], "SHORT"):
            if current["close"] < pdh_pdl["pdl"]:
                entry = current["close"]
                stop = entry + (atr * self.config["atr_stop_multiplier"])
                target = entry - (atr * self.config["atr_stop_multiplier"] * self.config["target_rr"])
                
                stop_distance = stop - entry
                position_size = self.calculate_position_size(self.risk_per_trade, stop_distance, entry)
                
                # Check cache to prevent duplicates
                cache_key = self.get_cache_key(ticker, "SHORT", current["datetime"])
                if cache_key in self.signal_cache:
                    return None
                
                return {
                    "ticker": ticker,
                    "direction": "SHORT",
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "atr": atr,
                    "position_size": position_size,
                    "risk": stop_distance * position_size,
                    "reward": (entry - target) * position_size,
                    "time": current["datetime"],
                    "pdl": pdh_pdl["pdl"],
                    "cache_key": cache_key
                }
        
        return None
    
    def send_discord_alert(self, signal: Dict):
        """Send Discord webhook alert."""
        if not self.discord_webhook:
            return
        
        direction_emoji = "🚀" if signal["direction"] == "LONG" else "🔻"
        
        embed = {
            "title": f"{direction_emoji} WAR MACHINE SIGNAL",
            "color": 65280 if signal["direction"] == "LONG" else 16711680,
            "fields": [
                {"name": "Ticker", "value": signal["ticker"], "inline": True},
                {"name": "Direction", "value": signal["direction"], "inline": True},
                {"name": "Time", "value": signal["time"].strftime("%I:%M %p EST"), "inline": True},
                {"name": "Entry", "value": f"${signal['entry']:.2f}", "inline": True},
                {"name": "Stop", "value": f"${signal['stop']:.2f} (-${signal['entry']-signal['stop']:.2f})", "inline": True},
                {"name": "Target", "value": f"${signal['target']:.2f} (+${abs(signal['target']-signal['entry']):.2f})", "inline": True},
                {"name": "Position Size", "value": f"{signal['position_size']} shares", "inline": True},
                {"name": "Risk", "value": f"${signal['risk']:.2f}", "inline": True},
                {"name": "Reward", "value": f"${signal['reward']:.2f} ({signal['reward']/signal['risk']:.1f}R)", "inline": True},
                {"name": "ATR", "value": f"${signal['atr']:.2f}", "inline": True},
                {"name": "Breakout Level", "value": f"${signal.get('pdh', signal.get('pdl', 0)):.2f}", "inline": True},
            ],
            "footer": {"text": "War Machine V3 | Validated: 83% WR, 7.70 PF"},
            "timestamp": signal["time"].isoformat()
        }
        
        payload = {
            "embeds": [embed]
        }
        
        try:
            response = requests.post(self.discord_webhook, json=payload)
            if response.status_code == 204:
                print(f"  ✅ Discord alert sent")
            else:
                print(f"  ⚠️  Discord alert failed: {response.status_code}")
        except Exception as e:
            print(f"  ⚠️  Discord error: {e}")
    
    def print_signal(self, signal: Dict):
        """Print signal to console."""
        emoji = "🚀" if signal["direction"] == "LONG" else "🔻"
        
        print("\n" + "="*70)
        print(f"{emoji} WAR MACHINE SIGNAL")
        print("="*70)
        print(f"Ticker: {signal['ticker']}")
        print(f"Direction: {signal['direction']}")
        print(f"Time: {signal['time'].strftime('%Y-%m-%d %I:%M %p EST')}")
        print()
        print(f"Entry: ${signal['entry']:.2f}")
        print(f"Stop: ${signal['stop']:.2f} (-${abs(signal['entry']-signal['stop']):.2f}, {self.config['atr_stop_multiplier']:.1f} ATR)")
        print(f"Target: ${signal['target']:.2f} (+${abs(signal['target']-signal['entry']):.2f}, {self.config['target_rr']:.1f} R:R)")
        print()
        print(f"Position Size: {signal['position_size']} shares")
        print(f"Risk: ${signal['risk']:.2f}")
        print(f"Reward: ${signal['reward']:.2f} ({signal['reward']/signal['risk']:.1f}R)")
        print()
        print(f"ATR: ${signal['atr']:.2f}")
        print(f"Breakout Level: ${signal.get('pdh', signal.get('pdl', 0)):.2f}")
        print("="*70)
        print()
    
    def run_scan(self):
        """Run single scan cycle."""
        signals = []
        
        for ticker in self.tickers:
            signal = self.scan_ticker(ticker)
            if signal:
                signals.append(signal)
        
        return signals
    
    def run_continuous(self, scan_interval: int = 60):
        """Run continuous scanning during market hours."""
        print("⏳ Starting continuous scanner...")
        print(f"   Scan interval: {scan_interval} seconds")
        print(f"   Active window: {self.market_open.strftime('%H:%M')} - {self.market_close_scan.strftime('%H:%M')} EST")
        print()
        
        last_scan_date = None
        
        while True:
            now = datetime.now(ET)
            current_date = now.date()
            
            # Clear cache at start of new day
            if current_date != last_scan_date:
                print(f"\n📅 New trading day: {current_date}")
                self.clear_daily_cache()
                last_scan_date = current_date
            
            # Check if market hours
            if not self.is_market_hours():
                current_time = now.time()
                
                if current_time < self.market_open:
                    wait_seconds = (datetime.combine(current_date, self.market_open) - now).total_seconds()
                    print(f"\n⏰ Market opens in {wait_seconds/60:.0f} minutes. Waiting...")
                    time.sleep(min(wait_seconds, 300))  # Check every 5 min
                else:
                    print(f"\n🛎 Scanning window closed. Next scan tomorrow at {self.market_open.strftime('%H:%M')}")
                    time.sleep(3600)  # Sleep 1 hour
                
                continue
            
            # Run scan
            print(f"\n🔍 Scanning at {now.strftime('%I:%M:%S %p')}...")
            signals = self.run_scan()
            
            if signals:
                for signal in signals:
                    self.print_signal(signal)
                    self.send_discord_alert(signal)
                    
                    # Add to cache
                    self.signal_cache.add(signal["cache_key"])
                    self.save_cache()
            else:
                print("  No signals detected")
            
            # Wait for next scan
            time.sleep(scan_interval)


from datetime import timedelta

def main():
    # Load Discord webhook from environment or config
    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")  # Optional
    
    scanner = WarMachineScanner(
        discord_webhook=discord_webhook,
        risk_per_trade=100.0  # $100 risk per trade
    )
    
    # Run continuous scanning
    try:
        scanner.run_continuous(scan_interval=60)  # Scan every 60 seconds
    except KeyboardInterrupt:
        print("\n\n⏸️  Scanner stopped by user")
        print("="*70)


if __name__ == "__main__":
    main()
