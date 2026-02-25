# Integration Instructions: Regime Filter + Correlation Check

## Overview
Two new capital protection systems have been added:
1. **Regime Filter** (`regime_filter.py`) - Detects VIX/SPY market conditions to avoid bad tape
2. **Correlation Check** (`correlation_check.py`) - Prevents over-leverage to correlated positions

## Integration Points

### 1. Add Imports to `sniper.py`

Add these imports at the top of `sniper.py` (around line 30-40, after other imports):

```python
# ────────────────────────────────────────────────────────────────────────
# CAPITAL PROTECTION SYSTEMS
# ────────────────────────────────────────────────────────────────────────
try:
    from regime_filter import regime_filter
    REGIME_FILTER_ENABLED = True
    print("[SNIPER] ✅ Regime filter enabled (VIX/SPY market condition detection)")
except ImportError:
    regime_filter = None
    REGIME_FILTER_ENABLED = False
    print("[SNIPER] ⚠️  Regime filter not available")

try:
    from correlation_check import correlation_checker
    CORRELATION_CHECK_ENABLED = True
    print("[SNIPER] ✅ Correlation check enabled (prevents over-leverage)")
except ImportError:
    correlation_checker = None
    CORRELATION_CHECK_ENABLED = False
    print("[SNIPER] ⚠️  Correlation check not available")
```

### 2. Add Regime Check in `process_ticker()`

Add this check **BEFORE** the watching signals check (around line 1200):

```python
def process_ticker(ticker: str):
    try:
        # Load persistent state
        _maybe_load_watches()
        _maybe_load_armed_signals()

        # ════════════════════════════════════════════════════════════════════════
        # REGIME FILTER - Avoid trading in bad tape
        # Check VIX/SPY conditions before processing any ticker
        # ════════════════════════════════════════════════════════════════════════
        if REGIME_FILTER_ENABLED and regime_filter:
            if not regime_filter.is_favorable_regime():
                state = regime_filter.get_regime_state()
                print(
                    f"[{ticker}] 🚫 REGIME FILTER: {state.regime} "
                    f"(VIX: {state.vix:.1f}) - {state.reason}"
                )
                return  # Skip ticker entirely in unfavorable regime
        
        # Already armed, skip
        if ticker in armed_signals:
            return
        
        # ... rest of function continues
```

### 3. Add Correlation Check in `arm_ticker()`

Replace the existing `_is_highly_correlated()` check (around line 900) with the new correlation checker:

```python
def arm_ticker(ticker, direction, zone_low, zone_high, or_low, or_high,
               entry_price, stop_price, t1, t2, confidence, grade,
               options_rec=None, signal_type="CFW6_OR", validation_result=None,
               bos_confirmation=None, bos_candle_type=None):
    
    # Check stop tightness
    if abs(entry_price - stop_price) < entry_price * 0.001:
        print(f"[ARM] ⚠️ {ticker} stop too tight — skipping")
        return

    # ════════════════════════════════════════════════════════════════════════
    # CORRELATION CHECK - Prevent over-leverage to correlated positions
    # Replaces old _is_highly_correlated() with sector-aware checker
    # ════════════════════════════════════════════════════════════════════════
    open_positions = position_manager.get_open_positions()
    
    if CORRELATION_CHECK_ENABLED and correlation_checker:
        safe, warning = correlation_checker.is_safe_to_add_position(
            ticker=ticker,
            open_positions=open_positions
        )
        
        if not safe:
            print(
                f"[ARM] 🚫 CORRELATION FILTER: {ticker} - {warning.reason}"
            )
            print(
                f"[ARM]   Correlated positions: {', '.join(warning.correlated_tickers)}"
            )
            return  # Skip arming this signal
        
        # Log warning if present (but still safe)
        if warning:
            print(f"[ARM] ⚠️ CORRELATION WARNING: {ticker} - {warning.reason}")
    else:
        # Fallback to old correlation check if new system unavailable
        if _is_highly_correlated(ticker, open_positions, window_bars=60, threshold=0.9):
            print(f"[CORR] Skipping {ticker} — highly correlated with open book")
            return
    
    # ... rest of arm_ticker() continues
```

### 4. Optional: Add Daily Regime Summary

Add to EOD reporting in `scanner.py` (around the analytics section):

```python
# Print EOD regime summary
if REGIME_FILTER_ENABLED and regime_filter:
    try:
        print("\n[EOD] Market Regime Summary:")
        regime_filter.print_regime_summary()
    except Exception as e:
        print(f"[EOD] Regime summary error: {e}")
```

### 5. Optional: Add Correlation Matrix to EOD

Add to EOD reporting in `scanner.py`:

```python
# Print EOD correlation analysis
if CORRELATION_CHECK_ENABLED and correlation_checker:
    try:
        open_positions = position_manager.get_open_positions()
        if open_positions:
            correlation_checker.print_correlation_matrix(open_positions)
    except Exception as e:
        print(f"[EOD] Correlation analysis error: {e}")
```

## Testing

After integration, verify the systems are active:

1. **Startup Check**: Look for these lines in Railway logs:
   ```
   [SNIPER] ✅ Regime filter enabled (VIX/SPY market condition detection)
   [SNIPER] ✅ Correlation check enabled (prevents over-leverage)
   ```

2. **Regime Filter Test**: When VIX > 30, you should see:
   ```
   [TICKER] 🚫 REGIME FILTER: VOLATILE (VIX: 32.5) - VIX elevated (32.5) - elevated volatility
   ```

3. **Correlation Test**: When trying to arm 4th tech position:
   ```
   [ARM] 🚫 CORRELATION FILTER: GOOGL - Too many correlated positions (3/3)
   [ARM]   Correlated positions: AAPL, MSFT, NVDA
   ```

## Configuration

Both systems use parameters from `config.py`:

```python
# Regime Filter (uses existing market timing settings)
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Correlation Check (uses Phase 1.9 settings)
MAX_SECTOR_EXPOSURE_PCT = 40.0  # Maximum % in single sector
MAX_OPEN_POSITIONS = 5          # Hard cap on concurrent positions
```

Adjust these in `config.py` if needed:
- Increase `MAX_SECTOR_EXPOSURE_PCT` to allow more sector concentration (risky)
- Decrease to be more conservative (safer)
- `MAX_OPEN_POSITIONS` is already set to 5 (good default)

## Emergency Disable

If you need to disable either system without changing code:

1. **Regime Filter**: Return `True` always
   ```python
   # In regime_filter.py
   def is_favorable_regime(self, force_refresh: bool = False) -> bool:
       return True  # Emergency disable
   ```

2. **Correlation Check**: Return `(True, None)` always
   ```python
   # In correlation_check.py
   def is_safe_to_add_position(self, ticker, open_positions, proposed_risk_dollars=None):
       return (True, None)  # Emergency disable
   ```

## Next Steps

After integration:
1. Monitor Railway logs for filter activations
2. Collect data on how often regime filter blocks trading
3. Adjust sector exposure limits based on win/loss patterns
4. Consider adding more sector groups to correlation checker

## Performance Impact

- **Regime Filter**: 5-minute cache, minimal CPU (one VIX/SPY check per 5 min)
- **Correlation Check**: O(n²) where n = open positions (max 5), negligible overhead

Both systems add < 1ms latency per signal arming attempt.
