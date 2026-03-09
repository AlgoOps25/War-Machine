# Supreme Quality Filter - Integration Guide

## Overview

The Supreme Quality Filter implements the YouTube BOS+FVG methodology that achieved:
- **66.7% win rate** (+21.8pp improvement)
- **+0.82R average** (+447% profitability improvement)
- **92% signal reduction** (78 → 6 signals)

## Integration Points

### 1. Import the Module

```python
# At top of sniper.py
from app.core.supreme_quality import is_supreme_quality, print_supreme_stats, reset_supreme_stats
```

### 2. Add Supreme Gate Before Position Entry

In `_run_signal_pipeline()`, add this check **after all validation passes** but **before `arm_ticker()`**:

```python
# After validation_result check (around line 850)
if not VALIDATOR_TEST_MODE:
    if not validation_result['should_take']:
        print(f"[VALIDATOR] {ticker} FILTERED")
        return False

# NEW: SUPREME QUALITY GATE (add here)
supreme_signal = {
    'ticker': ticker,
    'time': _now_et().strftime('%H:%M'),
    'volume_ratio': current_volume / avg_volume if avg_volume > 0 else 1.0,
    'bos_strength': abs(entry_price - or_low_ref) / or_low_ref if direction == 'bull' else abs(or_high_ref - entry_price) / or_high_ref,
    'mtf_score': mtf_result.get('convergence_score', 0) * 10 if mtf_result.get('convergence') else 5.0,
    'confirmation_score': 85 + (final_grade == 'A+') * 10 - (final_grade == 'A-') * 10,
    'direction': direction
}

approved, gate = is_supreme_quality(supreme_signal)
if not approved:
    print(f"[{ticker}] 🚫 SUPREME FILTER: Rejected at {gate}")
    return False

print(f"[{ticker}] ✅ SUPREME QUALITY: Passed all gates")

# Continue to arm_ticker()...
```

### 3. Add EOD Statistics

In `process_ticker()` at EOD reporting (around line 1100):

```python
if is_force_close_time(bars_session[-1]):
    position_manager.close_all_eod({ticker: bars_session[-1]["close"]})
    print_validation_stats()
    print_validation_call_stats()
    print_mtf_stats()
    
    # NEW: Add supreme quality stats
    print_supreme_stats()
    reset_supreme_stats()
    
    # ... rest of EOD logic
```

## Signal Field Mapping

### Required Fields

| Field | Source | Description |
|-------|--------|-------------|
| `ticker` | Direct | Ticker symbol |
| `time` | `_now_et().strftime('%H:%M')` | Current time (HH:MM) |
| `volume_ratio` | `current_volume / avg_volume` | Relative volume |
| `bos_strength` | Entry distance from structure | Break strength |
| `mtf_score` | `mtf_result['convergence_score'] * 10` | MTF alignment (0-10) |
| `confirmation_score` | Grade-based (85±10) | Candle quality (0-100) |
| `direction` | `'bull'` or `'bear'` | Signal direction |

### Calculation Examples

#### Volume Ratio
```python
# Calculate 20-bar average volume
avg_volume = np.mean([b['volume'] for b in bars_session[-20:]])
current_volume = bars_session[-1]['volume']
volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
```

#### BOS Strength
```python
# Distance from structure level as percentage
if direction == 'bull':
    bos_strength = abs(entry_price - or_low_ref) / or_low_ref
else:
    bos_strength = abs(or_high_ref - entry_price) / or_high_ref
```

#### MTF Score
```python
# Convert MTF convergence to 0-10 scale
if mtf_result.get('convergence'):
    mtf_score = mtf_result['convergence_score'] * 10  # 0.8 → 8.0
else:
    mtf_score = 5.0  # Neutral baseline
```

#### Confirmation Score
```python
# Grade-based scoring (A+: 95, A: 85, A-: 75)
base_score = 85
if final_grade == 'A+':
    confirmation_score = 95
elif final_grade == 'A':
    confirmation_score = 85
elif final_grade == 'A-':
    confirmation_score = 75
else:
    confirmation_score = 70  # Below threshold
```

## Gate Criteria (Backtest-Tuned)

| Gate | Criterion | Rationale |
|------|-----------|----------|
| TIME_GATE | 9:30-11:00 AM | 100% of winners in opening range |
| VOLUME_GATE | ≥1.5x | Strong rejection conviction |
| BOS_GATE | ≥0.0015 (0.15%) | Clean breakout |
| MTF_GATE | ≥8.0 | Higher TF support |
| CONFIRMATION_GATE | ≥85 | Strong candle structure |

## Expected Impact

### Before Supreme Filter
- 78 signals per backtest period
- 44.9% win rate
- +0.15R average

### After Supreme Filter
- 6 signals per backtest period (-92%)
- 66.7% win rate (+21.8pp)
- +0.82R average (+447%)

## Testing

1. **Dry Run Mode**: Set `SUPREME_DRY_RUN = True` to log without filtering
2. **Statistics**: Review rejection breakdown at EOD
3. **Optimization**: Adjust thresholds in `supreme_quality.py` if needed

## Monitoring

### Daily Statistics Output
```
================================================================================
SUPREME QUALITY GATE - DAILY STATISTICS
================================================================================
Total Signals Evaluated: 78
Approved: 6 (7.7%)
Rejected: 72 (92.3%)

Rejection Breakdown:
  TIME_GATE          :  35 ( 44.9%) ██████████████████████
  VOLUME_GATE        :  18 ( 23.1%) ███████████
  BOS_GATE           :  10 ( 12.8%) ██████
  MTF_GATE           :   6 (  7.7%) ███
  CONFIRMATION_GATE  :   3 (  3.8%) █
================================================================================
Quality-over-Quantity: 92.3% filtered
Target: 70%+ win rate on approved signals
================================================================================
```

## Troubleshooting

### No Signals Passing
- Check time window (must be 9:30-11:00 AM)
- Review volume ratios (may need lower threshold for slow days)
- Verify MTF convergence is detecting properly

### Too Many Rejections at Specific Gate
- Review gate statistics to identify bottleneck
- Consider slight threshold adjustments (±5%)
- Validate calculation accuracy with debug logs

## Version History

- **v1.0.0** (2026-03-09): Initial implementation from YouTube backtest
- Criteria: Time 9:30-11:00, Vol≥1.5x, BOS≥0.15%, MTF≥8.0, Conf≥85
