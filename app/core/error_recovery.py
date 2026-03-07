#!/usr/bin/env python3
"""
Fix #2: Error Recovery & Graceful Degradation

Provides robust error handling with:
- Exponential backoff retries with jitter
- Circuit breaker pattern for failing services
- Fallback data sources
- Error context tracking
- Automatic recovery strategies

Usage:
    from app.core.error_recovery import with_retry, circuit_breaker, with_fallback
    
    @with_retry(max_attempts=3, backoff_base=2.0)
    def fetch_market_data(ticker: str) -> dict:
        return api.get_data(ticker)
    
    @circuit_breaker(failure_threshold=5, timeout=60)
    def call_external_service():
        return service.call()
    
    @with_fallback(fallback_fn=get_cached_data)
    def get_options_data(ticker: str):
        return api.get_options(ticker)
"""

import time
import random
import functools
import traceback
from typing import Callable, Any, Optional, TypeVar, ParamSpec
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import threading

P = ParamSpec('P')
T = TypeVar('T')

print("[ERROR-RECOVERY] ✅ Module initialized - graceful degradation enabled")

# ==============================================================================
# EXPONENTIAL BACKOFF WITH JITTER
# ==============================================================================

class RetryStrategy(Enum):
    """Retry strategy types"""
    EXPONENTIAL = "exponential"  # 1s, 2s, 4s, 8s...
    LINEAR = "linear"            # 1s, 2s, 3s, 4s...
    CONSTANT = "constant"        # 1s, 1s, 1s, 1s...

@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_attempts: int = 3
    backoff_base: float = 2.0  # seconds
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    jitter: bool = True
    jitter_range: float = 0.5  # +/- 50%
    retryable_exceptions: tuple = (Exception,)
    
def calculate_backoff(
    attempt: int,
    base: float,
    strategy: RetryStrategy,
    jitter: bool = True,
    jitter_range: float = 0.5
) -> float:
    """
    Calculate backoff delay with optional jitter.
    
    Args:
        attempt: Current retry attempt (1-indexed)
        base: Base delay in seconds
        strategy: Retry strategy to use
        jitter: Whether to add random jitter
        jitter_range: Jitter range as fraction (+/- 0.5 = +/-50%)
    
    Returns:
        Delay in seconds
    """
    if strategy == RetryStrategy.EXPONENTIAL:
        delay = base ** attempt
    elif strategy == RetryStrategy.LINEAR:
        delay = base * attempt
    else:  # CONSTANT
        delay = base
    
    if jitter:
        jitter_amount = delay * jitter_range
        delay += random.uniform(-jitter_amount, jitter_amount)
    
    return max(0.1, delay)  # Minimum 100ms

def with_retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
    jitter: bool = True,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """
    Decorator for automatic retry with exponential backoff.
    
    Args:
        max_attempts: Maximum number of attempts (including initial)
        backoff_base: Base delay for backoff calculation
        strategy: Retry strategy (EXPONENTIAL, LINEAR, CONSTANT)
        jitter: Whether to add random jitter to backoff
        retryable_exceptions: Tuple of exceptions to retry on
        on_retry: Optional callback called on each retry
    
    Example:
        @with_retry(max_attempts=3, backoff_base=2.0)
        def fetch_data(ticker: str) -> dict:
            return api.get_data(ticker)
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt == max_attempts:
                        # Final attempt failed - raise original exception
                        raise
                    
                    # Calculate backoff delay
                    delay = calculate_backoff(
                        attempt, backoff_base, strategy, jitter
                    )
                    
                    # Call retry callback if provided
                    if on_retry:
                        try:
                            on_retry(e, attempt)
                        except:
                            pass  # Don't let callback errors break retry logic
                    
                    print(
                        f"[RETRY] {func.__name__} attempt {attempt}/{max_attempts} "
                        f"failed: {type(e).__name__}: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    
                    time.sleep(delay)
            
            # Should never reach here, but just in case
            raise last_exception
        
        return wrapper
    return decorator

# ==============================================================================
# CIRCUIT BREAKER PATTERN
# ==============================================================================

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing - reject requests immediately
    HALF_OPEN = "half_open"  # Testing if service recovered

@dataclass
class CircuitBreaker:
    """
    Circuit breaker for failing services.
    
    Prevents cascading failures by stopping requests to failing services.
    
    States:
        CLOSED: Normal operation, requests pass through
        OPEN: Service failing, requests rejected immediately
        HALF_OPEN: Testing recovery, limited requests allowed
    """
    name: str
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 60.0  # seconds to wait before HALF_OPEN
    
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: Optional[datetime] = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    
    def call(self, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """
        Execute function through circuit breaker.
        
        Raises:
            CircuitBreakerOpenError: If circuit is open
        """
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if timeout elapsed
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    print(f"[CIRCUIT] {self.name}: OPEN → HALF_OPEN (testing recovery)")
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker {self.name} is OPEN - service unavailable"
                    )
        
        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        if self._last_failure_time is None:
            return True
        elapsed = (datetime.now() - self._last_failure_time).total_seconds()
        return elapsed >= self.timeout
    
    def _record_success(self):
        """Record successful call"""
        with self._lock:
            self._failure_count = 0
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    print(f"[CIRCUIT] {self.name}: HALF_OPEN → CLOSED (recovered)")
    
    def _record_failure(self):
        """Record failed call"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()
            
            if self._state == CircuitState.HALF_OPEN:
                # Failed during recovery test - back to OPEN
                self._state = CircuitState.OPEN
                self._success_count = 0
                print(f"[CIRCUIT] {self.name}: HALF_OPEN → OPEN (recovery failed)")
            
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                print(
                    f"[CIRCUIT] {self.name}: CLOSED → OPEN "
                    f"({self._failure_count} failures, timeout={self.timeout}s)"
                )
    
    def get_state(self) -> CircuitState:
        """Get current circuit state"""
        with self._lock:
            return self._state
    
    def reset(self):
        """Manually reset circuit breaker"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            print(f"[CIRCUIT] {self.name}: manually reset to CLOSED")

class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open"""
    pass

# Global circuit breakers
_circuit_breakers: dict[str, CircuitBreaker] = {}
_circuit_lock = threading.Lock()

def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout: float = 60.0
) -> CircuitBreaker:
    """Get or create circuit breaker by name"""
    with _circuit_lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                timeout=timeout
            )
        return _circuit_breakers[name]

def circuit_breaker(
    name: Optional[str] = None,
    failure_threshold: int = 5,
    timeout: float = 60.0
):
    """
    Decorator for circuit breaker pattern.
    
    Args:
        name: Circuit breaker name (defaults to function name)
        failure_threshold: Number of failures before opening circuit
        timeout: Seconds to wait before attempting recovery
    
    Example:
        @circuit_breaker(name="market_data_api", failure_threshold=5)
        def fetch_market_data(ticker: str) -> dict:
            return api.get_data(ticker)
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        breaker_name = name or func.__name__
        breaker = get_circuit_breaker(breaker_name, failure_threshold, timeout)
        
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return breaker.call(func, *args, **kwargs)
        
        return wrapper
    return decorator

# ==============================================================================
# FALLBACK DATA SOURCES
# ==============================================================================

def with_fallback(
    fallback_fn: Callable[P, T],
    fallback_exceptions: tuple = (Exception,),
    log_fallback: bool = True
):
    """
    Decorator for fallback data sources.
    
    If primary function fails, calls fallback function with same arguments.
    
    Args:
        fallback_fn: Fallback function to call on error
        fallback_exceptions: Exceptions that trigger fallback
        log_fallback: Whether to log fallback usage
    
    Example:
        @with_fallback(fallback_fn=get_cached_options_data)
        def get_live_options_data(ticker: str) -> dict:
            return api.get_options(ticker)
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except fallback_exceptions as e:
                if log_fallback:
                    print(
                        f"[FALLBACK] {func.__name__} failed: {type(e).__name__}: {e}. "
                        f"Using fallback: {fallback_fn.__name__}"
                    )
                return fallback_fn(*args, **kwargs)
        
        return wrapper
    return decorator

# ==============================================================================
# ERROR CONTEXT TRACKING
# ==============================================================================

@dataclass
class ErrorContext:
    """Context information for error tracking"""
    function_name: str
    error_type: str
    error_message: str
    timestamp: datetime
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    traceback_str: Optional[str] = None
    retry_count: int = 0
    recovered: bool = False

class ErrorTracker:
    """Track errors for monitoring and debugging"""
    
    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self._errors: list[ErrorContext] = []
        self._lock = threading.Lock()
    
    def record_error(
        self,
        func_name: str,
        error: Exception,
        args: tuple = (),
        kwargs: dict = None,
        retry_count: int = 0,
        include_traceback: bool = True
    ):
        """Record an error occurrence"""
        context = ErrorContext(
            function_name=func_name,
            error_type=type(error).__name__,
            error_message=str(error),
            timestamp=datetime.now(),
            args=args,
            kwargs=kwargs or {},
            traceback_str=traceback.format_exc() if include_traceback else None,
            retry_count=retry_count
        )
        
        with self._lock:
            self._errors.append(context)
            if len(self._errors) > self.max_history:
                self._errors.pop(0)
    
    def get_recent_errors(self, count: int = 10) -> list[ErrorContext]:
        """Get most recent errors"""
        with self._lock:
            return self._errors[-count:]
    
    def get_error_summary(self) -> dict:
        """Get summary statistics of errors"""
        with self._lock:
            if not self._errors:
                return {"total": 0, "by_type": {}, "by_function": {}}
            
            by_type = {}
            by_function = {}
            
            for error in self._errors:
                by_type[error.error_type] = by_type.get(error.error_type, 0) + 1
                by_function[error.function_name] = by_function.get(error.function_name, 0) + 1
            
            return {
                "total": len(self._errors),
                "by_type": by_type,
                "by_function": by_function
            }

# Global error tracker
error_tracker = ErrorTracker(max_history=100)

def get_error_tracker() -> ErrorTracker:
    """Get global error tracker instance"""
    return error_tracker

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def safe_execute(
    func: Callable[P, T],
    *args: P.args,
    default: T = None,
    log_errors: bool = True,
    **kwargs: P.kwargs
) -> T:
    """
    Safely execute a function, returning default value on error.
    
    Args:
        func: Function to execute
        *args: Positional arguments
        default: Default value to return on error
        log_errors: Whether to log errors
        **kwargs: Keyword arguments
    
    Returns:
        Function result or default value
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_errors:
            print(f"[SAFE-EXEC] {func.__name__} failed: {type(e).__name__}: {e}")
            error_tracker.record_error(func.__name__, e, args, kwargs)
        return default

def print_error_summary():
    """Print error summary for debugging"""
    summary = error_tracker.get_error_summary()
    
    if summary["total"] == 0:
        print("\n[ERROR-SUMMARY] No errors recorded")
        return
    
    print("\n" + "="*70)
    print("ERROR RECOVERY SUMMARY")
    print("="*70)
    print(f"Total Errors: {summary['total']}")
    print("\nBy Error Type:")
    for error_type, count in sorted(summary['by_type'].items(), key=lambda x: -x[1]):
        print(f"  {error_type}: {count}")
    print("\nBy Function:")
    for func_name, count in sorted(summary['by_function'].items(), key=lambda x: -x[1]):
        print(f"  {func_name}: {count}")
    print("="*70 + "\n")

def get_all_circuit_states() -> dict[str, str]:
    """Get states of all circuit breakers"""
    with _circuit_lock:
        return {name: breaker.get_state().value for name, breaker in _circuit_breakers.items()}

def reset_all_circuits():
    """Reset all circuit breakers (for testing/recovery)"""
    with _circuit_lock:
        for breaker in _circuit_breakers.values():
            breaker.reset()
