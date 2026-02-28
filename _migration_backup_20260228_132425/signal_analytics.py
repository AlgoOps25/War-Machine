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

Usage:
  # In sniper.py after pattern detection:
  from signal_analytics import signal_tracker
  signal_tracker.record_signal_generated(ticker, 'CFW6_OR', 'bull', grade='A', confidence=0.72)
  
  # In signal_validator.py after validation:
  signal_tracker.record_validation_result(ticker, passed=True, confidence_after=0.78)
  
  # In sniper.py after confirmation:
  signal_tracker.record_signal_armed(ticker, final_confidence=0.81)
  
  # In position_manager.py when trade opens:
  signal_tracker.record_trade_executed(ticker, position_id=123)
  
  # EOD summary:
  stats = signal_tracker.get_daily_summary()
  funnel = signal_tracker.get_funnel_stats()
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import statistics
from collections import defaultdict
from db_connection import get_conn, ph, dict_cursor, serial_pk

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
        
        # Create indexes for fast queries
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
        
        conn.commit()
        conn.close()
        
        print("[ANALYTICS] Signal tracking database initialized")
    
    def _get_session_date(self) -> str:
        """Get current trading session date (ET timezone)."""
        return datetime.now(ET).strftime("%Y-%m-%d")
    
    def _get_hour_of_day(self) -> int:
        """Get current hour (0-23) in ET timezone."""
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
        
        Args:
            ticker: Stock symbol
            signal_type: 'CFW6_OR' or 'CFW6_INTRADAY'
            direction: 'bull' or 'bear'
            grade: 'A+', 'A', or 'A-'
            confidence: Base confidence before multipliers
            entry_price: Proposed entry price
            stop_price: Proposed stop loss
            t1_price: Target 1 price
            t2_price: Target 2 price
        
        Returns:
            Signal event ID
        """
        p = ph()
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
        conn.close()
        
        # Cache in session
        self.session_signals[ticker] = {
            'event_id': event_id,
            'stage': 'GENERATED',
            'timestamp': datetime.now(ET)
        }
        
        return event_id
    
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
        
        Args:
            ticker: Stock symbol
            passed: Whether signal passed validation
            confidence_after: Confidence after multipliers applied
            ivr_multiplier: IV Rank multiplier effect
            uoa_multiplier: Unusual Options Activity multiplier
            gex_multiplier: Gamma Exposure multiplier
            mtf_boost: Multi-timeframe convergence boost
            ticker_multiplier: Ticker-specific learning multiplier
            ivr_label: IVR category label
            uoa_label: UOA category label
            gex_label: GEX category label
            checks_passed: List of validator checks that passed
            rejection_reason: Why signal was rejected (if failed)
        
        Returns:
            Signal event ID
        """
        # Get latest signal for this ticker
        cached = self.session_signals.get(ticker)
        if not cached or cached['stage'] != 'GENERATED':
            print(f"[ANALYTICS] Warning: No GENERATED signal found for {ticker}")
            return -1
        
        p = ph()
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
        
        # Create new event linked to original GENERATED event
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
        conn.close()
        
        # Update cache
        self.session_signals[ticker]['stage'] = stage
        self.session_signals[ticker]['validation_event_id'] = event_id
        
        return event_id
    
    def record_signal_armed(
        self,
        ticker: str,
        final_confidence: float,
        bars_to_confirmation: int,
        confirmation_type: str = 'retest'
    ) -> int:
        """
        Record signal armed (passed confirmation via wait_for_confirmation).
        
        Args:
            ticker: Stock symbol
            final_confidence: Final confidence after all adjustments
            bars_to_confirmation: Number of bars waited for confirmation
            confirmation_type: 'retest' or 'rejection'
        
        Returns:
            Signal event ID
        """
        cached = self.session_signals.get(ticker)
        if not cached or cached['stage'] != 'VALIDATED':
            print(f"[ANALYTICS] Warning: No VALIDATED signal found for {ticker}")
            return -1
        
        p = ph()
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
        conn.close()
        
        self.session_signals[ticker]['stage'] = 'ARMED'
        self.session_signals[ticker]['armed_event_id'] = event_id
        
        return event_id
    
    def record_trade_executed(
        self,
        ticker: str,
        position_id: int
    ) -> int:
        """
        Record trade execution (position opened).
        
        Args:
            ticker: Stock symbol
            position_id: Position ID from position_manager
        
        Returns:
            Signal event ID
        """
        cached = self.session_signals.get(ticker)
        if not cached or cached['stage'] != 'ARMED':
            print(f"[ANALYTICS] Warning: No ARMED signal found for {ticker}")
            return -1
        
        p = ph()
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
        conn.close()
        
        self.session_signals[ticker]['stage'] = 'TRADED'
        self.session_signals[ticker]['traded_event_id'] = event_id
        
        return event_id
    
    def get_funnel_stats(self, session_date: str = None) -> Dict:
        """
        Get signal funnel conversion rates.
        
        Args:
            session_date: Specific date or None for today
        
        Returns:
            {
                'generated': int,
                'validated': int,
                'armed': int,
                'traded': int,
                'validation_rate': float,  # % of generated that validated
                'arming_rate': float,      # % of validated that armed
                'execution_rate': float    # % of armed that traded
            }
        """
        session_date = session_date or self._get_session_date()
        
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute(f"""
            SELECT stage, COUNT(*) as count
            FROM signal_events
            WHERE session_date = {p}
            GROUP BY stage
        """, (session_date,))
        
        rows = cursor.fetchall()
        conn.close()
        
        stage_counts = {row['stage']: row['count'] for row in rows}
        
        generated = stage_counts.get('GENERATED', 0)
        validated = stage_counts.get('VALIDATED', 0)
        armed = stage_counts.get('ARMED', 0)
        traded = stage_counts.get('TRADED', 0)
        
        validation_rate = (validated / generated * 100) if generated > 0 else 0
        arming_rate = (armed / validated * 100) if validated > 0 else 0
        execution_rate = (traded / armed * 100) if armed > 0 else 0
        
        return {
            'generated': generated,
            'validated': validated,
            'armed': armed,
            'traded': traded,
            'validation_rate': round(validation_rate, 1),
            'arming_rate': round(arming_rate, 1),
            'execution_rate': round(execution_rate, 1)
        }
    
    def get_grade_distribution(self, session_date: str = None) -> Dict:
        """
        Get distribution of signals by grade.
        
        Returns:
            {'A+': count, 'A': count, 'A-': count, 'percentages': {...}}
        """
        session_date = session_date or self._get_session_date()
        
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute(f"""
            SELECT grade, COUNT(*) as count
            FROM signal_events
            WHERE session_date = {p} AND stage = 'GENERATED'
            GROUP BY grade
        """, (session_date,))
        
        rows = cursor.fetchall()
        conn.close()
        
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
        """
        Analyze average multiplier effects on confidence.
        
        Returns:
            {
                'ivr_avg': float,
                'uoa_avg': float,
                'gex_avg': float,
                'mtf_avg': float,
                'total_boost_avg': float
            }
        """
        session_date = session_date or self._get_session_date()
        
        p = ph()
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
        conn.close()
        
        if not row or row['ivr_avg'] is None:
            return {
                'ivr_avg': 1.0,
                'uoa_avg': 1.0,
                'gex_avg': 1.0,
                'mtf_avg': 0.0,
                'base_avg': 0.0,
                'final_avg': 0.0,
                'total_boost_pct': 0.0
            }
        
        base_avg = row['base_avg'] or 0.7
        final_avg = row['final_avg'] or 0.7
        total_boost_pct = ((final_avg - base_avg) / base_avg * 100) if base_avg > 0 else 0
        
        return {
            'ivr_avg': round(row['ivr_avg'] or 1.0, 3),
            'uoa_avg': round(row['uoa_avg'] or 1.0, 3),
            'gex_avg': round(row['gex_avg'] or 1.0, 3),
            'mtf_avg': round(row['mtf_avg'] or 0.0, 3),
            'base_avg': round(base_avg, 3),
            'final_avg': round(final_avg, 3),
            'total_boost_pct': round(total_boost_pct, 1)
        }
    
    def get_daily_summary(self, session_date: str = None) -> str:
        """
        Generate formatted daily summary report.
        
        Returns:
            Formatted string with all key metrics
        """
        session_date = session_date or self._get_session_date()
        
        funnel = self.get_funnel_stats(session_date)
        grades = self.get_grade_distribution(session_date)
        mults = self.get_multiplier_impact(session_date)
        
        lines = []
        lines.append("\n" + "="*80)
        lines.append("SIGNAL ANALYTICS - DAILY SUMMARY")
        lines.append("="*80)
        lines.append(f"Session Date: {session_date}\n")
        
        lines.append("── Signal Funnel " + "─"*62)
        lines.append(f"  Generated:  {funnel['generated']:>3}")
        lines.append(f"  Validated:  {funnel['validated']:>3}  ({funnel['validation_rate']:>5.1f}% pass rate)")
        lines.append(f"  Armed:      {funnel['armed']:>3}  ({funnel['arming_rate']:>5.1f}% confirmation rate)")
        lines.append(f"  Traded:     {funnel['traded']:>3}  ({funnel['execution_rate']:>5.1f}% execution rate)\n")
        
        lines.append("── Grade Distribution " + "─"*57)
        for grade in ['A+', 'A', 'A-']:
            count = grades['counts'].get(grade, 0)
            pct = grades['percentages'].get(grade, 0)
            lines.append(f"  {grade:<3}: {count:>3}  ({pct:>5.1f}%)")
        lines.append("")
        
        lines.append("── Multiplier Impact " + "─"*58)
        lines.append(f"  IVR Multiplier:  {mults['ivr_avg']:.3f}x")
        lines.append(f"  UOA Multiplier:  {mults['uoa_avg']:.3f}x")
        lines.append(f"  GEX Multiplier:  {mults['gex_avg']:.3f}x")
        lines.append(f"  MTF Boost:       +{mults['mtf_avg']:.3f}")
        lines.append(f"  Base → Final:    {mults['base_avg']:.3f} → {mults['final_avg']:.3f}  ({mults['total_boost_pct']:+.1f}%)")
        lines.append("="*80 + "\n")
        
        return "\n".join(lines)
    
    def clear_session_cache(self):
        """Clear session cache (call at EOD)."""
        self.session_signals.clear()
        self.session_start = datetime.now(ET)
        print("[ANALYTICS] Session cache cleared")


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

signal_tracker = SignalTracker()


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Signal Analytics System...\n")
    
    # Simulate signal lifecycle
    print("1. Generating signal...")
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
    
    print("2. Recording validation result...")
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
    
    print("3. Arming signal...")
    signal_tracker.record_signal_armed(
        ticker="SPY",
        final_confidence=0.81,
        bars_to_confirmation=3,
        confirmation_type="retest"
    )
    
    print("4. Recording trade execution...")
    signal_tracker.record_trade_executed(
        ticker="SPY",
        position_id=42
    )
    
    # Generate summary
    print("\n" + signal_tracker.get_daily_summary())
    
    # Test funnel stats
    funnel = signal_tracker.get_funnel_stats()
    print("\nFunnel Visualization:")
    print(f"{funnel['generated']} generated → "
          f"{funnel['validated']} validated ({funnel['validation_rate']:.0f}%) → "
          f"{funnel['armed']} armed ({funnel['arming_rate']:.0f}%) → "
          f"{funnel['traded']} traded ({funnel['execution_rate']:.0f}%)")
