#!/usr/bin/env python3
"""
EOD Digest Enhancement System

Comprehensive daily and weekly performance reports consolidating all analytics.

Digest Types:
  1. Daily Digest - Detailed session performance breakdown
  2. Weekly Digest - 5-day cumulative performance and trends
  3. Monthly Digest - Long-term performance analysis

Components:
  - Executive Summary (P&L, trades, win rate)
  - Signal Analytics (funnel, grades, multipliers)
  - Performance Metrics (Sharpe, drawdown, streaks)
  - Validator Effectiveness (pass rates, rejection reasons)
  - Best/Worst Trades (identification and analysis)
  - Action Items (recommendations for next session)

Usage:
  # Daily digest at EOD:
  from eod_digest import digest_manager
  digest_manager.generate_daily_digest()
  
  # Weekly digest on Fridays:
  if today.weekday() == 4:  # Friday
      digest_manager.generate_weekly_digest()
  
  # Manual report generation:
  report = digest_manager.get_daily_report_dict()
  digest_manager.export_to_csv('daily_report_2026-02-24.csv')
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import json
import csv
from collections import defaultdict
from db_connection import get_conn, ph, dict_cursor
import config

ET = ZoneInfo("America/New_York")

# Import analytics modules
try:
    from signal_analytics import signal_tracker
    from performance_monitor import performance_monitor
    ANALYTICS_ENABLED = True
except ImportError as e:
    print(f"[DIGEST] Warning: Analytics modules not available - {e}")
    ANALYTICS_ENABLED = False


class EODDigestManager:
    """Generates comprehensive end-of-day and weekly performance digests."""
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
    
    def _get_session_date(self) -> str:
        """Get current trading session date."""
        return datetime.now(ET).strftime("%Y-%m-%d")
    
    def _get_week_dates(self) -> Tuple[str, str]:
        """Get start and end dates of current week (Mon-Fri)."""
        today = datetime.now(ET)
        # Find Monday of current week
        monday = today - timedelta(days=today.weekday())
        friday = monday + timedelta(days=4)
        return monday.strftime("%Y-%m-%d"), friday.strftime("%Y-%m-%d")
    
    def get_trade_breakdown(self, session_date: str = None) -> List[Dict]:
        """
        Get detailed trade-by-trade breakdown for the day.
        
        Args:
            session_date: Specific date or None for today
        
        Returns:
            List of trade dicts with ticker, grade, P&L, R:R, outcome
        """
        session_date = session_date or self._get_session_date()
        
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute(f"""
            SELECT 
                ticker,
                signal_type,
                direction,
                grade,
                entry_price,
                exit_price,
                stop_loss,
                target_1,
                target_2,
                realized_pnl,
                exit_reason,
                entry_time,
                exit_time
            FROM positions
            WHERE DATE(exit_time) = {p} AND status = 'closed'
            ORDER BY exit_time DESC
        """, (session_date,))
        
        trades = cursor.fetchall()
        conn.close()
        
        trade_list = []
        for trade in trades:
            # Calculate R:R achieved
            entry = trade['entry_price']
            exit_price = trade['exit_price']
            stop = trade['stop_loss']
            risk = abs(entry - stop)
            reward = abs(exit_price - entry)
            rr_achieved = (reward / risk) if risk > 0 else 0
            
            # Determine outcome
            if trade['realized_pnl'] > 0:
                if trade['exit_reason'] == 'target_2':
                    outcome = "T2 HIT"
                elif trade['exit_reason'] == 'target_1':
                    outcome = "T1 HIT"
                else:
                    outcome = "PROFIT"
            else:
                if trade['exit_reason'] == 'stop_loss':
                    outcome = "STOPPED"
                else:
                    outcome = "LOSS"
            
            trade_list.append({
                'ticker': trade['ticker'],
                'signal_type': trade['signal_type'],
                'direction': trade['direction'],
                'grade': trade['grade'],
                'pnl': trade['realized_pnl'],
                'rr_achieved': round(rr_achieved, 2),
                'outcome': outcome,
                'exit_reason': trade['exit_reason'],
                'duration_minutes': self._calculate_duration(
                    trade['entry_time'], 
                    trade['exit_time']
                )
            })
        
        return trade_list
    
    def _calculate_duration(self, entry_time, exit_time) -> int:
        """Calculate trade duration in minutes."""
        if not entry_time or not exit_time:
            return 0
        
        try:
            if isinstance(entry_time, str):
                entry_time = datetime.fromisoformat(entry_time)
            if isinstance(exit_time, str):
                exit_time = datetime.fromisoformat(exit_time)
            
            delta = exit_time - entry_time
            return int(delta.total_seconds() / 60)
        except Exception:
            return 0
    
    def get_validator_stats(self, session_date: str = None) -> Dict:
        """
        Get validator effectiveness statistics.
        
        Returns:
            {
                'total_checked': int,
                'passed': int,
                'filtered': int,
                'pass_rate': float,
                'top_rejection_reasons': List[Tuple[str, int]]
            }
        """
        session_date = session_date or self._get_session_date()
        
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        # Get validation counts
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN validation_passed = 1 THEN 1 ELSE 0 END) as passed,
                SUM(CASE WHEN validation_passed = 0 THEN 1 ELSE 0 END) as filtered
            FROM signal_events
            WHERE session_date = {p} AND stage IN ('VALIDATED', 'REJECTED')
        """, (session_date,))
        
        row = cursor.fetchone()
        total = row['total'] if row else 0
        passed = row['passed'] if row else 0
        filtered = row['filtered'] if row else 0
        pass_rate = (passed / total * 100) if total > 0 else 0
        
        # Get rejection reasons
        cursor.execute(f"""
            SELECT rejection_reason, COUNT(*) as count
            FROM signal_events
            WHERE session_date = {p} 
              AND stage = 'REJECTED'
              AND rejection_reason IS NOT NULL
              AND rejection_reason != ''
            GROUP BY rejection_reason
            ORDER BY count DESC
            LIMIT 5
        """, (session_date,))
        
        rejection_reasons = [(row['rejection_reason'], row['count']) for row in cursor.fetchall()]
        conn.close()
        
        return {
            'total_checked': total,
            'passed': passed,
            'filtered': filtered,
            'pass_rate': round(pass_rate, 1),
            'top_rejection_reasons': rejection_reasons
        }
    
    def generate_daily_digest(self) -> str:
        """
        Generate comprehensive daily digest.
        
        Returns:
            Formatted digest string
        """
        if not ANALYTICS_ENABLED:
            return "[DIGEST] Analytics modules not available"
        
        session_date = self._get_session_date()
        
        # Gather all metrics
        pnl = performance_monitor.get_session_pnl()
        win_rates = performance_monitor.get_win_rate_by_grade(days=1)
        streak = performance_monitor.get_streak_stats(days=7)
        sharpe = performance_monitor.get_sharpe_ratio(days=30)
        dd = performance_monitor.get_max_drawdown()
        
        funnel = signal_tracker.get_funnel_stats(session_date)
        grades = signal_tracker.get_grade_distribution(session_date)
        mults = signal_tracker.get_multiplier_impact(session_date)
        
        validator_stats = self.get_validator_stats(session_date)
        trades = self.get_trade_breakdown(session_date)
        
        # Build digest
        lines = []
        lines.append("\n" + "="*100)
        lines.append("END OF DAY DIGEST")
        lines.append("="*100)
        lines.append(f"Date: {session_date} | {datetime.now(ET).strftime('%A')}\n")
        
        # ═══ EXECUTIVE SUMMARY ═══
        lines.append("═"*100)
        lines.append("EXECUTIVE SUMMARY")
        lines.append("═"*100)
        
        pnl_emoji = "📈" if pnl['total_pnl'] >= 0 else "📉"
        lines.append(f"{pnl_emoji} Daily P&L:        ${pnl['total_pnl']:>10,.2f}  ({pnl['total_pnl_pct']:>+6.2f}%)")
        lines.append(f"   Realized:       ${pnl['realized_pnl']:>10,.2f}")
        lines.append(f"   Unrealized:     ${pnl['unrealized_pnl']:>10,.2f}")
        lines.append(f"   Account Value:  ${pnl['account_value']:>10,.2f}")
        lines.append("")
        
        overall_wr = win_rates.get('overall', {}).get('win_rate', 0)
        overall_wins = win_rates.get('overall', {}).get('wins', 0)
        overall_losses = win_rates.get('overall', {}).get('losses', 0)
        lines.append(f"🎯 Win Rate:        {overall_wr:>6.1f}%  ({overall_wins}W-{overall_losses}L)")
        lines.append(f"🔥 Current Streak:   {abs(streak['current_streak'])} {streak['current_streak_type']}")
        lines.append(f"📊 Momentum:        {streak['current_momentum']}")
        lines.append("")
        
        # ═══ SIGNAL ANALYTICS ═══
        lines.append("═"*100)
        lines.append("SIGNAL ANALYTICS")
        lines.append("═"*100)
        
        lines.append("── Signal Funnel " + "─"*83)
        lines.append(f"  Generated:  {funnel['generated']:>3}")
        lines.append(f"  Validated:  {funnel['validated']:>3}  ({funnel['validation_rate']:>5.1f}% pass rate)")
        lines.append(f"  Armed:      {funnel['armed']:>3}  ({funnel['arming_rate']:>5.1f}% confirmation rate)")
        lines.append(f"  Traded:     {funnel['traded']:>3}  ({funnel['execution_rate']:>5.1f}% execution rate)")
        lines.append("")
        
        lines.append("── Grade Distribution " + "─"*77)
        for grade in ['A+', 'A', 'A-']:
            grade_count = grades['counts'].get(grade, 0)
            grade_pct = grades['percentages'].get(grade, 0)
            grade_wr_data = win_rates.get(grade, {})
            grade_wr = grade_wr_data.get('win_rate', 0) if grade_wr_data.get('total', 0) > 0 else 0
            lines.append(f"  {grade:<3}: {grade_count:>3} signals ({grade_pct:>5.1f}%)  |  Win Rate: {grade_wr:>5.1f}%")
        lines.append("")
        
        lines.append("── Multiplier Impact " + "─"*79)
        lines.append(f"  IVR Avg:     {mults['ivr_avg']:.3f}x")
        lines.append(f"  UOA Avg:     {mults['uoa_avg']:.3f}x")
        lines.append(f"  GEX Avg:     {mults['gex_avg']:.3f}x")
        lines.append(f"  MTF Boost:   +{mults['mtf_avg']:.3f}")
        lines.append(f"  Total Lift:  {mults['base_avg']:.3f} → {mults['final_avg']:.3f}  ({mults['total_boost_pct']:+.1f}%)")
        lines.append("")
        
        # ═══ VALIDATOR EFFECTIVENESS ═══
        lines.append("═"*100)
        lines.append("VALIDATOR EFFECTIVENESS")
        lines.append("═"*100)
        lines.append(f"  Total Checked:   {validator_stats['total_checked']}")
        lines.append(f"  Passed:          {validator_stats['passed']}")
        lines.append(f"  Filtered:        {validator_stats['filtered']}")
        lines.append(f"  Pass Rate:       {validator_stats['pass_rate']:.1f}%")
        
        if validator_stats['top_rejection_reasons']:
            lines.append("\n  Top Rejection Reasons:")
            for i, (reason, count) in enumerate(validator_stats['top_rejection_reasons'][:5], 1):
                lines.append(f"    {i}. {reason:<50} ({count})")
        lines.append("")
        
        # ═══ TRADE BREAKDOWN ═══
        lines.append("═"*100)
        lines.append("TRADE BREAKDOWN")
        lines.append("═"*100)
        
        if trades:
            lines.append(f"{'Ticker':<8} {'Type':<15} {'Dir':<6} {'Grade':<6} {'Outcome':<10} {'P&L':<12} {'R:R':<8} {'Duration'}")
            lines.append("─"*100)
            
            for trade in trades:
                pnl_str = f"${trade['pnl']:>9,.2f}"
                duration_str = f"{trade['duration_minutes']}m"
                lines.append(
                    f"{trade['ticker']:<8} "
                    f"{trade['signal_type']:<15} "
                    f"{trade['direction']:<6} "
                    f"{trade['grade']:<6} "
                    f"{trade['outcome']:<10} "
                    f"{pnl_str:<12} "
                    f"{trade['rr_achieved']:<8.2f} "
                    f"{duration_str}"
                )
        else:
            lines.append("  No trades closed today")
        lines.append("")
        
        # ═══ BEST & WORST TRADES ═══
        if trades:
            lines.append("═"*100)
            lines.append("BEST & WORST TRADES")
            lines.append("═"*100)
            
            sorted_trades = sorted(trades, key=lambda x: x['pnl'], reverse=True)
            
            lines.append("── Best Trades " + "─"*84)
            for i, trade in enumerate(sorted_trades[:3], 1):
                lines.append(
                    f"  {i}. {trade['ticker']:<6} {trade['grade']:<3}  "
                    f"${trade['pnl']:>9,.2f}  ({trade['outcome']})  "
                    f"R:R {trade['rr_achieved']:.2f}"
                )
            
            lines.append("\n── Worst Trades " + "─"*83)
            for i, trade in enumerate(reversed(sorted_trades[-3:]), 1):
                lines.append(
                    f"  {i}. {trade['ticker']:<6} {trade['grade']:<3}  "
                    f"${trade['pnl']:>9,.2f}  ({trade['outcome']})  "
                    f"R:R {trade['rr_achieved']:.2f}"
                )
            lines.append("")
        
        # ═══ ADVANCED METRICS ═══
        lines.append("═"*100)
        lines.append("ADVANCED METRICS")
        lines.append("═"*100)
        if sharpe is not None:
            lines.append(f"  Sharpe Ratio (30d):     {sharpe:>6.2f}")
        lines.append(f"  Max Drawdown:           {dd['max_drawdown_pct']:>6.2f}%")
        lines.append(f"  Current Drawdown:       {dd['current_drawdown_pct']:>6.2f}%")
        lines.append(f"  Session High:           ${dd['peak_value']:>10,.2f}")
        lines.append("")
        
        # ═══ ACTION ITEMS ═══
        lines.append("═"*100)
        lines.append("ACTION ITEMS FOR NEXT SESSION")
        lines.append("═"*100)
        
        action_items = self._generate_action_items(
            pnl, win_rates, funnel, validator_stats, streak
        )
        for item in action_items:
            lines.append(f"  • {item}")
        
        lines.append("\n" + "="*100 + "\n")
        
        return "\n".join(lines)
    
    def _generate_action_items(
        self, 
        pnl: Dict, 
        win_rates: Dict, 
        funnel: Dict, 
        validator_stats: Dict,
        streak: Dict
    ) -> List[str]:
        """
        Generate actionable recommendations based on day's performance.
        
        Returns:
            List of action item strings
        """
        items = []
        
        # Win rate recommendations
        overall_wr = win_rates.get('overall', {}).get('win_rate', 0)
        if overall_wr < 60:
            items.append("Win rate below target (60%) - Review confidence thresholds and validator settings")
        elif overall_wr >= 75:
            items.append("Excellent win rate! Current setup is working well - maintain discipline")
        
        # Funnel analysis
        if funnel['validation_rate'] < 50:
            items.append(f"Low validation pass rate ({funnel['validation_rate']:.1f}%) - Consider loosening validator checks")
        
        if funnel['arming_rate'] < 40:
            items.append(f"Low confirmation rate ({funnel['arming_rate']:.1f}%) - Signals timing out frequently")
        
        if funnel['execution_rate'] < 30:
            items.append(f"Low execution rate ({funnel['execution_rate']:.1f}%) - Review risk limits and position sizing")
        
        # Streak warnings
        if streak['current_streak'] <= -3:
            items.append("⚠️ Loss streak detected - Review recent losing trades for patterns")
            items.append("Consider reducing position size until momentum improves")
        
        # P&L recommendations
        if pnl['total_pnl_pct'] >= 2.0:
            items.append("🎯 Daily target achieved! Well done.")
        elif pnl['total_pnl_pct'] < -1.0:
            items.append("Negative day - Review setup quality and market conditions tomorrow")
        
        # Default if no specific items
        if not items:
            items.append("Continue current approach - performance is within expected range")
            items.append("Review signal analytics for optimization opportunities")
        
        return items
    
    def generate_weekly_digest(self) -> str:
        """
        Generate comprehensive weekly digest (call on Fridays).
        
        Returns:
            Formatted weekly digest string
        """
        if not ANALYTICS_ENABLED:
            return "[DIGEST] Analytics modules not available"
        
        week_start, week_end = self._get_week_dates()
        
        lines = []
        lines.append("\n" + "="*100)
        lines.append("WEEKLY PERFORMANCE DIGEST")
        lines.append("="*100)
        lines.append(f"Week: {week_start} to {week_end}\n")
        
        # Get weekly P&L
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN realized_pnl <= 0 THEN 1 ELSE 0 END) as losses,
                SUM(realized_pnl) as total_pnl,
                AVG(realized_pnl) as avg_pnl,
                MAX(realized_pnl) as best_trade,
                MIN(realized_pnl) as worst_trade
            FROM positions
            WHERE DATE(exit_time) >= {p}
              AND DATE(exit_time) <= {p}
              AND status = 'closed'
        """, (week_start, week_end))
        
        week_stats = cursor.fetchone()
        conn.close()
        
        total_trades = week_stats['total_trades'] if week_stats else 0
        wins = week_stats['wins'] if week_stats else 0
        losses = week_stats['losses'] if week_stats else 0
        total_pnl = week_stats['total_pnl'] if week_stats else 0
        avg_pnl = week_stats['avg_pnl'] if week_stats else 0
        best_trade = week_stats['best_trade'] if week_stats else 0
        worst_trade = week_stats['worst_trade'] if week_stats else 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        pnl_pct = (total_pnl / config.ACCOUNT_SIZE * 100) if config.ACCOUNT_SIZE > 0 else 0
        
        lines.append("═"*100)
        lines.append("WEEKLY SUMMARY")
        lines.append("═"*100)
        lines.append(f"💰 Weekly P&L:       ${total_pnl:>10,.2f}  ({pnl_pct:>+6.2f}%)")
        lines.append(f"📊 Total Trades:     {total_trades}")
        lines.append(f"🎯 Win Rate:         {win_rate:>6.1f}%  ({wins}W-{losses}L)")
        lines.append(f"💵 Avg Trade:        ${avg_pnl:>10,.2f}")
        lines.append(f"🏆 Best Trade:       ${best_trade:>10,.2f}")
        lines.append(f"💀 Worst Trade:      ${worst_trade:>10,.2f}")
        lines.append("")
        
        lines.append("═"*100)
        lines.append("FOCUS AREAS FOR NEXT WEEK")
        lines.append("═"*100)
        lines.append("  • Review weekly performance trends")
        lines.append("  • Identify best performing setups and replicate")
        lines.append("  • Analyze losses for pattern recognition")
        lines.append("  • Adjust confidence thresholds if needed")
        lines.append("\n" + "="*100 + "\n")
        
        return "\n".join(lines)
    
    def export_to_csv(self, filename: str, session_date: str = None):
        """
        Export daily digest data to CSV file.
        
        Args:
            filename: Output CSV filename
            session_date: Specific date or None for today
        """
        session_date = session_date or self._get_session_date()
        trades = self.get_trade_breakdown(session_date)
        
        with open(filename, 'w', newline='') as f:
            if trades:
                fieldnames = trades[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(trades)
                print(f"[DIGEST] Exported {len(trades)} trades to {filename}")
            else:
                print(f"[DIGEST] No trades to export for {session_date}")
    
    def get_daily_report_dict(self, session_date: str = None) -> Dict:
        """
        Get daily digest data as structured dictionary (for JSON export).
        
        Returns:
            Complete digest data as dict
        """
        session_date = session_date or self._get_session_date()
        
        return {
            'session_date': session_date,
            'pnl': performance_monitor.get_session_pnl(),
            'win_rates': performance_monitor.get_win_rate_by_grade(days=1),
            'streak': performance_monitor.get_streak_stats(days=7),
            'funnel': signal_tracker.get_funnel_stats(session_date),
            'grades': signal_tracker.get_grade_distribution(session_date),
            'multipliers': signal_tracker.get_multiplier_impact(session_date),
            'validator': self.get_validator_stats(session_date),
            'trades': self.get_trade_breakdown(session_date)
        }


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

digest_manager = EODDigestManager()


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing EOD Digest Manager...\n")
    
    if ANALYTICS_ENABLED:
        # Generate daily digest
        print(digest_manager.generate_daily_digest())
        
        # Check if Friday for weekly digest
        if datetime.now(ET).weekday() == 4:
            print(digest_manager.generate_weekly_digest())
    else:
        print("Analytics modules not available")
