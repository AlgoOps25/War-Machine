"""
Performance Reporter for War Machine
Generates daily/weekly stats and insights
"""

import logging
from datetime import datetime, timedelta

class PerformanceReporter:
    def __init__(self, db_connection):
        self.db = db_connection
        logging.info("[REPORTER] Performance reporter initialized")
    
    def get_daily_summary(self):
        """Generate today's performance summary"""
        try:
            cursor = self.db.cursor()
            
            # Overall stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_signals,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    AVG(CASE WHEN outcome = 'WIN' THEN profit_pct END) as avg_win,
                    AVG(CASE WHEN outcome = 'LOSS' THEN profit_pct END) as avg_loss,
                    SUM(profit_pct) as total_profit,
                    AVG(hold_minutes) as avg_hold,
                    SUM(CASE WHEN hit_t1 THEN 1 ELSE 0 END) as t1_hits,
                    SUM(CASE WHEN hit_t2 THEN 1 ELSE 0 END) as t2_hits
                FROM signal_outcomes
                WHERE DATE(signal_time) = CURRENT_DATE
                AND outcome IS NOT NULL
            """)
            
            row = cursor.fetchone()
            
            if row[0] == 0:
                return "📊 **DAILY SUMMARY**\
No completed trades today"
            
            total, wins, losses, avg_win, avg_loss, total_profit, avg_hold, t1_hits, t2_hits = row
            win_rate = (wins / total * 100) if total > 0 else 0
            
            summary = f"""
📊 **DAILY SUMMARY** - {datetime.now().strftime('%Y-%m-%d')}

**Overall Performance:**
✅ Trades: {total} | W/L: {wins}/{losses} ({win_rate:.1f}% WR)
💰 Total P&L: {total_profit:.2f}%
📈 Avg Win: +{avg_win:.2f}% | Avg Loss: {avg_loss:.2f}%
⏱️ Avg Hold: {int(avg_hold)} minutes

**Target Achievement:**
🎯 T1 Hits: {t1_hits}/{total} ({t1_hits/total*100:.0f}%)
🎯 T2 Hits: {t2_hits}/{total} ({t2_hits/total*100:.0f}%)
"""
            
            # Best/worst trades
            cursor.execute("""
                SELECT ticker, profit_pct, hold_minutes
                FROM signal_outcomes
                WHERE DATE(signal_time) = CURRENT_DATE
                AND outcome IS NOT NULL
                ORDER BY profit_pct DESC
                LIMIT 3
            """)
            
            best_trades = cursor.fetchall()
            if best_trades:
                summary += "\
**Top Performers:**\
"
                for ticker, profit, hold in best_trades:
                    summary += f"• {ticker}: +{profit:.2f}% ({hold}m hold)\
"
            
            return summary
            
        except Exception as e:
            logging.error(f"[REPORTER] Failed to generate summary: {e}")
            return "Error generating report"
    
    def get_pattern_performance(self):
        """Get performance by pattern type"""
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT pattern, total_trades, win_rate, avg_profit_pct, avg_hold_minutes
                FROM pattern_performance
                ORDER BY total_trades DESC
                LIMIT 5
            """)
            
            rows = cursor.fetchall()
            
            report = "\
📈 **PATTERN PERFORMANCE**\
\
"
            for pattern, total, wr, avg_profit, avg_hold in rows:
                report += f"**{pattern}**\
"
                report += f"  Trades: {total} | WR: {wr:.1f}% | Avg: {avg_profit:.2f}% | Hold: {avg_hold}m\
\
"
            
            return report
            
        except Exception as e:
            logging.error(f"[REPORTER] Failed to get pattern performance: {e}")
            return ""
    
    def send_eod_report(self, webhook_url=None):
        """
        Send end-of-day report to Discord
        """
        summary = self.get_daily_summary()
        patterns = self.get_pattern_performance()
        
        full_report = summary + patterns
        
        logging.info(f"[REPORTER] 📧 EOD Report:\
{full_report}")
        
        # TODO: Send to Discord webhook if provided
        if webhook_url:
            # Discord webhook integration here
            pass
        
        return full_report
