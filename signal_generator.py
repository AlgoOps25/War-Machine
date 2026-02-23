"""
Signal Generator - Integrate Breakout Detector with Scanner

Responsibilities:
  - Check watchlist tickers for breakout signals
  - Filter duplicate signals (cooldown period)
  - Send Discord alerts with entry/stop/target
  - Track signal performance with signal_analytics
  - Manage signal state (pending, filled, stopped, hit target)
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
    from signal_analytics import log_signal, update_signal_outcome, get_recent_signals
    ANALYTICS_ENABLED = True
except ImportError:
    ANALYTICS_ENABLED = False
    print("[SIGNALS] ⚠️ signal_analytics not available - performance tracking disabled")

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
        
        print(f"[SIGNALS] Generator initialized | "
              f"Lookback: {lookback_bars} | Volume: {volume_multiplier}x | "
              f"Cooldown: {cooldown_minutes}m | Min Confidence: {min_confidence}%")
        
        if ANALYTICS_ENABLED:
            print("[SIGNALS] ✅ Performance tracking enabled with database-backed cooldown")
    
    def check_ticker(self, ticker: str, use_5m: bool = True) -> Optional[Dict]:
        """
        Check if ticker has a breakout signal.
        
        Args:
            ticker: Stock ticker to check
            use_5m: Use 5-minute bars (True) or 1-minute bars (False)
        
        Returns:
            Signal dict if detected, None otherwise
        """
        # Check cooldown
        if self._is_in_cooldown(ticker):
            return None
        
        # Get bars from database
        if use_5m:
            bars = data_manager.get_today_5m_bars(ticker)
        else:
            bars = data_manager.get_today_session_bars(ticker)
        
        if not bars or len(bars) < self.detector.lookback_bars:
            return None
        
        # Detect breakout
        signal = self.detector.detect_breakout(bars)
        
        if signal and signal['confidence'] >= self.min_confidence:
            # Add ticker to signal
            signal['ticker'] = ticker
            
            # Update cooldown
            self.recent_signals[ticker] = datetime.now(ET)
            
            # Log signal to analytics database
            if ANALYTICS_ENABLED:
                try:
                    signal_id = log_signal(
                        ticker=ticker,
                        direction=signal['signal'],
                        entry=signal['entry'],
                        stop=signal['stop'],
                        target=signal['target'],
                        confidence=signal['confidence'],
                        volume_multiple=signal.get('volume_multiple'),
                        atr=signal.get('atr'),
                        signal_type=signal.get('type', 'BREAKOUT'),
                        notes=signal.get('notes')
                    )
                    signal['signal_id'] = signal_id  # Store DB ID for outcome tracking
                except Exception as e:
                    print(f"[SIGNALS] Analytics logging error: {e}")
            
            # Store active signal
            self.active_signals[ticker] = signal
            
            return signal
        
        return None
    
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
        print("\\n" + "="*70)
        print(f"🚨 BREAKOUT SIGNAL DETECTED: {ticker}")
        print("="*70)
        print(format_signal_message(ticker, signal))
        if 'signal_id' in signal:
            print(f"Signal ID: {signal['signal_id']} (tracked in analytics DB)")
        print("="*70 + "\\n")
        
        # Discord alert
        if send_discord:
            try:
                msg = f"🚨 **BREAKOUT ALERT**\\n{format_signal_message(ticker, signal)}"
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
        Check if ticker is in cooldown period.
        
        Uses two-tier approach:
        1. Check in-memory cache first (fast path)
        2. Query database if not in cache (handles restarts)
        
        This ensures cooldown persists even after scanner restarts.
        """
        now_et = datetime.now(ET)
        
        # Fast path: Check in-memory cache
        if ticker in self.recent_signals:
            last_signal_time = self.recent_signals[ticker]
            last_signal_time = _ensure_timezone_aware(last_signal_time)
            
            elapsed = (now_et - last_signal_time).total_seconds() / 60
            if elapsed < self.cooldown_minutes:
                return True
        
        # Slow path: Query database (handles restarts)
        if ANALYTICS_ENABLED:
            try:
                # Check signals from database within cooldown window
                # Using hours=1 to cover the 15-minute cooldown window
                recent = get_recent_signals(hours=1)
                
                for sig in recent:
                    if sig['ticker'] == ticker:
                        signal_time = sig['signal_time']
                        
                        # Handle both datetime objects and ISO strings
                        if isinstance(signal_time, str):
                            # Parse ISO string, handle 'Z' suffix for UTC
                            signal_time = datetime.fromisoformat(signal_time.replace('Z', '+00:00'))
                        
                        # Ensure timezone-aware comparison
                        signal_time = _ensure_timezone_aware(signal_time)
                        
                        elapsed = (now_et - signal_time).total_seconds() / 60
                        
                        if elapsed < self.cooldown_minutes:
                            # Update in-memory cache for next check
                            self.recent_signals[ticker] = signal_time
                            return True
            except Exception as e:
                print(f"[SIGNALS] Cooldown DB check error for {ticker}: {e}")
                # Continue without database check - don't block signals on DB errors
        
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
        
        # Update analytics database
        if ANALYTICS_ENABLED and 'signal_id' in signal:
            try:
                outcome = 'WIN' if status == 'HIT_TARGET' else 'LOSS'
                update_signal_outcome(
                    signal_id=signal['signal_id'],
                    outcome=outcome,
                    exit_price=exit_price
                )
            except Exception as e:
                print(f"[SIGNALS] Analytics update error: {e}")
        
        # Console output
        emoji = "✅" if status == 'HIT_TARGET' else "❌"
        print(f"\\n{emoji} {ticker} {status}: ${exit_price:.2f} | P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)\\n")
        
        # Discord alert
        try:
            msg = (
                f"{emoji} **{ticker} {status}**\\n"
                f"Entry: ${entry:.2f} → Exit: ${exit_price:.2f}\\n"
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
        
        summary = "\\n" + "="*70 + "\\n"
        summary += "ACTIVE SIGNALS\\n"
        summary += "="*70 + "\\n"
        summary += f"{'Ticker':<8} {'Signal':<6} {'Entry':<8} {'Stop':<8} {'Target':<8} {'Conf':<5}\\n"
        summary += "-"*70 + "\\n"
        
        for ticker, signal in self.active_signals.items():
            summary += (
                f"{ticker:<8} "
                f"{signal['signal']:<6} "
                f"${signal['entry']:<7.2f} "
                f"${signal['stop']:<7.2f} "
                f"${signal['target']:<7.2f} "
                f"{signal['confidence']:<5}%\\n"
            )
        
        summary += "="*70 + "\\n"
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
                
                # Mark as EXPIRED in analytics
                if ANALYTICS_ENABLED and 'signal_id' in signal:
                    try:
                        # Get current price for exit
                        bars = data_manager.get_today_session_bars(ticker)
                        exit_price = bars[-1]['close'] if bars else signal['entry']
                        
                        update_signal_outcome(
                            signal_id=signal['signal_id'],
                            outcome='EXPIRED',
                            exit_price=exit_price
                        )
                    except Exception as e:
                        print(f"[SIGNALS] Analytics expiry error for {ticker}: {e}")
        
        for ticker in expired:
            print(f"[SIGNALS] Clearing stale signal for {ticker}")
            del self.active_signals[ticker]
    
    def reset_daily(self) -> None:
        """Reset signal generator for new trading day."""
        self.recent_signals.clear()
        self.active_signals.clear()
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
        print(f"\\n[SIGNALS] {len(updates)} signal updates\\n")


def print_active_signals() -> None:
    """Print summary of active signals."""
    print(signal_generator.get_active_signals_summary())


def print_performance_report(days: int = 30) -> None:
    """Print signal performance report."""
    if ANALYTICS_ENABLED:
        from signal_analytics import print_performance_report as _print_report
        _print_report(days)
    else:
        print("[SIGNALS] ⚠️ Analytics not enabled - cannot generate report")


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    # Example: Scan watchlist for signals
    test_watchlist = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]
    
    print("Scanning watchlist for breakout signals...\\n")
    signals = scan_for_signals(test_watchlist)
    
    if signals:
        print(f"Found {len(signals)} signals:\\n")
        for signal in signals:
            print(format_signal_message(signal['ticker'], signal))
            print("-" * 70)
    else:
        print("No signals detected")
    
    # Print performance stats
    print("\\n" + "="*70)
    print_performance_report(days=7)
