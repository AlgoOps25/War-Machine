#!/usr/bin/env python3
"""
Performance Alert System

Automated Discord alerts for trading performance milestones, risk warnings,
and circuit breaker status.

Alert Categories:
  1. Circuit Breaker Alerts - Risk management warnings
  2. Equity Milestones - Profit targets and new highs
  3. Momentum Alerts - Win/loss streaks
  4. Risk Exposure Alerts - Position and sector limits
  5. Scheduled Digests - Hourly/daily/weekly summaries

Usage:
  # In main trading loop:
  from performance_alerts import alert_manager
  
  # Check and send alerts (call every scan cycle)
  alert_manager.check_and_send_alerts()
  
  # Manual alerts
  alert_manager.send_circuit_breaker_warning()
  alert_manager.send_equity_milestone(milestone_type='daily_target')
  
  # Scheduled digests
  alert_manager.send_hourly_digest()  # Call every hour
  alert_manager.send_eod_summary()    # Call at market close
"""
from typing import Dict, Optional
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from utils import config

ET = ZoneInfo("America/New_York")

# Import performance monitor and Discord helpers
try:
    from . import performance_monitor
    from app.discord_helpers import send_simple_message
    ALERTS_ENABLED = True
except ImportError as e:
    print(f"[ALERTS] Warning: Could not import dependencies - {e}")
    ALERTS_ENABLED = False


class PerformanceAlertManager:
    """Manages automated performance alerts and notifications."""
    
    def __init__(self):
        self.last_alert_timestamps = {}
        self.alert_cooldowns = {
            'circuit_breaker_warning': 300,   # 5 minutes
            'circuit_breaker_critical': 120,  # 2 minutes
            'equity_high': 600,               # 10 minutes
            'win_streak': 1800,               # 30 minutes
            'loss_streak': 900,               # 15 minutes
            'risk_warning': 600,              # 10 minutes
            'hourly_digest': 3600             # 1 hour (enforced)
        }
        
        # Track state to avoid duplicate alerts
        self.alerted_today = set()
        self.last_equity_high = 0.0
    
    def _should_send_alert(self, alert_type: str) -> bool:
        """
        Check if alert cooldown has expired.
        
        Args:
            alert_type: Type of alert to check
        
        Returns:
            True if alert can be sent
        """
        if not ALERTS_ENABLED:
            return False
        
        last_sent = self.last_alert_timestamps.get(alert_type, 0)
        cooldown = self.alert_cooldowns.get(alert_type, 300)
        now = datetime.now(ET).timestamp()
        
        return (now - last_sent) >= cooldown
    
    def _mark_alert_sent(self, alert_type: str):
        """Record alert send timestamp."""
        self.last_alert_timestamps[alert_type] = datetime.now(ET).timestamp()
    
    def _is_market_hours(self) -> bool:
        """Check if current time is during market hours."""
        now = datetime.now(ET).time()
        return config.MARKET_OPEN <= now <= config.MARKET_CLOSE
    
    def send_circuit_breaker_warning(self, cb_status: Dict):
        """
        Send circuit breaker proximity alert.
        
        Args:
            cb_status: Circuit breaker status dict from performance_monitor
        """
        level = cb_status['warning_level']
        
        if level == 'TRIGGERED':
            alert_type = 'circuit_breaker_triggered'
            if not self._should_send_alert(alert_type):
                return
            
            message = (
                f"ðŸ›‘ **CIRCUIT BREAKER TRIGGERED** ðŸ›‘\n\n"
                f"Trading halted due to daily loss limit.\n\n"
                f"**Current Loss:** {cb_status['current_loss_pct']:.2f}%\n"
                f"**Trigger Threshold:** {cb_status['trigger_threshold_pct']:.2f}%\n\n"
                f"âŒ **No new positions until reset**"
            )
            send_simple_message(message)
            self._mark_alert_sent(alert_type)
        
        elif level == 'CRITICAL':
            alert_type = 'circuit_breaker_critical'
            if not self._should_send_alert(alert_type):
                return
            
            message = (
                f"ðŸš¨ **CIRCUIT BREAKER CRITICAL** ðŸš¨\n\n"
                f"Daily loss approaching circuit breaker trigger!\n\n"
                f"**Current Loss:** {cb_status['current_loss_pct']:.2f}%\n"
                f"**Distance to Trigger:** {cb_status['distance_to_trigger_pct']:.2f}%\n\n"
                f"âš ï¸ Reduce exposure immediately"
            )
            send_simple_message(message)
            self._mark_alert_sent(alert_type)
        
        elif level == 'WARNING':
            alert_type = 'circuit_breaker_warning'
            if not self._should_send_alert(alert_type):
                return
            
            message = (
                f"âš ï¸ **Circuit Breaker Warning** âš ï¸\n\n"
                f"Daily loss approaching -3% limit.\n\n"
                f"**Current Loss:** {cb_status['current_loss_pct']:.2f}%\n"
                f"**Distance to Trigger:** {cb_status['distance_to_trigger_pct']:.2f}%\n\n"
                f"ðŸ‘€ Monitor closely"
            )
            send_simple_message(message)
            self._mark_alert_sent(alert_type)
    
    def send_equity_milestone(self, milestone_type: str, pnl_data: Dict):
        """
        Send equity milestone alert.
        
        Args:
            milestone_type: 'daily_target', 'session_high', 'weekly_target'
            pnl_data: P&L data dict from performance_monitor
        """
        alert_key = f"equity_{milestone_type}"
        
        # Prevent duplicate daily alerts
        if alert_key in self.alerted_today:
            return
        
        if milestone_type == 'daily_target':
            if pnl_data['total_pnl_pct'] >= 2.0:
                message = (
                    f"ðŸŽ¯ **Daily Profit Target Hit!** ðŸŽ¯\n\n"
                    f"Session P&L: ${pnl_data['total_pnl']:,.2f} (+{pnl_data['total_pnl_pct']:.2f}%)\n"
                    f"Account Value: ${pnl_data['account_value']:,.2f}\n\n"
                    f"ðŸŽ‰ Excellent execution today!"
                )
                send_simple_message(message)
                self.alerted_today.add(alert_key)
        
        elif milestone_type == 'session_high':
            current_value = pnl_data['account_value']
            if current_value > self.last_equity_high and self._should_send_alert('equity_high'):
                message = (
                    f"ðŸ“ˆ **New Session High!** ðŸ“ˆ\n\n"
                    f"Account Value: ${current_value:,.2f}\n"
                    f"Session Gain: +{pnl_data['total_pnl_pct']:.2f}%\n\n"
                    f"ðŸ‘ Keep up the momentum!"
                )
                send_simple_message(message)
                self.last_equity_high = current_value
                self._mark_alert_sent('equity_high')
    
    def send_streak_alert(self, streak_data: Dict):
        """
        Send win/loss streak alert.
        
        Args:
            streak_data: Streak data dict from performance_monitor
        """
        streak = streak_data['current_streak']
        streak_type = streak_data['current_streak_type']
        
        # Win streak alerts
        if streak >= 5 and self._should_send_alert('win_streak'):
            message = (
                f"ðŸŽ¯ **EXCEPTIONAL WIN STREAK** ðŸŽ¯\n\n"
                f"Current streak: {streak} consecutive wins!\n"
                f"Momentum: {streak_data['current_momentum']}\n\n"
                f"ðŸ”¥ You're on fire! Stay focused."
            )
            send_simple_message(message)
            self._mark_alert_sent('win_streak')
        
        elif streak >= 3 and self._should_send_alert('win_streak'):
            message = (
                f"ðŸ”¥ **Hot Hand Detected** ðŸ”¥\n\n"
                f"Current streak: {streak} wins in a row\n"
                f"Momentum: {streak_data['current_momentum']}\n\n"
                f"ðŸ‘ Keep executing the system!"
            )
            send_simple_message(message)
            self._mark_alert_sent('win_streak')
        
        # Loss streak alerts
        elif streak <= -3 and self._should_send_alert('loss_streak'):
            message = (
                f"â„ï¸ **Loss Streak Alert** â„ï¸\n\n"
                f"Current streak: {abs(streak)} consecutive losses\n"
                f"Momentum: {streak_data['current_momentum']}\n\n"
                f"ðŸ‘€ Review your setup and confidence gates.\n"
                f"ðŸ’ª Stick to the system - variance is normal."
            )
            send_simple_message(message)
            self._mark_alert_sent('loss_streak')
    
    def send_risk_exposure_alert(self, risk_data: Dict):
        """
        Send risk exposure warning.
        
        Args:
            risk_data: Risk exposure dict from performance_monitor
        """
        if not risk_data['approaching_limits']:
            return
        
        if not self._should_send_alert('risk_warning'):
            return
        
        warnings_text = "\n".join([f"  â€¢ {w}" for w in risk_data['approaching_limits']])
        
        message = (
            f"âš ï¸ **Risk Exposure Warning** âš ï¸\n\n"
            f"One or more risk limits approaching:\n\n"
            f"{warnings_text}\n\n"
            f"**Current Exposure:**\n"
            f"  â€¢ Open Positions: {risk_data['open_positions']}/{config.MAX_OPEN_POSITIONS}\n"
            f"  â€¢ Total Exposure: {risk_data['total_exposure_pct']:.2f}%\n\n"
            f"ðŸ‘€ Review position sizing"
        )
        send_simple_message(message)
        self._mark_alert_sent('risk_warning')
    
    def send_hourly_digest(self):
        """
        Send hourly performance digest during market hours.
        """
        if not self._is_market_hours():
            return
        
        if not self._should_send_alert('hourly_digest'):
            return
        
        pnl = performance_monitor.get_session_pnl()
        cb = performance_monitor.get_circuit_breaker_status()
        risk = performance_monitor.get_risk_exposure()
        
        pnl_emoji = "ðŸ“ˆ" if pnl['total_pnl'] >= 0 else "ðŸ“‰"
        cb_emoji = {"SAFE": "âœ…", "WARNING": "âš ï¸", "CRITICAL": "ðŸš¨", "TRIGGERED": "ðŸ›‘"}[cb['warning_level']]
        
        message = (
            f"ðŸ“Š **Hourly Performance Update** ðŸ“Š\n\n"
            f"{pnl_emoji} **Session P&L:** ${pnl['total_pnl']:,.2f} ({pnl['total_pnl_pct']:+.2f}%)\n"
            f"  Realized: ${pnl['realized_pnl']:,.2f} | Unrealized: ${pnl['unrealized_pnl']:,.2f}\n\n"
            f"{cb_emoji} **Risk Status:** {cb['warning_level']}\n"
            f"  Distance to CB: {cb['distance_to_trigger_pct']:.2f}%\n\n"
            f"ðŸ’¼ **Positions:** {pnl['trades_closed']} closed, {pnl['trades_open']} open\n"
            f"ðŸ“ **Exposure:** {risk['total_exposure_pct']:.2f}%"
        )
        
        send_simple_message(message)
        self._mark_alert_sent('hourly_digest')
    
    def send_eod_summary(self):
        """
        Send end-of-day performance summary.
        """
        # Get comprehensive report from performance monitor
        report = performance_monitor.get_daily_performance_report()
        
        # Extract key stats for Discord formatting
        pnl = performance_monitor.get_session_pnl()
        win_rates = performance_monitor.get_win_rate_by_grade(days=1)
        streak = performance_monitor.get_streak_stats(days=7)
        
        pnl_emoji = "ðŸ“ˆ" if pnl['total_pnl'] >= 0 else "ðŸ“‰"
        overall_wr = win_rates.get('overall', {}).get('win_rate', 0)
        
        message = (
            f"ðŸŽ† **END OF DAY SUMMARY** ðŸŽ†\n\n"
            f"{pnl_emoji} **Daily P&L:** ${pnl['total_pnl']:,.2f} ({pnl['total_pnl_pct']:+.2f}%)\n"
            f"ðŸŽ¯ **Win Rate:** {overall_wr:.1f}% ({win_rates['overall']['wins']}W-{win_rates['overall']['losses']}L)\n"
            f"ðŸ”¥ **Streak:** {abs(streak['current_streak'])} {streak['current_streak_type']}\n"
            f"ðŸ“Š **Account:** ${pnl['account_value']:,.2f}\n\n"
            f"ðŸ‘‰ Full report in console logs"
        )
        
        send_simple_message(message)
        
        # Print full report to console
        print("\n" + report)
    
    def check_and_send_alerts(self):
        """
        Check all alert conditions and send as needed.
        Call this every scan cycle during market hours.
        """
        if not ALERTS_ENABLED:
            return
        
        # Get current performance data
        pnl = performance_monitor.get_session_pnl()
        cb = performance_monitor.get_circuit_breaker_status()
        risk = performance_monitor.get_risk_exposure()
        streak = performance_monitor.get_streak_stats(days=7)
        
        # Check circuit breaker
        if cb['warning_level'] in ['WARNING', 'CRITICAL', 'TRIGGERED']:
            self.send_circuit_breaker_warning(cb)
        
        # Check equity milestones
        if pnl['total_pnl_pct'] >= 2.0:
            self.send_equity_milestone('daily_target', pnl)
        
        self.send_equity_milestone('session_high', pnl)
        
        # Check streaks
        if abs(streak['current_streak']) >= 3:
            self.send_streak_alert(streak)
        
        # Check risk exposure
        if risk['approaching_limits']:
            self.send_risk_exposure_alert(risk)
    
    def reset_daily_state(self):
        """Reset daily tracking state at EOD."""
        self.alerted_today.clear()
        self.last_equity_high = 0.0
        print("[ALERTS] Daily state reset")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# GLOBAL INSTANCE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

alert_manager = PerformanceAlertManager()


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# USAGE EXAMPLE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

if __name__ == "__main__":
    print("Testing Performance Alert Manager...\n")
    
    if ALERTS_ENABLED:
        # Example: Check all alerts
        alert_manager.check_and_send_alerts()
        
        print("Alert system ready. Alerts will be sent to Discord when conditions are met.")
    else:
        print("Alert system disabled - dependencies not available.")





