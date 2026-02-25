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
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json

from breakout_detector import BreakoutDetector, format_signal_message
from data_manager import data_manager
from discord_helpers import send_simple_message

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
                 volume_multiplier: float = 2.0,
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
            atr_stop_multiplier=1.5,
            risk_reward_ratio=2.0
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
    
    def check_ticker(self, ticker: str, use_5m: bool = True) -> Optional[Dict]:
        """
        Check if ticker has a breakout signal.
        
        Phase 1.8: Now passes ticker to detector for PDH/PDL-aware analysis.
        Issue #3 Fix: Cooldown check moved AFTER validation - only validated signals trigger cooldown.
        
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
        
        # === MULTI-INDICATOR VALIDATION (TEST MODE) ===
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
        Send alert for detected signal.
        
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
        
        # Add validation summary if available
        if 'validation_test' in signal:
            val = signal['validation_test']
            print(f"\nValidation Test:")
            print(f"  Status: {'✅ Would Pass' if val['should_pass'] else '❌ Would Filter'}")
            print(f"  Confidence: {val['original_confidence']}% → {val['adjusted_confidence']}% ({val['confidence_delta']:+.0f}%)")
            print(f"  Checks: {val['check_score']}")
            if val['checks_failed']:
                print(f"  Failed: {', '.join(val['checks_failed'])}")
        
        if 'signal_id' in signal:
            print(f"Signal ID: {signal['signal_id']} (tracked in analytics DB)")
        print("="*70 + "\n")
        
        # Discord alert
        if send_discord:
            try:
                msg = f"🚨 **BREAKOUT ALERT**\n{format_signal_message(ticker, signal)}"
                
                # Add validation test info to Discord
                if 'validation_test' in signal:
                    val = signal['validation_test']
                    status_emoji = "✅" if val['should_pass'] else "⚠️"
                    msg += f"\n\n{status_emoji} **Validation Test:** {val['check_score']} checks"
                    msg += f"\nConfidence: {val['original_confidence']}% → {val['adjusted_confidence']}%"
                
                send_simple_message(msg)
                print(f"[SIGNALS] Discord alert sent for {ticker}")
            except Exception as e:
                print(f"[SIGNALS] Discord error: {e}")
    
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
        target = signal['target']
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
            summary += (
                f"{ticker:<8} "
                f"{signal['signal']:<6} "
                f"${signal['entry']:<7.2f} "
                f"${signal['stop']:<7.2f} "
                f"${signal['target']:<7.2f} "
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
