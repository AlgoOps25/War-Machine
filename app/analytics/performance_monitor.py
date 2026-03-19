#!/usr/bin/env python3
"""
Performance Monitor — app.analytics.performance_monitor

Phase 4 live performance dashboard + risk alert system.
Tracks daily P&L, win rate, drawdown, and fires Discord alerts
when thresholds are breached.

sniper.py imports:
    from app.analytics.performance_monitor import (
        performance_monitor,
        check_performance_dashboard,
        check_performance_alerts,
    )

Used via:
    check_performance_dashboard(_state, PHASE_4_ENABLED)
    check_performance_alerts(_state, PHASE_4_ENABLED, alert_manager, send_simple_message)
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any
import logging
logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# ─────────────────────────────────────────────────────────────────────────────
# Dashboard print cadence (once per N scanner cycles)
# ─────────────────────────────────────────────────────────────────────────────
_DASHBOARD_INTERVAL_CYCLES = 60   # ~5 min at 5s/cycle
_ALERT_CHECK_INTERVAL_CYCLES = 20 # ~100s
_dashboard_cycle_counter = 0
_alert_cycle_counter = 0

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
_session: Dict = {
    'signals_generated': 0,
    'signals_armed': 0,
    'signals_rejected': 0,
    'wins': 0,
    'losses': 0,
    'total_pnl_pct': 0.0,
    'peak_pnl_pct': 0.0,
    'max_drawdown_pct': 0.0,
    'last_dashboard_ts': None,
    'risk_alerts_fired': 0,
}

# ─────────────────────────────────────────────────────────────────────────────
# DB bootstrap
# ─────────────────────────────────────────────────────────────────────────────
def _ensure_table():
    try:
        from app.data.db_connection import get_conn, serial_pk, return_conn
        conn = get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS performance_snapshots (
                    id {serial_pk()},
                    session_date DATE,
                    signals_generated INTEGER DEFAULT 0,
                    signals_armed INTEGER DEFAULT 0,
                    signals_rejected INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_pnl_pct REAL DEFAULT 0.0,
                    max_drawdown_pct REAL DEFAULT 0.0,
                    win_rate REAL DEFAULT 0.0,
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            return_conn(conn)
    except Exception as e:
        logger.info(f"[PERF-MONITOR] DB init error (non-fatal): {e}")


_ensure_table()


# ─────────────────────────────────────────────────────────────────────────────
# Public update API (called by signal_tracker in sniper.py)
# ─────────────────────────────────────────────────────────────────────────────
def record_signal_generated():
    _session['signals_generated'] += 1

def record_signal_armed():
    _session['signals_armed'] += 1

def record_signal_rejected():
    _session['signals_rejected'] += 1

def record_trade_outcome(pnl_pct: float):
    if pnl_pct >= 0:
        _session['wins'] += 1
    else:
        _session['losses'] += 1
    _session['total_pnl_pct'] += pnl_pct
    if _session['total_pnl_pct'] > _session['peak_pnl_pct']:
        _session['peak_pnl_pct'] = _session['total_pnl_pct']
    drawdown = _session['peak_pnl_pct'] - _session['total_pnl_pct']
    if drawdown > _session['max_drawdown_pct']:
        _session['max_drawdown_pct'] = drawdown


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot to DB (called EOD or on demand)
# ─────────────────────────────────────────────────────────────────────────────
def _persist_snapshot():
    try:
        from app.data.db_connection import get_conn, ph as _ph, return_conn
        conn = get_conn()
        today = datetime.now(_ET).date()
        total_closed = _session['wins'] + _session['losses']
        win_rate = (_session['wins'] / total_closed * 100) if total_closed > 0 else 0.0
        try:
            cursor = conn.cursor()
            p = _ph()
            cursor.execute(
                f"INSERT INTO performance_snapshots "
                f"(session_date, signals_generated, signals_armed, signals_rejected, "
                f" wins, losses, total_pnl_pct, max_drawdown_pct, win_rate, ts) "
                f"VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p})",
                (today,
                 _session['signals_generated'],
                 _session['signals_armed'],
                 _session['signals_rejected'],
                 _session['wins'],
                 _session['losses'],
                 _session['total_pnl_pct'],
                 _session['max_drawdown_pct'],
                 win_rate,
                 datetime.now(_ET))
            )
            conn.commit()
        finally:
            return_conn(conn)
    except Exception as e:
        logger.info(f"[PERF-MONITOR] Snapshot persist error (non-fatal): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard print
# ─────────────────────────────────────────────────────────────────────────────
def _print_dashboard():
    total_closed = _session['wins'] + _session['losses']
    win_rate = (_session['wins'] / total_closed * 100) if total_closed > 0 else 0.0
    now_str = datetime.now(_ET).strftime('%H:%M ET')
    print(
        f"[PERF-MONITOR] 📊 {now_str} | "
        f"Generated:{_session['signals_generated']} "
        f"Armed:{_session['signals_armed']} "
        f"Rejected:{_session['signals_rejected']} | "
        f"W:{_session['wins']} L:{_session['losses']} "
        f"WR:{win_rate:.0f}% | "
        f"P&L:{_session['total_pnl_pct']:+.2f}% "
        f"MaxDD:{_session['max_drawdown_pct']:.2f}%"
    )
    _session['last_dashboard_ts'] = datetime.now(_ET)


# ─────────────────────────────────────────────────────────────────────────────
# Risk alert checks
# ─────────────────────────────────────────────────────────────────────────────
_MAX_DAILY_LOSS_PCT    = -3.0   # stop signaling if daily P&L < -3%
_MAX_DRAWDOWN_PCT      = 4.0    # alert if drawdown exceeds 4%
_MAX_CONSECUTIVE_LOSS  = 3      # alert after 3 losses in a row
_consecutive_losses    = 0

def _check_risk_alerts(send_fn) -> bool:
    """Returns True if a halt condition is active."""
    global _consecutive_losses
    alerts = []

    if _session['total_pnl_pct'] < _MAX_DAILY_LOSS_PCT:
        alerts.append(
            f"🚨 DAILY LOSS LIMIT: P&L={_session['total_pnl_pct']:+.2f}% < {_MAX_DAILY_LOSS_PCT}%"
        )

    if _session['max_drawdown_pct'] >= _MAX_DRAWDOWN_PCT:
        alerts.append(
            f"⚠️ MAX DRAWDOWN: {_session['max_drawdown_pct']:.2f}% >= {_MAX_DRAWDOWN_PCT}%"
        )

    for alert in alerts:
        logger.info(f"[PERF-MONITOR] {alert}")
        _session['risk_alerts_fired'] += 1
        if send_fn:
            try:
                send_fn(alert)
            except Exception:
                pass

    return _session['total_pnl_pct'] < _MAX_DAILY_LOSS_PCT


# ─────────────────────────────────────────────────────────────────────────────
# Singleton class
# ─────────────────────────────────────────────────────────────────────────────
class PerformanceMonitor:
    def record_signal_generated(self, **kwargs) -> None:
        record_signal_generated()

    def record_signal_armed(self, **kwargs) -> None:
        record_signal_armed()

    def record_signal_rejected(self, **kwargs) -> None:
        record_signal_rejected()

    def record_trade_outcome(self, pnl_pct: float = 0.0, **kwargs) -> None:
        record_trade_outcome(pnl_pct)

    def get_daily_stats(self) -> Dict:
        total_closed = _session['wins'] + _session['losses']
        win_rate = (_session['wins'] / total_closed * 100) if total_closed > 0 else 0.0
        return {
            **_session,
            'win_rate_pct': win_rate,
            'total_closed': total_closed,
        }

    def print_eod_report(self) -> None:
        _print_dashboard()
        _persist_snapshot()

    def reset_daily_stats(self) -> None:
        _session.update({
            'signals_generated': 0, 'signals_armed': 0, 'signals_rejected': 0,
            'wins': 0, 'losses': 0, 'total_pnl_pct': 0.0,
            'peak_pnl_pct': 0.0, 'max_drawdown_pct': 0.0,
            'last_dashboard_ts': None, 'risk_alerts_fired': 0,
        })


# Singleton
performance_monitor = PerformanceMonitor()


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers called directly by sniper.py
# check_performance_dashboard(_state, PHASE_4_ENABLED)
# check_performance_alerts(_state, PHASE_4_ENABLED, alert_manager, send_simple_message)
# ─────────────────────────────────────────────────────────────────────────────
def check_performance_dashboard(state, phase_4_enabled: bool) -> None:
    """Called every scanner cycle. Prints dashboard every ~5 min."""
    if not phase_4_enabled:
        return
    global _dashboard_cycle_counter
    _dashboard_cycle_counter += 1
    if _dashboard_cycle_counter >= _DASHBOARD_INTERVAL_CYCLES:
        _dashboard_cycle_counter = 0
        _print_dashboard()


def check_performance_alerts(state, phase_4_enabled: bool,
                              alert_manager, send_fn) -> None:
    """Called every scanner cycle. Checks risk thresholds every ~100s."""
    if not phase_4_enabled:
        return
    global _alert_cycle_counter
    _alert_cycle_counter += 1
    if _alert_cycle_counter >= _ALERT_CHECK_INTERVAL_CYCLES:
        _alert_cycle_counter = 0
        _check_risk_alerts(send_fn)
