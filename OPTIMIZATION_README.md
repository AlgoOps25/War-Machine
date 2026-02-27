# War Machine - Comprehensive Parameter Optimization

## Overview

This system tests **EVERY available EODHD data point** to find optimal parameters for the BOS/FVG trading system.

---

## 📊 Available EODHD Data Points

### Core OHLCV Data (1-minute bars)
- ✅ Open, High, Low, Close, Volume
- ✅ Timestamp (ET timezone)
- ✅ Extended hours (4 AM - 8 PM ET)

### Previous Day Data
- ✅ PDH (Previous Day High)
- ✅ PDL (Previous Day Low) 
- ✅ PDC (Previous Day Close)
- ✅ Previous Day Volume

### Volatility Data
- ✅ VIX level (current volatility regime)
- ✅ ATR (Average True Range)

### Real-Time Data
- ✅ Live price snapshots
- ✅ WebSocket feed integration
- ✅ Bulk ticker updates (50 at once)

---

## 🔬 Parameters Being Tested

### 1. Volume Confirmation
**What it tests:** How much above average volume is needed for a valid signal?

- 1.5x average
- 2.0x average ← Current baseline
- 2.5x average
- 3.0x average
- 4.0x average

**Why it matters:** Higher volume = stronger conviction, but fewer signals.

---

### 2. ATR Stop Loss Multiplier
**What it tests:** How wide should stops be relative to volatility?

- 1.0 ATR (tight stops)
- 1.5 ATR ← Current baseline
- 2.0 ATR
- 2.5 ATR
- 3.0 ATR (wide stops)

**Why it matters:** Tighter stops = more stopped out. Wider stops = larger risk per trade.

**Current problem:** 68.4% stopped out with 1.5 ATR → Need to test wider!

---

### 3. Risk:Reward Ratio
**What it tests:** How far should targets be from entry?

- 1.5:1 (closer targets)
- 2.0:1 ← Current baseline
- 2.5:1
- 3.0:1
- 4.0:1 (ambitious targets)

**Why it matters:** Higher R:R = bigger wins but lower hit rate needed.

---

### 4. Lookback Period
**What it tests:** How many bars back to find support/resistance?

- 8 bars (5-10 minutes)
- 10 bars
- 12 bars ← Current baseline
- 16 bars
- 20 bars
- 24 bars (15-20 minutes)

**Why it matters:** Longer lookback = stronger levels but fewer signals.

---

### 5. Momentum Filter
**What it tests:** Should we require directional momentum?

- **None:** No momentum required
- **Weak:** Price moving in breakout direction (>0%)
- **Strong:** Strong momentum (>0.5% move)

**Why it matters:** Momentum confirmation reduces false breakouts.

---

### 6. Trend Filter
**What it tests:** Should we only trade with the trend?

- **False:** Trade all breakouts
- **True:** Only trade when trend aligns (HH for long, LL for short)

**Why it matters:** Trend alignment improves win rate but reduces opportunities.

---

### 7. Gap Size Filter
**What it tests:** Should we require a gap to enter?

- **None:** No gap required
- **Small:** >0.1% gap
- **Large:** >0.5% gap

**Why it matters:** Gaps indicate strong momentum but are less frequent.

---

### 8. VIX Regime Filter
**What it tests:** Should we trade differently based on volatility?

- **None:** Trade all conditions
- **Low VIX:** Only trade when VIX <15 (calm markets)
- **Normal VIX:** Only trade when VIX 15-25
- **High VIX:** Only trade when VIX >25 (volatile markets)

**Why it matters:** Strategy performance varies by volatility regime.

---

### 9. Time-of-Day Filter
**What it tests:** Which session is most profitable?

- **All:** Trade entire session (9:30-16:00)
- **Morning:** Only 9:30-11:00 (high volume)
- **Midday:** Only 11:00-15:00 (trend following)
- **Power Hour:** Only 15:00-16:00 (late momentum)

**Why it matters:** Different strategies work better at different times.

---

### 10. PDH/PDL Filter
**What it tests:** Should we filter by previous day levels?

- **None:** Ignore PDH/PDL
- **Require:** Only trade breakouts above PDH or below PDL
- **Against:** Avoid trades at PDH/PDL (fade levels)

**Why it matters:** PDH/PDL are major psychological levels.

---

### 11. Relative Strength Filter
**What it tests:** Should we only trade stocks outperforming SPY?

- **False:** Trade all stocks
- **True:** Only trade if outperforming SPY

**Why it matters:** Relative strength finds market leaders.

---

## 🚀 Running the Optimization

### Step 1: Pull Latest Code
```powershell
git pull origin main
```

### Step 2: Run Comprehensive Optimization
```powershell
python comprehensive_optimization.py
```

**Expected runtime:** 15-25 minutes

**What it does:**
- Tests ~300-500 parameter combinations
- Scans 10 days of data across 15 tickers
- Simulates every trade with realistic stops/targets
- Calculates win rate, profit factor, P&L for each config

### Step 3: Review Results

Three files are generated:

1. **comprehensive_results.csv**
   - All parameter combinations tested
   - Full metrics for each
   - Use for detailed analysis

2. **top_20_configs.json**
   - Top 20 best performing configurations
   - Ranked by total P&L
   - Ready to implement

3. **optimization_report.txt**
   - Summary statistics
   - Best configuration details
   - Quick reference

---

## 📈 Advanced Indicators (Separate Testing)

The `advanced_indicators.py` module provides additional technical indicators that can be layered on top of BOS/FVG signals:

### Moving Averages
- SMA (Simple Moving Average)
- EMA (Exponential Moving Average)
- VWAP (Volume Weighted Average Price)

### Momentum Indicators
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- Stochastic Oscillator

### Volatility Indicators
- Bollinger Bands
- Keltner Channels
- Standard Deviation

### Volume Indicators
- OBV (On Balance Volume)
- Volume Rate of Change
- Accumulation/Distribution

### Pattern Recognition
- Engulfing candles
- Doji detection
- Inside/Outside bars

### Usage Example:
```python
from advanced_indicators import advanced_indicators

# Get all indicator signals for current bar
signals = advanced_indicators.generate_indicator_signals(bars)

# Check specific indicators
rsi = signals['rsi']
macd_histogram = signals['macd_histogram']
bb_position = signals['bb_position']  # 'upper', 'lower', or 'middle'

# Combined signals
trend = signals['trend_signal']  # 'bullish', 'bearish', 'neutral'
momentum = signals['momentum_signal']  # 'overbought', 'oversold', etc.
```

---

## 🎯 Expected Outcomes

### What We're Looking For:

✅ **Win rate: 40-50%** (currently 29.1%)
✅ **Profit factor: >1.5** (currently 0.68)
✅ **Stopped out: <50%** (currently 68.4%)
✅ **Target hits: >40%** (currently 24.8%)

### Key Improvements Needed:

1. **Reduce false breakouts**
   - Test momentum + trend filters together
   - Require multiple confirmations

2. **Better stop placement**
   - Test wider ATR multiples (2.0-2.5 ATR)
   - Consider breakout-based stops

3. **Time-based filtering**
   - Avoid choppy midday periods
   - Focus on high-conviction times

4. **Entry timing**
   - Wait for pullback confirmation
   - Don't chase immediate breakouts

---

## 📊 Current Baseline Results

From `quick_backtest.py` (10 days, 15 tickers):

```
Total Trades: 3,034
Win Rate: 29.1%
Profit Factor: 0.68
Total P&L: -$243.01

Exit Breakdown:
  Stopped Out: 68.4%
  Hit Target: 24.8%
  Timeout: 6.9%
```

**Analysis:** System is detecting valid signals but:
- Entering too early (getting stopped)
- Stops too tight for volatility
- Need better confirmation filters

---

## 🔧 Next Steps After Optimization

1. **Implement Best Config**
   - Take top-performing parameters from results
   - Update `signal_generator.py` with optimal settings

2. **Live Paper Trading**
   - Test optimized config in real-time
   - Track performance vs backtest

3. **Walk-Forward Testing**
   - Test on out-of-sample data
   - Ensure no overfitting

4. **Add Advanced Indicators**
   - Layer RSI/MACD on top of BOS/FVG
   - Create multi-confirmation system

---

## 📝 Notes

- All data comes from EODHD API (1-minute bars)
- Backtest uses realistic stop/target execution
- No look-ahead bias (signals generated bar-by-bar)
- Commission/slippage not yet included
- Tests use cache for speed (loads 10 days in seconds)

---

## 🆘 Troubleshooting

### "No bars found for ticker"
**Solution:** Run `python data_manager.py` to fetch historical data first

### "Database not initialized"
**Solution:** System will auto-create on first run

### "Optimization taking too long"
**Solution:** Reduce parameter grid or test fewer tickers

### "All configs showing negative P&L"
**Solution:** This is expected initially - optimization finds best of available options

---

## 📧 Questions?

Check the generated reports first:
- `optimization_report.txt` for summary
- `comprehensive_results.csv` for detailed analysis
- `top_20_configs.json` for best parameters

The system tests EVERY combination of EVERY parameter using ALL available EODHD data! 🚀
