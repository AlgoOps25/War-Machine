"""
Daily Bias Engine - ICT Top-Down Analysis

Implements Inner Circle Trader's pre-market bias methodology:
  1. Mark pivot highs/lows on 1-hour chart (previous session)
  2. Identify liquidity sweeps that signal directional intent
  3. Set BULL or BEAR bias for current session
  4. Filter counter-trend signals throughout the day

Bias Determination Logic:
  - BULLISH: Price sweeps previous day's low (PDL) and reclaims structure
  - BEARISH: Price sweeps previous day's high (PDH) and breaks structure
  - NEUTRAL: No clear sweep or conflicting signals

Pivot Detection:
  - Pivot High: Bar higher than N bars on left and right
  - Pivot Low: Bar lower than N bars on left and right
  - Standard: N=2 (5-bar pattern: 2 left, center, 2 right)

Liquidity Sweep:
  - Price briefly exceeds pivot level (3-5 ticks)
  - Followed by rapid rejection (close back inside range)
  - Confirms liquidity grab before directional move
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import json

from data_manager import data_manager

ET = ZoneInfo("America/New_York")


class DailyBiasEngine:
    """ICT-style daily bias determination from higher timeframe analysis."""
    
    def __init__(self,
                 pivot_lookback: int = 2,
                 sweep_tolerance_pct: float = 0.15,
                 min_rejection_pct: float = 0.3):
        """
        Args:
            pivot_lookback: Bars to left/right for pivot confirmation (default: 2)
            sweep_tolerance_pct: % beyond pivot to qualify as sweep (default: 0.15%)
            min_rejection_pct: Minimum % rejection to confirm sweep (default: 0.3%)
        """
        self.pivot_lookback = pivot_lookback
        self.sweep_tolerance_pct = sweep_tolerance_pct / 100.0
        self.min_rejection_pct = min_rejection_pct / 100.0
        
        # Daily bias cache
        self.current_bias: Optional[str] = None  # 'BULL', 'BEAR', 'NEUTRAL'
        self.bias_timestamp: Optional[datetime] = None
        self.bias_confidence: float = 0.0  # 0.0-1.0
        self.bias_reasons: List[str] = []
        
        # Pivot cache (reset daily)
        self.yesterday_pivots: Dict[str, List[Dict]] = {}  # ticker -> [pivot dicts]
        self.key_levels: Dict[str, Dict] = {}  # ticker -> {PDH, PDL, session_high, session_low}
        
        print("[BIAS] Daily Bias Engine initialized")
        print(f"[BIAS] Pivot lookback: {pivot_lookback} bars")
        print(f"[BIAS] Sweep tolerance: {sweep_tolerance_pct*100:.2f}%")
        print(f"[BIAS] Min rejection: {min_rejection_pct*100:.2f}%")
    
    def calculate_daily_bias(self, ticker: str, force_refresh: bool = False) -> Dict:
        """
        Calculate daily bias for ticker using ICT top-down analysis.
        
        Process:
          1. Get yesterday's 1H bars
          2. Mark pivot highs/lows
          3. Get today's pre-market bars
          4. Check for liquidity sweeps (PDH/PDL)
          5. Determine bias direction and confidence
        
        Args:
            ticker: Stock ticker to analyze
            force_refresh: Force recalculation even if cached
        
        Returns:
            Dict with bias, confidence, reasons, and key levels
        """
        now = datetime.now(ET)
        
        # Return cached bias if still valid (same session)
        if not force_refresh and self.current_bias and self.bias_timestamp:
            if self.bias_timestamp.date() == now.date():
                return self._get_bias_dict()
        
        # Step 1: Get yesterday's 1H bars for pivot analysis
        yesterday = now - timedelta(days=1)
        yesterday_bars = self._get_hourly_bars(ticker, yesterday)
        
        if not yesterday_bars or len(yesterday_bars) < 5:
            print(f"[BIAS] {ticker}: Insufficient historical data for bias calculation")
            return self._set_neutral_bias("Insufficient data")
        
        # Step 2: Mark pivot highs/lows on 1H chart
        pivots = self._find_pivots(yesterday_bars)
        self.yesterday_pivots[ticker] = pivots
        
        if not pivots:
            print(f"[BIAS] {ticker}: No pivots found in previous session")
            return self._set_neutral_bias("No pivots detected")
        
        # Step 3: Extract key levels (PDH, PDL)
        pdh = max(bar['high'] for bar in yesterday_bars)
        pdl = min(bar['low'] for bar in yesterday_bars)
        
        self.key_levels[ticker] = {
            'PDH': pdh,
            'PDL': pdl,
            'pivots': pivots
        }
        
        print(f"[BIAS] {ticker}: PDH=${pdh:.2f} | PDL=${pdl:.2f} | {len(pivots)} pivots")
        
        # Step 4: Get today's pre-market/early session bars
        today_bars = data_manager.get_today_session_bars(ticker)
        
        if not today_bars or len(today_bars) < 3:
            print(f"[BIAS] {ticker}: Waiting for session data (pre-market or opening)")
            return self._set_neutral_bias("Awaiting session data")
        
        # Step 5: Check for liquidity sweeps
        bullish_sweep = self._check_bullish_sweep(today_bars, pdl)
        bearish_sweep = self._check_bearish_sweep(today_bars, pdh)
        
        # Step 6: Determine bias from sweep analysis
        return self._determine_bias(
            ticker=ticker,
            bullish_sweep=bullish_sweep,
            bearish_sweep=bearish_sweep,
            pdh=pdh,
            pdl=pdl,
            current_price=today_bars[-1]['close']
        )
    
    def _get_hourly_bars(self, ticker: str, date: datetime) -> List[Dict]:
        """
        Get 1-hour bars for specified date.
        Uses 5-minute bars and aggregates into 1-hour periods.
        """
        try:
            # Get all bars for the date
            bars_5m = data_manager.get_bars_for_date(ticker, date.strftime('%Y-%m-%d'))
            
            if not bars_5m:
                return []
            
            # Aggregate into 1-hour bars
            hourly_bars = []
            current_hour = None
            hour_data = []
            
            for bar in bars_5m:
                bar_time = bar['timestamp']
                if isinstance(bar_time, str):
                    bar_time = datetime.fromisoformat(bar_time.replace('Z', '+00:00'))
                
                bar_hour = bar_time.replace(minute=0, second=0, microsecond=0)
                
                if current_hour is None:
                    current_hour = bar_hour
                
                if bar_hour == current_hour:
                    hour_data.append(bar)
                else:
                    # Aggregate completed hour
                    if hour_data:
                        hourly_bars.append(self._aggregate_bars(hour_data, current_hour))
                    current_hour = bar_hour
                    hour_data = [bar]
            
            # Add final hour
            if hour_data:
                hourly_bars.append(self._aggregate_bars(hour_data, current_hour))
            
            return hourly_bars
        
        except Exception as e:
            print(f"[BIAS] Error getting hourly bars for {ticker}: {e}")
            return []
    
    def _aggregate_bars(self, bars: List[Dict], timestamp: datetime) -> Dict:
        """Aggregate multiple bars into single OHLCV bar."""
        return {
            'timestamp': timestamp,
            'open': bars[0]['open'],
            'high': max(b['high'] for b in bars),
            'low': min(b['low'] for b in bars),
            'close': bars[-1]['close'],
            'volume': sum(b['volume'] for b in bars)
        }
    
    def _find_pivots(self, bars: List[Dict]) -> List[Dict]:
        """
        Find pivot highs and lows using N-bar pattern.
        
        Pivot High: Bar[i] higher than N bars left and N bars right
        Pivot Low: Bar[i] lower than N bars left and N bars right
        """
        pivots = []
        n = self.pivot_lookback
        
        # Need at least 2N+1 bars (N left, center, N right)
        if len(bars) < (2 * n + 1):
            return pivots
        
        # Check each potential pivot (skip first/last N bars)
        for i in range(n, len(bars) - n):
            center = bars[i]
            
            # Check pivot high
            is_pivot_high = True
            for offset in range(-n, n + 1):
                if offset == 0:
                    continue
                if bars[i + offset]['high'] >= center['high']:
                    is_pivot_high = False
                    break
            
            if is_pivot_high:
                pivots.append({
                    'type': 'HIGH',
                    'price': center['high'],
                    'timestamp': center['timestamp'],
                    'index': i
                })
                continue
            
            # Check pivot low
            is_pivot_low = True
            for offset in range(-n, n + 1):
                if offset == 0:
                    continue
                if bars[i + offset]['low'] <= center['low']:
                    is_pivot_low = False
                    break
            
            if is_pivot_low:
                pivots.append({
                    'type': 'LOW',
                    'price': center['low'],
                    'timestamp': center['timestamp'],
                    'index': i
                })
        
        return pivots
    
    def _check_bullish_sweep(self, bars: List[Dict], pdl: float) -> Optional[Dict]:
        """
        Check for bullish liquidity sweep below PDL.
        
        Criteria:
          1. Price wicks below PDL by sweep_tolerance
          2. Bar closes back above PDL (rejection)
          3. Rejection size >= min_rejection_pct
        """
        sweep_threshold = pdl * (1.0 - self.sweep_tolerance_pct)
        
        for i, bar in enumerate(bars):
            # Check if wick swept below PDL
            if bar['low'] <= sweep_threshold:
                # Check for rejection (close back above PDL)
                if bar['close'] > pdl:
                    rejection_pct = (bar['close'] - bar['low']) / bar['low']
                    
                    if rejection_pct >= self.min_rejection_pct:
                        return {
                            'type': 'BULLISH',
                            'sweep_price': bar['low'],
                            'close_price': bar['close'],
                            'rejection_pct': rejection_pct * 100,
                            'timestamp': bar['timestamp'],
                            'bar_index': i
                        }
        
        return None
    
    def _check_bearish_sweep(self, bars: List[Dict], pdh: float) -> Optional[Dict]:
        """
        Check for bearish liquidity sweep above PDH.
        
        Criteria:
          1. Price wicks above PDH by sweep_tolerance
          2. Bar closes back below PDH (rejection)
          3. Rejection size >= min_rejection_pct
        """
        sweep_threshold = pdh * (1.0 + self.sweep_tolerance_pct)
        
        for i, bar in enumerate(bars):
            # Check if wick swept above PDH
            if bar['high'] >= sweep_threshold:
                # Check for rejection (close back below PDH)
                if bar['close'] < pdh:
                    rejection_pct = (bar['high'] - bar['close']) / bar['high']
                    
                    if rejection_pct >= self.min_rejection_pct:
                        return {
                            'type': 'BEARISH',
                            'sweep_price': bar['high'],
                            'close_price': bar['close'],
                            'rejection_pct': rejection_pct * 100,
                            'timestamp': bar['timestamp'],
                            'bar_index': i
                        }
        
        return None
    
    def _determine_bias(self,
                       ticker: str,
                       bullish_sweep: Optional[Dict],
                       bearish_sweep: Optional[Dict],
                       pdh: float,
                       pdl: float,
                       current_price: float) -> Dict:
        """
        Determine daily bias from sweep analysis and price structure.
        
        Priority:
          1. Liquidity sweep + structural confirmation (highest confidence)
          2. Price relative to PDH/PDL range (medium confidence)
          3. No clear signal (neutral, low confidence)
        """
        reasons = []
        confidence = 0.0
        bias = 'NEUTRAL'
        
        # Check for bullish sweep
        if bullish_sweep:
            reasons.append(
                f"Bullish sweep @ ${bullish_sweep['sweep_price']:.2f} "
                f"(rejection: {bullish_sweep['rejection_pct']:.1f}%)"
            )
            
            # Strong bullish bias if price reclaimed above PDL
            if current_price > pdl:
                bias = 'BULL'
                confidence = 0.85
                reasons.append(f"Price reclaimed above PDL (${pdl:.2f})")
            else:
                bias = 'BULL'
                confidence = 0.65
                reasons.append("Sweep detected but awaiting reclaim")
        
        # Check for bearish sweep
        elif bearish_sweep:
            reasons.append(
                f"Bearish sweep @ ${bearish_sweep['sweep_price']:.2f} "
                f"(rejection: {bearish_sweep['rejection_pct']:.1f}%)"
            )
            
            # Strong bearish bias if price broke below PDH
            if current_price < pdh:
                bias = 'BEAR'
                confidence = 0.85
                reasons.append(f"Price broke below PDH (${pdh:.2f})")
            else:
                bias = 'BEAR'
                confidence = 0.65
                reasons.append("Sweep detected but awaiting breakdown")
        
        # No sweep - check price position relative to range
        else:
            mid_range = (pdh + pdl) / 2.0
            range_size = pdh - pdl
            
            if current_price > (pdh - range_size * 0.2):
                # Price in upper 20% of range
                bias = 'BEAR'
                confidence = 0.4
                reasons.append(f"Price near PDH (${pdh:.2f}) - premium zone")
            elif current_price < (pdl + range_size * 0.2):
                # Price in lower 20% of range
                bias = 'BULL'
                confidence = 0.4
                reasons.append(f"Price near PDL (${pdl:.2f}) - discount zone")
            else:
                # Price in middle - no clear bias
                bias = 'NEUTRAL'
                confidence = 0.3
                reasons.append("Price in equilibrium - no clear sweep")
        
        # Cache the bias
        self.current_bias = bias
        self.bias_confidence = confidence
        self.bias_reasons = reasons
        self.bias_timestamp = datetime.now(ET)
        
        print(f"\n[BIAS] {ticker} DAILY BIAS: {bias} ({confidence*100:.0f}% confidence)")
        for reason in reasons:
            print(f"[BIAS]   • {reason}")
        print()
        
        return self._get_bias_dict()
    
    def _set_neutral_bias(self, reason: str) -> Dict:
        """Set neutral bias with reason."""
        self.current_bias = 'NEUTRAL'
        self.bias_confidence = 0.0
        self.bias_reasons = [reason]
        self.bias_timestamp = datetime.now(ET)
        return self._get_bias_dict()
    
    def _get_bias_dict(self) -> Dict:
        """Get current bias as dict."""
        return {
            'bias': self.current_bias,
            'confidence': self.bias_confidence,
            'reasons': self.bias_reasons,
            'timestamp': self.bias_timestamp,
            'key_levels': self.key_levels
        }
    
    def should_filter_signal(self, ticker: str, signal_direction: str) -> Tuple[bool, str]:
        """
        Check if signal should be filtered based on daily bias.
        
        Args:
            ticker: Stock ticker
            signal_direction: 'BUY' or 'SELL'
        
        Returns:
            (should_filter, reason)
        """
        # Get or calculate bias
        if not self.current_bias or not self.bias_timestamp:
            bias_data = self.calculate_daily_bias(ticker)
        else:
            bias_data = self._get_bias_dict()
        
        bias = bias_data['bias']
        confidence = bias_data['confidence']
        
        # Allow all signals in NEUTRAL bias
        if bias == 'NEUTRAL':
            return False, "Neutral bias - all signals allowed"
        
        # Filter counter-trend signals if confidence is high
        if confidence >= 0.7:
            if bias == 'BULL' and signal_direction == 'SELL':
                return True, f"Counter-trend SELL signal filtered (BULLISH bias, {confidence*100:.0f}% conf)"
            elif bias == 'BEAR' and signal_direction == 'BUY':
                return True, f"Counter-trend BUY signal filtered (BEARISH bias, {confidence*100:.0f}% conf)"
        
        # Allow signal - aligned with bias or low confidence
        return False, f"Signal aligned with {bias} bias ({confidence*100:.0f}% conf)"
    
    def get_bias_summary(self, ticker: str) -> str:
        """Get formatted bias summary for display."""
        if not self.current_bias:
            return "[BIAS] Not calculated yet"
        
        emoji = {
            'BULL': '🟢',
            'BEAR': '🔴',
            'NEUTRAL': '⚪'
        }.get(self.current_bias, '⚪')
        
        summary = f"\n{'='*70}\n"
        summary += f"DAILY BIAS: {emoji} {self.current_bias}\n"
        summary += f"Confidence: {self.bias_confidence*100:.0f}%\n"
        summary += f"{'='*70}\n"
        
        if ticker in self.key_levels:
            levels = self.key_levels[ticker]
            summary += f"PDH: ${levels['PDH']:.2f}\n"
            summary += f"PDL: ${levels['PDL']:.2f}\n"
            summary += f"Pivots: {len(levels.get('pivots', []))}\n"
        
        summary += "\nReasons:\n"
        for reason in self.bias_reasons:
            summary += f"  • {reason}\n"
        
        summary += f"{'='*70}\n"
        return summary
    
    def reset_daily(self) -> None:
        """Reset bias engine for new trading day."""
        self.current_bias = None
        self.bias_timestamp = None
        self.bias_confidence = 0.0
        self.bias_reasons = []
        self.yesterday_pivots.clear()
        self.key_levels.clear()
        print("[BIAS] Daily reset complete - bias engine cleared")


# ========================================
# GLOBAL INSTANCE
# ========================================
bias_engine = DailyBiasEngine(
    pivot_lookback=2,
    sweep_tolerance_pct=0.15,
    min_rejection_pct=0.3
)


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def get_daily_bias(ticker: str, force_refresh: bool = False) -> Dict:
    """Get daily bias for ticker."""
    return bias_engine.calculate_daily_bias(ticker, force_refresh)


def should_filter_signal(ticker: str, signal_direction: str) -> Tuple[bool, str]:
    """Check if signal should be filtered based on daily bias."""
    return bias_engine.should_filter_signal(ticker, signal_direction)


def print_bias_summary(ticker: str) -> None:
    """Print daily bias summary."""
    print(bias_engine.get_bias_summary(ticker))


def reset_bias() -> None:
    """Reset bias engine for new day."""
    bias_engine.reset_daily()


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    # Example: Calculate daily bias for SPY
    ticker = "SPY"
    
    print(f"Calculating daily bias for {ticker}...\n")
    bias_data = get_daily_bias(ticker)
    
    print_bias_summary(ticker)
    
    # Test signal filtering
    print("\nTesting signal filtering:\n")
    
    for direction in ['BUY', 'SELL']:
        should_filter, reason = should_filter_signal(ticker, direction)
        status = "❌ FILTERED" if should_filter else "✅ ALLOWED"
        print(f"{status} {direction} signal: {reason}")
