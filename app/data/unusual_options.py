"""
Unusual Options Activity (UOA) Detector - Task 6

Responsibilities:
  - Detect unusual whale activity (large options orders)
  - Track dark pool prints and block trades
  - Identify multi-exchange sweeps (aggressive buyers/sellers)
  - Correlate options flow with breakout signals
  - Boost signal confidence when institutional activity detected

Data Sources:
  - Unusual Whales API (premium whale detection)
  - EODHD Options Data (volume, OI, Greeks)
  - Dark Pool data feeds (if available)

Impact: Front-run institutional money, higher win rate on whale-confirmed signals
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

ET = ZoneInfo("America/New_York")


class UnusualOptionsDetector:
    """
    Detect unusual options activity and whale trades.
    
    Scoring System (0-10):
      - Whale Score: Large single orders (>$100K premium)
      - Flow Score: Directional bias (call/put ratio)
      - Sweep Score: Multi-exchange aggression
      - Dark Pool Score: Block trade activity
      - Overall Score: Weighted combination
    
    Confidence Boost:
      - Score 8-10: +10% confidence boost
      - Score 6-8: +5% confidence boost
      - Score 4-6: +2% confidence boost
      - Score <4: No boost (not unusual)
    """
    
    def __init__(self):
        """Initialize UOA detector with API keys and cache."""
        self.eodhd_api_key = os.getenv('EODHD_API_KEY', '')
        self.unusual_whales_key = os.getenv('UNUSUAL_WHALES_API_KEY', '')
        
        # 5-minute cache to avoid API spam
        self.cache: Dict[str, Dict] = {}  # ticker -> {data, timestamp}
        self.cache_ttl = 300  # 5 minutes
        
        # Thresholds for unusual activity
        self.min_premium_whale = 100000  # $100K minimum for whale classification
        self.min_volume_ratio = 3.0  # 3x average volume
        self.min_oi_ratio = 2.0  # 2x open interest
        self.min_sweep_legs = 3  # Minimum exchanges for sweep detection
        
        print("[UOA] Unusual Options Detector initialized")
        print(f"[UOA] Whale threshold: ${self.min_premium_whale:,}")
        print(f"[UOA] Cache TTL: {self.cache_ttl}s")
    
    def check_whale_activity(self, ticker: str, direction: str = 'CALL') -> Dict:
        """
        Check for unusual whale activity on a ticker.
        
        Args:
            ticker: Stock ticker
            direction: 'CALL' or 'PUT' (matches signal direction)
        
        Returns:
            Dict with whale detection results and confidence boost
        """
        # Check cache first
        if self._is_cached(ticker):
            cached = self.cache[ticker]['data']
            print(f"[UOA] {ticker} - Using cached whale data")
            return cached
        
        # Detect whale activity from multiple sources
        whale_score = self._detect_large_orders(ticker, direction)
        flow_score = self._analyze_options_flow(ticker, direction)
        sweep_score = self._detect_sweeps(ticker, direction)
        dark_pool_score = self._check_dark_pool_activity(ticker)
        
        # Calculate overall score (weighted)
        overall_score = (
            whale_score * 0.35 +      # Large orders most important
            flow_score * 0.25 +        # Directional flow
            sweep_score * 0.25 +       # Multi-exchange aggression
            dark_pool_score * 0.15     # Block trades
        )
        
        # Determine if unusual (threshold: 4.0/10)
        is_unusual = overall_score >= 4.0
        
        # Calculate confidence boost
        if overall_score >= 8.0:
            confidence_boost = 0.10  # +10%
        elif overall_score >= 6.0:
            confidence_boost = 0.05  # +5%
        elif overall_score >= 4.0:
            confidence_boost = 0.02  # +2%
        else:
            confidence_boost = 0.0  # No boost
        
        # Build result
        result = {
            'ticker': ticker,
            'direction': direction,
            'is_unusual': is_unusual,
            'overall_score': round(overall_score, 1),
            'whale_score': round(whale_score, 1),
            'flow_score': round(flow_score, 1),
            'sweep_score': round(sweep_score, 1),
            'dark_pool_score': round(dark_pool_score, 1),
            'confidence_boost': confidence_boost,
            'summary': self._generate_summary(overall_score, whale_score, flow_score, sweep_score),
            'timestamp': datetime.now(ET).isoformat()
        }
        
        # Cache result
        self._cache_result(ticker, result)
        
        # Log significant activity
        if is_unusual:
            print(f"[UOA] {ticker} 🐋 UNUSUAL ACTIVITY DETECTED | \")
            print(f\"      Overall: {overall_score:.1f}/10 | \"\n                  f\"Whale: {whale_score:.1f} | Flow: {flow_score:.1f} | \"\n                  f\"Sweep: {sweep_score:.1f} | Dark Pool: {dark_pool_score:.1f}")
            print(f"[UOA]   Confidence Boost: +{confidence_boost*100:.0f}%")
        
        return result
    
    def _detect_large_orders(self, ticker: str, direction: str) -> float:
        """
        Detect large whale orders (single trades >$100K premium).
        
        Args:
            ticker: Stock ticker
            direction: 'CALL' or 'PUT'
        
        Returns:
            Score 0-10 (0 = no whales, 10 = massive whale activity)
        """
        # TODO: Integrate Unusual Whales API
        # For now, use EODHD options data as proxy
        
        try:
            # Simulate whale detection logic
            # In production, this would call:
            # - Unusual Whales API for real-time whale alerts
            # - EODHD options chain for volume/premium analysis
            
            # Placeholder scoring logic
            # Real implementation would analyze:
            # 1. Single orders with premium > $100K
            # 2. Block trades (100+ contracts in one order)
            # 3. Institutional order flow patterns
            
            # For MVP, return moderate score to show integration
            score = 0.0
            
            # Check for volume spikes (proxy for whale activity)
            # Real API integration would replace this
            
            print(f"[UOA] {ticker} whale detection: {score:.1f}/10")
            return score
        
        except Exception as e:
            print(f"[UOA] {ticker} whale detection error: {e}")
            return 0.0
    
    def _analyze_options_flow(self, ticker: str, direction: str) -> float:
        """
        Analyze options flow for directional bias.
        
        Looks at:
          - Call/Put volume ratio
          - Call/Put OI ratio
          - Bid vs Ask volume (aggressive buyers vs sellers)
        
        Args:
            ticker: Stock ticker
            direction: 'CALL' or 'PUT' (expected direction)
        
        Returns:
            Score 0-10 (10 = strong flow in signal direction)
        """
        try:
            # TODO: Integrate EODHD options chain API
            # Calculate call/put ratios and directional flow
            
            # Placeholder logic
            # Real implementation would analyze:
            # 1. Total call volume vs put volume
            # 2. At-the-money strikes (most liquid)
            # 3. Bid vs ask volume (aggression indicator)
            
            score = 0.0
            
            print(f"[UOA] {ticker} flow analysis: {score:.1f}/10")
            return score
        
        except Exception as e:
            print(f"[UOA] {ticker} flow analysis error: {e}")
            return 0.0
    
    def _detect_sweeps(self, ticker: str, direction: str) -> float:
        """
        Detect multi-exchange option sweeps.
        
        A sweep is an aggressive order that hits multiple exchanges
        simultaneously, indicating urgency and conviction.
        
        Args:
            ticker: Stock ticker
            direction: 'CALL' or 'PUT'
        
        Returns:
            Score 0-10 (10 = aggressive multi-exchange sweep detected)
        """
        try:
            # TODO: Integrate sweep detection API
            # Real-time options data with exchange flags required
            
            # Placeholder logic
            # Real implementation would detect:
            # 1. Orders hitting 3+ exchanges simultaneously
            # 2. Above-ask buys or below-bid sells (aggressive)
            # 3. Large size relative to open interest
            
            score = 0.0
            
            print(f"[UOA] {ticker} sweep detection: {score:.1f}/10")
            return score
        
        except Exception as e:
            print(f"[UOA] {ticker} sweep detection error: {e}")
            return 0.0
    
    def _check_dark_pool_activity(self, ticker: str) -> float:
        """
        Check for dark pool prints and block trades.
        
        Dark pool activity indicates institutional positioning.
        Large block trades often precede major moves.
        
        Args:
            ticker: Stock ticker
        
        Returns:
            Score 0-10 (10 = significant dark pool activity)
        """
        try:
            # TODO: Integrate dark pool data feed
            # Options: Trade Algo, Quiver Quant, or paid feeds
            
            # Placeholder logic
            # Real implementation would analyze:
            # 1. Block trades (10K+ shares)
            # 2. Dark pool volume as % of total volume
            # 3. Timing (recent blocks more relevant)
            
            score = 0.0
            
            print(f"[UOA] {ticker} dark pool activity: {score:.1f}/10")
            return score
        
        except Exception as e:
            print(f"[UOA] {ticker} dark pool check error: {e}")
            return 0.0
    
    def _generate_summary(self, overall: float, whale: float, flow: float, sweep: float) -> str:
        """
        Generate human-readable summary of UOA detection.
        
        Args:
            overall: Overall score
            whale: Whale score
            flow: Flow score
            sweep: Sweep score
        
        Returns:
            Summary string for Discord alerts
        """
        if overall >= 8.0:
            return "🔥 EXTREME whale activity - Strong institutional conviction"
        elif overall >= 6.0:
            if whale >= 7.0:
                return "🐋 Large whale orders detected - Follow the smart money"
            elif sweep >= 7.0:
                return "⚡ Aggressive multi-exchange sweeps - High urgency"
            else:
                return "📊 Significant options flow - Institutional interest"
        elif overall >= 4.0:
            return "✅ Moderate unusual activity - Positive confirmation"
        else:
            return "No unusual activity detected"
    
    def _is_cached(self, ticker: str) -> bool:
        """Check if ticker data is in cache and still valid."""
        if ticker not in self.cache:
            return False
        
        cached_time = datetime.fromisoformat(self.cache[ticker]['data']['timestamp'])
        age_seconds = (datetime.now(ET) - cached_time).total_seconds()
        
        return age_seconds < self.cache_ttl
    
    def _cache_result(self, ticker: str, result: Dict) -> None:
        """Cache whale detection result."""
        self.cache[ticker] = {
            'data': result,
            'timestamp': datetime.now(ET)
        }
    
    def clear_cache(self) -> None:
        """Clear UOA cache (called at EOD reset)."""
        count = len(self.cache)
        self.cache.clear()
        print(f"[UOA] Cache cleared ({count} entries removed)")
    
    def get_whale_alerts(self, tickers: List[str], min_score: float = 6.0) -> List[Dict]:
        """
        Scan multiple tickers for whale activity.
        
        Args:
            tickers: List of tickers to scan
            min_score: Minimum overall score to include
        
        Returns:
            List of tickers with significant whale activity
        """
        alerts = []
        
        for ticker in tickers:
            try:
                # Check both calls and puts
                call_data = self.check_whale_activity(ticker, 'CALL')
                put_data = self.check_whale_activity(ticker, 'PUT')
                
                # Add to alerts if above threshold
                if call_data['overall_score'] >= min_score:
                    alerts.append(call_data)
                
                if put_data['overall_score'] >= min_score:
                    alerts.append(put_data)
            
            except Exception as e:
                print(f"[UOA] Error scanning {ticker}: {e}")
                continue
        
        # Sort by overall score (highest first)
        alerts.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return alerts
    
    def format_whale_alert(self, alert: Dict) -> str:
        """
        Format whale alert for Discord.
        
        Args:
            alert: Whale detection result
        
        Returns:
            Formatted Discord message
        """
        ticker = alert['ticker']
        direction = alert['direction']
        score = alert['overall_score']
        summary = alert['summary']
        
        msg = f"🐋 **WHALE ALERT: {ticker}** 🐋\n\n"
        msg += f"**Direction:** {direction}s\n"
        msg += f"**Overall Score:** {score}/10\n\n"
        
        msg += f"**Breakdown:**\n"
        msg += f"  🐋 Whale Orders: {alert['whale_score']}/10\n"
        msg += f"  📊 Options Flow: {alert['flow_score']}/10\n"
        msg += f"  ⚡ Sweeps: {alert['sweep_score']}/10\n"
        msg += f"  🌑 Dark Pool: {alert['dark_pool_score']}/10\n\n"
        
        msg += f"**Analysis:** {summary}\n"
        msg += f"**Confidence Boost:** +{alert['confidence_boost']*100:.0f}%"
        
        return msg


# ========================================
# GLOBAL INSTANCE
# ========================================
uoa_detector = UnusualOptionsDetector()


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def check_whale_activity(ticker: str, direction: str = 'CALL') -> Dict:
    """Check for whale activity on a ticker."""
    return uoa_detector.check_whale_activity(ticker, direction)


def scan_for_whales(watchlist: List[str], min_score: float = 6.0) -> List[Dict]:
    """Scan watchlist for whale activity."""
    return uoa_detector.get_whale_alerts(watchlist, min_score)


def format_whale_alert(alert: Dict) -> str:
    """Format whale alert for Discord."""
    return uoa_detector.format_whale_alert(alert)


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    # Example: Check whale activity
    test_ticker = "AAPL"
    
    print(f"Checking whale activity for {test_ticker}...\n")
    
    call_activity = check_whale_activity(test_ticker, 'CALL')
    print(f"\nCALL Activity:")
    print(f"  Unusual: {call_activity['is_unusual']}")
    print(f"  Score: {call_activity['overall_score']}/10")
    print(f"  Boost: +{call_activity['confidence_boost']*100:.0f}%")
    print(f"  Summary: {call_activity['summary']}")
    
    # Example: Scan watchlist
    print("\n" + "="*70)
    print("Scanning watchlist for whale activity...\n")
    
    test_watchlist = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]
    whale_alerts = scan_for_whales(test_watchlist, min_score=5.0)
    
    if whale_alerts:
        print(f"Found {len(whale_alerts)} whale alerts:\n")
        for alert in whale_alerts:
            print(format_whale_alert(alert))
            print("-" * 70)
    else:
        print("No significant whale activity detected")
