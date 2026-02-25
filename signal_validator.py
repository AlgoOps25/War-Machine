"""
Signal Validator - Multi-Indicator Confirmation Engine

Enhances CFW6 signals with additional technical indicator validation.
Reduces false positives by requiring multiple confirmations.

Validation Layers:
  0. Daily Bias (ICT Top-Down) - Filter counter-trend signals [NEW]
  1. Trend Strength (ADX) - Is there a real trend?
  2. Volume Confirmation (AvgVol) - Is there institutional interest?
  3. Trend Direction (DMI) - Does direction match signal?
  4. Momentum (CCI) - Are we entering overbought/oversold?
  5. Volatility Context (Bollinger Bands) - Squeeze or expansion?
  6. Volume Profile (VPVR) - Support/resistance alignment?

Integration:
  - Called by signal_generator.py AFTER CFW6 pattern detection
  - Can boost or filter signals based on confluence
  - Returns enriched metadata for logging and Discord
"""
from typing import Dict, Optional, Tuple
from datetime import datetime
import technical_indicators as ti
import vpvr_calculator as vpvr

# Import daily bias engine for top-down analysis
try:
    from daily_bias_engine import bias_engine
    BIAS_ENGINE_ENABLED = True
    print("[VALIDATOR] ✅ Daily bias filtering enabled (ICT top-down analysis)")
except ImportError:
    BIAS_ENGINE_ENABLED = False
    bias_engine = None
    print("[VALIDATOR] ⚠️  daily_bias_engine not available - bias filtering disabled")


class SignalValidator:
    """Multi-indicator signal validation engine."""
    
    def __init__(
        self,
        min_adx: float = 20.0,
        min_volume_ratio: float = 1.3,
        enable_vpvr: bool = True,
        enable_daily_bias: bool = True,
        min_bias_confidence: float = 0.7,
        strict_mode: bool = False
    ):
        """
        Initialize signal validator.
        
        Args:
            min_adx: Minimum ADX for trend strength (default 20)
            min_volume_ratio: Minimum volume vs average (default 1.3x)
            enable_vpvr: Use VPVR for signal validation (default True)
            enable_daily_bias: Filter counter-trend signals (default True)
            min_bias_confidence: Minimum bias confidence to filter (default 0.7)
            strict_mode: Require all checks to pass (default False)
        """
        self.min_adx = min_adx
        self.min_volume_ratio = min_volume_ratio
        self.enable_vpvr = enable_vpvr
        self.enable_daily_bias = enable_daily_bias and BIAS_ENGINE_ENABLED
        self.min_bias_confidence = min_bias_confidence
        self.strict_mode = strict_mode
        
        # Statistics tracking
        self.validation_stats = {
            'total_validated': 0,
            'passed': 0,
            'filtered': 0,
            'boosted': 0,
            'bias_filtered': 0  # NEW: Track bias-based filtering
        }
        
        if self.enable_daily_bias:
            print(f"[VALIDATOR] Daily bias filter active (min confidence: {min_bias_confidence*100:.0f}%)")
    
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
        
        metadata = {
            'timestamp': datetime.now().isoformat(),
            'ticker': ticker,
            'direction': signal_direction,
            'base_confidence': base_confidence,
            'checks': {}
        }
        
        confidence_adjustment = 0.0
        failed_checks = []
        passed_checks = []
        
        # ════════════════════════════════════════════════
        # CHECK 0: DAILY BIAS (ICT Top-Down) [NEW - FIRST FILTER]
        # ════════════════════════════════════════════════
        if self.enable_daily_bias and bias_engine:
            try:
                # Check if signal aligns with daily bias
                should_filter, bias_reason = bias_engine.should_filter_signal(
                    ticker, signal_direction
                )
                
                # Get bias details
                bias_data = bias_engine._get_bias_dict()
                
                metadata['checks']['daily_bias'] = {
                    'bias': bias_data['bias'],
                    'confidence': bias_data['confidence'],
                    'should_filter': should_filter,
                    'reason': bias_reason
                }
                
                # HARD FILTER: Counter-trend signals with high confidence bias
                if should_filter and bias_data['confidence'] >= self.min_bias_confidence:
                    # This is a counter-trend signal - reject immediately
                    self.validation_stats['filtered'] += 1
                    self.validation_stats['bias_filtered'] += 1
                    
                    metadata['summary'] = {
                        'should_pass': False,
                        'adjusted_confidence': 0.0,
                        'confidence_adjustment': -base_confidence,
                        'passed_checks': [],
                        'failed_checks': ['BIAS_COUNTER_TREND'],
                        'check_score': '0/1 (bias filtered)',
                        'filter_reason': f"Counter-trend signal filtered by {bias_data['bias']} bias ({bias_data['confidence']*100:.0f}% conf)"
                    }
                    
                    return False, 0.0, metadata
                
                # Signal aligned with bias or neutral - apply boost/penalty
                if bias_data['bias'] != 'NEUTRAL':
                    if not should_filter:
                        # Signal aligned with bias
                        bias_boost = bias_data['confidence'] * 0.10  # Up to +10% for strong bias
                        confidence_adjustment += bias_boost
                        passed_checks.append(f"BIAS_ALIGNED_{bias_data['bias']}")
                    else:
                        # Bias exists but confidence too low to filter
                        passed_checks.append('BIAS_WEAK')
                
            except Exception as e:
                metadata['checks']['daily_bias'] = {'error': str(e)}
                print(f"[VALIDATOR] Bias check error for {ticker}: {e}")
        
        # ════════════════════════════════════════════════
        # CHECK 1: Trend Strength (ADX)
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
                    # Very strong trend
                    confidence_adjustment += 0.05
                    passed_checks.append('ADX_STRONG')
                elif adx_value >= self.min_adx:
                    # Sufficient trend
                    passed_checks.append('ADX_OK')
                else:
                    # Weak trend
                    confidence_adjustment -= 0.05
                    failed_checks.append('ADX_WEAK')
        except Exception as e:
            metadata['checks']['adx'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 2: Volume Confirmation
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
                    # Exceptional volume
                    confidence_adjustment += 0.10
                    passed_checks.append('VOLUME_STRONG')
                elif volume_ratio >= self.min_volume_ratio:
                    # Good volume
                    confidence_adjustment += 0.03
                    passed_checks.append('VOLUME_OK')
                else:
                    # Weak volume
                    confidence_adjustment -= 0.08
                    failed_checks.append('VOLUME_WEAK')
        except Exception as e:
            metadata['checks']['volume'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 3: Trend Direction (DMI)
        # ════════════════════════════════════════════════
        try:
            trend_direction = ti.get_trend_direction(ticker)
            
            metadata['checks']['dmi'] = {
                'direction': trend_direction
            }
            
            if trend_direction:
                expected_direction = 'BULLISH' if signal_direction == 'BUY' else 'BEARISH'
                
                if trend_direction == expected_direction:
                    # Trend aligns with signal
                    confidence_adjustment += 0.05
                    passed_checks.append('DMI_ALIGNED')
                else:
                    # Trend opposes signal
                    confidence_adjustment -= 0.10
                    failed_checks.append('DMI_CONFLICT')
        except Exception as e:
            metadata['checks']['dmi'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 4: Momentum (CCI)
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
                        # Check for oversold conditions (good for BUY)
                        if cci_value < -100:
                            confidence_adjustment += 0.05
                            passed_checks.append('CCI_OVERSOLD')
                        elif cci_value > 100:
                            # Overbought - bad for BUY
                            confidence_adjustment -= 0.05
                            failed_checks.append('CCI_OVERBOUGHT')
                    else:  # SELL
                        # Check for overbought conditions (good for SELL)
                        if cci_value > 100:
                            confidence_adjustment += 0.05
                            passed_checks.append('CCI_OVERBOUGHT')
                        elif cci_value < -100:
                            # Oversold - bad for SELL
                            confidence_adjustment -= 0.05
                            failed_checks.append('CCI_OVERSOLD')
        except Exception as e:
            metadata['checks']['cci'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 5: Bollinger Bands Squeeze
        # ════════════════════════════════════════════════
        try:
            is_squeezed, band_width = ti.check_bollinger_squeeze(ticker)
            
            metadata['checks']['bbands'] = {
                'band_width': band_width,
                'is_squeezed': is_squeezed
            }
            
            if is_squeezed:
                # Squeeze = potential breakout setup
                confidence_adjustment += 0.05
                passed_checks.append('BB_SQUEEZE')
        except Exception as e:
            metadata['checks']['bbands'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # CHECK 6: VPVR Context (Optional)
        # ════════════════════════════════════════════════
        if self.enable_vpvr:
            try:
                vpvr_context = vpvr.get_vpvr_signal_context(
                    ticker, current_price, signal_direction
                )
                
                if vpvr_context:
                    metadata['checks']['vpvr'] = vpvr_context
                    
                    recommendation = vpvr_context['recommendation']
                    
                    if recommendation == 'STRONG':
                        confidence_adjustment += 0.08
                        passed_checks.append('VPVR_STRONG')
                    elif recommendation == 'WEAK':
                        confidence_adjustment -= 0.05
                        failed_checks.append('VPVR_WEAK')
            except Exception as e:
                metadata['checks']['vpvr'] = {'error': str(e)}
        
        # ════════════════════════════════════════════════
        # FINAL DECISION
        # ════════════════════════════════════════════════
        
        # Calculate adjusted confidence
        adjusted_confidence = max(0.0, min(1.0, base_confidence + confidence_adjustment))
        
        # Determine if signal should pass
        if self.strict_mode:
            # Strict mode: Must have no critical failures
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
            'check_score': f"{len(passed_checks)}/{len(passed_checks) + len(failed_checks)}"
        }
        
        return should_pass, adjusted_confidence, metadata
    
    def get_validation_stats(self) -> Dict:
        """Get validation statistics."""
        total = self.validation_stats['total_validated']
        if total == 0:
            return self.validation_stats
        
        return {
            **self.validation_stats,
            'pass_rate': round(self.validation_stats['passed'] / total, 3),
            'filter_rate': round(self.validation_stats['filtered'] / total, 3),
            'boost_rate': round(self.validation_stats['boosted'] / total, 3),
            'bias_filter_rate': round(self.validation_stats['bias_filtered'] / total, 3)
        }
    
    def reset_stats(self):
        """Reset validation statistics."""
        self.validation_stats = {
            'total_validated': 0,
            'passed': 0,
            'filtered': 0,
            'boosted': 0,
            'bias_filtered': 0
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
            min_adx=20.0,
            min_volume_ratio=1.3,
            enable_vpvr=True,
            enable_daily_bias=True,
            min_bias_confidence=0.7,
            strict_mode=False
        )
    return _validator_instance


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test signal validator
    print("Testing Signal Validator with Daily Bias Integration...\n")
    
    validator = SignalValidator(
        min_adx=20.0,
        min_volume_ratio=1.3,
        enable_vpvr=True,
        enable_daily_bias=True,
        min_bias_confidence=0.7,
        strict_mode=False
    )
    
    # Test signal
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
    print(f"Bias Filter Rate: {stats.get('bias_filter_rate', 0)*100:.1f}%")
    print(f"Boost Rate: {stats.get('boost_rate', 0)*100:.1f}%")
    print("="*80)
