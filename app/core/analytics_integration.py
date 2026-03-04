"""\nAnalytics Integration Helper for War Machine Scanner\nProvides easy integration of signal analytics, ML, and reporting\n"""

import logging
from datetime import datetime
import os
from src.analytics.signal_analytics import SignalAnalytics
from src.learning.ml_feedback_loop import MLFeedbackLoop
from src.reporting.performance_reporter import PerformanceReporter


class AnalyticsIntegration:
    """\n    Helper class to integrate analytics into War Machine scanner\n    
    Usage in scanner.py:
        self.analytics_integration = AnalyticsIntegration(db_connection)
        
        # Before Discord alert:
        signal_id = self.analytics_integration.process_signal(signal_data)
        if signal_id:
            send_discord_alert(signal_data)
    """
    
    def __init__(self, db_connection, enable_ml=True, enable_discord=True):
        self.db = db_connection
        self.enable_ml = enable_ml
        self.enable_discord = enable_discord
        
        # Initialize analytics modules
        self.analytics = SignalAnalytics(db_connection)
        self.ml_loop = MLFeedbackLoop(db_connection) if enable_ml else None
        
        discord_webhook = os.getenv('DISCORD_WEBHOOK_URL') if enable_discord else None
        self.reporter = PerformanceReporter(db_connection, discord_webhook)
        
        # Time-based flags
        self.daily_reset_done = False
        self.eod_ml_done = False
        self.eod_report_done = False
        
        logging.info("[ANALYTICS] Integration initialized (ML: %s, Discord: %s)", 
                    enable_ml, enable_discord)
    
    def process_signal(self, signal_data, regime=None, vix_level=None, spy_trend=None):
        """\n        Process a signal through analytics pipeline\n        \n        Args:
            signal_data: Dict with ticker, pattern, confidence, entry, stop, t1, t2, rvol, score\n            regime: Current market regime (BULL/BEAR/NEUTRAL)\n            vix_level: Current VIX level\n            spy_trend: SPY trend direction\n            \n        Returns:
            signal_id if signal should fire, None if blocked\n        """
        ticker = signal_data['ticker']
        
        # Step 1: Deduplication check
        should_fire, reason = self.analytics.should_fire_signal(ticker)
        if not should_fire:
            logging.info(f"[ANALYTICS] ⏸️ {ticker} blocked: {reason}")
            return None
        
        # Step 2: Prepare signal data for logging
        log_data = {
            'ticker': ticker,
            'signal_time': datetime.now(),
            'pattern': signal_data.get('pattern', 'UNKNOWN'),
            'confidence': signal_data.get('confidence', 70),
            'entry_price': signal_data['entry'],
            'stop_loss': signal_data['stop'],
            'target_1': signal_data['t1'],
            'target_2': signal_data['t2'],
            'regime': regime or 'NEUTRAL',
            'vix_level': vix_level or 20.0,
            'spy_trend': spy_trend or 'NEUTRAL',
            'rvol': signal_data.get('rvol', 1.0),
            'score': signal_data.get('score', 50),
            'explosive_override': signal_data.get('explosive_override', False)
        }
        
        # Step 3: ML confidence adjustment (optional)
        if self.ml_loop and self.enable_ml:
            try:
                confidence_adj, win_prob = self.ml_loop.predict_signal_quality(log_data)
                log_data['confidence'] += confidence_adj
                logging.info(f"[ANALYTICS] 🧠 {ticker} ML: {win_prob:.1%} win prob, {confidence_adj:+d}% adj")
            except Exception as e:
                logging.warning(f"[ANALYTICS] ML prediction failed: {e}")
        
        # Step 4: Log to database
        signal_id = self.analytics.log_signal(log_data)
        
        if signal_id:
            logging.info(f"[ANALYTICS] ✅ {ticker} signal logged (ID: {signal_id}, Confidence: {log_data['confidence']}%)")
        
        return signal_id
    
    def monitor_active_signals(self, price_fetcher):
        """\n        Monitor active signals for T1/T2/Stop hits\n        \n        Args:
            price_fetcher: Function that takes ticker and returns current price\n        """
        if not self.analytics.active_signals:
            return
        
        current_prices = {}
        for ticker in self.analytics.active_signals.keys():
            try:
                price = price_fetcher(ticker)
                if price:
                    current_prices[ticker] = price
            except Exception as e:
                logging.error(f"[ANALYTICS] Failed to fetch price for {ticker}: {e}")
        
        self.analytics.monitor_active_signals(current_prices)
    
    def check_scheduled_tasks(self):
        """\n        Run time-based tasks (market open/close routines)\n        Call this once per minute in your scanner loop\n        """
        now = datetime.now()
        
        # Market open (9:30 AM) - Reset daily cooldowns
        if now.hour == 9 and now.minute == 30 and not self.daily_reset_done:
            self.analytics.reset_daily_cooldowns()
            self.daily_reset_done = True
            self.eod_ml_done = False
            self.eod_report_done = False
            logging.info("[ANALYTICS] 🔄 Daily reset complete")
        
        # Market close (4:00 PM) - Train ML model
        if now.hour == 16 and now.minute == 0 and not self.eod_ml_done:
            if self.ml_loop and self.enable_ml:
                logging.info("[ANALYTICS] 🧠 Training ML model...")
                try:
                    success = self.ml_loop.train_model()
                    if success:
                        importance = self.ml_loop.get_feature_importance()
                        logging.info(f"[ANALYTICS] ML training complete. Top features: {importance}")
                except Exception as e:
                    logging.error(f"[ANALYTICS] ML training failed: {e}")
            self.eod_ml_done = True
        
        # EOD Report (4:05 PM) - Send performance summary
        if now.hour == 16 and now.minute == 5 and not self.eod_report_done:
            logging.info("[ANALYTICS] 📊 Generating EOD report...")
            try:
                report = self.reporter.generate_eod_report()
                if report and self.enable_discord:
                    success = self.reporter.send_to_discord(report)
                    if success:
                        logging.info("[ANALYTICS] EOD report sent to Discord")
                elif report:
                    logging.info(f"[ANALYTICS] EOD: {report['total_signals']} signals, {report['win_rate']}% WR, {report['total_profit']}% P&L")
            except Exception as e:
                logging.error(f"[ANALYTICS] EOD report failed: {e}")
            self.eod_report_done = True
        
        # Reset flags at midnight
        if now.hour == 0 and now.minute == 0:
            self.daily_reset_done = False
    
    def get_today_stats(self):
        """Get today's performance summary"""
        return self.analytics.get_today_stats()
