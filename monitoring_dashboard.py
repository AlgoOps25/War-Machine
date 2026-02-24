"""
Monitoring Dashboard - Phase 4 Performance Visibility

Real-time visualization of War Machine trading system performance.
Provides actionable insights into signal quality, conversion rates,
and learning engine effectiveness.

Key Metrics:
  1. Signal Funnel Analysis - Where are signals dropping?
  2. Performance by Grade/Type/Ticker - What's working?
  3. Confidence Impact - Are multipliers helping?
  4. Validator Effectiveness - Which checks matter?
  5. Learning Engine Status - Is AI adapting correctly?

Usage:
  from monitoring_dashboard import dashboard
  
  # Real-time monitoring
  dashboard.print_live_summary()
  
  # End-of-day report
  dashboard.print_eod_report()
  
  # Send to Discord
  dashboard.send_discord_summary()
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import statistics

from db_connection import get_conn, dict_cursor, ph

# Import Discord helper (optional)
try:
    from discord_helpers import send_simple_message
    DISCORD_ENABLED = True
except ImportError:
    DISCORD_ENABLED = False
    print("[DASHBOARD] Discord integration disabled (discord_helpers not available)")

ET = ZoneInfo("America/New_York")


class MonitoringDashboard:
    """Real-time performance monitoring and reporting."""
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
    
    # ═════════════════════════════════════════════════════════════════════
    # SIGNAL FUNNEL ANALYSIS
    # ═════════════════════════════════════════════════════════════════════
    
    def get_signal_funnel(self, date: Optional[str] = None) -> Dict:
        """
        Get signal funnel conversion rates for a specific date.
        
        Args:
            date: Date string (YYYY-MM-DD) or None for today
        
        Returns:
            Dict with funnel metrics:
            {
                'generated': int,
                'validated': int,
                'armed': int,
                'traded': int,
                'conversion_rates': {
                    'gen_to_val': float,
                    'val_to_armed': float,
                    'armed_to_traded': float,
                    'gen_to_traded': float
                }
            }
        """
        if date is None:
            date = datetime.now(ET).strftime("%Y-%m-%d")
        
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p = ph()
            
            # Count signals at each stage
            cursor.execute(f"""
                SELECT 
                    stage,
                    COUNT(DISTINCT ticker) as count
                FROM signal_events
                WHERE session_date = {p}
                GROUP BY stage
            """, (date,))
            
            stage_counts = {row['stage']: row['count'] for row in cursor.fetchall()}
            conn.close()
            
            generated = stage_counts.get('GENERATED', 0)
            validated = stage_counts.get('VALIDATED', 0)
            armed = stage_counts.get('ARMED', 0)
            traded = stage_counts.get('TRADED', 0)
            
            # Calculate conversion rates
            gen_to_val = (validated / generated * 100) if generated > 0 else 0
            val_to_armed = (armed / validated * 100) if validated > 0 else 0
            armed_to_traded = (traded / armed * 100) if armed > 0 else 0
            gen_to_traded = (traded / generated * 100) if generated > 0 else 0
            
            return {
                'generated': generated,
                'validated': validated,
                'armed': armed,
                'traded': traded,
                'conversion_rates': {
                    'gen_to_val': round(gen_to_val, 1),
                    'val_to_armed': round(val_to_armed, 1),
                    'armed_to_traded': round(armed_to_traded, 1),
                    'gen_to_traded': round(gen_to_traded, 1)
                }
            }
        
        except Exception as e:
            print(f"[DASHBOARD] Signal funnel error: {e}")
            return {
                'generated': 0,
                'validated': 0,
                'armed': 0,
                'traded': 0,
                'conversion_rates': {
                    'gen_to_val': 0,
                    'val_to_armed': 0,
                    'armed_to_traded': 0,
                    'gen_to_traded': 0
                }
            }
    
    # ═════════════════════════════════════════════════════════════════════
    # PERFORMANCE BREAKDOWN
    # ═════════════════════════════════════════════════════════════════════
    
    def get_performance_by_grade(self, lookback_days: int = 30) -> Dict[str, Dict]:
        """
        Get win rate and P&L by signal grade.
        
        Args:
            lookback_days: Number of days to analyze
        
        Returns:
            Dict mapping grade -> {trades, wins, win_rate, avg_pnl, total_pnl}
        """
        try:
            since = (datetime.now(ET) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p = ph()
            
            cursor.execute(f"""
                SELECT 
                    grade,
                    COUNT(*) as trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(pnl) as avg_pnl,
                    SUM(pnl) as total_pnl
                FROM positions
                WHERE status = 'CLOSED'
                  AND DATE(exit_time) >= {p}
                  AND grade IS NOT NULL
                GROUP BY grade
                ORDER BY grade DESC
            """, (since,))
            
            results = {}
            for row in cursor.fetchall():
                grade = row['grade']
                trades = row['trades']
                wins = row['wins'] or 0
                
                results[grade] = {
                    'trades': trades,
                    'wins': wins,
                    'losses': trades - wins,
                    'win_rate': round((wins / trades * 100) if trades > 0 else 0, 1),
                    'avg_pnl': round(row['avg_pnl'] or 0, 2),
                    'total_pnl': round(row['total_pnl'] or 0, 2)
                }
            
            conn.close()
            return results
        
        except Exception as e:
            print(f"[DASHBOARD] Performance by grade error: {e}")
            return {}
    
    def get_performance_by_ticker(self, lookback_days: int = 30, min_trades: int = 3) -> Dict[str, Dict]:
        """
        Get win rate and P&L by ticker.
        
        Args:
            lookback_days: Number of days to analyze
            min_trades: Minimum trades required to include ticker
        
        Returns:
            Dict mapping ticker -> {trades, wins, win_rate, avg_pnl, total_pnl}
        """
        try:
            since = (datetime.now(ET) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p = ph()
            
            cursor.execute(f"""
                SELECT 
                    ticker,
                    COUNT(*) as trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(pnl) as avg_pnl,
                    SUM(pnl) as total_pnl
                FROM positions
                WHERE status = 'CLOSED'
                  AND DATE(exit_time) >= {p}
                GROUP BY ticker
                HAVING COUNT(*) >= {p}
                ORDER BY total_pnl DESC
            """, (since, min_trades))
            
            results = {}
            for row in cursor.fetchall():
                ticker = row['ticker']
                trades = row['trades']
                wins = row['wins'] or 0
                
                results[ticker] = {
                    'trades': trades,
                    'wins': wins,
                    'losses': trades - wins,
                    'win_rate': round((wins / trades * 100) if trades > 0 else 0, 1),
                    'avg_pnl': round(row['avg_pnl'] or 0, 2),
                    'total_pnl': round(row['total_pnl'] or 0, 2)
                }
            
            conn.close()
            return results
        
        except Exception as e:
            print(f"[DASHBOARD] Performance by ticker error: {e}")
            return {}
    
    def get_performance_by_signal_type(self, lookback_days: int = 30) -> Dict[str, Dict]:
        """
        Get win rate comparison: OR-anchored vs Intraday BOS signals.
        
        Args:
            lookback_days: Number of days to analyze
        
        Returns:
            Dict mapping signal_type -> {trades, wins, win_rate, avg_pnl}
        """
        try:
            since = (datetime.now(ET) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p = ph()
            
            # Join signal_events with positions to get signal_type
            cursor.execute(f"""
                SELECT 
                    se.signal_type,
                    COUNT(*) as trades,
                    SUM(CASE WHEN p.pnl > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(p.pnl) as avg_pnl,
                    SUM(p.pnl) as total_pnl
                FROM signal_events se
                JOIN positions p ON se.position_id = p.id
                WHERE p.status = 'CLOSED'
                  AND DATE(p.exit_time) >= {p}
                  AND se.stage = 'TRADED'
                GROUP BY se.signal_type
            """, (since,))
            
            results = {}
            for row in cursor.fetchall():
                signal_type = row['signal_type']
                trades = row['trades']
                wins = row['wins'] or 0
                
                results[signal_type] = {
                    'trades': trades,
                    'wins': wins,
                    'losses': trades - wins,
                    'win_rate': round((wins / trades * 100) if trades > 0 else 0, 1),
                    'avg_pnl': round(row['avg_pnl'] or 0, 2),
                    'total_pnl': round(row['total_pnl'] or 0, 2)
                }
            
            conn.close()
            return results
        
        except Exception as e:
            print(f"[DASHBOARD] Performance by signal type error: {e}")
            return {}
    
    # ═════════════════════════════════════════════════════════════════════
    # CONFIDENCE ANALYSIS
    # ═════════════════════════════════════════════════════════════════════
    
    def get_confidence_distribution(self, date: Optional[str] = None) -> Dict:
        """
        Analyze confidence score distribution and accuracy.
        
        Args:
            date: Date string or None for today
        
        Returns:
            Dict with confidence buckets and their win rates
        """
        if date is None:
            date = datetime.now(ET).strftime("%Y-%m-%d")
        
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p = ph()
            
            # Get confidence scores and outcomes
            cursor.execute(f"""
                SELECT 
                    se.final_confidence,
                    p.pnl
                FROM signal_events se
                JOIN positions p ON se.position_id = p.id
                WHERE se.stage = 'ARMED'
                  AND p.status = 'CLOSED'
                  AND DATE(p.exit_time) = {p}
            """, (date,))
            
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                return {}
            
            # Bucket confidence scores
            buckets = {
                '40-50%': [],
                '50-60%': [],
                '60-70%': [],
                '70-80%': [],
                '80-90%': [],
                '90%+': []
            }
            
            for row in rows:
                conf = (row['final_confidence'] or 0) * 100
                pnl = row['pnl'] or 0
                
                if conf < 50:
                    buckets['40-50%'].append(pnl)
                elif conf < 60:
                    buckets['50-60%'].append(pnl)
                elif conf < 70:
                    buckets['60-70%'].append(pnl)
                elif conf < 80:
                    buckets['70-80%'].append(pnl)
                elif conf < 90:
                    buckets['80-90%'].append(pnl)
                else:
                    buckets['90%+'].append(pnl)
            
            # Calculate win rate per bucket
            results = {}
            for bucket, pnls in buckets.items():
                if not pnls:
                    continue
                
                wins = sum(1 for pnl in pnls if pnl > 0)
                results[bucket] = {
                    'trades': len(pnls),
                    'wins': wins,
                    'win_rate': round((wins / len(pnls) * 100) if pnls else 0, 1),
                    'avg_pnl': round(statistics.mean(pnls), 2)
                }
            
            return results
        
        except Exception as e:
            print(f"[DASHBOARD] Confidence distribution error: {e}")
            return {}
    
    def get_multiplier_impact(self, lookback_days: int = 7) -> Dict:
        """
        Analyze impact of confidence multipliers (IVR, UOA, GEX, MTF).
        
        Args:
            lookback_days: Number of days to analyze
        
        Returns:
            Dict with average multiplier values and their correlation to wins
        """
        try:
            since = (datetime.now(ET) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p = ph()
            
            cursor.execute(f"""
                SELECT 
                    se.ivr_multiplier,
                    se.uoa_multiplier,
                    se.gex_multiplier,
                    se.mtf_boost,
                    se.ticker_multiplier,
                    se.base_confidence,
                    se.final_confidence,
                    p.pnl
                FROM signal_events se
                JOIN positions p ON se.position_id = p.id
                WHERE se.stage = 'ARMED'
                  AND p.status = 'CLOSED'
                  AND DATE(p.exit_time) >= {p}
            """, (since,))
            
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                return {}
            
            # Calculate average multipliers and win correlation
            multipliers = {
                'ivr': [],
                'uoa': [],
                'gex': [],
                'mtf': [],
                'ticker': []
            }
            
            wins_by_mult = {
                'ivr': {'wins': 0, 'total': 0},
                'uoa': {'wins': 0, 'total': 0},
                'gex': {'wins': 0, 'total': 0},
                'mtf': {'wins': 0, 'total': 0},
                'ticker': {'wins': 0, 'total': 0}
            }
            
            for row in rows:
                is_win = (row['pnl'] or 0) > 0
                
                # Track multipliers
                if row['ivr_multiplier'] and row['ivr_multiplier'] > 1.0:
                    multipliers['ivr'].append(row['ivr_multiplier'])
                    wins_by_mult['ivr']['total'] += 1
                    if is_win:
                        wins_by_mult['ivr']['wins'] += 1
                
                if row['uoa_multiplier'] and row['uoa_multiplier'] > 1.0:
                    multipliers['uoa'].append(row['uoa_multiplier'])
                    wins_by_mult['uoa']['total'] += 1
                    if is_win:
                        wins_by_mult['uoa']['wins'] += 1
                
                if row['gex_multiplier'] and row['gex_multiplier'] > 1.0:
                    multipliers['gex'].append(row['gex_multiplier'])
                    wins_by_mult['gex']['total'] += 1
                    if is_win:
                        wins_by_mult['gex']['wins'] += 1
                
                if row['mtf_boost'] and row['mtf_boost'] > 0:
                    multipliers['mtf'].append(row['mtf_boost'])
                    wins_by_mult['mtf']['total'] += 1
                    if is_win:
                        wins_by_mult['mtf']['wins'] += 1
                
                if row['ticker_multiplier'] and row['ticker_multiplier'] > 1.0:
                    multipliers['ticker'].append(row['ticker_multiplier'])
                    wins_by_mult['ticker']['total'] += 1
                    if is_win:
                        wins_by_mult['ticker']['wins'] += 1
            
            # Calculate results
            results = {}
            for name, values in multipliers.items():
                if not values:
                    continue
                
                stats = wins_by_mult[name]
                win_rate = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
                
                results[name.upper()] = {
                    'avg_value': round(statistics.mean(values), 3),
                    'trades_boosted': stats['total'],
                    'win_rate': round(win_rate, 1)
                }
            
            return results
        
        except Exception as e:
            print(f"[DASHBOARD] Multiplier impact error: {e}")
            return {}
    
    # ═════════════════════════════════════════════════════════════════════
    # VALIDATOR STATISTICS
    # ═════════════════════════════════════════════════════════════════════
    
    def get_validator_stats(self, date: Optional[str] = None) -> Dict:
        """
        Get validator check pass/fail statistics.
        
        Args:
            date: Date string or None for today
        
        Returns:
            Dict with validator effectiveness metrics
        """
        if date is None:
            date = datetime.now(ET).strftime("%Y-%m-%d")
        
        try:
            conn = get_conn(self.db_path)
            cursor = dict_cursor(conn)
            p = ph()
            
            cursor.execute(f"""
                SELECT 
                    validation_passed,
                    rejection_reason,
                    COUNT(*) as count
                FROM signal_events
                WHERE stage IN ('VALIDATED', 'REJECTED')
                  AND session_date = {p}
                GROUP BY validation_passed, rejection_reason
            """, (date,))
            
            rows = cursor.fetchall()
            conn.close()
            
            passed = sum(row['count'] for row in rows if row['validation_passed'] == 1)
            failed = sum(row['count'] for row in rows if row['validation_passed'] == 0)
            
            # Count rejection reasons
            rejections = defaultdict(int)
            for row in rows:
                if row['validation_passed'] == 0 and row['rejection_reason']:
                    rejections[row['rejection_reason']] += row['count']
            
            return {
                'passed': passed,
                'failed': failed,
                'pass_rate': round((passed / (passed + failed) * 100) if (passed + failed) > 0 else 0, 1),
                'top_rejections': dict(sorted(rejections.items(), key=lambda x: x[1], reverse=True)[:5])
            }
        
        except Exception as e:
            print(f"[DASHBOARD] Validator stats error: {e}")
            return {'passed': 0, 'failed': 0, 'pass_rate': 0, 'top_rejections': {}}
    
    # ═════════════════════════════════════════════════════════════════════
    # LEARNING ENGINE STATUS
    # ═════════════════════════════════════════════════════════════════════
    
    def get_learning_engine_status(self) -> Dict:
        """
        Get AI learning engine adaptation status.
        
        Returns:
            Dict with ticker multipliers and recent adjustments
        """
        try:
            from ai_learning import learning_engine
            
            # Get top performing tickers (multiplier > 1.0)
            boosted_tickers = {}
            penalized_tickers = {}
            
            # Sample common tickers
            sample_tickers = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD', 'GOOGL']
            
            for ticker in sample_tickers:
                mult = learning_engine.get_ticker_confidence_multiplier(ticker)
                if mult > 1.0:
                    boosted_tickers[ticker] = round(mult, 3)
                elif mult < 1.0:
                    penalized_tickers[ticker] = round(mult, 3)
            
            return {
                'boosted_tickers': dict(sorted(boosted_tickers.items(), key=lambda x: x[1], reverse=True)),
                'penalized_tickers': dict(sorted(penalized_tickers.items(), key=lambda x: x[1]))
            }
        
        except Exception as e:
            print(f"[DASHBOARD] Learning engine status error: {e}")
            return {'boosted_tickers': {}, 'penalized_tickers': {}}
    
    # ═════════════════════════════════════════════════════════════════════
    # REPORT GENERATION
    # ═════════════════════════════════════════════════════════════════════
    
    def print_live_summary(self):
        """Print real-time session summary to console."""
        print("\n" + "═"*80)
        print("WAR MACHINE - LIVE PERFORMANCE DASHBOARD")
        print("═"*80)
        print(f"Session: {datetime.now(ET).strftime('%A, %B %d, %Y %I:%M %p ET')}\n")
        
        # Signal Funnel
        funnel = self.get_signal_funnel()
        print("─"*80)
        print("SIGNAL FUNNEL")
        print("─"*80)
        print(f"  Generated:   {funnel['generated']:>3}")
        print(f"  Validated:   {funnel['validated']:>3}  ({funnel['conversion_rates']['gen_to_val']:>5.1f}% conversion)")
        print(f"  Armed:       {funnel['armed']:>3}  ({funnel['conversion_rates']['val_to_armed']:>5.1f}% conversion)")
        print(f"  Traded:      {funnel['traded']:>3}  ({funnel['conversion_rates']['armed_to_traded']:>5.1f}% conversion)")
        print(f"  ╭── Overall:  {funnel['conversion_rates']['gen_to_traded']:>5.1f}% (Generated → Traded)")
        
        # Performance by Grade
        by_grade = self.get_performance_by_grade(lookback_days=7)
        if by_grade:
            print("\n" + "─"*80)
            print("PERFORMANCE BY GRADE (7 Days)")
            print("─"*80)
            for grade in ['A+', 'A', 'A-']:
                if grade in by_grade:
                    stats = by_grade[grade]
                    print(f"  {grade:>2}:  {stats['trades']:>2} trades | "
                          f"{stats['win_rate']:>5.1f}% WR | "
                          f"Avg: ${stats['avg_pnl']:>+7.2f} | "
                          f"Total: ${stats['total_pnl']:>+8.2f}")
        
        # Validator Stats
        validator = self.get_validator_stats()
        if validator['passed'] + validator['failed'] > 0:
            print("\n" + "─"*80)
            print("VALIDATOR PERFORMANCE (Today)")
            print("─"*80)
            print(f"  Passed: {validator['passed']:>3} | Failed: {validator['failed']:>3} | "
                  f"Pass Rate: {validator['pass_rate']:>5.1f}%")
            if validator['top_rejections']:
                print("  Top Rejection Reasons:")
                for reason, count in list(validator['top_rejections'].items())[:3]:
                    print(f"    • {reason}: {count}")
        
        # Multiplier Impact
        mult_impact = self.get_multiplier_impact(lookback_days=7)
        if mult_impact:
            print("\n" + "─"*80)
            print("MULTIPLIER IMPACT (7 Days)")
            print("─"*80)
            for name, stats in mult_impact.items():
                print(f"  {name:>6}:  Avg {stats['avg_value']:.3f} | "
                      f"{stats['trades_boosted']:>2} trades | "
                      f"{stats['win_rate']:>5.1f}% WR")
        
        print("\n" + "═"*80 + "\n")
    
    def print_eod_report(self):
        """Print comprehensive end-of-day report."""
        print("\n" + "═"*80)
        print("WAR MACHINE - END OF DAY REPORT")
        print("═"*80)
        print(f"Date: {datetime.now(ET).strftime('%A, %B %d, %Y')}\n")
        
        # Get position manager stats
        try:
            from position_manager import position_manager
            daily_stats = position_manager.get_daily_stats()
            
            print("─"*80)
            print("TRADING PERFORMANCE")
            print("─"*80)
            print(f"  Total Trades:    {daily_stats['trades']}")
            print(f"  Winners:         {daily_stats['wins']}")
            print(f"  Losers:          {daily_stats['losses']}")
            print(f"  Win Rate:        {daily_stats['win_rate']:.1f}%")
            print(f"  Net P&L:         ${daily_stats['total_pnl']:+,.2f}")
        except Exception as e:
            print(f"[DASHBOARD] Could not load position stats: {e}")
        
        # Signal Funnel
        funnel = self.get_signal_funnel()
        print("\n" + "─"*80)
        print("SIGNAL FUNNEL ANALYSIS")
        print("─"*80)
        print(f"  Generated:       {funnel['generated']:>3}")
        print(f"  Validated:       {funnel['validated']:>3}  ({funnel['conversion_rates']['gen_to_val']:.1f}%)")
        print(f"  Armed:           {funnel['armed']:>3}  ({funnel['conversion_rates']['val_to_armed']:.1f}%)")
        print(f"  Traded:          {funnel['traded']:>3}  ({funnel['conversion_rates']['armed_to_traded']:.1f}%)")
        print(f"  Overall Efficiency: {funnel['conversion_rates']['gen_to_traded']:.1f}% (Gen → Traded)")
        
        # Performance breakdown
        by_type = self.get_performance_by_signal_type(lookback_days=7)
        if by_type:
            print("\n" + "─"*80)
            print("SIGNAL TYPE COMPARISON (7 Days)")
            print("─"*80)
            for sig_type, stats in by_type.items():
                print(f"  {sig_type:>15}:  {stats['trades']:>2} trades | "
                      f"{stats['win_rate']:>5.1f}% WR | "
                      f"Avg: ${stats['avg_pnl']:>+7.2f}")
        
        # Top/Bottom Tickers
        by_ticker = self.get_performance_by_ticker(lookback_days=7, min_trades=2)
        if by_ticker:
            print("\n" + "─"*80)
            print("TOP PERFORMING TICKERS (7 Days, min 2 trades)")
            print("─"*80)
            top_5 = sorted(by_ticker.items(), key=lambda x: x[1]['total_pnl'], reverse=True)[:5]
            for ticker, stats in top_5:
                print(f"  {ticker:>6}:  {stats['trades']:>2} trades | "
                      f"{stats['win_rate']:>5.1f}% WR | "
                      f"Total: ${stats['total_pnl']:>+8.2f}")
        
        # Learning Engine Status
        learning = self.get_learning_engine_status()
        if learning['boosted_tickers'] or learning['penalized_tickers']:
            print("\n" + "─"*80)
            print("LEARNING ENGINE ADAPTATIONS")
            print("─"*80)
            if learning['boosted_tickers']:
                print("  Boosted Tickers (Multiplier > 1.0):")
                for ticker, mult in list(learning['boosted_tickers'].items())[:5]:
                    print(f"    {ticker:>6}: {mult:.3f}x")
            if learning['penalized_tickers']:
                print("  Penalized Tickers (Multiplier < 1.0):")
                for ticker, mult in list(learning['penalized_tickers'].items())[:5]:
                    print(f"    {ticker:>6}: {mult:.3f}x")
        
        print("\n" + "═"*80 + "\n")
    
    def send_discord_summary(self):
        """Send EOD summary to Discord webhook."""
        if not DISCORD_ENABLED:
            print("[DASHBOARD] Discord integration disabled")
            return
        
        try:
            # Get key metrics
            funnel = self.get_signal_funnel()
            by_grade = self.get_performance_by_grade(lookback_days=1)
            
            # Build Discord message
            msg_lines = [
                "📡 **WAR MACHINE - EOD SUMMARY**",
                f"📅 {datetime.now(ET).strftime('%A, %B %d, %Y')}",
                "",
                "**Signal Funnel:**",
                f"Generated: {funnel['generated']} → Validated: {funnel['validated']} → Armed: {funnel['armed']} → Traded: {funnel['traded']}",
                f"Efficiency: {funnel['conversion_rates']['gen_to_traded']:.1f}% (Gen → Traded)",
            ]
            
            # Add grade performance
            if by_grade:
                msg_lines.append("")
                msg_lines.append("**Performance by Grade:**")
                for grade in ['A+', 'A', 'A-']:
                    if grade in by_grade:
                        stats = by_grade[grade]
                        msg_lines.append(
                            f"{grade}: {stats['trades']} trades | {stats['win_rate']:.1f}% WR | ${stats['total_pnl']:+.2f}"
                        )
            
            message = "\n".join(msg_lines)
            send_simple_message(message)
            print("[DASHBOARD] ✅ EOD summary sent to Discord")
        
        except Exception as e:
            print(f"[DASHBOARD] Discord send error: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═════════════════════════════════════════════════════════════════════════════

dashboard = MonitoringDashboard()


# ═════════════════════════════════════════════════════════════════════════════
# CLI USAGE
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "live":
            dashboard.print_live_summary()
        elif command == "eod":
            dashboard.print_eod_report()
        elif command == "discord":
            dashboard.send_discord_summary()
        else:
            print("Usage: python monitoring_dashboard.py [live|eod|discord]")
    else:
        # Default: live summary
        dashboard.print_live_summary()
