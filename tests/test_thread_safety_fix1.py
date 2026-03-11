#!/usr/bin/env python3
"""
Validation Tests for Fix #1: Thread-Safe State Management

Run after migration to verify thread safety is working correctly.

Usage:
    pytest tests/test_thread_safety_fix1.py -v
    python tests/test_thread_safety_fix1.py       # legacy direct runner
"""

import threading
import time
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.thread_safe_state import get_state, ThreadSafeState


def test_singleton_pattern():
    """Test that get_state() always returns the same instance."""
    state1 = get_state()
    state2 = get_state()
    assert state1 is state2, "get_state() should return same instance"


def test_armed_signals_thread_safety():
    """Test concurrent armed_signals operations."""
    state = get_state()
    state.clear_armed_signals()

    errors = []

    def worker(thread_id: int):
        try:
            for i in range(100):
                ticker = f"TICKER{thread_id}_{i}"
                data = {"position_id": i, "direction": "bull", "entry_price": 100.0}
                state.set_armed_signal(ticker, data)
                retrieved = state.get_armed_signal(ticker)
                assert retrieved is not None, f"Failed to retrieve {ticker}"
                assert retrieved["position_id"] == i
                state.remove_armed_signal(ticker)
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Armed signals thread safety errors: {errors}"


def test_watching_signals_thread_safety():
    """Test concurrent watching_signals operations."""
    state = get_state()
    state.clear_watching_signals()

    errors = []

    def worker(thread_id: int):
        try:
            for i in range(100):
                ticker = f"WATCH{thread_id}_{i}"
                data = {"direction": "bear", "breakout_idx": i, "or_high": 150.0}
                state.set_watching_signal(ticker, data)
                retrieved = state.get_watching_signal(ticker)
                assert retrieved is not None
                assert retrieved["breakout_idx"] == i
                state.remove_watching_signal(ticker)
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Watching signals thread safety errors: {errors}"


def test_validator_stats_thread_safety():
    """Test concurrent validator stats updates."""
    state = get_state()
    state.reset_validator_stats()

    errors = []
    expected_total = 10 * 100  # 10 threads * 100 increments each

    def worker(thread_id: int):
        try:
            for i in range(100):
                state.increment_validator_stat('tested')
                if i % 2 == 0:
                    state.increment_validator_stat('passed')
                else:
                    state.increment_validator_stat('filtered')
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Validator stats errors: {errors}"
    stats = state.get_validator_stats()
    assert stats['tested'] == expected_total, (
        f"Validator stats count mismatch: expected {expected_total}, got {stats['tested']}"
    )


def test_validation_call_tracker_thread_safety():
    """Test concurrent validation call tracking."""
    state = get_state()
    state.clear_validation_call_tracker()

    errors = []
    signal_id = "TEST_AAPL_bull_150.00_20260307"
    expected_count = 100  # 10 threads * 10 calls each

    def worker(thread_id: int):
        try:
            for i in range(10):
                state.track_validation_call(signal_id)
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Validation call tracker errors: {errors}"
    tracker = state.get_validation_call_tracker()
    assert tracker.get(signal_id) == expected_count, (
        f"Call count mismatch: expected {expected_count}, got {tracker.get(signal_id)}"
    )


def test_monitoring_timing_thread_safety():
    """Test concurrent dashboard/alert timing updates."""
    state = get_state()

    errors = []

    def worker(thread_id: int):
        try:
            for i in range(50):
                now = datetime.now()
                if thread_id % 2 == 0:
                    state.update_last_dashboard_check(now)
                    state.get_last_dashboard_check()
                else:
                    state.update_last_alert_check(now)
                    state.get_last_alert_check()
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Monitoring timing errors: {errors}"


def test_race_condition_scenario():
    """Test realistic concurrent set/get/remove race condition."""
    state = get_state()
    state.clear_armed_signals()

    ticker = "TSLA"
    errors = []

    def set_worker():
        try:
            for i in range(100):
                data = {"position_id": i, "entry_price": 200.0 + i}
                state.set_armed_signal(ticker, data)
                time.sleep(0.001)
        except Exception as e:
            errors.append(f"Set worker: {e}")

    def get_worker():
        try:
            for i in range(100):
                result = state.get_armed_signal(ticker)
                if result is not None:
                    assert isinstance(result, dict)
                time.sleep(0.001)
        except Exception as e:
            errors.append(f"Get worker: {e}")

    def remove_worker():
        try:
            for i in range(50):
                state.remove_armed_signal(ticker)
                time.sleep(0.002)
        except Exception as e:
            errors.append(f"Remove worker: {e}")

    threads = [
        threading.Thread(target=set_worker),
        threading.Thread(target=set_worker),
        threading.Thread(target=get_worker),
        threading.Thread(target=get_worker),
        threading.Thread(target=remove_worker),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Race condition errors: {errors}"


# ─────────────────────────────────────────────────────────────────────────────
# Legacy direct-run entry point (python tests/test_thread_safety_fix1.py)
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("Fix #1: Thread-Safe State Validation Tests")
    print("=" * 70)

    tests = [
        test_singleton_pattern,
        test_armed_signals_thread_safety,
        test_watching_signals_thread_safety,
        test_validator_stats_thread_safety,
        test_validation_call_tracker_thread_safety,
        test_monitoring_timing_thread_safety,
        test_race_condition_scenario,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"✅ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} CRASHED: {e}")
            failed += 1

    print()
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("✅ All thread-safety tests PASSED")
        return 0
    else:
        print(f"❌ {failed} test(s) FAILED")
        return 1


if __name__ == '__main__':
    exit(main())
