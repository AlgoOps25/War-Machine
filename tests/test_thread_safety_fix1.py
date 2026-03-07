#!/usr/bin/env python3
"""
Validation Tests for Fix #1: Thread-Safe State Management

Run after migration to verify thread safety is working correctly.

Usage:
    python tests/test_thread_safety_fix1.py
"""

import threading
import time
from datetime import datetime
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.thread_safe_state import get_state, ThreadSafeState

def test_singleton_pattern():
    """Test that get_state() always returns the same instance"""
    print("⏳ Testing singleton pattern...")
    state1 = get_state()
    state2 = get_state()
    assert state1 is state2, "get_state() should return same instance"
    print("✅ Singleton pattern verified")

def test_armed_signals_thread_safety():
    """Test concurrent armed_signals operations"""
    print("\n⏳ Testing armed_signals thread safety...")
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
    
    if errors:
        print("❌ Armed signals thread safety FAILED:")
        for error in errors:
            print(f"   {error}")
        return False
    
    print("✅ Armed signals thread safety verified (1000 operations across 10 threads)")
    return True

def test_watching_signals_thread_safety():
    """Test concurrent watching_signals operations"""
    print("\n⏳ Testing watching_signals thread safety...")
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
    
    if errors:
        print("❌ Watching signals thread safety FAILED:")
        for error in errors:
            print(f"   {error}")
        return False
    
    print("✅ Watching signals thread safety verified (1000 operations across 10 threads)")
    return True

def test_validator_stats_thread_safety():
    """Test concurrent validator stats updates"""
    print("\n⏳ Testing validator stats thread safety...")
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
    
    stats = state.get_validator_stats()
    
    if errors:
        print("❌ Validator stats thread safety FAILED:")
        for error in errors:
            print(f"   {error}")
        return False
    
    if stats['tested'] != expected_total:
        print(f"❌ Validator stats count mismatch: expected {expected_total}, got {stats['tested']}")
        return False
    
    print(f"✅ Validator stats thread safety verified (counted to {stats['tested']} correctly)")
    return True

def test_validation_call_tracker_thread_safety():
    """Test concurrent validation call tracking"""
    print("\n⏳ Testing validation call tracker thread safety...")
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
    
    tracker = state.get_validation_call_tracker()
    
    if errors:
        print("❌ Validation call tracker thread safety FAILED:")
        for error in errors:
            print(f"   {error}")
        return False
    
    if tracker.get(signal_id) != expected_count:
        print(f"❌ Call count mismatch: expected {expected_count}, got {tracker.get(signal_id)}")
        return False
    
    print(f"✅ Validation call tracker thread safety verified (counted {expected_count} calls correctly)")
    return True

def test_monitoring_timing_thread_safety():
    """Test concurrent dashboard/alert timing updates"""
    print("\n⏳ Testing monitoring timing thread safety...")
    state = get_state()
    
    errors = []
    
    def worker(thread_id: int):
        try:
            for i in range(50):
                now = datetime.now()
                if thread_id % 2 == 0:
                    state.update_last_dashboard_check(now)
                    retrieved = state.get_last_dashboard_check()
                else:
                    state.update_last_alert_check(now)
                    retrieved = state.get_last_alert_check()
                # Just verify it doesn't crash
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")
    
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    if errors:
        print("❌ Monitoring timing thread safety FAILED:")
        for error in errors:
            print(f"   {error}")
        return False
    
    print("✅ Monitoring timing thread safety verified (500 concurrent updates)")
    return True

def test_race_condition_scenario():
    """Test realistic race condition scenario"""
    print("\n⏳ Testing realistic race condition scenario...")
    state = get_state()
    state.clear_armed_signals()
    
    ticker = "TSLA"
    errors = []
    
    def set_worker():
        try:
            for i in range(100):
                data = {"position_id": i, "entry_price": 200.0 + i}
                state.set_armed_signal(ticker, data)
                time.sleep(0.001)  # Simulate work
        except Exception as e:
            errors.append(f"Set worker: {e}")
    
    def get_worker():
        try:
            for i in range(100):
                result = state.get_armed_signal(ticker)
                # Just verify it doesn't crash or return corrupted data
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
    
    if errors:
        print("❌ Race condition test FAILED:")
        for error in errors:
            print(f"   {error}")
        return False
    
    print("✅ Race condition scenario passed (concurrent set/get/remove operations)")
    return True

def main():
    print("="*70)
    print("Fix #1: Thread-Safe State Validation Tests")
    print("="*70)
    print()
    
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
            result = test()
            if result is False:
                failed += 1
            else:
                passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} CRASHED: {e}")
            failed += 1
    
    print()
    print("="*70)
    print(f"Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("✅ All thread-safety tests PASSED")
        print("\nThread-safe state management is working correctly!")
        print("You can now proceed with production deployment.")
        return 0
    else:
        print(f"❌ {failed} test(s) FAILED")
        print("\nPlease review the errors above before deploying.")
        return 1

if __name__ == '__main__':
    exit(main())
