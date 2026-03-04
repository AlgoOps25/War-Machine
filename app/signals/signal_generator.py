"""
Signal Generator - Integrate Breakout Detector with Scanner

Responsibilities:
  - Check watchlist for breakout signals
  - Filter duplicate signals (cooldown period)
  - Send Discord alerts with entry/stop/target
  - Track signal performance with signal_analytics
  - Manage signal state (pending, filled, stopped, hit target)
  - [NEW] Multi-indicator validation (Test Mode - no filtering yet)
  - [Phase 1.8] PDH/PDL-aware breakout detection via ticker parameter
  - [FIX] Cooldown only triggers AFTER validation passes (Issue #3)
  - [Phase 1.9] Data-driven DTE selection with EODHD options intelligence
  - [Day 5] Adaptive target discovery using 90-day cached data
  - [TASK 4] ML-based signal scoring with confidence prediction
  - [TASK 6] Options flow integration with whale detection
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import numpy as np

from app.signals.breakout_detector import BreakoutDetector, format_signal_message
from app.data.data_manager import data_manager
from app.discord_helpers import send_simple_message

# Import signal analytics for performance tracking
try:
    from signal_analytics import signal_tracker
    ANALYTICS_ENABLED = True
    print("[SIGNALS] ✅ Phase 4 tracking enabled (signal_analytics + performance_alerts)")
except ImportError:
    ANALYTICS_ENABLED = False
    signal_tracker = None
    print("[SIGNALS] ⚠️  signal_analytics not available - performance tracking disabled")

# Import signal validator for multi-indicator confirmation
try:
    from signal_validator import get_validator
    VALIDATOR_ENABLED = True
    VALIDATOR_TEST_MODE = False  # Set to False to enable filtering
except ImportError:
    VALIDATOR_ENABLED = False
    print("[SIGNALS] ⚠️  signal_validator not available - multi-indicator validation disabled")

# Import DTE selector for data-driven options expiration logic
try:
    from options_dte_selector import dte_selector, get_optimal_dte
    DTE_SELECTOR_ENABLED = True
    print("[SIGNALS] ✅ Options DTE selector enabled (data-driven expiration logic)")
except ImportError:
    DTE_SELECTOR_ENABLED = False
    dte_selector = None
    print("[SIGNALS] ⚠️  options_dte_selector not available - using time-based fallback")

# Import Day 5 adaptive target discovery
try:
    from app.analytics.target_discovery import get_target_discovery
    from app.data.candle_cache import candle_cache
    target_discovery = get_target_discovery(candle_cache)
    TARGET_DISCOVERY_ENABLED = True
    print("[SIGNALS] ✅ Adaptive target discovery enabled (90-day historical analysis)")
except ImportError as e:
    TARGET_DISCOVERY_ENABLED = False
    target_discovery = None
    print(f"[SIGNALS] ⚠️  target_discovery not available ({e}) - using fixed R-multiples")

# TASK 4: Import ML Confidence Booster
try:
    from app.ml.ml_confidence_boost import MLConfidenceBooster
    ML_BOOSTER_ENABLED = True
    print("[SIGNALS] ✅ ML Confidence Booster enabled (Task 4 - ML signal scoring)")
except ImportError as e:
    ML_BOOSTER_ENABLED = False
    print(f"[SIGNALS] ⚠️  ML Confidence Booster not available ({e})")

# TASK 6: Import UOA Whale Detector
try:
    from app.data.unusual_options import uoa_detector
    UOA_ENABLED = True
    print("[SIGNALS] ✅ UOA Whale Detection enabled (Task 6 - Options flow integration)")
except ImportError as e:
    UOA_ENABLED = False
    print(f"[SIGNALS] ⚠️  UOA not available ({e})")

ET = ZoneInfo("America/New_York")


def _ensure_timezone_aware(dt: datetime) -> datetime:
    """
    Ensure datetime is timezone-aware (ET).
    Helper function to safely handle mixed timezone data.
    
    Args:
        dt: datetime object (aware or naive)
    
    Returns:
        timezone-aware datetime in ET
    """
    if dt.tzinfo is None:
        # Naive datetime - assume ET
        return dt.replace(tzinfo=ET)
    elif dt.tzinfo != ET:
        # Different timezone - convert to ET
        return dt.astimezone(ET)
    return dt


class SignalGenerator:
    """Generate and manage trading signals from breakout detector."""
    
    def __init__(self, 
                 lookback_bars: int = 12,
                 volume_multiplier: float = 3.0,
                 cooldown_minutes: int = 15,
                 min_confidence: int = 60):
        """
        Args:
            lookback_bars: Bars to use for support/resistance
            volume_multiplier: Volume confirmation threshold
            cooldown_minutes: Time to wait before generating another signal for same ticker
            min_confidence: Minimum confidence score to send alert
        """
        self.detector = BreakoutDetector(
            lookback_bars=lookback_bars,
            volume_multiplier=volume_multiplier,
            atr_stop_multiplier=2.5,
            risk_reward_ratio=3.0
        )
        
        self.cooldown_minutes = cooldown_minutes
        self.min_confidence = min_confidence
        
        # Track recent signals to avoid duplicates (in-memory cache)
        self.recent_signals: Dict[str, datetime] = {}  # ticker -> last_signal_time
        
        # Track active signals for performance monitoring
        # Now includes signal_id from analytics database
        self.active_signals: Dict[str, Dict] = {}  # ticker -> signal_data
        
        # Initialize validator if available
        self.validator = None
        if VALIDATOR_ENABLED:
            try:
                self.validator = get_validator()
                mode = "TEST MODE (no filtering)" if VALIDATOR_TEST_MODE else "FULL MODE (filtering enabled)"
                print(f"[SIGNALS] ✅ Multi-indicator validator ACTIVE ({mode})")
            except Exception as e:
                print(f"[SIGNALS] ⚠️  Validator initialization error: {e}")
                self.validator = None
        
        # TASK 4: Initialize ML Booster
        self.ml_booster = None
        if ML_BOOSTER_ENABLED:
            try:
                self.ml_booster = MLConfidenceBooster()
                status = "trained" if self.ml_booster.is_trained else "untrained"
                print(f"[SIGNALS] ML Booster loaded: {status}")
            except Exception as e:
                print(f"[SIGNALS] ML Booster initialization error: {e}")
                self.ml_booster = None
        
        # Validation statistics
        self.validation_stats = {
            'total_signals': 0,
            'would_filter': 0,
            'would_pass': 0,
            'confidence_boosted': 0,
            'confidence_penalized': 0
        }
        
        print(f"[SIGNALS] Generator initialized | "
              f"Lookback: {lookback_bars} | Volume: {volume_multiplier}x | "
              f"Cooldown: {cooldown_minutes}m | Min Confidence: {min_confidence}%")
        
        if ANALYTICS_ENABLED:
            print("[SIGNALS] ✅ Performance tracking enabled with database-backed cooldown")
        
        print("[SIGNALS] ✅ Cooldown only triggers after validation passes (Issue #3 fix)")
    
    def _extract_ml_features(self, ticker: str, signal: Dict, latest_bar: Dict) -> Dict[str, float]:
        """
        Extract ML features from signal data for confidence prediction (TASK 4).
        
        Args:
            ticker: Stock ticker
            signal: Signal dict with entry/stop/targets
            latest_bar: Latest price bar
        
        Returns:
            Dict of feature_name -> value (22 features)
        """
        features = {}
        now_et = datetime.now(ET)
        
        # Time features
        features['hour_of_day'] = now_et.hour
        features['day_of_week'] = now_et.weekday()
        features['time_since_open_min'] = signal.get('time_since_open_min', 0)
        
        # Gap features
        gap_pct = signal.get('gap_pct', 0.0)
        features['gap_pct'] = gap_pct
        features['gap_abs'] = abs(gap_pct)
        features['gap_direction'] = 1 if gap_pct > 0 else 0
        
        # Volume features
        volume = latest_bar.get('volume', signal.get('volume', 0))
        features['entry_volume'] = volume
        features['volume_surge_ratio'] = signal.get('volume_surge', 1.0)
        features['or_volume'] = signal.get('or_volume', 0)
        features['volume_log'] = np.log1p(volume)
        
        # Price vs key levels
        features['price_vs_pdh'] = signal.get('price_vs_pdh', 0.0)
        features['price_vs_or_high'] = signal.get('price_vs_or_high', 0.0)
        
        # PDH/PDL distance
        entry_price = signal['entry']
        pdh = signal.get('pdh', 0)
        pdl = signal.get('pdl', 0)
        
        if pdh and pdl and entry_price:
            features['pdh_distance_pct'] = (entry_price - pdh) / pdh * 100
            features['pdl_distance_pct'] = (entry_price - pdl) / pdl * 100
            features['pd_range_pct'] = (pdh - pdl) / pdl * 100
        else:
            features['pdh_distance_pct'] = 0.0
            features['pdl_distance_pct'] = 0.0
            features['pd_range_pct'] = 0.0
        
        # OR breakout
        or_high = signal.get('or_high', 0)
        or_low = signal.get('or_low', 0)
        
        if or_high and or_low and entry_price:
            features['or_breakout_size_pct'] = (entry_price - or_high) / or_high * 100
            features['or_range_pct'] = (or_high - or_low) / or_low * 100
        else:
            features['or_breakout_size_pct'] = 0.0
            features['or_range_pct'] = 0.0
        
        # VIX
        features['vix_level'] = signal.get('vix', 15.0)
        
        # Signal type one-hot
        signal_type = signal.get('type', 'unknown')
        for sig_type in ['gap_breakout', 'volume_surge', 'momentum', 'reversal']:
            features[f'signal_{sig_type}'] = 1 if sig_type in signal_type.lower() else 0
        
        return features
    
    def check_ticker(self, ticker: str, use_5m: bool = True) -> Optional[Dict]:
        """
        Check if ticker has a breakout signal.
        
        Phase 1.8: Now passes ticker to detector for PDH/PDL-aware analysis.
        Issue #3 Fix: Cooldown check moved AFTER validation - only validated signals trigger cooldown.
        Phase 1.9: Adds data-driven DTE selection for options recommendations.
        Day 5: Adaptive profit targets using 90-day cached historical data.
        TASK 4: ML-based confidence adjustments.
        TASK 6: UOA whale detection and flow correlation.
        
        Args:
            ticker: Stock ticker to check
            use_5m: Use 5-minute bars (True) or 1-minute bars (False)
        
        Returns:
            Signal dict if detected, None otherwise
        """
        # Get bars from database
        if use_5m:
            bars = data_manager.get_today_5m_bars(ticker)
        else:
            bars = data_manager.get_today_session_bars(ticker)
        
        if not bars or len(bars) < self.detector.lookback_bars:
            return None
        
        # Phase 1.8: Pass ticker to detector for PDH/PDL integration
        signal = self.detector.detect_breakout(bars, ticker=ticker)
        
        if not signal or signal['confidence'] < self.min_confidence:
            return None
        
        # Add ticker to signal
        signal['ticker'] = ticker
        
        # === DAY 5: ADAPTIVE TARGET DISCOVERY ===
        if TARGET_DISCOVERY_ENABLED and target_discovery:
            try:
                direction = 'bull' if signal['signal'] == 'BUY' else 'bear'
                
                targets = target_discovery.get_adaptive_targets(
                    ticker=ticker,
                    direction=direction,
                    entry=signal['entry'],
                    stop=signal['stop'],
                    confidence=signal['confidence'] / 100.0
                )
                
                # Replace fixed targets with adaptive targets
                signal['t1'] = targets['t1']
                signal['t2'] = targets['t2']
                signal['target'] = targets['t2']  # Keep legacy field
                signal['target_method'] = targets['method']
                signal['target_confidence'] = targets['confidence']
                signal['target_levels'] = targets['levels']
                signal['target_debug'] = targets.get('debug', {})
                
                # Log adaptive targets
                risk = abs(signal['entry'] - signal['stop'])
                t1_r = abs(targets['t1'] - signal['entry']) / risk
                t2_r = abs(targets['t2'] - signal['entry']) / risk
                
                print(f"[TARGETS] {ticker} {direction} | method={targets['method']} | "
                      f"t1=${targets['t1']:.2f} ({t1_r:.1f}R) | "
                      f"t2=${targets['t2']:.2f} ({t2_r:.1f}R) | "
                      f"conf={targets['confidence']:.0%}")
                
                if targets.get('debug'):
                    debug = targets['debug']
                    if 'levels_found' in debug:
                        print(f"[TARGETS]   {debug['levels_found']} volume zones detected | "
                              f"T1: {debug.get('t1_touches', 'N/A')} touches | "
                              f"T2: {debug.get('t2_touches', 'N/A')} touches")
            
            except Exception as e:
                print(f"[TARGETS] {ticker} error ({e}) - using fixed R-multiples")
                # Fallback: Keep detector's original targets
                pass
        
        # === MULTI-INDICATOR VALIDATION ===
        if self.validator and bars:
            try:
                latest_bar = bars[-1]
                
                # Run validation
                should_pass, adjusted_conf, metadata = self.validator.validate_signal(
                    ticker=ticker,
                    signal_direction=signal['signal'],
                    current_price=signal['entry'],
                    current_volume=latest_bar['volume'],
                    base_confidence=signal['confidence'] / 100.0  # Convert to 0.0-1.0
                )
                
                # Update statistics
                self.validation_stats['total_signals'] += 1
                if should_pass:
                    self.validation_stats['would_pass'] += 1
                else:
                    self.validation_stats['would_filter'] += 1
                
                if adjusted_conf > (signal['confidence'] / 100.0):
                    self.validation_stats['confidence_boosted'] += 1
                elif adjusted_conf < (signal['confidence'] / 100.0):
                    self.validation_stats['confidence_penalized'] += 1
                
                # Store validation results in signal (for analysis)
                signal['validation_test'] = {
                    'should_pass': should_pass,
                    'original_confidence': signal['confidence'],
                    'adjusted_confidence': round(adjusted_conf * 100, 1),
                    'confidence_delta': round((adjusted_conf - signal['confidence'] / 100.0) * 100, 1),
                    'checks_passed': metadata['summary']['passed_checks'],
                    'checks_failed': metadata['summary']['failed_checks'],
                    'check_score': metadata['summary']['check_score']
                }
                
                # Log validation result
                status_emoji = "✅" if should_pass else "❌"
                conf_change = signal['validation_test']['confidence_delta']
                conf_emoji = "📈" if conf_change > 0 else "📉" if conf_change < 0 else "➡️"
                
                print(f"[VALIDATOR TEST] {ticker} {status_emoji} | "
                      f"Conf: {signal['confidence']:.0f}% → {adjusted_conf*100:.0f}% "
                      f"{conf_emoji} ({conf_change:+.0f}%) | "
                      f"Score: {metadata['summary']['check_score']}")
                
                if not should_pass:
                    print(f"[VALIDATOR TEST]   Would filter: {', '.join(metadata['summary']['failed_checks'])}")
                
                # TEST MODE: Continue with original signal (don't filter)
                if VALIDATOR_TEST_MODE:
                    pass  # Keep going with original signal
                else:
                    # FULL MODE: Apply validation filter
                    if not should_pass:
                        print(f"[VALIDATOR] {ticker} FILTERED - weak confirmation")
                        # ⭐ CRITICAL FIX: Do NOT update cooldown for filtered signals
                        return None
                    
                    # Update signal with boosted confidence
                    signal['confidence'] = round(adjusted_conf * 100, 1)
            
            except Exception as e:
                print(f"[VALIDATOR] Error validating {ticker}: {e}")
                # Continue without validation on error
        
        # ⭐ CRITICAL FIX: Cooldown check AFTER validation passes
        # Only signals that pass validation trigger cooldown
        if self._is_in_cooldown(ticker):
            print(f"[SIGNALS] {ticker} in cooldown (validated signal already exists)")
            return None
        
        # Update cooldown (only for validated signals)
        self.recent_signals[ticker] = datetime.now(ET)
        print(f"[SIGNALS] {ticker} cooldown started ({self.cooldown_minutes}m)")
        
        # === TASK 4: ML CONFIDENCE ADJUSTMENT ===
        if ML_BOOSTER_ENABLED and self.ml_booster and self.ml_booster.is_trained:
            try:
                # Extract features
                latest_bar = bars[-1] if bars else {}
                ml_features = self._extract_ml_features(ticker, signal, latest_bar)
                
                # Get ML confidence adjustment (±15%)
                adjustment = self.ml_booster.predict_confidence_adjustment(ml_features)
                
                # Apply adjustment (clamp to 0-100)
                original_conf = signal['confidence']
                adjusted_conf = max(0, min(100, original_conf + (adjustment * 100)))
                signal['confidence'] = round(adjusted_conf, 1)
                
                # Store ML metadata
                signal['ml_adjustment'] = {
                    'original': original_conf,
                    'adjusted': adjusted_conf,
                    'delta': adjusted_conf - original_conf,
                    'model_confidence': adjustment
                }
                
                # Log significant adjustments
                if abs(adjustment * 100) > 1.0:
                    emoji = "📈" if adjustment > 0 else "📉"
                    print(f"[ML-BOOST] {ticker} {emoji} | "
                          f"Conf: {original_conf:.0f}% → {adjusted_conf:.0f}% "
                          f"({adjustment*100:+.1f}%)")
            
            except Exception as e:
                print(f"[ML-BOOST] {ticker} error: {e}")
                # Keep original confidence on error
        
        # === TASK 6: UOA WHALE DETECTION ===
        if UOA_ENABLED and uoa_detector:
            try:
                direction = 'CALL' if signal['signal'] == 'BUY' else 'PUT'
                whale_data = uoa_detector.check_whale_activity(ticker, direction)
                
                # Store UOA data in signal
                signal['uoa'] = whale_data
                
                # Apply confidence boost if whale activity detected
                if whale_data['is_unusual'] and whale_data['confidence_boost'] > 0:
                    original_conf = signal['confidence']
                    boosted_conf = min(100, original_conf + (whale_data['confidence_boost'] * 100))
                    signal['confidence'] = round(boosted_conf, 1)
                    
                    print(f"[UOA-BOOST] {ticker} 🐋 | "
                          f"Conf: {original_conf:.0f}% → {boosted_conf:.0f}% "
                          f"(+{whale_data['confidence_boost']*100:.1f}%) | "
                          f"Score: {whale_data['overall_score']:.1f}/10")
            
            except Exception as e:
                print(f"[UOA] {ticker} error: {e}")
        
        # === Phase 1.9: DATA-DRIVEN DTE SELECTION ===
        if DTE_SELECTOR_ENABLED and dte_selector:
            try:
                dte_recommendation = get_optimal_dte(
                    ticker=ticker,
                    entry_price=signal['entry'],
                    direction=signal['signal'],
                    confidence=signal['confidence']
                )
                
                if dte_recommendation:
                    signal['options_dte'] = dte_recommendation
                    print(f"[OPTIONS-DTE] {ticker} DTE: {dte_recommendation.get('dte', 'N/A')} "
                          f"(Score: {dte_recommendation.get('confidence_pct', 0)}%)")
                else:
                    print(f"[OPTIONS-DTE] {ticker} - No DTE recommendation available")
            except Exception as e:
                print(f"[OPTIONS-DTE] Error calculating DTE for {ticker}: {e}")
        
        # Log signal to analytics database (NEW Phase 4 integration)
        if ANALYTICS_ENABLED and signal_tracker:
            try:
                signal_id = signal_tracker.record_signal_generated(
                    ticker=ticker,
                    signal_type=signal.get('type', 'CFW6_OR'),
                    direction='bull' if signal['signal'] == 'BUY' else 'bear',
                    grade=signal.get('grade', 'A'),
                    confidence=signal['confidence'] / 100.0,  # Convert to 0.0-1.0
                    entry_price=signal['entry'],
                    stop_price=signal['stop'],
                    t1_price=signal.get('t1', signal['target']),
                    t2_price=signal.get('t2', signal['target'])
                )
                signal['signal_id'] = signal_id  # Store DB ID for outcome tracking
                print(f"[ANALYTICS] Signal {signal_id} logged for {ticker}")
            except Exception as e:
                print(f"[SIGNALS] Analytics logging error: {e}")
        
        # Store active signal
        self.active_signals[ticker] = signal
        
        return signal
    
    def scan_watchlist(self, watchlist: List[str], use_5m: bool = True) -> List[Dict]:
        """
        Scan entire watchlist for breakout signals.
        
        Args:
            watchlist: List of tickers to scan
            use_5m: Use 5-minute bars (default: True for cleaner signals)
        
        Returns:
            List of detected signals
        """
        signals = []
        
        for ticker in watchlist:
            try:
                signal = self.check_ticker(ticker, use_5m=use_5m)
                if signal:
                    signals.append(signal)
            except Exception as e:
                print(f"[SIGNALS] Error checking {ticker}: {e}")
                continue
        
        return signals
    
    def send_signal_alert(self, signal: Dict, send_discord: bool = True) -> None:
        """
        Send alert for detected signal with enhanced Discord formatting.
        
        Phase 1.9: Now includes options DTE recommendation in Discord alert.
        Day 5: Includes adaptive target method and confidence in alerts.
        TASK 4: Shows ML confidence adjustments.
        TASK 6: Shows UOA whale activity.
        
        Args:
            signal: Signal dict from detector
            send_discord: Send to Discord (default: True)
        """
        ticker = signal['ticker']
        
        # Console output
        print("\n" + "="*70)
        print(f"🚨 BREAKOUT SIGNAL DETECTED: {ticker}")
        print("="*70)
        print(format_signal_message(ticker, signal))
        
        # Add adaptive target info if available
        if 'target_method' in signal:
            print(f"\nAdaptive Targets:")
            print(f"  Method: {signal['target_method']}")
            print(f"  Confidence: {signal.get('target_confidence', 0):.0%}")
            if signal.get('target_levels'):
                print(f"  Levels Found: {len(signal['target_levels'])}")
            if signal.get('target_debug'):
                debug = signal['target_debug']
                for key, val in debug.items():
                    if key not in ['levels_found']:  # Already shown
                        print(f"  {key}: {val}")
        
        # Add validation summary if available
        if 'validation_test' in signal:
            val = signal['validation_test']
            print(f"\nValidation Test:")
            print(f"  Status: {'✅ Would Pass' if val['should_pass'] else '❌ Would Filter'}")
            print(f"  Confidence: {val['original_confidence']}% → {val['adjusted_confidence']}% ({val['confidence_delta']:+.0f}%)")
            print(f"  Checks: {val['check_score']}")
            if val['checks_failed']:
                print(f"  Failed: {', '.join(val['checks_failed'])}")
        
        # TASK 4: Show ML adjustment
        if 'ml_adjustment' in signal:
            ml = signal['ml_adjustment']
            print(f"\nML Confidence Adjustment (Task 4):")
            print(f"  Original: {ml['original']:.1f}%")
            print(f"  Adjusted: {ml['adjusted']:.1f}%")
            print(f"  Delta: {ml['delta']:+.1f}%")
        
        # TASK 6: Show UOA whale data
        if 'uoa' in signal:
            uoa = signal['uoa']
            print(f"\nWhale Activity (Task 6):")
            print(f"  Unusual: {uoa['is_unusual']}")
            print(f"  Overall Score: {uoa['overall_score']:.1f}/10")
            print(f"  Whale Score: {uoa['whale_score']:.1f}/10")
            print(f"  Flow Score: {uoa['flow_score']:.1f}/10")
            print(f"  Confidence Boost: +{uoa['confidence_boost']*100:.1f}%")
            print(f"  Summary: {uoa['summary']}")
        
        if 'signal_id' in signal:
            print(f"Signal ID: {signal['signal_id']} (tracked in analytics DB)")
        
        # Add DTE recommendation
        if 'options_dte' in signal:
            dte_info = signal['options_dte']
            print(f"\nOptions DTE Recommendation:")
            print(f"  Selected: {dte_info.get('dte', 'N/A')}DTE")
            print(f"  Confidence: {dte_info.get('confidence_pct', 0)}%")
            print(f"  Time Remaining: {dte_info.get('time_remaining_hours', 0):.1f} hours")
        
        print("="*70 + "\n")
        
        # Discord alert with enhanced formatting
        if send_discord:
            try:
                msg = self._format_discord_alert(signal)
                send_simple_message(msg)
                print(f"[SIGNALS] Discord alert sent for {ticker}")
            except Exception as e:
                print(f"[SIGNALS] Discord error: {e}")
    
    def _format_discord_alert(self, signal: Dict) -> str:
        """
        Format enhanced Discord alert message with all enhancements.
        
        Args:
            signal: Signal dict
        
        Returns:
            Formatted Discord message
        """
        ticker = signal['ticker']
        direction = signal['signal']
        entry = signal['entry']
        stop = signal['stop']
        target = signal.get('t2', signal['target'])  # Use T2 as main target
        t1 = signal.get('t1', signal['target'])
        confidence = signal['confidence']
        
        # Calculate risk/reward
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Build message
        msg = f"🚨 **{ticker} {direction} BREAKOUT** 🚨\n\n"
        
        # Entry guidance
        entry_range_low = entry * 0.9985
        entry_range_high = entry * 1.0015
        msg += f"🎯 **ENTRY GUIDANCE:**\n"
        msg += f"   Limit Range: ${entry_range_low:.2f} - ${entry_range_high:.2f}\n"
        msg += f"   Current Price: ${entry:.2f}\n"
        msg += f"   Entry Window: Next 2-5 minutes\n\n"
        
        # Risk management with adaptive targets
        msg += f"🛡️ **RISK MANAGEMENT:**\n"
        msg += f"   Stop Loss: ${stop:.2f} ({((stop - entry) / entry * 100):+.2f}%)\n"
        msg += f"   T1 (50%): ${t1:.2f} ({((t1 - entry) / entry * 100):+.2f}%)\n"
        msg += f"   T2 (50%): ${target:.2f} ({((target - entry) / entry * 100):+.2f}%)\n"
        msg += f"   R:R Ratio: {rr_ratio:.2f}:1\n"
        
        # Add target method if adaptive
        if 'target_method' in signal and signal['target_method'] != 'fixed_rmultiples':
            method_name = signal['target_method'].replace('_', ' ').title()
            target_conf = signal.get('target_confidence', 0)
            msg += f"   📊 Targets: {method_name} ({target_conf:.0%} confidence)\n"
        
        msg += "\n"
        
        # Signal quality
        msg += f"📊 **SIGNAL QUALITY:**\n"
        msg += f"   Confidence: {confidence}%"
        
        # Show ML adjustment if available
        if 'ml_adjustment' in signal:
            ml = signal['ml_adjustment']
            if abs(ml['delta']) > 1.0:
                emoji = "📈" if ml['delta'] > 0 else "📉"
                msg += f" ({emoji} ML: {ml['delta']:+.1f}%)"
        
        # Show UOA whale boost if available
        if 'uoa' in signal and signal['uoa']['is_unusual']:
            uoa = signal['uoa']
            msg += f" (🐋 Whale: +{uoa['confidence_boost']*100:.1f}%)"
        
        msg += "\n"
        msg += f"   Pattern: {signal.get('pattern', 'BOS/FVG Breakout')}\n"
        msg += f"   Timeframe: Multi-TF Convergence\n\n"
        
        # === OPTIONS RECOMMENDATION (DTE) ===
        if 'options_dte' in signal:
            dte_info = signal['options_dte']
            selected_dte = dte_info.get('dte')
            
            if selected_dte is not None:
                msg += f"📈 **OPTIONS RECOMMENDATION:**\n"
                msg += f"   ✅ **SELECTED: {selected_dte}DTE** (Expires {'Today' if selected_dte == 0 else 'Tomorrow'} 4:00 PM)\n\n"
                
                # Data analysis summary
                factors = dte_info.get('data_factors', {})
                time_hrs = dte_info.get('time_remaining_hours', 0)
                
                msg += f"   **Data Analysis:**\n"
                msg += f"   {'✅' if factors.get('time_adequate') else '❌'} Time Adequate: {time_hrs:.1f} hours remaining\n"
                msg += f"   {'✅' if factors.get('dte_0_liquid') else '❌'} Liquidity {'Strong' if factors.get('dte_0_liquid') else 'Weak'}\n"
                msg += f"   {'✅' if factors.get('dte_0_theta_acceptable') else '❌'} Theta {'Acceptable' if factors.get('dte_0_theta_acceptable') else 'Aggressive'}\n"
                msg += f"   {'✅' if factors.get('dte_0_spread_tight') else '❌'} Spread {'Tight' if factors.get('dte_0_spread_tight') else 'Wide'}\n"
                msg += f"   {'✅' if factors.get('iv_favorable') else '❌'} IV {'Fair' if factors.get('iv_favorable') else 'Inflated'}\n\n"
                
                # Strike recommendations
                strikes = dte_info.get('recommended_strikes', [])
                if strikes:
                    for i, strike in enumerate(strikes[:2], 1):
                        label = "RECOMMENDED" if i == 1 else "Alternative"
                        msg += f"   **Strike #{i} ({label}):**\n"
                        msg += f"   - {strike['strike']}{'C' if direction == 'BUY' else 'P'} | Exp: {strike['exp_date']} | Score: {strike['score']}/30\n"
                        msg += f"   - Delta: {strike['delta']:.2f} | Theta: {strike.get('theta', 0):.2f}\n"
                        msg += f"   - Bid/Ask: ${strike['bid']:.2f} / ${strike['ask']:.2f} ({strike['spread_pct']:.1f}% spread)\n"
                        msg += f"   - OI: {strike['open_interest']:,} | Volume: {strike['volume']:,}\n\n"
            else:
                # Skip signal
                msg += f"🚫 **OPTIONS:** {dte_info.get('reasoning', 'No recommendation available')}\n\n"
        else:
            # Fallback time-based
            now_et = datetime.now(ET)
            market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            hours_left = (market_close - now_et).total_seconds() / 3600
            
            if hours_left >= 2.5:
                msg += f"📈 **OPTIONS RECOMMENDATION:**\n"
                msg += f"   ⏰ 0DTE (Expires Today 4:00 PM)\n"
                msg += f"   Time Remaining: {hours_left:.1f} hours\n\n"
            elif hours_left >= 1.5:
                msg += f"📅 **OPTIONS RECOMMENDATION:**\n"
                msg += f"   📆 1DTE (Expires Tomorrow 4:00 PM)\n"
                msg += f"   Reason: Limited time today ({hours_left:.1f} hrs)\n\n"
            else:
                msg += f"🚫 **OPTIONS:** Too close to market close\n\n"
        
        # Timestamp and holding guidance
        msg += f"⏰ **Signal Time:** {datetime.now(ET).strftime('%I:%M:%S %p ET')}\n"
        msg += f"⏳ **Hold Time:** 15-30 minutes max"
        
        # Add validation test info if available
        if 'validation_test' in signal:
            val = signal['validation_test']
            status_emoji = "✅" if val['should_pass'] else "⚠️"
            msg += f"\n\n{status_emoji} **Validation:** {val['check_score']} checks | "
            msg += f"Conf: {val['original_confidence']}% → {val['adjusted_confidence']}%"
        
        return msg
    
    def update_signal_status(self, ticker: str, current_price: float) -> Optional[str]:
        """
        Update status of active signal based on current price.
        
        Args:
            ticker: Stock ticker
            current_price: Current market price
        
        Returns:
            Status string: 'HIT_TARGET', 'STOPPED_OUT', 'ACTIVE', or None if not tracked
        """
        if ticker not in self.active_signals:
            return None
        
        signal = self.active_signals[ticker]
        entry = signal['entry']
        stop = signal['stop']
        target = signal.get('t2', signal['target'])  # Use T2 as final target
        signal_type = signal['signal']
        
        # Check if stopped out
        if signal_type == 'BUY' and current_price <= stop:
            self._close_signal(ticker, 'STOPPED_OUT', current_price)
            return 'STOPPED_OUT'
        elif signal_type == 'SELL' and current_price >= stop:
            self._close_signal(ticker, 'STOPPED_OUT', current_price)
            return 'STOPPED_OUT'
        
        # Check if target hit
        if signal_type == 'BUY' and current_price >= target:
            self._close_signal(ticker, 'HIT_TARGET', current_price)
            return 'HIT_TARGET'
        elif signal_type == 'SELL' and current_price <= target:
            self._close_signal(ticker, 'HIT_TARGET', current_price)
            return 'HIT_TARGET'
        
        return 'ACTIVE'
    
    def monitor_active_signals(self) -> List[Dict]:
        """
        Monitor all active signals and update their status.
        
        Returns:
            List of status updates (stopped out or target hit)
        """
        updates = []
        
        for ticker in list(self.active_signals.keys()):
            try:
                # Get current price
                bars = data_manager.get_today_session_bars(ticker)
                if not bars:
                    continue
                
                current_price = bars[-1]['close']
                status = self.update_signal_status(ticker, current_price)
                
                if status in ['STOPPED_OUT', 'HIT_TARGET']:
                    updates.append({
                        'ticker': ticker,
                        'status': status,
                        'price': current_price
                    })
            except Exception as e:
                print(f"[SIGNALS] Error monitoring {ticker}: {e}")
                continue
        
        return updates
    
    def _is_in_cooldown(self, ticker: str) -> bool:
        """
        Check if ticker is in cooldown period using in-memory cache.
        Database persistence removed - cooldown is session-based only.
        """
        now_et = datetime.now(ET)
        
        if ticker in self.recent_signals:
            last_signal_time = self.recent_signals[ticker]
            last_signal_time = _ensure_timezone_aware(last_signal_time)
            
            elapsed = (now_et - last_signal_time).total_seconds() / 60
            if elapsed < self.cooldown_minutes:
                return True
        
        return False
    
    def _close_signal(self, ticker: str, status: str, exit_price: float) -> None:
        """
        Close an active signal and send update.
        
        Args:
            ticker: Stock ticker
            status: 'STOPPED_OUT' or 'HIT_TARGET'
            exit_price: Price at which signal closed
        """
        if ticker not in self.active_signals:
            return
        
        signal = self.active_signals[ticker]
        entry = signal['entry']
        
        # Calculate P&L
        if signal['signal'] == 'BUY':
            pnl = exit_price - entry
            pnl_pct = (pnl / entry) * 100
        else:  # SELL
            pnl = entry - exit_price
            pnl_pct = (pnl / entry) * 100
        
        # Console output
        emoji = "✅" if status == 'HIT_TARGET' else "❌"
        print(f"\n{emoji} {ticker} {status}: ${exit_price:.2f} | P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)\n")
        
        # Discord alert
        try:
            msg = (
                f"{emoji} **{ticker} {status}**\n"
                f"Entry: ${entry:.2f} → Exit: ${exit_price:.2f}\n"
                f"P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)"
            )
            send_simple_message(msg)
        except Exception as e:
            print(f"[SIGNALS] Discord error: {e}")
        
        # Remove from active signals
        del self.active_signals[ticker]
    
    def get_active_signals_summary(self) -> str:
        """
        Get formatted summary of all active signals.
        
        Returns:
            Formatted string with active signals table
        """
        if not self.active_signals:
            return "No active signals"
        
        summary = "\n" + "="*70 + "\n"
        summary += "ACTIVE SIGNALS\n"
        summary += "="*70 + "\n"
        summary += f"{'Ticker':<8} {'Signal':<6} {'Entry':<8} {'Stop':<8} {'Target':<8} {'Conf':<5}\n"
        summary += "-"*70 + "\n"
        
        for ticker, signal in self.active_signals.items():
            target = signal.get('t2', signal['target'])
            summary += (
                f"{ticker:<8} "
                f"{signal['signal']:<6} "
                f"${signal['entry']:<7.2f} "
                f"${signal['stop']:<7.2f} "
                f"${target:<7.2f} "
                f"{signal['confidence']:<5}%\n"
            )
        
        summary += "="*70 + "\n"
        return summary
    
    def get_validation_stats_summary(self) -> str:
        """
        Get formatted summary of validation test statistics.
        
        Returns:
            Formatted string with validation stats
        """
        if not VALIDATOR_ENABLED or self.validation_stats['total_signals'] == 0:
            return "No validation data available"
        
        stats = self.validation_stats
        total = stats['total_signals']
        
        pass_rate = (stats['would_pass'] / total * 100) if total > 0 else 0
        filter_rate = (stats['would_filter'] / total * 100) if total > 0 else 0
        boost_rate = (stats['confidence_boosted'] / total * 100) if total > 0 else 0
        
        summary = "\n" + "="*70 + "\n"
        summary += "VALIDATOR TEST MODE STATISTICS\n"
        summary += "="*70 + "\n"
        summary += f"Total Signals Tested: {total}\n"
        summary += f"Would Pass: {stats['would_pass']} ({pass_rate:.1f}%)\n"
        summary += f"Would Filter: {stats['would_filter']} ({filter_rate:.1f}%)\n"
        summary += f"Confidence Boosted: {stats['confidence_boosted']} ({boost_rate:.1f}%)\n"
        summary += f"Confidence Penalized: {stats['confidence_penalized']}\n"
        summary += "="*70 + "\n"
        
        if VALIDATOR_TEST_MODE:
            summary += "⚠️  TEST MODE ACTIVE - Signals NOT being filtered\n"
            summary += "Switch VALIDATOR_TEST_MODE to False to enable filtering\n"
        else:
            summary += "✅ FULL MODE ACTIVE - Weak signals being filtered\n"
        
        summary += "="*70 + "\n"
        
        return summary
    
    def clear_expired_signals(self, max_age_hours: int = 4) -> None:
        """
        Clear signals older than max_age_hours (stale signals).
        
        Args:
            max_age_hours: Maximum age before signal is considered stale
        """
        now = datetime.now(ET)
        expired = []
        
        for ticker, signal in self.active_signals.items():
            signal_time = signal['timestamp']
            if isinstance(signal_time, str):
                signal_time = datetime.fromisoformat(signal_time)
            
            signal_time = _ensure_timezone_aware(signal_time)
            age = (now - signal_time).total_seconds() / 3600
            
            if age > max_age_hours:
                expired.append(ticker)
        
        for ticker in expired:
            print(f"[SIGNALS] Clearing stale signal for {ticker}")
            del self.active_signals[ticker]
    
    def reset_daily(self) -> None:
        """
        Reset signal generator for new trading day.
        
        Phase 1.8: Now clears PDH/PDL cache in breakout detector.
        """
        self.recent_signals.clear()
        self.active_signals.clear()
        
        # Phase 1.8: Clear PDH/PDL cache for new trading day
        try:
            self.detector.clear_pdh_pdl_cache()
            print("[SIGNALS] PDH/PDL cache cleared for new session")
        except Exception as e:
            print(f"[SIGNALS] PDH/PDL cache clear error: {e}")
        
        # Print validation stats before reset
        if VALIDATOR_ENABLED and self.validation_stats['total_signals'] > 0:
            print(self.get_validation_stats_summary())
        
        # Reset validation stats
        self.validation_stats = {
            'total_signals': 0,
            'would_filter': 0,
            'would_pass': 0,
            'confidence_boosted': 0,
            'confidence_penalized': 0
        }
        
        # Clear analytics session cache (EOD reset)
        if ANALYTICS_ENABLED and signal_tracker:
            try:
                signal_tracker.clear_session_cache()
            except Exception as e:
                print(f"[SIGNALS] Analytics cache clear error: {e}")
        
        # Clear UOA cache
        if UOA_ENABLED and uoa_detector:
            try:
                uoa_detector.clear_cache()
            except Exception as e:
                print(f"[SIGNALS] UOA cache clear error: {e}")
        
        print("[SIGNALS] Daily reset complete")


# ========================================
# GLOBAL INSTANCE
# ========================================
signal_generator = SignalGenerator(
    lookback_bars=12,
    volume_multiplier=2.0,
    cooldown_minutes=15,
    min_confidence=60
)


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def scan_for_signals(watchlist: List[str]) -> List[Dict]:
    """Convenience function to scan watchlist for signals."""
    return signal_generator.scan_watchlist(watchlist, use_5m=True)


def check_and_alert(watchlist: List[str]) -> None:
    """Scan watchlist and send alerts for any detected signals."""
    signals = signal_generator.scan_watchlist(watchlist, use_5m=True)
    
    for signal in signals:
        signal_generator.send_signal_alert(signal, send_discord=True)


def monitor_signals() -> None:
    """Monitor active signals and send updates."""
    updates = signal_generator.monitor_active_signals()
    
    if updates:
        print(f"\n[SIGNALS] {len(updates)} signal updates\n")


def print_active_signals() -> None:
    """Print summary of active signals."""
    print(signal_generator.get_active_signals_summary())


def print_validation_stats() -> None:
    """Print validation test statistics."""
    print(signal_generator.get_validation_stats_summary())


def print_performance_report(days: int = 30) -> None:
    """Print signal performance report from analytics database."""
    if ANALYTICS_ENABLED and signal_tracker:
        try:
            summary = signal_tracker.get_daily_summary()
            print(summary)
        except Exception as e:
            print(f"[SIGNALS] Performance report error: {e}")
    else:
        print("[SIGNALS] ⚠️  Analytics not enabled - cannot generate report")


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    # Example: Scan watchlist for signals
    test_watchlist = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]
    
    print("Scanning watchlist for breakout signals...\n")
    signals = scan_for_signals(test_watchlist)
    
    if signals:
        print(f"Found {len(signals)} signals:\n")
        for signal in signals:
            print(format_signal_message(signal['ticker'], signal))
            print("-" * 70)
    else:
        print("No signals detected")
    
    # Print validation stats (if enabled)
    if VALIDATOR_ENABLED:
        print_validation_stats()
    
    # Print performance stats
    print("\n" + "="*70)
    print_performance_report(days=7)
