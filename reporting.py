"""
Reporting Module - Consolidated Performance Reporting

PHASE 2C: Merged eod_digest.py + pnl_digest.py into single reporting module.

Unified reporting system for:
  - Daily P&L Discord digests
  - Comprehensive EOD reports (console + CSV)
  - Weekly performance summaries
  - Trade breakdowns and analytics

Key Classes:
  DailyReporter     - Simple Discord digest (from pnl_digest.py)
  EODDigestManager  - Comprehensive reports (from eod_digest.py)

Usage:
  # Quick Discord digest at EOD:
  from reporting import send_pnl_digest
  send_pnl_digest()
  
  # Comprehensive analysis:
  from reporting import digest_manager
  print(digest_manager.generate_daily_digest())
  digest_manager.export_to_csv('report.csv')
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dtime, date
from zoneinfo import ZoneInfo
import csv
from collections import defaultdict
from utils import get_conn, ph, dict_cursor
import config

ET = ZoneInfo("America/New_York")

# Import analytics modules
try:
    from signal_analytics import signal_tracker
    SIGNAL_ANALYTICS_ENABLED = True
except ImportError:
    SIGNAL_ANALYTICS_ENABLED = False
    signal_tracker = None

try:
    from performance_monitor import performance_monitor
    PERFORMANCE_MONITOR_ENABLED = True
except ImportError:
    PERFORMANCE_MONITOR_ENABLED = False
    performance_monitor = None

ANALYTICS_ENABLED = SIGNAL_ANALYTICS_ENABLED and PERFORMANCE_MONITOR_ENABLED


# ══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES (deduplicated from both files)
# ══════════════════════════════════════════════════════════════════════════════

def _now_et() -> datetime:
    """Get current ET time."""
    return datetime.now(ET)

def _today_et() -> date:
    """Get current ET date."""
    return _now_et().date()

def _calculate_duration(entry_time, exit_time) -> int:
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


# ══════════════════════════════════════════════════════════════════════════════
# DAILY REPORTER (from pnl_digest.py)
# ══════════════════════════════════════════════════════════════════════════════

class DailyReporter:
    """
    Simplified daily P&L reporter for Discord.
    
    Generates quick end-of-day performance summaries optimized for Discord.
    """
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
    
    def _query_closed_positions(self, cursor, p, today: date) -> list:
        """Fetch all closed positions opened today."""
        try:
            cursor.execute(f"""
                SELECT
                    ticker, direction,
                    entry_price, close_price,
                    open_time,  close_time,
                    confidence, grade
                FROM positions
                WHERE DATE(open_time) = {p}
                  AND close_price IS NOT NULL
                ORDER BY open_time ASC
            """, (today,))
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception:
            return []
    
    def _query_signals_fired(self, cursor, p, today: date) -> int:
        """Count signals entered into proposed_trades today."""
        try:
            cursor.execute(
                f"SELECT COUNT(*) FROM proposed_trades WHERE DATE(timestamp) = {p}",
                (today,)
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0
    
    def build_pnl_summary(self) -> dict:
        """
        Query DB and build complete performance summary for today.
        
        Returns dict with date, trades, wins, losses, win_rate, total_pnl,
        avg_pnl, avg_hold_min, signals_fired, best/worst trades,
        grade breakdown, confidence breakdown, and raw trades list.
        """
        today = _today_et()
        summary = {
            "date":            today.strftime("%A, %B %d, %Y"),
            "day_label":       today.strftime("%a %b %d"),
            "trades":          0,
            "wins":            0,
            "losses":          0,
            "win_rate":        0.0,
            "total_pnl":       0.0,
            "avg_pnl":         0.0,
            "avg_hold_min":    0.0,
            "signals_fired":   0,
            "best_trade":      None,
            "worst_trade":     None,
            "grade_breakdown": {},
            "conf_breakdown":  {},
            "raw_trades":      []
        }
        
        try:
            conn   = get_conn(self.db_path)
            cursor = conn.cursor()
            p      = ph()
            
            trades        = self._query_closed_positions(cursor, p, today)
            signals_fired = self._query_signals_fired(cursor, p, today)
            summary["signals_fired"] = signals_fired
            conn.close()
        except Exception as e:
            print(f"[REPORTING] DB error: {e}")
            return summary
        
        if not trades:
            return summary
        
        summary["raw_trades"] = trades
        
        # Core P&L calculation
        pnl_list   = []
        hold_times = []
        wins = losses = 0
        
        for t in trades:
            entry = t.get("entry_price") or 0
            close = t.get("close_price") or 0
            direc = (t.get("direction") or "bull").lower()
            
            if entry > 0 and close > 0:
                raw_pnl = (close - entry) if direc == "bull" else (entry - close)
                pnl_list.append(raw_pnl)
                t["pnl"] = raw_pnl
                if raw_pnl > 0:
                    wins += 1
                else:
                    losses += 1
            else:
                t["pnl"] = 0.0
                pnl_list.append(0.0)
            
            # Hold time in minutes
            ot = t.get("open_time")
            ct = t.get("close_time")
            if ot and ct:
                try:
                    if isinstance(ot, str):
                        ot = datetime.fromisoformat(ot)
                    if isinstance(ct, str):
                        ct = datetime.fromisoformat(ct)
                    hold_times.append((ct - ot).total_seconds() / 60)
                except Exception:
                    pass
        
        total = len(trades)
        total_pnl = sum(pnl_list)
        
        summary["trades"]       = total
        summary["wins"]         = wins
        summary["losses"]       = losses
        summary["win_rate"]     = round((wins / total) * 100, 1) if total > 0 else 0.0
        summary["total_pnl"]    = round(total_pnl, 2)
        summary["avg_pnl"]      = round(total_pnl / total, 2) if total > 0 else 0.0
        summary["avg_hold_min"] = round(sum(hold_times) / len(hold_times), 1) if hold_times else 0.0
        
        # Best/worst trade
        if pnl_list:
            best_idx  = pnl_list.index(max(pnl_list))
            worst_idx = pnl_list.index(min(pnl_list))
            summary["best_trade"]  = trades[best_idx]
            summary["worst_trade"] = trades[worst_idx]
        
        # Grade breakdown
        grade_data: dict = {}
        for t in trades:
            g = (t.get("grade") or "?").upper()
            if g not in grade_data:
                grade_data[g] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
            grade_data[g]["trades"]    += 1
            grade_data[g]["total_pnl"] += t.get("pnl", 0)
            if t.get("pnl", 0) > 0:
                grade_data[g]["wins"] += 1
        
        for g in grade_data:
            n = grade_data[g]["trades"]
            grade_data[g]["win_rate"] = round(
                (grade_data[g]["wins"] / n) * 100, 1
            ) if n > 0 else 0.0
            grade_data[g]["avg_pnl"] = round(
                grade_data[g]["total_pnl"] / n, 2
            ) if n > 0 else 0.0
        summary["grade_breakdown"] = grade_data
        
        # Confidence tier breakdown
        conf_tiers = {
            ">=90%":  {"trades": 0, "wins": 0, "total_pnl": 0.0},
            "80-89%": {"trades": 0, "wins": 0, "total_pnl": 0.0},
            "<80%":   {"trades": 0, "wins": 0, "total_pnl": 0.0}
        }
        for t in trades:
            conf = (t.get("confidence") or 0) * 100
            tier = ">=90%" if conf >= 90 else ("80-89%" if conf >= 80 else "<80%")
            conf_tiers[tier]["trades"]    += 1
            conf_tiers[tier]["total_pnl"] += t.get("pnl", 0)
            if t.get("pnl", 0) > 0:
                conf_tiers[tier]["wins"] += 1
        
        for tier in conf_tiers:
            n = conf_tiers[tier]["trades"]
            conf_tiers[tier]["win_rate"] = round(
                (conf_tiers[tier]["wins"] / n) * 100, 1
            ) if n > 0 else 0.0
        summary["conf_breakdown"] = conf_tiers
        
        return summary
    
    def format_discord_digest(self, s: dict) -> str:
        """Format P&L summary into Discord-ready message."""
        sep = "═" * 40
        
        lines = [
            sep,
            f"📊 **WAR MACHINE — Daily P&L Digest**",
            f"📅 {s['date']}",
            sep,
            ""
        ]
        
        # Financials
        pnl      = s["total_pnl"]
        pnl_sign = "+" if pnl >= 0 else ""
        pnl_icon = "🟢" if pnl >= 0 else "🔴"
        wr_icon  = "🎯" if s["win_rate"] >= 60 else ("⚠️" if s["win_rate"] >= 40 else "🟥")
        
        lines += [
            f"{pnl_icon} **Realized P&L:**   `{pnl_sign}{pnl:.2f} pts`",
            f"{wr_icon} **Win Rate:**        `{s['win_rate']:.1f}%`  "
            f"({s['wins']}W / {s['losses']}L / {s['trades']} trades)",
            f"📶 **Signals Fired:**   `{s['signals_fired']}`",
            f"⏱  **Avg Hold Time:**   `{s['avg_hold_min']:.0f} min`",
            f"💹 **Avg P&L / Trade:** `{pnl_sign}{s['avg_pnl']:.2f} pts`",
            ""
        ]
        
        # Best/Worst trade
        def _trade_line(t, icon):
            if not t:
                return f"{icon} N/A"
            pnl    = t.get("pnl", 0)
            sign   = "+" if pnl >= 0 else ""
            ticker = t.get("ticker", "?")
            direc  = (t.get("direction") or "?").upper()
            grade  = t.get("grade") or "?"
            conf   = (t.get("confidence") or 0) * 100
            return (f"{icon} **{ticker}** {direc} `{sign}{pnl:.2f}` "
                    f"| Grade: {grade} | Conf: {conf:.0f}%")
        
        lines += [
            _trade_line(s["best_trade"],  "🏆 **Best:**  "),
            _trade_line(s["worst_trade"], "💥 **Worst:** "),
            ""
        ]
        
        # Grade breakdown
        gb = s.get("grade_breakdown", {})
        if gb:
            lines.append("🎚️ **Grade Breakdown:**")
            for grade in ["A+", "A", "A-"]:
                if grade in gb:
                    d  = gb[grade]
                    sp = "+" if d["avg_pnl"] >= 0 else ""
                    lines.append(
                        f"  `{grade:<3}` {d['trades']:>2} trades | "
                        f"{d['win_rate']:>5.1f}% WR | avg `{sp}{d['avg_pnl']:.2f}`"
                    )
            lines.append("")
        
        # Confidence accuracy
        cb = s.get("conf_breakdown", {})
        if any(v["trades"] > 0 for v in cb.values()):
            lines.append("🧠 **Confidence Accuracy:**")
            for tier in [">=90%", "80-89%", "<80%"]:
                d = cb.get(tier, {})
                if d.get("trades", 0) > 0:
                    lines.append(
                        f"  `{tier:<7}` {d['trades']:>2} trades | {d['win_rate']:>5.1f}% WR"
                    )
            lines.append("")
        
        lines += [
            sep,
            f"🤖 War Machine | {_now_et().strftime('%I:%M %p ET')}",
            sep
        ]
        
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# EOD DIGEST MANAGER (from eod_digest.py)
# ══════════════════════════════════════════════════════════════════════════════

class EODDigestManager:
    """
    Comprehensive end-of-day and weekly performance digest generator.
    
    Includes signal analytics, validator stats, advanced metrics,
    and actionable recommendations.
    """
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.daily_reporter = DailyReporter(db_path)
    
    def _get_session_date(self) -> str:
        """Get current trading session date."""
        return _now_et().strftime("%Y-%m-%d")
    
    def _get_week_dates(self) -> Tuple[str, str]:
        """Get start and end dates of current week (Mon-Fri)."""
        today = _now_et()
        monday = today - timedelta(days=today.weekday())
        friday = monday + timedelta(days=4)
        return monday.strftime("%Y-%m-%d"), friday.strftime("%Y-%m-%d")
    
    def get_trade_breakdown(self, session_date: str = None) -> List[Dict]:
        """
        Get detailed trade-by-trade breakdown for the day.
        
        Returns list of trade dicts with ticker, grade, P&L, R:R, outcome.
        """
        session_date = session_date or self._get_session_date()
        
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute(f"""
            SELECT 
                ticker, signal_type, direction, grade,
                entry_price, exit_price, stop_loss,
                target_1, target_2, realized_pnl,
                exit_reason, entry_time, exit_time
            FROM positions
            WHERE DATE(exit_time) = {p} AND status = 'closed'
            ORDER BY exit_time DESC
        """, (session_date,))
        
        trades = cursor.fetchall()
        conn.close()
        
        trade_list = []
        for trade in trades:
            entry = trade['entry_price']
            exit_price = trade['exit_price']
            stop = trade['stop_loss']
            risk = abs(entry - stop)
            reward = abs(exit_price - entry)
            rr_achieved = (reward / risk) if risk > 0 else 0
            
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
                'duration_minutes': _calculate_duration(
                    trade['entry_time'], 
                    trade['exit_time']
                )
            })
        
        return trade_list
    
    def get_validator_stats(self, session_date: str = None) -> Dict:
        """
        Get validator effectiveness statistics.
        
        Returns dict with total_checked, passed, filtered, pass_rate,
        and top_rejection_reasons.
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
    
    def _generate_action_items(
        self, 
        pnl: Dict, 
        win_rates: Dict, 
        funnel: Dict, 
        validator_stats: Dict,
        streak: Dict
    ) -> List[str]:
        """Generate actionable recommendations based on day's performance."""
        items = []
        
        overall_wr = win_rates.get('overall', {}).get('win_rate', 0)
        if overall_wr < 60:
            items.append("Win rate below target (60%) - Review confidence thresholds and validator settings")
        elif overall_wr >= 75:
            items.append("Excellent win rate! Current setup is working well - maintain discipline")
        
        if funnel['validation_rate'] < 50:
            items.append(f"Low validation pass rate ({funnel['validation_rate']:.1f}%) - Consider loosening validator checks")
        
        if funnel['arming_rate'] < 40:
            items.append(f"Low confirmation rate ({funnel['arming_rate']:.1f}%) - Signals timing out frequently")
        
        if funnel['execution_rate'] < 30:
            items.append(f"Low execution rate ({funnel['execution_rate']:.1f}%) - Review risk limits and position sizing")
        
        if streak['current_streak'] <= -3:
            items.append("⚠️ Loss streak detected - Review recent losing trades for patterns")
            items.append("Consider reducing position size until momentum improves")
        
        if pnl['total_pnl_pct'] >= 2.0:
            items.append("🎯 Daily target achieved! Well done.")
        elif pnl['total_pnl_pct'] < -1.0:
            items.append("Negative day - Review setup quality and market conditions tomorrow")
        
        if not items:
            items.append("Continue current approach - performance is within expected range")
            items.append("Review signal analytics for optimization opportunities")
        
        return items
    
    def generate_daily_digest(self) -> str:
        """
        Generate comprehensive daily digest with full analytics.
        
        Returns formatted digest string for console output.
        """
        if not ANALYTICS_ENABLED:
            # Fallback to simple digest if analytics not available
            summary = self.daily_reporter.build_pnl_summary()
            return self.daily_reporter.format_discord_digest(summary)
        
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
        
        # Build comprehensive digest
        lines = []
        lines.append("\n" + "="*100)
        lines.append("END OF DAY DIGEST")
        lines.append("="*100)
        lines.append(f"Date: {session_date} | {_now_et().strftime('%A')}\n")
        
        # Executive summary
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
        
        # Signal analytics
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
        
        # Validator effectiveness
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
        
        # Trade breakdown
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
        
        # Best & worst trades
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
        
        # Advanced metrics
        lines.append("═"*100)
        lines.append("ADVANCED METRICS")
        lines.append("═"*100)
        if sharpe is not None:
            lines.append(f"  Sharpe Ratio (30d):     {sharpe:>6.2f}")
        lines.append(f"  Max Drawdown:           {dd['max_drawdown_pct']:>6.2f}%")
        lines.append(f"  Current Drawdown:       {dd['current_drawdown_pct']:>6.2f}%")
        lines.append(f"  Session High:           ${dd['peak_value']:>10,.2f}")
        lines.append("")
        
        # Action items
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
    
    def generate_weekly_digest(self) -> str:
        """
        Generate comprehensive weekly digest (call on Fridays).
        
        Returns formatted weekly digest string.
        """
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
                print(f"[REPORTING] Exported {len(trades)} trades to {filename}")
            else:
                print(f"[REPORTING] No trades to export for {session_date}")
    
    def get_daily_report_dict(self, session_date: str = None) -> Dict:
        """
        Get daily digest data as structured dictionary (for JSON export).
        
        Returns complete digest data as dict.
        """
        session_date = session_date or self._get_session_date()
        
        if not ANALYTICS_ENABLED:
            return self.daily_reporter.build_pnl_summary()
        
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
# GLOBAL INSTANCES & CONVENIENCE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

digest_manager = EODDigestManager()
_daily_reporter = DailyReporter()


def send_pnl_digest() -> bool:
    """
    Build and send the daily P&L digest to Discord.
    
    Main entry point for simple Discord EOD reporting.
    Safe to call anytime - silent no-op if no trades or Discord unavailable.
    """
    print("[REPORTING] Building daily P&L digest...")
    try:
        summary = _daily_reporter.build_pnl_summary()
        message = _daily_reporter.format_discord_digest(summary)
        
        # Print to console
        print("\n" + message + "\n")
        
        # Send to Discord
        from discord_helpers import send_simple_message
        send_simple_message(message)
        print("[REPORTING] ✅ Digest sent to Discord")
        return True
        
    except Exception as e:
        print(f"[REPORTING] Error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Consolidated Reporting Module...\n")
    
    # Test simple digest
    print("=" * 70)
    print("SIMPLE DISCORD DIGEST:")
    print("=" * 70)
    send_pnl_digest()
    
    # Test comprehensive digest
    if ANALYTICS_ENABLED:
        print("\n" + "=" * 70)
        print("COMPREHENSIVE EOD DIGEST:")
        print("=" * 70)
        print(digest_manager.generate_daily_digest())
        
        # Check if Friday for weekly digest
        if _now_et().weekday() == 4:
            print("\n" + "=" * 70)
            print("WEEKLY DIGEST:")
            print("=" * 70)
            print(digest_manager.generate_weekly_digest())
    else:
        print("\n[REPORTING] Analytics modules not available for comprehensive digest")
