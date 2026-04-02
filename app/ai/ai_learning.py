"""
AI Learning Module - Improves Entry Quality Over Time
Analyzes win/loss patterns and adjusts strategy parameters

CONSOLIDATED: Now includes learning_policy functions (compute_confidence, grade_to_label)
FIXED (Mar 10 2026): All get_conn() calls now use try/finally: return_conn(conn) — no leaks.
FIXED (Mar 16 2026): Extended _GRADE_BASE to all 9 grades (A+/A/A-/B+/B/B-).
                     Fixed bare 'import db_connection' -> 'from app.data import db_connection'.
FIXED (Mar 26 2026): record_trade() print() → logger.info() (Issue #37).
                     save_data() last_update timestamp naive → ZoneInfo ET (Issue #38).
FIXED (Mar 27 2026): get_options_flow_weight() imported options_dm from options_data_manager
                     (wrong module — dead import, always fell back to 1.0 with no effect).
                     Now correctly imports from options_intelligence (Issue #39 part 1).
FIX #46 (Mar 27 2026): generate_performance_report() now calls logger.info() so the
                     EOD report is surfaced in Railway logs when invoked, while still
                     returning the string for callers that need it.
FIX #47 (Mar 27 2026): AILearningEngine.__init__() self.data = self.load_data() wrapped
                     in try/except with fallback to default_data — prevents Railway
                     startup crash if Postgres row is malformed or JSON file is corrupt.
FIXED (Apr 01 2026): BUG-AIL-1: 6x logger.info on error/exception paths → logger.warning
                     so data-loss events surface in Railway logs.
                     BUG-AIL-2: optimize_confirmation_weights() not-enough-data message
                     → logger.debug (spammy until 20 trades accumulated).
                     BUG-AIL-4: __init__ load_data() fallback → logger.warning.
                     BUG-AIL-5: optimize_fvg_threshold() silent early return → logger.debug.
FIX (Apr 02 2026) — 47.P3-3: Kill C/C- grades.
                     Confidence scoring is inversely correlated with wins (backtest p=0.006).
                     Until confidence is properly re-tuned, C+/C/C- grades are rejected
                     at the source so no downstream code can accidentally pass them.
                     Changes:
                       - MIN_CONFIDENCE raised 0.50 → 0.60 (B- floor).
                       - _GRADE_BASE: C+/C/C- entries removed entirely.
                       - grade_to_label(): scores below 0.60 return 'reject'.
                       - config.py: MIN_CONFIDENCE_BY_GRADE / CONFIDENCE_CAP_BY_GRADE
                         C+/C/C- entries removed; CONFIDENCE_ABSOLUTE_FLOOR 0.55 → 0.60.
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

# Grade baseline confidence map — B- and above only.
# 47.P3-3 (Apr 02 2026): C+/C/C- removed. Confidence scoring is inversely
# correlated with wins (backtest p=0.006, n=107 trades) and is not yet
# re-tuned. Accepting C-tier signals until the scoring model is fixed risks
# feeding low-quality, mislabelled entries into live execution and ML training.
# Re-add C-tier entries here only after confidence calibration is validated.
_GRADE_BASE = {
    "A+":  0.90,   # midpoint of (0.88, 0.92)
    "A":   0.85,   # midpoint of (0.83, 0.87)
    "A-":  0.80,   # midpoint of (0.78, 0.82)
    "B+":  0.74,   # midpoint of (0.72, 0.76)
    "B":   0.68,   # midpoint of (0.66, 0.70)
    "B-":  0.62,   # midpoint of (0.60, 0.64)
    # C+/C/C- deliberately omitted — 47.P3-3
}

# Timeframe multiplier: higher timeframe = higher weight
_TF_MULTIPLIER = {
    "5m": 1.05,
    "3m": 1.02,
    "2m": 1.00,
    "1m": 0.97,
}

# Minimum threshold - signals below this are dropped upstream.
# 47.P3-3 (Apr 02 2026): raised 0.50 → 0.60 (B- floor).
# C+ midpoint is 0.575, C is 0.525, C- is 0.475 — all now below this floor.
MIN_CONFIDENCE = 0.60


def compute_confidence(
    grade: str,
    timeframe: str = "1m",
    ticker: str = ""
) -> float:
    """
    Compute base confidence score for a CFW6 signal.

    Args:
        grade:     Signal grade string - "A+" through "B-" (6 grades).
                   C+/C/C- grades are not in _GRADE_BASE (47.P3-3) and will
                   fall back to MIN_CONFIDENCE (0.60), which will be rejected
                   by downstream gates.
        timeframe: Bar timeframe - "1m", "2m", "3m", "5m"
        ticker:    Ticker symbol (reserved for future per-ticker tuning)

    Returns:
        Float in [0.0, 1.0] representing signal confidence.
        Falls back to MIN_CONFIDENCE (0.60) for unrecognised/C-tier grades.
    """
    base = _GRADE_BASE.get(grade, MIN_CONFIDENCE)
    tf_mult = _TF_MULTIPLIER.get(timeframe, 1.00)
    score = base * tf_mult
    return round(min(max(score, 0.0), 1.0), 4)


def grade_to_label(confidence: float) -> str:
    """
    Map a confidence float back to a letter grade.

    47.P3-3 (Apr 02 2026): Scores below 0.60 (B- floor) now return 'reject'.
    Previously C- returned for [0.45, 0.50) and C for [0.50, 0.55) — both
    are now 'reject' so callers that check for a non-reject grade act as a
    second gate against C-tier signals slipping through.
    """
    if confidence >= 0.88:   return "A+"
    elif confidence >= 0.83: return "A"
    elif confidence >= 0.78: return "A-"
    elif confidence >= 0.72: return "B+"
    elif confidence >= 0.66: return "B"
    elif confidence >= 0.60: return "B-"
    else:                    return "reject"

# =============================================================================
# AI LEARNING ENGINE
# =============================================================================

# Default learning state — used as fallback if load_data() fails at startup.
_DEFAULT_DATA: Dict = {
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


class AILearningEngine:
    def __init__(self, db_path: str = "learning_data.json"):
        self.db_path = db_path
        self._init_learning_table()
        # FIX #47: wrap load_data() — if Postgres row is malformed or JSON file
        # is corrupt this previously crashed the module-level singleton and took
        # down Railway startup. Fallback to clean default_data so the engine
        # always initialises successfully.
        try:
            self.data = self.load_data()
        except Exception as e:
            # BUG-AIL-4: warning so startup fallback is visible in Railway logs.
            logger.warning(f"[AI] load_data() failed at init — starting with defaults: {e}")
            self.data = dict(_DEFAULT_DATA)

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
            # BUG-AIL-1: table creation failure is an error, not info.
            logger.warning(f"[AI] Error creating learning table: {e}")
        finally:
            if conn:
                db_connection.return_conn(conn)

    def load_data(self) -> Dict:
        """Load learning data from PostgreSQL or JSON file."""
        default_data = dict(_DEFAULT_DATA)

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
                # BUG-AIL-1: PG load failure causes silent fallback to defaults — must be visible.
                logger.warning(f"[AI] Error loading from PostgreSQL: {e}")
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
                # BUG-AIL-1: JSON load failure causes silent fallback to defaults.
                logger.warning(f"[AI] Error loading JSON: {e}")
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
                # BUG-AIL-1: PG save failure means learning state is lost — must surface.
                logger.warning(f"[AI] Error saving to PostgreSQL: {e}")
            finally:
                if conn:
                    db_connection.return_conn(conn)
            return

        try:
            with open(self.db_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            # BUG-AIL-1: JSON save failure means learning state is lost.
            logger.warning(f"[AI] Error saving JSON: {e}")

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
            # BUG-AIL-2: debug — fires every EOD cycle until 20 trades; not actionable as info.
            logger.debug(
                f"[AI] Confirmation optimization skipped — "
                f"{len(trades_with_confirmations)}/20 trades with confirmations"
            )
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
            # BUG-AIL-5: silent return gave caller no visibility — log at debug.
            logger.debug(
                f"[AI] FVG threshold optimization skipped — "
                f"{len(recent_trades)}/30 trades required"
            )
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

        if win_rate >= 0.75:   return 1.10
        elif win_rate >= 0.65: return 1.05
        elif win_rate >= 0.55: return 1.0
        elif win_rate >= 0.45: return 0.95
        else:                  return 0.90

    def get_options_flow_weight(self, ticker: str) -> float:
        """
        Get options flow confidence weight from options_intelligence.
        Returns a multiplier in range [0.7, 1.3] based on options score.

        FIX #39 part 1 (Mar 27 2026): Previously imported options_dm from
        options_data_manager (the old EODHD strike selector — wrong module).
        That class has no get_options_score() so every call raised ImportError
        or AttributeError, was silently caught, and always returned 1.0.
        Now correctly imports from options_intelligence where options_dm is
        the backward-compat alias for OptionsIntelligence.

        Returns:
            1.0 if options_intelligence unavailable (neutral, no penalty)
            0.7-1.3 based on options score (0-100 scale)
        """
        try:
            from app.options.options_intelligence import options_dm
            score_data = options_dm.get_options_score(ticker)

            if not score_data.get('tradeable'):
                return 1.0

            score = score_data.get('score', 50)
            multiplier = 0.7 + (score / 100) * 0.6
            return round(multiplier, 2)

        except ImportError:
            return 1.0
        except Exception as e:
            # BUG-AIL-1/3: options flow weight failure should be visible in Railway logs.
            logger.warning(f"[AI] Error getting options flow weight for {ticker}: {e}")
            return 1.0

    def get_optimal_parameters(self) -> Dict:
        """Get current optimal strategy parameters."""
        return {
            "fvg_min_size_pct":    self.data["fvg_size_optimal"],
            "orb_break_threshold": self.data["or_break_threshold_optimal"],
            "confirmation_weights": self.data["confirmation_weights"]
        }

    def generate_performance_report(self) -> str:
        """Generate and log human-readable performance report. Also returns the string."""
        total_trades = len(self.data["trades"])
        if total_trades == 0:
            logger.info("[AI] Performance report: No trades recorded yet.")
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

        for grade in ["A+", "A", "A-", "B+", "B", "B-"]:
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

        # FIX #46: log the report to Railway — previously returned silently.
        # logger.info splits on newlines so each line appears as a separate log entry.
        for line in report.splitlines():
            logger.info(f"[AI] {line}")

        return report


# Global instance
learning_engine = AILearningEngine()
