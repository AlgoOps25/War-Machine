# Phase 3G + 3H: Production Hardening Plan

**Generated:** 2026-02-26 12:18 AM EST  
**Scope:** Import optimization + Error handling for production stability

---

## 🎯 OBJECTIVE

Harden War Machine for production with:
1. **Clean import organization** - prevent circular dependencies
2. **Robust error handling** - graceful degradation, no crashes
3. **Production logging** - debug issues in live trading

---

## ✅ PHASE 3G: IMPORT OPTIMIZATION

### Current State Analysis

**Findings from `sniper.py` (main entry point):**

✅ **Good Patterns Already in Place:**
- Try/except blocks around optional imports (Phase 4, MTF, regime_filter, etc.)
- Feature flags (PHASE_4_ENABLED, MTF_ENABLED, etc.)
- Graceful degradation when modules unavailable
- Non-fatal import philosophy

⚠️ **Areas for Improvement:**
1. **Import organization** - Mix of stdlib, third-party, and local imports
2. **Circular import risk** - `sniper.py` imports many modules that might import each other
3. **Import placement** - Some imports scattered throughout file
4. **Missing import guards** - A few imports without try/except

---

### Import Organization Standard

**PEP 8 Best Practice:**

```python
# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════

# 1. Standard library imports
import traceback
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

# 2. Third-party imports
import requests

# 3. Local application imports (critical)
from discord_helpers import send_options_signal_alert, send_simple_message
from data_manager import data_manager
from position_manager import position_manager
from bos_fvg_engine import scan_bos_fvg, is_force_close_time
from trade_calculator import compute_stop_and_targets, get_adaptive_fvg_threshold
import config

# 4. Optional feature imports (non-fatal)
try:
    from ai_learning import learning_engine, compute_confidence
    AI_LEARNING_ENABLED = True
except ImportError as e:
    print(f"[SNIPER] ⚠️  AI learning disabled: {e}")
    AI_LEARNING_ENABLED = False
    # Stub functions
    class _DummyLearningEngine:
        def get_ticker_confidence_multiplier(self, ticker): return 1.0
    learning_engine = _DummyLearningEngine()
    def compute_confidence(grade, tf, ticker): return 0.60

# Repeat for all optional modules...
```

---

### Benefits of Proper Import Organization

1. **✅ Clear dependency hierarchy** - Easy to see what's required vs optional
2. **✅ Prevents circular imports** - Grouped by dependency level
3. **✅ Fast debugging** - Know where to look when imports fail
4. **✅ Better IDE support** - Auto-complete and type checking work better
5. **✅ Railway-friendly** - Missing modules don't crash deployment

---

### Implementation Strategy

**Status: ✅ ALREADY MOSTLY IMPLEMENTED**

`sniper.py` already follows best practices! The try/except pattern around optional imports is **exactly** what we want.

**Minor improvements needed:**

1. **Group imports by category** (5 min)
   - Add comment headers: `# Standard library`, `# Third-party`, `# Local`
   - Reorder to match PEP 8 standard

2. **Document feature flags** (5 min)
   - Add comment explaining each `*_ENABLED` flag
   - Document stub function behavior

3. **Verify no circular imports** (10 min)
   - Run: `python -m sniper` and check for ImportError
   - If errors, refactor problem imports

---

## ✅ PHASE 3H: ERROR HANDLING

### Current Error Handling Assessment

**Findings from `sniper.py`:**

✅ **Good Patterns:**
- Main `process_ticker()` wrapped in try/except with traceback
- Safe database operations with try/except
- Optional module fallbacks

⚠️ **Critical Gaps:**

1. **API calls not protected**
   ```python
   # Current (DANGEROUS in production):
   bars_session = data_manager.get_today_session_bars(ticker)
   
   # Should be:
   try:
       bars_session = data_manager.get_today_session_bars(ticker)
       if not bars_session:
           raise ValueError("No bars returned")
   except Exception as e:
       print(f"[{ticker}] ❌ Data fetch failed: {e}")
       return  # Graceful exit, don't crash
   ```

2. **Discord webhook failures can crash**
   ```python
   # Current:
   send_options_signal_alert(...)
   
   # Should be:
   try:
       send_options_signal_alert(...)
   except Exception as e:
       print(f"[DISCORD] ❌ Alert failed: {e} (continuing...)")
       # Don't block trading because Discord is down!
   ```

3. **Database operations need rollback**
   ```python
   # Current:
   cursor.execute(...)
   conn.commit()
   
   # Should be:
   try:
       cursor.execute(...)
       conn.commit()
   except Exception as e:
       conn.rollback()
       print(f"[DB] ❌ Operation failed: {e}")
       raise  # Re-raise if critical
   ```

4. **No retry logic for transient failures**
   - API timeouts should retry (EODHD, Tradier, etc.)
   - Discord webhooks should retry once
   - Database deadlocks should retry

---

### Error Handling Patterns

#### Pattern 1: API Calls (with retry)

```python
def _fetch_with_retry(func, max_retries=3, delay=1.0):
    """Generic retry wrapper for API calls."""
    for attempt in range(max_retries):
        try:
            return func()
        except requests.Timeout:
            if attempt == max_retries - 1:
                raise
            print(f"[API] ⏳ Timeout, retrying ({attempt+1}/{max_retries})...")
            time.sleep(delay * (attempt + 1))  # Exponential backoff
        except requests.RequestException as e:
            print(f"[API] ❌ Request failed: {e}")
            raise
    return None

# Usage:
try:
    bars = _fetch_with_retry(lambda: data_manager.get_today_session_bars(ticker))
    if not bars:
        print(f"[{ticker}] ⚠️ No data available, skipping")
        return
except Exception as e:
    print(f"[{ticker}] ❌ Data fetch failed after retries: {e}")
    return
```

#### Pattern 2: Discord Alerts (non-blocking)

```python
def _send_alert_safe(alert_func, *args, **kwargs):
    """Send Discord alert without blocking on failure."""
    try:
        alert_func(*args, **kwargs)
        return True
    except Exception as e:
        print(f"[DISCORD] ❌ Alert failed (non-fatal): {e}")
        # Log to file for debugging
        with open("discord_failures.log", "a") as f:
            f.write(f"{datetime.now()} | {e}\n")
        return False

# Usage:
_send_alert_safe(send_options_signal_alert, ticker=ticker, ...)
# Trading continues even if Discord is down!
```

#### Pattern 3: Database Operations (with rollback)

```python
def _db_operation_safe(operation_func):
    """Execute database operation with automatic rollback on error."""
    conn = None
    try:
        conn = get_conn()
        result = operation_func(conn)
        conn.commit()
        return result
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[DB] ❌ Operation failed (rolled back): {e}")
        raise
    finally:
        if conn:
            conn.close()

# Usage:
try:
    _db_operation_safe(lambda conn: _persist_armed_signal(ticker, data, conn))
except Exception as e:
    print(f"[{ticker}] ⚠️ Failed to persist armed signal (memory only)")
    # Signal still works, just not persisted to DB
```

#### Pattern 4: Optional Feature Graceful Degradation

```python
def _safe_feature_call(feature_func, feature_name, default_value, *args, **kwargs):
    """Call optional feature with graceful fallback."""
    try:
        return feature_func(*args, **kwargs)
    except Exception as e:
        print(f"[{feature_name}] ⚠️ Feature unavailable: {e} (using default)")
        return default_value

# Usage:
mtf_boost = _safe_feature_call(
    enhance_signal_with_mtf,
    "MTF",
    default_value={'boost': 0.0, 'convergence': False},
    ticker=ticker,
    direction=direction,
    bars_session=bars_session
)
```

---

### Critical Protection Points

**High Priority (Must Fix):**

1. **`data_manager.get_today_session_bars()`** - Wrap in try/except with retry
2. **`send_options_signal_alert()`** - Make non-blocking
3. **`position_manager.open_position()`** - Wrap in try/except
4. **All database operations** - Add rollback logic
5. **`wait_for_confirmation()`** - Handle edge cases (empty bars, etc.)

**Medium Priority (Should Fix):**

6. **Optional feature calls** (MTF, Phase 4, regime_filter) - Already have try/except, add logging
7. **`compute_stop_and_targets()`** - Validate output (stop > 0, t1 > entry, etc.)
8. **`get_options_recommendation()`** - Handle API failures gracefully

**Low Priority (Nice to Have):**

9. **Correlation checks** - Add timeout protection
10. **Learning engine** - Add data validation

---

## 📝 IMPLEMENTATION ROADMAP

### Phase 3G: Import Optimization (15 min)

**Step 1: Reorganize imports in `sniper.py`** (5 min)
```python
# Add clear section headers
# Reorder by: stdlib → third-party → local → optional
```

**Step 2: Add import documentation** (5 min)
```python
# Document what each feature flag does
# Add "# Required" and "# Optional" comments
```

**Step 3: Verify no circular imports** (5 min)
```bash
python -c "import sniper"
# Should load without errors
```

---

### Phase 3H: Error Handling (30 min)

**Step 1: Add retry wrapper** (5 min)
- Create `_fetch_with_retry()` helper
- Test with mock API call

**Step 2: Protect critical API calls** (10 min)
- Wrap `data_manager.get_today_session_bars()`
- Wrap `wait_for_confirmation()`
- Wrap `compute_stop_and_targets()`

**Step 3: Make Discord non-blocking** (5 min)
- Wrap all `send_*` calls in try/except
- Add failure logging

**Step 4: Add database rollback** (5 min)
- Wrap `_persist_armed_signal()`
- Wrap `_persist_watch()`
- Test rollback on error

**Step 5: Test error scenarios** (5 min)
```python
# Simulate failures:
# - API timeout
# - Discord down
# - Database locked
# - Invalid data

# Verify:
# - System continues running
# - Errors logged clearly
# - No crashes
```

---

## ✅ SUCCESS CRITERIA

### Phase 3G (Import Optimization):
- ✅ Imports organized by PEP 8 standard
- ✅ All optional imports have try/except
- ✅ Feature flags documented
- ✅ No circular import warnings
- ✅ `python -c "import sniper"` succeeds

### Phase 3H (Error Handling):
- ✅ API calls wrapped in retry logic
- ✅ Discord failures don't block trading
- ✅ Database operations have rollback
- ✅ All critical paths have try/except
- ✅ System survives simulated failures

### Production Readiness:
- ✅ War Machine runs 8+ hours without crashes
- ✅ Handles API outages gracefully
- ✅ Discord downtime doesn't affect trading
- ✅ Database issues don't lose signals
- ✅ Errors logged for debugging

---

## 💡 RECOMMENDED APPROACH

### Tonight (Quick Wins - 20 min):

1. **Import organization** (5 min)
   - Add section headers to `sniper.py` imports
   - Verify no circular imports

2. **Discord protection** (5 min)
   - Wrap all `send_*` calls in try/except
   - Test that trading continues if Discord fails

3. **Critical API protection** (10 min)
   - Wrap `data_manager.get_today_session_bars()`
   - Add "data unavailable" fallback

**Impact:** 80% of production stability with 20% of effort

### Tomorrow (Complete Implementation - 25 min):

4. **Add retry logic** (10 min)
   - Create `_fetch_with_retry()` helper
   - Apply to all API calls

5. **Database rollback** (10 min)
   - Wrap all database operations
   - Test rollback scenarios

6. **Validation testing** (5 min)
   - Simulate failures
   - Verify graceful handling

---

## 🚨 CRITICAL INSIGHT

**Your current code is actually VERY GOOD already!**

`sniper.py` already has:
- ✅ Try/except around `process_ticker()` main loop
- ✅ Optional imports with feature flags
- ✅ Graceful degradation for missing modules
- ✅ Non-fatal error philosophy

**What's missing (high priority):**
- ⚠️ Discord failures can block trading
- ⚠️ API calls lack retry logic
- ⚠️ Database errors need rollback

**Quick fix = Big impact!**

Wrap 3-4 critical calls in try/except → **80% more stable**

---

## 👉 NEXT ACTION

**Option 1: Quick hardening tonight (20 min)**
- Import organization
- Discord protection
- Critical API wrapping
- **Wake up with production-ready system!**

**Option 2: Stop here, resume tomorrow**
- Phase 3F+ complete
- System works and is clean
- Do 3G+3H fresh tomorrow

---

**Status:** Ready for implementation  
**Time Required:** 20 min (quick wins) or 45 min (complete)  
**Impact:** **Production stability** 🛡️
