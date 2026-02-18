"""
Historical Backtesting Engine
Tests CFW6 + all confirmation layers on past data
"""

from datetime import datetime, timedelta
from typing import List, Dict
import json


class Backtest:
    def __init__(self, start_date: str, end_date: str, initial_capital: float = 5000):
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.trades = []
        self.daily_pnl = {}
        self.peak_capital = initial_capital
        self.max_drawdown = 0
        self.metrics = {}
        
    def run(self, tickers: List[str]):
        """Run backtest on historical data."""
        print(f"\n{'='*60}")
        print(f"BACKTESTING CFW6 STRATEGY")
        print(f"{'='*60}")
        print(f"Period: {self.start_date} to {self.end_date}")
        print(f"Tickers: {len(tickers)}")
        print(f"Initial Capital: ${self.initial_capital:,.2f}")
        print(f"{'='*60}\n")
        
        for idx, ticker in enumerate(tickers, 1):
            print(f"[{idx}/{len(tickers)}] Processing {ticker}...")
            
            try:
                bars = self.fetch_historical_bars(ticker)
                signals = self.detect_cfw6_signals(ticker, bars)
                
                print(f"  → Found {len(signals)} signals")
                
                for signal in signals:
                    self.execute_backtest_trade(signal)
                    
            except Exception as e:
                print(f"  → Error: {e}")
                continue
        
        self.calculate_metrics()
        self.save_results()
    
    def fetch_historical_bars(self, ticker: str) -> List[Dict]:
        """Fetch historical 1-minute bars from EODHD."""
        import requests
        import config
        
        url = f"https://eodhd.com/api/intraday/{ticker}.US"
        params = {
            "api_token": config.EODHD_API_KEY,
            "interval": "1m",
            "from": self.start_date,
            "to": self.end_date,
            "fmt": "json"
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        bars = []
        for bar in data:
            bars.append({
                "datetime": datetime.fromtimestamp(bar["timestamp"]),
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"]
            })
        
        return bars
    
    def detect_cfw6_signals(self, ticker: str, bars: List[Dict]) -> List[Dict]:
        """Detect all CFW6 signals in historical data."""
        from sniper import (
            compute_opening_range_from_bars,
            detect_breakout_after_or,
            detect_fvg_after_break
        )
        from candle_confirmation import wait_for_confirmation
        from targets import compute_stop_and_targets
        
        signals = []
        days = self.group_bars_by_day(bars)
        
        for date, day_bars in days.items():
            if len(day_bars) < 50:
                continue
            
            or_high, or_low = compute_opening_range_from_bars(day_bars)
            if not or_high:
                continue
            
            direction, breakout_idx = detect_breakout_after_or(day_bars, or_high, or_low)
            if not direction:
                continue
            
            fvg_low, fvg_high = detect_fvg_after_break(day_bars, breakout_idx, direction)
            if not fvg_low:
                continue
            
            zone_low, zone_high = min(fvg_low, fvg_high), max(fvg_low, fvg_high)
            
            found, entry_price, grade, confirm_idx = wait_for_confirmation(
                day_bars, direction, (zone_low, zone_high), breakout_idx + 1
            )
            
            if not found or grade == "reject":
                continue
            
            stop_price, t1, t2 = compute_stop_and_targets(
                day_bars, direction, or_high, or_low, entry_price
            )
            
            signals.append({
                "ticker": ticker,
                "date": date,
                "direction": direction,
                "entry": entry_price,
                "stop": stop_price,
                "t1": t1,
                "t2": t2,
                "grade": grade,
                "entry_time": day_bars[confirm_idx]["datetime"],
                "bars_after_entry": day_bars[confirm_idx:]
            })
        
        return signals
    
    def execute_backtest_trade(self, signal: Dict):
        """Execute and track backtest trade."""
        entry = signal["entry"]
        stop = signal["stop"]
        t1 = signal["t1"]
        direction = signal["direction"]
        
        from learning_policy import compute_confidence
        confidence = compute_confidence(signal["grade"], "1m", signal["ticker"])
        
        risk_per_share = abs(entry - stop)
        contracts = 1
        risk_dollars = risk_per_share * 100 * contracts
        
        bars_after = signal["bars_after_entry"]
        exit_price, exit_reason, exit_time = self.simulate_trade_exit(
            bars_after, entry, stop, t1, signal["t2"], direction
        )
        
        if direction == "bull":
            pnl_per_share = exit_price - entry
        else:
            pnl_per_share = entry - exit_price
        
        pnl_dollars = pnl_per_share * 100 * contracts
        pnl_pct = (pnl_dollars / risk_dollars) * 100 if risk_dollars > 0 else 0
        
        self.capital += pnl_dollars
        
        if self.capital > self.peak_capital:
            self.peak_capital = self.capital
        
        drawdown = ((self.peak_capital - self.capital) / self.peak_capital) * 100
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        trade = {
            "ticker": signal["ticker"],
            "date": signal["date"],
            "direction": direction,
            "grade": signal["grade"],
            "confidence": confidence,
            "entry": entry,
            "exit": exit_price,
            "stop": stop,
            "t1": t1,
            "t2": signal["t2"],
            "exit_reason": exit_reason,
            "pnl": pnl_dollars,
            "pnl_pct": pnl_pct,
            "contracts": contracts,
            "risk": risk_dollars,
            "entry_time": signal["entry_time"],
            "exit_time": exit_time,
            "hold_duration": (exit_time - signal["entry_time"]).total_seconds() / 60
        }
        
        self.trades.append(trade)
        
        date_key = signal["date"]
        if date_key not in self.daily_pnl:
            self.daily_pnl[date_key] = 0
        self.daily_pnl[date_key] += pnl_dollars
        
        status = "✅ WIN" if pnl_dollars > 0 else "❌ LOSS"
        print(f"  {status} {signal['ticker']} {direction.upper()} | "
              f"Entry: ${entry:.2f} Exit: ${exit_price:.2f} ({exit_reason}) | "
              f"P&L: ${pnl_dollars:+.2f}")
    
    def simulate_trade_exit(self, bars: List[Dict], entry: float, stop: float, 
                           t1: float, t2: float, direction: str):
        """Simulate trade exit based on stop/target hits."""
        for bar in bars:
            high = bar["high"]
            low = bar["low"]
            
            if direction == "bull":
                if low <= stop:
                    return stop, "Stop Loss", bar["datetime"]
                if high >= t1:
                    return t1, "Target 1", bar["datetime"]
                if high >= t2:
                    return t2, "Target 2", bar["datetime"]
            else:
                if high >= stop:
                    return stop, "Stop Loss", bar["datetime"]
                if low <= t1:
                    return t1, "Target 1", bar["datetime"]
                if low <= t2:
                    return t2, "Target 2", bar["datetime"]
        
        return bars[-1]["close"], "EOD Close", bars[-1]["datetime"]
    
    def group_bars_by_day(self, bars: List[Dict]) -> Dict[str, List[Dict]]:
        """Group bars by trading day."""
        days = {}
        for bar in bars:
            date_key = bar["datetime"].strftime("%Y-%m-%d")
            if date_key not in days:
                days[date_key] = []
            days[date_key].append(bar)
        return days
    
    def calculate_metrics(self):
        """Calculate comprehensive backtest metrics."""
        if not self.trades:
            print("\n❌ No trades executed in backtest period")
            return
        
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t["pnl"] > 0]
        losing_trades = [t for t in self.trades if t["pnl"] <= 0]
        
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / total_trades) * 100
        
        total_profit = sum(t["pnl"] for t in winning_trades)
        total_loss = abs(sum(t["pnl"] for t in losing_trades))
        
        profit_factor = total_profit / total_loss if total_loss > 0 else 999
        
        avg_win = total_profit / win_count if win_count > 0 else 0
        avg_loss = total_loss / loss_count if loss_count > 0 else 0
        
        final_capital = self.capital
        total_return = final_capital - self.initial_capital
        total_return_pct = (total_return / self.initial_capital) * 100
        
        avg_hold_time = sum(t["hold_duration"] for t in self.trades) / total_trades
        
        grade_counts = {}
        for trade in self.trades:
            grade = trade["grade"]
            if grade not in grade_counts:
                grade_counts[grade] = {"count": 0, "wins": 0, "pnl": 0}
            grade_counts[grade]["count"] += 1
            if trade["pnl"] > 0:
                grade_counts[grade]["wins"] += 1
            grade_counts[grade]["pnl"] += trade["pnl"]
        
        print("\n" + "="*60)
        print("BACKTEST RESULTS")
        print("="*60)
        print(f"Period: {self.start_date} to {self.end_date}")
        print(f"Initial Capital: ${self.initial_capital:,.2f}")
        print(f"Final Capital: ${final_capital:,.2f}")
        print(f"Total Return: ${total_return:+,.2f} ({total_return_pct:+.2f}%)")
        print(f"Max Drawdown: {self.max_drawdown:.2f}%")
        print()
        print(f"Total Trades: {total_trades}")
        print(f"Winners: {win_count} ({win_rate:.1f}%)")
        print(f"Losers: {loss_count}")
        print()
        print(f"Profit Factor: {profit_factor:.2f}")
        print(f"Avg Win: ${avg_win:.2f}")
        print(f"Avg Loss: ${avg_loss:.2f}")
        print(f"Avg Hold Time: {avg_hold_time:.1f} minutes")
        print()
        print("Grade Breakdown:")
        for grade in ["A+", "A", "A-"]:
            if grade in grade_counts:
                g = grade_counts[grade]
                g_wr = (g["wins"] / g["count"]) * 100
                print(f"  {grade}: {g['count']} trades, {g_wr:.1f}% WR, ${g['pnl']:+,.2f}")
        print("="*60)
        
        self.metrics = {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_return_pct": total_return_pct,
            "max_drawdown": self.max_drawdown,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_hold_time_minutes": avg_hold_time,
            "grade_breakdown": grade_counts
        }
    
    def save_results(self):
        """Save backtest results to JSON."""
        results = {
            "config": {
                "start_date": self.start_date,
                "end_date": self.end_date,
                "initial_capital": self.initial_capital
            },
            "metrics": self.metrics,
            "trades": self.trades,
            "daily_pnl": self.daily_pnl
        }
        
        filename = f"backtest_{self.start_date}_{self.end_date}.json"
        with open(filename, "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n✅ Results saved to {filename}")


if __name__ == "__main__":
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    tickers = ["AAPL", "TSLA", "NVDA", "AMD", "SPY", "QQQ", "MSFT", "META"]
    
    backtest = Backtest(start_date, end_date, initial_capital=5000)
    backtest.run(tickers)
