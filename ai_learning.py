"""
AI Learning Module - Improves Entry Quality Over Time
Analyzes win/loss patterns and adjusts strategy parameters
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List
import numpy as np
import db_connection


class AILearningEngine:
    def __init__(self, db_path: str = "learning_data.json"):
        self.db_path = db_path
        self._init_learning_table()
        self.data = self.load_data()

    def _init_learning_table(self):
        """Create AI learning state table in PostgreSQL."""
        if not db_connection.USE_POSTGRES:
            return
        try:
            conn = db_connection.get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_learning_state (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT single_row CHECK (id = 1)
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[AI] Error creating learning table: {e}")

    def load_data(self) -> Dict:
        """Load learning data from PostgreSQL or JSON file."""
        default_data = {
            "trades": [],
            "pattern_performance": {},
            "ticker_performance": {},
            "timeframe_performance": {},
            "confirmation_weights": {
                "vwap": 1.0, "prev_day": 1.0,
                "institutional": 1.0, "options_flow": 1.0
            },
            "fvg_size_optimal": 0.002,
            "or_break_threshold_optimal": 0.001,
            "last_update": None
        }

        if db_connection.USE_POSTGRES:
            try:
                conn = db_connection.get_conn()
                cursor = db_connection.dict_cursor(conn)
                cursor.execute("SELECT data FROM ai_learning_state WHERE id = 1")
                row = cursor.fetchone()
                conn.close()
                if row:
                    d = row["data"]
                    return d if isinstance(d, dict) else json.loads(d)
            except Exception as e:
                print(f"[AI] Error loading from PostgreSQL: {e}")
            return default_data

        # SQLite: load from JSON file
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[AI] Error loading JSON: {e}")
        return default_data

    def save_data(self):
        """Save learning data to PostgreSQL or JSON file."""
        self.data["last_update"] = datetime.now().isoformat()

        if db_connection.USE_POSTGRES:
            try:
                conn = db_connection.get_conn()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO ai_learning_state (id, data, updated_at)
                    VALUES (1, %s::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        data       = EXCLUDED.data,
                        updated_at = CURRENT_TIMESTAMP
                """, (json.dumps(self.data),))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[AI] Error saving to PostgreSQL: {e}")
            return

        # SQLite: save to JSON file
        try:
            with open(self.db_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"[AI] Error saving JSON: {e}")

    def record_trade(self, trade: Dict):
        """Record a completed trade for learning."""
        trade_record = {
            "timestamp":      datetime.now().isoformat(),
            "ticker":         trade["ticker"],
            "direction":      trade["direction"],
            "grade":          trade["grade"],
            "entry":          trade["entry"],
            "exit":           trade["exit"],
            "pnl":            trade["pnl"],
            "win":            trade["pnl"] > 0,
            "hold_duration":  trade.get("hold_duration", 0),
            "fvg_size":       trade.get("fvg_size", 0),
            "or_break_size":  trade.get("or_break_size", 0),
            "confirmations":  trade.get("confirmations", {}),
            "timeframe":      trade.get("timeframe", "1m")
        }

        self.data["trades"].append(trade_record)
        self.update_performance_metrics(trade_record)
        self.save_data()

        print(f"[AI] Trade recorded: {trade['ticker']} {trade['direction']} → "
              f"{'WIN' if trade_record['win'] else 'LOSS'} ${trade['pnl']:+.2f}")

    def update_performance_metrics(self, trade: Dict):
        """Update performance tracking by pattern, ticker, timeframe."""
        ticker    = trade["ticker"]
        grade     = trade["grade"]
        timeframe = trade["timeframe"]
        win       = trade["win"]
        pnl       = trade["pnl"]

        # Pattern (grade) performance
        if grade not in self.data["pattern_performance"]:
            self.data["pattern_performance"][grade] = {"count": 0, "wins": 0, "total_pnl": 0}
        self.data["pattern_performance"][grade]["count"] += 1
        if win:
            self.data["pattern_performance"][grade]["wins"] += 1
        self.data["pattern_performance"][grade]["total_pnl"] += pnl

        # Ticker performance
        if ticker not in self.data["ticker_performance"]:
            self.data["ticker_performance"][ticker] = {"count": 0, "wins": 0, "total_pnl": 0}
        self.data["ticker_performance"][ticker]["count"] += 1
        if win:
            self.data["ticker_performance"][ticker]["wins"] += 1
        self.data["ticker_performance"][ticker]["total_pnl"] += pnl

        # Timeframe performance
        if timeframe not in self.data["timeframe_performance"]:
            self.data["timeframe_performance"][timeframe] = {"count": 0, "wins": 0, "total_pnl": 0}
        self.data["timeframe_performance"][timeframe]["count"] += 1
        if win:
            self.data["timeframe_performance"][timeframe]["wins"] += 1
        self.data["timeframe_performance"][timeframe]["total_pnl"] += pnl

    def optimize_confirmation_weights(self):
        """Analyze which confirmations correlate with wins."""
        trades_with_confirmations = [
            t for t in self.data["trades"]
            if "confirmations" in t and t["confirmations"]
        ]

        if len(trades_with_confirmations) < 20:
            print("[AI] Not enough data for confirmation optimization (need 20+ trades)")
            return

        # Derive baseline win rate from all recorded trades
        all_trades = self.data["trades"]
        baseline_wr = (
            sum(1 for t in all_trades if t["win"]) / len(all_trades)
            if all_trades else 0.65
        )
        baseline_wr = max(baseline_wr, 0.01)  # guard against divide-by-zero

        confirmation_scores = {
            "vwap":         {"wins": 0, "total": 0},
            "prev_day":     {"wins": 0, "total": 0},
            "institutional":{"wins": 0, "total": 0},
            "options_flow": {"wins": 0, "total": 0}
        }

        for trade in trades_with_confirmations:
            confirmations = trade["confirmations"]
            win = trade["win"]
            for conf_type in confirmation_scores:
                if confirmations.get(conf_type):
                    confirmation_scores[conf_type]["total"] += 1
                    if win:
                        confirmation_scores[conf_type]["wins"] += 1

        for conf_type, scores in confirmation_scores.items():
            if scores["total"] > 0:
                win_rate   = scores["wins"] / scores["total"]
                new_weight = win_rate / baseline_wr
                self.data["confirmation_weights"][conf_type] = round(new_weight, 2)

        print("[AI] Confirmation weights optimized:")
        for conf, weight in self.data["confirmation_weights"].items():
            print(f"  {conf}: {weight:.2f}")
        self.save_data()

    def optimize_fvg_threshold(self):
        """Find optimal FVG size threshold."""
        recent_trades = self.data["trades"][-100:]  # Last 100 trades

        if len(recent_trades) < 30:
            return

        winning_fvg = [
            t["fvg_size"] for t in recent_trades
            if t.get("win") and t.get("fvg_size", 0) > 0
        ]

        if len(winning_fvg) > 10:
            optimal_fvg = np.median(winning_fvg)
            self.data["fvg_size_optimal"] = round(optimal_fvg, 4)
            print(f"[AI] Optimal FVG size updated: {optimal_fvg:.4f}")
            self.save_data()

    def get_ticker_confidence_multiplier(self, ticker: str) -> float:
        """Get confidence multiplier based on ticker's historical performance."""
        if ticker not in self.data["ticker_performance"]:
            return 1.0

        perf = self.data["ticker_performance"][ticker]
        if perf["count"] < 5:
            return 1.0  # Not enough data

        win_rate = perf["wins"] / perf["count"]
        if win_rate >= 0.75:
            return 1.10
        elif win_rate >= 0.65:
            return 1.05
        elif win_rate <= 0.45:
            return 0.90
        elif win_rate <= 0.55:
            return 0.95
        return 1.0

    def get_optimal_parameters(self) -> Dict:
        """Get current optimal strategy parameters."""
        return {
            "fvg_min_size_pct":       self.data["fvg_size_optimal"],
            "orb_break_threshold":    self.data["or_break_threshold_optimal"],
            "confirmation_weights":   self.data["confirmation_weights"]
        }

    def generate_performance_report(self) -> str:
        """Generate human-readable performance report."""
        total_trades = len(self.data["trades"])
        if total_trades == 0:
            return "No trades recorded yet."

        wins      = sum(1 for t in self.data["trades"] if t["win"])
        win_rate  = (wins / total_trades) * 100
        total_pnl = sum(t["pnl"] for t in self.data["trades"])

        report  = f"\n{'='*60}\n"
        report += "AI LEARNING ENGINE - PERFORMANCE REPORT\n"
        report += f"{'='*60}\n"
        report += f"Total Trades: {total_trades}\n"
        report += f"Win Rate: {win_rate:.1f}%\n"
        report += f"Total P&L: ${total_pnl:+,.2f}\n"
        report += f"\nGrade Performance:\n"

        for grade in ["A+", "A", "A-"]:
            if grade in self.data["pattern_performance"]:
                perf     = self.data["pattern_performance"][grade]
                grade_wr = (perf["wins"] / perf["count"]) * 100 if perf["count"] > 0 else 0
                report  += (f"  {grade}: {perf['count']} trades, "
                            f"{grade_wr:.1f}% WR, ${perf['total_pnl']:+.2f}\n")

        report += f"\nTop Performing Tickers:\n"
        sorted_tickers = sorted(
            self.data["ticker_performance"].items(),
            key=lambda x: x[1]["total_pnl"],
            reverse=True
        )[:5]
        for ticker, perf in sorted_tickers:
            ticker_wr = (perf["wins"] / perf["count"]) * 100 if perf["count"] > 0 else 0
            report   += (f"  {ticker}: {perf['count']} trades, "
                         f"{ticker_wr:.1f}% WR, ${perf['total_pnl']:+.2f}\n")

        report += f"{'='*60}\n"
        return report


# Global instance
learning_engine = AILearningEngine()
