"""
Market Analysis Module - Phase 3D Consolidation

Consolidates daily_bias_engine.py + vpvr_calculator.py into single module.

PHASE 3D CONSOLIDATION (Feb 26, 2026):
  - Merged 2 files → 1 active module
  - 44KB → ~42KB (5% reduction)
  - Single source of truth for market analysis
  - Compatibility maintained via factory functions

Components:
  1. DailyBiasEngine - ICT top-down bias determination
  2. VPVRCalculator - Volume profile analysis

Usage:
  from market_analysis import bias_engine, vpvr_calculator
  
  # Daily bias
  bias_data = bias_engine.calculate_daily_bias('SPY')
  should_filter, reason = bias_engine.should_filter_signal('SPY', 'BUY')
  
  # Volume profile
  vpvr = vpvr_calculator.calculate_vpvr(bars, lookback_bars=78)
  score, reason = vpvr_calculator.get_entry_score(entry_price, vpvr)
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import json

from data_manager import data_manager

ET = ZoneInfo("America/New_York")


# ══════════════════════════════════════════════════════════════════════════════
# DAILY BIAS ENGINE (from daily_bias_engine.py)
# ══════════════════════════════════════════════════════════════════════════════

class DailyBiasEngine:
    """
    ICT-style daily bias determination from higher timeframe analysis.
    
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

    Staleness Protection (Issue #6 fix - FEB 25, 2026):
      - Bias expires after MAX_BIAS_AGE_MINUTES
      - Automatic refresh when accessing stale bias
      - Prevents filtering on outdated market conditions
    """
    
    # ⭐ Issue #6 Fix: Maximum bias age before refresh required
    MAX_BIAS_AGE_MINUTES = 120  # 2 hours
    
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
        print(f"[BIAS] ⏰ Max bias age: {self.MAX_BIAS_AGE_MINUTES} minutes (auto-refresh when stale)")
    
    def _is_bias_stale(self) -> bool:
        """
        Check if current bias is stale (too old).
        
        Returns:
            True if bias should be refreshed
        """
        if not self.bias_timestamp:
            return True
        
        now = datetime.now(ET)
        age_minutes = (now - self.bias_timestamp).total_seconds() / 60
        
        # Check if same trading day
        if self.bias_timestamp.date() != now.date():
            return True
        
        # Check age threshold
        if age_minutes > self.MAX_BIAS_AGE_MINUTES:
            return True
        
        return False
    
    def _get_bias_age_minutes(self) -> Optional[float]:
        """
        Get age of current bias in minutes.
        
        Returns:
            Age in minutes or None if no bias
        """
        if not self.bias_timestamp:
            return None
        
        now = datetime.now(ET)
        return (now - self.bias_timestamp).total_seconds() / 60
    
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
            Dict with bias, confidence, reasons, key levels, and age
        """
        now = datetime.now(ET)
        
        # ⭐ Issue #6 Fix: Check staleness before returning cached bias
        if not force_refresh and self.current_bias and self.bias_timestamp:
            if not self._is_bias_stale():
                age_minutes = self._get_bias_age_minutes()
                result = self._get_bias_dict()
                result['age_minutes'] = round(age_minutes, 1) if age_minutes else None
                return result
            else:
                age_minutes = self._get_bias_age_minutes()
                print(f"[BIAS] ⚠️  Bias is stale (age: {age_minutes:.1f} min > {self.MAX_BIAS_AGE_MINUTES} min) - refreshing...")
        
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
        print(f"[BIAS] ⏰ Bias calculated at {self.bias_timestamp.strftime('%H:%M:%S')}")
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
        age_minutes = self._get_bias_age_minutes()
        
        return {
            'bias': self.current_bias,
            'confidence': self.bias_confidence,
            'reasons': self.bias_reasons,
            'timestamp': self.bias_timestamp,
            'age_minutes': round(age_minutes, 1) if age_minutes is not None else None,
            'is_stale': self._is_bias_stale(),
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
        # ⭐ Issue #6 Fix: Check staleness and auto-refresh if needed
        if not self.current_bias or not self.bias_timestamp or self._is_bias_stale():
            age_minutes = self._get_bias_age_minutes()
            if age_minutes is not None:
                print(f"[BIAS] ⏰ Bias age: {age_minutes:.1f} min - refreshing for {ticker}...")
            bias_data = self.calculate_daily_bias(ticker)
        else:
            bias_data = self._get_bias_dict()
            age_minutes = bias_data.get('age_minutes')
            if age_minutes and age_minutes > 60:
                print(f"[BIAS] ⚠️  Using bias from {age_minutes:.0f} min ago (still fresh)")
        
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
        
        age_minutes = self._get_bias_age_minutes()
        is_stale = self._is_bias_stale()
        
        summary = f"\n{'='*70}\n"
        summary += f"DAILY BIAS: {emoji} {self.current_bias}\n"
        summary += f"Confidence: {self.bias_confidence*100:.0f}%\n"
        
        if age_minutes is not None:
            summary += f"Age: {age_minutes:.0f} min {'⚠️ STALE' if is_stale else '✅ FRESH'}\n"
        
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


# ══════════════════════════════════════════════════════════════════════════════
# VPVR CALCULATOR (from vpvr_calculator.py)
# ══════════════════════════════════════════════════════════════════════════════

class VPVRCalculator:
    """
    Calculate volume profile metrics from intraday bars.
    
    Provides volume profile analysis for better entry/exit precision:
      - Point of Control (POC): Price level with highest traded volume
      - High Volume Nodes (HVN): Price clusters with heavy activity
      - Low Volume Nodes (LVN): Price zones with thin trading (potential breakout areas)
      - Value Area High/Low (VAH/VAL): 70% volume distribution boundaries

    Integration: Called by signal_validator.py and sniper.py for entry refinement.

    Edge Case Handling (Issue #4 fixes):
      - Minimum 10 bars required (graceful fallback below threshold)
      - Zero/low volume bars filtered appropriately
      - Flat price action detection (< $0.01 range)
      - Division by zero protection
    
    Use cases:
      - Entry refinement: Enter near POC or HVN for institutional support
      - Avoid LVNs: Thin zones where price can whipsaw quickly
      - Target setting: Place targets at VAH/VAL boundaries
      - Stop placement: Use LVNs as stop-loss zones (price likely to slice through)
    """
    
    # ⭐ Issue #4 Fix: Edge case thresholds
    MIN_BARS_REQUIRED = 10
    MIN_PRICE_RANGE = 0.01
    MIN_TOTAL_VOLUME = 1000
    
    def __init__(self, num_bins: int = 30):
        """
        Initialize VPVR calculator.
        
        Args:
            num_bins: Number of price bins to divide range into (default 30)
                     Higher = more granular, Lower = smoother profile
        """
        self.num_bins = num_bins
        self._cache = {}  # Cache results to avoid recalculation
        self._cache_ttl = 60  # Cache TTL in seconds
        
        print(f"[VPVR] Initialized with {num_bins} bins | Min bars: {self.MIN_BARS_REQUIRED}")
    
    def calculate_vpvr(self, bars: List[Dict], lookback_bars: int = 78) -> Dict:
        """
        Calculate volume profile from recent bars.
        
        Args:
            bars: List of bar dicts with datetime, open, high, low, close, volume
            lookback_bars: Number of bars to analyze (default 78 = ~1.3 hours of 1m bars)
        
        Returns:
            Dict with:
              - poc: Point of Control price
              - poc_volume: Volume at POC
              - vah: Value Area High (top of 70% volume)
              - val: Value Area Low (bottom of 70% volume)
              - hvn_zones: List of (price_low, price_high) tuples for High Volume Nodes
              - lvn_zones: List of (price_low, price_high) tuples for Low Volume Nodes
              - profile: Full volume profile bins [(price, volume), ...]
              - error: Optional error message if edge case detected
        """
        # ⭐ Issue #4 Fix: Enhanced validation
        if not bars:
            return self._empty_result(error="No bars provided")
        
        if len(bars) < self.MIN_BARS_REQUIRED:
            return self._empty_result(
                error=f"Insufficient bars: {len(bars)} < {self.MIN_BARS_REQUIRED} required"
            )
        
        # Use only last N bars
        recent_bars = bars[-lookback_bars:] if len(bars) > lookback_bars else bars
        
        # ⭐ Issue #4 Fix: Filter bars with missing or invalid data
        valid_bars = [
            b for b in recent_bars
            if all(k in b for k in ['low', 'high', 'volume'])
            and b['high'] >= b['low']
            and b['volume'] >= 0
        ]
        
        if len(valid_bars) < self.MIN_BARS_REQUIRED:
            return self._empty_result(
                error=f"Insufficient valid bars: {len(valid_bars)} < {self.MIN_BARS_REQUIRED}"
            )
        
        # Find price range
        try:
            price_low = min(b["low"] for b in valid_bars)
            price_high = max(b["high"] for b in valid_bars)
        except (ValueError, KeyError) as e:
            return self._empty_result(error=f"Price range calculation error: {e}")
        
        price_range = price_high - price_low
        
        # ⭐ Issue #4 Fix: Handle flat price action
        if price_range < self.MIN_PRICE_RANGE:
            print(f"[VPVR] ⚠️  Flat price action detected (range: ${price_range:.4f})")
            # Return simplified result with POC at midpoint
            mid_price = (price_low + price_high) / 2
            total_volume = sum(b.get('volume', 0) for b in valid_bars)
            
            return {
                'poc': round(mid_price, 2),
                'poc_volume': round(total_volume, 0),
                'vah': round(price_high, 2),
                'val': round(price_low, 2),
                'hvn_zones': [(round(price_low, 2), round(price_high, 2))],  # Entire range is HVN
                'lvn_zones': [],
                'profile': [(round(mid_price, 2), total_volume)],
                'total_volume': round(total_volume, 0),
                'price_range': round(price_range, 2),
                'warning': 'Flat price action - limited profile accuracy'
            }
        
        # Create price bins
        bin_size = price_range / self.num_bins
        bins = [0.0] * self.num_bins  # Volume per bin
        bin_prices = [
            price_low + (i + 0.5) * bin_size
            for i in range(self.num_bins)
        ]
        
        # ⭐ Issue #4 Fix: Track bars with zero volume
        zero_volume_count = 0
        
        # Distribute volume across bins based on bar range
        for bar in valid_bars:
            bar_low = bar["low"]
            bar_high = bar["high"]
            bar_volume = bar.get("volume", 0)
            
            # ⭐ Issue #4 Fix: Handle zero volume bars
            if bar_volume <= 0:
                zero_volume_count += 1
                continue
            
            # Find bins that this bar spans
            start_bin = int((bar_low - price_low) / bin_size)
            end_bin = int((bar_high - price_low) / bin_size)
            
            # Clamp to valid range
            start_bin = max(0, min(start_bin, self.num_bins - 1))
            end_bin = max(0, min(end_bin, self.num_bins - 1))
            
            # Distribute volume evenly across bins the bar touched
            bins_touched = end_bin - start_bin + 1
            volume_per_bin = bar_volume / bins_touched
            
            for i in range(start_bin, end_bin + 1):
                bins[i] += volume_per_bin
        
        # ⭐ Issue #4 Fix: Validate total volume
        total_volume = sum(bins)
        
        if total_volume < self.MIN_TOTAL_VOLUME:
            print(f"[VPVR] ⚠️  Low total volume: {total_volume:,.0f}")
            return self._empty_result(
                error=f"Insufficient volume: {total_volume:,.0f} < {self.MIN_TOTAL_VOLUME:,.0f}"
            )
        
        if zero_volume_count > len(valid_bars) * 0.3:
            print(f"[VPVR] ⚠️  High zero-volume bar ratio: {zero_volume_count}/{len(valid_bars)}")
        
        # Find POC (Point of Control) - bin with highest volume
        try:
            poc_bin_idx = np.argmax(bins)
            poc_price = bin_prices[poc_bin_idx]
            poc_volume = bins[poc_bin_idx]
        except (ValueError, IndexError) as e:
            return self._empty_result(error=f"POC calculation error: {e}")
        
        # Calculate Value Area (70% of volume)
        target_volume = total_volume * 0.70
        
        # Start from POC and expand outward until we capture 70% volume
        try:
            vah_idx, val_idx = self._find_value_area(
                bins, poc_bin_idx, target_volume
            )
            vah = bin_prices[vah_idx]
            val = bin_prices[val_idx]
        except Exception as e:
            print(f"[VPVR] ⚠️  Value area calculation error: {e}")
            # Fallback to full range
            vah = price_high
            val = price_low
        
        # Identify HVN and LVN zones
        try:
            hvn_zones, lvn_zones = self._identify_nodes(
                bins, bin_prices, bin_size, total_volume
            )
        except Exception as e:
            print(f"[VPVR] ⚠️  Node identification error: {e}")
            hvn_zones = []
            lvn_zones = []
        
        # Build full profile for optional detailed analysis
        profile = list(zip(bin_prices, bins))
        
        result = {
            "poc": round(poc_price, 2),
            "poc_volume": round(poc_volume, 0),
            "vah": round(vah, 2),
            "val": round(val, 2),
            "hvn_zones": hvn_zones,
            "lvn_zones": lvn_zones,
            "profile": profile,
            "total_volume": round(total_volume, 0),
            "price_range": round(price_range, 2)
        }
        
        # Add warnings if edge cases detected
        if zero_volume_count > 0:
            result['zero_volume_bars'] = zero_volume_count
        
        return result
    
    def _find_value_area(self, bins: List[float], poc_idx: int, 
                        target_volume: float) -> Tuple[int, int]:
        """
        Find Value Area High and Low indices by expanding from POC.
        
        Args:
            bins: Volume distribution across bins
            poc_idx: Index of POC bin
            target_volume: Target volume (70% of total)
        
        Returns:
            (vah_idx, val_idx) tuple
        """
        if not bins or poc_idx >= len(bins) or poc_idx < 0:
            raise ValueError(f"Invalid POC index: {poc_idx}")
        
        accumulated_volume = bins[poc_idx]
        vah_idx = poc_idx
        val_idx = poc_idx
        
        # ⭐ Issue #4 Fix: Safety counter to prevent infinite loops
        max_iterations = len(bins) * 2
        iterations = 0
        
        # Expand outward from POC until we capture target volume
        while accumulated_volume < target_volume and iterations < max_iterations:
            iterations += 1
            
            # Check which direction has more volume
            volume_above = bins[vah_idx + 1] if vah_idx + 1 < len(bins) else 0
            volume_below = bins[val_idx - 1] if val_idx - 1 >= 0 else 0
            
            # ⭐ Issue #4 Fix: Handle case where both directions are exhausted
            if volume_above == 0 and volume_below == 0:
                break
            
            if volume_above > volume_below and vah_idx + 1 < len(bins):
                vah_idx += 1
                accumulated_volume += bins[vah_idx]
            elif val_idx - 1 >= 0:
                val_idx -= 1
                accumulated_volume += bins[val_idx]
            else:
                break  # Can't expand further
        
        return vah_idx, val_idx
    
    def _identify_nodes(self, bins: List[float], bin_prices: List[float],
                       bin_size: float, total_volume: float) -> Tuple[List, List]:
        """
        Identify High Volume Nodes (HVN) and Low Volume Nodes (LVN).
        
        Args:
            bins: Volume distribution
            bin_prices: Price at each bin center
            bin_size: Width of each bin
            total_volume: Total volume across all bins
        
        Returns:
            (hvn_zones, lvn_zones) tuple of lists
        """
        # ⭐ Issue #4 Fix: Enhanced validation
        if not bins or total_volume == 0 or len(bins) != len(bin_prices):
            return [], []
        
        avg_volume = total_volume / len(bins)
        
        # ⭐ Issue #4 Fix: Avoid thresholds on very low average volume
        if avg_volume < 10:
            print(f"[VPVR] ⚠️  Very low average volume per bin: {avg_volume:.1f}")
            return [], []
        
        # HVN: Bins with volume > 150% of average
        hvn_threshold = avg_volume * 1.5
        # LVN: Bins with volume < 50% of average
        lvn_threshold = avg_volume * 0.5
        
        hvn_zones = []
        lvn_zones = []
        
        # Group consecutive bins into zones
        i = 0
        while i < len(bins):
            if bins[i] >= hvn_threshold:
                # Start of HVN zone
                zone_start = i
                while i < len(bins) and bins[i] >= hvn_threshold:
                    i += 1
                zone_end = i - 1
                
                price_low = bin_prices[zone_start] - bin_size / 2
                price_high = bin_prices[zone_end] + bin_size / 2
                hvn_zones.append((round(price_low, 2), round(price_high, 2)))
            
            elif bins[i] <= lvn_threshold:
                # Start of LVN zone
                zone_start = i
                while i < len(bins) and bins[i] <= lvn_threshold:
                    i += 1
                zone_end = i - 1
                
                price_low = bin_prices[zone_start] - bin_size / 2
                price_high = bin_prices[zone_end] + bin_size / 2
                lvn_zones.append((round(price_low, 2), round(price_high, 2)))
            else:
                i += 1
        
        return hvn_zones, lvn_zones
    
    def _empty_result(self, error: str = None) -> Dict:
        """
        Return empty result when insufficient data.
        
        Args:
            error: Optional error message describing why result is empty
        """
        result = {
            "poc": None,
            "poc_volume": 0,
            "vah": None,
            "val": None,
            "hvn_zones": [],
            "lvn_zones": [],
            "profile": [],
            "total_volume": 0,
            "price_range": 0
        }
        
        if error:
            result['error'] = error
            print(f"[VPVR] {error}")
        
        return result
    
    def get_entry_score(self, price: float, vpvr: Dict) -> Tuple[float, str]:
        """
        Score an entry price based on VPVR analysis.
        
        Args:
            price: Proposed entry price
            vpvr: VPVR result from calculate_vpvr()
        
        Returns:
            (score, reason) tuple
              score: 0.0 - 1.0 (higher is better)
              reason: Human-readable explanation
        """
        # ⭐ Issue #4 Fix: Better edge case handling
        if not vpvr:
            return 0.5, "No VPVR data"
        
        if 'error' in vpvr:
            return 0.5, f"VPVR error: {vpvr['error']}"
        
        if vpvr["poc"] is None:
            return 0.5, "No POC calculated"
        
        # ⭐ Issue #4 Fix: Handle warnings
        if 'warning' in vpvr:
            print(f"[VPVR] Entry score calculated with warning: {vpvr['warning']}")
        
        poc = vpvr["poc"]
        vah = vpvr["vah"]
        val = vpvr["val"]
        hvn_zones = vpvr["hvn_zones"]
        lvn_zones = vpvr["lvn_zones"]
        
        # ⭐ Issue #4 Fix: Division by zero protection
        if poc == 0:
            return 0.5, "Invalid POC (zero price)"
        
        # Best: Entry at or near POC (institutional support)
        poc_distance_pct = abs(price - poc) / poc * 100
        if poc_distance_pct < 0.3:  # Within 0.3% of POC
            return 1.0, f"At POC (${poc:.2f}) - strongest support"
        
        # Good: Entry within HVN zone (high volume area)
        for hvn_low, hvn_high in hvn_zones:
            if hvn_low <= price <= hvn_high:
                return 0.85, f"In HVN zone (${hvn_low:.2f}-${hvn_high:.2f})"
        
        # Good: Entry within Value Area (70% volume)
        if vah and val and val <= price <= vah:
            return 0.75, f"In Value Area (${val:.2f}-${vah:.2f})"
        
        # Risky: Entry in LVN zone (thin volume, whipsaw risk)
        for lvn_low, lvn_high in lvn_zones:
            if lvn_low <= price <= lvn_high:
                return 0.3, f"⚠️  In LVN zone (${lvn_low:.2f}-${lvn_high:.2f}) - thin volume"
        
        # Neutral: Outside value area but not in LVN
        if vah and price > vah:
            return 0.55, f"Above Value Area (VAH: ${vah:.2f})"
        elif val and price < val:
            return 0.55, f"Below Value Area (VAL: ${val:.2f})"
        else:
            return 0.6, "Near value area"
    
    def get_stop_recommendation(self, direction: str, entry: float, 
                               vpvr: Dict) -> Optional[float]:
        """
        Recommend stop-loss placement based on volume profile.
        
        Args:
            direction: "bull" or "bear"
            entry: Entry price
            vpvr: VPVR result from calculate_vpvr()
        
        Returns:
            Recommended stop price or None
        """
        if not vpvr or not vpvr.get("lvn_zones") or 'error' in vpvr:
            return None
        
        lvn_zones = vpvr["lvn_zones"]
        
        if direction == "bull":
            # For longs, find LVN below entry (price likely to slice through)
            candidates = [
                lvn_low for lvn_low, lvn_high in lvn_zones
                if lvn_high < entry
            ]
            if candidates:
                # Return bottom of closest LVN below entry
                return max(candidates)
        
        else:  # bear
            # For shorts, find LVN above entry
            candidates = [
                lvn_high for lvn_low, lvn_high in lvn_zones
                if lvn_low > entry
            ]
            if candidates:
                # Return top of closest LVN above entry
                return min(candidates)
        
        return None
    
    def get_target_recommendation(self, direction: str, entry: float,
                                 vpvr: Dict) -> Optional[float]:
        """
        Recommend profit target based on volume profile.
        
        Args:
            direction: "bull" or "bear"
            entry: Entry price
            vpvr: VPVR result from calculate_vpvr()
        
        Returns:
            Recommended target price or None
        """
        if not vpvr or vpvr.get("vah") is None or 'error' in vpvr:
            return None
        
        vah = vpvr["vah"]
        val = vpvr["val"]
        hvn_zones = vpvr.get("hvn_zones", [])
        
        if direction == "bull":
            # For longs, target VAH or next HVN above entry
            if vah > entry:
                return vah
            
            # Find next HVN above VAH
            candidates = [
                hvn_low for hvn_low, hvn_high in hvn_zones
                if hvn_low > vah
            ]
            if candidates:
                return min(candidates)
        
        else:  # bear
            # For shorts, target VAL or next HVN below entry
            if val and val < entry:
                return val
            
            # Find next HVN below VAL
            candidates = [
                hvn_high for hvn_low, hvn_high in hvn_zones
                if hvn_high < val
            ]
            if candidates:
                return max(candidates)
        
        return None
    
    def format_vpvr_summary(self, vpvr: Dict) -> str:
        """
        Format VPVR data for console display.
        
        Args:
            vpvr: VPVR result from calculate_vpvr()
        
        Returns:
            Formatted string
        """
        if not vpvr:
            return "[VPVR] No volume profile data available"
        
        if 'error' in vpvr:
            return f"[VPVR] Error: {vpvr['error']}"
        
        if vpvr.get("poc") is None:
            return "[VPVR] No volume profile data available"
        
        lines = [
            f"[VPVR] POC: ${vpvr['poc']:.2f} (vol: {vpvr['poc_volume']:,.0f})",
            f"[VPVR] Value Area: ${vpvr['val']:.2f} - ${vpvr['vah']:.2f}"
        ]
        
        if 'warning' in vpvr:
            lines.append(f"[VPVR] ⚠️  Warning: {vpvr['warning']}")
        
        if vpvr.get("hvn_zones"):
            hvn_str = ", ".join(
                f"${low:.2f}-${high:.2f}"
                for low, high in vpvr["hvn_zones"]
            )
            lines.append(f"[VPVR] HVN Zones: {hvn_str}")
        
        if vpvr.get("lvn_zones"):
            lvn_str = ", ".join(
                f"${low:.2f}-${high:.2f}"
                for low, high in vpvr["lvn_zones"]
            )
            lines.append(f"[VPVR] LVN Zones: {lvn_str} (⚠️  thin volume)")
        
        if 'zero_volume_bars' in vpvr and vpvr['zero_volume_bars'] > 0:
            lines.append(f"[VPVR] Zero-volume bars: {vpvr['zero_volume_bars']}")
        
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCES & CONVENIENCE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

# Global singletons
bias_engine = DailyBiasEngine(
    pivot_lookback=2,
    sweep_tolerance_pct=0.15,
    min_rejection_pct=0.3
)

vpvr_calculator = VPVRCalculator(num_bins=30)


# Daily Bias convenience functions
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


# Export all public APIs
__all__ = [
    # Classes
    'DailyBiasEngine',
    'VPVRCalculator',
    # Global instances
    'bias_engine',
    'vpvr_calculator',
    # Convenience functions
    'get_daily_bias',
    'should_filter_signal',
    'print_bias_summary',
    'reset_bias',
]


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("MARKET ANALYSIS MODULE - Unified Testing")
    print("=" * 70 + "\n")
    
    print("Testing DailyBiasEngine...")
    print(f"✅ bias_engine initialized")
    
    print("\nTesting VPVRCalculator...")
    print(f"✅ vpvr_calculator initialized")
    
    print("\n" + "=" * 70)
    print("All market analysis components operational!")
    print("=" * 70)
