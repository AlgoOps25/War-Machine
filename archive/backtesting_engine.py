"""
Historical Backtesting Engine
Tests CFW6 + all confirmation layers on past data
Includes Scaling Out logic (50% at T1) for accuracy
"""
import json
import os
import requests
from datetime import datetime, timedelta, time
from typing import List, Dict
import config


class Backtest:
    def __init__(self, start_date: str, end_date: str, initial_capital: float = 5000):
        self.start_date = start_date   # "YYYY-MM-DD"
        self.end_date   = end_date     # "YYYY-MM-DD"
        self.initial_capital = initial_capital
        self.capital    = initial_capital
        self.trades     = []
        self.daily_pnl  = {}
        self.peak_capital = initial_capital
        self.max_drawdown = 0
        self.metrics    = {}

    # ──────────────────────────────────────────────────────────
    # DATA FETCH
    # ──────────────────────────────────────────────────────────

    def fetch_historical_bars(self, ticker: str) -> List[Dict]:
        """Fetch intraday bars from EODHD using Unix timestamps (NOT date strings)."""
        # Convert date strings → Unix timestamps
        from_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        to_dt   = datetime.strptime(self.end_date,   "%Y-%m-%d") + timedelta(days=1)
        from_ts = int(from_dt.timestamp())
        to_ts   = int(to_dt.timestamp())

        url = f"https://eodhd.com/api/intraday/{ticker}.US"
        params = {
            "api_token": config.EODHD_API_KEY,
            "interval":  "1m",
            "from":      from_ts,
            "to":        to_ts,
            "fmt":       "json"
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        bars = []
        for b in data:
            try:
                bars.append({
                    "datetime": datetime.utcfromtimestamp(b["timestamp"]),
                    "open":     float(b["open"]),
                    "high":     float(b["high"]),
                    "low":      float(b["low"]),
                    "close":    float(b["close"]),
                    "volume":   int(b["volume"])
                })
            except Exception:
                continue
        return bars

    # ──────────────────────────────────────────────────────────
    # GROUP BARS BY DAY
    # ──────────────────────────────────────────────────────────

    def group_bars_by_day(self, bars: List[Dict]) -> Dict[str, List[Dict]]:
        """Split a flat bar list into per-day buckets."""
        days = {}
        for bar in bars:
            day_key = bar["datetime"].strftime("%Y-%m-%d")
            days.setdefault(day_key, []).append(bar)
        return days

    # ──────────────────────────────────────────────────────────
    # SIGNAL DETECTION — ONE DAY AT A TIME
    # ──────────────────────────────────────────────────────────

    def detect_cfw6_signals(self, ticker: str, bars: List[Dict]) -> List[Dict]:
        """
        Detect CFW6 signals: ORB breakout → FVG → confirmation candle.
        Processes each trading day independently (day-trading rule enforced).
        """
        signals  = []
        day_map  = self.group_bars_by_day(bars)

        for day_str, day_bars in sorted(day_map.items()):
            # Only use regular session bars 9:30–16:00 ET
            session = [
                b for b in day_bars
                if time(9, 30) <= b["datetime"].time() <= time(16, 0)
            ]
            if len(session) < 15:
                continue

            # ── Opening Range 9:30–9:40 ──────────────────────
            or_bars = [b for b in session if b["datetime"].time() < time(9, 40)]
            if len(or_bars) < 2:
                continue
            or_high = max(b["high"]  for b in or_bars)
            or_low  = min(b["low"]   for b in or_bars)

            # ── Breakout detection (first candle closing outside OR) ──
            direction    = None
            breakout_idx = None
            post_or      = [b for b in session if b["datetime"].time() >= time(9, 40)]

            for i, bar in enumerate(post_or):
                if bar["close"] > or_high * (1 + getattr(config, "ORB_BREAK_THRESHOLD", 0.001)):
                    direction, breakout_idx = "bull", i
                    break
                if bar["close"] < or_low * (1 - getattr(config, "ORB_BREAK_THRESHOLD", 0.001)):
                    direction, breakout_idx = "bear", i
                    break

            if direction is None:
                continue

            # ── FVG detection ─────────────────────────────────
            fvg_low = fvg_high = None
            fvg_min = getattr(config, "FVG_MIN_SIZE_PCT", 0.001)

            for i in range(breakout_idx + 3, len(post_or)):
                c0 = post_or[i - 2]
                c2 = post_or[i]
                if direction == "bull":
                    gap = c2["low"] - c0["high"]
                    if gap > 0 and (gap / c0["high"]) >= fvg_min:
                        fvg_low, fvg_high = c0["high"], c2["low"]
                        fvg_idx = i
                        break
                else:
                    gap = c0["low"] - c2["high"]
                    if gap > 0 and (gap / c0["low"]) >= fvg_min:
                        fvg_low, fvg_high = c2["high"], c0["low"]
                        fvg_idx = i
                        break

            if fvg_low is None:
                continue

            zone_mid  = (fvg_low + fvg_high) / 2
            entry_price = zone_mid

            # ── Stop & Targets ─────────────────────────────────
            atr = self._simple_atr(post_or[:breakout_idx + 1])
            if direction == "bull":
                stop_price = fvg_low - atr * 0.5
                t1         = entry_price + (entry_price - stop_price) * 1.5
                t2         = entry_price + (entry_price - stop_price) * 3.0
            else:
                stop_price = fvg_high + atr * 0.5
                t1         = entry_price - (stop_price - entry_price) * 1.5
                t2         = entry_price - (stop_price - entry_price) * 3.0

            # ── Bars after entry (EOD forced exit enforced) ───
            bars_after = post_or[fvg_idx + 1:]
            # Day-trading rule: never carry past 15:55 ET
            bars_after = [
                b for b in bars_after
                if b["datetime"].time() <= time(15, 55)
            ]

            if not bars_after:
                continue

            signals.append({
                "ticker":          ticker,
                "date":            day_str,
                "direction":       direction,
                "entry":           entry_price,
                "stop":            stop_price,
                "t1":              t1,
                "t2":              t2,
                "or_high":         or_high,
                "or_low":          or_low,
                "fvg_low":         fvg_low,
                "fvg_high":        fvg_high,
                "bars_after_entry": bars_after
            })

        return signals

    def _simple_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Simple ATR calculation for stop sizing."""
        if len(bars) < 2:
            return 0.5
        trs = [abs(b["high"] - b["low"]) for b in bars[-period:]]
        return sum(trs) / len(trs) if trs else 0.5

    # ──────────────────────────────────────────────────────────
    # TRADE EXECUTION
    # ──────────────────────────────────────────────────────────

    def execute_backtest_trade(self, signal: Dict):
        """Execute trade with Scaling Out (50% at T1) + EOD forced close."""
        entry     = signal["entry"]
        stop      = signal["stop"]
        t1        = signal["t1"]
        t2        = signal["t2"]
        direction = signal["direction"]
        contracts = 2  # Always even for 50/50 split

        bars_after  = signal["bars_after_entry"]
        total_pnl   = 0.0
        t1_hit      = False
        exit_time   = None
        exit_reason = "EOD CLOSE"  # Default — day trading rule

        for bar in bars_after:
            high = bar["high"]
            low  = bar["low"]

            if direction == "bull":
                if low <= stop:
                    remaining = contracts if not t1_hit else 1
                    total_pnl += (stop - entry) * 100 * remaining
                    exit_time   = bar["datetime"]
                    exit_reason = "STOP LOSS"
                    break
                if not t1_hit and high >= t1:
                    total_pnl += (t1 - entry) * 100 * (contracts // 2)
                    stop    = entry   # Move stop to breakeven
                    t1_hit  = True
                if t1_hit and high >= t2:
                    total_pnl += (t2 - entry) * 100 * 1
                    exit_time   = bar["datetime"]
                    exit_reason = "TARGET 2"
                    break
            else:  # bear
                if high >= stop:
                    remaining = contracts if not t1_hit else 1
                    total_pnl += (entry - stop) * 100 * remaining
                    exit_time   = bar["datetime"]
                    exit_reason = "STOP LOSS"
                    break
                if not t1_hit and low <= t1:
                    total_pnl += (entry - t1) * 100 * (contracts // 2)
                    stop    = entry
                    t1_hit  = True
                if t1_hit and low <= t2:
                    total_pnl += (entry - t2) * 100 * 1
                    exit_time   = bar["datetime"]
                    exit_reason = "TARGET 2"
                    break

        # EOD forced close — day trading rule
        if not exit_time:
            exit_time  = bars_after[-1]["datetime"]
            final_px   = bars_after[-1]["close"]
            remaining  = 1 if t1_hit else contracts
            total_pnl += (
                (final_px - entry) if direction == "bull" else (entry - final_px)
            ) * 100 * remaining

        self.capital = round(self.capital + total_pnl, 2)
        if self.capital > self.peak_capital:
            self.peak_capital = self.capital
        drawdown = self.peak_capital - self.capital
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        # Track daily P&L
        day_key = exit_time.strftime("%Y-%m-%d") if exit_time else "unknown"
        self.daily_pnl[day_key] = round(
            self.daily_pnl.get(day_key, 0) + total_pnl, 2
        )

        self.trades.append({
            "ticker":      signal["ticker"],
            "date":        signal.get("date", day_key),
            "direction":   direction,
            "entry":       round(entry, 2),
            "exit":        round(bars_after[-1]["close"] if not exit_time else exit_time and 0 or 0, 2),
            "pnl":         round(total_pnl, 2),
            "exit_reason": exit_reason,
            "t1_hit":      t1_hit
        })

        emoji = "✅" if total_pnl > 0 else "❌"
        print(f"  {emoji} {signal['ticker']} {direction.upper()} "
              f"| {exit_reason} | P&L: ${total_pnl:+.2f} | "
              f"Capital: ${self.capital:,.2f}")

    # ──────────────────────────────────────────────────────────
    # METRICS
    # ──────────────────────────────────────────────────────────

    def calculate_metrics(self):
        """Calculate full backtest performance metrics."""
        total_trades = len(self.trades)
        if total_trades == 0:
            self.metrics = {"error": "No trades executed"}
            return

        wins   = [t for t in self.trades if t["pnl"] > 0]
        losses = [t for t in self.trades if t["pnl"] <= 0]
        t1_hits = [t for t in self.trades if t.get("t1_hit")]

        win_rate     = len(wins) / total_trades * 100
        avg_win      = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
        avg_loss     = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        profit_factor = (
            abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses))
            if losses and sum(t["pnl"] for t in losses) != 0
            else float("inf")
        )
        total_pnl    = sum(t["pnl"] for t in self.trades)
        roi          = (self.capital - self.initial_capital) / self.initial_capital * 100

        exit_breakdown = {}
        for t in self.trades:
            r = t["exit_reason"]
            exit_breakdown[r] = exit_breakdown.get(r, 0) + 1

        self.metrics = {
            "total_trades":   total_trades,
            "wins":           len(wins),
            "losses":         len(losses),
            "win_rate":       round(win_rate, 1),
            "t1_hit_rate":    round(len(t1_hits) / total_trades * 100, 1),
            "avg_win":        round(avg_win, 2),
            "avg_loss":       round(avg_loss, 2),
            "profit_factor":  round(profit_factor, 2),
            "total_pnl":      round(total_pnl, 2),
            "final_capital":  round(self.capital, 2),
            "roi_pct":        round(roi, 2),
            "max_drawdown":   round(self.max_drawdown, 2),
            "exit_breakdown": exit_breakdown
        }

        print(f"\n{'='*60}")
        print(f"BACKTEST RESULTS: {self.start_date} → {self.end_date}")
        print(f"{'='*60}")
        print(f"Total Trades:   {total_trades}")
        print(f"Win Rate:       {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
        print(f"T1 Hit Rate:    {self.metrics['t1_hit_rate']}%")
        print(f"Profit Factor:  {profit_factor:.2f}")
        print(f"Avg Win:        ${avg_win:+.2f}")
        print(f"Avg Loss:       ${avg_loss:+.2f}")
        print(f"Total P&L:      ${total_pnl:+,.2f}")
        print(f"Final Capital:  ${self.capital:,.2f}")
        print(f"ROI:            {roi:.1f}%")
        print(f"Max Drawdown:   ${self.max_drawdown:,.2f}")
        print(f"Exit Breakdown: {exit_breakdown}")
        print(f"{'='*60}\n")

    # ──────────────────────────────────────────────────────────
    # SAVE
    # ──────────────────────────────────────────────────────────

    def save_results(self, output_dir: str = "."):
        """Save trades and metrics to JSON files."""
        os.makedirs(output_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        trades_path  = os.path.join(output_dir, f"backtest_trades_{stamp}.json")
        metrics_path = os.path.join(output_dir, f"backtest_metrics_{stamp}.json")

        with open(trades_path,  "w") as f:
            json.dump(self.trades,      f, indent=2, default=str)
        with open(metrics_path, "w") as f:
            json.dump(self.metrics,     f, indent=2, default=str)

        print(f"[BACKTEST] Results saved:")
        print(f"  Trades:  {trades_path}")
        print(f"  Metrics: {metrics_path}")

    # ──────────────────────────────────────────────────────────
    # RUN
    # ──────────────────────────────────────────────────────────

    def run(self, tickers: List[str]):
        """Run backtest on historical data."""
        print(f"\n{'='*60}")
        print(f"BACKTESTING CFW6 STRATEGY (WITH SCALING)")
        print(f"Period: {self.start_date} → {self.end_date}")
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Capital: ${self.initial_capital:,.2f}")
        print(f"{'='*60}\n")

        for idx, ticker in enumerate(tickers, 1):
            print(f"[{idx}/{len(tickers)}] Processing {ticker}...")
            try:
                bars    = self.fetch_historical_bars(ticker)
                print(f"  → {len(bars)} total bars fetched")
                signals = self.detect_cfw6_signals(ticker, bars)
                print(f"  → {len(signals)} signals detected")
                for signal in signals:
                    self.execute_backtest_trade(signal)
            except Exception as e:
                print(f"  → Error: {e}")
                continue

        self.calculate_metrics()
        self.save_results()


if __name__ == "__main__":
    backtest = Backtest("2026-01-01", "2026-02-18", initial_capital=5000)
    backtest.run(["AAPL", "TSLA", "NVDA", "MSFT"])
