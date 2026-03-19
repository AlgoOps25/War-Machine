"""
Thread-Safe State Manager for War Machine Trading System

Provides thread-safe access to global state dictionaries:
- armed_signals: Active positions waiting for entry/exit
- watching_signals: Tickers being monitored for FVG formation
- validator_stats: Validation statistics tracking
- validation_call_tracker: Prevents duplicate validations
- dashboard/alert timing: Phase 4 monitoring state

All mutations are protected by threading.Lock() to prevent race conditions.
"""
import threading
from typing import Dict, Any, Optional
from datetime import datetime
import logging
logger = logging.getLogger(__name__)

class ThreadSafeState:
    """Thread-safe singleton for managing global trading system state"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize all state dictionaries and their locks"""
        # Armed signals state
        self._armed_signals: Dict[str, Dict[str, Any]] = {}
        self._armed_lock = threading.Lock()
        self._armed_loaded = False
        
        # Watching signals state
        self._watching_signals: Dict[str, Dict[str, Any]] = {}
        self._watching_lock = threading.Lock()
        self._watches_loaded = False
        
        # Validator statistics
        self._validator_stats = {
            'tested': 0,
            'passed': 0,
            'filtered': 0,
            'boosted': 0,
            'penalized': 0
        }
        self._validator_stats_lock = threading.Lock()
        
        # Validation call tracker (prevents duplicates)
        self._validation_call_tracker: Dict[str, int] = {}
        self._validation_tracker_lock = threading.Lock()
        
        # Phase 4 monitoring timing
        self._last_dashboard_check = datetime.now()
        self._last_alert_check = datetime.now()
        self._monitoring_lock = threading.Lock()
    
    # ==================== ARMED SIGNALS ====================
    
    def get_armed_signal(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get armed signal data for a ticker (thread-safe)"""
        with self._armed_lock:
            return self._armed_signals.get(ticker)
    
    def set_armed_signal(self, ticker: str, data: Dict[str, Any]) -> None:
        """Set armed signal data for a ticker (thread-safe)"""
        with self._armed_lock:
            self._armed_signals[ticker] = data
    
    def remove_armed_signal(self, ticker: str) -> bool:
        """Remove armed signal for a ticker (thread-safe). Returns True if existed."""
        with self._armed_lock:
            if ticker in self._armed_signals:
                del self._armed_signals[ticker]
                return True
            return False
    
    def ticker_is_armed(self, ticker: str) -> bool:
        """Check if ticker is armed (thread-safe)"""
        with self._armed_lock:
            return ticker in self._armed_signals
    
    def get_all_armed_signals(self) -> Dict[str, Dict[str, Any]]:
        """Get copy of all armed signals (thread-safe)"""
        with self._armed_lock:
            return self._armed_signals.copy()
    
    def update_armed_signals_bulk(self, signals: Dict[str, Dict[str, Any]]) -> None:
        """Bulk update armed signals from DB load (thread-safe)"""
        with self._armed_lock:
            self._armed_signals.update(signals)
    
    def clear_armed_signals(self) -> None:
        """Clear all armed signals (thread-safe)"""
        with self._armed_lock:
            self._armed_signals.clear()
            self._armed_loaded = False
    
    def is_armed_loaded(self) -> bool:
        """Check if armed signals have been loaded from DB"""
        with self._armed_lock:
            return self._armed_loaded
    
    def set_armed_loaded(self, loaded: bool) -> None:
        """Set armed signals loaded status"""
        with self._armed_lock:
            self._armed_loaded = loaded
    
    # ==================== WATCHING SIGNALS ====================
    
    def get_watching_signal(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get watching signal data for a ticker (thread-safe)"""
        with self._watching_lock:
            return self._watching_signals.get(ticker)
    
    def set_watching_signal(self, ticker: str, data: Dict[str, Any]) -> None:
        """Set watching signal data for a ticker (thread-safe)"""
        with self._watching_lock:
            self._watching_signals[ticker] = data
    
    def remove_watching_signal(self, ticker: str) -> bool:
        """Remove watching signal for a ticker (thread-safe). Returns True if existed."""
        with self._watching_lock:
            if ticker in self._watching_signals:
                del self._watching_signals[ticker]
                return True
            return False
    
    def ticker_is_watching(self, ticker: str) -> bool:
        """Check if ticker is being watched (thread-safe)"""
        with self._watching_lock:
            return ticker in self._watching_signals
    
    def get_all_watching_signals(self) -> Dict[str, Dict[str, Any]]:
        """Get copy of all watching signals (thread-safe)"""
        with self._watching_lock:
            return self._watching_signals.copy()
    
    def update_watching_signals_bulk(self, signals: Dict[str, Dict[str, Any]]) -> None:
        """Bulk update watching signals from DB load (thread-safe)"""
        with self._watching_lock:
            self._watching_signals.update(signals)
    
    def update_watching_signal_field(self, ticker: str, field: str, value: Any) -> bool:
        """Update a specific field in watching signal (thread-safe). Returns True if ticker existed."""
        with self._watching_lock:
            if ticker in self._watching_signals:
                self._watching_signals[ticker][field] = value
                return True
            return False
    
    def clear_watching_signals(self) -> None:
        """Clear all watching signals (thread-safe)"""
        with self._watching_lock:
            self._watching_signals.clear()
            self._watches_loaded = False
    
    def is_watches_loaded(self) -> bool:
        """Check if watching signals have been loaded from DB"""
        with self._watching_lock:
            return self._watches_loaded
    
    def set_watches_loaded(self, loaded: bool) -> None:
        """Set watching signals loaded status"""
        with self._watching_lock:
            self._watches_loaded = loaded
    
    # ==================== VALIDATOR STATS ====================
    
    def increment_validator_stat(self, stat_name: str, amount: int = 1) -> None:
        """Increment a validator statistic (thread-safe)"""
        with self._validator_stats_lock:
            if stat_name in self._validator_stats:
                self._validator_stats[stat_name] += amount
    
    def get_validator_stats(self) -> Dict[str, int]:
        """Get copy of validator statistics (thread-safe)"""
        with self._validator_stats_lock:
            return self._validator_stats.copy()
    
    def reset_validator_stats(self) -> None:
        """Reset validator statistics (thread-safe)"""
        with self._validator_stats_lock:
            for key in self._validator_stats:
                self._validator_stats[key] = 0
    
    # ==================== VALIDATION CALL TRACKER ====================
    
    def track_validation_call(self, signal_id: str) -> int:
        """
        Track a validation call for signal_id.
        Returns the call count (1 for first call, 2+ for duplicates).
        Thread-safe.
        """
        with self._validation_tracker_lock:
            call_count = self._validation_call_tracker.get(signal_id, 0) + 1
            self._validation_call_tracker[signal_id] = call_count
            return call_count
    
    def get_validation_call_tracker(self) -> Dict[str, int]:
        """Get copy of validation call tracker (thread-safe)"""
        with self._validation_tracker_lock:
            return self._validation_call_tracker.copy()
    
    def clear_validation_call_tracker(self) -> None:
        """Clear validation call tracker (thread-safe)"""
        with self._validation_tracker_lock:
            self._validation_call_tracker.clear()
    
    # ==================== MONITORING TIMING ====================
    
    def get_last_dashboard_check(self) -> datetime:
        """Get last dashboard check time (thread-safe)"""
        with self._monitoring_lock:
            return self._last_dashboard_check
    
    def update_last_dashboard_check(self, check_time: datetime) -> None:
        """Update last dashboard check time (thread-safe)"""
        with self._monitoring_lock:
            self._last_dashboard_check = check_time
    
    def get_last_alert_check(self) -> datetime:
        """Get last alert check time (thread-safe)"""
        with self._monitoring_lock:
            return self._last_alert_check
    
    def update_last_alert_check(self, check_time: datetime) -> None:
        """Update last alert check time (thread-safe)"""
        with self._monitoring_lock:
            self._last_alert_check = check_time


# Create singleton instance
_state = ThreadSafeState()

# Export convenience functions for backward compatibility
def get_state() -> ThreadSafeState:
    """Get the thread-safe state singleton instance"""
    return _state


# Convenience functions for armed signals
def get_armed_signal(ticker: str) -> Optional[Dict[str, Any]]:
    return _state.get_armed_signal(ticker)

def set_armed_signal(ticker: str, data: Dict[str, Any]) -> None:
    _state.set_armed_signal(ticker, data)

def remove_armed_signal(ticker: str) -> bool:
    return _state.remove_armed_signal(ticker)

def ticker_is_armed(ticker: str) -> bool:
    return _state.ticker_is_armed(ticker)


# Convenience functions for watching signals
def get_watching_signal(ticker: str) -> Optional[Dict[str, Any]]:
    return _state.get_watching_signal(ticker)

def set_watching_signal(ticker: str, data: Dict[str, Any]) -> None:
    _state.set_watching_signal(ticker, data)

def remove_watching_signal(ticker: str) -> bool:
    return _state.remove_watching_signal(ticker)

def ticker_is_watching(ticker: str) -> bool:
    return _state.ticker_is_watching(ticker)


# Convenience functions for validator stats
def increment_validator_stat(stat_name: str, amount: int = 1) -> None:
    _state.increment_validator_stat(stat_name, amount)

def get_validator_stats() -> Dict[str, int]:
    return _state.get_validator_stats()


