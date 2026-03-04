"""
Performance Reporter for War Machine
Generate daily summaries and send to Discord
"""

import psycopg2
from datetime import datetime, date
import logging
import requests
import json

class PerformanceReporter:
    def __init__(self, db_connection, discord_webhook_url=None):
        self.db = db_connection
        self.webhook_url = discord_webhook_url
        logging.info("[REPORTER] Performance reporter initialized")
    
    def generate_eod_report(self, target_date=None):
        """
        Generate end-of-day performance report
        Returns: dict with summary stats
        """
        if target_date is None:
            target_date = date.today()
        
        try:
            cursor = self.db.cursor()
            
            # Overall stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_signals,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    ROUND(AVG(CASE WHEN outcome IS NOT NULL THEN profit_pct END), 2) as avg_profit,
                    ROUND(SUM(CASE WHEN outcome IS NOT NULL THEN profit_pct END), 2) as total_profit,
                    ROUND(AVG(CASE WHEN outcome IS NOT NULL THEN hold_minutes END), 0) as avg_hold
                FROM signal_outcomes
                WHERE DATE(signal_time) = %s
            """, (target_date,))
            
            stats = cursor.fetchone()
            total, wins, losses, avg_profit, total_profit, avg_hold = stats
            
            if total == 0:
                logging.info(f"[REPORTER] No signals for {target_date}")
                return None
            
            win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
            
            # Pattern breakdown
            cursor.execute("""
                SELECT 
                    pattern,
                    COUNT(*) as count,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    ROUND(AVG(profit_pct), 2) as avg_profit
                FROM signal_outcomes
                WHERE DATE(signal_time) = %s AND outcome IS NOT NULL
                GROUP BY pattern
                ORDER BY count DESC
            """, (target_date,))
            
            pattern_stats = []
            for row in cursor.fetchall():
                pattern, count, pat_wins, pat_avg = row
                pattern_stats.append({
                    'pattern': pattern,
                    'count': count,
                    'wins': pat_wins,
                    'avg_profit': pat_avg
                })
            
            # Best/worst trades
            cursor.execute("""
                SELECT ticker, profit_pct, profit_r, pattern
                FROM signal_outcomes
                WHERE DATE(signal_time) = %s AND outcome IS NOT NULL
                ORDER BY profit_pct DESC
                LIMIT 3
            """, (target_date,))
            best_trades = cursor.fetchall()
            
            cursor.execute("""
                SELECT ticker, profit_pct, profit_r, pattern
                FROM signal_outcomes
                WHERE DATE(signal_time) = %s AND outcome IS NOT NULL
                ORDER BY profit_pct ASC
                LIMIT 3
            """, (target_date,))
            worst_trades = cursor.fetchall()
            
            report = {
                'date': str(target_date),
                'total_signals': total,
                'wins': wins,
                'losses': losses,
                'win_rate': round(win_rate, 1),
                'avg_profit': avg_profit,
                'total_profit': total_profit,
                'avg_hold_minutes': int(avg_hold) if avg_hold else 0,
                'pattern_stats': pattern_stats,
                'best_trades': best_trades,
                'worst_trades': worst_trades
            }
            
            logging.info(f"[REPORTER] EOD report generated for {target_date}")
            return report
            
        except Exception as e:
            logging.error(f"[REPORTER] Failed to generate report: {e}")
            return None
    
    def send_to_discord(self, report):
        """
        Send EOD report to Discord webhook
        """
        if not self.webhook_url:
            logging.warning("[REPORTER] No Discord webhook URL configured")
            return False
        
        if not report:
            return False
        
        try:
            # Build message line by line
            lines = []
            lines.append(f"📊 **DAILY SUMMARY - {report['date']}**")
            lines.append("")
            lines.append(f"✅ **Trades:** {report['total_signals']} | W/L: {report['wins']}/{report['losses']} ({report['win_rate']}% WR)")
            lines.append(f"💰 **Total P&L:** {report['total_profit']:+.2f}%")
            lines.append(f"📈 **Avg Profit:** {report['avg_profit']:+.2f}%")
            lines.append(f"⏱️ **Avg Hold:** {report['avg_hold_minutes']}m")
            
            # Pattern breakdown
            if report['pattern_stats']:
                lines.append("")
                lines.append("📋 **Pattern Performance:**")
                for ps in report['pattern_stats']:
                    lines.append(f"  • {ps['pattern']}: {ps['count']} trades, {ps['wins']} wins, {ps['avg_profit']:+.2f}% avg")
            
            # Best trades
            if report['best_trades']:
                lines.append("")
                lines.append("🏆 **Top Trades:**")
                for ticker, pct, r, pattern in report['best_trades']:
                    lines.append(f"  • {ticker}: {pct:+.2f}% ({r:.2f}R) - {pattern}")
            
            # Worst trades
            if report['worst_trades']:
                lines.append("")
                lines.append("⚠️ **Worst Trades:**")
                for ticker, pct, r, pattern in report['worst_trades']:
                    lines.append(f"  • {ticker}: {pct:+.2f}% ({r:.2f}R) - {pattern}")
            
            message = "\n".join(lines)
            
            # Send to Discord
            payload = {"content": message}
            response = requests.post(self.webhook_url, json=payload, timeout=5)
            
            if response.status_code == 204:
                logging.info("[REPORTER] EOD report sent to Discord")
                return True
            else:
                logging.error(f"[REPORTER] Discord webhook failed: {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"[REPORTER] Failed to send Discord message: {e}")
            return False
    
    def schedule_eod_report(self):
        """
        Auto-generate and send EOD report at 4:05 PM
        Call this in your main loop
        """
        now = datetime.now()
        if now.hour == 16 and now.minute == 5:
            logging.info("[REPORTER] Running scheduled EOD report...")
            report = self.generate_eod_report()
            if report:
                self.send_to_discord(report)
