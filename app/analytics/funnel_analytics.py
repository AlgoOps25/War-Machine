"""
Funnel Analytics Dashboard - Real-Time Conversion Tracking

Tracks signal progression through the complete funnel:
  SCREENED → BOS → FVG → VALIDATOR → ARMED → FIRED → FILLED

Provides:
  - Real-time conversion rates at each stage
  - Rejection reason tracking
  - Hourly breakdown
  - Integration with existing signal_analytics.py

Usage:
  from app.analytics.funnel_analytics import funnel_tracker
  
  # Record stage progression
  funnel_tracker.record_stage('AAPL', 'SCREENED', passed=True)
  funnel_tracker.record_stage('AAPL', 'BOS', passed=True)
  funnel_tracker.record_stage('AAPL', 'FVG', passed=False, reason='low_volume')
  
  # Get daily report
  report = funnel_tracker.get_daily_report()
  logger.info(report)
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from app.data.db_connection import get_conn, return_conn, ph, dict_cursor, serial_pk
import logging
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


class FunnelTracker:
    """Tracks signal funnel conversion rates and rejection reasons."""
    
    # Funnel stages in order
    STAGES = ['SCREENED', 'BOS', 'FVG', 'VALIDATOR', 'ARMED', 'FIRED', 'FILLED']
    
    def __init__(self):
        self._initialize_database()
        
        # In-memory counters for fast lookups
        self.daily_counters: Dict[str, int] = defaultdict(int)
        self.rejection_counts: Dict[str, int] = defaultdict(int)
        self.last_reset = datetime.now(ET).date()
    
    def _initialize_database(self):
        """Create funnel_events table."""
        conn = None
        try:
            conn = get_conn()
            cursor = conn.cursor()
            
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS funnel_events (
                    id {serial_pk()},
                    ticker TEXT NOT NULL,
                    session TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    reason TEXT,
                    confidence REAL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    signal_id TEXT,
                    hour INTEGER
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_funnel_session_stage
                ON funnel_events(session, stage)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_funnel_ticker
                ON funnel_events(ticker, session)
            """)
            
            conn.commit()
            logger.info("[FUNNEL] Funnel analytics database initialized")
        except Exception as e:
            logger.info(f"[FUNNEL] Init error: {e}")
        finally:
            return_conn(conn)
    
    def _get_session(self) -> str:
        """Get current session date."""
        return datetime.now(ET).strftime("%Y-%m-%d")
    
    def _get_hour(self) -> int:
        """Get current hour (0-23)."""
        return datetime.now(ET).hour
    
    def _reset_daily_if_needed(self):
        """Reset daily counters if new trading day."""
        today = datetime.now(ET).date()
        if today != self.last_reset:
            self.daily_counters.clear()
            self.rejection_counts.clear()
            self.last_reset = today
    
    def record_stage(
        self,
        ticker: str,
        stage: str,
        passed: bool,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        signal_id: Optional[str] = None
    ):
        """
        Record signal progression through a funnel stage.
        
        Args:
            ticker: Stock symbol
            stage: Funnel stage (SCREENED, BOS, FVG, VALIDATOR, ARMED, FIRED, FILLED)
            passed: Whether signal passed this stage
            reason: Rejection reason if failed
            confidence: Signal confidence at this stage
            signal_id: Optional signal ID for linking
        """
        self._reset_daily_if_needed()
        
        session = self._get_session()
        hour = self._get_hour()
        
        # Update in-memory counters
        counter_key = f"{stage}_{'PASS' if passed else 'FAIL'}"
        self.daily_counters[counter_key] += 1
        
        if not passed and reason:
            self.rejection_counts[reason] += 1
        
        # Write to database
        conn = None
        try:
            p = ph()
            conn = get_conn()
            cursor = conn.cursor()
            
            cursor.execute(f"""
                INSERT INTO funnel_events
                    (ticker, session, stage, passed, reason, confidence, hour, signal_id)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (ticker, session, stage, int(passed), reason, confidence, hour, signal_id))
            
            conn.commit()
        except Exception as e:
            logger.info(f"[FUNNEL] record_stage error: {e}")
        finally:
            return_conn(conn)
    
    def get_stage_conversion(self, stage: str, session: Optional[str] = None) -> Dict:
        """
        Get conversion rate for a specific stage.
        
        Args:
            stage: Funnel stage
            session: Session date (defaults to today)
        
        Returns:
            {
                'total': int,
                'passed': int,
                'failed': int,
                'conversion_rate': float
            }
        """
        session = session or self._get_session()
        conn = None
        try:
            p = ph()
            conn = get_conn()
            cursor = dict_cursor(conn)
            
            cursor.execute(f"""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) as passed,
                    SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) as failed
                FROM funnel_events
                WHERE session = {p} AND stage = {p}
            """, (session, stage))
            
            row = cursor.fetchone()
        except Exception as e:
            logger.info(f"[FUNNEL] get_stage_conversion error: {e}")
            row = None
        finally:
            return_conn(conn)
        
        if not row:
            return {'total': 0, 'passed': 0, 'failed': 0, 'conversion_rate': 0}
        
        total = row['total'] or 0
        passed = row['passed'] or 0
        failed = row['failed'] or 0
        conversion_rate = (passed / total * 100) if total > 0 else 0
        
        return {
            'total': total,
            'passed': passed,
            'failed': failed,
            'conversion_rate': round(conversion_rate, 1)
        }
    
    def get_rejection_reasons(self, session: Optional[str] = None, limit: int = 10) -> List[Tuple[str, int]]:
        """
        Get top rejection reasons across all stages.
        
        Args:
            session: Session date (defaults to today)
            limit: Max number of reasons to return
        
        Returns:
            List of (reason, count) tuples sorted by count descending
        """
        session = session or self._get_session()
        conn = None
        try:
            p = ph()
            conn = get_conn()
            cursor = dict_cursor(conn)
            
            cursor.execute(f"""
                SELECT reason, COUNT(*) as count
                FROM funnel_events
                WHERE session = {p} AND passed = 0 AND reason IS NOT NULL
                GROUP BY reason
                ORDER BY count DESC
                LIMIT {p}
            """, (session, limit))
            
            rows = cursor.fetchall()
        except Exception as e:
            logger.info(f"[FUNNEL] get_rejection_reasons error: {e}")
            rows = []
        finally:
            return_conn(conn)
        
        return [(row['reason'], row['count']) for row in rows]
    
    def get_daily_report(self, session: Optional[str] = None) -> str:
        """
        Generate formatted daily funnel report.
        
        Args:
            session: Session date (defaults to today)
        
        Returns:
            Formatted report string
        """
        session = session or self._get_session()
        
        lines = []
        lines.append("\n" + "="*80)
        lines.append("📊 SIGNAL FUNNEL REPORT")
        lines.append("="*80)
        lines.append(f"Session: {session}\n")
        
        # Get conversion rates for each stage
        prev_passed = None
        
        for stage in self.STAGES:
            stats = self.get_stage_conversion(stage, session)
            
            if stats['total'] == 0:
                continue
            
            # Calculate conversion from previous stage
            if prev_passed is not None and prev_passed > 0:
                from_prev_pct = (stats['passed'] / prev_passed * 100)
                lines.append(f"{stage:<12} {stats['total']:>3}  ({from_prev_pct:>5.1f}% of {self.STAGES[self.STAGES.index(stage)-1]})")
            else:
                lines.append(f"{stage:<12} {stats['total']:>3}")
            
            prev_passed = stats['passed']
        
        # Rejection reasons
        lines.append("\n" + "─"*80)
        lines.append("❌ TOP REJECTIONS:\n")
        
        rejections = self.get_rejection_reasons(session, limit=5)
        if rejections:
            for reason, count in rejections:
                lines.append(f"  {reason:<30} {count:>3} signals filtered")
        else:
            lines.append("  No rejections recorded")
        
        lines.append("="*80 + "\n")
        
        return "\n".join(lines)
    
    def get_hourly_breakdown(self, session: Optional[str] = None) -> Dict[int, Dict]:
        """
        Get funnel stats broken down by hour.
        
        Args:
            session: Session date (defaults to today)
        
        Returns:
            Dict mapping hour (0-23) to stage counts
        """
        session = session or self._get_session()
        conn = None
        try:
            p = ph()
            conn = get_conn()
            cursor = dict_cursor(conn)
            
            cursor.execute(f"""
                SELECT hour, stage, COUNT(*) as count
                FROM funnel_events
                WHERE session = {p} AND passed = 1
                GROUP BY hour, stage
                ORDER BY hour
            """, (session,))
            
            rows = cursor.fetchall()
        except Exception as e:
            logger.info(f"[FUNNEL] get_hourly_breakdown error: {e}")
            rows = []
        finally:
            return_conn(conn)
        
        hourly = defaultdict(lambda: defaultdict(int))
        for row in rows:
            hourly[row['hour']][row['stage']] = row['count']
        
        return dict(hourly)


# Global tracker instance
funnel_tracker = FunnelTracker()


# ═════════════════════════════════════════════════════════════════════════════
# INTEGRATION HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def log_screened(ticker: str, passed: bool, reason: str = None):
    """Convenience function for logging SCREENED stage."""
    funnel_tracker.record_stage(ticker, 'SCREENED', passed, reason)

def log_bos(ticker: str, passed: bool, reason: str = None):
    """Convenience function for logging BOS stage."""
    funnel_tracker.record_stage(ticker, 'BOS', passed, reason)

def log_fvg(ticker: str, passed: bool, reason: str = None, confidence: float = None):
    """Convenience function for logging FVG stage."""
    funnel_tracker.record_stage(ticker, 'FVG', passed, reason, confidence)

def log_validator(ticker: str, passed: bool, reason: str = None, confidence: float = None):
    """Convenience function for logging VALIDATOR stage."""
    funnel_tracker.record_stage(ticker, 'VALIDATOR', passed, reason, confidence)

def log_armed(ticker: str, passed: bool = True, confidence: float = None):
    """Convenience function for logging ARMED stage."""
    funnel_tracker.record_stage(ticker, 'ARMED', passed, None, confidence)

def log_fired(ticker: str, passed: bool = True, confidence: float = None):
    """Convenience function for logging FIRED stage."""
    funnel_tracker.record_stage(ticker, 'FIRED', passed, None, confidence)

def log_filled(ticker: str, passed: bool = True):
    """Convenience function for logging FILLED stage."""
    funnel_tracker.record_stage(ticker, 'FILLED', passed)


if __name__ == "__main__":
    logger.info("Testing Funnel Analytics...\n")
    
    # Simulate funnel progression
    funnel_tracker.record_stage('AAPL', 'SCREENED', True)
    funnel_tracker.record_stage('AAPL', 'BOS', True)
    funnel_tracker.record_stage('AAPL', 'FVG', True, confidence=0.75)
    funnel_tracker.record_stage('AAPL', 'VALIDATOR', False, reason='low_volume')
    
    funnel_tracker.record_stage('TSLA', 'SCREENED', True)
    funnel_tracker.record_stage('TSLA', 'BOS', True)
    funnel_tracker.record_stage('TSLA', 'FVG', False, reason='vix_too_high')
    
    funnel_tracker.record_stage('NVDA', 'SCREENED', True)
    funnel_tracker.record_stage('NVDA', 'BOS', True)
    funnel_tracker.record_stage('NVDA', 'FVG', True, confidence=0.82)
    funnel_tracker.record_stage('NVDA', 'VALIDATOR', True, confidence=0.85)
    funnel_tracker.record_stage('NVDA', 'ARMED', True, confidence=0.88)
    funnel_tracker.record_stage('NVDA', 'FIRED', True)
    
    # Generate report
    logger.info(funnel_tracker.get_daily_report())
