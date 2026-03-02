"""
DTE Historical Advisor - Learn optimal DTE from trade outcomes

Queries positions database to recommend DTE based on historical win rates
under similar market conditions (hour, ADX, VIX, target distance).
"""
from typing import Dict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.data.db_connection import get_conn, ph, dict_cursor

ET = ZoneInfo("America/New_York")

class DTEHistoricalAdvisor:
    def __init__(self, db_path: str = "market_memory.db"):
        self.db_path = db_path
        self.min_sample_size = 30
        self.adx_buckets = [(0, 15, "CHOPPY"), (15, 25, "TRENDING"), (25, 100, "STRONG")]
        self.vix_buckets = [(0, 15, "LOW"), (15, 25, "NORMAL"), (25, 35, "ELEVATED"), (35, 100, "HIGH")]
        self.target_buckets = [(0.0, 0.5, "TIGHT"), (0.5, 0.8, "SMALL"), (0.8, 1.2, "MEDIUM"), (1.2, 100, "LARGE")]
        self.hour_buckets = [(9, 10, "OPEN"), (10, 12, "MORNING"), (12, 14, "MIDDAY"), (14, 16, "AFTERNOON")]
        print("[DTE-ADVISOR] Initialized")
    
    def _bucket(self, val: float, buckets: list) -> str:
        for low, high, label in buckets:
            if low <= val < high:
                return label
        return "UNKNOWN"
    
    def get_recommendation(self, hour_of_day: int, adx: float, vix: float, target_pct: float,
                          direction: str = None, grade: str = None, lookback_days: int = 90) -> Dict:
        """Get DTE recommendation based on historical win rates in similar context."""
        hour_bucket = self._bucket(hour_of_day, self.hour_buckets)
        adx_bucket = self._bucket(adx, self.adx_buckets)
        vix_bucket = self._bucket(vix, self.vix_buckets)
        target_bucket = self._bucket(target_pct, self.target_buckets)
        context = f"{hour_bucket}_{adx_bucket}_{vix_bucket}_{target_bucket}"
        
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        cutoff = (datetime.now(ET) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        
        where = ["status = 'CLOSED'", f"DATE(exit_time) >= {p}", "dte_selected IS NOT NULL", 
                 "adx_at_entry IS NOT NULL", "vix_at_entry IS NOT NULL", "target_pct_t1 IS NOT NULL"]
        params = [cutoff]
        if direction:
            where.append(f"direction = {p}")
            params.append(direction)
        if grade:
            where.append(f"grade = {p}")
            params.append(grade)
        
        query = f"SELECT dte_selected, pnl, adx_at_entry, vix_at_entry, target_pct_t1, CAST(strftime('%H', entry_time) AS INTEGER) as hr FROM positions WHERE {' AND '.join(where)}"
        cursor.execute(query, tuple(params))
        trades = cursor.fetchall()
        conn.close()
        
        if not trades:
            return {'has_preference': False, 'reason': 'No historical trades', 'context': context, 'confidence': 0.0}
        
        # Filter to matching context bucket
        matching = [t for t in trades if 
                   self._bucket(t['hr'], self.hour_buckets) == hour_bucket and
                   self._bucket(t['adx_at_entry'], self.adx_buckets) == adx_bucket and
                   self._bucket(t['vix_at_entry'], self.vix_buckets) == vix_bucket and
                   self._bucket(t['target_pct_t1'], self.target_buckets) == target_bucket]
        
        if len(matching) < self.min_sample_size:
            return {'has_preference': False, 'reason': f'Insufficient data ({len(matching)}/{self.min_sample_size})', 
                    'context': context, 'confidence': 0.0}
        
        dte0 = [t for t in matching if t['dte_selected'] == 0]
        dte1 = [t for t in matching if t['dte_selected'] == 1]
        if not dte0 or not dte1:
            return {'has_preference': False, 'reason': 'Missing DTE comparison', 'context': context, 'confidence': 0.0}
        
        wr0 = sum(1 for t in dte0 if t['pnl'] > 0) / len(dte0) * 100
        wr1 = sum(1 for t in dte1 if t['pnl'] > 0) / len(dte1) * 100
        
        if abs(wr0 - wr1) < 5.0:
            return {'has_preference': False, 'reason': f'Win rates too close ({wr0:.1f}% vs {wr1:.1f}%)', 
                    'context': context, 'confidence': 0.0}
        
        rec = 0 if wr0 > wr1 else 1
        conf = min(100, (len(matching) / self.min_sample_size) * 75 + min(25, abs(wr0 - wr1)))
        
        return {
            'has_preference': True, 
            'recommended_dte': rec, 
            'win_rate_0dte': round(wr0, 1),
            'win_rate_1dte': round(wr1, 1), 
            'sample_size': len(matching), 
            'confidence': round(conf, 1), 
            'context': context,
            'reason': f"{rec}DTE wins {max(wr0,wr1):.1f}% in {context} (n={len(matching)})"
        }

try:
    dte_advisor = DTEHistoricalAdvisor()
except Exception as e:
    print(f"[DTE-ADVISOR] Init failed: {e}")
    dte_advisor = None
