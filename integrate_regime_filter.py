"""
Integrate Regime Filter into Signal Validator
==============================================

This script patches signal_validator.py to add regime filter as CHECK 0A.

What it does:
  1. Backs up current signal_validator.py
  2. Adds regime_filter import at the top
  3. Adds CHECK 0A after daily bias (CHECK 0)
  4. Tests the integration

The regime filter will:
  - Block signals during VOLATILE markets (VIX > 30)
  - Block signals during CHOPPY markets (ADX < 25)
  - Allow signals during TRENDING markets
  - Apply heavy penalty (-30%) for unfavorable conditions

Usage:
  python integrate_regime_filter.py
"""

import os
import shutil
from datetime import datetime

def backup_validator():
    """Create backup of current signal_validator.py."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"signal_validator.py.backup_{timestamp}"
    
    if os.path.exists("signal_validator.py"):
        shutil.copy2("signal_validator.py", backup_file)
        print(f"✅ Backup created: {backup_file}")
        return True
    else:
        print("❌ signal_validator.py not found!")
        return False

def read_validator():
    """Read current signal_validator.py content."""
    try:
        with open("signal_validator.py", "r") as f:
            return f.read()
    except Exception as e:
        print(f"❌ Error reading signal_validator.py: {e}")
        return None

def check_if_already_integrated(content: str) -> bool:
    """Check if regime filter is already integrated."""
    return 'regime_filter' in content and 'CHECK 0A: REGIME FILTER' in content

def generate_regime_import() -> str:
    """Generate regime filter import statement."""
    return '''
# Import regime filter for market condition validation
try:
    from regime_filter import regime_filter
    REGIME_FILTER_ENABLED = True
    print("[VALIDATOR] ✅ Regime filter enabled (TRENDING/CHOPPY/VOLATILE)")
except ImportError:
    REGIME_FILTER_ENABLED = False
    regime_filter = None
    print("[VALIDATOR] ⚠️  regime_filter not available - regime filtering disabled")
'''

def generate_regime_check() -> str:
    """Generate regime filter validation check code."""
    return '''        # ════════════════════════════════════════════════
        # CHECK 0A: REGIME FILTER (Market Condition) [HEAVY PENALTY]
        # ════════════════════════════════════════════════
        if REGIME_FILTER_ENABLED and regime_filter:
            try:
                regime_state = regime_filter.get_regime_state()
                
                metadata['checks']['regime_filter'] = {
                    'regime': regime_state.regime,
                    'vix': regime_state.vix,
                    'spy_trend': regime_state.spy_trend,
                    'adx': regime_state.adx,
                    'favorable': regime_state.favorable,
                    'reason': regime_state.reason
                }
                
                # Apply regime-based confidence adjustment
                if not regime_state.favorable:
                    # Unfavorable regime (CHOPPY or VOLATILE)
                    regime_penalty = -0.30  # Heavy penalty for bad tape
                    confidence_adjustment += regime_penalty
                    failed_checks.append(f'REGIME_{regime_state.regime}')
                    
                    print(f"[VALIDATOR] ⚠️  {ticker} in {regime_state.regime} regime (-30%): {regime_state.reason}")
                    
                elif regime_state.regime == 'TRENDING':
                    # Favorable trending market
                    regime_boost = 0.05  # Small boost for good tape
                    confidence_adjustment += regime_boost
                    passed_checks.append('REGIME_TRENDING')
                    
                    print(f"[VALIDATOR] ✅ {ticker} in TRENDING regime (+5%): {regime_state.reason}")
                else:
                    # Neutral
                    passed_checks.append('REGIME_NEUTRAL')
                
            except Exception as e:
                metadata['checks']['regime_filter'] = {'error': str(e)}
                print(f"[VALIDATOR] Regime check error for {ticker}: {e}")
        
'''

def integrate_regime_filter():
    """Integrate regime filter into signal_validator.py."""
    
    print("\n" + "=" * 80)
    print("  REGIME FILTER INTEGRATION")
    print("=" * 80 + "\n")
    
    # Step 1: Backup
    print("[1/5] Creating backup...")
    if not backup_validator():
        return False
    
    # Step 2: Read current content
    print("[2/5] Reading signal_validator.py...")
    content = read_validator()
    if not content:
        return False
    
    # Step 3: Check if already integrated
    print("[3/5] Checking for existing integration...")
    if check_if_already_integrated(content):
        print("⚠️  Regime filter already integrated!")
        print("    No changes needed.")
        return True
    
    # Step 4: Add imports
    print("[4/5] Adding regime filter import...")
    
    # Find the VPVR import section (we'll add after it)
    vpvr_import_marker = 'print("[VALIDATOR] ⚠️  vpvr_calculator not available - volume profile disabled")'
    
    if vpvr_import_marker in content:
        # Insert regime import after VPVR import
        content = content.replace(
            vpvr_import_marker,
            vpvr_import_marker + generate_regime_import()
        )
        print("✅ Import added")
    else:
        print("❌ Could not find import location marker")
        return False
    
    # Step 5: Add regime check
    print("[5/5] Adding CHECK 0A (Regime Filter)...")
    
    # Find the daily bias check section (we'll add after it)
    bias_check_end = '''            except Exception as e:
                metadata['checks']['daily_bias'] = {'error': str(e)}
                print(f"[VALIDATOR] Bias check error for {ticker}: {e}")
        '''
    
    if bias_check_end in content:
        # Insert regime check after daily bias check
        content = content.replace(
            bias_check_end,
            bias_check_end + "\n" + generate_regime_check()
        )
        print("✅ CHECK 0A added")
    else:
        print("❌ Could not find CHECK 0 (daily bias) end marker")
        print("    Manual integration required.")
        return False
    
    # Step 6: Write updated content
    print("\n[6/6] Writing updated signal_validator.py...")
    try:
        with open("signal_validator.py", "w") as f:
            f.write(content)
        print("✅ File updated successfully")
    except Exception as e:
        print(f"❌ Error writing file: {e}")
        return False
    
    print("\n" + "=" * 80)
    print("✅ REGIME FILTER INTEGRATION COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("  1. Review the changes in signal_validator.py")
    print("  2. Run: python test_full_pipeline.py")
    print("  3. Commit and push changes to GitHub")
    print("  4. Deploy to Railway\n")
    
    return True

def test_integration():
    """Test the integration by importing and using the validator."""
    print("\n" + "=" * 80)
    print("  TESTING INTEGRATION")
    print("=" * 80 + "\n")
    
    try:
        # Reimport the validator
        import importlib
        import signal_validator
        importlib.reload(signal_validator)
        
        from signal_validator import get_validator
        
        validator = get_validator()
        
        print("✅ Validator imported successfully")
        
        # Test validation
        should_pass, adjusted_conf, metadata = validator.validate_signal(
            "SPY", "BUY", 500.0, 50_000_000, 0.75
        )
        
        # Check if regime filter was run
        if 'regime_filter' in metadata.get('checks', {}):
            regime_data = metadata['checks']['regime_filter']
            print(f"✅ Regime check executed")
            print(f"   Regime: {regime_data.get('regime')}")
            print(f"   Favorable: {regime_data.get('favorable')}")
            print(f"   Reason: {regime_data.get('reason')}")
            return True
        else:
            print("❌ Regime check not found in metadata")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import sys
    
    success = integrate_regime_filter()
    
    if success:
        print("\n" + "=" * 80)
        print("  Running integration test...")
        print("=" * 80)
        
        test_success = test_integration()
        
        if test_success:
            print("\n✅ Integration verified - regime filter is working!\n")
            sys.exit(0)
        else:
            print("\n⚠️  Integration completed but test failed")
            print("   Review error messages above\n")
            sys.exit(1)
    else:
        print("\n❌ Integration failed - see errors above\n")
        sys.exit(1)
