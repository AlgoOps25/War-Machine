# Phase 5 Roadmap: ML Features & Advanced Optimization

## Overview

**Goal:** Transform War Machine from rule-based to ML-enhanced trading system.

**Timeline:** 4-6 weeks  
**Prerequisite:** Phase 4 deployed + 2-4 weeks of data collected  
**Complexity:** High (ML/data science work)  

---

## Phase 5 Components

### 5.1: ML Signal Scoring (Week 1-2)

**Objective:** Use historical data to predict signal success probability.

#### Features to Extract:
1. **Technical Features:**
   - RSI, ADX, ATR percentiles
   - Volume profile (vs 20-day avg)
   - Price distance from key MAs
   - Bollinger Band width
   - MACD histogram trend

2. **Market Context:**
   - IVR (Implied Volatility Rank)
   - Unusual Options Activity score
   - GEX (Gamma Exposure) level
   - Market internals (TICK, TRIN)

3. **Time Features:**
   - Time of day (avoid first/last 30 min)
   - Day of week
   - Days to major events (FOMC, earnings)

4. **Historical Features:**
   - Ticker's 30-day win rate
   - Recent streak (wins/losses)
   - Avg P&L for this setup type

#### Model Architecture:

**Option A: Random Forest Classifier**
- Input: 25-30 features
- Output: Win probability (0-1)
- Pros: Interpretable, handles non-linear relationships
- Training: 200+ historical trades

**Option B: Gradient Boosting (XGBoost)**
- Input: Same 25-30 features
- Output: Win probability + confidence interval
- Pros: Better performance, feature importance built-in
- Training: 500+ historical trades for best results

#### Implementation Plan:

```python
# File: ml_signal_scorer.py

class MLSignalScorer:
    def __init__(self):
        self.model = None
        self.feature_extractor = FeatureExtractor()
        self.scaler = StandardScaler()
    
    def train(self, historical_signals):
        """Train on historical signal data."""
        X = self.feature_extractor.extract_features(historical_signals)
        y = [1 if s['realized_pnl'] > 0 else 0 for s in historical_signals]
        
        X_scaled = self.scaler.fit_transform(X)
        
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=10
        )
        self.model.fit(X_scaled, y)
    
    def score_signal(self, ticker, signal_data, market_data):
        """Score a new signal."""
        features = self.feature_extractor.extract_features([
            {
                'ticker': ticker,
                'signal_type': signal_data['type'],
                'technical': signal_data['indicators'],
                'market': market_data,
                'time': datetime.now()
            }
        ])
        
        features_scaled = self.scaler.transform(features)
        win_probability = self.model.predict_proba(features_scaled)[0][1]
        
        return {
            'ml_score': win_probability,
            'confidence': self._calculate_confidence(features_scaled),
            'feature_importance': self._get_top_features(features)
        }
```

#### Integration:

```python
# In sniper.py, after rule-based grading:

grade = grade_signal(ticker, signal_data)  # A+/A/A-

# Add ML scoring
ml_score = ml_scorer.score_signal(ticker, signal_data, market_data)

# Combine rule-based and ML:
if grade == 'A+' and ml_score['ml_score'] >= 0.70:
    final_grade = 'A+'
    ml_boost = 1.2
elif grade == 'A' and ml_score['ml_score'] >= 0.60:
    final_grade = 'A'
    ml_boost = 1.1
elif ml_score['ml_score'] < 0.40:
    # ML says skip this signal
    reject("ML score too low")
else:
    final_grade = grade
    ml_boost = 1.0

final_confidence = base_confidence * ml_boost
```

---

### 5.2: Multi-Timeframe Synchronization (Week 2-3)

**Objective:** Only trade when multiple timeframes align.

#### Timeframe Stack:
1. **Daily (D1):** Trend direction
2. **4-Hour (H4):** Momentum confirmation
3. **1-Hour (H1):** Entry timing
4. **15-Min (M15):** Precision entry (current)

#### Synchronization Logic:

```python
class MultiTimeframeAnalyzer:
    def check_alignment(self, ticker, direction):
        """
        Returns True only if all timeframes support the trade.
        """
        # D1: Trend filter
        daily_trend = self.get_trend('D1', ticker)
        if daily_trend != direction:
            return False, "Daily trend opposes signal"
        
        # H4: Momentum filter
        h4_momentum = self.get_momentum('H4', ticker)
        if h4_momentum == 'weak':
            return False, "4H momentum weak"
        
        # H1: Entry zone
        h1_in_zone = self.check_entry_zone('H1', ticker, direction)
        if not h1_in_zone:
            return False, "Not in H1 entry zone"
        
        return True, "MTF aligned"
    
    def get_trend(self, timeframe, ticker):
        """Determine trend using 20/50/200 EMA."""
        data = self.fetch_ohlcv(ticker, timeframe, limit=200)
        ema20 = talib.EMA(data['close'], 20)
        ema50 = talib.EMA(data['close'], 50)
        ema200 = talib.EMA(data['close'], 200)
        
        if ema20[-1] > ema50[-1] > ema200[-1]:
            return 'bull'
        elif ema20[-1] < ema50[-1] < ema200[-1]:
            return 'bear'
        else:
            return 'neutral'
```

#### Integration:

```python
# In signal_validator.py:

def validate_signal(ticker, signal_data):
    # Existing validation...
    
    # NEW: MTF check
    mtf_aligned, reason = mtf_analyzer.check_alignment(ticker, signal_data['direction'])
    
    if not mtf_aligned:
        return False, f"MTF rejection: {reason}"
    
    # Add MTF boost to confidence
    mtf_boost = 1.15  # 15% boost for MTF alignment
    final_confidence *= mtf_boost
    
    return True
```

---

### 5.3: Portfolio Optimization (Week 3-4)

**Objective:** Optimize position sizing and risk allocation across trades.

#### Position Sizing Algorithm:

**Kelly Criterion with Adjustment:**

```python
class PortfolioOptimizer:
    def calculate_position_size(self, signal_data, account_balance):
        """
        Kelly Criterion: f* = (p*b - q) / b
        Where:
          p = win probability
          q = loss probability (1-p)
          b = win/loss ratio (avg win / avg loss)
        """
        win_prob = signal_data['ml_score']  # From ML model
        loss_prob = 1 - win_prob
        
        # Get historical win/loss ratio for this ticker
        ticker_stats = self.get_ticker_stats(signal_data['ticker'])
        win_loss_ratio = ticker_stats['avg_win'] / ticker_stats['avg_loss']
        
        # Kelly fraction
        kelly_fraction = (win_prob * win_loss_ratio - loss_prob) / win_loss_ratio
        
        # Apply 0.5x Kelly for safety ("Half Kelly")
        safe_fraction = kelly_fraction * 0.5
        
        # Cap at max risk per trade (2% of account)
        max_risk = 0.02
        final_fraction = min(safe_fraction, max_risk)
        
        # Calculate dollar allocation
        position_value = account_balance * final_fraction
        
        # Convert to option contracts
        option_price = signal_data['entry_price']
        contracts = int(position_value / (option_price * 100))
        
        return max(contracts, 1)  # Minimum 1 contract
```

#### Correlation Management:

```python
def check_correlation_exposure(self, new_ticker, existing_positions):
    """
    Avoid taking correlated positions (e.g., AAPL + MSFT + GOOGL all long).
    """
    sectors = self.get_sector_exposure(existing_positions)
    new_sector = self.get_sector(new_ticker)
    
    # Limit sector exposure to 40% of portfolio
    if sectors.get(new_sector, 0) > 0.40:
        return False, f"Sector exposure limit reached: {new_sector}"
    
    # Check individual ticker correlation
    for pos in existing_positions:
        correlation = self.get_correlation(new_ticker, pos['ticker'])
        if correlation > 0.7:
            return False, f"High correlation with {pos['ticker']}"
    
    return True, "Correlation OK"
```

---

### 5.4: Adaptive Parameter Tuning (Week 4-5)

**Objective:** Auto-adjust stop widths, target ratios based on market conditions.

#### Market Regime Detection:

```python
class MarketRegimeDetector:
    def detect_regime(self, spy_data):
        """
        Classify market into regime:
          1. BULL_TRENDING: Strong uptrend, low vol
          2. BEAR_TRENDING: Strong downtrend, low vol
          3. CHOPPY_HIGH_VOL: Range-bound, high vol
          4. CHOPPY_LOW_VOL: Range-bound, low vol
        """
        # Calculate indicators
        adx = talib.ADX(spy_data['high'], spy_data['low'], spy_data['close'], 14)
        atr_pct = talib.ATR(...) / spy_data['close'][-1]
        ema20 = talib.EMA(spy_data['close'], 20)
        
        # Regime logic
        if adx[-1] > 25 and spy_data['close'][-1] > ema20[-1]:
            return 'BULL_TRENDING'
        elif adx[-1] > 25 and spy_data['close'][-1] < ema20[-1]:
            return 'BEAR_TRENDING'
        elif atr_pct > 0.015:  # 1.5%
            return 'CHOPPY_HIGH_VOL'
        else:
            return 'CHOPPY_LOW_VOL'
```

#### Regime-Based Parameter Adjustment:

```python
class AdaptiveParameters:
    def get_parameters(self, regime, grade):
        """
        Return adjusted stop/target widths based on regime.
        """
        base_params = CONFIG['grade_parameters'][grade]
        
        if regime == 'BULL_TRENDING':
            # Tight stops, aggressive targets
            return {
                'stop_width': base_params['stop'] * 0.85,
                't1_multiplier': base_params['t1'] * 1.2,
                't2_multiplier': base_params['t2'] * 1.3
            }
        
        elif regime == 'CHOPPY_HIGH_VOL':
            # Wide stops, conservative targets
            return {
                'stop_width': base_params['stop'] * 1.25,
                't1_multiplier': base_params['t1'] * 0.8,
                't2_multiplier': base_params['t2'] * 0.7
            }
        
        else:
            return base_params
```

---

### 5.5: Enhanced Exit Management (Week 5-6)

**Objective:** Dynamic exits based on real-time conditions.

#### Trailing Stop Logic:

```python
def update_trailing_stop(self, position):
    """
    Once T1 hit, trail stop to lock in profits.
    """
    if not position['t1_hit']:
        return position['stop_price']  # Static stop
    
    # T1 hit - activate trailing stop
    current_price = self.get_current_price(position['ticker'])
    entry = position['entry_price']
    direction = position['direction']
    
    if direction == 'bull':
        # Trail 50% of current profit
        profit = current_price - entry
        new_stop = entry + (profit * 0.5)
        return max(new_stop, position['stop_price'])  # Never lower stop
    
    else:  # bear
        profit = entry - current_price
        new_stop = entry - (profit * 0.5)
        return min(new_stop, position['stop_price'])  # Never raise stop
```

#### Time-Based Exits:

```python
def check_time_exit(self, position):
    """
    Close losing positions before EOD, let winners run.
    """
    time_in_trade = (datetime.now() - position['entry_time']).total_seconds() / 3600
    current_pnl = position['unrealized_pnl']
    
    # Losing trade held > 2 hours? Close it.
    if current_pnl < -100 and time_in_trade > 2:
        return True, "Time stop: Losing trade"
    
    # Winning trade can run until EOD
    if current_pnl > 0:
        return False, None
    
    return False, None
```

---

## Phase 5 Development Sequence

### Week 1-2: ML Signal Scoring
- [ ] Build feature extraction pipeline
- [ ] Train initial model on historical data
- [ ] Backtest ML-enhanced signals
- [ ] Integrate into sniper.py
- [ ] Deploy and collect 1 week of live data

### Week 3: Multi-Timeframe Sync
- [ ] Build MTF data fetcher
- [ ] Implement alignment logic
- [ ] Test MTF filtering
- [ ] Integrate into validator
- [ ] Deploy and monitor

### Week 4: Portfolio Optimization
- [ ] Implement Kelly position sizing
- [ ] Add correlation checks
- [ ] Build sector exposure limits
- [ ] Integrate into position manager
- [ ] Test with paper trading

### Week 5: Adaptive Parameters
- [ ] Build regime detector
- [ ] Create parameter adjustment logic
- [ ] Backtest regime-based params
- [ ] Integrate and deploy
- [ ] Monitor performance by regime

### Week 6: Enhanced Exits
- [ ] Implement trailing stops
- [ ] Add time-based exits
- [ ] Build partial profit-taking logic
- [ ] Integrate and test
- [ ] Final deployment

---

## Success Metrics (Phase 5)

### ML Signal Scoring:
- ✅ ML model accuracy ≥70% on test set
- ✅ Win rate improves by 5-10% vs rule-based only
- ✅ Feature importance analysis shows logical drivers

### MTF Synchronization:
- ✅ Reduces false signals by 20-30%
- ✅ Win rate on MTF-aligned signals ≥70%
- ✅ Drawdowns reduced vs no MTF filter

### Portfolio Optimization:
- ✅ Kelly sizing beats fixed sizing by 15%+
- ✅ Sector diversification maintained
- ✅ No correlated blowups

### Adaptive Parameters:
- ✅ Regime detection accuracy ≥80%
- ✅ Stop hit rate optimized per regime
- ✅ Better profit capture in trending markets

### Enhanced Exits:
- ✅ Trailing stops lock in 10-15% more profit
- ✅ Time stops reduce max loss per trade
- ✅ Average P&L per trade increases

---

## Dependencies

### Python Libraries:
```bash
pip install scikit-learn xgboost lightgbm
pip install pandas numpy scipy
pip install ta-lib  # Technical indicators
pip install joblib  # Model persistence
```

### Data Requirements:
- 200+ closed trades for ML training (minimum)
- 500+ trades for robust model (ideal)
- Multi-timeframe OHLCV data (1m to 1D)
- Market internals data (TICK, TRIN, VIX)

---

## Risk Considerations

⚠️ **Overfitting:** ML models can overfit to historical data. Use cross-validation and out-of-sample testing.

⚠️ **Data Leakage:** Ensure features don't contain future information. Validate temporal splits.

⚠️ **Regime Shifts:** Model trained in bull market may fail in bear market. Retrain quarterly.

⚠️ **Complexity:** More features = more failure points. Start simple, add complexity gradually.

---

## After Phase 5

You'll have:
- ✅ ML-enhanced signal selection
- ✅ Multi-timeframe filtering
- ✅ Optimized position sizing
- ✅ Adaptive parameters
- ✅ Dynamic exits

**Expected Outcome:**
- Win rate: 65-75%
- Sharpe ratio: 2.0+
- Max drawdown: <10%
- Consistency: Profitable 70%+ of weeks

---

**Start Phase 5 after Phase 4 has collected 2-4 weeks of comprehensive data!**
