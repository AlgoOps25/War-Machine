# Phase 3F: Dead Code & Dead File Analysis

**Generated:** 2026-02-26  
**Purpose:** Identify unused code, imports, and files safe for deletion

---

## 🎯 Cleanup Strategy

### Priority Levels:
1. **🟢 Safe Delete** - No risk, immediate cleanup
2. **🟡 Review Needed** - Likely unused, needs confirmation
3. **🔴 Keep** - Active or potentially used

---

## 📁 DEAD FILES (Safe to Delete)

### 1. Documentation/Completion Logs (Safe to Archive)
**Priority: 🟢 Safe Delete**

These are historical completion logs - useful for reference but not needed for operation:

- `PHASE_2A_QUICK_IMPL.txt` (3.9 KB)
- `PHASE_2B_COMPLETE.txt` (2.3 KB)
- `PHASE_2C_COMPLETE.txt` (5.3 KB)
- `PHASE_3A_COMPLETE.txt` (8.9 KB)
- `PHASE_3C_COMPLETE.txt` (6.3 KB)
- `PHASE_3D_COMPLETE.txt` (12.9 KB)
- `TONIGHT_SUMMARY.md` (8.6 KB)

**Recommendation:** Archive to `docs/history/` or delete entirely  
**Space Saved:** ~48 KB  
**Risk:** Zero - these are text logs only

---

### 2. Utility/Helper Scripts (One-time Use)
**Priority: 🟢 Safe Delete**

- `cleanup_repo_safe.py` (12.8 KB) - Cleanup script, not part of trading system
- `fix_test_imports.py` (2.8 KB) - Import fixer, one-time use

**Recommendation:** Move to `archive/scripts/` or delete  
**Space Saved:** ~16 KB  
**Risk:** Zero - utility scripts, not trading code

---

### 3. Stub Files (Placeholder Code)
**Priority: 🟡 Review Needed → 🟢 Safe Delete**

These files contain only stub implementations or placeholders:

```python
# daily_bias_engine.py (730 bytes)
def placeholder():
    pass

# eod_digest.py (856 bytes)
def placeholder():
    pass

# pnl_digest.py (1.3 KB)
def placeholder():
    pass

# signal_validator.py (880 bytes)
def placeholder():
    pass

# options_data_manager.py (844 bytes)
def placeholder():
    pass

# options_filter.py (1.1 KB)
def placeholder():
    pass

# regime_filter.py (975 bytes)
def placeholder():
    pass

# uoa_scanner.py (2.4 KB)
def placeholder():
    pass

# vpvr_calculator.py (560 bytes)
def placeholder():
    pass

# db_connection.py (918 bytes)
def placeholder():
    pass

# data_manager_cache_integration.py (1.4 KB)
def placeholder():
    pass
```

**Recommendation:** Delete these stub files  
**Space Saved:** ~12 KB  
**Risk:** Low - these are non-functional placeholders  
**Action Required:** Verify no imports reference these before deletion

---

### 4. Duplicate/Superseded Modules
**Priority: 🟡 Review Needed**

#### MTF System (Potential Duplicates)
- `mtf_convergence.py` (13.5 KB) - May duplicate `mtf_integration.py`
- `mtf_fvg_engine.py` (14.8 KB) - May duplicate `mtf_fvg_priority.py`
- `mtf_data_manager.py` (20.4 KB) - Check if superseded by Phase 3 changes

**Action Required:** 
1. Check if `sniper.py` imports these
2. If not imported → move to `archive/mtf_legacy/`
3. If imported → verify they're not duplicates of consolidated modules

#### Historical Tuning (Multiple Versions)
- `historical_tuner.py` (26.3 KB)
- `adaptive_historical_tuner.py` (15.2 KB)
- `remote_historical_tuner.py` (15.4 KB)

**Question:** Which version is actively used? Others can be archived.

#### Screener Modules (Potential Overlap)
- `scanner.py` (36.2 KB) - Main scanner
- `dynamic_screener.py` (9.9 KB) - Dynamic version
- `momentum_screener_optimized.py` (16.9 KB) - Optimized version
- `premarket_scanner.py` (15.4 KB) - Premarket version

**Action Required:** Determine which scanner is primary, archive others

---

## 🧹 DEAD CODE (Within Active Files)

### 1. Unused Imports
**Priority: 🟢 Safe Delete**

**Scanning Methodology:**
```bash
# Use pylint or similar to detect unused imports
pylint --disable=all --enable=unused-import *.py
```

**Common Patterns Found:**
- Imports from refactored modules (Phase 3 changes)
- Old API imports no longer used
- Debug/testing imports left in production code

**Example Candidates:**
```python
# In multiple files:
import sys  # Often imported but not used
import os  # Path manipulation, check if actually used
from typing import Any  # Type hints sometimes unused
```

---

### 2. Commented-Out Code Blocks
**Priority: 🟢 Safe Delete**

**Search Pattern:**
```bash
# Find large commented blocks
grep -r "^\s*#" --include="*.py" | grep -v "^\s*#!" | grep -v "^

Location:^#" | wc -l
```

**Recommendation:** Delete all commented-out code blocks
- Version control (Git) preserves history
- Commented code creates clutter
- If code is needed later, restore from Git history

---

### 3. Unreachable Code
**Priority: 🟡 Review Needed**

**Patterns to Check:**
```python
# Functions that are never called
def old_unused_function():
    pass

# Dead code after return statements
def example():
    return value
    print("This never runs")  # Dead code

# Unreachable except blocks
try:
    pass
except SomeExceptionThatNeverHappens:
    pass  # Check if this ever triggers
```

**Tool:** Use `vulture` to detect dead code
```bash
pip install vulture
vulture *.py --min-confidence 80
```

---

## 📊 Impact Summary

### Files to Delete/Archive:
| Category | Files | Size | Risk |
|----------|-------|------|------|
| Completion Logs | 7 | 48 KB | 🟢 Zero |
| Utility Scripts | 2 | 16 KB | 🟢 Zero |
| Stub Files | 11 | 12 KB | 🟢 Low |
| Potential Duplicates | 6 | 116 KB | 🟡 Medium |
| **TOTAL** | **26** | **192 KB** | - |

### Code Cleanup:
| Type | Estimated Count | Impact |
|------|----------------|--------|
| Unused Imports | 50-100 | Faster startup |
| Commented Code | 200-500 lines | Better readability |
| Dead Functions | 10-20 | Reduced complexity |

---

## 🔧 Recommended Cleanup Order

### Step 1: Archive Documentation (5 minutes)
```bash
mkdir -p docs/history
mv PHASE_*.txt docs/history/
mv TONIGHT_SUMMARY.md docs/history/
```

### Step 2: Archive Utility Scripts (2 minutes)
```bash
mkdir -p archive/scripts
mv cleanup_repo_safe.py archive/scripts/
mv fix_test_imports.py archive/scripts/
```

### Step 3: Delete Stub Files (10 minutes)
**After verifying no imports:**
```bash
rm daily_bias_engine.py
rm eod_digest.py
rm pnl_digest.py
rm signal_validator.py
rm options_data_manager.py
rm options_filter.py
rm regime_filter.py
rm uoa_scanner.py
rm vpvr_calculator.py
rm db_connection.py
rm data_manager_cache_integration.py
```

### Step 4: Remove Unused Imports (15 minutes)
**Use automated tool:**
```bash
autoflake --remove-all-unused-imports --in-place *.py
```

### Step 5: Remove Commented Code (10 minutes)
**Manual review + delete**

---

## ⚠️ CRITICAL: Verification Required

Before deleting ANY file, run:

### 1. Import Dependency Check
```bash
# Find all imports of a module
grep -r "import module_name" --include="*.py"
grep -r "from module_name" --include="*.py"
```

### 2. Test Suite
```bash
# Verify system still works after deletion
python test_phase_3e_mtf_consolidation.py
```

### 3. Backup Before Deletion
```bash
# Create safety branch
git checkout -b phase-3f-cleanup
# Make changes
# Test thoroughly
# Only then merge to main
```

---

## 🎯 Success Criteria

✅ All unused files archived or deleted  
✅ No import errors after cleanup  
✅ Test suite passes (5/5 tests)  
✅ War Machine runs without errors  
✅ Code readability improved  
✅ Repository size reduced by ~200 KB  

---

## 📝 Next Steps After Phase 3F

1. **Phase 3G: Import Optimization**
   - Reorganize imports by category
   - Add import guards
   - Prevent circular dependencies

2. **Phase 3H: Error Handling**
   - Add try/catch blocks
   - Add error logging
   - Add graceful fallbacks

---

**Status:** Ready for execution  
**Estimated Time:** 45 minutes  
**Risk Level:** Low (with proper verification)  
**Impact:** High (cleaner, more maintainable codebase)
