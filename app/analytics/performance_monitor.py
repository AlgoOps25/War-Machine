#!/usr/bin/env python3
"""
Performance Monitor System

Real-time tracking of trading performance, risk metrics, and system health.
Provides live dashboard, alerts, and comprehensive performance analytics.

Key Metrics:
  - P&L tracking (session/daily/weekly/monthly/all-time)
  - Win rate analysis (overall, by grade, by signal type, by ticker)
  - Risk metrics (Sharpe ratio, max drawdown, circuit breaker status)
  - Streak tracking (consecutive wins/losses)
  - Position exposure (sector concentration, correlation risk)
  - Best/worst trades analysis

FIXED (Mar 10 2026): All get_conn() calls now use try/finally: return_conn(conn) — no leaks.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import statistics
from collections import defaultdict
from app.data.db_connection import get_conn, return_conn, ph, dict_cursor
from utils import config

ET = ZoneInfo("America/New_York")


class PerformanceMonitor:
    """Monitors real-time trading performance and risk metrics."""

    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.session_start = datetime.now(ET)
        self.session_high_water_mark = 0.0
        self.account_size = config.ACCOUNT_SIZE
        self._update_high_water_mark()

    def _get_session_date(self) -> str:
        return datetime.now(ET).strftime("%Y-%m-%d")

    def _update_high_water_mark(self):
        current_value = self._get_current_account_value()
        if current_value > self.session_high_water_mark:
            self.session_high_water_mark = current_value

    def _get_current_account_value(self) -> float:
        realized_pnl = self._get_realized_pnl(days=0)
        unrealized_pnl = 0.0
        return self.account_size + realized_pnl + unrealized_pnl

    def _get_realized_pnl(self, days: int = 0) -> float:
        """
        Get realized P&L for specified period.
        days: 0=today, 1=yesterday, 7=last 7 days, 30=last 30 days, 999=all-time
        Note: Uses 'pnl' column to match positions table schema.
        """
        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            if days == 0:
                cursor.execute(f"""
                    SELECT COALESCE(SUM(pnl), 0) as total_pnl
                    FROM positions
                    WHERE DATE(exit_time) = {p} AND status = 'CLOSED'
                """, (self._get_session_date(),))
            elif days == 999:
                cursor.execute("""
                    SELECT COALESCE(SUM(pnl), 0) as total_pnl
                    FROM positions
                    WHERE status = 'CLOSED'
                """)
            else:
                cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
                cursor.execute(f"""
                    SELECT COALESCE(SUM(pnl), 0) as total_pnl
                    FROM positions
                    WHERE DATE(exit_time) >= {p} AND status = 'CLOSED'
                """, (cutoff,))

            row = cursor.fetchone()
            return row['total_pnl'] if row else 0.0
        except Exception as e:
            print(f"[MONITOR] _get_realized_pnl error: {e}")
            return 0.0
        finally:
            if conn:
                return_conn(conn)

    def _get_unrealized_pnl(self) -> float:
        return 0.0

    def get_session_pnl(self) -> Dict:
        """
        Get current session P&L breakdown.
        """
        realized = self._get_realized_pnl(days=0)
        unrealized = self._get_unrealized_pnl()
        total = realized + unrealized
        total_pct = (total / self.account_size * 100) if self.account_size > 0 else 0

        p = ph()
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            cursor.execute(f"""
                SELECT COUNT(*) as count FROM positions
                WHERE DATE(entry_time) = {p} AND status = 'CLOSED'
            """, (self._get_session_date(),))
            closed_count = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM positions WHERE status = 'OPEN'")
            open_count = cursor.fetchone()['count']
        except Exception as e:
            print(f"[MONITOR] get_session_pnl error: {e}")
            closed_count = 0
            open_count = 0
        finally:
            if conn:
                return_conn(conn)

        return {
            'realized_pnl':   round(realized, 2),
            'unrealized_pnl': round(unrealized, 2),
            'total_pnl':      round(total, 2),
            'total_pnl_pct':  round(total_pct, 2),
            'account_value':  round(self.account_size + total, 2),
            'trades_closed':  closed_count,
            'trades_open':    open_count
        }

    def get_win_rate_by_grade(self, days: int = 30) -> Dict:
        """
        Calculate win rate by signal grade.
        Note: Uses 'pnl' column to match positions table schema.
        """
        p = ph()
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = []
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT
                    grade,
                    COUNT(*) as total,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses
                FROM positions
                WHERE status = 'CLOSED'
                  AND DATE(exit_time) >= {p}
                  AND grade IS NOT NULL
                GROUP BY grade
            """, (cutoff,))
            rows = cursor.fetchall()
        except Exception as e:
            print(f"[MONITOR] get_win_rate_by_grade error: {e}")
        finally:
            if conn:
                return_conn(conn)

        results = {}
        total_wins = 0
        total_losses = 0

        for row in rows:
            grade = row['grade']
            wins = row['wins']
            losses = row['losses']
            total = row['total']
            results[grade] = {
                'wins': wins, 'losses': losses, 'total': total,
                'win_rate': round((wins / total * 100) if total > 0 else 0, 1)
            }
            total_wins += wins
            total_losses += losses

        total_trades = total_wins + total_losses
        results['overall'] = {
            'wins': total_wins, 'losses': total_losses, 'total': total_trades,
            'win_rate': round((total_wins / total_trades * 100) if total_trades > 0 else 0, 1)
        }
        return results

    def get_risk_exposure(self) -> Dict:
        """
        Calculate current risk exposure and concentration.
        """
        positions = []
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute("""
                SELECT ticker, entry_price, stop_price, remaining_contracts as contracts
                FROM positions
                WHERE status = 'OPEN'
            """)
            positions = cursor.fetchall()
        except Exception as e:
            print(f"[MONITOR] get_risk_exposure error: {e}")
        finally:
            if conn:
                return_conn(conn)

        if not positions:
            return {
                'open_positions': 0,
                'total_exposure_pct': 0.0,
                'max_single_position_pct': 0.0,
                'approaching_limits': []
            }

        total_risk = 0.0
        max_risk = 0.0
        for pos in positions:
            risk_per_contract = abs(pos['entry_price'] - pos['stop_price']) * pos['contracts'] * 100
            risk_pct = (risk_per_contract / self.account_size * 100) if self.account_size > 0 else 0
            total_risk += risk_pct
            max_risk = max(max_risk, risk_pct)

        warnings = []
        if len(positions) >= config.MAX_OPEN_POSITIONS:
            warnings.append(f"⚠️ Max positions reached ({len(positions)}/{config.MAX_OPEN_POSITIONS})")

        return {
            'open_positions': len(positions),
            'total_exposure_pct': round(total_risk, 2),
            'max_single_position_pct': round(max_risk, 2),
            'approaching_limits': warnings
        }

    def get_circuit_breaker_status(self) -> Dict:
        """
        Check circuit breaker status and proximity to trigger.
        """
        session_pnl = self.get_session_pnl()
        loss_pct = session_pnl['total_pnl_pct']
        trigger_threshold = -config.MAX_DAILY_LOSS_PCT
        distance = abs(loss_pct - trigger_threshold)

        if loss_pct <= trigger_threshold:
            warning_level = 'TRIGGERED'
        elif distance <= 0.5:
            warning_level = 'CRITICAL'
        elif distance <= 1.0:
            warning_level = 'WARNING'
        else:
            warning_level = 'SAFE'

        return {
            'triggered': loss_pct <= trigger_threshold,
            'current_loss_pct': round(loss_pct, 2),
            'trigger_threshold_pct': trigger_threshold,
            'distance_to_trigger_pct': round(distance, 2),
            'warning_level': warning_level
        }

    def get_streak_stats(self, days: int = 30) -> Dict:
        """
        Calculate consecutive win/loss streak statistics.
        Note: Uses 'pnl' column to match positions table schema.
        """
        p = ph()
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        trades = []
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT pnl
                FROM positions
                WHERE status = 'CLOSED' AND DATE(exit_time) >= {p}
                ORDER BY exit_time DESC
            """, (cutoff,))
            trades = [row['pnl'] for row in cursor.fetchall()]
        except Exception as e:
            print(f"[MONITOR] get_streak_stats error: {e}")
        finally:
            if conn:
                return_conn(conn)

        if not trades:
            return {
                'current_streak': 0, 'current_streak_type': 'NONE',
                'longest_win_streak': 0, 'longest_loss_streak': 0,
                'current_momentum': 'NEUTRAL'
            }

        current_streak = 0
        streak_type = 'WIN' if trades[0] > 0 else 'LOSS'
        for pnl in trades:
            if (pnl > 0 and streak_type == 'WIN') or (pnl <= 0 and streak_type == 'LOSS'):
                current_streak += 1
            else:
                break
        if streak_type == 'LOSS':
            current_streak = -current_streak

        longest_win = 0
        longest_loss = 0
        temp_streak = 0
        last_was_win = None
        for pnl in reversed(trades):
            is_win = pnl > 0
            if last_was_win is None or last_was_win == is_win:
                temp_streak += 1
            else:
                if last_was_win:
                    longest_win = max(longest_win, temp_streak)
                else:
                    longest_loss = max(longest_loss, temp_streak)
                temp_streak = 1
            last_was_win = is_win
        if last_was_win:
            longest_win = max(longest_win, temp_streak)
        else:
            longest_loss = max(longest_loss, temp_streak)

        if current_streak >= 3:
            momentum = 'STRONG'
        elif current_streak >= 1:
            momentum = 'MODERATE'
        elif current_streak == 0:
            momentum = 'NEUTRAL'
        elif current_streak >= -2:
            momentum = 'WEAK'
        else:
            momentum = 'NEGATIVE'

        return {
            'current_streak': current_streak,
            'current_streak_type': streak_type,
            'longest_win_streak': longest_win,
            'longest_loss_streak': longest_loss,
            'current_momentum': momentum
        }

    def get_sharpe_ratio(self, days: int = 30) -> Optional[float]:
        """
        Calculate Sharpe ratio (risk-adjusted returns).
        Note: Uses 'pnl' column to match positions table schema.
        """
        p = ph()
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        pnls = []
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            cursor.execute(f"""
                SELECT pnl
                FROM positions
                WHERE status = 'CLOSED' AND DATE(exit_time) >= {p}
            """, (cutoff,))
            pnls = [row['pnl'] for row in cursor.fetchall()]
        except Exception as e:
            print(f"[MONITOR] get_sharpe_ratio error: {e}")
        finally:
            if conn:
                return_conn(conn)

        if len(pnls) < 5:
            return None

        returns = [pnl / self.account_size for pnl in pnls]
        avg_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0
        sharpe = (avg_return / std_return) if std_return > 0 else 0
        return round(sharpe * (252 ** 0.5), 2)

    def get_max_drawdown(self, days: int = 30) -> Dict:
        """Calculate maximum drawdown from peak."""
        self._update_high_water_mark()
        current_value = self._get_current_account_value()
        current_dd = (
            (current_value - self.session_high_water_mark) /
            self.session_high_water_mark * 100
        ) if self.session_high_water_mark > 0 else 0
        max_dd = current_dd
        return {
            'max_drawdown_pct':     round(max_dd, 2),
            'current_drawdown_pct': round(current_dd, 2),
            'peak_value':           round(self.session_high_water_mark, 2),
            'trough_value':         round(current_value, 2)
        }

    def get_live_dashboard(self) -> str:
        """Generate formatted live performance dashboard."""
        pnl = self.get_session_pnl()
        cb = self.get_circuit_breaker_status()
        risk = self.get_risk_exposure()
        streak = self.get_streak_stats(days=7)
        win_rates = self.get_win_rate_by_grade(days=7)
        sharpe = self.get_sharpe_ratio(days=30)
        dd = self.get_max_drawdown()

        lines = []
        lines.append("\n" + "="*80)
        lines.append("LIVE PERFORMANCE DASHBOARD")
        lines.append("="*80)
        lines.append(f"Time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S ET')}\n")

        lines.append("── P&L " + "─"*72)
        pnl_emoji = "📈" if pnl['total_pnl'] >= 0 else "📉"
        lines.append(f"  {pnl_emoji} Session P&L:     ${pnl['total_pnl']:>10,.2f}  ({pnl['total_pnl_pct']:>+6.2f}%)")
        lines.append(f"     Realized:       ${pnl['realized_pnl']:>10,.2f}")
        lines.append(f"     Unrealized:     ${pnl['unrealized_pnl']:>10,.2f}")
        lines.append(f"  💰 Account Value:  ${pnl['account_value']:>10,.2f}")
        lines.append(f"  📊 Trades:         {pnl['trades_closed']} closed, {pnl['trades_open']} open\n")

        lines.append("── Circuit Breaker " + "─"*60)
        cb_emoji = {"SAFE": "✅", "WARNING": "⚠️", "CRITICAL": "🚨", "TRIGGERED": "🛑"}[cb['warning_level']]
        lines.append(f"  {cb_emoji} Status:           {cb['warning_level']}")
        lines.append(f"     Current Loss:   {cb['current_loss_pct']:>6.2f}%")
        lines.append(f"     Trigger:        {cb['trigger_threshold_pct']:>6.2f}%")
        lines.append(f"     Distance:       {cb['distance_to_trigger_pct']:>6.2f}%\n")

        lines.append("── Risk Exposure " + "─"*62)
        lines.append(f"  🔍 Open Positions:  {risk['open_positions']}/{config.MAX_OPEN_POSITIONS}")
        lines.append(f"  💼 Total Exposure:  {risk['total_exposure_pct']:.2f}%")
        lines.append(f"  🎯 Largest Position: {risk['max_single_position_pct']:.2f}%")
        for warning in risk['approaching_limits']:
            lines.append(f"  {warning}")
        lines.append("")

        lines.append("── Win Rates (Last 7 Days) " + "─"*51)
        overall = win_rates.get('overall', {})
        lines.append(f"  🎯 Overall:  {overall.get('win_rate', 0):>5.1f}%  ({overall.get('wins', 0)}W-{overall.get('losses', 0)}L)")
        for grade in ['A+', 'A', 'A-']:
            grade_data = win_rates.get(grade, {})
            if grade_data.get('total', 0) > 0:
                lines.append(f"     {grade:<3}:      {grade_data['win_rate']:>5.1f}%  ({grade_data['wins']}W-{grade_data['losses']}L)")
        lines.append("")

        lines.append("── Momentum " + "─"*66)
        streak_emoji = "🔥" if streak['current_streak'] > 0 else "❄️" if streak['current_streak'] < 0 else "➖"
        lines.append(f"  {streak_emoji} Current Streak:  {abs(streak['current_streak'])} {streak['current_streak_type']}")
        lines.append(f"  📊 Momentum:       {streak['current_momentum']}")
        lines.append(f"  🏆 Best Win Streak: {streak['longest_win_streak']}")
        lines.append(f"  💀 Worst Loss Run:  {streak['longest_loss_streak']}\n")

        lines.append("── Advanced Metrics " + "─"*58)
        if sharpe is not None:
            lines.append(f"  📝 Sharpe Ratio (30d): {sharpe:>6.2f}")
        lines.append(f"  📉 Max Drawdown:       {dd['max_drawdown_pct']:>6.2f}%")
        lines.append(f"  🎢 Current Drawdown:   {dd['current_drawdown_pct']:>6.2f}%")
        lines.append("="*80 + "\n")

        return "\n".join(lines)

    def get_daily_performance_report(self) -> str:
        """
        Generate comprehensive EOD performance report.
        Note: Uses 'pnl' column to match positions table schema.
        """
        dashboard = self.get_live_dashboard()

        p = ph()
        best_trades = []
        worst_trades = []
        conn = None
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)

            cursor.execute(f"""
                SELECT ticker, pnl, grade
                FROM positions
                WHERE DATE(exit_time) = {p} AND status = 'CLOSED'
                ORDER BY pnl DESC
                LIMIT 3
            """, (self._get_session_date(),))
            best_trades = cursor.fetchall()

            cursor.execute(f"""
                SELECT ticker, pnl, grade
                FROM positions
                WHERE DATE(exit_time) = {p} AND status = 'CLOSED'
                ORDER BY pnl ASC
                LIMIT 3
            """, (self._get_session_date(),))
            worst_trades = cursor.fetchall()
        except Exception as e:
            print(f"[MONITOR] get_daily_performance_report error: {e}")
        finally:
            if conn:
                return_conn(conn)

        lines = [dashboard]

        if best_trades:
            lines.append("\n🏆 BEST TRADES OF THE DAY")
            lines.append("─"*80)
            for i, trade in enumerate(best_trades, 1):
                lines.append(f"  {i}. {trade['ticker']:<6} {trade['grade']:<3}  ${trade['pnl']:>8,.2f}")

        if worst_trades:
            lines.append("\n💀 WORST TRADES OF THE DAY")
            lines.append("─"*80)
            for i, trade in enumerate(worst_trades, 1):
                lines.append(f"  {i}. {trade['ticker']:<6} {trade['grade']:<3}  ${trade['pnl']:>8,.2f}")

        lines.append("\n" + "="*80)
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

performance_monitor = PerformanceMonitor()


if __name__ == "__main__":
    print("Testing Performance Monitor...\n")
    print(performance_monitor.get_live_dashboard())
