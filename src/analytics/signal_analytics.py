"""
Signal Analytics Module for War Machine
Tracks signal outcomes, performance metrics, and ML training data
"""

import psycopg2
from datetime import datetime, timedelta
import logging

class SignalAnalytics:
    def __init__(self, db_connection):
        self.db = db_connection
        self.active_signals = {}  # Track live signals {ticker: signal_data}
        self.fired_today = {}  # Deduplication: {ticker: last_signal_time}
        self.cooldown_minutes = 30  # Prevent re-signals within 30 min
        logging.info("[ANALYTICS] Signal tracking initialized")
    
    def should_fire_signal(self, ticker):
        """
        Check if signal should fire (deduplication logic)
        Returns: (bool, str) - (should_fire, reason)
        """
        if ticker not in self.fired_today:
            return True, "New signal"
        
        last_fire = self.fired_today[ticker]
        minutes_since = (datetime.now() - last_fire).total_seconds() / 60
        
        if minutes_since < self.cooldown_minutes:
            return False, f"Cooldown active ({int(minutes_since)}m / {self.cooldown_minutes}m)"
        
        return True, "Cooldown expired"
    
    def log_signal(self, signal_data):
        """
        Log a new signal when it fires
        Returns: signal_id or None
        """
        ticker = signal_data['ticker']
        
        # Deduplication check
        should_fire, reason = self.should_fire_signal(ticker)
        if not should_fire:
            logging.info(f"[ANALYTICS] ⏸️ {ticker} signal blocked: {reason}")
            return None
        
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                INSERT INTO signal_outcomes (
                    ticker, signal_time, pattern, confidence,
                    entry_price, stop_loss, target_1, target_2,
                    regime, vix_level, spy_trend, rvol, score,
                    explosive_override
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                ticker,
                signal_data['signal_time'],
                signal_data['pattern'],
                signal_data['confidence'],
                signal_data['entry_price'],
                signal_data['stop_loss'],
                signal_data['target_1'],
                signal_data['target_2'],
                signal_data['regime'],
                signal_data['vix_level'],
                signal_data['spy_trend'],
                signal_data['rvol'],
                signal_data['score'],
                signal_data.get('explosive_override', False)
            ))
            
            signal_id = cursor.fetchone()[0]
            self.db.commit()
            
            # Track for deduplication and monitoring
            self.fired_today[ticker] = signal_data['signal_time']
            self.active_signals[ticker] = {
                'id': signal_id,
                'entry_price': signal_data['entry_price'],
                'stop_loss': signal_data['stop_loss'],
                'target_1': signal_data['target_1'],
                'target_2': signal_data['target_2'],
                'signal_time': signal_data['signal_time']
            }
            
            logging.info(f"[ANALYTICS] ✅ Signal logged: {ticker} (ID: {signal_id})")
            return signal_id
            
        except Exception as e:
            logging.error(f"[ANALYTICS] ❌ Failed to log signal: {e}")
            self.db.rollback()
            return None
    
    def monitor_active_signals(self, current_prices):
        """
        Check active signals against current prices
        Call this every minute during market hours
        """
        for ticker, signal in list(self.active_signals.items()):
            if ticker not in current_prices:
                continue
            
            price = current_prices[ticker]
            
            # Check if T1 hit
            if price >= signal['target_1'] and not signal.get('t1_hit'):
                self._update_target_hit(signal['id'], 't1', price)
                signal['t1_hit'] = True
                logging.info(f"[ANALYTICS] 🎯 {ticker} T1 HIT @ ${price:.2f}")
            
            # Check if T2 hit (implies T1 also hit)
            if price >= signal['target_2']:
                self._close_signal(signal['id'], ticker, price, 'WIN', hit_t2=True)
                del self.active_signals[ticker]
                logging.info(f"[ANALYTICS] 🎯 {ticker} T2 HIT @ ${price:.2f} - CLOSED")
            
            # Check if stopped out
            elif price <= signal['stop_loss']:
                self._close_signal(signal['id'], ticker, price, 'LOSS', stopped_out=True)
                del self.active_signals[ticker]
                logging.info(f"[ANALYTICS] 🛑 {ticker} STOPPED OUT @ ${price:.2f}")
            
            # Auto-close after 30 minutes (time-based exit)
            elif datetime.now() - signal['signal_time'] > timedelta(minutes=30):
                outcome = 'WIN' if price > signal['entry_price'] else 'BREAKEVEN'
                self._close_signal(signal['id'], ticker, price, outcome)
                del self.active_signals[ticker]
                logging.info(f"[ANALYTICS] ⏰ {ticker} TIME EXIT @ ${price:.2f} ({outcome})")
    
    def _update_target_hit(self, signal_id, target, price):
        """Mark T1 or T2 as hit"""
        try:
            cursor = self.db.cursor()
            cursor.execute(f"""
                UPDATE signal_outcomes
                SET hit_{target} = TRUE
                WHERE id = %s
            """, (signal_id,))
            self.db.commit()
        except Exception as e:
            logging.error(f"[ANALYTICS] Failed to update target: {e}")
    
    def _close_signal(self, signal_id, ticker, exit_price, outcome, hit_t2=False, stopped_out=False):
        """Close an active signal and calculate metrics"""
        try:
            cursor = self.db.cursor()
            
            # Get original signal data
            cursor.execute("""
                SELECT entry_price, stop_loss, signal_time, pattern
                FROM signal_outcomes WHERE id = %s
            """, (signal_id,))
            entry_price, stop_loss, signal_time, pattern = cursor.fetchone()
            
            # Calculate metrics
            exit_time = datetime.now()
            hold_minutes = int((exit_time - signal_time).total_seconds() / 60)
            profit_pct = ((exit_price - entry_price) / entry_price) * 100
            risk = entry_price - stop_loss
            profit_r = (exit_price - entry_price) / risk if risk > 0 else 0
            
            # Update outcome
            cursor.execute("""
                UPDATE signal_outcomes
                SET outcome = %s,
                    exit_price = %s,
                    exit_time = %s,
                    hold_minutes = %s,
                    profit_pct = %s,
                    profit_r = %s,
                    hit_t2 = %s,
                    stopped_out = %s
                WHERE id = %s
            """, (outcome, exit_price, exit_time, hold_minutes, profit_pct, profit_r, hit_t2, stopped_out, signal_id))
            
            self.db.commit()
            
            # Update pattern performance
            self._update_pattern_stats(pattern)
            
            # Feed ML training data
            self._feed_ml_training(signal_id, outcome == 'WIN', profit_r)
            
            logging.info(f"[ANALYTICS] ✅ {ticker} closed: {outcome} | P&L: {profit_pct:.2f}% ({profit_r:.2f}R) | Hold: {hold_minutes}m")
            
        except Exception as e:
            logging.error(f"[ANALYTICS] Failed to close signal: {e}")
            self.db.rollback()
    
    def _update_pattern_stats(self, pattern):
        """Update aggregate stats for this pattern"""
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                INSERT INTO pattern_performance (pattern, total_trades, wins, losses, win_rate, avg_profit_pct, avg_hold_minutes)
                SELECT 
                    pattern,
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    (SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END)::DECIMAL / COUNT(*)) * 100 as win_rate,
                    AVG(profit_pct) as avg_profit_pct,
                    AVG(hold_minutes) as avg_hold_minutes
                FROM signal_outcomes
                WHERE pattern = %s AND outcome IS NOT NULL
                GROUP BY pattern
                ON CONFLICT (pattern) 
                DO UPDATE SET
                    total_trades = EXCLUDED.total_trades,
                    wins = EXCLUDED.wins,
                    losses = EXCLUDED.losses,
                    win_rate = EXCLUDED.win_rate,
                    avg_profit_pct = EXCLUDED.avg_profit_pct,
                    avg_hold_minutes = EXCLUDED.avg_hold_minutes,
                    updated_at = NOW()
            """, (pattern,))
            self.db.commit()
        except Exception as e:
            logging.error(f"[ANALYTICS] Failed to update pattern stats: {e}")
    
    def _feed_ml_training(self, signal_id, outcome, profit_r):
        """Add data to ML training table"""
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                INSERT INTO ml_training_data (signal_id, rvol, vix, score, time_of_day, confidence, regime, outcome, profit_r)
                SELECT 
                    id,
                    rvol,
                    vix_level,
                    score,
                    TO_CHAR(signal_time, 'HH24:MI') as time_of_day,
                    confidence,
                    regime,
                    %s,
                    %s
                FROM signal_outcomes
                WHERE id = %s
            """, (outcome, profit_r, signal_id))
            self.db.commit()
        except Exception as e:
            logging.error(f"[ANALYTICS] Failed to feed ML training: {e}")
    
    def get_today_stats(self):
        """Get today's performance summary"""
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    AVG(CASE WHEN outcome IS NOT NULL THEN profit_pct END) as avg_profit,
                    SUM(CASE WHEN outcome IS NOT NULL THEN profit_pct END) as total_profit
                FROM signal_outcomes
                WHERE DATE(signal_time) = CURRENT_DATE
            """)
            row = cursor.fetchone()
            return {
                'total': row[0] or 0,
                'wins': row[1] or 0,
                'losses': row[2] or 0,
                'avg_profit': row[3] or 0,
                'total_profit': row[4] or 0
            }
        except Exception as e:
            logging.error(f"[ANALYTICS] Failed to get today stats: {e}")
            return None
    
    def reset_daily_cooldowns(self):
        """Clear deduplication tracking at market open"""
        self.fired_today.clear()
        self.active_signals.clear()
        logging.info("[ANALYTICS] 🔄 Daily cooldowns reset")