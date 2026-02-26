# Phase 2: Data Management Consolidation Plan

**Status:** 📋 Planning  
**Estimated Impact:** 2-3 files → 1 main file + utilities  
**Breaking Changes:** ZERO (compatibility stubs)  

---

## 🎯 Objectives

### Primary Goals
1. **Merge cache integration** into `data_manager.py`
2. **Organize database utilities** into `utils/` folder
3. **Maintain backwards compatibility** with existing imports
4. **Preserve all functionality** including:
   - 95%+ API reduction from caching
   - Smart startup backfill
   - Background cache sync
   - Cache warmup capabilities

### Success Criteria
- ✅ Zero import errors on startup
- ✅ Cache hit rate remains 100% on redeploy
- ✅ Startup time remains <30 seconds
- ✅ All existing code continues to work

---

## 📁 Current Structure

### Files to Consolidate

| File | Size | Purpose | Status |
|------|------|---------|--------|
| `data_manager.py` | ~800 lines | Core data management class | **Keep & enhance** |
| `data_manager_cache_integration.py` | 206 lines | Caching layer patches | **Merge in** |
| `candle_cache.py` | Unknown | Low-level cache operations | **Keep separate** |
| `db_connection.py` | ~100 lines | Database connection manager | **Move to utils/** |

### Import Map (Current)

```python
# scanner.py
from data_manager import data_manager, cleanup_old_bars
from data_manager_cache_integration import startup_backfill_with_cache

# Usage in scanner.py
startup_backfill_with_cache(data_manager, startup_watchlist, days=30)
data_manager.startup_intraday_backfill_today(startup_watchlist)
```

---

## 🔧 Consolidation Strategy

### Step 1: Enhance DataManager Class

**Add cache methods to `data_manager.py`:**

```python
class DataManager:
    # ... existing methods ...
    
    def startup_backfill_with_cache(self, tickers: List[str], days: int = 30):
        """Smart startup backfill using cache (moved from cache_integration)."""
        # Move logic from data_manager_cache_integration.startup_backfill_with_cache()
        pass
    
    def store_bars_with_cache(self, ticker: str, bars: List[Dict], quiet: bool = False) -> int:
        """Enhanced store_bars that auto-caches (moved from cache_integration)."""
        # Move logic from data_manager_cache_integration.store_bars_with_cache()
        pass
    
    def background_cache_sync(self, tickers: List[str]):
        """Hourly background cache sync (moved from cache_integration)."""
        # Move logic from data_manager_cache_integration.background_cache_sync()
        pass
    
    def warmup_cache(self, tickers: List[str], days: int = 60):
        """One-time cache warmup (moved from cache_integration)."""
        # Move logic from data_manager_cache_integration.warmup_cache()
        pass
```

### Step 2: Update Scanner Imports

**Before:**
```python
from data_manager import data_manager, cleanup_old_bars
from data_manager_cache_integration import startup_backfill_with_cache

# Usage
startup_backfill_with_cache(data_manager, startup_watchlist, days=30)
```

**After:**
```python
from data_manager import data_manager, cleanup_old_bars

# Usage
data_manager.startup_backfill_with_cache(startup_watchlist, days=30)
```

### Step 3: Create Compatibility Stub

**`data_manager_cache_integration.py` becomes:**

```python
"""
COMPATIBILITY STUB - Deprecated

Cache integration is now built into data_manager.py
This stub maintains backwards compatibility.

New code should use:
    data_manager.startup_backfill_with_cache(tickers, days=30)
    data_manager.store_bars_with_cache(ticker, bars)
    data_manager.background_cache_sync(tickers)
    data_manager.warmup_cache(tickers, days=60)
"""

from data_manager import data_manager

def startup_backfill_with_cache(dm, tickers, days=30):
    """Deprecated: Use data_manager.startup_backfill_with_cache() instead."""
    print("[DEPRECATED] data_manager_cache_integration.startup_backfill_with_cache() "
          "is deprecated. Use data_manager.startup_backfill_with_cache() instead.")
    return dm.startup_backfill_with_cache(tickers, days)

def store_bars_with_cache(dm, ticker, bars, quiet=False):
    """Deprecated: Use data_manager.store_bars_with_cache() instead."""
    return dm.store_bars_with_cache(ticker, bars, quiet)

def background_cache_sync(dm, tickers):
    """Deprecated: Use data_manager.background_cache_sync() instead."""
    return dm.background_cache_sync(tickers)

def warmup_cache(dm, tickers, days=60):
    """Deprecated: Use data_manager.warmup_cache() instead."""
    return dm.warmup_cache(tickers, days)
```

---

## 📋 Implementation Checklist

### Phase 2A: Data Manager Cache Merge

- [ ] Get `data_manager.py` structure (first 100 lines)
- [ ] Add cache methods to `DataManager` class
- [ ] Test: Verify startup backfill works
- [ ] Update `scanner.py` to use new method signature
- [ ] Convert `data_manager_cache_integration.py` to stub
- [ ] Test: Full scanner startup
- [ ] Commit: "Phase 2A: Merge cache integration into data_manager"

### Phase 2B: Database Utilities Organization (Optional)

- [ ] Create `utils/` directory
- [ ] Move `db_connection.py` → `utils/db_connection.py`
- [ ] Update all imports across codebase
- [ ] Create `utils/__init__.py` with convenience imports
- [ ] Test: Verify all database operations work
- [ ] Commit: "Phase 2B: Organize database utilities"

---

## 🧪 Testing Strategy

### Test 1: Startup Backfill
```powershell
python -c "from data_manager import data_manager; data_manager.startup_backfill_with_cache(['SPY', 'QQQ'], days=30)"
```

**Expected:**
- Cache hit rate: 100%
- No API calls (if cache is fresh)
- <5 second execution

### Test 2: Full Scanner Startup
```powershell
python scanner.py
```

**Expected:**
- No deprecation warnings (after scanner.py update)
- Cache stats show 100% hit rate
- All systems initialize normally

### Test 3: Import Compatibility
```powershell
python -c "from data_manager_cache_integration import startup_backfill_with_cache"
```

**Expected:**
- Deprecation warning prints
- Function still works
- No import errors

---

## 📊 Expected Results

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| **Active Files** | 2 | 1 + stub | -50% |
| **Lines of Code** | 1,006 | ~1,000 | -0.6% |
| **Import Complexity** | High | Low | ✅ Simplified |
| **Cache Performance** | 95%+ | 95%+ | ✅ Maintained |
| **Startup Time** | <30s | <30s | ✅ Maintained |
| **Breaking Changes** | N/A | **ZERO** | ✅ Compatible |

---

## 🚨 Risk Assessment

### Low Risk
- ✅ All functionality is being moved, not rewritten
- ✅ Compatibility stub prevents breaking changes
- ✅ Can be rolled back easily
- ✅ No complex refactoring required

### Mitigation
- Keep git history clean (one commit per step)
- Test each step before moving to next
- Maintain compatibility stubs until Phase 3

---

## 🚀 Next Steps

### To Proceed

**Run this command:**
```powershell
Get-Content .\data_manager.py -TotalCount 100
```

This will show the class structure so I can properly integrate the cache methods.

### Alternative: Skip to Phase 2C

If you want to tackle a different consolidation first:
- **Phase 2C:** Performance Reporting (5 → 2 files)
- **Phase 2D:** Scanner Optimizer Finalization

---

**Last Updated:** February 25, 2026  
**Status:** Awaiting `data_manager.py` structure review
