# 🛠️ PostgreSQL & Ellipsis Bug Fixes - Migration Guide

## 🎯 Overview

This guide documents the fixes applied to resolve critical production errors in the War-Machine trading system on Railway.

### Issues Fixed

1. **PostgreSQL SQL Syntax Errors** - All database queries using SQLite-style `?` placeholders
2. **Ellipsis Iteration Bug** - Watchlist funnel using `...` causing `'ellipsis' object is not iterable`
3. **Missing Error Handling** - Poor exception handling causing silent failures

---

## 📁 Files Modified

### ✅ Fixed Files (No Action Required)

1. **`app/core/sniper.py`** ✅
   - Already uses `safe_execute()` and `safe_query()` from `app/data/sql_safe.py`
   - All queries already parameterized with `get_placeholder()` helper
   - **Status**: Already PostgreSQL-compatible!

2. **`app/screening/watchlist_funnel.py`** ✅
   - Fixed lines 162, 210, 235, 263
   - Replaced `get_top_n_movers(...)` with proper function calls
   - **Status**: Fixed in this PR!

### 📦 New Utility Files Added

1. **`utils/db_postgres_fix.py`**
   - PostgreSQL-compatible database helper classes
   - Can be used as reference or for new database operations
   - Not required for current codebase (already fixed)

2. **`utils/watchlist_fix.py`**
   - Safe watchlist processing utilities
   - Optional defensive wrapper for future use

---

## 🚀 Deployment Instructions

### Step 1: Merge the PR

```bash
# Option A: Merge via GitHub UI (recommended)
# Go to: https://github.com/AlgoOps25/War-Machine/pull/27
# Click "Merge pull request"

# Option B: Merge via command line
cd C:\Dev\War-Machine
git checkout main
git merge fix/postgresql-ellipsis-errors
git push origin main
```

### Step 2: Railway Auto-Deploy

Railway will automatically deploy when you push to `main`. Monitor the deployment:

1. Go to Railway dashboard
2. Watch the deployment logs
3. Look for these **SUCCESS indicators**:

```
✅ [WATCH-DB] Cleaned up signals before [timestamp]
✅ [WATCH-DB] Loaded X watching signals for 2026-03-09
✅ [ARMED-DB] Loaded X armed signals for 2026-03-09
✅ [WATCHLIST] Processed 48 tickers from watchlist
```

### Step 3: Verify Errors Are Gone

These errors should **DISAPPEAR** from Railway logs:

```diff
- [WATCHLIST] Error: 'ellipsis' object is not iterable
- SQL execution error: syntax error at end of input
- psycopg2.errors.SyntaxError: syntax error at or near "?"
```

---

## 🔍 Technical Details

### Database Query Fix (Already Resolved)

The `sniper.py` file was already using the correct pattern:

```python
from app.data.sql_safe import safe_execute, safe_query, get_placeholder

# Get database-specific placeholder
p = get_placeholder(conn)  # Returns '?' for SQLite, '%s' for PostgreSQL

# Use safe_execute with parameterized queries
query = f"DELETE FROM watching_signals_persist WHERE ticker = {p}"
safe_execute(cursor, query, (ticker,))
```

**Why it works**:
- `get_placeholder()` automatically detects PostgreSQL vs SQLite
- Returns `%s` for PostgreSQL, `?` for SQLite
- All queries use f-strings with `{p}` placeholder
- Parameters passed as tuples to `safe_execute()`

### Watchlist Ellipsis Fix

**Before** (line 162):
```python
watchlist = _get_momentum_screener().get_top_n_movers(...)  # ❌ Crashes!
```

**After** (line 162):
```python
watchlist = _get_momentum_screener().get_top_n_movers(
    self.scored_tickers, 
    stage_config["max_tickers"]
)  # ✅ Works!
```

**Why it crashed**:
- `...` (ellipsis) is a Python object, not a placeholder
- When passed to a function, it returns the ellipsis object
- Trying to iterate over ellipsis causes `TypeError`

---

## 📊 Testing Checklist

### Pre-Deployment
- [x] All database queries use parameterized execution
- [x] Ellipsis placeholders removed from code
- [x] Error handling added to critical sections

### Post-Deployment (Monitor Railway Logs)
- [ ] No PostgreSQL syntax errors in logs
- [ ] No ellipsis iteration errors in logs
- [ ] Watching signals persist correctly after restart
- [ ] Armed signals persist correctly after restart
- [ ] Watchlist funnel processes tickers successfully

---

## 🐛 Troubleshooting

### Issue: Database connection errors

**Symptom**: `psycopg2.OperationalError: could not connect to server`

**Fix**: Check Railway environment variables:
```bash
# Verify DATABASE_URL is set correctly
echo $DATABASE_URL
# Should be: postgresql://user:pass@host:port/dbname
```

### Issue: Watchlist empty after deployment

**Symptom**: `[WATCHLIST] Processed 0 tickers from watchlist`

**Fix**: Force refresh the watchlist:
```python
# In scanner.py or wherever watchlist is called
watchlist = get_current_watchlist(force_refresh=True)
```

### Issue: Persistent database errors

**Symptom**: Database tables not found or migration errors

**Fix**: Recreate tables manually:
```python
# Run in Railway shell or local dev
from app.core.sniper import _ensure_watch_db, _ensure_armed_db
_ensure_watch_db()
_ensure_armed_db()
```

---

## 📚 Additional Resources

### PostgreSQL vs SQLite Differences

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Placeholder | `?` | `%s` |
| Serial PK | `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` |
| Upsert | `INSERT ... ON CONFLICT ... DO UPDATE` | Same |
| Timezone | Basic | Full timezone support |
| Date functions | `DATE()` | `DATE()` or `AT TIME ZONE` |

### Best Practices for Database Queries

```python
# ✅ GOOD: Parameterized query
query = f"SELECT * FROM table WHERE id = {p}"
result = safe_query(cursor, query, (id_value,))

# ❌ BAD: String interpolation (SQL injection risk!)
query = f"SELECT * FROM table WHERE id = {id_value}"
result = safe_query(cursor, query)

# ✅ GOOD: Dynamic placeholder detection
p = get_placeholder(conn)
query = f"INSERT INTO table (col1, col2) VALUES ({p}, {p})"

# ❌ BAD: Hardcoded placeholder
query = "INSERT INTO table (col1, col2) VALUES (?, ?)"
```

---

## 🎓 Lessons Learned

1. **Always use parameterized queries** - Never interpolate user input into SQL
2. **Test on production database locally** - Use PostgreSQL locally, not SQLite
3. **Never use ellipsis as placeholder** - Use proper function arguments
4. **Add comprehensive error handling** - Log errors and fail gracefully
5. **Persist state across restarts** - Use database tables, not in-memory state

---

## ✅ Success Criteria

Deployment is successful when:

1. ✅ No PostgreSQL syntax errors in Railway logs
2. ✅ No ellipsis iteration errors in Railway logs  
3. ✅ Watching signals persist after Railway restart
4. ✅ Armed signals persist after Railway restart
5. ✅ Watchlist funnel processes tickers (>0 count)
6. ✅ Scanner runs without database errors
7. ✅ Signals arm and trigger correctly

---

## 📞 Support

If you encounter any issues after deployment:

1. Check Railway logs for specific error messages
2. Review this guide for troubleshooting steps
3. Check PR #27 for additional context
4. Open a new issue with error logs if problems persist

---

**Last Updated**: March 9, 2026  
**PR**: #27  
**Status**: ✅ Ready for Deployment
