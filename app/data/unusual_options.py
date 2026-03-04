"""
Unusual Options Activity (UOA) Detector

Responsibilities:
  - Real-time whale/institutional options flow monitoring
  - Dark pool print correlation
  - Unusual sweep activity detection
  - Premium tracking (big money moves)
  - Integration with signal validation

Data Sources:
  - Unusual Whales API (premium data)
  - EODHD options chain (volume/OI)
  - Internal trade flow tracking
"""

import os
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import time

ET = ZoneInfo("America/New_York")

# API Configuration
UW_API_KEY = os.getenv("UNUSUAL_WHALES_API_KEY", "")
UW_BASE_URL = "https://api.unusualwhales.com/api"

# UOA Detection Thresholds
MIN_PREMIUM = 50000  # $50k minimum premium to be considered "whale"
MIN_VOLUME_OI_RATIO = 2.0  # Volume/OI ratio for unusual activity
DARK_POOL_MIN_SIZE = 100000  # $100k minimum for dark pool print
SWEEP_MIN_LEGS = 3  # Minimum legs to be considered a sweep


class UnusualOptionsDetector:
    """Detect unusual options activity for signal validation."""
    
    def __init__(self):
        self.enabled = bool(UW_API_KEY)
        self.cache = {}  # ticker -> {timestamp, data}
        self.cache_ttl = 60  # Cache TTL in seconds
        
        # Track recent UOA for correlation
        self.recent_uoa: Dict[str, List[Dict]] = defaultdict(list)  # ticker -> [uoa_events]
        self.recent_dark_pool: Dict[str, List[Dict]] = defaultdict(list)
        
        if self.enabled:
            print("[UOA] ✅ Unusual Options Activity detector enabled (Unusual Whales API)")
        else:
            print("[UOA] ⚠️  Disabled - No Unusual Whales API key found")
    
    # ========================================
    # MAIN PUBLIC INTERFACE
    # ========================================
    
    def check_unusual_activity(self, ticker: str, direction: str = "CALL") -> Dict:
        """
        Check for unusual options activity on ticker.
        
        Args:
            ticker: Stock ticker
            direction: "CALL" or "PUT"
        
        Returns:
            Dict with UOA analysis:
            {
                'has_whale_activity': bool,
                'has_dark_pool': bool,
                'has_sweep': bool,
                'confidence_boost': float,  # 0.0 to 0.15 (up to +15%)
                'details': {...}
            }
        """
        if not self.enabled:
            return self._empty_result()
        
        # Check cache first
        if self._is_cached(ticker):
            return self.cache[ticker]['data']
        
        result = {
            'has_whale_activity': False,
            'has_dark_pool': False,
            'has_sweep': False,
            'confidence_boost': 0.0,
            'details': {}
        }
        
        try:
            # 1. Check for whale flow
            whale_data = self._fetch_whale_flow(ticker)
            if whale_data:
                result['has_whale_activity'] = True
                result['details']['whale'] = whale_data
            
            # 2. Check for dark pool prints
            dark_pool_data = self._fetch_dark_pool_prints(ticker)
            if dark_pool_data:
                result['has_dark_pool'] = True
                result['details']['dark_pool'] = dark_pool_data
            
            # 3. Check for options sweeps
            sweep_data = self._fetch_options_sweeps(ticker, direction)
            if sweep_data:
                result['has_sweep'] = True
                result['details']['sweep'] = sweep_data
            
            # 4. Calculate confidence boost
            result['confidence_boost'] = self._calculate_confidence_boost(result)
            
            # Cache result
            self._cache_result(ticker, result)
            
            # Log significant activity
            if result['confidence_boost'] > 0:
                self._log_activity(ticker, result)
        
        except Exception as e:
            print(f"[UOA] Error checking {ticker}: {e}")
            return self._empty_result()
        
        return result
    
    def get_recent_flow_summary(self, ticker: str, lookback_minutes: int = 30) -> Dict:
        """
        Get summary of recent options flow for ticker.
        
        Args:
            ticker: Stock ticker
            lookback_minutes: How far back to look
        
        Returns:
            Summary dict with aggregated flow data
        """
        if not self.enabled:
            return {}
        
        cutoff = datetime.now(ET) - timedelta(minutes=lookback_minutes)
        
        # Filter recent UOA events
        recent_events = [
            event for event in self.recent_uoa[ticker]
            if event['timestamp'] >= cutoff
        ]
        
        if not recent_events:
            return {'total_events': 0}
        
        # Aggregate stats
        total_premium = sum(e.get('premium', 0) for e in recent_events)
        call_premium = sum(e.get('premium', 0) for e in recent_events if e.get('type') == 'CALL')
        put_premium = sum(e.get('premium', 0) for e in recent_events if e.get('type') == 'PUT')
        
        return {
            'total_events': len(recent_events),
            'total_premium': total_premium,
            'call_premium': call_premium,
            'put_premium': put_premium,
            'call_put_ratio': call_premium / put_premium if put_premium > 0 else float('inf'),
            'bullish': call_premium > put_premium,
            'lookback_minutes': lookback_minutes
        }
    
    # ========================================
    # UNUSUAL WHALES API CALLS
    # ========================================
    
    def _fetch_whale_flow(self, ticker: str) -> Optional[Dict]:
        """
        Fetch whale-sized options trades from Unusual Whales.
        
        Returns:
            Dict with whale flow data or None
        """
        try:
            url = f"{UW_BASE_URL}/stock/{ticker}/flow"
            headers = {"Authorization": f"Bearer {UW_API_KEY}"}
            params = {"date": datetime.now(ET).strftime("%Y-%m-%d")}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Filter for whale-sized trades (>$50k premium)
                whale_trades = [
                    trade for trade in data.get('data', [])
                    if trade.get('premium', 0) >= MIN_PREMIUM
                ]
                
                if whale_trades:
                    # Get most recent whale trade
                    latest = sorted(whale_trades, key=lambda x: x['timestamp'], reverse=True)[0]
                    
                    return {
                        'count': len(whale_trades),
                        'total_premium': sum(t['premium'] for t in whale_trades),
                        'latest_trade': {
                            'premium': latest['premium'],
                            'type': latest['call_put'],
                            'strike': latest['strike'],
                            'expiry': latest['expiry'],
                            'sentiment': latest.get('sentiment', 'neutral')
                        }
                    }
            
            return None
        
        except Exception as e:
            print(f"[UOA] Whale flow fetch error for {ticker}: {e}")
            return None
    
    def _fetch_dark_pool_prints(self, ticker: str) -> Optional[Dict]:
        """
        Fetch dark pool print data from Unusual Whales.
        
        Returns:
            Dict with dark pool data or None
        """
        try:
            url = f"{UW_BASE_URL}/darkpool/{ticker}"
            headers = {"Authorization": f"Bearer {UW_API_KEY}"}
            params = {"date": datetime.now(ET).strftime("%Y-%m-%d")}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Filter for large prints (>$100k)
                large_prints = [
                    print_data for print_data in data.get('data', [])
                    if print_data.get('size_usd', 0) >= DARK_POOL_MIN_SIZE
                ]
                
                if large_prints:
                    total_volume = sum(p['size'] for p in large_prints)
                    total_value = sum(p['size_usd'] for p in large_prints)
                    
                    return {
                        'count': len(large_prints),
                        'total_volume': total_volume,
                        'total_value': total_value,
                        'average_price': total_value / total_volume if total_volume > 0 else 0,
                        'bullish_percentage': self._calculate_bullish_pct(large_prints)
                    }
            
            return None
        
        except Exception as e:
            print(f"[UOA] Dark pool fetch error for {ticker}: {e}")
            return None
    
    def _fetch_options_sweeps(self, ticker: str, direction: str) -> Optional[Dict]:
        """
        Fetch options sweep data (multi-leg aggressive fills).
        
        Args:
            ticker: Stock ticker
            direction: "CALL" or "PUT"
        
        Returns:
            Dict with sweep data or None
        """
        try:
            url = f"{UW_BASE_URL}/stock/{ticker}/sweeps"
            headers = {"Authorization": f"Bearer {UW_API_KEY}"}
            params = {"date": datetime.now(ET).strftime("%Y-%m-%d")}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Filter for direction match
                sweeps = [
                    sweep for sweep in data.get('data', [])
                    if sweep.get('call_put', '').upper() == direction.upper()
                    and sweep.get('legs', 0) >= SWEEP_MIN_LEGS
                ]
                
                if sweeps:
                    # Get most recent sweep
                    latest = sorted(sweeps, key=lambda x: x['timestamp'], reverse=True)[0]
                    
                    return {
                        'count': len(sweeps),
                        'total_premium': sum(s.get('premium', 0) for s in sweeps),
                        'latest_sweep': {
                            'premium': latest['premium'],
                            'legs': latest['legs'],
                            'strike': latest['strike'],
                            'sentiment': latest.get('sentiment', 'bullish' if direction == 'CALL' else 'bearish')
                        }
                    }
            
            return None
        
        except Exception as e:
            print(f"[UOA] Sweep fetch error for {ticker}: {e}")
            return None
    
    # ========================================
    # CONFIDENCE CALCULATION
    # ========================================
    
    def _calculate_confidence_boost(self, result: Dict) -> float:
        """
        Calculate confidence boost based on UOA signals.
        
        Returns:
            Boost amount: 0.0 to 0.15 (0% to +15%)
        """
        boost = 0.0
        
        # Whale activity: +5%
        if result['has_whale_activity']:
            whale_data = result['details'].get('whale', {})
            if whale_data.get('total_premium', 0) > 500000:  # >$500k
                boost += 0.08
            elif whale_data.get('total_premium', 0) > 200000:  # >$200k
                boost += 0.05
            else:
                boost += 0.03
        
        # Dark pool activity: +3%
        if result['has_dark_pool']:
            dp_data = result['details'].get('dark_pool', {})
            bullish_pct = dp_data.get('bullish_percentage', 50)
            if bullish_pct > 65:  # Strong bullish bias
                boost += 0.05
            elif bullish_pct > 55:
                boost += 0.03
            else:
                boost += 0.02
        
        # Options sweeps: +4%
        if result['has_sweep']:
            sweep_data = result['details'].get('sweep', {})
            if sweep_data.get('total_premium', 0) > 300000:  # >$300k
                boost += 0.06
            elif sweep_data.get('total_premium', 0) > 100000:  # >$100k
                boost += 0.04
            else:
                boost += 0.02
        
        # Cap at +15%
        return min(boost, 0.15)
    
    def _calculate_bullish_pct(self, prints: List[Dict]) -> float:
        """
        Calculate bullish percentage from dark pool prints.
        Uses price momentum and volume weighting.
        """
        if not prints:
            return 50.0
        
        # Simplified: count prints at ask (bullish) vs bid (bearish)
        bullish = sum(1 for p in prints if p.get('side', '').lower() == 'ask')
        total = len(prints)
        
        return (bullish / total * 100) if total > 0 else 50.0
    
    # ========================================
    # CACHING & LOGGING
    # ========================================
    
    def _is_cached(self, ticker: str) -> bool:
        """Check if ticker result is cached and fresh."""
        if ticker not in self.cache:
            return False
        
        age = (datetime.now(ET) - self.cache[ticker]['timestamp']).total_seconds()
        return age < self.cache_ttl
    
    def _cache_result(self, ticker: str, result: Dict):
        """Cache UOA result for ticker."""
        self.cache[ticker] = {
            'timestamp': datetime.now(ET),
            'data': result
        }
        
        # Store in recent activity for correlation
        if result['confidence_boost'] > 0:
            event = {
                'timestamp': datetime.now(ET),
                'premium': result['details'].get('whale', {}).get('total_premium', 0),
                'type': result['details'].get('whale', {}).get('latest_trade', {}).get('type', 'UNKNOWN'),
                'has_sweep': result['has_sweep'],
                'has_dark_pool': result['has_dark_pool']
            }
            self.recent_uoa[ticker].append(event)
            
            # Trim old events (keep last 100)
            if len(self.recent_uoa[ticker]) > 100:
                self.recent_uoa[ticker] = self.recent_uoa[ticker][-100:]
    
    def _log_activity(self, ticker: str, result: Dict):
        """Log significant UOA activity."""
        boost_pct = result['confidence_boost'] * 100
        
        indicators = []
        if result['has_whale_activity']:
            whale = result['details']['whale']
            indicators.append(f"🐋 Whale: ${whale['total_premium']:,.0f}")
        
        if result['has_dark_pool']:
            dp = result['details']['dark_pool']
            indicators.append(f"🌑 Dark Pool: ${dp['total_value']:,.0f}")
        
        if result['has_sweep']:
            sweep = result['details']['sweep']
            indicators.append(f"🧹 Sweep: ${sweep['total_premium']:,.0f}")
        
        print(f"[UOA] {ticker} 📈 Confidence boost: +{boost_pct:.1f}% | {' | '.join(indicators)}")
    
    def _empty_result(self) -> Dict:
        """Return empty result when UOA disabled or error."""
        return {
            'has_whale_activity': False,
            'has_dark_pool': False,
            'has_sweep': False,
            'confidence_boost': 0.0,
            'details': {}
        }
    
    # ========================================
    # UTILITY METHODS
    # ========================================
    
    def clear_cache(self):
        """Clear all cached UOA data."""
        self.cache.clear()
        print("[UOA] Cache cleared")
    
    def clear_recent_activity(self, ticker: Optional[str] = None):
        """Clear recent activity tracking."""
        if ticker:
            self.recent_uoa[ticker].clear()
            self.recent_dark_pool[ticker].clear()
        else:
            self.recent_uoa.clear()
            self.recent_dark_pool.clear()
        print(f"[UOA] Recent activity cleared{' for ' + ticker if ticker else ''}")


# ========================================
# GLOBAL INSTANCE
# ========================================
uoa_detector = UnusualOptionsDetector()


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def check_uoa(ticker: str, direction: str = "CALL") -> Dict:
    """Convenience function to check UOA."""
    return uoa_detector.check_unusual_activity(ticker, direction)


def get_flow_summary(ticker: str, lookback_minutes: int = 30) -> Dict:
    """Get recent flow summary for ticker."""
    return uoa_detector.get_recent_flow_summary(ticker, lookback_minutes)
