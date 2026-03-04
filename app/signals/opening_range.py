"""
Opening Range (OR) Detection - Task 7

Responsibilities:
  - Classify Opening Range (9:30-9:40) as TIGHT, NORMAL, or WIDE
  - Alert at 9:38 for tight OR forming (expansion breakout likely)
  - Raise confidence threshold for wide OR (consolidation filter)
  - Provide dynamic scan frequency recommendations
  - Boost confidence for tight OR breakouts

Classification:
  - TIGHT: < 0.5 ATR (expansion likely, scan aggressively)
  - NORMAL: 0.5-1.5 ATR (standard behavior)
  - WIDE: > 1.5 ATR (consolidation likely, require higher confidence)

Impact: Capture 9:30-9:40 early moves, filter choppy wide ORs
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import numpy as np

from app.data.data_manager import data_manager

ET = ZoneInfo("America/New_York")


class OpeningRangeDetector:
    """
    Detect and classify Opening Range for intraday trading.
    
    OR Window: 9:30-9:40 AM ET (10 minutes)
    
    Classification Logic:
      - Calculate ATR(14) from prior day
      - Measure OR range (high - low)
      - Compare OR range to ATR
      - Classify as TIGHT/NORMAL/WIDE
    
    Trading Rules:
      - TIGHT OR: Scan every 30s at 9:40+, +5% confidence boost
      - NORMAL OR: Scan every 45s (standard), normal thresholds
      - WIDE OR: Scan every 45s, raise threshold to 75%
    """
    
    def __init__(self):
        """Initialize OR detector."""
        # OR window parameters
        self.or_start_time = time(9, 30)  # 9:30 AM ET
        self.or_end_time = time(9, 40)    # 9:40 AM ET
        self.or_alert_time = time(9, 38)  # Alert time for tight OR forming
        
        # Classification thresholds (ATR multipliers)
        self.tight_threshold = 0.5   # < 0.5 ATR = TIGHT
        self.wide_threshold = 1.5    # > 1.5 ATR = WIDE
        
        # Confidence adjustments
        self.tight_or_boost = 0.05        # +5% for tight OR breakouts
        self.wide_or_min_confidence = 0.75  # 75% minimum for wide OR
        
        # Scan frequency recommendations (seconds)
        self.scan_freq_tight = 30    # Aggressive
        self.scan_freq_normal = 45   # Standard
        self.scan_freq_wide = 45     # Same as normal, but higher threshold
        
        # Session cache
        self.or_cache: Dict[str, Dict] = {}  # ticker -> OR data
        self.alerts_sent: Dict[str, bool] = {}  # ticker -> alert sent flag
        
        print("[OR] Opening Range Detector initialized")
        print(f"[OR] Window: 9:30-9:40 AM ET (10 minutes)")
        print(f"[OR] Thresholds: TIGHT<{self.tight_threshold} ATR, WIDE>{self.wide_threshold} ATR")
        print(f"[OR] Scan frequencies: Tight={self.scan_freq_tight}s, Normal={self.scan_freq_normal}s")
    
    def classify_or(self, ticker: str, current_time: Optional[datetime] = None) -> Optional[Dict]:
        """
        Classify Opening Range for a ticker.
        
        Args:
            ticker: Stock ticker
            current_time: Current time (defaults to now)
        
        Returns:
            OR classification dict or None if OR not complete
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        # Check if OR window has passed
        if not self._is_or_complete(current_time):
            return None
        
        # Check cache first
        if ticker in self.or_cache:
            return self.or_cache[ticker]
        
        # Get today's bars for OR calculation
        bars_1m = data_manager.get_today_session_bars(ticker)
        
        if not bars_1m or len(bars_1m) < 10:
            print(f"[OR] {ticker} - Insufficient data for OR calculation")
            return None
        
        # Extract OR bars (9:30-9:40)
        or_bars = self._extract_or_bars(bars_1m)
        
        if not or_bars:
            print(f"[OR] {ticker} - No OR bars found")
            return None
        
        # Calculate OR range
        or_high = max(b['high'] for b in or_bars)
        or_low = min(b['low'] for b in or_bars)
        or_range = or_high - or_low
        or_range_pct = (or_range / or_low) * 100 if or_low > 0 else 0
        
        # Calculate ATR(14) from prior day for comparison
        atr = self._calculate_atr(ticker)
        
        if atr is None or atr == 0:
            print(f"[OR] {ticker} - Could not calculate ATR")
            return None
        
        # Classify OR based on ATR ratio
        or_range_atr = or_range / atr
        
        if or_range_atr < self.tight_threshold:
            classification = 'TIGHT'
            scan_frequency = self.scan_freq_tight
            confidence_adjustment = self.tight_or_boost
            min_confidence = 0.60  # Standard threshold
        elif or_range_atr > self.wide_threshold:
            classification = 'WIDE'
            scan_frequency = self.scan_freq_wide
            confidence_adjustment = 0.0  # No boost
            min_confidence = self.wide_or_min_confidence  # Raised to 75%
        else:
            classification = 'NORMAL'
            scan_frequency = self.scan_freq_normal
            confidence_adjustment = 0.0
            min_confidence = 0.60  # Standard threshold
        
        # Build result
        result = {
            'ticker': ticker,
            'or_high': round(or_high, 2),
            'or_low': round(or_low, 2),
            'or_range': round(or_range, 2),
            'or_range_pct': round(or_range_pct, 2),
            'or_range_atr': round(or_range_atr, 2),
            'atr': round(atr, 2),
            'classification': classification,
            'scan_frequency': scan_frequency,
            'confidence_adjustment': confidence_adjustment,
            'min_confidence': min_confidence,
            'timestamp': current_time.isoformat()
        }
        
        # Cache result
        self.or_cache[ticker] = result
        
        # Log classification
        emoji = "🎯" if classification == 'TIGHT' else "⚠️" if classification == 'WIDE' else "✅"
        print(f"[OR] {ticker} {emoji} {classification} | Range: ${or_range:.2f} ({or_range_pct:.2f}%) | ATR Ratio: {or_range_atr:.2f}x")
        
        if classification == 'TIGHT':
            print(f"[OR]   🚀 Expansion breakout likely - Scanning every {scan_frequency}s")
            print(f"[OR]   📈 Confidence boost: +{confidence_adjustment*100:.0f}%")
        elif classification == 'WIDE':
            print(f"[OR]   ⏳ Consolidation likely - Min confidence raised to {min_confidence*100:.0f}%")
        
        return result
    
    def should_alert_or_forming(self, ticker: str, current_time: Optional[datetime] = None) -> bool:
        """
        Check if we should send 'OR forming' alert (at 9:38 AM for tight OR).
        
        Args:
            ticker: Stock ticker
            current_time: Current time (defaults to now)
        
        Returns:
            True if alert should be sent
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        # Only alert at 9:38 AM
        if current_time.time() < self.or_alert_time:
            return False
        
        # Only alert once per ticker per session
        if ticker in self.alerts_sent:
            return False
        
        # Check if OR is forming and looks TIGHT
        bars_1m = data_manager.get_today_session_bars(ticker)
        
        if not bars_1m or len(bars_1m) < 8:
            return False
        
        # Get bars from 9:30-9:38 (8 minutes)
        or_bars_so_far = self._extract_or_bars(bars_1m, end_time=time(9, 38))
        
        if not or_bars_so_far or len(or_bars_so_far) < 8:
            return False
        
        # Calculate partial OR range
        or_high = max(b['high'] for b in or_bars_so_far)
        or_low = min(b['low'] for b in or_bars_so_far)
        or_range = or_high - or_low
        
        # Get ATR for comparison
        atr = self._calculate_atr(ticker)
        
        if atr is None or atr == 0:
            return False
        
        # Check if forming TIGHT OR
        or_range_atr = or_range / atr
        
        if or_range_atr < self.tight_threshold:
            # Mark alert as sent
            self.alerts_sent[ticker] = True
            return True
        
        return False
    
    def should_scan_now(self, ticker: str, current_time: Optional[datetime] = None) -> bool:
        """
        Determine if we should scan this ticker now based on OR classification.
        
        Args:
            ticker: Stock ticker
            current_time: Current time (defaults to now)
        
        Returns:
            True if should scan
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        # Before OR complete, use normal scanning
        if not self._is_or_complete(current_time):
            return True
        
        # Get OR classification
        or_data = self.classify_or(ticker, current_time)
        
        if or_data is None:
            return True  # Fallback to scanning if no OR data
        
        # For now, always return True (scan frequency handled by scanner loop)
        # The scan frequency recommendation is used by the main scanner
        return True
    
    def adjust_signal_confidence(self, signal: Dict, current_time: Optional[datetime] = None) -> Dict:
        """
        Adjust signal confidence based on OR classification.
        
        Args:
            signal: Signal dict with 'ticker' and 'confidence'
            current_time: Current time (defaults to now)
        
        Returns:
            Updated signal dict with OR adjustments
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        ticker = signal['ticker']
        
        # Get OR classification
        or_data = self.classify_or(ticker, current_time)
        
        if or_data is None:
            return signal  # No OR data, return unchanged
        
        # Apply confidence adjustment
        original_confidence = signal.get('confidence', 0)
        confidence_adjustment = or_data['confidence_adjustment']
        
        # Adjust confidence
        if confidence_adjustment > 0:
            # Boost for tight OR
            signal['confidence'] = min(100, original_confidence + (confidence_adjustment * 100))
            signal['or_boost'] = confidence_adjustment
        
        # Check minimum confidence threshold for wide OR
        if or_data['classification'] == 'WIDE':
            min_confidence = or_data['min_confidence'] * 100
            if signal['confidence'] < min_confidence:
                signal['or_filtered'] = True
                signal['or_filter_reason'] = f"Wide OR requires {min_confidence:.0f}% confidence"
        
        # Add OR data to signal
        signal['or'] = or_data
        
        return signal
    
    def get_scan_frequency(self, ticker: str, current_time: Optional[datetime] = None) -> int:
        """
        Get recommended scan frequency for a ticker based on OR.
        
        Args:
            ticker: Stock ticker
            current_time: Current time (defaults to now)
        
        Returns:
            Scan frequency in seconds
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        # Before OR complete, use normal frequency
        if not self._is_or_complete(current_time):
            return self.scan_freq_normal
        
        # Get OR classification
        or_data = self.classify_or(ticker, current_time)
        
        if or_data is None:
            return self.scan_freq_normal
        
        return or_data['scan_frequency']
    
    def _is_or_complete(self, current_time: datetime) -> bool:
        """
        Check if OR window (9:30-9:40) has completed.
        
        Args:
            current_time: Current time
        
        Returns:
            True if OR window has passed
        """
        return current_time.time() >= self.or_end_time
    
    def _extract_or_bars(self, bars_1m: List[Dict], end_time: Optional[time] = None) -> List[Dict]:
        """
        Extract bars within OR window (9:30-9:40).
        
        Args:
            bars_1m: List of 1-minute bars
            end_time: Optional end time (defaults to 9:40)
        
        Returns:
            List of bars within OR window
        """
        if end_time is None:
            end_time = self.or_end_time
        
        or_bars = []
        
        for bar in bars_1m:
            bar_time = datetime.fromisoformat(bar['timestamp']).astimezone(ET).time()
            
            if self.or_start_time <= bar_time < end_time:
                or_bars.append(bar)
        
        return or_bars
    
    def _calculate_atr(self, ticker: str, period: int = 14) -> Optional[float]:
        """
        Calculate ATR(14) for a ticker from prior day data.
        
        Args:
            ticker: Stock ticker
            period: ATR period (default 14)
        
        Returns:
            ATR value or None if insufficient data
        """
        # Get recent bars (need at least 'period' bars)
        bars_1m = data_manager.get_today_session_bars(ticker)
        
        if not bars_1m or len(bars_1m) < period:
            # Try to get yesterday's bars if today's insufficient
            # For now, use a simple estimation from available bars
            if not bars_1m or len(bars_1m) < 5:
                return None
        
        # Calculate True Range for each bar
        true_ranges = []
        
        for i in range(1, min(len(bars_1m), period + 1)):
            high = bars_1m[i]['high']
            low = bars_1m[i]['low']
            prev_close = bars_1m[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            
            true_ranges.append(tr)
        
        if not true_ranges:
            return None
        
        # ATR is simple average of true ranges
        atr = np.mean(true_ranges)
        
        return atr
    
    def clear_cache(self) -> None:
        """Clear OR cache (called at market open for new session)."""
        or_count = len(self.or_cache)
        alert_count = len(self.alerts_sent)
        
        self.or_cache.clear()
        self.alerts_sent.clear()
        
        print(f"[OR] Session cache cleared ({or_count} OR entries, {alert_count} alerts reset)")
    
    def get_or_summary(self, tickers: List[str], current_time: Optional[datetime] = None) -> str:
        """
        Generate summary of OR classifications for watchlist.
        
        Args:
            tickers: List of tickers
            current_time: Current time (defaults to now)
        
        Returns:
            Formatted summary string
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        if not self._is_or_complete(current_time):
            return "⏳ Opening Range (9:30-9:40) still forming..."
        
        summary = "📊 Opening Range Summary:\n\n"
        
        tight_tickers = []
        wide_tickers = []
        normal_tickers = []
        
        for ticker in tickers:
            or_data = self.classify_or(ticker, current_time)
            
            if or_data is None:
                continue
            
            if or_data['classification'] == 'TIGHT':
                tight_tickers.append(f"{ticker} ({or_data['or_range_atr']:.2f}x ATR)")
            elif or_data['classification'] == 'WIDE':
                wide_tickers.append(f"{ticker} ({or_data['or_range_atr']:.2f}x ATR)")
            else:
                normal_tickers.append(f"{ticker} ({or_data['or_range_atr']:.2f}x ATR)")
        
        if tight_tickers:
            summary += f"🎯 **TIGHT OR** (expansion likely):\n"
            for t in tight_tickers:
                summary += f"  • {t}\n"
            summary += "\n"
        
        if normal_tickers:
            summary += f"✅ **NORMAL OR**:\n"
            for t in normal_tickers:
                summary += f"  • {t}\n"
            summary += "\n"
        
        if wide_tickers:
            summary += f"⚠️ **WIDE OR** (consolidation likely):\n"
            for t in wide_tickers:
                summary += f"  • {t}\n"
            summary += "\n"
        
        return summary.strip()


# ========================================
# GLOBAL INSTANCE
# ========================================
or_detector = OpeningRangeDetector()


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def classify_or(ticker: str) -> Optional[Dict]:
    """Classify Opening Range for a ticker."""
    return or_detector.classify_or(ticker)


def should_alert_or_forming(ticker: str) -> bool:
    """Check if OR forming alert should be sent (9:38 AM for tight OR)."""
    return or_detector.should_alert_or_forming(ticker)


def adjust_signal_for_or(signal: Dict) -> Dict:
    """Adjust signal confidence based on OR classification."""
    return or_detector.adjust_signal_confidence(signal)


def get_scan_frequency(ticker: str) -> int:
    """Get recommended scan frequency based on OR."""
    return or_detector.get_scan_frequency(ticker)


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    # Example: Classify OR
    test_ticker = "SPY"
    
    print(f"Testing OR detection for {test_ticker}...\n")
    
    or_data = classify_or(test_ticker)
    
    if or_data:
        print(f"\nOR Classification:")
        print(f"  Ticker: {or_data['ticker']}")
        print(f"  Range: ${or_data['or_range']} ({or_data['or_range_pct']}%)")
        print(f"  ATR: ${or_data['atr']}")
        print(f"  ATR Ratio: {or_data['or_range_atr']}x")
        print(f"  Classification: {or_data['classification']}")
        print(f"  Scan Frequency: {or_data['scan_frequency']}s")
        print(f"  Confidence Adjustment: +{or_data['confidence_adjustment']*100:.0f}%")
        print(f"  Min Confidence: {or_data['min_confidence']*100:.0f}%")
    else:
        print("OR not yet complete or insufficient data")
