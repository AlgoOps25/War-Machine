"""
AI Learning Module - Improves Entry Quality Over Time
Analyzes win/loss patterns and adjusts strategy parameters

CONSOLIDATED: Now includes learning_policy functions (compute_confidence, grade_to_label)
FIXED (Mar 10 2026): All get_conn() calls now use try/finally: return_conn(conn) — no leaks.
FIXED (Mar 16 2026): Extended _GRADE_BASE to all 9 grades (A+/A/A-/B+/B/B-/C+/C/C-).
                     Fixed bare 'import db_connection' -> 'from app.data import db_connection'.
FIXED (Mar 26 2026): record_trade() print() → logger.info() (Issue #37).
                     save_data() last_update timestamp naive → ZoneInfo ET (Issue #38).
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List
import numpy as np
from app.data import db_connection
from utils import config
import logging
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


# =============================================================================
# CONFIDENCE SCORING (formerly learning_policy.py)
# =============================================================================

# Grade baseline confidence map — all 9 CFW6 grades.
# A+/A/A- midpoints align with original learning_policy values.
# B+/B/B-/C+/C/C- midpoints sourced from confidence_model.py (Phase 2 extraction).
_GRADE_BASE = {
    "A+":  0.90,   # midpoint of (0.88, 0.92)
    "A":   0.85,   # midpoint of (0.83, 0.87)
    "A-":  0.80,   # midpoint of (0.78, 0.82)
    "B+":  0.74,   # midpoint of (0.72, 0.76)
    "B":   0.68,   # midpoint of (0.66, 0.70)
    "B-":  0.62,   # midpoint of (0.60, 0.64)
    "C+":  0.575,  # midpoint of (0.55, 0.60)
    "C":   0.525,  # midpoint of (0.50, 0.55)
    "C-":  0.475,  # midpoint of (0.45, 0.50)
}

# Timeframe multiplier: higher timeframe = higher weight
_TF_MULTIPLIER = {
    "5m": 1.05,
    "3m": 1.02,
    "2m": 1.00,
    "1m": 0.97,
}

# Minimum threshold - signals below this are dropped upstream
MIN_CONFIDENCE = 0.50


def compute_confidence(
    grade: str,
    timeframe: str = "1m",
    ticker: str = ""
) -> float:
    """
    Compute base confidence score for a CFW6 signal.

    Args:
        grade:     Signal grade string - "A+" through "C-" (9 grades)
        timeframe: Bar timeframe - "1m", "2m", "3m", "5m"
        ticker:    Ticker symbol (reserved for future per-ticker tuning)

    Returns:
        Float in [0.0, 1.0] representing signal confidence.
        Falls back to 0.50 (MIN_CONFIDENCE) for unrecognised grades.
    """
    base = _GRADE_BASE.get(grade, MIN_CONFIDENCE)
    tf_mult = _TF_MULTIPLIER.get(timeframe, 1.00)
    score = base * tf_mult
    return round(min(max(score, 0.0), 1.0), 4)


def grade_to_label(confidence: float) -> str:
    if confidence >= 0.88:   return "A+"
    elif confidence >= 0.83: return "A"
    elif confidence >= 0.78: return "A-"
    elif confidence >= 0.72: return "B+"
    elif confidence >= 0.66: return "B"
    elif confidence >= 0.60: return "B-"
    elif confidence >= 0.55: return "C+"
    elif confidence >= 0.50: return "C"
    elif confidence >= 0.45: return "C-"
    else:                    return "reject"

# =============================================================================
# AI LEARNING ENGINE
# =============================================================================

class AILearningEngine:
    def __init__(self, db_path: str = "learning_data.json"):
        self.db_path = db_path
        self._init_learning_table()
        self.data = self.load_data()

    def _init_learning_table(self):
        """Create AI learning state table in PostgreSQL."""
        if not db_connection.USE_POSTGRES:
            return
        conn = None
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
        except Exception as e:
            logger.info(f"[AI] Error creating learning table: {e}")
        finally:
            if conn:
                db_connection.return_conn(conn)

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
            conn = None
            try:
                conn = db_connection.get_conn()
                cursor = db_connection.dict_cursor(conn)
                cursor.execute("SELECT data FROM ai_learning_state WHERE id = 1")
                row = cursor.fetchone()
                if row:
                    d = row["data"]
                    if not isinstance(d, dict):
                        d = json.loads(d)
                    return {**default_data, **d}
            except Exception as e:
                logger.info(f"[AI] Error loading from PostgreSQL: {e}")
            finally:
                if conn:
                    db_connection.return_conn(conn)
            return default_data

        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    return {**default_data, **loaded}
            except Exception as e:
                logger.info(f"[AI] Error loading JSON: {e}")
        return default_data

    def save_data(self):
        """Save learning data to PostgreSQL or JSON file."""
        # FIX #38: datetime.now() was naive (UTC on Railway).
        # Use ZoneInfo ET for consistent timestamps across the codebase.
        self.data["last_update"] = datetime.now(ET).isoformat()

        if db_connection.USE_POSTGRES:
            conn = None
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
            except Exception as e:
                logger.info(f"[AI] Error saving to PostgreSQL: {e}")
            finally:
                if conn:
                    db_connection.return_conn(conn)
            return

        try:
            with open(self.db_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.info(f"[AI] Error saving JSON: {e}")

    def record_trade(self, trade: Dict):
        """Record a completed trade for learning."""
        trade_record = {
            "timestamp":      datetime.now(ET).isoformat(),
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

        # FIX #37: print() → logger.info() — consistent with rest of codebase.
        logger.info(
            f"[AI] Trade recorded: {trade['ticker']} {trade['direction']} -> "
            f"{'WIN' if trade_record['win'] else 'LOSS'} ${trade['pnl']:+.2f}"
        )

    def update_performance_metrics(self, trade: Dict):
        """Update performance tracking by pattern, ticker, timeframe."""
        ticker    = trade["ticker"]
        grade     = trade["grade"]
        timeframe = trade["timeframe"]
        win       = trade["win"]
        pnl       = trade["pnl"]

        if grade not in self.data["pattern_performance"]:
            self.data["pattern_performance"][grade] = {"count": 0, "wins": 0, "total_pnl": 0}
        self.data["pattern_performance"][grade]["count"] += 1
        if win:
            self.data["pattern_performance"][grade]["wins"] += 1
        self.data["pattern_performance"][grade]["total_pnl"] += pnl

        if ticker not in self.data["ticker_performance"]:
            self.data["ticker_performance"][ticker] = {"count": 0, "wins": 0, "total_pnl": 0}
        self.data["ticker_performance"][ticker]["count"] += 1
        if win:
            self.data["ticker_performance"][ticker]["wins"] += 1
        self.data["ticker_performance"][ticker]["total_pnl"] += pnl

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
            logger.info("[AI] Not enough data for confirmation optimization (need 20+ trades)")
            return

        all_trades = self.data["trades"]
        baseline_wr = (
            sum(1 for t in all_trades if t["win"]) / len(all_trades)
            if all_trades else 0.65
        )
        baseline_wr = max(baseline_wr, 0.01)

        confirmation_scores = {
            "vwap":          {"wins": 0, "total": 0},
            "prev_day":      {"wins": 0, "total": 0},
            "institutional": {"wins": 0, "total": 0},
            "options_flow":  {"wins": 0, "total": 0}
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

        logger.info("[AI] Confirmation weights optimized:")
        for conf, weight in self.data["confirmation_weights"].items():
            logger.info(f"  {conf}: {weight:.2f}")
        self.save_data()

    def optimize_fvg_threshold(self):
        """Find optimal FVG size threshold."""
        recent_trades = self.data["trades"][-100:]

        if len(recent_trades) < 30:
            return

        winning_fvg = [
            t["fvg_size"] for t in recent_trades
            if t.get("win") and t.get("fvg_size", 0) > 0
        ]

        if len(winning_fvg) > 10:
            optimal_fvg = np.median(winning_fvg)
            self.data["fvg_size_optimal"] = round(optimal_fvg, 4)
            logger.info(f"[AI] Optimal FVG size updated: {optimal_fvg:.4f}")
            self.save_data()

    def get_ticker_confidence_multiplier(self, ticker: str) -> float:
        """
        Get confidence multiplier based on ticker's historical performance.

        Returns:
            1.10 if WR >= 75% (strong performer)
            1.05 if WR >= 65% (above baseline)
            1.00 if WR 55-65% (neutral)
            0.95 if WR 45-55% (slightly below baseline)
            0.90 if WR <= 45% (poor performer)
        """
        if ticker not in self.data["ticker_performance"]:
            return 1.0

        perf = self.data["ticker_performance"][ticker]
        if perf["count"] < 5:
            return 1.0

        win_rate = perf["wins"] / perf["count"]

        if win_rate >= 0.75:
            return 1.10
        elif win_rate >= 0.65:
            return 1.05
        elif win_rate >= 0.55:
            return 1.0
        elif win_rate >= 0.45:
            return 0.95
        else:
            return 0.90

    def get_options_flow_weight(self, ticker: str) -> float:
        """
        Get options flow confidence weight from options_data_manager.
        Returns a multiplier in range [0.7, 1.3] based on options score.

        Returns:
            1.0 if options_data_manager unavailable (neutral, no penalty)
            0.7-1.3 based on options score (0-100 scale)
        """
        try:
            from app.options.options_data_manager import options_dm
            score_data = options_dm.get_options_score(ticker)

            if not score_data.get('tradeable'):
                return 1.0

            score = score_data.get('score', 50)
            multiplier = 0.7 + (score / 100) * 0.6
            return round(multiplier, 2)

        except ImportError:
            return 1.0
        except Exception as e:
            logger.info(f"[AI] Error getting options flow weight for {ticker}: {e}")
            return 1.0

    def get_optimal_parameters(self) -> Dict:
        """Get current optimal strategy parameters."""
        return {
            "fvg_min_size_pct":    self.data["fvg_size_optimal"],
            "orb_break_threshold": self.data["or_break_threshold_optimal"],
            "confirmation_weights": self.data["confirmation_weights"]
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
        report += "\nGrade Performance:\n"

        for grade in ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-"]:
            if grade in self.data["pattern_performance"]:
                perf     = self.data["pattern_performance"][grade]
                grade_wr = (perf["wins"] / perf["count"]) * 100 if perf["count"] > 0 else 0
                report  += (f"  {grade}: {perf['count']} trades, "
                            f"{grade_wr:.1f}% WR, ${perf['total_pnl']:+.2f}\n")

        report += "\nTop Performing Tickers:\n"
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
