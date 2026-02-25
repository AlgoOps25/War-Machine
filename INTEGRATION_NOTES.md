# MTF Integration Guide

## Overview
Integrate multi-timeframe (MTF) FVG convergence detection into `sniper.py` with minimal, surgical changes.

## Integration Steps

### Step 1: Add Import (Line ~68, after OPTIONS_PRE_GATE_ENABLED block)

```python
# ────────────────────────────────────────────────────────────────────────
# MTF INTEGRATION - Multi-timeframe FVG convergence
# Non-fatal import: sniper works normally if MTF system unavailable.
# ────────────────────────────────────────────────────────────────────────
try:
    from mtf_integration import enhance_signal_with_mtf, print_mtf_stats
    MTF_ENABLED = True
    print("[SNIPER] ✅ MTF convergence boost enabled")
except ImportError:
    MTF_ENABLED = False
    print("[SNIPER] ⚠️  MTF system not available — single-timeframe mode")
    def enhance_signal_with_mtf(*args, **kwargs):
        return {'enabled': False, 'convergence': False, 'boost': 0.0, 'reason': 'MTF disabled'}
    def print_mtf_stats():
        pass
```

### Step 2: Call MTF Detection (Line ~814, after Step 8 - Confirmation Layers)

Insert AFTER this block:
```python
    # STEP 8 — CONFIRMATION LAYERS
    conf_result = grade_signal_with_confirmations(...)
    if conf_result["final_grade"] == "reject":
        print(f"[{ticker}] — Rejected by confirmation layers")
        return False
    final_grade = conf_result["final_grade"]
```

Add this NEW block:
```python
    # ════════════════════════════════════════════════════════════
    # STEP 8.2 — MTF CONVERGENCE DETECTION
    # Check if signal has multi-timeframe convergence (5m + 3m FVG alignment)
    # ════════════════════════════════════════════════════════════
    mtf_result = enhance_signal_with_mtf(
        ticker=ticker,
        direction=direction,
        bars_session=bars_session
    )
    
    # Log MTF result
    if mtf_result['convergence']:
        print(
            f"[{ticker}] ✅ MTF CONVERGENCE: "
            f"{mtf_result['convergence_score']:.1%} across "
            f"{', '.join(mtf_result['timeframes'])} | "
            f"Boost: +{mtf_result['boost']:.2%}"
        )
    else:
        print(f"[{ticker}] MTF: {mtf_result['reason']}")
```

### Step 3: Use MTF Boost in Confidence (Line ~986, in Step 11 confidence calculation)

REPLACE this block:
```python
    # STEP 11 — CONFIDENCE (uses validator-adjusted base_confidence)
    ticker_multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)
    try:
        from timeframe_manager import calculate_mtf_convergence_boost
        mtf_boost = calculate_mtf_convergence_boost(ticker)
    except ImportError:
        mtf_boost = 0.0
```

WITH this:
```python
    # STEP 11 — CONFIDENCE (uses validator-adjusted base_confidence)
    ticker_multiplier = learning_engine.get_ticker_confidence_multiplier(ticker)
    
    # MTF boost from Step 8.2 (already calculated)
    mtf_boost = mtf_result.get('boost', 0.0)
```

### Step 4: Print MTF Stats at EOD (Line ~1063, in process_ticker EOD block)

ADD after existing print statements:
```python
        if is_force_close_time(bars_session[-1]):
            position_manager.close_all_eod({ticker: bars_session[-1]["close"]})
            # Print validation stats before market close
            print_validation_stats()
            
            # Print MTF stats  # ← ADD THIS
            print_mtf_stats()  # ← ADD THIS
            
            # Print Phase 4 analytics summary
            if PHASE_4_ENABLED and signal_tracker:
                try:
                    summary = signal_tracker.get_daily_summary()
                    print(summary)
                except Exception as e:
                    print(f"[PHASE 4] Summary error: {e}")
            
            return
```

## Verification

After integration, test with:
```bash
# Run MTF test first
python test_mtf.py

# Then run sniper on a single ticker
python -c "from sniper import process_ticker; process_ticker('SPY')"
```

Expected output should include:
- `[SNIPER] ✅ MTF convergence boost enabled` on startup
- `[{ticker}] MTF: ...` messages during signal processing
- MTF stats at EOD if any signals detected

## Rollback

If issues arise, simply:
1. Comment out the import block (Step 1)
2. System falls back to single-timeframe mode automatically

## Benefits

- **Non-breaking**: Gracefully degrades if MTF unavailable
- **Minimal changes**: Only 4 touchpoints in sniper.py
- **Performance**: MTF data cached per ticker, cleared daily
- **Transparent**: All MTF decisions logged for debugging
- **Testable**: Can disable MTF without code changes

## Next Steps

Once integrated and validated:
1. Monitor MTF convergence rate (should be 10-30% of signals)
2. Track impact on signal win rate
3. Consider adjusting MTF boost range if needed
4. Potentially expand to more timeframes (15m?) if data available
