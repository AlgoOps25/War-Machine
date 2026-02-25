"""
Signal Validator - Multi-Indicator Confirmation Engine

Enhances CFW6 signals with additional technical indicator validation.
Reduces false positives by requiring multiple confirmations.

Validation Layers:
  0. Daily Bias (ICT Top-Down) - HEAVY penalty for counter-trend (was hard filter)
  1. Time-of-Day Quality - Soft penalty for low-probability time windows
  2. EMA Stack Confirmation - Boost for full EMA alignment (9>20>50)
  3. RSI Divergence - Early reversal warning (soft signal)
  4. Trend Strength (ADX) - Is there a real trend?
  5. Volume Confirmation (AvgVol) - Is there institutional interest?
  6. Trend Direction (DMI) - Does direction match signal?
  7. Momentum (CCI) - Are we entering overbought/oversold?
  8. Volatility Context (Bollinger Bands) - Squeeze or expansion?
  9. Volume Profile (VPVR) - Support/resistance alignment? (CAN RESCUE counter-trend)

Integration:
  - Called by signal_generator.py AFTER CFW6 pattern detection
  - Can boost or filter signals based on confluence
  - Returns enriched metadata for logging and Discord

Fine-Tuning Updates (Applied):
  #1. Time-of-Day: Morning/Power Hour +0.05, Dead Zone -0.03
  #2. RSI Divergence: Detect price/RSI mismatch ±0.05
  #3. EMA Stack: Full stack +0.07, No stack -0.04
  #4. Bias Threshold: 0.65 (was 0.70) - allows more valid setups
  #5. ADX Threshold: 25 (was 20) - filters choppy markets [NEW]
      Volume Ratio: 1.5x (was 1.3x) - stronger institutional confirmation [NEW]
  #6. VPVR Integration: Entry scoring based on POC/HVN/LVN zones [NEW - FEB 25, 2026]
  #7. VPVR Rescue Logic: Excellent VPVR scores can override bias penalty [FIX - FEB 25, 2026]
"""
from typing import Dict, Optional, Tuple
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import technical_indicators as ti

ET = ZoneInfo("America/New_York")

# Import daily bias engine for top-down analysis
try:
    from daily_bias_engine import bias_engine
    BIAS_ENGINE_ENABLED = True
    print("[VALIDATOR] ✅ Daily bias penalty enabled (ICT top-down analysis)")
except ImportError:
    BIAS_ENGINE_ENABLED = False
    bias_engine = None
    print("[VALIDATOR] ⚠️  daily_bias_engine not available - bias filtering disabled")

# Import VPVR calculator for volume profile analysis
try:
    from vpvr_calculator import vpvr_calculator
    VPVR_ENABLED = True
    print("[VALIDATOR] ✅ VPVR entry scoring enabled (POC/HVN/LVN analysis + counter-trend rescue)")
except ImportError:
    VPVR_ENABLED = False
    vpvr_calculator = None
    print("[VALIDATOR] ⚠️  vpvr_calculator not available - volume profile disabled")


# ══════════════════════════════════════════════════════════════════════════════
# TIME-OF-DAY QUALITY SCORING
# ══════════════════════════════════════════════════════════════════════════════

def get_time_of_day_quality(signal_time: datetime) -> Tuple[str, float]:
    """
    Assess signal quality based on time of day.
    
    Historical edge analysis shows:
      - Morning session (9:30-10:30): Highest momentum, best follow-through
      - Power hour (15:00-16:00): Strong institutional positioning
      - Dead zone (11:30-13:00): Choppy, low follow-through
    
    Returns:
        (zone_label, confidence_adjustment)
        
        confidence_adjustment:
          +0.05 = Prime time (morning session, power hour)
          +0.02 = Good time (early afternoon)
           0.00 = Neutral time (late morning, mid-afternoon)
          -0.03 = Weak time (dead zone 11:30-13:00)
    
    Note: This is a SOFT penalty, not a hard filter. Signals in weak zones
    still pass validation but receive lower confidence scores.
    """
    current_time = signal_time.time()
    
    # Prime Time Windows
    if dtime(9, 30) <= current_time < dtime(10, 30):
        return 'MORNING_SESSION', 0.05  # Opening hour - strongest moves
    
    if dtime(15, 0) <= current_time < dtime(16, 0):
        return 'POWER_HOUR', 0.05  # Closing hour - institutional positioning
    
    # Good Time Windows
    if dtime(10, 30) <= current_time < dtime(11, 30):
        return 'LATE_MORNING', 0.02  # Still decent momentum
    
    if dtime(13, 30) <= current_time < dtime(15, 0):
        return 'EARLY_AFTERNOON', 0.02  # Post-lunch recovery
    
    # Dead Zone (highest chop risk)
    if dtime(11, 30) <= current_time < dtime(13, 0):
        return 'DEAD_ZONE', -0.03  # Lunch hour chop
    
    # Neutral (edge uncertain)
    if dtime(13, 0) <= current_time < dtime(13, 30):
        return 'LUNCH_RECOVERY', 0.0  # Transitional period
    
    # After hours / pre-market (shouldn't reach here in normal flow)
    return 'OFF_HOURS', 0.0


class SignalValidator:
    """Multi-indicator signal validation engine."""
    
    def __init__(
        self,
        min_adx: float = 25.0,
        min_volume_ratio: float = 1.5,
        enable_vpvr: bool = True,
        enable_daily_bias: bool = True,
        enable_time_filter: bool = True,
        enable_ema_stack: bool = True,
        enable_rsi_divergence: bool = True,
        min_bias_confidence: float = 0.65,
        strict_mode: bool = False
    ):
        """
        Initialize signal validator.
        
        Args:
            min_adx: Minimum ADX for trend strength (default 25, was 20)
            min_volume_ratio: Minimum volume vs average (default 1.5x, was 1.3x)
            enable_vpvr: Use VPVR for signal validation (default True)
            enable_daily_bias: Penalize counter-trend signals (default True)
            enable_time_filter: Apply time-of-day quality scoring (default True)
            enable_ema_stack: Check EMA stack alignment (9>20>50) (default True)
            enable_rsi_divergence: Check for RSI divergence warnings (default True)
            min_bias_confidence: Minimum bias confidence to penalize (default 0.65)
            strict_mode: Require all checks to pass (default False)
        """
        self.min_adx = min_adx
        self.min_volume_ratio = min_volume_ratio
        self.enable_vpvr = enable_vpvr and VPVR_ENABLED
        self.enable_daily_bias = enable_daily_bias and BIAS_ENGINE_ENABLED
        self.enable_time_filter = enable_time_filter
        self.enable_ema_stack = enable_ema_stack
        self.enable_rsi_divergence = enable_rsi_divergence
        self.min_bias_confidence = min_bias_confidence
        self.strict_mode = strict_mode
        
        # Statistics tracking
        self.validation_stats = {
            'total_validated': 0,
            'passed': 0,
            'filtered': 0,
            'boosted': 0,
            'bias_penalized': 0,  # Changed from 'bias_filtered'
            'vpvr_rescued': 0,     # NEW: Counter-trend signals rescued by VPVR
            'vpvr_scored': 0,
            'time_zones': {},
            'ema_stack_aligned': 0,
            'rsi_divergence_detected': 0
        }
        
        if self.enable_daily_bias:
            print(f"[VALIDATOR] Daily bias penalty active (min confidence: {min_bias_confidence*100:.0f}%)")
            print(f"[VALIDATOR] ⭐ Counter-trend signals penalized but can be rescued by VPVR")
        
        if self.enable_time_filter:
            print(f"[VALIDATOR] Time-of-day quality scoring enabled (soft penalty, not hard block)")
        
        if self.enable_ema_stack:
            print(f"[VALIDATOR] EMA stack confirmation enabled (9>20>50 alignment check)")
        
        if self.enable_rsi_divergence:
            print(f"[VALIDATOR] RSI divergence detection enabled (early reversal warnings)")
        
        if self.enable_vpvr:
            print(f"[VALIDATOR] VPVR entry scoring enabled (POC/HVN/LVN context)")
        
        print(f"[VALIDATOR] ADX threshold: {min_adx} (filters choppy/weak trends)")
        print(f"[VALIDATOR] Volume ratio: {min_volume_ratio}x (institutional confirmation)")
    
    def validate_signal(
        self,
        ticker: str,
        signal_direction: str,
        current_price: float,
        current_volume: int,
        base_confidence: float
    ) -> Tuple[bool, float, Dict]:
        """
        Validate signal with multi-indicator confirmation.
        
        Args:
            ticker: Stock symbol
            signal_direction: 'BUY' or 'SELL'
            current_price: Current stock price
            current_volume: Current bar volume
            base_confidence: CFW6 base confidence (0.0-1.0)
        
        Returns:
            (should_pass, adjusted_confidence, metadata)
            
            should_pass: True if signal passes validation
            adjusted_confidence: Base confidence + boosts/penalties
            metadata: Dict with validation details for logging
        """
        self.validation_stats['total_validated'] += 1
        signal_time = datetime.now(ET)
        
        metadata = {
            'timestamp': signal_time.isoformat(),
            'ticker': ticker,
            'direction': signal_direction,
            'base_confidence': base_confidence,
            'checks': {}
        }
        
        confidence_adjustment = 0.0
        failed_checks = []
        passed_checks = []
        
        # Track whether this is a counter-trend signal that might need VPVR rescue
        counter_trend_penalty = 0.0
        needs_vpvr_rescue = False
        
        # ════════════════════════════════════════════════
        # CHECK 0: DAILY BIAS (ICT Top-Down) [HEAVY PENALTY, NOT HARD FILTER]
        # ════════════════════════════════════════════════
        if self.enable_daily_bias and bias_engine:
            try:
                should_filter, bias_reason = bias_engine.should_filter_signal(
                    ticker, signal_direction
                )
                
                bias_data = bias_engine._get_bias_dict()
                
                metadata['checks']['daily_bias'] = {
                    'bias': bias_data['bias'],
                    'confidence': bias_data['confidence'],
                    'should_filter': should_filter,
                    'reason': bias_reason
                }
                
                # ⭐ CRITICAL CHANGE: Apply HEAVY PENALTY instead of hard filter
                # Let VPVR and other checks still run
                if should_filter and bias_data['confidence'] >= self.min_bias_confidence:
                    # Strong counter-trend penalty
                    counter_trend_penalty = -0.25
                    confidence_adjustment += counter_trend_penalty
                    failed_checks.append('BIAS_COUNTER_TREND_STRONG')
                    needs_vpvr_rescue = True
                    self.validation_stats['bias_penalized'] += 1
                    
                    print(f"[VALIDATOR] ⚠️  {ticker} counter-trend to {bias_data['bias']} bias (-25%) - VPVR can rescue")
                    
                # Signal aligned with bias or neutral - apply boost/penalty
                elif bias_data['bias'] != 'NEUTRAL':
                    if not should_filter:
                        bias_boost = bias_data['confidence'] * 0.10
                        confidence_adjustment += bias_boost
                        passed_checks.append(f"BIAS_ALIGNED_{bias_data['bias']}")
                    else:
                        passed_checks.append('BIAS_WEAK')
                
            except Exception as e:
                metadata['checks']['daily_bias'] = {'error': str(e)}
                print(f"[VALIDATOR] Bias check error for {ticker}: {e}")
        
        # ════════════════════════════════════════════════
        # CHECK 1: TIME-OF-DAY QUALITY [SOFT PENALTY]
        # ════════════════════════════════════════════════
        if self.enable_time_filter:
            try:
                time_zone, time_adjustment = get_time_of_day_quality(signal_time)
                
                metadata['checks']['time_of_day'] = {
                    'zone': time_zone,
                    'time': signal_time.strftime('%H:%M:%S'),
                    'adjustment': time_adjustment
                }
                
                confidence_adjustment += time_adjustment
                
                # Track time zone statistics
                if time_zone not in self.validation_stats['time_zones']:
                    self.validation_stats['time_zones'][time_zone] = 0
                self.validation_stats['time_zones'][time_zone] += 1
                
                # Label the result
                if time_adjustment > 0:
                    passed_checks.append(f'TIME_{time_zone}')
                elif time_adjustment < 0:
                    failed_checks.append(f'TIME_{time_zone}')
                else:
                    passed_checks.append(f'TIME_NEUTRAL')
                
            except Exception as e:
                metadata['checks']['time_of_day'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 2: EMA STACK CONFIRMATION [SOFT BOOST]
        # ════════════════════════════════════════════════
        if self.enable_ema_stack:
            try:
                # Fetch 9, 20, 50 EMAs
                ema9_data = ti.fetch_ema(ticker, period=9)
                ema20_data = ti.fetch_ema(ticker, period=20)
                ema50_data = ti.fetch_ema(ticker, period=50)
                
                if all([ema9_data, ema20_data, ema50_data]):
                    ema9 = ti.get_latest_value(ema9_data, 'ema')
                    ema20 = ti.get_latest_value(ema20_data, 'ema')
                    ema50 = ti.get_latest_value(ema50_data, 'ema')
                    
                    if all([ema9, ema20, ema50]):
                        # Check for proper stack alignment
                        if signal_direction == 'BUY':
                            # Bullish stack: 9 > 20 > 50 (and price > 9)
                            full_stack = (current_price > ema9 > ema20 > ema50)
                            partial_stack = (current_price > ema9 and ema9 > ema20)  # At least 2-layer
                        else:  # SELL
                            # Bearish stack: 9 < 20 < 50 (and price < 9)
                            full_stack = (current_price < ema9 < ema20 < ema50)
                            partial_stack = (current_price < ema9 and ema9 < ema20)  # At least 2-layer
                        
                        metadata['checks']['ema_stack'] = {
                            'ema9': round(ema9, 2),
                            'ema20': round(ema20, 2),
                            'ema50': round(ema50, 2),
                            'full_stack': full_stack,
                            'partial_stack': partial_stack
                        }
                        
                        if full_stack:
                            # Perfect EMA alignment = strong trend
                            confidence_adjustment += 0.07
                            passed_checks.append('EMA_FULL_STACK')
                            self.validation_stats['ema_stack_aligned'] += 1
                        elif partial_stack:
                            # Partial alignment = decent trend
                            confidence_adjustment += 0.03
                            passed_checks.append('EMA_PARTIAL_STACK')
                        else:
                            # No alignment = choppy / counter-trend
                            confidence_adjustment -= 0.04
                            failed_checks.append('EMA_NO_STACK')
                    else:
                        metadata['checks']['ema_stack'] = {'error': 'Missing EMA values'}
                else:
                    metadata['checks']['ema_stack'] = {'error': 'Failed to fetch EMA data'}
                    
            except Exception as e:
                metadata['checks']['ema_stack'] = {'error': str(e)}
                print(f"[VALIDATOR] EMA stack error for {ticker}: {e}")
        
        # ════════════════════════════════════════════════
        # CHECK 3: RSI DIVERGENCE [SOFT WARNING]
        # ════════════════════════════════════════════════
        if self.enable_rsi_divergence:
            try:
                div_result, div_details = ti.check_rsi_divergence(
                    ticker, signal_direction, lookback_bars=10
                )
                
                if div_result and div_details:
                    metadata['checks']['rsi_divergence'] = div_details
                    
                    if div_result == 'BEARISH_DIV':
                        # Price new high, RSI lower high = uptrend exhaustion
                        if signal_direction == 'SELL':
                            # Divergence favors SELL signals
                            confidence_adjustment += 0.05
                            passed_checks.append('RSI_DIV_FAVORABLE')
                        else:
                            # Divergence warns against BUY signals
                            confidence_adjustment -= 0.05
                            failed_checks.append('RSI_DIV_WARNING')
                        self.validation_stats['rsi_divergence_detected'] += 1
                    
                    elif div_result == 'BULLISH_DIV':
                        # Price new low, RSI higher low = downtrend exhaustion
                        if signal_direction == 'BUY':
                            # Divergence favors BUY signals
                            confidence_adjustment += 0.05
                            passed_checks.append('RSI_DIV_FAVORABLE')
                        else:
                            # Divergence warns against SELL signals
                            confidence_adjustment -= 0.05
                            failed_checks.append('RSI_DIV_WARNING')
                        self.validation_stats['rsi_divergence_detected'] += 1
                    
                    # NO_DIV = neutral (no adjustment)
                    
            except Exception as e:
                metadata['checks']['rsi_divergence'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 4: Trend Strength (ADX)
        # ════════════════════════════════════════════════
        try:
            is_trending, adx_value = ti.check_trend_strength(ticker, self.min_adx)
            
            metadata['checks']['adx'] = {
                'value': adx_value,
                'passed': is_trending,
                'threshold': self.min_adx
            }
            
            if adx_value:
                if adx_value >= 40:
                    confidence_adjustment += 0.05
                    passed_checks.append('ADX_STRONG')
                elif adx_value >= self.min_adx:
                    passed_checks.append('ADX_OK')
                else:
                    confidence_adjustment -= 0.05
                    failed_checks.append('ADX_WEAK')
        except Exception as e:
            metadata['checks']['adx'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 5: Volume Confirmation
        # ════════════════════════════════════════════════
        try:
            is_confirmed, volume_ratio = ti.check_volume_confirmation(
                ticker, current_volume, self.min_volume_ratio
            )
            
            metadata['checks']['volume'] = {
                'ratio': volume_ratio,
                'passed': is_confirmed,
                'threshold': self.min_volume_ratio
            }
            
            if volume_ratio:
                if volume_ratio >= 2.0:
                    confidence_adjustment += 0.10
                    passed_checks.append('VOLUME_STRONG')
                elif volume_ratio >= self.min_volume_ratio:
                    confidence_adjustment += 0.03
                    passed_checks.append('VOLUME_OK')
                else:
                    confidence_adjustment -= 0.08
                    failed_checks.append('VOLUME_WEAK')
        except Exception as e:
            metadata['checks']['volume'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 6: Trend Direction (DMI)
        # ════════════════════════════════════════════════
        try:
            trend_direction = ti.get_trend_direction(ticker)
            
            metadata['checks']['dmi'] = {
                'direction': trend_direction
            }
            
            if trend_direction:
                expected_direction = 'BULLISH' if signal_direction == 'BUY' else 'BEARISH'
                
                if trend_direction == expected_direction:
                    confidence_adjustment += 0.05
                    passed_checks.append('DMI_ALIGNED')
                else:
                    confidence_adjustment -= 0.10
                    failed_checks.append('DMI_CONFLICT')
        except Exception as e:
            metadata['checks']['dmi'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 7: Momentum (CCI)
        # ════════════════════════════════════════════════
        try:
            cci_data = ti.fetch_cci(ticker)
            if cci_data:
                cci_value = ti.get_latest_value(cci_data, 'cci')
                
                metadata['checks']['cci'] = {
                    'value': cci_value
                }
                
                if cci_value is not None:
                    if signal_direction == 'BUY':
                        if cci_value < -100:
                            confidence_adjustment += 0.05
                            passed_checks.append('CCI_OVERSOLD')
                        elif cci_value > 100:
                            confidence_adjustment -= 0.05
                            failed_checks.append('CCI_OVERBOUGHT')
                    else:  # SELL
                        if cci_value > 100:
                            confidence_adjustment += 0.05
                            passed_checks.append('CCI_OVERBOUGHT')
                        elif cci_value < -100:
                            confidence_adjustment -= 0.05
                            failed_checks.append('CCI_OVERSOLD')
        except Exception as e:
            metadata['checks']['cci'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 8: Bollinger Bands Squeeze
        # ════════════════════════════════════════════════
        try:
            is_squeezed, band_width = ti.check_bollinger_squeeze(ticker)
            
            metadata['checks']['bbands'] = {
                'band_width': band_width,
                'is_squeezed': is_squeezed
            }
            
            if is_squeezed:
                confidence_adjustment += 0.05
                passed_checks.append('BB_SQUEEZE')
        except Exception as e:
            metadata['checks']['bbands'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 9: VPVR ENTRY SCORING [CAN RESCUE COUNTER-TREND]
        # ════════════════════════════════════════════════
        vpvr_rescue_applied = False
        
        if self.enable_vpvr and vpvr_calculator:
            try:
                # Import data_manager to get bars
                from data_manager import data_manager
                
                # Get recent bars for VPVR calculation
                bars = data_manager.get_today_session_bars(ticker)
                
                if bars and len(bars) >= 78:
                    # Calculate VPVR from last 78 bars (~1.3 hours of 1m data)
                    vpvr = vpvr_calculator.calculate_vpvr(bars, lookback_bars=78)
                    
                    if vpvr and vpvr['poc'] is not None:
                        # Score the entry price
                        entry_score, entry_reason = vpvr_calculator.get_entry_score(
                            current_price, vpvr
                        )
                        
                        metadata['checks']['vpvr'] = {
                            'poc': vpvr['poc'],
                            'vah': vpvr['vah'],
                            'val': vpvr['val'],
                            'entry_score': round(entry_score, 2),
                            'entry_reason': entry_reason,
                            'hvn_zones': vpvr['hvn_zones'][:2] if len(vpvr['hvn_zones']) > 2 else vpvr['hvn_zones'],
                            'lvn_zones': vpvr['lvn_zones'][:2] if len(vpvr['lvn_zones']) > 2 else vpvr['lvn_zones']
                        }
                        
                        self.validation_stats['vpvr_scored'] += 1
                        
                        # ⭐ VPVR RESCUE LOGIC FOR COUNTER-TREND SIGNALS
                        if needs_vpvr_rescue and entry_score >= 0.85:
                            # Excellent VPVR score (at POC/HVN) overrides bias penalty
                            rescue_boost = abs(counter_trend_penalty) * 0.80  # Recover 80% of penalty
                            confidence_adjustment += rescue_boost
                            passed_checks.append('VPVR_RESCUE')
                            failed_checks.remove('BIAS_COUNTER_TREND_STRONG')
                            vpvr_rescue_applied = True
                            self.validation_stats['vpvr_rescued'] += 1
                            
                            print(f"[VPVR] ✨ {ticker} RESCUED: Excellent entry at {entry_reason} overrides bias penalty (+{rescue_boost:.2%})")
                        
                        # Standard VPVR scoring (for all signals)
                        if entry_score >= 0.85:
                            # Strong entry (POC or HVN)
                            if not vpvr_rescue_applied:  # Don't double-boost
                                confidence_adjustment += 0.08
                                passed_checks.append('VPVR_STRONG')
                            print(f"[VPVR] ✅ {ticker} strong entry: {entry_reason}")
                        elif entry_score >= 0.70:
                            # Good entry (Value Area)
                            confidence_adjustment += 0.03
                            passed_checks.append('VPVR_GOOD')
                            print(f"[VPVR] 🟢 {ticker} good entry: {entry_reason}")
                        elif entry_score < 0.50:
                            # Weak entry (LVN or far from value)
                            confidence_adjustment -= 0.05
                            failed_checks.append('VPVR_WEAK')
                            print(f"[VPVR] ⚠️  {ticker} weak entry: {entry_reason}")
                        else:
                            # Neutral entry
                            passed_checks.append('VPVR_NEUTRAL')
                            print(f"[VPVR] 🟡 {ticker} neutral entry: {entry_reason}")
                        
                        # Store rescue status in metadata
                        if vpvr_rescue_applied:
                            metadata['checks']['vpvr']['rescued'] = True
                    else:
                        metadata['checks']['vpvr'] = {'error': 'Insufficient VPVR data'}
                else:
                    metadata['checks']['vpvr'] = {'error': f'Need 78+ bars, got {len(bars) if bars else 0}'}
                    
            except Exception as e:
                metadata['checks']['vpvr'] = {'error': str(e)}
                print(f"[VALIDATOR] VPVR error for {ticker}: {e}")
        
        # ════════════════════════════════════════════════
        # FINAL DECISION
        # ════════════════════════════════════════════════
        
        adjusted_confidence = max(0.0, min(1.0, base_confidence + confidence_adjustment))
        
        if self.strict_mode:
            critical_failures = [
                'VOLUME_WEAK', 'DMI_CONFLICT', 'ADX_WEAK'
            ]
            should_pass = not any(fail in failed_checks for fail in critical_failures)
        else:
            # Normal mode: Pass if more checks passed than failed
            should_pass = len(passed_checks) >= len(failed_checks)
        
        # Update stats
        if should_pass:
            self.validation_stats['passed'] += 1
            if confidence_adjustment > 0:
                self.validation_stats['boosted'] += 1
        else:
            self.validation_stats['filtered'] += 1
        
        # Add summary to metadata
        metadata['summary'] = {
            'should_pass': should_pass,
            'adjusted_confidence': round(adjusted_confidence, 3),
            'confidence_adjustment': round(confidence_adjustment, 3),
            'passed_checks': passed_checks,
            'failed_checks': failed_checks,
            'check_score': f"{len(passed_checks)}/{len(passed_checks) + len(failed_checks)}",
            'vpvr_rescued': vpvr_rescue_applied
        }
        
        return should_pass, adjusted_confidence, metadata
    
    def get_validation_stats(self) -> Dict:
        """Get validation statistics."""
        total = self.validation_stats['total_validated']
        if total == 0:
            return self.validation_stats
        
        stats = {
            **self.validation_stats,
            'pass_rate': round(self.validation_stats['passed'] / total, 3),
            'filter_rate': round(self.validation_stats['filtered'] / total, 3),
            'boost_rate': round(self.validation_stats['boosted'] / total, 3),
            'bias_penalty_rate': round(self.validation_stats['bias_penalized'] / total, 3),
            'vpvr_rescue_rate': round(self.validation_stats['vpvr_rescued'] / total, 3),
            'ema_stack_rate': round(self.validation_stats['ema_stack_aligned'] / total, 3),
            'rsi_div_rate': round(self.validation_stats['rsi_divergence_detected'] / total, 3),
            'vpvr_scored_rate': round(self.validation_stats['vpvr_scored'] / total, 3)
        }
        
        # Add time zone distribution
        if self.validation_stats['time_zones']:
            stats['time_zone_distribution'] = self.validation_stats['time_zones']
        
        return stats
    
    def reset_stats(self):
        """Reset validation statistics."""
        self.validation_stats = {
            'total_validated': 0,
            'passed': 0,
            'filtered': 0,
            'boosted': 0,
            'bias_penalized': 0,
            'vpvr_rescued': 0,
            'vpvr_scored': 0,
            'time_zones': {},
            'ema_stack_aligned': 0,
            'rsi_divergence_detected': 0
        }


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════════════

_validator_instance: Optional[SignalValidator] = None


def get_validator() -> SignalValidator:
    """Get or create global validator instance."""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = SignalValidator(
            min_adx=25.0,
            min_volume_ratio=1.5,
            enable_vpvr=True,
            enable_daily_bias=True,
            enable_time_filter=True,
            enable_ema_stack=True,
            enable_rsi_divergence=True,
            min_bias_confidence=0.65,
            strict_mode=False
        )
    return _validator_instance


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Signal Validator (ADX: 25, Volume: 1.5x, Bias: 0.65, VPVR: ON + RESCUE)...\n")
    
    validator = SignalValidator(
        min_adx=25.0,
        min_volume_ratio=1.5,
        enable_vpvr=True,
        enable_daily_bias=True,
        enable_time_filter=True,
        enable_ema_stack=True,
        enable_rsi_divergence=True,
        min_bias_confidence=0.65,
        strict_mode=False
    )
    
    test_ticker = "AAPL"
    test_direction = "BUY"
    test_price = 175.50
    test_volume = 5_000_000
    test_confidence = 0.75
    
    print("="*80)
    print(f"VALIDATING SIGNAL: {test_ticker} {test_direction} @ ${test_price}")
    print(f"Base Confidence: {test_confidence*100:.1f}%")
    print("="*80 + "\n")
    
    should_pass, adjusted_conf, metadata = validator.validate_signal(
        test_ticker,
        test_direction,
        test_price,
        test_volume,
        test_confidence
    )
    
    print("\n" + "="*80)
    print("VALIDATION RESULTS")
    print("="*80)
    
    summary = metadata['summary']
    print(f"\nDecision: {'✅ PASS' if should_pass else '❌ FILTERED'}")
    print(f"Adjusted Confidence: {adjusted_conf*100:.1f}% ({summary['confidence_adjustment']:+.1%})")
    
    if summary.get('vpvr_rescued'):
        print(f"\n✨ VPVR RESCUE: Counter-trend signal saved by excellent volume profile entry")
    
    print(f"\nChecks Passed: {', '.join(summary['passed_checks']) if summary['passed_checks'] else 'None'}")
    print(f"Checks Failed: {', '.join(summary['failed_checks']) if summary['failed_checks'] else 'None'}")
    print(f"Score: {summary['check_score']}")
    
    if 'filter_reason' in summary:
        print(f"\n⚠️  Filter Reason: {summary['filter_reason']}")
    
    print("\n" + "="*80)
    print("CHECK DETAILS")
    print("="*80)
    
    for check_name, check_data in metadata['checks'].items():
        print(f"\n{check_name.upper()}:")
        for key, value in check_data.items():
            if isinstance(value, dict):
                print(f"  {key}: {{...}}")
            else:
                print(f"  {key}: {value}")
    
    print("\n" + "="*80)
    print("VALIDATOR STATISTICS")
    print("="*80)
    stats = validator.get_validation_stats()
    print(f"Total Validated: {stats['total_validated']}")
    print(f"Pass Rate: {stats.get('pass_rate', 0)*100:.1f}%")
    print(f"Filter Rate: {stats.get('filter_rate', 0)*100:.1f}%")
    print(f"Bias Penalty Rate: {stats.get('bias_penalty_rate', 0)*100:.1f}%")
    print(f"VPVR Rescue Rate: {stats.get('vpvr_rescue_rate', 0)*100:.1f}%")
    print(f"Boost Rate: {stats.get('boost_rate', 0)*100:.1f}%")
    print(f"EMA Stack Aligned Rate: {stats.get('ema_stack_rate', 0)*100:.1f}%")
    print(f"RSI Divergence Rate: {stats.get('rsi_div_rate', 0)*100:.1f}%")
    print(f"VPVR Scored Rate: {stats.get('vpvr_scored_rate', 0)*100:.1f}%")
    
    if 'time_zone_distribution' in stats:
        print(f"\nTime Zone Distribution:")
        for zone, count in stats['time_zone_distribution'].items():
            print(f"  {zone}: {count}")
    
    print("="*80)
