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

Phase 1.17 Fixes (Mar 10, 2026):
  - calculate_support_resistance() now anchors to 9:30 session high/low via
    get_session_levels() so breakouts against the day's true range are detected
    regardless of the rolling lookback window size.
  - min_bars_since_breakout default: 1 -> 0  (1-bar confirmation delay is fatal
    for 0DTE same-day explosive plays; first break IS the signal)
  - lookback_bars default: 12 -> 20  (20 min of 1m context is more appropriate)
  - session_anchored flag added to signal dict for log transparency

Mar 27, 2026 Fixes:
  - __init__: print() -> logger.info() for confirmation bars line.
    Raw stdout bypassed Railway structured logging entirely (no timestamp,
    no log level). Now captured consistently with all other [BREAKOUT] logs.

Risk Management:
  - Stop: ATR-based dynamic stop (typically 1.5-2x ATR)
  - T1: 1.5R (take 50% position, secure gains)
  - T2: 2.5R (let 50% run, maximize winners)
  - Max risk per trade: 1-2% of account
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import statistics
import logging
logger = logging.getLogger(__name__)


class BreakoutDetector:
    """Detect high-probability breakout entries with volume confirmation."""

    def __init__(self,
                 lookback_bars: int = 20,
                 volume_multiplier: float = 2.0,
                 atr_period: int = 14,
                 atr_stop_multiplier: float = 1.5,
                 risk_reward_ratio: float = 2.0,
                 t1_reward_ratio: float = 1.5,
                 t2_reward_ratio: float = 2.5,
                 min_candle_body_pct: float = 0.4,
                 min_bars_since_breakout: int = 0):
        """
        Args:
            lookback_bars:           Bars for rolling support/resistance (default 20 = 20 min on 1m)
            volume_multiplier:       Volume must be Nx EMA avg for confirmation
            atr_period:              Period for ATR calculation
            atr_stop_multiplier:     Stop distance = ATR * multiplier
            risk_reward_ratio:       Default target (backwards compat)
            t1_reward_ratio:         T1 target ratio (1.5R = take 50% profit)
            t2_reward_ratio:         T2 target ratio (2.5R = let 50% run)
            min_candle_body_pct:     Min candle body% for strong price action (0.4 = 40%)
            min_bars_since_breakout: Phase 1.17: default 0 (was 1). 0 = signal on
                                     the first break bar. Set to 1 only if you want
                                     confirmation-bar entries (swing mode).
        """
        self.lookback_bars           = lookback_bars
        self.volume_multiplier       = volume_multiplier
        self.atr_period              = atr_period
        self.atr_stop_multiplier     = atr_stop_multiplier
        self.risk_reward_ratio       = risk_reward_ratio
        self.t1_reward_ratio         = t1_reward_ratio
        self.t2_reward_ratio         = t2_reward_ratio
        self.min_candle_body_pct     = min_candle_body_pct
        self.min_bars_since_breakout = min_bars_since_breakout

        # ATR cache: ticker -> (atr, bars_count)
        self._atr_cache: Dict[str, Tuple[float, int]] = {}

        # PDH/PDL cache (refreshed daily)
        self._pdh_pdl_cache: Dict[str, Tuple[float, float]] = {}

        logger.info(f"[BREAKOUT] Split targets: T1={t1_reward_ratio}R (50%), T2={t2_reward_ratio}R (50%)")
        logger.info(f"[BREAKOUT] Confirmation bars: {min_bars_since_breakout} "
                    f"({'first-break signal' if min_bars_since_breakout == 0 else 'wait-for-confirm'})")
        logger.info(f"[BREAKOUT] Lookback: {lookback_bars} bars | Session anchoring: ENABLED")

    # =================================================================
    # ATR
    # =================================================================

    def calculate_atr(self, bars: List[Dict], ticker: str = "unknown") -> float:
        """
        Calculate Average True Range for dynamic stops.
        Cached by bar count to avoid redundant calculations.
        """
        if len(bars) < 2:
            return 0.0

        bars_count = len(bars)
        if ticker in self._atr_cache:
            cached_atr, cached_count = self._atr_cache[ticker]
            if cached_count == bars_count:
                return cached_atr

        true_ranges = []
        for i in range(1, len(bars)):
            high       = bars[i]['high']
            low        = bars[i]['low']
            prev_close = bars[i - 1]['close']
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low  - prev_close)
            )
            true_ranges.append(tr)

        atr_bars = (true_ranges[-self.atr_period:]
                    if len(true_ranges) >= self.atr_period
                    else true_ranges)
        atr = statistics.mean(atr_bars) if atr_bars else 0.0
        self._atr_cache[ticker] = (atr, bars_count)
        return atr

    # =================================================================
    # PDH / PDL
    # =================================================================

    def get_pdh_pdl(self, ticker: str, as_of_date=None) -> Tuple[Optional[float], Optional[float]]:
        """Get previous day high/low from data_manager (cached per ticker+date).

        as_of_date: pass session date in backtests so each fold fetches its own PDH/PDL.
        """
        cache_key = (ticker, as_of_date)
        if cache_key in self._pdh_pdl_cache:
            return self._pdh_pdl_cache[cache_key]
        try:
            from app.data.data_manager import data_manager
            prev_day = data_manager.get_previous_day_ohlc(ticker, as_of_date=as_of_date)
            if prev_day and 'high' in prev_day and 'low' in prev_day:
                pdh = prev_day['high']
                pdl = prev_day['low']
                self._pdh_pdl_cache[cache_key] = (pdh, pdl)
                return pdh, pdl
        except Exception as e:
            logger.info(f"[BREAKOUT] PDH/PDL fetch error for {ticker}: {e}")
        return None, None

    def clear_pdh_pdl_cache(self) -> None:
        """Clear PDH/PDL cache (called at end of day)."""
        self._pdh_pdl_cache.clear()

    # =================================================================
    # SUPPORT / RESISTANCE  (Phase 1.17: session-anchored)
    # =================================================================

    def calculate_support_resistance(
        self, bars: List[Dict], ticker: str = "unknown", as_of_date=None
    ) -> Tuple[float, float, str, str]:
        """
        Calculate support and resistance levels.

        Phase 1.17 — Session Anchoring:
          1. Compute rolling intraday levels from last N bars
          2. Pull 9:30 session high/low via get_session_levels()
          3. Session high becomes resistance when price is within 0.5% of it
             OR when it is higher than the rolling resistance (true day high)
          4. Session low becomes support when price is within 0.5% of it
             OR when it is lower than the rolling support (true day low)
          5. PDH/PDL confluence still applies on top

        Fixes (this commit):
          - resistance_source and support_source are now initialized immediately
            after the rolling levels are set, preventing NameError when the
            session-anchoring try block runs without updating them.
          - Removed duplicate get_pdh_pdl() call that appeared both before and
            after the session-anchoring block (second call was redundant).
        """
        if not bars:
            return 0.0, 0.0, 'rolling', 'rolling'

        lookback = (bars[-self.lookback_bars:]
                    if len(bars) >= self.lookback_bars
                    else bars)

        # Step 1: rolling intraday levels
        resistance = max(bar['high'] for bar in lookback)
        support    = min(bar['low']  for bar in lookback)

        # Initialize source labels immediately (fixes NameError)
        resistance_source = 'rolling'
        support_source    = 'rolling'

        # Step 2: session-anchoring via opening_range.get_session_levels()
        try:
            from app.signals.opening_range import get_session_levels
            session = get_session_levels(ticker)
            if session:
                session_high  = session['session_high']
                session_low   = session['session_low']
                current_price = bars[-1]['close']

                near_session_high = (abs(current_price - session_high) / session_high) < 0.005
                if session_high >= resistance or near_session_high:
                    resistance        = session_high
                    resistance_source = 'session'

                near_session_low = (abs(current_price - session_low) / session_low) < 0.005
                if session_low <= support or near_session_low:
                    support        = session_low
                    support_source = 'session'
        except Exception:
            pass

        # Step 3: PDH/PDL confluence (single fetch — removed duplicate)
        pdh, pdl = self.get_pdh_pdl(ticker, as_of_date=as_of_date)
        if pdh is not None:
            if abs(pdh - resistance) / resistance < 0.02:
                resistance        = pdh
                resistance_source = 'pdh'
        if pdl is not None:
            if abs(pdl - support) / support < 0.02:
                support        = pdl
                support_source = 'pdl'

        return support, resistance, support_source, resistance_source

    # =================================================================
    # VOLUME
    # =================================================================

    def calculate_ema_volume(self, bars: List[Dict], period: int = None) -> float:
        """EMA of volume — more responsive to recent spikes than SMA."""
        if not bars:
            return 0.0
        period  = period or self.lookback_bars
        lookback = bars[-period:] if len(bars) >= period else bars
        if not lookback:
            return 0.0
        multiplier = 2.0 / (period + 1)
        ema = lookback[0]['volume']
        for bar in lookback[1:]:
            ema = (bar['volume'] * multiplier) + (ema * (1 - multiplier))
        return ema

    def calculate_average_volume(self, bars: List[Dict]) -> float:
        """Deprecated: kept for backwards compat. Calls calculate_ema_volume()."""
        return self.calculate_ema_volume(bars)

    # =================================================================
    # CANDLE STRENGTH
    # =================================================================

    def analyze_candle_strength(self, bar: Dict) -> Dict:
        """
        Assess candle strength using 3 entry patterns (BOS+FVG strategy):
          Type 1 — Marubozu: body ≥80% of range, wicks ≤10% both sides
          Type 2 — Hammer/Shooting Star: rejection wick ≥2x body, tiny opposing wick
          Type 3 — Engulfing/Strong Body: body ≥ min_candle_body_pct, close in directional third
        """
        open_price  = bar['open']
        close_price = bar['close']
        high        = bar['high']
        low         = bar['low']
        total_range = high - low

        if total_range == 0:
            return {
                'body_pct': 0.0, 'is_strong': False,
                'has_rejection': False, 'candle_type': 'DOJI',
                'direction': 'neutral', 'upper_wick_pct': 0.0, 'lower_wick_pct': 0.0
            }

        body_size      = abs(close_price - open_price)
        body_pct       = body_size / total_range
        direction      = 'bull' if close_price >= open_price else 'bear'
        body_top       = max(open_price, close_price)
        body_bottom    = min(open_price, close_price)
        upper_wick     = high - body_top
        lower_wick     = body_bottom - low
        upper_wick_pct = upper_wick / total_range
        lower_wick_pct = lower_wick / total_range

        # Type 1: Marubozu
        is_marubozu = (body_pct >= 0.80 and upper_wick_pct <= 0.10 and lower_wick_pct <= 0.10)

        # Type 2: Hammer (bull) / Shooting Star (bear)
        if direction == 'bull':
            has_rejection  = body_size > 0 and lower_wick >= 2.0 * body_size and upper_wick_pct <= 0.10
            candle_type_t2 = 'HAMMER'
        else:
            has_rejection  = body_size > 0 and upper_wick >= 2.0 * body_size and lower_wick_pct <= 0.10
            candle_type_t2 = 'SHOOTING_STAR'

        # Type 3: Engulfing / Strong Body
        close_position = (close_price - low) / total_range
        if direction == 'bull':
            is_engulfing = body_pct >= self.min_candle_body_pct and close_position >= 0.70
        else:
            is_engulfing = body_pct >= self.min_candle_body_pct and close_position <= 0.30

        if is_marubozu:
            candle_type = 'MARUBOZU'
        elif has_rejection:
            candle_type = candle_type_t2
        elif is_engulfing:
            candle_type = 'ENGULFING'
        else:
            candle_type = 'WEAK'

        return {
            'body_pct':       round(body_pct, 2),
            'is_strong':      is_marubozu or has_rejection or is_engulfing,
            'has_rejection':  has_rejection,
            'is_marubozu':    is_marubozu,
            'is_engulfing':   is_engulfing,
            'candle_type':    candle_type,
            'direction':      direction,
            'upper_wick_pct': round(upper_wick_pct, 2),
            'lower_wick_pct': round(lower_wick_pct, 2),
        }

    # =================================================================
    # MAIN DETECTION
    # =================================================================

    def detect_breakout(
        self, bars: List[Dict], ticker: str = "unknown", as_of_date=None
    ) -> Optional[Dict]:
        """
        Detect breakout/breakdown entry signal.

        Phase 1.17 changes:
          - support/resistance now session-anchored (see calculate_support_resistance)
          - min_bars_since_breakout default is 0 (first-break signal for 0DTE plays)
          - session_anchored flag in returned dict
        """
        if len(bars) < self.lookback_bars:
            return None

        latest      = bars[-1]
        support, resistance, support_source, resistance_source = self.calculate_support_resistance(bars[:-1], ticker, as_of_date=as_of_date)
        ema_volume  = self.calculate_ema_volume(bars[:-1])
        atr         = self.calculate_atr(bars, ticker)

        if ema_volume == 0 or atr == 0:
            return None

        current_volume  = latest['volume']
        volume_ratio    = current_volume / ema_volume
        candle_strength = self.analyze_candle_strength(latest)
        pdh, pdl        = self.get_pdh_pdl(ticker, as_of_date=as_of_date)

        # Detect whether session levels were used
        session_anchored = (resistance_source == 'session' or support_source == 'session')

        # ============================================================
        # BULL BREAKOUT
        # ============================================================
        if latest['close'] > resistance and volume_ratio >= self.volume_multiplier:

            if candle_strength['direction'] != 'bull' or not candle_strength['is_strong']:
                return None

            # Phase 1.17: min_bars_since_breakout=0 skips this block entirely
            if self.min_bars_since_breakout > 0:
                recent_bars = bars[-(self.min_bars_since_breakout + 1):-1]
                if recent_bars and all(bar['close'] <= resistance for bar in recent_bars):
                    return None

            entry    = latest['close']
            stop     = entry - (atr * self.atr_stop_multiplier)
            risk     = entry - stop
            t1_price = entry + risk * self.t1_reward_ratio
            t2_price = entry + risk * self.t2_reward_ratio
            reward   = risk * self.t2_reward_ratio

            pdh_confluence = (pdh is not None and
                              abs(resistance - pdh) / pdh < 0.01)

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

            reason = (f'Breakout above ${resistance:.2f} with {volume_ratio:.1f}x volume'
                      f'{" (PDH confluence)" if pdh_confluence else ""}'
                      f'{" [session-anchored]" if session_anchored else ""}')

            return {
                'signal':           'BUY',
                'entry':            round(entry, 2),
                'stop':             round(stop, 2),
                'target':           round(t2_price, 2),
                't1':               round(t1_price, 2),
                't2':               round(t2_price, 2),
                't1_r':             self.t1_reward_ratio,
                't2_r':             self.t2_reward_ratio,
                'risk':             round(risk, 2),
                'reward':           round(reward, 2),
                'risk_reward':      round(reward / risk, 2),
                'atr':              round(atr, 2),
                'volume_ratio':     round(volume_ratio, 2),
                'volume_multiple':  round(volume_ratio, 1),
                'confidence':       confidence,
                'reason':           reason,
                'type':             'BREAKOUT',
                'candle_body_pct':  candle_strength['body_pct'],
                'session_anchored': session_anchored,
                'resistance_used':  round(resistance, 2),
                'support_used':     round(support, 2),
                'timestamp':        latest.get('datetime', datetime.now())
            }

        # ============================================================
        # BEAR BREAKDOWN
        # ============================================================
        elif latest['close'] < support and volume_ratio >= self.volume_multiplier:

            if candle_strength['direction'] != 'bear' or not candle_strength['is_strong']:
                return None

            if self.min_bars_since_breakout > 0:
                recent_bars = bars[-(self.min_bars_since_breakout + 1):-1]
                if recent_bars and all(bar['close'] >= support for bar in recent_bars):
                    return None

            entry    = latest['close']
            stop     = entry + (atr * self.atr_stop_multiplier)
            risk     = stop - entry
            t1_price = entry - risk * self.t1_reward_ratio
            t2_price = entry - risk * self.t2_reward_ratio
            reward   = risk * self.t2_reward_ratio

            pdl_confluence = (pdl is not None and
                              abs(support - pdl) / pdl < 0.01)

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

            reason = (f'Breakdown below ${support:.2f} with {volume_ratio:.1f}x volume'
                      f'{" (PDL confluence)" if pdl_confluence else ""}'
                      f'{" [session-anchored]" if session_anchored else ""}')

            return {
                'signal':           'SELL',
                'entry':            round(entry, 2),
                'stop':             round(stop, 2),
                'target':           round(t2_price, 2),
                't1':               round(t1_price, 2),
                't2':               round(t2_price, 2),
                't1_r':             self.t1_reward_ratio,
                't2_r':             self.t2_reward_ratio,
                'risk':             round(risk, 2),
                'reward':           round(reward, 2),
                'risk_reward':      round(reward / risk, 2),
                'atr':              round(atr, 2),
                'volume_ratio':     round(volume_ratio, 2),
                'volume_multiple':  round(volume_ratio, 1),
                'confidence':       confidence,
                'reason':           reason,
                'type':             'BREAKDOWN',
                'candle_body_pct':  candle_strength['body_pct'],
                'session_anchored': session_anchored,
                'resistance_used':  round(resistance, 2),
                'support_used':     round(support, 2),
                'timestamp':        latest.get('datetime', datetime.now())
            }

        return None

    # =================================================================
    # RETEST ENTRY
    # =================================================================

    def detect_retest_entry(
        self, bars: List[Dict], breakout_level: float,
        breakout_type: str, ticker: str = "unknown"
    ) -> Optional[Dict]:
        """
        Detect retest of a previous breakout level (higher probability entry).
        T1/T2 split targets applied.
        """
        if len(bars) < 3:
            return None

        latest     = bars[-1]
        atr        = self.calculate_atr(bars, ticker)
        ema_volume = self.calculate_ema_volume(bars[:-1])

        if atr == 0 or ema_volume == 0:
            return None

        volume_ratio    = latest['volume'] / ema_volume
        candle_strength = self.analyze_candle_strength(latest)
        retest_tolerance = atr * 0.5

        if breakout_type == 'BULL':
            in_retest_zone = abs(latest['low'] - breakout_level) <= retest_tolerance
            if not (in_retest_zone and
                    candle_strength['direction'] == 'bull' and
                    candle_strength['is_strong'] and
                    volume_ratio >= 1.5):
                return None

            entry    = latest['close']
            stop     = breakout_level - (atr * self.atr_stop_multiplier)
            risk     = entry - stop
            t1_price = entry + risk * self.t1_reward_ratio
            t2_price = entry + risk * self.t2_reward_ratio
            reward   = risk * self.t2_reward_ratio

            confidence = self._calculate_confidence(
                volume_ratio=volume_ratio,
                breakout_strength=0.02,
                atr_pct=atr / entry,
                signal_type='BULL',
                candle_strength=candle_strength,
                pdh_pdl_confluence=False
            ) + 10

            return {
                'signal':          'BUY',
                'entry':           round(entry, 2),
                'stop':            round(stop, 2),
                'target':          round(t2_price, 2),
                't1':              round(t1_price, 2),
                't2':              round(t2_price, 2),
                't1_r':            self.t1_reward_ratio,
                't2_r':            self.t2_reward_ratio,
                'risk':            round(risk, 2),
                'reward':          round(reward, 2),
                'risk_reward':     round(reward / risk, 2),
                'atr':             round(atr, 2),
                'volume_ratio':    round(volume_ratio, 2),
                'volume_multiple': round(volume_ratio, 1),
                'confidence':      min(confidence, 95),
                'reason':          f'Retest of ${breakout_level:.2f} breakout with {volume_ratio:.1f}x volume',
                'type':            'RETEST',
                'candle_body_pct': candle_strength['body_pct'],
                'session_anchored': False,
                'timestamp':       latest.get('datetime', datetime.now())
            }

        elif breakout_type == 'BEAR':
            in_retest_zone = abs(latest['high'] - breakout_level) <= retest_tolerance
            if not (in_retest_zone and
                    candle_strength['direction'] == 'bear' and
                    candle_strength['is_strong'] and
                    volume_ratio >= 1.5):
                return None

            entry    = latest['close']
            stop     = breakout_level + (atr * self.atr_stop_multiplier)
            risk     = stop - entry
            t1_price = entry - risk * self.t1_reward_ratio
            t2_price = entry - risk * self.t2_reward_ratio
            reward   = risk * self.t2_reward_ratio

            confidence = self._calculate_confidence(
                volume_ratio=volume_ratio,
                breakout_strength=0.02,
                atr_pct=atr / entry,
                signal_type='BEAR',
                candle_strength=candle_strength,
                pdh_pdl_confluence=False
            ) + 10

            return {
                'signal':          'SELL',
                'entry':           round(entry, 2),
                'stop':            round(stop, 2),
                'target':          round(t2_price, 2),
                't1':              round(t1_price, 2),
                't2':              round(t2_price, 2),
                't1_r':            self.t1_reward_ratio,
                't2_r':            self.t2_reward_ratio,
                'risk':            round(risk, 2),
                'reward':          round(reward, 2),
                'risk_reward':     round(reward / risk, 2),
                'atr':             round(atr, 2),
                'volume_ratio':    round(volume_ratio, 2),
                'volume_multiple': round(volume_ratio, 1),
                'confidence':      min(confidence, 95),
                'reason':          f'Retest of ${breakout_level:.2f} breakdown with {volume_ratio:.1f}x volume',
                'type':            'RETEST',
                'candle_body_pct': candle_strength['body_pct'],
                'session_anchored': False,
                'timestamp':       latest.get('datetime', datetime.now())
            }

        return None

    # =================================================================
    # CONFIDENCE SCORING
    # =================================================================

    def _calculate_confidence(
        self,
        volume_ratio: float,
        breakout_strength: float,
        atr_pct: float,
        signal_type: str,
        candle_strength: Dict = None,
        pdh_pdl_confluence: bool = False
    ) -> int:
        """
        Confidence score 0-100.

        Factors:
          Volume ratio       0-30 pts
          Breakout strength  0-20 pts
          ATR pct            0-10 pts
          Candle body%       0-10 pts
          PDH/PDL confluence +10 pts bonus
        """
        confidence = 50

        # Volume (0-30)
        if   volume_ratio >= 3.0:  confidence += 30
        elif volume_ratio >= 2.5:  confidence += 20
        elif volume_ratio >= 2.0:  confidence += 10

        # Breakout strength (0-20)
        if   breakout_strength >= 0.03:  confidence += 20
        elif breakout_strength >= 0.02:  confidence += 15
        elif breakout_strength >= 0.01:  confidence += 10

        # ATR pct — lower is better (0-10)
        if   atr_pct < 0.02:  confidence += 10
        elif atr_pct < 0.03:  confidence += 5

        # Candle body (0-10)
        if candle_strength:
            body_pct = candle_strength['body_pct']
            if   body_pct >= 0.7:  confidence += 10
            elif body_pct >= 0.6:  confidence += 7
            elif body_pct >= 0.5:  confidence += 5
            elif body_pct >= 0.4:  confidence += 3

        # PDH/PDL confluence bonus
        if pdh_pdl_confluence:
            confidence += 10

        return min(confidence, 100)

    # =================================================================
    # POSITION SIZING
    # =================================================================

    def calculate_position_size(
        self, account_balance: float, risk_percent: float,
        entry: float, stop: float
    ) -> int:
        """Calculate share count based on account risk."""
        risk_amount    = account_balance * (risk_percent / 100)
        risk_per_share = abs(entry - stop)
        if risk_per_share == 0:
            return 0
        return max(int(risk_amount / risk_per_share), 0)


# =============================================================
# FORMATTING
# =============================================================

def format_signal_message(ticker: str, signal: Dict) -> str:
    """Format breakout signal for Discord/console output."""
    emoji = "\U0001f4c8" if signal['signal'] == 'BUY' else "\U0001f4c9"
    anchored_tag = " [S]" if signal.get('session_anchored') else ""

    msg = (
        f"{emoji} **{signal['signal']} {ticker}{anchored_tag}** @ ${signal['entry']}\n"
        f"Stop: ${signal['stop']}\n"
    )
    if 't1' in signal and 't2' in signal:
        msg += (
            f"T1: ${signal['t1']} ({signal.get('t1_r', 1.5)}R - 50%)\n"
            f"T2: ${signal['t2']} ({signal.get('t2_r', 2.5)}R - 50%)\n"
        )
    else:
        msg += f"Target: ${signal['target']}\n"

    msg += (
        f"Risk: ${signal['risk']} | Reward: ${signal['reward']} | R:R {signal['risk_reward']}:1\n"
        f"Volume: {signal['volume_ratio']}x avg | ATR: ${signal['atr']}\n"
        f"Confidence: {signal['confidence']}% | {signal['reason']}"
    )
    if 'candle_body_pct' in signal:
        msg += f"\nCandle Body: {signal['candle_body_pct']*100:.0f}%"
    if signal.get('session_anchored'):
        msg += (f"\nLevels: R=${signal.get('resistance_used','?')} "
                f"S=${signal.get('support_used','?')} [session-anchored]")
    return msg


# =============================================================
# USAGE EXAMPLE
# =============================================================
if __name__ == "__main__":
    detector = BreakoutDetector(
        lookback_bars=20,
        volume_multiplier=2.0,
        atr_stop_multiplier=1.5,
        t1_reward_ratio=1.5,
        t2_reward_ratio=2.5,
        min_candle_body_pct=0.4,
        min_bars_since_breakout=0
    )

    sample_bars = [
        {'datetime': datetime.now(), 'open': 100,   'high': 101,   'low': 99,    'close': 100.5, 'volume': 1000000},
        {'datetime': datetime.now(), 'open': 100.5, 'high': 102,   'low': 100,   'close': 101,   'volume': 1100000},
        {'datetime': datetime.now(), 'open': 101,   'high': 103,   'low': 100.5, 'close': 102,   'volume': 1200000},
        {'datetime': datetime.now(), 'open': 102,   'high': 104,   'low': 101.5, 'close': 103,   'volume': 1300000},
        {'datetime': datetime.now(), 'open': 103,   'high': 104.5, 'low': 102,   'close': 103.5, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 103.5, 'high': 105,   'low': 103,   'close': 104,   'volume': 1000000},
        {'datetime': datetime.now(), 'open': 104,   'high': 105.5, 'low': 103.5, 'close': 104.5, 'volume': 1050000},
        {'datetime': datetime.now(), 'open': 104.5, 'high': 106,   'low': 104,   'close': 105,   'volume': 1100000},
        {'datetime': datetime.now(), 'open': 105,   'high': 106.5, 'low': 104.5, 'close': 105.5, 'volume': 1150000},
        {'datetime': datetime.now(), 'open': 105.5, 'high': 107,   'low': 105,   'close': 106,   'volume': 1200000},
        {'datetime': datetime.now(), 'open': 106,   'high': 107.5, 'low': 105.5, 'close': 106.5, 'volume': 1100000},
        {'datetime': datetime.now(), 'open': 106.5, 'high': 108,   'low': 106,   'close': 107,   'volume': 1000000},
        {'datetime': datetime.now(), 'open': 107,   'high': 108.5, 'low': 106.5, 'close': 107.5, 'volume': 1050000},
        {'datetime': datetime.now(), 'open': 107.5, 'high': 109,   'low': 107,   'close': 108,   'volume': 1020000},
        {'datetime': datetime.now(), 'open': 108,   'high': 109.5, 'low': 107.5, 'close': 108.5, 'volume': 1030000},
        {'datetime': datetime.now(), 'open': 108.5, 'high': 110,   'low': 108,   'close': 109,   'volume': 1040000},
        {'datetime': datetime.now(), 'open': 109,   'high': 110.5, 'low': 108.5, 'close': 109.5, 'volume': 1050000},
        {'datetime': datetime.now(), 'open': 109.5, 'high': 111,   'low': 109,   'close': 110,   'volume': 1060000},
        {'datetime': datetime.now(), 'open': 110,   'high': 111.5, 'low': 109.5, 'close': 110.5, 'volume': 1070000},
        {'datetime': datetime.now(), 'open': 110.5, 'high': 112,   'low': 110,   'close': 111,   'volume': 1080000},
        # BREAKOUT BAR: price breaks 112 with 2.5x volume + strong bull candle
        {'datetime': datetime.now(), 'open': 111,   'high': 114.5, 'low': 110.5, 'close': 114,   'volume': 2700000},
    ]

    signal = detector.detect_breakout(sample_bars, ticker="TEST")

    if signal:
        logger.info("\n" + "="*60)
        logger.info("BREAKOUT DETECTED!")
        logger.info("="*60)
        logger.info(format_signal_message("TEST", signal))
        logger.info("="*60)
        shares = detector.calculate_position_size(
            account_balance=10000, risk_percent=1.0,
            entry=signal['entry'], stop=signal['stop']
        )
        logger.info(f"\nPosition Size: {shares} shares")
        logger.info(f"Total Risk:    ${shares * signal['risk']:.2f}")
        logger.info(f"T1 Profit:     ${shares * 0.5 * (signal['t1'] - signal['entry']):.2f}")
        logger.info(f"T2 Profit:     ${shares * 0.5 * (signal['t2'] - signal['entry']):.2f}")
    else:
        logger.info("No breakout signal detected")
