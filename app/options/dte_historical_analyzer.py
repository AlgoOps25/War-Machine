"""
Historical DTE Analyzer - EODHD-Based Market Pattern Analysis

Builds DTE recommendation engine from historical intraday price movements.
This is the PRIMARY data source for intelligent DTE selection.

Core Logic:
  - Fetch 90 days of 1-minute SPY bars from EODHD
  - For each bar, simulate entry and measure time-to-target
  - Bucket by context: hour_of_day, ADX regime, VIX level
  - Calculate realistic hold time distributions
  - Recommend 0DTE if P(target within 60min) > 70%, else 1DTE

Context Bucketing:
  Hour: 'OPEN' (9:30-10:30), 'MID' (10:30-14:00), 'LATE' (14:00-16:00)
  ADX: 'TRENDING' (>25), 'MODERATE' (15-25), 'CHOPPY' (<15)
  VIX: 'HIGH' (>25), 'ELEVATED' (20-25), 'NORMAL' (15-20), 'LOW' (<15)

Output:
  For given context + target_pct, returns:
  {
    'recommended_dte': 0 or 1,
    'confidence': 0-100,
    'avg_hold_time_min': float,
    'p50_hold_time_min': float (median),
    'p75_hold_time_min': float,
    'success_rate_60min': float (% reaching target in <60 min),
    'sample_size': int,
    'reasoning': str
  }
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import statistics
import requests
import os
from app.data.db_connection import get_conn, ph, dict_cursor, serial_pk

ET = ZoneInfo("America/New_York")


class DTEHistoricalAnalyzer:
    """Analyzes historical market data to recommend optimal DTE."""
    
    def __init__(self, eodhd_api_key: Optional[str] = None, db_path: str = "market_memory.db"):
        self.api_key = eodhd_api_key or os.getenv('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError("EODHD_API_KEY required for historical analysis")
        
        self.db_path = db_path
        self._initialize_database()
        
        # Check if historical analysis exists
        if not self._has_historical_data():
            print("[DTE-HISTORICAL] No historical analysis found. Run build_historical_database() first.")
        
        print("[DTE-HISTORICAL] Analyzer initialized")
    
    def _initialize_database(self):
        """Create historical move analysis table."""
        conn = get_conn(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS dte_historical_moves (
                id {serial_pk()},
                date TEXT NOT NULL,
                entry_time TIME NOT NULL,
                hour_bucket TEXT NOT NULL,
                adx_bucket TEXT NOT NULL,
                vix_bucket TEXT NOT NULL,
                entry_price REAL NOT NULL,
                target_pct REAL NOT NULL,
                target_price REAL NOT NULL,
                hit_target INTEGER NOT NULL,
                time_to_target_min INTEGER,
                bars_to_target INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dte_hist_context
            ON dte_historical_moves(hour_bucket, adx_bucket, vix_bucket, target_pct)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dte_hist_date
            ON dte_historical_moves(date)
        """)
        
        conn.commit()
        conn.close()
    
    def _has_historical_data(self) -> bool:
        """Check if historical analysis exists in DB."""
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute("SELECT COUNT(*) as count FROM dte_historical_moves")
        row = cursor.fetchone()
        conn.close()
        
        return row['count'] > 1000  # Need at least 1000 samples
    
    def build_historical_database(
        self,
        ticker: str = "SPY",
        lookback_days: int = 90,
        target_pcts: List[float] = [0.5, 0.75, 1.0]
    ):
        """
        Fetch historical 1-minute bars and analyze time-to-target patterns.
        
        This is a ONE-TIME initialization process. Run once, then query results.
        
        Args:
            ticker: Ticker to analyze (default SPY for broad market proxy)
            lookback_days: Days of history to analyze
            target_pcts: Target percentage moves to track
        """
        print(f"[DTE-HISTORICAL] Building historical database for {ticker}...")
        print(f"[DTE-HISTORICAL] Lookback: {lookback_days} days, Targets: {target_pcts}")
        
        end_date = datetime.now(ET).date()
        start_date = end_date - timedelta(days=lookback_days)
        
        # Fetch 1-min bars from EODHD
        print(f"[DTE-HISTORICAL] Fetching 1-min data from {start_date} to {end_date}...")
        bars = self._fetch_intraday_bars(ticker, start_date, end_date)
        
        if not bars:
            print("[DTE-HISTORICAL] ERROR: No data returned from EODHD")
            return
        
        print(f"[DTE-HISTORICAL] Analyzing {len(bars)} bars...")
        
        # Group bars by date
        bars_by_date = {}
        for bar in bars:
            date_str = bar['datetime'][:10]
            if date_str not in bars_by_date:
                bars_by_date[date_str] = []
            bars_by_date[date_str].append(bar)
        
        # Analyze each date
        total_moves = 0
        conn = get_conn(self.db_path)
        cursor = conn.cursor()
        
        for date_str in sorted(bars_by_date.keys()):
            day_bars = sorted(bars_by_date[date_str], key=lambda x: x['datetime'])
            
            # Calculate ADX and VIX proxies for the day (simplified)
            adx_proxy = self._calculate_adx_proxy(day_bars)
            vix_proxy = self._calculate_vix_proxy(day_bars)
            
            adx_bucket = self._bucket_adx(adx_proxy)
            vix_bucket = self._bucket_vix(vix_proxy)
            
            # Simulate entry at every bar during RTH
            for i, bar in enumerate(day_bars):
                bar_time = datetime.fromisoformat(bar['datetime']).time()
                
                # Only analyze RTH (9:30-15:30 to allow time to reach targets)
                if bar_time < dtime(9, 30) or bar_time >= dtime(15, 30):
                    continue
                
                hour_bucket = self._bucket_hour(bar_time)
                entry_price = bar['close']
                
                # Check each target
                for target_pct in target_pcts:
                    target_price = entry_price * (1 + target_pct / 100)
                    
                    # Look forward to see if/when target hit
                    hit_target = 0
                    time_to_target_min = None
                    bars_to_target = None
                    
                    for j in range(i + 1, min(i + 120, len(day_bars))):  # Max 120 bars = 2 hours
                        future_bar = day_bars[j]
                        if future_bar['high'] >= target_price:
                            hit_target = 1
                            bars_to_target = j - i
                            time_to_target_min = bars_to_target  # 1-min bars
                            break
                    
                    # Insert record
                    p = ph()
                    cursor.execute(f"""
                        INSERT INTO dte_historical_moves
                            (date, entry_time, hour_bucket, adx_bucket, vix_bucket,
                             entry_price, target_pct, target_price,
                             hit_target, time_to_target_min, bars_to_target)
                        VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                    """, (
                        date_str,
                        bar_time.strftime('%H:%M:%S'),
                        hour_bucket,
                        adx_bucket,
                        vix_bucket,
                        entry_price,
                        target_pct,
                        target_price,
                        hit_target,
                        time_to_target_min,
                        bars_to_target
                    ))
                    
                    total_moves += 1
            
            if total_moves % 1000 == 0:
                print(f"[DTE-HISTORICAL] Processed {total_moves} potential moves...")
                conn.commit()
        
        conn.commit()
        conn.close()
        
        print(f"[DTE-HISTORICAL] ✅ Analysis complete! {total_moves} moves catalogued.")
        print(f"[DTE-HISTORICAL] Ready for intelligent DTE recommendations.")
    
    def get_dte_recommendation(
        self,
        hour_of_day: int,
        adx: float,
        vix: float,
        target_pct: float,
        time_remaining_hours: float
    ) -> Dict:
        """
        Get DTE recommendation based on historical move patterns.
        
        Args:
            hour_of_day: Current hour (0-23)
            adx: Current ADX value
            vix: Current VIX value
            target_pct: Target profit percentage (e.g., 1.0 for 1%)
            time_remaining_hours: Hours until market close
        
        Returns:
            Dict with recommendation and supporting data
        """
        # Bucket inputs
        bar_time = dtime(hour_of_day, 0)
        hour_bucket = self._bucket_hour(bar_time)
        adx_bucket = self._bucket_adx(adx)
        vix_bucket = self._bucket_vix(vix)
        
        # Find closest target_pct in database
        available_targets = [0.5, 0.75, 1.0]
        closest_target = min(available_targets, key=lambda x: abs(x - target_pct))
        
        # Query historical moves matching this context
        p = ph()
        conn = get_conn(self.db_path)
        cursor = dict_cursor(conn)
        
        cursor.execute(f"""
            SELECT
                hit_target,
                time_to_target_min
            FROM dte_historical_moves
            WHERE hour_bucket = {p}
              AND adx_bucket = {p}
              AND vix_bucket = {p}
              AND target_pct = {p}
              AND hit_target = 1
        """, (hour_bucket, adx_bucket, vix_bucket, closest_target))
        
        successful_moves = cursor.fetchall()
        conn.close()
        
        if len(successful_moves) < 30:
            # Insufficient data - fall back to time-only logic with confidence penalty
            return self._fallback_recommendation(time_remaining_hours, len(successful_moves))
        
        # Analyze time distributions
        hold_times = [m['time_to_target_min'] for m in successful_moves]
        avg_hold = statistics.mean(hold_times)
        median_hold = statistics.median(hold_times)
        p75_hold = statistics.quantiles(hold_times, n=4)[2]  # 75th percentile
        
        # Calculate success rate within 60 minutes
        within_60min = sum(1 for t in hold_times if t <= 60)
        success_rate_60min = (within_60min / len(hold_times)) * 100
        
        # DTE Decision Logic
        time_remaining_min = time_remaining_hours * 60
        
        # 0DTE viable if:
        # 1. >70% of moves complete within 60 min, AND
        # 2. Median hold time + 15min buffer < time remaining
        if success_rate_60min >= 70 and (median_hold + 15) < time_remaining_min:
            recommended_dte = 0
            confidence = min(95, 60 + (success_rate_60min - 70) * 1.5)
            reasoning = (
                f"0DTE viable: {success_rate_60min:.0f}% of historical moves "
                f"completed in <60min. Median hold: {median_hold:.0f}min. "
                f"Time remaining: {time_remaining_min:.0f}min."
            )
        else:
            recommended_dte = 1
            confidence = min(95, 60 + (100 - success_rate_60min) * 0.5)
            reasoning = (
                f"1DTE recommended: Only {success_rate_60min:.0f}% of moves "
                f"completed in <60min. Median hold: {median_hold:.0f}min. "
                f"Need buffer for {target_pct:.2f}% target in {hour_bucket}/{adx_bucket}/{vix_bucket} regime."
            )
        
        return {
            'recommended_dte': recommended_dte,
            'confidence': round(confidence, 1),
            'avg_hold_time_min': round(avg_hold, 1),
            'p50_hold_time_min': round(median_hold, 1),
            'p75_hold_time_min': round(p75_hold, 1),
            'success_rate_60min': round(success_rate_60min, 1),
            'sample_size': len(successful_moves),
            'context': f"{hour_bucket}/{adx_bucket}/{vix_bucket}",
            'reasoning': reasoning
        }
    
    def _fallback_recommendation(self, time_remaining_hours: float, sample_size: int) -> Dict:
        """Fallback logic when insufficient historical data."""
        if time_remaining_hours >= 3.5:
            dte = 0
            reasoning = f"0DTE (time-based fallback - {time_remaining_hours:.1f}hrs remaining)"
        elif time_remaining_hours >= 1.0:
            dte = 1
            reasoning = f"1DTE (time-based fallback - {time_remaining_hours:.1f}hrs remaining)"
        else:
            dte = None
            reasoning = "SKIP - too close to market close"
        
        return {
            'recommended_dte': dte,
            'confidence': 40.0,  # Low confidence fallback
            'avg_hold_time_min': None,
            'p50_hold_time_min': None,
            'p75_hold_time_min': None,
            'success_rate_60min': None,
            'sample_size': sample_size,
            'context': 'INSUFFICIENT_DATA',
            'reasoning': f"⚠️ {reasoning} (only {sample_size} historical samples)"
        }
    
    def _fetch_intraday_bars(self, ticker: str, start_date, end_date) -> List[Dict]:
        """Fetch 1-minute intraday bars from EODHD."""
        url = f"https://eodhd.com/api/intraday/{ticker}.US"
        
        params = {
            'api_token': self.api_key,
            'interval': '1m',
            'from': int(start_date.strftime('%s')),
            'to': int(end_date.strftime('%s')),
            'fmt': 'json'
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"[DTE-HISTORICAL] EODHD fetch error: {e}")
            return []
    
    def _calculate_adx_proxy(self, bars: List[Dict]) -> float:
        """Calculate ADX proxy from daily bar volatility."""
        if len(bars) < 14:
            return 15.0  # Default moderate
        
        # Simple proxy: avg true range as % of close
        ranges = []
        for bar in bars[-14:]:
            true_range = bar['high'] - bar['low']
            ranges.append(true_range / bar['close'] * 100)
        
        avg_range = statistics.mean(ranges)
        
        # Map to ADX scale (rough approximation)
        if avg_range > 0.8:
            return 30.0  # High volatility = trending
        elif avg_range > 0.4:
            return 20.0  # Moderate
        else:
            return 10.0  # Low volatility = choppy
    
    def _calculate_vix_proxy(self, bars: List[Dict]) -> float:
        """Calculate VIX proxy from intraday volatility."""
        if len(bars) < 20:
            return 18.0  # Default normal
        
        # Calculate intraday standard deviation
        closes = [bar['close'] for bar in bars]
        returns = [(closes[i] / closes[i-1] - 1) * 100 for i in range(1, len(closes))]
        
        if len(returns) < 2:
            return 18.0
        
        std_dev = statistics.stdev(returns)
        
        # Annualize and scale to VIX-like range
        vix_proxy = std_dev * (252 ** 0.5) * 15  # Rough scaling
        
        return max(10, min(50, vix_proxy))  # Clamp 10-50
    
    def _bucket_hour(self, bar_time: dtime) -> str:
        """Bucket hour into trading session segment."""
        if bar_time < dtime(10, 30):
            return 'OPEN'  # Opening range volatility
        elif bar_time < dtime(14, 0):
            return 'MID'   # Midday grind
        else:
            return 'LATE'  # Power hour / close
    
    def _bucket_adx(self, adx: float) -> str:
        """Bucket ADX into regime categories."""
        if adx >= 25:
            return 'TRENDING'
        elif adx >= 15:
            return 'MODERATE'
        else:
            return 'CHOPPY'
    
    def _bucket_vix(self, vix: float) -> str:
        """Bucket VIX into volatility regimes."""
        if vix >= 25:
            return 'HIGH'
        elif vix >= 20:
            return 'ELEVATED'
        elif vix >= 15:
            return 'NORMAL'
        else:
            return 'LOW'


# ========================================
# GLOBAL INSTANCE
# ========================================
try:
    dte_historical_analyzer = DTEHistoricalAnalyzer()
except ValueError as e:
    print(f"[DTE-HISTORICAL] ⚠️ Initialization failed: {e}")
    dte_historical_analyzer = None


# ========================================
# CONVENIENCE FUNCTION
# ========================================
def get_historical_dte_recommendation(
    hour_of_day: int,
    adx: float,
    vix: float,
    target_pct: float,
    time_remaining_hours: float
) -> Optional[Dict]:
    """Convenience function for getting DTE recommendation."""
    if dte_historical_analyzer is None:
        return None
    
    return dte_historical_analyzer.get_dte_recommendation(
        hour_of_day=hour_of_day,
        adx=adx,
        vix=vix,
        target_pct=target_pct,
        time_remaining_hours=time_remaining_hours
    )
