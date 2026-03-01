# VIX-Based Position Sizing Integration Guide

## Overview

The VIX sizing module (`app/risk/vix_sizing.py`) provides dynamic position sizing that scales with market volatility. Lower VIX = larger positions, higher VIX = smaller positions.

## VIX Regimes

| VIX Level | Regime | Multiplier | Position Size |
|-----------|--------|------------|---------------|
| < 12 | Ultra-Calm | 1.30× | +30% |
| 12-15 | Calm | 1.15× | +15% |
| 15-20 | **Normal** | **1.00×** | **Baseline** |
| 20-25 | Elevated | 0.85× | -15% |
| 25-30 | High | 0.70× | -30% |
| 30-40 | Very High | 0.50× | -50% |
| > 40 | Crisis | 0.30× | -70% |

**Historical Context**:
- **2019**: VIX averaged ~15 (calm markets)
- **COVID crash (March 2020)**: VIX spiked to 82 (crisis)
- **2021-2022**: VIX averaged 20-25 (elevated)
- **2023-2024**: VIX back to 12-18 (calm/normal)

---

## Integration with Position Manager

### Current Risk Tiers (Before VIX Adjustment)

```python
# Your existing risk allocations
RISK_TIERS = {
    "A+": 0.030,  # 3.0%
    "A":  0.025,  # 2.5%
    "B+": 0.020,  # 2.0%
    "B":  0.016,  # 1.6%
    "C+": 0.014,  # 1.4%
}
```

### Option A: Simple Integration (Recommended)

**Location**: `app/risk/position_manager.py` (or wherever you calculate position size)

```python
from app.risk.vix_sizing import get_vix_multiplier, get_adjusted_risk

class PositionManager:
    def calculate_position_size(self, signal_grade: str, account_value: float):
        # Get base risk from tier
        base_risk = RISK_TIERS.get(signal_grade, 0.014)
        
        # Apply VIX adjustment
        vix_mult = get_vix_multiplier()
        adjusted_risk = get_adjusted_risk(base_risk, vix_mult)
        
        # Calculate dollar risk
        dollar_risk = account_value * adjusted_risk
        
        # Log adjustment
        if vix_mult != 1.0:
            print(f"[POSITION] {signal_grade} risk: {base_risk*100:.1f}% -> "
                  f"{adjusted_risk*100:.1f}% (VIX {vix_mult:.2f}×)")
        
        return dollar_risk
```

### Option B: Pre-Fetch VIX at Startup (More Efficient)

Fetch VIX once per scan cycle instead of per signal:

```python
from app.risk.vix_sizing import get_vix_regime, get_adjusted_risk

class Scanner:
    def __init__(self):
        self.vix_multiplier = 1.0
    
    def update_vix_regime(self):
        """Call once per scan cycle (every 30-60 seconds)"""
        regime = get_vix_regime()
        self.vix_multiplier = regime['multiplier']
        
        # Log regime changes
        if regime['regime'] != 'normal':
            print(f"[VIX] {regime['vix']:.2f} ({regime['regime']}) - "
                  f"sizing at {regime['multiplier']*100:.0f}%")
    
    def scan_loop(self):
        while True:
            # Update VIX every cycle
            self.update_vix_regime()
            
            # Detect signals
            signals = self.detect_signals()
            
            for signal in signals:
                # Calculate position with VIX adjustment
                base_risk = RISK_TIERS[signal.grade]
                adjusted_risk = get_adjusted_risk(base_risk, self.vix_multiplier)
                position_size = account_value * adjusted_risk
                
                # Arm signal with adjusted size
                self.arm_signal(signal, position_size)
            
            time.sleep(30)
```

---

## Example: Position Sizing Math

**Scenario**: A+ signal (3% base risk), $10,000 account

### VIX = 15 (Normal)
```python
base_risk = 0.03
vix_mult = 1.0  # Normal regime
adjusted_risk = 0.03 * 1.0 = 0.03 (3.0%)
position_size = $10,000 * 0.03 = $300 risk per trade
```

### VIX = 30 (High Volatility)
```python
base_risk = 0.03
vix_mult = 0.7  # High regime (reduce 30%)
adjusted_risk = 0.03 * 0.7 = 0.021 (2.1%)
position_size = $10,000 * 0.021 = $210 risk per trade
```
**Result**: 30% smaller position during high volatility

### VIX = 10 (Ultra Calm)
```python
base_risk = 0.03
vix_mult = 1.3  # Ultra-calm (increase 30%)
adjusted_risk = 0.03 * 1.3 = 0.039 (3.9%)
position_size = $10,000 * 0.039 = $390 risk per trade
```
**Result**: 30% larger position during calm markets

---

## Diagnostic Commands

### Test VIX Sizing Manually

```bash
# Run VIX sizing diagnostics
python -m app.risk.vix_sizing
```

**Expected Output (example during normal market)**:
```
============================================================
VIX SIZING - Market Volatility Check
============================================================

VIX Level: 16.42
Regime: NORMAL
Position Multiplier: 1.00× (100% of base)
Cache Status: Fresh (0s old)

➡️  NORMAL VOLATILITY - Use baseline position sizes

============================================================
VIX POSITION SIZING - Current Regime
============================================================
VIX Level: 16.42 (NORMAL)
Multiplier: 1.00× (100% of base size)

Grade    Base Risk    VIX-Adjusted    Change
------------------------------------------------------------
A+         3.0%         3.0%           +0.0%
A          2.5%         2.5%           +0.0%
B+         2.0%         2.0%           +0.0%
B          1.6%         1.6%           +0.0%
C+         1.4%         1.4%           +0.0%
============================================================
```

### Test in Python REPL

```python
from app.risk.vix_sizing import *

# Check current VIX
regime = get_vix_regime()
print(f"VIX: {regime['vix']:.2f} ({regime['regime']})")

# Get multiplier
mult = get_vix_multiplier()
print(f"Multiplier: {mult:.2f}×")

# Test adjustment
base = 0.03  # 3% for A+
adjusted = get_adjusted_risk(base)
print(f"Risk: {base*100:.1f}% -> {adjusted*100:.1f}%")

# Show all examples
print(get_sizing_examples())
```

---

## When VIX Adjustment Activates

### ✅ Increase Size (VIX < 15)
- Market calm, low volatility
- Trending markets with tight ranges
- Good time to increase exposure

### ➡️ Baseline (VIX 15-20)
- Normal market conditions
- Use your standard risk tiers
- No adjustment needed

### ⚠️ Reduce Size (VIX 20-30)
- Elevated volatility
- Choppier price action
- More false breakouts
- Reduce exposure 15-30%

### 🚨 Minimal Size (VIX > 30)
- High/crisis volatility
- Market panic or uncertainty
- Sharp intraday swings
- Reduce exposure 50-70%
- Consider sitting on sidelines if VIX > 40

---

## Cost and API Usage

- **Data Source**: EODHD real-time endpoint (`^VIX.INDX`)
- **Cost**: $0 (included in your EOD+Intraday plan)
- **API Calls**: 1 per 5 minutes (cached)
- **Rate Limit Impact**: Negligible (~12 calls/hour)

---

## Fallback Behavior

If VIX fetch fails:
1. Uses cached VIX (up to 5 minutes old)
2. If no cache, assumes VIX = 20 (normal regime, 1.0× multiplier)
3. Logs warning but continues execution

**Recommendation**: Monitor logs for `[VIX] Fetch error` messages.

---

## Integration Checklist

- [ ] `git pull origin main` completed
- [ ] Import VIX sizing in position_manager.py
- [ ] Test with `python -m app.risk.vix_sizing`
- [ ] Verify VIX fetch works (check for real VIX value)
- [ ] Add VIX adjustment to position size calculation
- [ ] Monitor logs for regime changes during trading
- [ ] Backtest with historical VIX data (optional)

---

## Historical VIX Examples

### March 2020 (COVID Crash)
- **VIX**: 60-80
- **Regime**: Crisis (0.3× multiplier)
- **Effect**: A+ signal (3% base) → 0.9% adjusted
- **Outcome**: Massive risk reduction during extreme volatility

### Summer 2024 (Calm Markets)
- **VIX**: 11-13
- **Regime**: Ultra-calm (1.3× multiplier)
- **Effect**: A+ signal (3% base) → 3.9% adjusted
- **Outcome**: Increased exposure during trending market

### October 2023 (Elevated Vol)
- **VIX**: 22-25
- **Regime**: Elevated (0.85× multiplier)
- **Effect**: A+ signal (3% base) → 2.55% adjusted
- **Outcome**: Slight reduction during choppy market

---

## Next Steps

After VIX sizing is integrated:
1. Monitor position sizes during different VIX regimes
2. Verify smaller positions during VIX spikes
3. Track P&L correlation with VIX adjustments
4. Consider manual override during extreme events (VIX > 50)
