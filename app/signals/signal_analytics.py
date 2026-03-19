"""
Signal Analytics Tracking System

Tracks the complete lifecycle of every CFW6 signal from generation through execution.
Provides funnel analysis, performance metrics, and data export for optimization.

Signal Lifecycle:
  1. GENERATED   - Pattern detected by sniper.py (OR breakout or BOS+FVG)
  2. VALIDATED   - Passed signal_validator.py checks (ADX, volume, DMI, etc.)
  3. ARMED       - Confirmed via wait_for_confirmation() (retest/rejection)
  4. TRADED      - Position opened via position_manager
  5. CLOSED      - Position closed (stop/T1/T2/EOD)

Key Metrics:
  - Signal funnel conversion rates (generated → validated → armed → traded)
  - Grade distribution (A+ vs A vs A-)
  - Confidence distribution before/after multipliers
  - Multiplier impact analysis (IVR/UOA/GEX/MTF average effects)
  - Time-to-confirmation (bars waited before retest)
  - Hourly signal patterns (time-of-day analysis)
  - Validation rejection reasons (which checks fail most)

FIXED (Mar 10 2026): All get_conn() calls now use try/finally: return_conn(conn) — no leaks.
ADDED (Mar 16 2026):
  - get_rejection_breakdown(days): aggregate rejection_reason by count — shows which
    validator checks (ADX, VOLUME, DMI, etc.) kill the most signals.
  - get_hourly_funnel(days): funnel breakdown per hour_of_day — reveals time-of-day
    signal quality differences for threshold tuning.
  - get_daily_summary() extended to include rejection breakdown + hourly funnel sections.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import statistics
from collections import defaultdict
from app.data.db_connection import get_conn, return_conn, ph, dict_cursor, serial_pk
import logging
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


class SignalTracker:
    """Tracks signal lifecycle events and provides analytics."""

    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self._initialize_database()

        # Session cache for fast lookups (cleared daily)
        self.session_signals: Dict[str, Dict] = {}  # {ticker: latest_signal_data}
        self.session_start = datetime.now(ET)

    def _initialize_database(self):
        """Create signal_events table if not exists."""
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = conn.cursor()

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS signal_events (
                    id {serial_pk()},
                    ticker TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    grade TEXT,

                    -- Lifecycle stages
                    stage TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    -- Confidence tracking
                    base_confidence REAL,
                    final_confidence REAL,

                    -- Multipliers
                    ivr_multiplier REAL DEFAULT 1.0,
                    uoa_multiplier REAL DEFAULT 1.0,
                    gex_multiplier REAL DEFAULT 1.0,
                    mtf_boost REAL DEFAULT 0.0,
                    ticker_multiplier REAL DEFAULT 1.0,

                    -- Multiplier labels for debugging
                    ivr_label TEXT,
                    uoa_label TEXT,
                    gex_label TEXT,

                    -- Validation details
                    validation_passed INTEGER,
                    validation_checks TEXT,
                    rejection_reason TEXT,

                    -- Confirmation details
                    bars_to_confirmation INTEGER,
                    confirmation_type TEXT,

                    -- Trade linkage
                    position_id INTEGER,

                    -- Additional metadata
                    entry_price REAL,
                    stop_price REAL,
                    t1_price REAL,
                    t2_price REAL,
                    session_date TEXT,
                    hour_of_day INTEGER
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_events_ticker
                ON signal_events(ticker)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_events_session
                ON signal_events(session_date, stage)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_events_timestamp
                ON signal_events(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_events_hour
                ON signal_events(session_date, hour_of_day, stage)
            """)

            conn.commit()
            logger.info("[ANALYTICS] Signal tracking database initialized")
        except Exception as e:
            logger.info(f"[ANALYTICS] DB init error: {e}")
        finally:
            if conn:
                return_conn(conn)

    def _get_session_date(self) -> str:
        return datetime.now(ET).strftime("%Y-%m-%d")

    def _get_hour_of_day(self) -> int:
        return datetime.now(ET).hour

    def record_signal_generated(
        self,
        ticker: str,
        signal_type: str,
        direction: str,
        grade: str,
        confidence: float,
        entry_price: float = 0.0,
        stop_price: float = 0.0,
        t1_price: float = 0.0,
        t2_price: float = 0.0
    ) -> int:
        """
        Record a new signal generation event.

        Returns:
            Signal event ID
        """
        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            values = (
                ticker, signal_type, direction, grade,
                'GENERATED', self._get_session_date(), self._get_hour_of_day(),
                confidence, entry_price, stop_price, t1_price, t2_price
            )

            if 'postgres' in str(type(cursor)):
                cursor.execute(f"""
                    INSERT INTO signal_events
                        (ticker, signal_type, direction, grade, stage, session_date, hour_of_day,
                         base_confidence, entry_price, stop_price, t1_price, t2_price)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                    RETURNING id
                """, values)
                event_id = cursor.fetchone()['id']
            else:
                cursor.execute(f"""
                    INSERT INTO signal_events
                        (ticker, signal_type, direction, grade, stage, session_date, hour_of_day,
                         base_confidence, entry_price, stop_price, t1_price, t2_price)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                """, values)
                event_id = cursor.lastrowid

            conn.commit()

            # Cache in session
            self.session_signals[ticker] = {
                'event_id': event_id,
                'stage': 'GENERATED',
                'timestamp': datetime.now(ET)
            }

            return event_id
        except Exception as e:
            logger.info(f"[ANALYTICS] record_signal_generated error for {ticker}: {e}")
            return -1
        finally:
            if conn:
                return_conn(conn)

    def record_validation_result(
        self,
        ticker: str,
        passed: bool,
        confidence_after: float = 0.0,
        ivr_multiplier: float = 1.0,
        uoa_multiplier: float = 1.0,
        gex_multiplier: float = 1.0,
        mtf_boost: float = 0.0,
        ticker_multiplier: float = 1.0,
        ivr_label: str = "",
        uoa_label: str = "",
        gex_label: str = "",
        checks_passed: List[str] = None,
        rejection_reason: str = ""
    ) -> int:
        """
        Record validation result (signal_validator.py output).

        Returns:
            Signal event ID
        """
        cached = self.session_signals.get(ticker)
        if not cached or cached['stage'] != 'GENERATED':
            logger.info(f"[ANALYTICS] Warning: No GENERATED signal found for {ticker}")
            return -1

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            checks_str = ','.join(checks_passed) if checks_passed else ''
            stage = 'VALIDATED' if passed else 'REJECTED'

            values = (
                ticker, self.session_signals[ticker]['event_id'],
                stage, self._get_session_date(), self._get_hour_of_day(),
                confidence_after, int(passed), checks_str, rejection_reason,
                ivr_multiplier, uoa_multiplier, gex_multiplier, mtf_boost, ticker_multiplier,
                ivr_label, uoa_label, gex_label
            )

            if 'postgres' in str(type(cursor)):
                cursor.execute(f"""
                    INSERT INTO signal_events
                        (ticker, position_id, stage, session_date, hour_of_day,
                         final_confidence, validation_passed, validation_checks, rejection_reason,
                         ivr_multiplier, uoa_multiplier, gex_multiplier, mtf_boost, ticker_multiplier,
                         ivr_label, uoa_label, gex_label)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                    RETURNING id
                """, values)
                event_id = cursor.fetchone()['id']
            else:
                cursor.execute(f"""
                    INSERT INTO signal_events
                        (ticker, position_id, stage, session_date, hour_of_day,
                         final_confidence, validation_passed, validation_checks, rejection_reason,
                         ivr_multiplier, uoa_multiplier, gex_multiplier, mtf_boost, ticker_multiplier,
                         ivr_label, uoa_label, gex_label)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                """, values)
                event_id = cursor.lastrowid

            conn.commit()

            self.session_signals[ticker]['stage'] = stage
            self.session_signals[ticker]['validation_event_id'] = event_id

            return event_id
        except Exception as e:
            logger.info(f"[ANALYTICS] record_validation_result error for {ticker}: {e}")
            return -1
        finally:
            if conn:
                return_conn(conn)

    def record_signal_armed(
        self,
        ticker: str,
        final_confidence: float,
        bars_to_confirmation: int,
        confirmation_type: str = 'retest'
    ) -> int:
        """
        Record signal armed (passed confirmation via wait_for_confirmation).

        Returns:
            Signal event ID
        """
        cached = self.session_signals.get(ticker)
        if not cached or cached['stage'] != 'VALIDATED':
            logger.info(f"[ANALYTICS] Warning: No VALIDATED signal found for {ticker}")
            return -1

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            values = (
                ticker, cached.get('validation_event_id'),
                'ARMED', self._get_session_date(), self._get_hour_of_day(),
                final_confidence, bars_to_confirmation, confirmation_type
            )

            if 'postgres' in str(type(cursor)):
                cursor.execute(f"""
                    INSERT INTO signal_events
                        (ticker, position_id, stage, session_date, hour_of_day,
                         final_confidence, bars_to_confirmation, confirmation_type)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
                    RETURNING id
                """, values)
                event_id = cursor.fetchone()['id']
            else:
                cursor.execute(f"""
                    INSERT INTO signal_events
                        (ticker, position_id, stage, session_date, hour_of_day,
                         final_confidence, bars_to_confirmation, confirmation_type)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
                """, values)
                event_id = cursor.lastrowid

            conn.commit()

            self.session_signals[ticker]['stage'] = 'ARMED'
            self.session_signals[ticker]['armed_event_id'] = event_id

            return event_id
        except Exception as e:
            logger.info(f"[ANALYTICS] record_signal_armed error for {ticker}: {e}")
            return -1
        finally:
            if conn:
                return_conn(conn)

    def record_trade_executed(
        self,
        ticker: str,
        position_id: int
    ) -> int:
        """
        Record trade execution (position opened).
        Called by arm_signal.arm_ticker() after position_manager.open_position() returns > 0.

        Returns:
            Signal event ID
        """
        cached = self.session_signals.get(ticker)
        if not cached or cached['stage'] != 'ARMED':
            logger.info(f"[ANALYTICS] Warning: No ARMED signal found for {ticker}")
            return -1

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            values = (
                ticker, position_id,
                'TRADED', self._get_session_date(), self._get_hour_of_day()
            )

            if 'postgres' in str(type(cursor)):
                cursor.execute(f"""
                    INSERT INTO signal_events
                        (ticker, position_id, stage, session_date, hour_of_day)
                    VALUES ({p},{p},{p},{p},{p})
                    RETURNING id
                """, values)
                event_id = cursor.fetchone()['id']
            else:
                cursor.execute(f"""
                    INSERT INTO signal_events
                        (ticker, position_id, stage, session_date, hour_of_day)
                    VALUES ({p},{p},{p},{p},{p})
                """, values)
                event_id = cursor.lastrowid

            conn.commit()

            self.session_signals[ticker]['stage'] = 'TRADED'
            self.session_signals[ticker]['traded_event_id'] = event_id

            return event_id
        except Exception as e:
            logger.info(f"[ANALYTICS] record_trade_executed error for {ticker}: {e}")
            return -1
        finally:
            if conn:
                return_conn(conn)

    # ══════════════════════════════════════════════════════════════════════════
    # QUERY METHODS
    # ══════════════════════════════════════════════════════════════════════════

    def get_funnel_stats(self, session_date: str = None) -> Dict:
        """
        Get signal funnel conversion rates.

        Returns:
            {
                'generated': int,
                'validated': int,
                'armed': int,
                'traded': int,
                'rejected': int,
                'validation_rate': float,
                'arming_rate': float,
                'execution_rate': float
            }
        """
        session_date = session_date or self._get_session_date()

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            cursor.execute(f"""
                SELECT stage, COUNT(*) as count
                FROM signal_events
                WHERE session_date = {p}
                GROUP BY stage
            """, (session_date,))

            rows = cursor.fetchall()
        except Exception as e:
            logger.info(f"[ANALYTICS] get_funnel_stats error: {e}")
            rows = []
        finally:
            if conn:
                return_conn(conn)

        stage_counts = {row['stage']: row['count'] for row in rows}

        generated = stage_counts.get('GENERATED', 0)
        validated = stage_counts.get('VALIDATED', 0)
        armed     = stage_counts.get('ARMED', 0)
        traded    = stage_counts.get('TRADED', 0)
        rejected  = stage_counts.get('REJECTED', 0)

        return {
            'generated':       generated,
            'validated':       validated,
            'armed':           armed,
            'traded':          traded,
            'rejected':        rejected,
            'validation_rate': round((validated / generated * 100) if generated > 0 else 0, 1),
            'arming_rate':     round((armed / validated * 100) if validated > 0 else 0, 1),
            'execution_rate':  round((traded / armed * 100) if armed > 0 else 0, 1),
            'rejection_rate':  round((rejected / generated * 100) if generated > 0 else 0, 1),
        }

    def get_grade_distribution(self, session_date: str = None) -> Dict:
        """Get distribution of signals by grade."""
        session_date = session_date or self._get_session_date()

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            cursor.execute(f"""
                SELECT grade, COUNT(*) as count
                FROM signal_events
                WHERE session_date = {p} AND stage = 'GENERATED'
                GROUP BY grade
            """, (session_date,))

            rows = cursor.fetchall()
        except Exception as e:
            logger.info(f"[ANALYTICS] get_grade_distribution error: {e}")
            rows = []
        finally:
            if conn:
                return_conn(conn)

        grade_counts = {row['grade']: row['count'] for row in rows}
        total = sum(grade_counts.values())

        percentages = {
            grade: round((count / total * 100), 1) if total > 0 else 0
            for grade, count in grade_counts.items()
        }

        return {
            'counts': grade_counts,
            'percentages': percentages,
            'total': total
        }

    def get_multiplier_impact(self, session_date: str = None) -> Dict:
        """Analyze average multiplier effects on confidence."""
        session_date = session_date or self._get_session_date()

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            cursor.execute(f"""
                SELECT
                    AVG(ivr_multiplier) as ivr_avg,
                    AVG(uoa_multiplier) as uoa_avg,
                    AVG(gex_multiplier) as gex_avg,
                    AVG(mtf_boost) as mtf_avg,
                    AVG(base_confidence) as base_avg,
                    AVG(final_confidence) as final_avg
                FROM signal_events
                WHERE session_date = {p} AND stage = 'VALIDATED'
            """, (session_date,))

            row = cursor.fetchone()
        except Exception as e:
            logger.info(f"[ANALYTICS] get_multiplier_impact error: {e}")
            row = None
        finally:
            if conn:
                return_conn(conn)

        if not row or row['ivr_avg'] is None:
            return {
                'ivr_avg': 1.0, 'uoa_avg': 1.0, 'gex_avg': 1.0,
                'mtf_avg': 0.0, 'base_avg': 0.0, 'final_avg': 0.0,
                'total_boost_pct': 0.0
            }

        base_avg = row['base_avg'] or 0.7
        final_avg = row['final_avg'] or 0.7
        total_boost_pct = ((final_avg - base_avg) / base_avg * 100) if base_avg > 0 else 0

        return {
            'ivr_avg':         round(row['ivr_avg'] or 1.0, 3),
            'uoa_avg':         round(row['uoa_avg'] or 1.0, 3),
            'gex_avg':         round(row['gex_avg'] or 1.0, 3),
            'mtf_avg':         round(row['mtf_avg'] or 0.0, 3),
            'base_avg':        round(base_avg, 3),
            'final_avg':       round(final_avg, 3),
            'total_boost_pct': round(total_boost_pct, 1)
        }

    def get_rejection_breakdown(self, days: int = 7) -> Dict[str, int]:
        """
        Aggregate rejection_reason counts for REJECTED signals over the last N days.

        Answers: which validator checks (ADX, VOLUME, DMI, VWAP, etc.) kill the most
        signals — the #1 tuning insight for threshold optimisation.

        Returns:
            {rejection_reason: count} sorted by count descending.
            e.g. {'ADX,VOLUME': 12, 'DMI': 7, 'VWAP': 4}
        """
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT rejection_reason, COUNT(*) as count
                FROM signal_events
                WHERE stage = 'REJECTED'
                  AND session_date >= {p}
                  AND rejection_reason IS NOT NULL
                  AND rejection_reason != ''
                GROUP BY rejection_reason
                ORDER BY count DESC
            """, (cutoff,))
            rows = cursor.fetchall()
        except Exception as e:
            logger.info(f"[ANALYTICS] get_rejection_breakdown error: {e}")
            rows = []
        finally:
            if conn:
                return_conn(conn)
        return {row['rejection_reason']: row['count'] for row in rows}

    def get_hourly_funnel(self, days: int = 7) -> Dict[int, Dict]:
        """
        Signal funnel breakdown by hour of day over the last N days.

        Reveals whether 10 AM signals have 80% validation rate vs 2 PM at 30%,
        enabling data-driven hourly gate threshold tuning.

        Returns:
            {hour: {'generated': int, 'validated': int, 'armed': int, 'traded': int,
                    'rejected': int, 'validation_rate': float, 'arming_rate': float}}
        """
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT hour_of_day, stage, COUNT(*) as count
                FROM signal_events
                WHERE session_date >= {p}
                  AND hour_of_day IS NOT NULL
                GROUP BY hour_of_day, stage
                ORDER BY hour_of_day
            """, (cutoff,))
            rows = cursor.fetchall()
        except Exception as e:
            logger.info(f"[ANALYTICS] get_hourly_funnel error: {e}")
            rows = []
        finally:
            if conn:
                return_conn(conn)

        # Build nested dict: hour -> stage -> count
        hourly: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            hourly[row['hour_of_day']][row['stage']] = row['count']

        result = {}
        for hour in sorted(hourly.keys()):
            stages = hourly[hour]
            generated = stages.get('GENERATED', 0)
            validated = stages.get('VALIDATED', 0)
            armed     = stages.get('ARMED', 0)
            traded    = stages.get('TRADED', 0)
            rejected  = stages.get('REJECTED', 0)
            result[hour] = {
                'generated':       generated,
                'validated':       validated,
                'armed':           armed,
                'traded':          traded,
                'rejected':        rejected,
                'validation_rate': round((validated / generated * 100) if generated > 0 else 0, 1),
                'arming_rate':     round((armed / validated * 100) if validated > 0 else 0, 1),
            }
        return result

    def get_daily_summary(self, session_date: str = None) -> str:
        """Generate formatted daily summary report (printed to logs + sent to Discord at EOD)."""
        session_date = session_date or self._get_session_date()

        funnel    = self.get_funnel_stats(session_date)
        grades    = self.get_grade_distribution(session_date)
        mults     = self.get_multiplier_impact(session_date)
        rejections = self.get_rejection_breakdown(days=1)  # today only
        hourly    = self.get_hourly_funnel(days=1)          # today only

        lines = []
        lines.append("\n" + "="*80)
        lines.append("SIGNAL ANALYTICS - DAILY SUMMARY")
        lines.append("="*80)
        lines.append(f"Session Date: {session_date}\n")

        lines.append("── Signal Funnel " + "─"*62)
        lines.append(f"  Generated:  {funnel['generated']:>3}")
        lines.append(f"  Validated:  {funnel['validated']:>3}  ({funnel['validation_rate']:>5.1f}% pass rate)")
        lines.append(f"  Rejected:   {funnel['rejected']:>3}  ({funnel['rejection_rate']:>5.1f}% reject rate)")
        lines.append(f"  Armed:      {funnel['armed']:>3}  ({funnel['arming_rate']:>5.1f}% confirmation rate)")
        lines.append(f"  Traded:     {funnel['traded']:>3}  ({funnel['execution_rate']:>5.1f}% execution rate)\n")

        lines.append("── Grade Distribution " + "─"*57)
        for grade in ['A+', 'A', 'A-', 'B+', 'B']:
            count = grades['counts'].get(grade, 0)
            if count > 0:
                pct = grades['percentages'].get(grade, 0)
                lines.append(f"  {grade:<3}: {count:>3}  ({pct:>5.1f}%)")
        lines.append("")

        lines.append("── Multiplier Impact " + "─"*58)
        lines.append(f"  IVR Multiplier:  {mults['ivr_avg']:.3f}x")
        lines.append(f"  UOA Multiplier:  {mults['uoa_avg']:.3f}x")
        lines.append(f"  GEX Multiplier:  {mults['gex_avg']:.3f}x")
        lines.append(f"  MTF Boost:       +{mults['mtf_avg']:.3f}")
        lines.append(f"  Base → Final:    {mults['base_avg']:.3f} → {mults['final_avg']:.3f}  ({mults['total_boost_pct']:+.1f}%)")
        lines.append("")

        if rejections:
            lines.append("── Rejection Breakdown " + "─"*56)
            lines.append("  (validator checks that killed signals today)")
            for reason, count in list(rejections.items())[:10]:  # top 10
                lines.append(f"  {reason:<30} {count:>3}x")
            lines.append("")

        if hourly:
            lines.append("── Hourly Funnel " + "─"*61)
            lines.append(f"  {'Hour':<6} {'Gen':>4} {'Val':>4} {'Arm':>4} {'Trd':>4} {'Val%':>6} {'Arm%':>6}")
            for hour, data in sorted(hourly.items()):
                if data['generated'] > 0:
                    lines.append(
                        f"  {hour:02d}:00  "
                        f"{data['generated']:>4} "
                        f"{data['validated']:>4} "
                        f"{data['armed']:>4} "
                        f"{data['traded']:>4} "
                        f"{data['validation_rate']:>5.1f}% "
                        f"{data['arming_rate']:>5.1f}%"
                    )
            lines.append("")

        lines.append("="*80 + "\n")

        return "\n".join(lines)

    def get_discord_eod_summary(self, session_date: str = None) -> str:
        """
        Compact Discord-friendly EOD summary (no wide tables, uses emoji).
        Sent by eod_reporter.py via send_simple_message().
        """
        session_date = session_date or self._get_session_date()
        funnel     = self.get_funnel_stats(session_date)
        rejections = self.get_rejection_breakdown(days=1)

        lines = [
            f"📊 **Signal Funnel — {session_date}**",
            f"Generated: `{funnel['generated']}` → "
            f"Validated: `{funnel['validated']}` ({funnel['validation_rate']:.0f}%) → "
            f"Armed: `{funnel['armed']}` ({funnel['arming_rate']:.0f}%) → "
            f"Traded: `{funnel['traded']}` ({funnel['execution_rate']:.0f}%)",
        ]

        if funnel['rejected'] > 0:
            lines.append(f"Rejected: `{funnel['rejected']}` ({funnel['rejection_rate']:.0f}%)")

        if rejections:
            lines.append("")
            lines.append("🚫 **Top Rejection Reasons:**")
            for reason, count in list(rejections.items())[:5]:
                lines.append(f"  • `{reason}` — {count}x")

        return "\n".join(lines)

    def clear_session_cache(self):
        """Clear session cache (call at EOD)."""
        self.session_signals.clear()
        self.session_start = datetime.now(ET)
        logger.info("[ANALYTICS] Session cache cleared")


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

signal_tracker = SignalTracker()


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logger.info("Testing Signal Analytics System...\n")

    logger.info("1. Generating signal...")
    signal_tracker.record_signal_generated(
        ticker="SPY",
        signal_type="CFW6_OR",
        direction="bull",
        grade="A",
        confidence=0.72,
        entry_price=595.50,
        stop_price=594.00,
        t1_price=598.50,
        t2_price=600.75
    )

    logger.info("2. Recording validation result...")
    signal_tracker.record_validation_result(
        ticker="SPY",
        passed=True,
        confidence_after=0.81,
        ivr_multiplier=1.05,
        uoa_multiplier=1.10,
        gex_multiplier=0.98,
        mtf_boost=0.05,
        ticker_multiplier=1.02,
        ivr_label="IVR-FAVORABLE",
        uoa_label="UOA-ALIGNED-CALL",
        gex_label="GEX-NEUTRAL",
        checks_passed=['ADX', 'VOLUME', 'DMI', 'VPVR']
    )

    logger.info("3. Arming signal...")
    signal_tracker.record_signal_armed(
        ticker="SPY",
        final_confidence=0.81,
        bars_to_confirmation=3,
        confirmation_type="retest"
    )

    logger.info("4. Recording trade execution...")
    signal_tracker.record_trade_executed(
        ticker="SPY",
        position_id=42
    )

    logger.info("\n" + signal_tracker.get_daily_summary())

    funnel = signal_tracker.get_funnel_stats()
    logger.info("\nFunnel Visualization:")
    print(f"{funnel['generated']} generated → "
          f"{funnel['validated']} validated ({funnel['validation_rate']:.0f}%) → "
          f"{funnel['armed']} armed ({funnel['arming_rate']:.0f}%) → "
          f"{funnel['traded']} traded ({funnel['execution_rate']:.0f}%)")

    logger.info("\nRejection Breakdown (7d):")
    for reason, count in signal_tracker.get_rejection_breakdown(days=7).items():
        logger.info(f"  {reason}: {count}x")

    logger.info("\nHourly Funnel (7d):")
    for hour, data in signal_tracker.get_hourly_funnel(days=7).items():
        logger.info(f"  {hour:02d}:00  Gen={data['generated']} Val={data['validated']} ({data['validation_rate']:.0f}%)")
