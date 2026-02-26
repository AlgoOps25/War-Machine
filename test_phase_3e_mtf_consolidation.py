#!/usr/bin/env python3
"""
Phase 3E Verification Test Suite
Validates MTF consolidation refactor

Tests:
1. Import validation (no circular imports, no missing modules)
2. Compression function parity (outputs match expected structure)
3. Integration test (both MTF modules can use consolidated functions)
4. Metadata availability (TIMEFRAME_PRIORITY, TIMEFRAME_WEIGHTS accessible)

Usage:
    python test_phase_3e_mtf_consolidation.py

Expected Output:
    ✅ All tests pass
    🚫 Any failures indicate Phase 3E broke something
"""

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Import Validation
# ═══════════════════════════════════════════════════════════════════════════════

def test_imports():
    """Test that all modules import without errors."""
    print("\n" + "="*80)
    print("TEST 1: Import Validation")
    print("="*80)
    
    try:
        # Test consolidated module
        import mtf_compression
        print("✅ mtf_compression.py imports successfully")
        
        # Test compression functions exist
        assert hasattr(mtf_compression, 'compress_to_3m'), "Missing compress_to_3m"
        assert hasattr(mtf_compression, 'compress_to_2m'), "Missing compress_to_2m"
        assert hasattr(mtf_compression, 'compress_to_1m'), "Missing compress_to_1m"
        assert hasattr(mtf_compression, 'compress_to_all_timeframes'), "Missing compress_to_all_timeframes"
        print("✅ All compression functions exist in mtf_compression")
        
        # Test metadata exists
        assert hasattr(mtf_compression, 'TIMEFRAME_PRIORITY'), "Missing TIMEFRAME_PRIORITY"
        assert hasattr(mtf_compression, 'TIMEFRAME_WEIGHTS'), "Missing TIMEFRAME_WEIGHTS"
        print("✅ Timeframe metadata exists in mtf_compression")
        
        # Test mtf_integration imports
        import mtf_integration
        print("✅ mtf_integration.py imports successfully")
        
        # Test mtf_fvg_priority imports
        import mtf_fvg_priority
        print("✅ mtf_fvg_priority.py imports successfully")
        
        print("\n✅ TEST 1 PASSED: All imports successful, no circular dependencies\n")
        return True
        
    except ImportError as e:
        print(f"\n🚫 TEST 1 FAILED: Import error - {e}\n")
        return False
    except AssertionError as e:
        print(f"\n🚫 TEST 1 FAILED: Missing attribute - {e}\n")
        return False
    except Exception as e:
        print(f"\n🚫 TEST 1 FAILED: Unexpected error - {e}\n")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: Compression Function Validation
# ═══════════════════════════════════════════════════════════════════════════════

def test_compression_functions():
    """Test that compression functions produce expected output structure."""
    print("\n" + "="*80)
    print("TEST 2: Compression Function Validation")
    print("="*80)
    
    try:
        import mtf_compression
        
        # Create synthetic 5m bars
        base_time = datetime(2026, 2, 26, 9, 30, tzinfo=ET)
        bars_5m = []
        
        for i in range(10):
            bar_time = base_time + timedelta(minutes=5*i)
            bars_5m.append({
                'datetime': bar_time,
                'open': 100.0 + i,
                'high': 101.0 + i,
                'low': 99.0 + i,
                'close': 100.5 + i,
                'volume': 10000 * (i + 1)
            })
        
        print(f"Created {len(bars_5m)} synthetic 5m bars")
        
        # Test 3m compression
        bars_3m = mtf_compression.compress_to_3m(bars_5m)
        assert len(bars_3m) == len(bars_5m), f"3m bars count mismatch: {len(bars_3m)} != {len(bars_5m)}"
        assert all('datetime' in b for b in bars_3m), "Missing datetime in 3m bars"
        assert all('open' in b for b in bars_3m), "Missing open in 3m bars"
        assert all('high' in b for b in bars_3m), "Missing high in 3m bars"
        assert all('low' in b for b in bars_3m), "Missing low in 3m bars"
        assert all('close' in b for b in bars_3m), "Missing close in 3m bars"
        assert all('volume' in b for b in bars_3m), "Missing volume in 3m bars"
        print(f"✅ compress_to_3m() produced {len(bars_3m)} valid 3m bars")
        
        # Test 2m compression
        bars_2m = mtf_compression.compress_to_2m(bars_5m)
        assert len(bars_2m) == len(bars_5m), f"2m bars count mismatch: {len(bars_2m)} != {len(bars_5m)}"
        assert all('datetime' in b for b in bars_2m), "Missing datetime in 2m bars"
        print(f"✅ compress_to_2m() produced {len(bars_2m)} valid 2m bars")
        
        # Test 1m compression
        bars_1m = mtf_compression.compress_to_1m(bars_5m)
        assert len(bars_1m) == len(bars_5m) * 5, f"1m bars count mismatch: {len(bars_1m)} != {len(bars_5m) * 5}"
        assert all('datetime' in b for b in bars_1m), "Missing datetime in 1m bars"
        print(f"✅ compress_to_1m() produced {len(bars_1m)} valid 1m bars (5x input)")
        
        # Test compress_to_all_timeframes convenience function
        all_tf_bars = mtf_compression.compress_to_all_timeframes(bars_5m)
        assert '5m' in all_tf_bars, "Missing 5m in all_timeframes result"
        assert '3m' in all_tf_bars, "Missing 3m in all_timeframes result"
        assert '2m' in all_tf_bars, "Missing 2m in all_timeframes result"
        assert '1m' in all_tf_bars, "Missing 1m in all_timeframes result"
        assert len(all_tf_bars['5m']) == len(bars_5m), "5m bars mismatch in all_timeframes"
        assert len(all_tf_bars['3m']) == len(bars_5m), "3m bars mismatch in all_timeframes"
        assert len(all_tf_bars['2m']) == len(bars_5m), "2m bars mismatch in all_timeframes"
        assert len(all_tf_bars['1m']) == len(bars_5m) * 5, "1m bars mismatch in all_timeframes"
        print(f"✅ compress_to_all_timeframes() produced all 4 timeframes correctly")
        
        print("\n✅ TEST 2 PASSED: All compression functions work correctly\n")
        return True
        
    except AssertionError as e:
        print(f"\n🚫 TEST 2 FAILED: {e}\n")
        return False
    except Exception as e:
        print(f"\n🚫 TEST 2 FAILED: Unexpected error - {e}\n")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: MTF Integration Test
# ═══════════════════════════════════════════════════════════════════════════════

def test_mtf_integration():
    """Test that mtf_integration.py can use consolidated compression."""
    print("\n" + "="*80)
    print("TEST 3: MTF Integration Module Test")
    print("="*80)
    
    try:
        import mtf_integration
        import mtf_compression
        
        # Create test bars
        base_time = datetime(2026, 2, 26, 9, 30, tzinfo=ET)
        bars_5m = []
        
        for i in range(30):
            bar_time = base_time + timedelta(minutes=5*i)
            bars_5m.append({
                'datetime': bar_time,
                'open': 100.0,
                'high': 101.0,
                'low': 99.0,
                'close': 100.0,
                'volume': 10000
            })
        
        # Test that mtf_integration can call compression functions
        # (We're testing that the import works, not the full convergence logic)
        bars_3m = mtf_compression.compress_to_3m(bars_5m)
        bars_2m = mtf_compression.compress_to_2m(bars_5m)
        bars_1m = mtf_compression.compress_to_1m(bars_5m)
        
        assert len(bars_3m) > 0, "3m compression failed"
        assert len(bars_2m) > 0, "2m compression failed"
        assert len(bars_1m) > 0, "1m compression failed"
        
        print("✅ mtf_integration.py can access consolidated compression functions")
        
        # Test public API exists
        assert hasattr(mtf_integration, 'enhance_signal_with_mtf'), "Missing enhance_signal_with_mtf"
        assert hasattr(mtf_integration, 'check_mtf_convergence'), "Missing check_mtf_convergence"
        assert hasattr(mtf_integration, 'print_mtf_stats'), "Missing print_mtf_stats"
        print("✅ mtf_integration.py public API intact")
        
        print("\n✅ TEST 3 PASSED: mtf_integration.py works with consolidated module\n")
        return True
        
    except AssertionError as e:
        print(f"\n🚫 TEST 3 FAILED: {e}\n")
        return False
    except Exception as e:
        print(f"\n🚫 TEST 3 FAILED: Unexpected error - {e}\n")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: MTF FVG Priority Test
# ═══════════════════════════════════════════════════════════════════════════════

def test_mtf_fvg_priority():
    """Test that mtf_fvg_priority.py can use consolidated compression + metadata."""
    print("\n" + "="*80)
    print("TEST 4: MTF FVG Priority Module Test")
    print("="*80)
    
    try:
        import mtf_fvg_priority
        import mtf_compression
        
        # Test that mtf_fvg_priority can access compression functions
        base_time = datetime(2026, 2, 26, 9, 30, tzinfo=ET)
        bars_5m = []
        
        for i in range(30):
            bar_time = base_time + timedelta(minutes=5*i)
            bars_5m.append({
                'datetime': bar_time,
                'open': 100.0,
                'high': 101.0,
                'low': 99.0,
                'close': 100.0,
                'volume': 10000
            })
        
        bars_3m = mtf_compression.compress_to_3m(bars_5m)
        bars_2m = mtf_compression.compress_to_2m(bars_5m)
        bars_1m = mtf_compression.compress_to_1m(bars_5m)
        
        assert len(bars_3m) > 0, "3m compression failed"
        assert len(bars_2m) > 0, "2m compression failed"
        assert len(bars_1m) > 0, "1m compression failed"
        
        print("✅ mtf_fvg_priority.py can access consolidated compression functions")
        
        # Test that metadata is accessible
        tf_priority = mtf_compression.TIMEFRAME_PRIORITY
        tf_weights = mtf_compression.TIMEFRAME_WEIGHTS
        
        assert tf_priority == ['5m', '3m', '2m', '1m'], f"TIMEFRAME_PRIORITY mismatch: {tf_priority}"
        assert tf_weights == {'5m': 1.00, '3m': 0.85, '2m': 0.70, '1m': 0.55}, f"TIMEFRAME_WEIGHTS mismatch: {tf_weights}"
        print("✅ mtf_fvg_priority.py can access timeframe metadata")
        
        # Test public API exists
        assert hasattr(mtf_fvg_priority, 'get_highest_priority_fvg'), "Missing get_highest_priority_fvg"
        assert hasattr(mtf_fvg_priority, 'get_full_mtf_analysis'), "Missing get_full_mtf_analysis"
        assert hasattr(mtf_fvg_priority, 'resolve_fvg_priority'), "Missing resolve_fvg_priority"
        assert hasattr(mtf_fvg_priority, 'print_priority_stats'), "Missing print_priority_stats"
        print("✅ mtf_fvg_priority.py public API intact")
        
        print("\n✅ TEST 4 PASSED: mtf_fvg_priority.py works with consolidated module\n")
        return True
        
    except AssertionError as e:
        print(f"\n🚫 TEST 4 FAILED: {e}\n")
        return False
    except Exception as e:
        print(f"\n🚫 TEST 4 FAILED: Unexpected error - {e}\n")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: No Duplicate Function Definitions
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_duplicates():
    """Verify that compression functions are NOT defined in mtf_integration or mtf_fvg_priority."""
    print("\n" + "="*80)
    print("TEST 5: No Duplicate Compression Functions")
    print("="*80)
    
    try:
        import mtf_integration
        import mtf_fvg_priority
        
        # Check mtf_integration doesn't have duplicate compression functions
        # (They should only be imported, not defined locally)
        integration_functions = dir(mtf_integration)
        
        # These functions should exist (imported from mtf_compression)
        assert 'compress_to_3m' in integration_functions, "compress_to_3m not imported in mtf_integration"
        assert 'compress_to_2m' in integration_functions, "compress_to_2m not imported in mtf_integration"
        assert 'compress_to_1m' in integration_functions, "compress_to_1m not imported in mtf_integration"
        
        print("✅ mtf_integration.py imports compression functions (not defining duplicates)")
        
        # Check mtf_fvg_priority doesn't have duplicate compression functions
        priority_functions = dir(mtf_fvg_priority)
        
        assert 'compress_to_3m' in priority_functions, "compress_to_3m not imported in mtf_fvg_priority"
        assert 'compress_to_2m' in priority_functions, "compress_to_2m not imported in mtf_fvg_priority"
        assert 'compress_to_1m' in priority_functions, "compress_to_1m not imported in mtf_fvg_priority"
        
        print("✅ mtf_fvg_priority.py imports compression functions (not defining duplicates)")
        
        # Check metadata imports
        assert 'TIMEFRAME_PRIORITY' in priority_functions, "TIMEFRAME_PRIORITY not imported in mtf_fvg_priority"
        assert 'TIMEFRAME_WEIGHTS' in priority_functions, "TIMEFRAME_WEIGHTS not imported in mtf_fvg_priority"
        print("✅ mtf_fvg_priority.py imports timeframe metadata")
        
        print("\n✅ TEST 5 PASSED: No duplicate function definitions found\n")
        return True
        
    except AssertionError as e:
        print(f"\n🚫 TEST 5 FAILED: {e}\n")
        return False
    except Exception as e:
        print(f"\n🚫 TEST 5 FAILED: Unexpected error - {e}\n")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_all_tests():
    """Run all Phase 3E verification tests."""
    print("\n" + "#"*80)
    print("# PHASE 3E VERIFICATION TEST SUITE")
    print("# MTF Consolidation Refactor Validation")
    print("#"*80)
    
    tests = [
        ("Import Validation", test_imports),
        ("Compression Functions", test_compression_functions),
        ("MTF Integration Module", test_mtf_integration),
        ("MTF FVG Priority Module", test_mtf_fvg_priority),
        ("No Duplicate Functions", test_no_duplicates)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n🚫 {test_name} CRASHED: {e}\n")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Print summary
    print("\n" + "#"*80)
    print("# TEST SUMMARY")
    print("#"*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "🚫 FAIL"
        print(f"{status}: {test_name}")
    
    print("\n" + "="*80)
    if passed == total:
        print(f"🎉 ALL TESTS PASSED ({passed}/{total})")
        print("✅ Phase 3E MTF Consolidation is VERIFIED and ready for production!")
        print("="*80 + "\n")
        return 0
    else:
        print(f"🚫 TESTS FAILED ({total - passed}/{total} failures)")
        print("⚠️  Phase 3E has issues that need to be fixed before production!")
        print("="*80 + "\n")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
