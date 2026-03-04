"""
Unusual Options Activity (UOA) Detector - Task 6

Integrates real-time options flow data to detect:
- Whale activity (large institutional orders)
- Dark pool prints
- Unusual sweep activity
- Options volume spikes

Data Sources:
- Unusual Whales API (premium tier recommended)
- EODHD options data (fallback)
- Real-time order flow tracking

Usage:
    from app.data.unusual_options import uoa_detector
    
    # Check for whale activity
    whale_data = uoa_detector.check_whale_activity('AAPL')
    if whale_data['is_unusual']:
        print(f"🐋 Whale detected: {whale_data['summary']}")
"""
import os
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import json

ET = ZoneInfo("America/New_York")

# Unusual Whales API credentials (optional - enhances detection)
UNUSUAL_WHALES_API_KEY = os.getenv("UNUSUAL_WHALES_API_KEY", "")
EODHD_API_KEY = os.getenv("EODHD_API_KEY", "")


class UnusualOptionsDetector:
    """
    Detect unusual options activity for signal enhancement.
    
    Scoring System:
    - Whale Score: 0-10 (based on order size and frequency)
    - Flow Score: 0-10 (based on bullish/bearish flow imbalance)
    - Dark Pool Score: 0-10 (based on dark pool print correlation)
    - Overall UOA Score: Average of above (0-10)
    
    Thresholds:
    - Score >= 7.0: Strong whale activity (boost confidence +10-15%)
    - Score >= 5.0: Moderate activity (boost confidence +5-10%)
    - Score < 5.0: Normal activity (no adjustment)
    """
    
    def __init__(self):
        self.has_unusual_whales = bool(UNUSUAL_WHALES_API_KEY)
        self.has_eodhd = bool(EODHD_API_KEY)
        
        # Cache recent whale activity (15 min TTL)
        self._whale_cache: Dict[str, Dict] = {}
        self._cache_ttl = timedelta(minutes=15)
        
        # Track dark pool activity
        self._dark_pool_cache: Dict[str, List] = defaultdict(list)
        
        print(f"[UOA] Initialized | Unusual Whales: {'✅' if self.has_unusual_whales else '❌'} | "
              f"EODHD: {'✅' if self.has_eodhd else '❌'}")
    
    def check_whale_activity(self, ticker: str, direction: str = 'CALL') -> Dict:
        """
        Check for unusual whale activity on a ticker.
        
        Args:
            ticker: Stock ticker
            direction: 'CALL' or 'PUT'
        
        Returns:
            Dict with whale detection results:
            {
                'is_unusual': bool,
                'whale_score': float (0-10),
                'flow_score': float (0-10),
                'dark_pool_score': float (0-10),
                'overall_score': float (0-10),
                'confidence_boost': float (0.0-0.15),
                'summary': str,
                'details': {...}
            }
        """
        now_et = datetime.now(ET)
        
        # Check cache first
        if ticker in self._whale_cache:
            cached = self._whale_cache[ticker]
            if (now_et - cached['timestamp']) < self._cache_ttl:
                print(f"[UOA] {ticker} cache hit")
                return cached['data']
        
        # Initialize result
        result = {
            'is_unusual': False,
            'whale_score': 0.0,
            'flow_score': 0.0,
            'dark_pool_score': 0.0,
            'overall_score': 0.0,
            'confidence_boost': 0.0,
            'summary': 'No unusual activity detected',
            'details': {}
        }
        
        try:
            # Try Unusual Whales API first (most comprehensive)
            if self.has_unusual_whales:
                whale_data = self._fetch_unusual_whales_data(ticker, direction)
                if whale_data:
                    result = self._analyze_whale_data(whale_data, direction)
            
            # Fallback to EODHD options analysis
            elif self.has_eodhd:
                eodhd_data = self._fetch_eodhd_options(ticker, direction)
                if eodhd_data:
                    result = self._analyze_eodhd_options(eodhd_data, direction)
            
            # Check dark pool correlation
            dark_pool_score = self._check_dark_pool_correlation(ticker, direction)
            result['dark_pool_score'] = dark_pool_score
            
            # Calculate overall score
            result['overall_score'] = (
                result['whale_score'] * 0.5 +
                result['flow_score'] * 0.3 +
                result['dark_pool_score'] * 0.2
            )
            
            # Determine if unusual
            result['is_unusual'] = result['overall_score'] >= 5.0
            
            # Calculate confidence boost
            if result['overall_score'] >= 7.0:
                result['confidence_boost'] = 0.10 + (result['overall_score'] - 7.0) * 0.02  # 10-15%
            elif result['overall_score'] >= 5.0:
                result['confidence_boost'] = 0.05 + (result['overall_score'] - 5.0) * 0.025  # 5-10%
            else:
                result['confidence_boost'] = 0.0
            
            # Generate summary
            if result['is_unusual']:
                activity_level = "Strong" if result['overall_score'] >= 7.0 else "Moderate"
                result['summary'] = (
                    f"{activity_level} whale activity detected "
                    f"(Score: {result['overall_score']:.1f}/10)"
                )
            
            # Cache result
            self._whale_cache[ticker] = {
                'timestamp': now_et,
                'data': result
            }
            
            if result['is_unusual']:
                print(f"[UOA] 🐋 {ticker} | {result['summary']} | "
                      f"Boost: +{result['confidence_boost']*100:.1f}%")
        
        except Exception as e:
            print(f"[UOA] {ticker} error: {e}")
        
        return result
    
    def _fetch_unusual_whales_data(self, ticker: str, direction: str) -> Optional[Dict]:
        """
        Fetch unusual options activity from Unusual Whales API.
        
        API Endpoints:
        - /api/stock/{ticker}/flow - Real-time options flow
        - /api/stock/{ticker}/sweeps - Unusual sweep orders
        - /api/darkpool/{ticker} - Dark pool activity
        """
        if not self.has_unusual_whales:
            return None
        
        try:
            # Fetch options flow (last 4 hours)
            url = f"https://api.unusualwhales.com/api/stock/{ticker}/flow"
            headers = {"Authorization": f"Bearer {UNUSUAL_WHALES_API_KEY}"}
            params = {"hours": 4}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            return data
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                print(f"[UOA] Unusual Whales API: Invalid credentials")
            else:
                print(f"[UOA] Unusual Whales API error: {e}")
            return None
        
        except Exception as e:
            print(f"[UOA] Unusual Whales fetch error: {e}")
            return None
    
    def _fetch_eodhd_options(self, ticker: str, direction: str) -> Optional[Dict]:
        """
        Fetch options data from EODHD as fallback.
        
        Analyzes:
        - Volume vs open interest ratio
        - Bid/ask spread changes
        - Premium flow (calls vs puts)
        """
        if not self.has_eodhd:
            return None
        
        try:
            # Get current options chain
            url = f"https://eodhd.com/api/options/{ticker}.US"
            params = {
                "api_token": EODHD_API_KEY,
                "fmt": "json"
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            return data
        
        except Exception as e:
            print(f"[UOA] EODHD options fetch error: {e}")
            return None
    
    def _analyze_whale_data(self, data: Dict, direction: str) -> Dict:
        """
        Analyze Unusual Whales API data for whale activity.
        
        Scoring:
        - Whale Score: Based on large order frequency and size
        - Flow Score: Based on bullish/bearish flow imbalance
        """
        whale_score = 0.0
        flow_score = 0.0
        details = {}
        
        try:
            flows = data.get('data', [])
            if not flows:
                return {'whale_score': 0.0, 'flow_score': 0.0, 'details': {}}
            
            # Analyze flows
            large_orders = 0
            total_premium = 0.0
            call_premium = 0.0
            put_premium = 0.0
            sweep_count = 0
            
            for flow in flows:
                premium = flow.get('premium', 0)
                is_sweep = flow.get('is_sweep', False)
                option_type = flow.get('type', '').upper()
                
                total_premium += premium
                
                if option_type == 'CALL':
                    call_premium += premium
                elif option_type == 'PUT':
                    put_premium += premium
                
                # Large order detection (>$100k premium)
                if premium > 100000:
                    large_orders += 1
                
                if is_sweep:
                    sweep_count += 1
            
            # Calculate whale score (0-10)
            # Based on: large orders, sweep frequency, total premium
            if large_orders > 0:
                whale_score += min(4.0, large_orders * 1.5)  # Up to 4 pts for large orders
            
            if sweep_count > 0:
                whale_score += min(3.0, sweep_count * 0.5)  # Up to 3 pts for sweeps
            
            if total_premium > 500000:
                whale_score += min(3.0, (total_premium / 500000))  # Up to 3 pts for premium
            
            whale_score = min(10.0, whale_score)
            
            # Calculate flow score (0-10)
            # Based on call/put premium imbalance
            if total_premium > 0:
                if direction == 'CALL':
                    ratio = call_premium / total_premium
                else:
                    ratio = put_premium / total_premium
                
                # Strong directional flow
                if ratio >= 0.75:
                    flow_score = 9.0
                elif ratio >= 0.65:
                    flow_score = 7.0
                elif ratio >= 0.55:
                    flow_score = 5.0
                else:
                    flow_score = 3.0
            
            details = {
                'large_orders': large_orders,
                'sweep_count': sweep_count,
                'total_premium': total_premium,
                'call_premium': call_premium,
                'put_premium': put_premium,
                'flow_ratio': (call_premium / total_premium) if total_premium > 0 else 0.0
            }
        
        except Exception as e:
            print(f"[UOA] Whale data analysis error: {e}")
        
        return {
            'whale_score': whale_score,
            'flow_score': flow_score,
            'details': details
        }
    
    def _analyze_eodhd_options(self, data: Dict, direction: str) -> Dict:
        """
        Analyze EODHD options data for unusual activity.
        
        Simplified scoring without sweep detection.
        """
        whale_score = 0.0
        flow_score = 0.0
        details = {}
        
        try:
            options = data.get('data', [])
            if not options:
                return {'whale_score': 0.0, 'flow_score': 0.0, 'details': {}}
            
            # Filter to near-the-money options (within 5% of current price)
            current_price = data.get('lastTradePrice', 0)
            if not current_price:
                return {'whale_score': 0.0, 'flow_score': 0.0, 'details': {}}
            
            call_volume = 0
            put_volume = 0
            high_vol_count = 0
            
            for opt in options:
                strike = opt.get('strike', 0)
                if abs(strike - current_price) / current_price > 0.05:
                    continue  # Skip far OTM
                
                volume = opt.get('volume', 0)
                open_interest = opt.get('openInterest', 1)
                option_type = opt.get('type', '').upper()
                
                if option_type == 'CALL':
                    call_volume += volume
                elif option_type == 'PUT':
                    put_volume += volume
                
                # High volume relative to OI indicates unusual activity
                vol_oi_ratio = volume / open_interest if open_interest > 0 else 0
                if vol_oi_ratio > 0.5:  # Volume > 50% of OI
                    high_vol_count += 1
            
            # Whale score based on volume/OI anomalies
            if high_vol_count > 0:
                whale_score = min(8.0, high_vol_count * 2.0)
            
            # Flow score based on call/put volume imbalance
            total_volume = call_volume + put_volume
            if total_volume > 0:
                if direction == 'CALL':
                    ratio = call_volume / total_volume
                else:
                    ratio = put_volume / total_volume
                
                if ratio >= 0.70:
                    flow_score = 8.0
                elif ratio >= 0.60:
                    flow_score = 6.0
                else:
                    flow_score = 4.0
            
            details = {
                'call_volume': call_volume,
                'put_volume': put_volume,
                'high_vol_count': high_vol_count,
                'vol_ratio': (call_volume / total_volume) if total_volume > 0 else 0.0
            }
        
        except Exception as e:
            print(f"[UOA] EODHD analysis error: {e}")
        
        return {
            'whale_score': whale_score,
            'flow_score': flow_score,
            'details': details
        }
    
    def _check_dark_pool_correlation(self, ticker: str, direction: str) -> float:
        """
        Check for dark pool print correlation with signal direction.
        
        Returns:
            Dark pool score (0-10)
        """
        # This would require real-time dark pool data feed
        # Placeholder implementation - returns moderate score for now
        
        # In production, integrate with:
        # - Unusual Whales dark pool endpoint
        # - FINRA TRF data
        # - Your existing dark pool tracking system
        
        return 5.0  # Neutral score for now
    
    def get_sweep_alerts(self, ticker: str, lookback_minutes: int = 30) -> List[Dict]:
        """
        Get recent sweep alerts for a ticker.
        
        Args:
            ticker: Stock ticker
            lookback_minutes: How far back to look
        
        Returns:
            List of sweep events with metadata
        """
        if not self.has_unusual_whales:
            return []
        
        try:
            url = f"https://api.unusualwhales.com/api/stock/{ticker}/sweeps"
            headers = {"Authorization": f"Bearer {UNUSUAL_WHALES_API_KEY}"}
            params = {"minutes": lookback_minutes}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            sweeps = data.get('data', [])
            
            return sweeps
        
        except Exception as e:
            print(f"[UOA] Sweep alerts error: {e}")
            return []
    
    def clear_cache(self):
        """Clear whale activity cache."""
        self._whale_cache.clear()
        self._dark_pool_cache.clear()
        print("[UOA] Cache cleared")


# ========================================
# GLOBAL INSTANCE
# ========================================
uoa_detector = UnusualOptionsDetector()


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def check_whale_activity(ticker: str, direction: str = 'CALL') -> Dict:
    """Check for unusual whale activity."""
    return uoa_detector.check_whale_activity(ticker, direction)


def get_sweep_alerts(ticker: str, lookback_minutes: int = 30) -> List[Dict]:
    """Get recent sweep alerts."""
    return uoa_detector.get_sweep_alerts(ticker, lookback_minutes)


if __name__ == "__main__":
    # Test whale detection
    test_tickers = ["AAPL", "TSLA", "NVDA"]
    
    print("\n" + "="*70)
    print("TESTING WHALE DETECTION")
    print("="*70 + "\n")
    
    for ticker in test_tickers:
        result = check_whale_activity(ticker, 'CALL')
        
        print(f"\n{ticker}:")
        print(f"  Unusual: {result['is_unusual']}")
        print(f"  Overall Score: {result['overall_score']:.1f}/10")
        print(f"  Whale Score: {result['whale_score']:.1f}/10")
        print(f"  Flow Score: {result['flow_score']:.1f}/10")
        print(f"  Dark Pool Score: {result['dark_pool_score']:.1f}/10")
        print(f"  Confidence Boost: +{result['confidence_boost']*100:.1f}%")
        print(f"  Summary: {result['summary']}")
