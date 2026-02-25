# MTF FVG Priority Resolver - Integration Guide

## Purpose
Enforce Nitro Trades rule: "Always take the highest timeframe FVG when conflicts exist."

Priority order: **5m > 3m > 2m > 1m**

## What Changed

### New Module: `mtf_fvg_priority.py`
- Scans all timeframes (5m, 3m, 2m, 1m) for FVGs
- When multiple FVGs exist, selects the highest-TF one as primary
- Tracks lower-TF FVGs as "confluence" (secondary confirmation)
- Provides statistics on priority conflicts and resolution

## Integration Steps

### Step 1: Import the Priority Resolver (sniper.py line ~84)

**Add after MTF integration import:**

```python
# ────────────────────────────────────────────────────────────────────────
# MTF FVG PRIORITY - Highest timeframe FVG selection
# ────────────────────────────────────────────────────────────────────────
try:
    from mtf_fvg_priority import get_highest_priority_fvg, get_full_mtf_analysis, print_priority_stats
    MTF_PRIORITY_ENABLED = True
    print("[SNIPER] ✅ MTF FVG priority resolver enabled")
except ImportError:
    MTF_PRIORITY_ENABLED = False
    print("[SNIPER] ⚠️  MTF priority resolver not available — single-TF FVG mode")
    def get_highest_priority_fvg(*args, **kwargs):
        return None
    def get_full_mtf_analysis(*args, **kwargs):
        return {'primary_fvg': None, 'secondary_fvgs': [], 'confluence_count': 0}
    def print_priority_stats():
        pass
```

### Step 2: Update INTRADAY_BOS Path (sniper.py ~line 1460)

**BEFORE (current code):**
```python
# ── INTRADAY BOS+FVG PATH (scan_bos_fvg from bos_fvg_engine) ─────────────────────
if scan_mode is None:
    if len(bars_session) < 30:
        return

    fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
    bos_signal = scan_bos_fvg(ticker, bars_session, fvg_min_pct=fvg_threshold)
    if bos_signal is None:
        print(f"[{ticker}] — No BOS+FVG signal")
        return

    direction    = bos_signal["direction"]
    zone_low     = bos_signal["fvg_low"]
    zone_high    = bos_signal["fvg_high"]
    breakout_idx = bos_signal["bos_idx"]
```

**AFTER (with MTF priority integration):**
```python
# ── INTRADAY BOS+FVG PATH (with MTF priority resolver) ─────────────────────
if scan_mode is None:
    if len(bars_session) < 30:
        return

    fvg_threshold, _ = get_adaptive_fvg_threshold(bars_session, ticker)
    bos_signal = scan_bos_fvg(ticker, bars_session, fvg_min_pct=fvg_threshold)
    if bos_signal is None:
        print(f"[{ticker}] — No BOS+FVG signal")
        return

    direction    = bos_signal["direction"]
    breakout_idx = bos_signal["bos_idx"]
    
    # Extract 3-tier candle confirmation from bos_signal
    bos_confirmation = bos_signal.get("confirmation")
    bos_candle_type = bos_signal.get("candle_type")
    
    # ═══════════════════════════════════════════════════════════════════════
    # MTF FVG PRIORITY RESOLVER
    # Scan all timeframes (5m, 3m, 2m, 1m) for FVGs and select highest-TF one
    # ═══════════════════════════════════════════════════════════════════════
    if MTF_PRIORITY_ENABLED:
        try:
            # Get full MTF analysis (primary + secondary FVGs)
            mtf_analysis = get_full_mtf_analysis(
                ticker=ticker,
                direction=direction,
                bars_5m=bars_session,
                min_pct=fvg_threshold
            )
            
            primary_fvg = mtf_analysis['primary_fvg']
            
            if primary_fvg is None:
                print(f"[{ticker}] — No FVGs found on any timeframe (MTF scan)")
                return
            
            # Use highest-priority FVG as trade zone
            zone_low  = primary_fvg['fvg_low']
            zone_high = primary_fvg['fvg_high']
            
            # Log priority resolution
            if mtf_analysis['has_conflict']:
                print(
                    f"[{ticker}] 🎯 MTF PRIORITY: {primary_fvg['timeframe']} FVG selected | "
                    f"Confluence: {mtf_analysis['confluence_count']} timeframe(s) | "
                    f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                )
            else:
                print(
                    f"[{ticker}] 📍 Single FVG on {primary_fvg['timeframe']} | "
                    f"Zone: ${zone_low:.2f}-${zone_high:.2f}"
                )
        
        except Exception as priority_err:
            print(f"[{ticker}] MTF priority error (falling back to 5m): {priority_err}")
            # Fallback to original bos_signal FVG
            zone_low  = bos_signal["fvg_low"]
            zone_high = bos_signal["fvg_high"]
    else:
        # MTF priority disabled - use 5m FVG from bos_signal
        zone_low  = bos_signal["fvg_low"]
        zone_high = bos_signal["fvg_high"]
    
    # Continue with OR refs (unchanged)
    if direction == "bull":
        or_high_ref = bos_signal["bos_price"]
        or_low_ref  = zone_low
    else:
        or_high_ref = zone_high
        or_low_ref  = bos_signal["bos_price"]

    scan_mode = "INTRADAY_BOS"
```

### Step 3: Add Stats Printing (sniper.py ~line 1310)

**Find the EOD stats block:**
```python
if is_force_close_time(bars_session[-1]):
    position_manager.close_all_eod({ticker: bars_session[-1]["close"]})
    # Print validation stats before market close
    print_validation_stats()
    
    # Print MTF stats
    print_mtf_stats()
```

**Add MTF priority stats:**
```python
if is_force_close_time(bars_session[-1]):
    position_manager.close_all_eod({ticker: bars_session[-1]["close"]})
    # Print validation stats before market close
    print_validation_stats()
    
    # Print MTF stats
    print_mtf_stats()
    
    # Print MTF priority stats
    print_priority_stats()
```

## Testing

### Unit Test (verify priority selection)

```python
from mtf_fvg_priority import get_full_mtf_analysis

# Create test bars with known FVG zones
bars = create_test_bars_with_fvgs()  # Your test data

result = get_full_mtf_analysis(
    ticker="TEST",
    direction="bull",
    bars_5m=bars,
    min_pct=0.001
)

print(f"Primary FVG TF: {result['primary_fvg']['timeframe']}")
print(f"Confluence count: {result['confluence_count']}")
print(f"Has conflict: {result['has_conflict']}")
```

### Live Test

1. Deploy updated `sniper.py` + `mtf_fvg_priority.py`
2. Monitor Discord alerts for new priority log messages
3. Check EOD stats for priority resolution breakdown

## Expected Behavior

### Scenario 1: Single FVG (5m only)
**Output:**
```
[SPY] 📍 Single FVG on 5m | Zone: $450.20-$450.45
```

### Scenario 2: Multiple FVGs (conflict)
**Output:**
```
[AAPL] 🎯 MTF PRIORITY: 5m FVG selected | Confluence: 3 timeframe(s) | Zone: $182.50-$183.10
```

### Scenario 3: No FVGs
**Output:**
```
[TSLA] — No FVGs found on any timeframe (MTF scan)
```

## Statistics Output (EOD)

```
================================================================================
MTF FVG PRIORITY RESOLVER - DAILY STATISTICS
================================================================================
Total Scans:          47
Conflicts Resolved:   23 (48.9%)
Confluence Found:     18 (38.3%)

Primary FVG Timeframe Breakdown:
  5m: 31 (66.0%)
  3m: 12 (25.5%)
  2m: 3 (6.4%)
  1m: 1 (2.1%)

Priority Rule: 5m > 3m > 2m > 1m
Confluence: Lower-TF FVGs overlapping primary FVG zone
================================================================================
```

## Rollback Plan

If issues occur:

1. **Disable MTF priority** by setting `MTF_PRIORITY_ENABLED = False` in the try/except block
2. System falls back to original 5m FVG from `bos_signal`
3. No other code changes needed

## Key Advantages

✅ **Trades highest-quality FVG zones** (larger TF = more institutional money)  
✅ **Confluence tracking** (lower-TF alignment boosts confidence)  
✅ **Backward compatible** (graceful fallback if module unavailable)  
✅ **Performance tracking** (stats show how often conflicts occur)  
✅ **Non-breaking** (existing signals still work, just with better FVG selection)

## Next Steps

1. Apply integration patches to `sniper.py`
2. Test on paper trading / backtest mode first
3. Monitor priority stats for 2-3 days
4. Compare win rate before/after MTF priority (expect 3-5% improvement)
