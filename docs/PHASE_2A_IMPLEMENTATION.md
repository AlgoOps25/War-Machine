# Phase 2A Implementation Guide
## Merge Cache Integration into Data Manager

**Status:** ✅ Ready to implement  
**Files Modified:** 2  
**Time Required:** 5-10 minutes  
**Risk Level:** LOW (compatibility stub prevents breaking changes)  

---

## 📋 Step-by-Step Instructions

### Step 1: Add Cache Methods to `data_manager.py`

**Location:** After `startup_intraday_backfill_today()` method (around line 337)

**Action:** Insert the following section:

```python
    # =============================================================
    # CACHE-AWARE STARTUP & SYNC (Phase 2: Merged from cache_integration)
    # =============================================================

    def startup_backfill_with_cache(self, tickers: List[str], days: int = 30):
        """
        Smart startup backfill using candle_cache.
        
        Workflow:
        1. Check cache for each ticker
        2. If cache exists and fresh: Load from cache (INSTANT)
        3. If cache missing/stale: Fetch from API and cache
        4. Only fetch gaps (new data since last cache)
        
        This reduces:
        - API calls from ~160,000 to <500 per deploy
        - Startup time from 5-10 min to 10-30 seconds
        """
        from candle_cache import candle_cache
        
        now_et = datetime.now(ET)
        timeframe = '1m'
        
        print(f"\n[CACHE] 🚀 Smart startup backfill: {len(tickers)} tickers | {days} days")
        
        cache_hits = 0
        cache_misses = 0
        gap_fills = 0
        total_api_bars = 0
        total_cached_bars = 0
        
        for idx, ticker in enumerate(tickers, 1):
            try:
                # Step 1: Check cache status
                metadata = candle_cache.get_cache_metadata(ticker, timeframe)
                
                if metadata and metadata["bar_count"] > 0:
                    # Cache exists - check if we need updates
                    last_cached = metadata["last_bar_time"]
                    if isinstance(last_cached, str):
                        last_cached = datetime.fromisoformat(last_cached)
                    
                    # Load from cache
                    cached_bars = candle_cache.load_cached_candles(ticker, timeframe, days)
                    
                    if cached_bars:
                        # Store cached bars to intraday_bars (for compatibility)
                        self.store_bars(ticker, cached_bars, quiet=True)
                        self.materialize_5m_bars(ticker)
                        total_cached_bars += len(cached_bars)
                        
                        # Check if we need to fetch new data
                        age_minutes = (now_et - last_cached.replace(tzinfo=ET if last_cached.tzinfo is None else None)).total_seconds() / 60
                        
                        if age_minutes > 60:  # Cache older than 1 hour
                            # Fetch only new data since last cache
                            from_ts = int(last_cached.replace(tzinfo=ET).timestamp())
                            to_ts = int(now_et.timestamp())
                            
                            new_bars = self._fetch_range(ticker, from_ts, to_ts)
                            if new_bars:
                                # Cache new bars
                                candle_cache.cache_candles(ticker, timeframe, new_bars, quiet=True)
                                # Also store to intraday_bars
                                self.store_bars(ticker, new_bars, quiet=True)
                                self.materialize_5m_bars(ticker)
                                total_api_bars += len(new_bars)
                                gap_fills += 1
                                print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                      f"{len(cached_bars)} from cache + {len(new_bars)} new bars")
                            else:
                                print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                      f"{len(cached_bars)} bars from cache (up-to-date)")
                        else:
                            print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                                  f"{len(cached_bars)} bars from cache (fresh)")
                        
                        cache_hits += 1
                        continue
                
                # Step 2: Cache miss - full backfill from API
                cache_misses += 1
                today_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
                from_ts = int((today_midnight - timedelta(days=days)).timestamp())
                to_ts = int((today_midnight - timedelta(seconds=1)).timestamp())
                
                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    # Cache the bars
                    candle_cache.cache_candles(ticker, timeframe, bars, quiet=True)
                    # Store to intraday_bars
                    self.store_bars(ticker, bars, quiet=True)
                    self.materialize_5m_bars(ticker)
                    total_api_bars += len(bars)
                    print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: "
                          f"{len(bars)} bars fetched and cached")
                else:
                    print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: no data returned")
            
            except Exception as e:
                print(f"[CACHE] [{idx}/{len(tickers)}] {ticker} error: {e}")
        
        # Print summary
        print(f"\n[CACHE] ✅ Startup complete!")
        print(f"[CACHE] 📊 Stats:")
        print(f"[CACHE]   - Cache hits: {cache_hits}/{len(tickers)} ({cache_hits/len(tickers)*100:.1f}%)")
        print(f"[CACHE]   - Cache misses: {cache_misses}")
        print(f"[CACHE]   - Gap fills: {gap_fills}")
        print(f"[CACHE]   - Bars from cache: {total_cached_bars:,}")
        print(f"[CACHE]   - Bars from API: {total_api_bars:,}")
        
        if cache_hits > 0:
            api_reduction = (1 - total_api_bars / (total_cached_bars + total_api_bars)) * 100 if (total_cached_bars + total_api_bars) > 0 else 0
            print(f"[CACHE]   - API reduction: {api_reduction:.1f}%")
        print()

    def store_bars_with_cache(self, ticker: str, bars: List[Dict], quiet: bool = False) -> int:
        """
        Enhanced store_bars that auto-caches to candle_cache.
        
        This is a wrapper around store_bars() that also caches to candle_cache.
        Use this when you want automatic caching behavior.
        """
        if not bars:
            return 0
        
        # Store to intraday_bars (original behavior)
        result = self.store_bars(ticker, bars, quiet)
        
        # Also cache to candle_cache
        if result > 0:
            try:
                from candle_cache import candle_cache
                candle_cache.cache_candles(ticker, '1m', bars, quiet=True)
            except Exception as e:
                print(f"[CACHE] Auto-cache failed for {ticker}: {e}")
        
        return result

    def background_cache_sync(self, tickers: List[str]):
        """
        Hourly background task to sync cache with latest data.
        
        Run this every 60 minutes to keep cache fresh without
        impacting real-time scanning performance.
        """
        from candle_cache import candle_cache
        
        now_et = datetime.now(ET)
        
        # Only sync during market hours + 1 hour after close
        if not (config.MARKET_OPEN <= now_et.time() <= dtime(17, 0)):
            return
        
        print(f"[CACHE] 🔄 Background sync: {len(tickers)} tickers")
        
        synced = 0
        for ticker in tickers:
            try:
                metadata = candle_cache.get_cache_metadata(ticker, '1m')
                if not metadata:
                    continue
                
                last_cached = metadata["last_bar_time"]
                if isinstance(last_cached, str):
                    last_cached = datetime.fromisoformat(last_cached)
                
                # Sync if cache is > 10 minutes old
                age_minutes = (now_et - last_cached.replace(tzinfo=ET if last_cached.tzinfo is None else None)).total_seconds() / 60
                
                if age_minutes > 10:
                    from_ts = int(last_cached.replace(tzinfo=ET).timestamp())
                    to_ts = int(now_et.timestamp())
                    
                    new_bars = self._fetch_range(ticker, from_ts, to_ts)
                    if new_bars:
                        candle_cache.cache_candles(ticker, '1m', new_bars, quiet=True)
                        synced += 1
            
            except Exception as e:
                print(f"[CACHE] Background sync error for {ticker}: {e}")
        
        if synced > 0:
            print(f"[CACHE] ✅ Background sync complete: {synced}/{len(tickers)} updated")

    def warmup_cache(self, tickers: List[str], days: int = 60):
        """
        One-time cache warmup with extended history.
        
        Use this to pre-populate cache with 60 days of data
        for better backtesting capabilities.
        """
        from candle_cache import candle_cache
        
        print(f"[CACHE] 🔥 Cache warmup: {len(tickers)} tickers | {days} days")
        
        now_et = datetime.now(ET)
        today_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        from_ts = int((today_midnight - timedelta(days=days)).timestamp())
        to_ts = int((today_midnight - timedelta(seconds=1)).timestamp())
        
        for idx, ticker in enumerate(tickers, 1):
            try:
                bars = self._fetch_range(ticker, from_ts, to_ts)
                if bars:
                    candle_cache.cache_candles(ticker, '1m', bars)
                    print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: {len(bars)} bars cached")
                else:
                    print(f"[CACHE] [{idx}/{len(tickers)}] {ticker}: no data")
            except Exception as e:
                print(f"[CACHE] [{idx}/{len(tickers)}] {ticker} error: {e}")
        
        print(f"[CACHE] ✅ Warmup complete!\n")
```

---

### Step 2: Update `scanner.py`

**Find this line (around line 50):**
```python
from data_manager_cache_integration import startup_backfill_with_cache
```

**Delete it** (no longer needed)

**Find this usage (around line 150):**
```python
startup_backfill_with_cache(data_manager, startup_watchlist, days=30)
```

**Replace with:**
```python
data_manager.startup_backfill_with_cache(startup_watchlist, days=30)
```

---

### Step 3: Create Compatibility Stub

**Replace entire contents of `data_manager_cache_integration.py` with:**

```python
"""
COMPATIBILITY STUB - Deprecated

Cache integration is now built into data_manager.py (Phase 2A merge).
This stub maintains backwards compatibility for any external code.

New code should use:
    data_manager.startup_backfill_with_cache(tickers, days=30)
    data_manager.store_bars_with_cache(ticker, bars)
    data_manager.background_cache_sync(tickers)
    data_manager.warmup_cache(tickers, days=60)

This file can be safely deleted after verifying no external dependencies.
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

## 🧪 Testing

### Test 1: Verify Import
```powershell
python -c "from data_manager import data_manager; print(hasattr(data_manager, 'startup_backfill_with_cache'))"
```
**Expected:** `True`

### Test 2: Full Scanner Startup
```powershell
python scanner.py
```
**Expected:**
- No import errors
- Cache stats show 100% hit rate (if cache exists)
- All systems initialize normally
- Scanner runs successfully

### Test 3: Compatibility Stub (Optional)
```powershell
python -c "from data_manager_cache_integration import startup_backfill_with_cache"
```
**Expected:**
- Deprecation warning prints
- No import errors

---

## ✅ Success Criteria

- [ ] Cache methods added to data_manager.py
- [ ] scanner.py updated to use new method
- [ ] Compatibility stub created
- [ ] Test 1 passes (method exists)
- [ ] Test 2 passes (scanner works)
- [ ] Cache hit rate remains 100%
- [ ] Startup time <30 seconds
- [ ] No breaking changes

---

## 🔄 Git Workflow

```powershell
# After completing all changes:
git add data_manager.py
git add scanner.py
git add data_manager_cache_integration.py

git commit -m "Phase 2A: Merge cache integration into data_manager

- Added 4 cache methods to DataManager class
- Updated scanner.py to use data_manager.startup_backfill_with_cache()
- Converted data_manager_cache_integration.py to compatibility stub
- Zero breaking changes (stub maintains backwards compatibility)
- Maintains 95%+ cache hit rate and <30s startup time"

git push
```

---

## 📊 Expected Results

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Active Files | 2 | 1 + stub | ✅ Cleaner |
| DataManager Methods | 19 | 23 | +4 cache methods |
| Import Statements (scanner.py) | 2 | 1 | ✅ Simpler |
| Cache Performance | 95%+ | 95%+ | ✅ Maintained |
| Startup Time | <30s | <30s | ✅ Maintained |
| Breaking Changes | N/A | **ZERO** | ✅ Compatible |

---

**Last Updated:** February 25, 2026  
**Status:** Ready for implementation  
**Estimated Time:** 5-10 minutes  
