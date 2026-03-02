"""
DTE Historical Advisor - Learn from Past Trade Outcomes

Analyzes historical trade results to recommend optimal DTE based on:
- Time of day patterns (early vs late session performance)
- Market regime context (ADX buckets: choppy vs trending)
- Volatility environment (VIX buckets: low/medium/high)
- Target distance (how far price needs to move)
- Signal grade and direction

The advisor queries the positions database to find similar historical
trades and compares win rates between 0DTE and 1DTE under those conditions.

As the system accumulates more trade data, recommendations become increasingly
data-driven and adaptive to actual performance patterns.

Usage:
    from app.options.dte_historical_advisor import dte_historical_advisor
    
    recommendation = dte_historical_advisor.get_recommendation(
        hour_of_day=14,
        adx=12.5,
        vix=18.3,
        target_pct=0.8,
        grade='A',
        direction='bull'
    )
    
    if recommendation['confidence'] >= 0.6:
        use_dte = recommendation['recommended_dte']
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.data.db_connection import get_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")


class DTEHistoricalAdvisor:
    """Recommends DTE based on historical trade outcomes under similar conditions."""
    
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        
        # Minimum sample size needed for confident recommendation
        self.min_sample_size = 30
        
        # Context bucketing ranges
        self.hour_buckets = [
            (9, 11, 'morning'),      # 9:30-11:00 AM
            (11, 13, 'midday'),      # 11:00 AM-1:00 PM
            (13, 15, 'afternoon'),   # 1:00-3:00 PM
            (15, 16, 'power_hour')   # 3:00-4:00 PM
        ]
        
        self.adx_buckets = [
            (0, 15, 'choppy'),       # Non-trending
            (15, 25, 'trending'),    # Moderate trend
            (25, 100, 'strong_trend') # Strong trend
        ]
        
        self.vix_buckets = [
            (0, 15, 'low_vol'),      # Calm market
            (15, 25, 'normal_vol'),  # Normal volatility
            (25, 100, 'high_vol')    # Elevated fear
        ]
        
        self.target_buckets = [
            (0, 0.5, 'small'),       # <0.5% scalp
            (0.5, 1.0, 'medium'),    # 0.5-1.0% move
            (1.0, 100, 'large')      # >1.0% swing
        ]
        
        print("[DTE-ADVISOR] Historical advisor initialized")
    
    def _bucket_value(self, value: float, buckets: List[Tuple]) -> str:
        """Map continuous value to discrete bucket label."""
        for low, high, label in buckets:
            if low <= value < high:
                return label
        return buckets[-1][2]  # Default to last bucket
    
    def get_recommendation(
        self,
        hour_of_day: int,
        adx: float,
        vix: float,
        target_pct: float,
        grade: str = 'A',
        direction: str = 'bull',
        lookback_days: int = 90
    ) -> Dict:
        """
        Get DTE recommendation based on historical trade outcomes.
        
        Args:
            hour_of_day: Hour in ET (9-16)
            adx: Current ADX value
            vix: Current VIX level
            target_pct: Distance to T1 target as percentage
            grade: Signal grade ('A+', 'A', 'A-')
            direction: 'bull' or 'bear'
            lookback_days: How far back to query historical data
        
        Returns:
            {
                'recommended_dte': int (0 or 1),
                'win_rate_0dte': float,
                'win_rate_1dte': float,
                'sample_size_0dte': int,
                'sample_size_1dte': int,
                'confidence': float (0-1),
                'reasoning': str,
                'buckets_used': dict
            }
        """
        # Bucket the input conditions
        hour_bucket = self._bucket_value(hour_of_day, self.hour_buckets)
        adx_bucket = self._bucket_value(adx, self.adx_buckets)
        vix_bucket = self._bucket_value(vix, self.vix_buckets)
        target_bucket = self._bucket_value(target_pct, self.target_buckets)
        
        buckets = {
            'hour': hour_bucket,
            'adx': adx_bucket,
            'vix': vix_bucket,
            'target': target_bucket,
            'grade': grade,
            'direction': direction
        }
        
        # Query historical trades matching these buckets
        historical_stats = self._query_historical_performance(
            hour_bucket=hour_bucket,
            adx_bucket=adx_bucket,
            vix_bucket=vix_bucket,
            target_bucket=target_bucket,
            grade=grade,
            direction=direction,
            lookback_days=lookback_days
        )
        
        # Calculate recommendation
        return self._calculate_recommendation(historical_stats, buckets)
    
    def _query_historical_performance(
        self,
        hour_bucket: str,
        adx_bucket: str,
        vix_bucket: str,
        target_bucket: str,
        grade: str,
        direction: str,
        lookback_days: int
    ) -> Dict:
        """
        Query positions DB for historical trades matching context buckets.
        
        Returns win rates for 0DTE and 1DTE under these conditions.
        """
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cutoff_date = (datetime.now(ET) - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        
        # Map buckets back to value ranges for SQL query
        hour_ranges = {'morning': (9, 11), 'midday': (11, 13), 'afternoon': (13, 15), 'power_hour': (15, 16)}
        adx_ranges = {'choppy': (0, 15), 'trending': (15, 25), 'strong_trend': (25, 100)}
        vix_ranges = {'low_vol': (0, 15), 'normal_vol': (15, 25), 'high_vol': (25, 100)}
        target_ranges = {'small': (0, 0.5), 'medium': (0.5, 1.0), 'large': (1.0, 100)}
        
        hour_min, hour_max = hour_ranges.get(hour_bucket, (9, 16))
        adx_min, adx_max = adx_ranges.get(adx_bucket, (0, 100))
        vix_min, vix_max = vix_ranges.get(vix_bucket, (0, 100))
        target_min, target_max = target_ranges.get(target_bucket, (0, 100))
        
        # Query for 0DTE trades
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                AVG(pnl) as avg_pnl,
                AVG(CASE WHEN exit_time IS NOT NULL AND entry_time IS NOT NULL 
                    THEN (julianday(exit_time) - julianday(entry_time)) * 24 * 60 
                    ELSE NULL END) as avg_hold_minutes
            FROM positions
            WHERE status = 'CLOSED'
              AND dte_selected = 0
              AND DATE(entry_time) >= {p}
              AND hour_of_day >= {p} AND hour_of_day < {p}
              AND adx_at_entry >= {p} AND adx_at_entry < {p}
              AND vix_at_entry >= {p} AND vix_at_entry < {p}
              AND target_pct_t1 >= {p} AND target_pct_t1 < {p}
              AND grade = {p}
              AND direction = {p}
        """, (
            cutoff_date,
            hour_min, hour_max,
            adx_min, adx_max,
            vix_min, vix_max,
            target_min, target_max,
            grade, direction
        ))
        
        dte_0_stats = cursor.fetchone()
        
        # Query for 1DTE trades
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                AVG(pnl) as avg_pnl,
                AVG(CASE WHEN exit_time IS NOT NULL AND entry_time IS NOT NULL 
                    THEN (julianday(exit_time) - julianday(entry_time)) * 24 * 60 
                    ELSE NULL END) as avg_hold_minutes
            FROM positions
            WHERE status = 'CLOSED'
              AND dte_selected = 1
              AND DATE(entry_time) >= {p}
              AND hour_of_day >= {p} AND hour_of_day < {p}
              AND adx_at_entry >= {p} AND adx_at_entry < {p}
              AND vix_at_entry >= {p} AND vix_at_entry < {p}
              AND target_pct_t1 >= {p} AND target_pct_t1 < {p}
              AND grade = {p}
              AND direction = {p}
        """, (
            cutoff_date,
            hour_min, hour_max,
            adx_min, adx_max,
            vix_min, vix_max,
            target_min, target_max,
            grade, direction
        ))
        
        dte_1_stats = cursor.fetchone()
        
        conn.close()
        
        return {
            'dte_0': {
                'total': dte_0_stats['total'] if dte_0_stats else 0,
                'wins': dte_0_stats['wins'] if dte_0_stats and dte_0_stats['wins'] else 0,
                'avg_pnl': dte_0_stats['avg_pnl'] if dte_0_stats and dte_0_stats['avg_pnl'] else 0,
                'avg_hold_minutes': dte_0_stats['avg_hold_minutes'] if dte_0_stats and dte_0_stats['avg_hold_minutes'] else 0
            },
            'dte_1': {
                'total': dte_1_stats['total'] if dte_1_stats else 0,
                'wins': dte_1_stats['wins'] if dte_1_stats and dte_1_stats['wins'] else 0,
                'avg_pnl': dte_1_stats['avg_pnl'] if dte_1_stats and dte_1_stats['avg_pnl'] else 0,
                'avg_hold_minutes': dte_1_stats['avg_hold_minutes'] if dte_1_stats and dte_1_stats['avg_hold_minutes'] else 0
            }
        }
    
    def _calculate_recommendation(
        self,
        historical_stats: Dict,
        buckets: Dict
    ) -> Dict:
        """
        Calculate DTE recommendation from historical statistics.
        
        Returns recommendation with confidence based on sample size.
        """
        dte_0 = historical_stats['dte_0']
        dte_1 = historical_stats['dte_1']
        
        total_0 = dte_0['total']
        total_1 = dte_1['total']
        total_samples = total_0 + total_1
        
        # Calculate win rates
        win_rate_0 = (dte_0['wins'] / total_0 * 100) if total_0 > 0 else 0
        win_rate_1 = (dte_1['wins'] / total_1 * 100) if total_1 > 0 else 0
        
        # Insufficient data fallback
        if total_samples < self.min_sample_size:
            return {
                'recommended_dte': None,
                'win_rate_0dte': round(win_rate_0, 1),
                'win_rate_1dte': round(win_rate_1, 1),
                'sample_size_0dte': total_0,
                'sample_size_1dte': total_1,
                'confidence': 0.0,
                'reasoning': f"Insufficient historical data ({total_samples} trades, need {self.min_sample_size}). Using live options data only.",
                'buckets_used': buckets
            }
        
        # Calculate confidence based on sample size and win rate difference
        sample_confidence = min(total_samples / (self.min_sample_size * 3), 1.0)  # Max at 90 samples
        win_rate_diff = abs(win_rate_0 - win_rate_1)
        diff_confidence = min(win_rate_diff / 20.0, 1.0)  # Max at 20% difference
        
        overall_confidence = (sample_confidence * 0.6) + (diff_confidence * 0.4)
        
        # Make recommendation
        if win_rate_0 > win_rate_1:
            recommended_dte = 0
            reasoning = f"0DTE historically wins {win_rate_0:.1f}% vs {win_rate_1:.1f}% for 1DTE under these conditions"
        elif win_rate_1 > win_rate_0:
            recommended_dte = 1
            reasoning = f"1DTE historically wins {win_rate_1:.1f}% vs {win_rate_0:.1f}% for 0DTE under these conditions"
        else:
            # Tie - use average P&L as tiebreaker
            if dte_0['avg_pnl'] > dte_1['avg_pnl']:
                recommended_dte = 0
                reasoning = f"Equal win rates, but 0DTE has higher avg P&L (${dte_0['avg_pnl']:.2f} vs ${dte_1['avg_pnl']:.2f})"
            else:
                recommended_dte = 1
                reasoning = f"Equal win rates, but 1DTE has higher avg P&L (${dte_1['avg_pnl']:.2f} vs ${dte_0['avg_pnl']:.2f})"
        
        # Add context to reasoning
        reasoning += f" | Sample: {total_0} (0DTE) + {total_1} (1DTE) trades"
        reasoning += f" | Context: {buckets['hour']}, ADX {buckets['adx']}, VIX {buckets['vix']}, target {buckets['target']}"
        
        return {
            'recommended_dte': recommended_dte,
            'win_rate_0dte': round(win_rate_0, 1),
            'win_rate_1dte': round(win_rate_1, 1),
            'sample_size_0dte': total_0,
            'sample_size_1dte': total_1,
            'confidence': round(overall_confidence, 2),
            'reasoning': reasoning,
            'buckets_used': buckets,
            'avg_hold_minutes_0dte': round(dte_0['avg_hold_minutes'], 1) if dte_0['avg_hold_minutes'] else 0,
            'avg_hold_minutes_1dte': round(dte_1['avg_hold_minutes'], 1) if dte_1['avg_hold_minutes'] else 0
        }
    
    def get_performance_breakdown(self, days: int = 30) -> Dict:
        """
        Get overall DTE performance breakdown for reporting.
        
        Returns summary stats for 0DTE vs 1DTE over last N days.
        """
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime('%Y-%m-%d')
        
        cursor.execute(f"""
            SELECT 
                dte_selected,
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                AVG(pnl) as avg_pnl,
                SUM(pnl) as total_pnl
            FROM positions
            WHERE status = 'CLOSED'
              AND DATE(entry_time) >= {p}
              AND dte_selected IS NOT NULL
            GROUP BY dte_selected
        """, (cutoff,))
        
        rows = cursor.fetchall()
        conn.close()
        
        results = {}
        for row in rows:
            dte = row['dte_selected']
            total = row['total']
            wins = row['wins'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0
            
            results[f'{dte}DTE'] = {
                'total_trades': total,
                'wins': wins,
                'losses': total - wins,
                'win_rate': round(win_rate, 1),
                'avg_pnl': round(row['avg_pnl'], 2) if row['avg_pnl'] else 0,
                'total_pnl': round(row['total_pnl'], 2) if row['total_pnl'] else 0
            }
        
        return results


# ========================================
# GLOBAL INSTANCE
# ========================================
try:
    dte_historical_advisor = DTEHistoricalAdvisor()
except Exception as e:
    print(f"[DTE-ADVISOR] ⚠️  Initialization failed: {e}")
    dte_historical_advisor = None


# ========================================
# CONVENIENCE FUNCTION
# ========================================
def get_historical_recommendation(
    hour_of_day: int,
    adx: float,
    vix: float,
    target_pct: float,
    grade: str = 'A',
    direction: str = 'bull'
) -> Optional[Dict]:
    """Convenience function to get DTE recommendation."""
    if dte_historical_advisor is None:
        return None
    
    return dte_historical_advisor.get_recommendation(
        hour_of_day=hour_of_day,
        adx=adx,
        vix=vix,
        target_pct=target_pct,
        grade=grade,
        direction=direction
    )
