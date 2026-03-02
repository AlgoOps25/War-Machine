# Data-Driven DTE Selector Integration Guide

## Overview

This guide shows how to update `sniper.py` and `position_manager.py` to use the new data-driven DTE selector.

---

## 1. Update `app/core/sniper.py`

### Current Code (approximate location)

```python
# Around line 800-900 in sniper.py where DTE selector is called
dte_result = dte_selector.calculate_optimal_dte(
    ticker=ticker,
    entry_price=entry_price,
    direction=direction,
    confidence=confidence
)
```

### Updated Code

```python
# Before calling DTE selector, gather context data
from app.market.market_data import get_vix  # Or wherever VIX is fetched

# ADX is already calculated in sniper.py validation
adx_value = adx  # From your existing ADX calculation

# VIX - fetch current value
try:
    vix_value = get_vix()  # Implement this or use existing VIX source
except:
    vix_value = None  # Fallback if unavailable

# T1 and T2 prices are already calculated
t1_price = entry_price * (1 + t1_pct / 100)  # Bull example
t2_price = entry_price * (1 + t2_pct / 100)

# Call DTE selector with full context
dte_result = dte_selector.calculate_optimal_dte(
    ticker=ticker,
    entry_price=entry_price,
    direction=direction,
    confidence=confidence,
    adx=adx_value,        # NEW
    vix=vix_value,        # NEW
    t1_price=t1_price,    # NEW
    t2_price=t2_price     # NEW
)
```

**Key Points:**
- ADX: Already computed during signal validation
- VIX: May need to add fetching logic (or pass None for now)
- T1/T2: Already calculated from your target logic
- All new params are **optional** - backward compatible

---

## 2. Update `app/trading/position_manager.py`

### Current Code (approximate location)

```python
# In open_position() method when inserting to positions table
cursor.execute(f"""
    INSERT INTO positions (
        ticker, direction, entry_price, stop_price, 
        t1_price, t2_price, ...
    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, ...)
""", (ticker, direction, entry_price, stop_price, t1_price, t2_price, ...))
```

### Updated Code

```python
# Calculate tracking data before insert
dte_selected = dte_result.get('dte')  # From DTE selector response
adx_at_entry = signal_data.get('adx')  # From signal context
vix_at_entry = signal_data.get('vix')  # From signal context
target_pct_t1 = abs((t1_price - entry_price) / entry_price * 100)

# Insert with new tracking columns
cursor.execute(f"""
    INSERT INTO positions (
        ticker, direction, entry_price, stop_price,
        t1_price, t2_price, 
        dte_selected, adx_at_entry, vix_at_entry, target_pct_t1,  -- NEW
        ...
    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, ...)
""", (
    ticker, direction, entry_price, stop_price,
    t1_price, t2_price,
    dte_selected, adx_at_entry, vix_at_entry, target_pct_t1,  # NEW
    ...
))
```

**Key Points:**
- `dte_selected`: From DTE selector response
- `adx_at_entry`: From signal validation context
- `vix_at_entry`: From market data (or None)
- `target_pct_t1`: Calculate from entry vs T1 price

---

## 3. Run Database Migration

**Before deploying:**

```bash
python migrations/add_dte_tracking_columns.py
```

**Expected output:**
```
✅ Added column: dte_selected
✅ Added column: adx_at_entry
✅ Added column: vix_at_entry
✅ Added column: target_pct_t1

🎉 Migration complete!
```

---

## 4. VIX Data Source Options

### Option A: EODHD (Recommended)
```python
def get_vix() -> float:
    """Fetch current VIX from EODHD."""
    url = "https://eodhd.com/api/real-time/VIX.INDX"
    params = {"api_token": os.getenv('EODHD_API_KEY'), "fmt": "json"}
    try:
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        return float(data.get('close', 20.0))  # Default to 20 if unavailable
    except:
        return 20.0  # Neutral fallback
```

### Option B: Cache Daily VIX
```python
# Fetch once per day and cache
class MarketData:
    def __init__(self):
        self.vix_cache = None
        self.vix_cache_date = None
    
    def get_vix(self) -> float:
        today = datetime.now(ET).date()
        if self.vix_cache_date != today:
            self.vix_cache = self._fetch_vix_from_eodhd()
            self.vix_cache_date = today
        return self.vix_cache or 20.0
```

### Option C: Start Without VIX
```python
# Pass None for now - regime scoring will use ADX + target only
dte_result = dte_selector.calculate_optimal_dte(
    ticker=ticker,
    entry_price=entry_price,
    direction=direction,
    confidence=confidence,
    adx=adx_value,
    vix=None,  # Will skip VIX scoring
    t1_price=t1_price,
    t2_price=t2_price
)
```

---

## 5. Testing Workflow

### Phase 1: Basic Integration (Week 1)
1. Run migration
2. Update sniper.py with ADX + T1/T2 params
3. Update position_manager.py to store tracking columns
4. VIX can be None initially
5. Historical advisor returns "no preference" (expected)
6. System uses live options + regime scoring

### Phase 2: Add VIX (Week 2)
1. Implement VIX fetching
2. Pass VIX to DTE selector
3. Regime scoring now includes all 3 factors

### Phase 3: Historical Learning (Week 4+)
1. After 30+ trades, historical advisor activates
2. Monitor recommendations in Discord alerts
3. System self-calibrates to your conditions

---

## 6. Validation Checklist

**Before merging:**
- [ ] Migration runs without errors
- [ ] DTE selector accepts new params
- [ ] sniper.py passes ADX + targets
- [ ] position_manager.py stores tracking data
- [ ] Historical advisor gracefully handles empty DB

**After merging:**
- [ ] First signal shows regime-based reasoning
- [ ] Tracking columns populate in positions table
- [ ] After 30 trades, historical recommendations appear
- [ ] Discord alerts show 3-layer scoring breakdown

---

## 7. Example Signal Output

**Before (old system):**
```
⚠️ Fallback to time-based: 1DTE
Reason: No options data available from EODHD
```

**After (new system):**
```
📅 SELECTED: 1DTE
📊 Historical: No preference (Insufficient data 8/30)
💹 Live Options: 0DTE scored 6.5/10.5
🎯 Regime: Favors 1DTE (choppy ADX, normal VIX, medium target)
Confidence: 58%
```

**After 30+ trades:**
```
📅 SELECTED: 1DTE
📊 Historical: 1DTE (1DTE wins 67.3% in AFTERNOON_CHOPPY_NORMAL_MEDIUM (n=42))
💹 Live Options: 0DTE scored 7.2/10.5
🎯 Regime: Favors 1DTE (choppy ADX, medium target)
Confidence: 72%
```

---

## Questions?

Refer to:
- `app/options/dte_historical_advisor.py` - Historical learning logic
- `app/options/options_dte_selector.py` - Combined scoring
- PR #9 description - Full architecture overview
