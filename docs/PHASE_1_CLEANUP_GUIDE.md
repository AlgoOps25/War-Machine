# Phase 1 Cleanup Guide - Remove Deprecation Warnings

## 📌 Status

**Completed:**
- ✅ `watchlist_funnel.py` - Updated to use `premarket_scanner`

**Remaining:**
- ⚠️ 1 more file imports `learning_policy` (needs to be found)

---

## 🔍 Finding the Remaining Import

### Step 1: Search for the Import

Run this in PowerShell from `C:\Dev\War-Machine`:

```powershell
# Find all files importing learning_policy
Select-String -Path *.py -Pattern "from learning_policy" -CaseSensitive

# Alternative: Search for the functions it exports
Select-String -Path *.py -Pattern "compute_confidence|grade_to_label|MIN_CONFIDENCE"
```

### Step 2: Likely Suspects

Based on the startup log sequence, the import is most likely in one of these files:

| File | Probability | Reason |
|------|-------------|--------|
| `sniper.py` | **HIGH** | Uses confidence scoring for signal evaluation |
| `signal_generator.py` | **MEDIUM** | Might compute grades/confidence |
| `breakout_detector.py` | **LOW** | Might use grade labels |
| `validator.py` | **LOW** | Might check MIN_CONFIDENCE threshold |

---

## ✏️ How to Update

### When You Find the File

**Old import:**
```python
from learning_policy import compute_confidence, grade_to_label, MIN_CONFIDENCE
```

**New import:**
```python
from ai_learning import compute_confidence, grade_to_label, MIN_CONFIDENCE
```

### Example Fix for `sniper.py`

If found in `sniper.py`, change this:
```python
# Near the top of the file
from learning_policy import compute_confidence
```

To this:
```python
# Near the top of the file  
from ai_learning import compute_confidence
```

---

## ✅ Verification

After updating the file:

```powershell
# Restart scanner
python scanner.py
```

**Expected result:**
- ✅ Only 1 deprecation warning (for `premarket_scanner_integration`) - FIXED
- ❌ No `learning_policy` warning - SUCCESS!

---

## 📝 Quick Reference

### What Changed in Phase 1

| Old Module | New Module | Status |
|------------|------------|--------|
| `premarket_scanner_integration.py` | `premarket_scanner.py` | ✅ Updated in `watchlist_funnel.py` |
| `premarket_scanner_pro.py` | `premarket_scanner.py` | ✅ No imports found |
| `learning_policy.py` | `ai_learning.py` | ⚠️ 1 file needs update |

### All New Imports (for reference)

```python
# Premarket scanning
from premarket_scanner import (
    scan_ticker,
    scan_watchlist,
    fetch_fundamental_data,
    run_momentum_screener,
    get_top_n_movers,
    print_momentum_summary,
    get_cache_stats
)

# AI learning & confidence scoring  
from ai_learning import (
    compute_confidence,
    grade_to_label,
    MIN_CONFIDENCE,
    learning_engine,
    AILearningEngine
)
```

---

## 🚀 After Cleanup Complete

Once both deprecation warnings are gone:

1. **Optional:** Delete the compatibility stubs
   ```powershell
   # These can be safely deleted (but not required)
   Remove-Item premarket_scanner_integration.py
   Remove-Item premarket_scanner_pro.py  
   Remove-Item learning_policy.py
   ```

2. **Move to Phase 2:** Continue with data management consolidation

---

## 🐛 Troubleshooting

### If You Can't Find the Import

```powershell
# Search in ALL subdirectories
Get-ChildItem -Recurse -Filter *.py | Select-String "learning_policy"

# Search for just the word (catches dynamic imports)
Get-ChildItem -Recurse -Filter *.py | Select-String "learning_policy" -SimpleMatch
```

### If Nothing Shows Up

The import might be:
- In a `.pyc` bytecode file (delete `__pycache__` folders)
- Dynamic: `__import__('learning_policy')`  
- In a Jupyter notebook (`.ipynb` files)

To clear bytecode cache:
```powershell
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
```

---

**Last Updated:** February 25, 2026  
**Status:** 1 of 2 imports updated (✅ premarket, ⚠️ learning_policy)
