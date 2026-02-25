# 🧹 Repository Cleanup Guide

## Overview

The `cleanup_repo.py` script reorganizes the War Machine repository from **100+ files in root** to a clean, structured layout with **~10 root files**.

---

## 📋 Before You Start

### Current Issues

```
War-Machine/
├── 📄 100+ files in root directory (❌ CLUTTERED)
├── 📄 5+ backup files being tracked
├── 📄 10+ duplicate documentation files
├── 📄 20+ experimental modules
└── 📄 No clear organization
```

### After Cleanup

```
War-Machine/
├── 📁 src/              # All Python modules
├── 📁 docs/             # All documentation
├── 📁 scripts/          # Utility scripts
├── 📁 tests/            # Test files
├── 📁 archive/          # Old/backup files
├── 📄 .gitignore
├── 📄 requirements.txt
├── 📄 railway.toml
├── 📄 nixpacks.toml
└── 📄 README.md
```

---

## 🚀 Usage

### Step 1: Preview Changes (DRY RUN)

**ALWAYS run dry-run first to see what will happen!**

```bash
python cleanup_repo.py --dry-run
```

#### Expected Output:

```
################################################################################
#                                                                              #
#                    WAR MACHINE REPOSITORY CLEANUP                            #
#                                                                              #
################################################################################

Running in DRY RUN mode - no files will be moved

================================================================================
  ORGANIZING FILES
================================================================================

Processing: src/core/
------------------------------------------------------------
[INFO] Would create: src/core
[INFO] Would move: scanner.py -> src/core/scanner.py
[INFO] Would move: signal_generator.py -> src/core/signal_generator.py
[INFO] Would move: signal_validator.py -> src/core/signal_validator.py
...

Processing: src/engines/
------------------------------------------------------------
[INFO] Would create: src/engines
[INFO] Would move: breakout_detector.py -> src/engines/breakout_detector.py
[INFO] Would move: daily_bias_engine.py -> src/engines/daily_bias_engine.py
[INFO] Would move: regime_filter.py -> src/engines/regime_filter.py
...

[INFO] Would create new README.md in root
[INFO] Would update .gitignore with backup file exclusions

================================================================================
  CLEANUP SUMMARY
================================================================================

[WARN] DRY RUN MODE - No files were actually moved

[INFO] Directories to create: 15
[INFO] Files to move: 87
[INFO] Issues found: 0

================================================================================
To execute cleanup, run:
  python cleanup_repo.py --execute
================================================================================
```

---

### Step 2: Review the Plan

**Check the output carefully:**

- ✅ All files accounted for?
- ✅ Directories make sense?
- ✅ No unexpected moves?
- ✅ Issues: 0?

If you see warnings or issues, address them before proceeding!

---

### Step 3: Execute Cleanup

**Once you're confident, run:**

```bash
python cleanup_repo.py --execute
```

#### Safety Confirmation:

```
Are you sure you want to proceed? (yes/no): yes
```

#### Expected Output:

```
[SUCCESS] Created: src/core
[SUCCESS] Moved: scanner.py -> src/core/scanner.py
[SUCCESS] Moved: signal_generator.py -> src/core/signal_generator.py
...
[SUCCESS] Created new README.md
[SUCCESS] Updated .gitignore

================================================================================
  CLEANUP SUMMARY
================================================================================

[INFO] Directories to create: 15
[INFO] Files to move: 87
[INFO] Issues found: 0

================================================================================
✅ CLEANUP COMPLETE!
================================================================================

Next steps:
  1. Review changes: git status
  2. Test system: python scripts/test_full_pipeline.py
  3. Commit changes: git add . && git commit -m 'Reorganize repository structure'
  4. Push to GitHub: git push origin main
```

---

## 🧪 Testing After Cleanup

### Verify Imports Still Work

```bash
cd War-Machine
python scripts/test_full_pipeline.py
```

**Expected:** All tests pass (8/8)

### Update Import Statements (if needed)

**Before:**
```python
from scanner import Scanner
from signal_generator import SignalGenerator
```

**After:**
```python
from src.core.scanner import Scanner
from src.core.signal_generator import SignalGenerator
```

> **Note:** The cleanup script moves files but doesn't update imports. You may need to add the root directory to `PYTHONPATH` or update imports.

---

## 📁 New Directory Structure

### `src/` - Core Application Code

```
src/
├── core/              # Main system components
│   ├── scanner.py
│   ├── signal_generator.py
│   ├── signal_validator.py
│   ├── position_manager.py
│   ├── data_manager.py
│   └── sniper.py
│
├── engines/           # Detection and analysis engines
│   ├── breakout_detector.py
│   ├── daily_bias_engine.py
│   ├── regime_filter.py
│   ├── vpvr_calculator.py
│   ├── bos_fvg_engine.py
│   └── gex_engine.py
│
├── indicators/        # Technical indicators
│   ├── technical_indicators.py
│   ├── cfw6_confirmation.py
│   └── mtf_convergence.py
│
├── filters/           # Signal filtering layers
│   ├── options_filter.py
│   ├── fundamentals_filter.py
│   ├── news_filter.py
│   └── insider_filter.py
│
├── analytics/         # Performance tracking
│   ├── signal_analytics.py
│   ├── performance_monitor.py
│   ├── performance_alerts.py
│   ├── eod_digest.py
│   └── pnl_digest.py
│
├── data/              # Data management
│   ├── candle_cache.py
│   ├── cache_manager.py
│   ├── options_data_manager.py
│   └── db_connection.py
│
├── screeners/         # Market scanners
│   ├── dynamic_screener.py
│   ├── momentum_screener_optimized.py
│   ├── premarket_scanner_pro.py
│   └── watchlist_funnel.py
│
├── optimizers/        # Parameter tuning
│   ├── historical_tuner.py
│   ├── parameter_optimizer.py
│   └── dynamic_thresholds.py
│
├── ml/                # Machine learning
│   ├── ai_learning.py
│   └── learning_policy.py
│
└── utils/             # Utility functions
    ├── exchange_hours.py
    ├── trade_calculator.py
    ├── discord_helpers.py
    └── config.py
```

### `docs/` - Documentation

```
docs/
├── TESTING_GUIDE.md
├── REGIME_FILTER_SUMMARY.md
├── README_REGIME_FILTER.md
├── deployment/
│   ├── DEPLOYMENT_READY.md
│   ├── INTEGRATION_COMPLETE.md
│   └── VPVR_INTEGRATION_GUIDE.md
└── fixes/
    ├── FIXES_FEB25_1030AM.md
    └── Fixes.txt
```

### `scripts/` - Utility Scripts

```
scripts/
├── test_full_pipeline.py
├── integrate_regime_filter.py
├── deploy.ps1
└── migrate_files.py
```

### `archive/` - Old/Deprecated Code

```
archive/
└── backups/
    ├── regime_filter.py.backup
    ├── regime_filter_original.py
    └── signal_validator.py.backup_*
```

---

## 🔧 Fixing Import Issues

### Option 1: Update All Imports (Recommended for Production)

**Find and replace across all files:**

```bash
# PowerShell
Get-ChildItem -Recurse -Filter *.py | ForEach-Object {
    (Get-Content $_.FullName) -replace '^from (\w+) import', 'from src.core.$1 import' | Set-Content $_.FullName
}
```

### Option 2: Add `src/` to PYTHONPATH (Quick Fix)

**In your shell:**

```bash
# PowerShell
$env:PYTHONPATH = "$PWD/src;$env:PYTHONPATH"

# Bash
export PYTHONPATH="$PWD/src:$PYTHONPATH"
```

**Or add to `scanner.py` / main entry point:**

```python
import sys
from pathlib import Path

# Add src/ to path
src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

# Now imports work
from core.scanner import Scanner
from engines.regime_filter import regime_filter
```

---

## 🚨 Rollback (If Something Goes Wrong)

### Before Committing

```bash
# Discard all changes
git reset --hard HEAD
```

### After Committing

```bash
# Revert to previous commit
git revert HEAD
git push origin main
```

---

## 📊 Benefits

### Before Cleanup
- ❌ 100+ files in root
- ❌ Hard to find anything
- ❌ Backup files tracked in git
- ❌ No clear structure
- ❌ Difficult onboarding

### After Cleanup
- ✅ ~10 files in root
- ✅ Clear organization
- ✅ Backups ignored by git
- ✅ Logical grouping
- ✅ Easy navigation

---

## 🎯 Next Steps

1. **Run dry-run:** `python cleanup_repo.py --dry-run`
2. **Review output:** Check for issues
3. **Execute cleanup:** `python cleanup_repo.py --execute`
4. **Test system:** `python scripts/test_full_pipeline.py`
5. **Fix imports:** Update import statements if needed
6. **Commit changes:** `git add . && git commit -m 'Reorganize repository'`
7. **Deploy:** `git push origin main`

---

## 🆘 Troubleshooting

### "File not found" during cleanup

**Issue:** File was already moved or doesn't exist

**Solution:** The script will log a warning but continue. Review the dry-run output first.

### Import errors after cleanup

**Issue:** Python can't find moved modules

**Solution:** Update imports or add `src/` to `PYTHONPATH` (see "Fixing Import Issues" above)

### Railway deployment fails

**Issue:** Entry point can't find modules

**Solution:** Update `railway.toml` start command:

```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "PYTHONPATH=./src python scanner.py"
```

---

## 📞 Support

If you encounter issues:

1. Check the dry-run output for warnings
2. Review the "Issues" section in the summary
3. Test imports with `python -c "from src.core.scanner import Scanner"`
4. Run `python scripts/test_full_pipeline.py` to verify system integrity

---

**Built with 🧹 by AlgoOps - Clean code, clean structure**
