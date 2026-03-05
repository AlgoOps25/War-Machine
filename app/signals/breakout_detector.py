"""
Breakout Entry Detector - High-Probability Entry Signals

Strategy:
  - 5-minute breakout above resistance (highest high of last N bars)
  - Volume confirmation: current volume > 2x EMA volume (more responsive than SMA)
  - ATR-based dynamic stops and targets
  - Filters out low-quality breakouts (low volume, choppy price action, weak candles)
  - PDH/PDL awareness: Uses previous day levels as dynamic support/resistance
  - Split profit targets: T1 (1.5R) and T2 (2.5R) for optimal trade management

Entry Types:
  1. BULL BREAKOUT: Price breaks above resistance + volume spike + strong candle
  2. BEAR BREAKDOWN: Price breaks below support + volume spike + strong candle
  3. RETEST ENTRY: Price retests breakout level with volume confirmation

Phase 1.8 Optimizations:
  - PDH/PDL integration for confluence-based entries
  - EMA volume (more responsive to recent activity)
  - Price action strength filter (body%, wick rejection)
  - Breakout confirmation counter (reduces false breaks)
  - Cached ATR calculation
  - T1/T2 split targets (Issue #2 fix - FEB 25, 2026)

Risk Management:
  - Stop: ATR-based dynamic stop (typically 1.5-2x ATR)
  - T1: 1.5R (take 50% position, secure gains)
  - T2: 2.5R (let 50% run, maximize winners)
  - Max risk per trade: 1-2% of account
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import statistics


class BreakoutDetector:
    """Detect high-probability breakout entries with volume confirmation."""
    
    def __init__(self, 
                 lookback_bars: int = 12,
                 volume_multiplier: float = 2.0,
                 atr_period: int = 14,
                 atr_stop_multiplier: float = 1.5,
                 risk_reward_ratio: float = 2.0,
                 t1_reward_ratio: float = 1.5,
                 t2_reward_ratio: float = 2.5,
                 min_candle_body_pct: float = 0.4,
                 min_bars_since_breakout: int = 1):
        """
        Args:
            lookback_bars: Number of bars to determine support/resistance
            volume_multiplier: Volume must be Nx average for confirmation
            atr_period: Period for ATR calculation
            atr_stop_multiplier: Stop distance = ATR * multiplier
            risk_reward_ratio: Default target (maintained for backwards compatibility)
            t1_reward_ratio: T1 target ratio (1.5R = take 50% profit)
            t2_reward_ratio: T2 target ratio (2.5R = let 50% run)
            min_candle_body_pct: Minimum candle body% for strong price action (0.4 = 40%)
            min_bars_since_breakout: Bars to wait after initial break (false break filter)
        """
        self.lookback_bars = lookback_bars
        self.volume_multiplier = volume_multiplier
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_reward_ratio = risk_reward_ratio
        self.t1_reward_ratio = t1_reward_ratio
        self.t2_reward_ratio = t2_reward_ratio
        self.min_candle_body_pct = min_candle_body_pct
        self.min_bars_since_breakout = min_bars_since_breakout
        
        # Performance optimization: Cache ATR calculations
        self._atr_cache: Dict[str, Tuple[float, int]] = {}  # ticker -> (atr, bars_count)
        
        # PDH/PDL cache (refreshed daily)
        self._pdh_pdl_cache: Dict[str, Tuple[float, float]] = {}  # ticker -> (pdh, pdl)
        
        print(f"[BREAKOUT] Split targets enabled: T1={t1_reward_ratio}R (50%), T2={t2_reward_ratio}R (50%)")
    
    def calculate_atr(self, bars: List[Dict], ticker: str = "unknown") -> float:
        """
        Calculate Average True Range for dynamic stops.
        
        Phase 1.8: Added caching to avoid redundant calculations.
        Cache is invalidated when bar count changes.
        
        Args:
            bars: List of OHLCV bars
            ticker: Ticker symbol for cache key
        
        Returns:
            ATR value
        """
        if len(bars) < 2:
            return 0.0
        
        # Check cache
        bars_count = len(bars)
        if ticker in self._atr_cache:
            cached_atr, cached_count = self._atr_cache[ticker]
            if cached_count == bars_count:
                return cached_atr
        
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            
            # True Range = max(high-low, high-prev_close, prev_close-low)
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        # Return average of last N true ranges
        atr_bars = true_ranges[-self.atr_period:] if len(true_ranges) >= self.atr_period else true_ranges
        atr = statistics.mean(atr_bars) if atr_bars else 0.0
        
        # Update cache
        self._atr_cache[ticker] = (atr, bars_count)
        
        return atr
    
    def get_pdh_pdl(self, ticker: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get previous day high/low from data_manager.
        
        Phase 1.8: Centralized PDH/PDL retrieval for confluence analysis.
        Results are cached per ticker to avoid repeated API calls.
        
        Args:
            ticker: Stock ticker
        
        Returns:
            (pdh, pdl) tuple or (None, None) if unavailable
        """
        # Check cache first
        if ticker in self._pdh_pdl_cache:
            return self._pdh_pdl_cache[ticker]
        
        # Fetch from data_manager
        try:
            from app.data.data_manager import data_manager
            prev_day = data_manager.get_previous_day_ohlc(ticker)
            
            if prev_day and 'high' in prev_day and 'low' in prev_day:
                pdh = prev_day['high']
                pdl = prev_day['low']
                self._pdh_pdl_cache[ticker] = (pdh, pdl)
                return pdh, pdl
        except Exception as e:
            print(f"[BREAKOUT] PDH/PDL fetch error for {ticker}: {e}")
        
        return None, None
    
    def clear_pdh_pdl_cache(self) -> None:
        """
        Clear PDH/PDL cache (called at end of day).
        """
        self._pdh_pdl_cache.clear()
    
    def calculate_support_resistance(self, bars: List[Dict], ticker: str = "unknown") -> Tuple[float, float]:
        """
        Calculate support and resistance levels from recent bars.
        
        Phase 1.8: Now considers PDH/PDL as additional levels for confluence.
        
        Args:
            bars: List of OHLCV bars
            ticker: Stock ticker (for PDH/PDL lookup)
        
        Returns:
            (support, resistance) tuple
        """
        if not bars:
            return 0.0, 0.0
        
        lookback = bars[-self.lookback_bars:] if len(bars) >= self.lookback_bars else bars
        
        # Intraday levels
        intraday_resistance = max(bar['high'] for bar in lookback)
        intraday_support = min(bar['low'] for bar in lookback)
        
        # PDH/PDL levels (for confluence)
        pdh, pdl = self.get_pdh_pdl(ticker)
        
        # Use the more significant level (PDH/PDL takes precedence if nearby)
        resistance = intraday_resistance
        support = intraday_support
        
        if pdh is not None:
            # If PDH is within 2% of intraday resistance, use PDH (stronger level)
            if abs(pdh - intraday_resistance) / intraday_resistance < 0.02:
                resistance = pdh
        
        if pdl is not None:
            # If PDL is within 2% of intraday support, use PDL (stronger level)
            if abs(pdl - intraday_support) / intraday_support < 0.02:
                support = pdl
        
        return support, resistance
    
    def calculate_ema_volume(self, bars: List[Dict], period: int = None) -> float:
        """
        Calculate Exponential Moving Average of volume.
        
        Phase 1.8: EMA is more responsive to recent volume spikes than SMA.
        This helps catch momentum shifts earlier.
        
        Args:
            bars: List of OHLCV bars
            period: EMA period (defaults to lookback_bars)
        
        Returns:
            EMA volume
        """
        if not bars:
            return 0.0
        
        period = period or self.lookback_bars
        lookback = bars[-period:] if len(bars) >= period else bars
        
        if not lookback:
            return 0.0
        
        # Calculate EMA
        multiplier = 2.0 / (period + 1)
        ema = lookback[0]['volume']
        
        for bar in lookback[1:]:
            ema = (bar['volume'] * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def calculate_average_volume(self, bars: List[Dict]) -> float:
        """
        Calculate average volume over lookback period.
        
        Phase 1.8: Deprecated in favor of calculate_ema_volume().
        Kept for backwards compatibility.
        """
        return self.calculate_ema_volume(bars)
    
    def analyze_candle_strength(self, bar: Dict) -> Dict:
        """
        Analyze price action strength of a candle.
        
        Phase 1.8: Filter weak breakouts with poor candle structure.
        
        Args:
            bar: OHLCV bar dict
        
        Returns:
            {
                'body_pct': float,       # Body size as % of total range
                'is_strong': bool,       # Body% >= min threshold
                'has_rejection': bool,   # Long wick opposite to direction
                'direction': str         # 'bull' or 'bear'
            }
        """
        open_price = bar['open']
        close_price = bar['close']
        high = bar['high']
        low = bar['low']
        
        total_range = high - low
        if total_range == 0:
            return {
                'body_pct': 0.0,
                'is_strong': False,
                'has_rejection': False,
                'direction': 'neutral'
            }
        
        body_size = abs(close_price - open_price)
        body_pct = body_size / total_range
        
        # Determine direction
        direction = 'bull' if close_price > open_price else 'bear'
        
        # Check for rejection wicks (long wick opposite to close direction)
        if direction == 'bull':
            # Bull candle: check for bearish rejection (long lower wick)
            lower_wick = open_price - low
            has_rejection = (lower_wick / total_range) > 0.4
        else:
            # Bear candle: check for bullish rejection (long upper wick)
            upper_wick = high - open_price
            has_rejection = (upper_wick / total_range) > 0.4
        
        is_strong = body_pct >= self.min_candle_body_pct
        
        return {
            'body_pct': round(body_pct, 2),
            'is_strong': is_strong,
            'has_rejection': has_rejection,
            'direction': direction
        }
    
    def detect_breakout(self, bars: List[Dict], ticker: str = "unknown") -> Optional[Dict]:
        """
        Detect breakout entry signal.
        
        Phase 1.8 Enhancements:
          - PDH/PDL confluence bonus
          - EMA volume instead of SMA
          - Price action strength filter
          - Breakout confirmation (wait N bars)
          - T1/T2 split targets (Issue #2 fix)
        
        Args:
            bars: List of OHLCV bars (must have at least lookback_bars)
            ticker: Stock ticker (for PDH/PDL and caching)
        
        Returns:
            Signal dict if breakout detected, None otherwise
        """
        if len(bars) < self.lookback_bars:
            return None
        
        latest = bars[-1]
        support, resistance = self.calculate_support_resistance(bars[:-1], ticker)
        ema_volume = self.calculate_ema_volume(bars[:-1])
        atr = self.calculate_atr(bars, ticker)
        
        if ema_volume == 0 or atr == 0:
            return None
        
        current_volume = latest['volume']
        volume_ratio = current_volume / ema_volume
        
        # Phase 1.8: Price action strength filter
        candle_strength = self.analyze_candle_strength(latest)
        
        # Get PDH/PDL for confluence check
        pdh, pdl = self.get_pdh_pdl(ticker)
        
        # ========================================
        # BULL BREAKOUT: Close above resistance
        # ========================================
        if latest['close'] > resistance and volume_ratio >= self.volume_multiplier:
            # Phase 1.8: Filter weak bull candles
            if candle_strength['direction'] != 'bull' or not candle_strength['is_strong']:
                return None
            
            # Phase 1.8: Breakout confirmation (wait N bars)
            if self.min_bars_since_breakout > 0:
                # Check if resistance was broken in previous bars
                recent_bars = bars[-(self.min_bars_since_breakout + 1):-1]
                if recent_bars and all(bar['close'] <= resistance for bar in recent_bars):
                    # This is the initial break â€” wait for confirmation
                    return None
            
            entry = latest['close']
            stop = entry - (atr * self.atr_stop_multiplier)
            risk = entry - stop
            
            # â­ Issue #2 Fix: Calculate T1 and T2 targets
            t1_reward = risk * self.t1_reward_ratio
            t2_reward = risk * self.t2_reward_ratio
            t1_price = entry + t1_reward
            t2_price = entry + t2_reward
            
            # Maintain original 'target' for backwards compatibility (use T2)
            target = t2_price
            reward = t2_reward
            
            # Phase 1.8: PDH confluence check
            pdh_confluence = False
            if pdh is not None and abs(resistance - pdh) / pdh < 0.01:
                pdh_confluence = True
            
            # Quality filters
            confidence = self._calculate_confidence(
                volume_ratio=volume_ratio,
                breakout_strength=(entry - resistance) / resistance,
                atr_pct=atr / entry,
                signal_type='BULL',
                candle_strength=candle_strength,
                pdh_pdl_confluence=pdh_confluence
            )
            
            if confidence < 50:
                return None
            
            return {
                'signal': 'BUY',
                'entry': round(entry, 2),
                'stop': round(stop, 2),
                'target': round(target, 2),  # T2 for backwards compatibility
                't1': round(t1_price, 2),    # â­ NEW: T1 target (1.5R)
                't2': round(t2_price, 2),    # â­ NEW: T2 target (2.5R)
                't1_r': self.t1_reward_ratio,
                't2_r': self.t2_reward_ratio,
                'risk': round(risk, 2),
                'reward': round(reward, 2),  # T2 reward
                'risk_reward': round(reward / risk, 2),  # T2 R:R
                'atr': round(atr, 2),
                'volume_ratio': round(volume_ratio, 2),
                'volume_multiple': round(volume_ratio, 1),  # For analytics
                'confidence': confidence,
                'reason': (
                    f'Breakout above ${resistance:.2f} with {volume_ratio:.1f}x volume'
                    f'{" (PDH confluence)" if pdh_confluence else ""}'
                ),
                'type': 'BREAKOUT',
                'candle_body_pct': candle_strength['body_pct'],
                'timestamp': latest.get('datetime', datetime.now())
            }
        
        # =========================================
        # BEAR BREAKDOWN: Close below support
        # =========================================
        elif latest['close'] < support and volume_ratio >= self.volume_multiplier:
            # Phase 1.8: Filter weak bear candles
            if candle_strength['direction'] != 'bear' or not candle_strength['is_strong']:
                return None
            
            # Phase 1.8: Breakout confirmation
            if self.min_bars_since_breakout > 0:
                recent_bars = bars[-(self.min_bars_since_breakout + 1):-1]
                if recent_bars and all(bar['close'] >= support for bar in recent_bars):
                    return None
            
            entry = latest['close']
            stop = entry + (atr * self.atr_stop_multiplier)
            risk = stop - entry
            
            # â­ Issue #2 Fix: Calculate T1 and T2 targets
            t1_reward = risk * self.t1_reward_ratio
            t2_reward = risk * self.t2_reward_ratio
            t1_price = entry - t1_reward
            t2_price = entry - t2_reward
            
            # Maintain original 'target' for backwards compatibility
            target = t2_price
            reward = t2_reward
            
            # Phase 1.8: PDL confluence check
            pdl_confluence = False
            if pdl is not None and abs(support - pdl) / pdl < 0.01:
                pdl_confluence = True
            
            confidence = self._calculate_confidence(
                volume_ratio=volume_ratio,
                breakout_strength=(support - entry) / support,
                atr_pct=atr / entry,
                signal_type='BEAR',
                candle_strength=candle_strength,
                pdh_pdl_confluence=pdl_confluence
            )
            
            if confidence < 50:
                return None
            
            return {
                'signal': 'SELL',
                'entry': round(entry, 2),
                'stop': round(stop, 2),
                'target': round(target, 2),  # T2 for backwards compatibility
                't1': round(t1_price, 2),    # â­ NEW: T1 target (1.5R)
                't2': round(t2_price, 2),    # â­ NEW: T2 target (2.5R)
                't1_r': self.t1_reward_ratio,
                't2_r': self.t2_reward_ratio,
                'risk': round(risk, 2),
                'reward': round(reward, 2),  # T2 reward
                'risk_reward': round(reward / risk, 2),  # T2 R:R
                'atr': round(atr, 2),
                'volume_ratio': round(volume_ratio, 2),
                'volume_multiple': round(volume_ratio, 1),
                'confidence': confidence,
                'reason': (
                    f'Breakdown below ${support:.2f} with {volume_ratio:.1f}x volume'
                    f'{" (PDL confluence)" if pdl_confluence else ""}'
                ),
                'type': 'BREAKDOWN',
                'candle_body_pct': candle_strength['body_pct'],
                'timestamp': latest.get('datetime', datetime.now())
            }
        
        return None
    
    def detect_retest_entry(self, bars: List[Dict], breakout_level: float, 
                           breakout_type: str, ticker: str = "unknown") -> Optional[Dict]:
        """
        Detect retest of a previous breakout level (higher probability entry).
        
        Phase 1.8: Added price action strength filter for retest entries.
        Issue #2: Added T1/T2 split targets.
        
        Args:
            bars: List of OHLCV bars
            breakout_level: Previous breakout/breakdown level
            breakout_type: 'BULL' or 'BEAR'
            ticker: Stock ticker
        
        Returns:
            Signal dict if retest entry detected, None otherwise
        """
        if len(bars) < 3:
            return None
        
        latest = bars[-1]
        atr = self.calculate_atr(bars, ticker)
        ema_volume = self.calculate_ema_volume(bars[:-1])
        
        if atr == 0 or ema_volume == 0:
            return None
        
        volume_ratio = latest['volume'] / ema_volume
        candle_strength = self.analyze_candle_strength(latest)
        
        # Define retest zone (within 0.5 ATR of breakout level)
        retest_tolerance = atr * 0.5
        
        # BULL RETEST: Price comes back to test breakout level from above
        if breakout_type == 'BULL':
            in_retest_zone = abs(latest['low'] - breakout_level) <= retest_tolerance
            
            # Phase 1.8: Require strong bull candle for retest
            if not (in_retest_zone and
                    candle_strength['direction'] == 'bull' and
                    candle_strength['is_strong'] and
                    volume_ratio >= 1.5):


                return None
            
            entry = latest['close']
            stop = breakout_level - (atr * self.atr_stop_multiplier)
            risk = entry - stop
            
            # â­ Issue #2 Fix: T1/T2 targets
            t1_reward = risk * self.t1_reward_ratio
            t2_reward = risk * self.t2_reward_ratio
            t1_price = entry + t1_reward
            t2_price = entry + t2_reward
            target = t2_price
            reward = t2_reward
            
            confidence = self._calculate_confidence(
                volume_ratio=volume_ratio,
                breakout_strength=0.02,
                atr_pct=atr / entry,
                signal_type='BULL',
                candle_strength=candle_strength,
                pdh_pdl_confluence=False
            ) + 10  # Retest bonus
            
            return {
                'signal': 'BUY',
                'entry': round(entry, 2),
                'stop': round(stop, 2),
                'target': round(target, 2),
                't1': round(t1_price, 2),
                't2': round(t2_price, 2),
                't1_r': self.t1_reward_ratio,
                't2_r': self.t2_reward_ratio,
                'risk': round(risk, 2),
                'reward': round(reward, 2),
                'risk_reward': round(reward / risk, 2),
                'atr': round(atr, 2),
                'volume_ratio': round(volume_ratio, 2),
                'volume_multiple': round(volume_ratio, 1),
                'confidence': min(confidence, 95),
                'reason': f'Retest of ${breakout_level:.2f} breakout with {volume_ratio:.1f}x volume',
                'type': 'RETEST',
                'candle_body_pct': candle_strength['body_pct'],
                'timestamp': latest.get('datetime', datetime.now())
            }
        
        # BEAR RETEST: Price comes back to test breakdown level from below
        elif breakout_type == 'BEAR':
            in_retest_zone = abs(latest['high'] - breakout_level) <= retest_tolerance
            
            # Phase 1.8: Require strong bear candle for retest
            if not (in_retest_zone and
                    candle_strength['direction'] == 'bear' and
                    candle_strength['is_strong'] and       # ✅ Added closing bracket
                    volume_ratio >= 1.5):

                return None
            
            entry = latest['close']
            stop = breakout_level + (atr * self.atr_stop_multiplier)
            risk = stop - entry
            
            # â­ Issue #2 Fix: T1/T2 targets
            t1_reward = risk * self.t1_reward_ratio
            t2_reward = risk * self.t2_reward_ratio
            t1_price = entry - t1_reward
            t2_price = entry - t2_reward
            target = t2_price
            reward = t2_reward
            
            confidence = self._calculate_confidence(
                volume_ratio=volume_ratio,
                breakout_strength=0.02,
                atr_pct=atr / entry,
                signal_type='BEAR',
                candle_strength=candle_strength,
                pdh_pdl_confluence=False
            ) + 10
            
            return {
                'signal': 'SELL',
                'entry': round(entry, 2),
                'stop': round(stop, 2),
                'target': round(target, 2),
                't1': round(t1_price, 2),
                't2': round(t2_price, 2),
                't1_r': self.t1_reward_ratio,
                't2_r': self.t2_reward_ratio,
                'risk': round(risk, 2),
                'reward': round(reward, 2),
                'risk_reward': round(reward / risk, 2),
                'atr': round(atr, 2),
                'volume_ratio': round(volume_ratio, 2),
                'volume_multiple': round(volume_ratio, 1),
                'confidence': min(confidence, 95),
                'reason': f'Retest of ${breakout_level:.2f} breakdown with {volume_ratio:.1f}x volume',
                'type': 'RETEST',
                'candle_body_pct': candle_strength['body_pct'],
                'timestamp': latest.get('datetime', datetime.now())
            }
        
        return None
    
    def _calculate_confidence(self, volume_ratio: float, breakout_strength: float, 
                            atr_pct: float, signal_type: str,
                            candle_strength: Dict = None,
                            pdh_pdl_confluence: bool = False) -> int:
        """
        Calculate confidence score (0-100) for breakout signal.
        
        Phase 1.8: Enhanced with candle strength and PDH/PDL confluence factors.
        
        Factors:
          - Volume ratio: Higher volume = higher confidence (0-30 pts)
          - Breakout strength: Stronger break = higher confidence (0-20 pts)
          - ATR percentage: Lower volatility = higher confidence (0-10 pts)
          - Candle body%: Stronger candle = higher confidence (0-10 pts)
          - PDH/PDL confluence: At key level = bonus confidence (+10 pts)
        """
        confidence = 50  # Base confidence
        
        # Volume factor (0-30 points)
        if volume_ratio >= 3.0:
            confidence += 30
        elif volume_ratio >= 2.5:
            confidence += 20
        elif volume_ratio >= 2.0:
            confidence += 10
        
        # Breakout strength (0-20 points)
        if breakout_strength >= 0.03:  # 3%+ breakout
            confidence += 20
        elif breakout_strength >= 0.02:  # 2%+ breakout
            confidence += 15
        elif breakout_strength >= 0.01:  # 1%+ breakout
            confidence += 10
        
        # ATR percentage - lower is better (0-10 points)
        if atr_pct < 0.02:  # Less than 2% ATR
            confidence += 10
        elif atr_pct < 0.03:
            confidence += 5
        
        # Phase 1.8: Candle strength factor (0-10 points)
        if candle_strength:
            body_pct = candle_strength['body_pct']
            if body_pct >= 0.7:  # 70%+ body (very strong)
                confidence += 10
            elif body_pct >= 0.6:  # 60%+ body
                confidence += 7
            elif body_pct >= 0.5:  # 50%+ body
                confidence += 5
            elif body_pct >= 0.4:  # 40%+ body (minimum)
                confidence += 3
        
        # Phase 1.8: PDH/PDL confluence bonus (+10 points)
        if pdh_pdl_confluence:
            confidence += 10
        
        return min(confidence, 100)
    
    def calculate_position_size(self, account_balance: float, risk_percent: float, 
                              entry: float, stop: float) -> int:
        """
        Calculate position size based on account risk.
        
        Args:
            account_balance: Total account value
            risk_percent: Risk per trade (e.g., 1.0 = 1%)
            entry: Entry price
            stop: Stop loss price
        
        Returns:
            Number of shares to trade
        """
        risk_amount = account_balance * (risk_percent / 100)
        risk_per_share = abs(entry - stop)
        
        if risk_per_share == 0:
            return 0
        
        shares = int(risk_amount / risk_per_share)
        return max(shares, 0)


def format_signal_message(ticker: str, signal: Dict) -> str:
    """
    Format breakout signal for Discord/console output.
    
    Args:
        ticker: Stock ticker
        signal: Signal dict from detect_breakout()
    
    Returns:
        Formatted message string
    """
    emoji = "ðŸ“ˆ" if signal['signal'] == 'BUY' else "ðŸ“‰"
    
    # â­ Issue #2 Fix: Show T1 and T2 targets
    msg = (
        f"{emoji} **{signal['signal']} {ticker}** @ ${signal['entry']}\n"
        f"Stop: ${signal['stop']}\n"
    )
    
    # Show split targets if available
    if 't1' in signal and 't2' in signal:
        msg += (
            f"T1: ${signal['t1']} ({signal.get('t1_r', 1.5)}R - 50%)\n"
            f"T2: ${signal['t2']} ({signal.get('t2_r', 2.5)}R - 50%)\n"
        )
    else:
        msg += f"Target: ${signal['target']}\n"
    
    msg += (
        f"Risk: ${signal['risk']} | Max Reward: ${signal['reward']} | R:R {signal['risk_reward']}:1\n"
        f"Volume: {signal['volume_ratio']}x avg | ATR: ${signal['atr']}\n"
        f"Confidence: {signal['confidence']}% - {signal['reason']}"
    )
    
    # Phase 1.8: Add candle strength info if available
    if 'candle_body_pct' in signal:
        msg += f"\nCandle Body: {signal['candle_body_pct']*100:.0f}%"
    
    return msg


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    # Example: Test with sample bars
    detector = BreakoutDetector(
        lookback_bars=12,
        volume_multiplier=2.0,
        atr_stop_multiplier=1.5,
        risk_reward_ratio=2.0,
        t1_reward_ratio=1.5,
        t2_reward_ratio=2.5,
        min_candle_body_pct=0.4,
        min_bars_since_breakout=1
    )
    
    # Sample bars (OHLCV)
    sample_bars = [
        {'datetime': datetime.now(), 'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'volume': 1000000},
        {'datetime': datetime.now(), 'open': 100.5, 'high': 102, 'low': 100, 'close': 101, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 101, 'high': 103, 'low': 100.5, 'close': 102, 'volume': 1200000},
        {'datetime': datetime.now(), 'open': 102, 'high': 104, 'low': 101.5, 'close': 103, 'volume': 1300000},
        {'datetime': datetime.now(), 'open': 103, 'high': 104.5, 'low': 102, 'close': 103.5, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 103.5, 'high': 105, 'low': 103, 'close': 104, 'volume': 1000000},
        {'datetime': datetime.now(), 'open': 104, 'high': 105.5, 'low': 103.5, 'close': 104.5, 'volume': 1050000},
        {'datetime': datetime.now(), 'open': 104.5, 'high': 106, 'low': 104, 'close': 105, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 105, 'high': 106.5, 'low': 104.5, 'close': 105.5, 'volume': 1150000},
        {'datetime': datetime.now(), 'open': 105.5, 'high': 107, 'low': 105, 'close': 106, 'volume': 1200000},
        {'datetime': datetime.now(), 'open': 106, 'high': 107.5, 'low': 105.5, 'close': 106.5, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 106.5, 'high': 108, 'low': 106, 'close': 107, 'volume': 1000000},
        # BREAKOUT BAR: Price breaks above 108 with 2.5x volume + strong bull candle
        {'datetime': datetime.now(), 'open': 107, 'high': 110, 'low': 106.5, 'close': 109.5, 'volume': 2500000},
    ]
    
    signal = detector.detect_breakout(sample_bars, ticker="TEST")
    
    if signal:
        print("\n" + "="*60)
        print("BREAKOUT DETECTED!")
        print("="*60)
        print(format_signal_message("TEST", signal))
        print("="*60)
        
        # Calculate position size for $10,000 account risking 1%
        shares = detector.calculate_position_size(
            account_balance=10000,
            risk_percent=1.0,
            entry=signal['entry'],
            stop=signal['stop']
        )
        print(f"\nPosition Size: {shares} shares")
        print(f"Total Risk: ${shares * signal['risk']:.2f}")
        print(f"T1 Profit (50%): ${shares * 0.5 * (signal['t1'] - signal['entry']):.2f}")
        print(f"T2 Profit (50%): ${shares * 0.5 * (signal['t2'] - signal['entry']):.2f}")
        print(f"Max Total Profit: ${shares * signal['reward']:.2f}")
    else:
        print("No breakout signal detected")

