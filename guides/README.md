# WAR MACHINE — CFW6 Day Trading System

> 🎉 **PHASE 1 FOUNDATION: COMPLETE!** 🎉  
> **Status:** 10/10 phases implemented | Production Ready  
> **Next:** Phase 2 - Live Trading Integration  
> 📄 **[View Complete Phase 1 Summary](../docs/PHASE_1_COMPLETE.md)**

---

**War Machine** is a fully automated 0DTE options day trading system built around the **CFW6 strategy**: Opening Range Breakout (ORB) → Fair Value Gap (FVG) → Multi-timeframe Confirmation → Precision entries with adaptive stops and scale-out targets.

---

## ✨ Phase 1 Achievements

### ✅ Foundation Infrastructure
- **PostgreSQL/SQLite Database** - Cross-database compatibility layer
- **Real-Time WebSocket Feed** - EODHD 1m bars with auto-reconnect
- **Discord Alert System** - Rich embeds for all trade lifecycle events
- **Railway Deployment** - Production-ready cloud infrastructure

### ✅ Signal Generation
- **CFW6 Pattern Detection** - ORB, BOS, FVG with multi-timeframe confirmation
- **Confidence Scoring** - 0-100 scale with time decay and MTF bonuses
- **Signal Quality Grading** - A+/A/A- classification system
- **Adaptive Thresholds** - Volatility-based FVG and ORB calibration

### ✅ Options Integration
- **Live Options Chain** - Real-time strike selection and Greeks
- **IV Rank Filtering** - 20-80 range (avoid IV crush)
- **Delta Targeting** - Grade-adjusted delta ranges (0.35-0.60)
- **Liquidity Validation** - OI, volume, spread filters
- **GEX & UOA Multipliers** - Gamma exposure and unusual activity analysis

### ✅ Risk Management
- **Circuit Breaker** - Auto-stop at -3% daily loss
- **Max Drawdown Monitor** - -5% from intraday peak
- **Sector Limits** - 40% max per sector (correlation tracking)
- **Dynamic Position Sizing** - Performance-based adjustment (0.5x-1.25x)
- **R:R Validation** - Minimum 1.5:1 before entry

### ✅ AI & Analytics
- **AI Learning Engine** - Ticker-specific confidence multipliers
- **Signal Analytics** - Quality scoring (0-100), expectancy, Sharpe ratio
- **Confidence Calibration** - Predicted vs actual win rate tracking
- **Time-of-Day Analysis** - Performance breakdown by market session
- **Optimization Recommendations** - Automated system tuning alerts

---

## Core Features

### Signal Detection
- **Two-path scanning**: OR-Anchored (9:30-9:40 breakout) + Intraday BOS+FVG fallback
- **Multi-timeframe confirmation**: 5m → 3m → 2m → 1m convergence analysis
- **Adaptive thresholds**: FVG size and ORB break dynamically adjust to volatility (ATR-based)
- **Smart watch state**: BOS alerts trigger watch mode; FVG confirmation arms the signal

### Risk Management
- **Grade-based position sizing**: A+ (3.0%), A (2.4%), A- (1.4%) risk per trade
- **Scale-out logic**: 50% at T1 (2R), remainder at T2 (3.5R), stop moves to breakeven after T1
- **ATR-adjusted stops**: Tighter for A+ signals (1.2×ATR), wider for A- (1.8×ATR)
- **Force close at 3:55 PM ET**: 0DTE day trading rule — no overnight holds
- **Portfolio limits**: Max 5 positions, 40% sector exposure, -3% daily loss circuit breaker

### AI Learning Engine
- **Ticker-specific confidence multipliers**: High WR tickers get boosted (1.10×), underperformers penalized (0.90×)
- **Pattern optimization**: Learns which FVG sizes, confirmation types, and timeframes win
- **Adaptive confidence gates**: Per-grade minimum thresholds after IVR/UOA/GEX multipliers
- **Historical seeding**: Bootstrap with backtest data instead of cold-starting from zero

### Options Integration
- **IV Rank filtering**: Only trades when IVR 20-80 (avoid IV crush)
- **Delta targeting**: A+ = 0.50-0.60Δ, A = 0.40-0.50Δ, A- = 0.35-0.45Δ
- **UOA (Unusual Options Activity)**: Confidence boost when flow aligns with signal
- **GEX (Gamma Exposure)**: Identifies pin zones and hedging pressure

### Data & Execution
- **Real-time WebSocket feed**: EODHD 1-minute bars (extended hours 4 AM - 8 PM ET)
- **PostgreSQL persistence**: All bars, signals, and trades survive Railway redeploys
- **Discord alerts**: Signal arms, scale-outs, exits with full trade context
- **Position tracking**: Live P&L, drawdown, win rate by grade
- **Performance monitoring**: Quality scoring, expectancy, Sharpe ratio, max drawdown

---

## Quick Start

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set Environment Variables

Create a `.env` file:

```bash
EODHD_API_KEY=your_eodhd_api_key_here
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DATABASE_URL=postgresql://user:pass@host:port/db  # Railway provides this
ACCOUNT_SIZE=25000
```

### 3. Seed the AI Learning Engine (Recommended)

Instead of starting from zero, seed with 30 days of backtest data:

```bash
python seed_learning_engine.py --use-watchlist --days 30 --reset
```

**What this does:**
- Backtests your entire watchlist over the last 30 days
- Assigns grades (A+/A/A-) to each historical trade
- Imports trades into AI learning engine
- Calibrates ticker confidence multipliers based on real win rates
- Identifies underperformers (AAPL, NVDA) and applies penalty multipliers

**Output example:**
```
[SEED] Importing 156 trades...
[SEED] Ticker Confidence Multipliers:
  SPY: 1.10x (15 trades, 73.3% WR)
  AAPL: 0.90x (8 trades, 37.5% WR)  ← penalized
  NVDA: 0.90x (6 trades, 33.3% WR)  ← penalized
```

See **[SEEDING_GUIDE.md](./SEEDING_GUIDE.md)** for full details.

### 4. Run the Scanner

```bash
python scanner.py
```

The scanner:
1. Connects to EODHD WebSocket for live 1m bars
2. Runs 30-day historical backfill (for OR and prior-day context)
3. Scans watchlist every 30-180 seconds (adaptive by time of day)
4. Arms signals when CFW6 + confirmation layers pass confidence gates
5. Monitors open positions for stops/targets
6. Force-closes all positions at 3:55 PM ET

---

## File Structure

```
/
├─ scanner.py                    # Main orchestrator
├─ sniper.py                     # Signal detection + arming logic
├─ data_manager.py               # Bar storage + WebSocket integration
├─ ws_feed.py                    # EODHD WebSocket client
├─ bos_fvg_engine.py             # Intraday BOS+FVG detection
├─ cfw6_confirmation.py          # Multi-TF confirmation layers
├─ position_manager.py           # Trade tracking + scale-out logic
├─ ai_learning.py                # Learning engine core
├─ options_filter.py             # IV rank, delta targeting, UOA, GEX
├─ trade_calculator.py           # Stop/target calculation
├─ config.py                     # All tuning parameters
├─ signal_analytics.py           # Performance monitoring & analytics
├─ backtesting_engine.py         # Historical backtest runner
├─ seed_learning_engine.py       # Backtest → AI learning pipeline
├─ analyze_learning_state.py     # Diagnose underperforming tickers/grades
├─ docs/
│  ├─ PHASE_1_COMPLETE.md        # Phase 1 summary (10/10 complete)
│  └─ ARCHITECTURE.md            # System design overview
├─ guides/
│  └─ SEEDING_GUIDE.md           # AI learning seeding workflow
└─ requirements.txt              # Python dependencies
```

---

## AI Learning Workflow

### Initial Setup (Before First Live Trade)

1. **Seed with historical data** (30-60 days):
   ```bash
   python seed_learning_engine.py --use-watchlist --days 30 --reset
   ```

2. **Analyze baseline performance**:
   ```bash
   python analyze_learning_state.py
   ```

3. **Review problem tickers** (low WR, negative P&L):
   ```
   🚨 UNDERPERFORMING TICKERS:
     AAPL: 8 trades, 37.5% WR, $-1,200
       Recommendation: Consider removing from watchlist or blocking A- signals
   ```

4. **Adjust config if needed**:
   - Raise `MIN_CONFIDENCE_BY_GRADE["A-"]` to block low-quality signals
   - Remove chronic underperformers from `FINAL_WATCHLIST` in `screener.py`
   - Tighten `MIN_CONFIDENCE_INTRADAY` if intraday signals are weak

### Live Trading (Continuous Learning)

Once live:
- Every closed trade is recorded via `position_manager.close_position()`
- AI learning engine recalculates ticker multipliers after each trade
- Confidence gates adapt based on real win rates (not backtests)
- Run `analyze_learning_state.py` weekly to diagnose patterns

### After 30 Days Live

Once you have 50+ real trades:
- **Do NOT re-seed** — live execution data (fills, slippage, timing) is more valuable than backtests
- Use `analyze_learning_state.py --ticker AAPL --show-trades` to deep-dive specific tickers
- Adjust `config.py` thresholds based on real-world performance

---

## Configuration Tuning

### Key Parameters (`config.py`)

| Parameter | Default | Purpose |
|-----------|---------|----------|
| `MIN_CONFIDENCE_OR` | 0.70 | Minimum confidence for OR-path signals |
| `MIN_CONFIDENCE_INTRADAY` | 0.75 | Minimum confidence for intraday BOS signals |
| `MIN_CONFIDENCE_BY_GRADE["A-"]` | 0.78 | A- signals must hit 78% after multipliers |
| `MAX_DAILY_LOSS_PCT` | 3.0 | Circuit breaker threshold (-3% daily loss) |
| `MAX_INTRADAY_DRAWDOWN_PCT` | 5.0 | Max drawdown from intraday peak |
| `MAX_OPEN_POSITIONS` | 5 | Maximum concurrent positions |
| `MAX_SECTOR_EXPOSURE_PCT` | 40.0 | Maximum exposure per sector |
| `MIN_RISK_REWARD_RATIO` | 1.5 | Minimum R:R to enter trade |
| `ORB_BREAK_THRESHOLD` | 0.001 | 0.1% breakout threshold (adaptive by volume) |
| `FVG_MIN_SIZE_PCT` | 0.002 | 0.2% minimum FVG size (adaptive by ATR) |
| `MIN_OR_RANGE_PCT` | 0.003 | 0.3% minimum OR width (skips choppy opens) |
| `STOP_MULTIPLIERS["A+"]` | 1.2 | ATR stop multiplier for A+ signals |
| `TARGET_1_RR` | 2.0 | Risk:reward for T1 (scale-out) |
| `TARGET_2_RR` | 3.5 | Risk:reward for T2 (full exit) |

### When to Adjust

- **Too many false signals**: Raise `MIN_CONFIDENCE_INTRADAY` or `MIN_OR_RANGE_PCT`
- **Missing good setups**: Lower `FVG_MIN_SIZE_PCT` or `ORB_BREAK_THRESHOLD`
- **Stops too tight**: Increase `STOP_MULTIPLIERS` for problem grades
- **A- signals losing**: Raise `MIN_CONFIDENCE_BY_GRADE["A-"]` to 0.85 or 0.95
- **Hitting daily loss limit**: Lower `POSITION_RISK` or `MAX_OPEN_POSITIONS`

---

## Troubleshooting

### "No session bars" on startup

**Cause:** WebSocket not connected yet, or today's bars haven't populated.

**Fix:**
1. Check `[WS] Connected` log line
2. Wait 30 seconds after startup for backfill to complete
3. Run `startup_intraday_backfill_today()` if mid-session restart

### AAPL/NVDA losing every trade

**Cause:** Large caps with heavy options flow tend to chop FVG zones before confirming.

**Fix:**
1. Run `python analyze_learning_state.py --ticker AAPL`
2. Check if A- grades dominate (low-quality signals)
3. Raise `MIN_CONFIDENCE_BY_GRADE["A-"]` to 0.85
4. Or remove from watchlist if WR < 30% after 20+ trades

### Confidence multipliers not updating

**Cause:** Trades aren't being recorded (Bug #9 was fixed in `position_manager.py`).

**Fix:**
1. Verify `learning_engine.record_trade()` is called in `close_position()`
2. Check PostgreSQL `ai_learning_state` table for recent updates
3. Run `python analyze_learning_state.py` to confirm trades are present

### Railway deployment resets watch state

**Cause:** Watch state is stored in `watching_signals_persist` PostgreSQL table.

**Fix:** Already handled — watches survive redeploys. Check `[WATCH-DB] 🔄 Reloaded` log.

### Circuit breaker triggered

**Cause:** Daily loss limit reached (-3% default).

**Fix:**
1. Check `position_manager.get_risk_summary()` for details
2. No new positions will open until next trading session
3. Review `signal_analytics.print_performance_report()` for patterns
4. Consider raising `MIN_CONFIDENCE_OR` to be more selective

---

## Deployment (Railway)

### Environment Variables

Set in Railway dashboard:

```
EODHD_API_KEY=your_key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DATABASE_URL=${{Postgres.DATABASE_URL}}  # Auto-provided by Railway
ACCOUNT_SIZE=25000
ENVIRONMENT=production
```

### Procfile

```
web: python scanner.py
```

### Railway Build Command

```bash
pip install -r requirements.txt
python seed_learning_engine.py --use-watchlist --days 30 --reset
```

This seeds the AI learning engine during deployment before the scanner starts.

---

## Performance Monitoring

### Real-Time Risk Dashboard

```python
from position_manager import position_manager
print(position_manager.get_risk_summary())
```

**Output:**
```
============================================================
RISK MANAGEMENT SUMMARY
============================================================
Account Balance:  $25,750
Session Start:    $25,000
High Water Mark:  $26,200
Daily P&L:        +$750 (+3.00%)
Max Drawdown:     -1.72% (limit: -3.00%)
Open Positions:   3 / 5 max
Total Exposure:   $2,400 (9.3%)
Performance:      2W (x1.10)
Circuit Breaker:  ✅ OK
============================================================
```

### Daily Reports

EOD (after 3:55 PM ET close):

```python
from signal_analytics import print_performance_report
print_performance_report(days=30)
```

**Output includes:**
- Win rate, profit factor, total P&L
- Quality score (0-100), expectancy, Sharpe ratio
- Per-ticker breakdown
- Time-of-day performance
- Optimization recommendations

### Weekly Analysis

```bash
python analyze_learning_state.py
```

**Output:**
- Ticker performance table (sorted by P&L)
- Underperforming tickers with recommendations
- Grade breakdown (A+/A/A-)
- Confidence multiplier status

### Deep Dives

```bash
python analyze_learning_state.py --ticker AAPL --show-trades
```

Shows all AAPL trades with:
- Entry/exit prices
- P&L per trade
- FVG size, OR break size
- Grade assigned
- Recommendations

---

## System Architecture

### Data Flow

1. **EODHD WebSocket** → `ws_feed.py` → `data_manager.store_bars()` (quiet=True during backfill)
2. **Scanner cycle** → `sniper.process_ticker()` → BOS detection → FVG detection
3. **Watch alert** → Discord → Wait for FVG (up to 30 bars)
4. **FVG found** → Confirmation layers → Confidence calculation → Arm signal
5. **Position opened** → `position_manager.open_position()` → Monitor stops/targets
6. **Exit hit** → `position_manager.close_position()` → `learning_engine.record_trade()`
7. **EOD** → Force close all → AI learning optimization → Discord digest

### Confidence Calculation

```python
base_confidence = compute_confidence(grade, "5m", ticker)  # 0.65-0.85
ticker_mult = learning_engine.get_ticker_confidence_multiplier(ticker)  # 0.90-1.10
mtf_boost = calculate_mtf_convergence_boost(ticker)  # 0-0.15
ivr_mult = options_rec["ivr_multiplier"]  # 0.95-1.05
uoa_mult = options_rec["uoa_multiplier"]  # 0.95-1.10
gex_mult = options_rec["gex_multiplier"]  # 0.90-1.08

final_confidence = (
    base_confidence * ticker_mult * ivr_mult * uoa_mult * gex_mult
) + mtf_boost

# Gate check
min_threshold = max(
    MIN_CONFIDENCE_OR,  # 0.70
    MIN_CONFIDENCE_BY_GRADE[grade],  # 0.65-0.78
    CONFIDENCE_ABSOLUTE_FLOOR  # 0.60
)

if final_confidence < min_threshold:
    # Signal dropped
```

### Risk Validation

```python
# Before opening position
can_open, reason = position_manager.can_open_position(ticker, risk_dollars)

# Checks:
# 1. Circuit breaker (daily loss limit)
# 2. Max drawdown from peak
# 3. Max open positions (5)
# 4. Sector exposure (40% max)
# 5. R:R validation (1.5:1 min)
# 6. No duplicate ticker positions

if not can_open:
    print(f"Position rejected: {reason}")
    return
```

---

## FAQ

### Why seed the learning engine?

**Without seeding:** System starts with 1.0× multipliers for all tickers, takes 10-20 live trades to calibrate.

**With seeding:** System starts with real market data, underperformers (AAPL, NVDA) penalized immediately, winning tickers (SPY) boosted from day one.

### How is this different from backtesting?

**Backtesting** answers: "Would this strategy have worked historically?"

**AI learning engine** answers: "Is this strategy working **for me right now** with my execution, fills, and timing?"

Seeding bridges the gap — it uses backtest data to initialize the learning engine, then live trades take over and adapt to real-world conditions.

### Can I use this for stock/futures instead of options?

Yes. Disable options filtering in `options_filter.py` and adjust position sizing in `position_manager.py` to use shares instead of contracts. The CFW6 signal logic is instrument-agnostic.

### What's the minimum account size?

Recommended: **$25,000** for PDT rule compliance (day trading).

Minimum: **$5,000** with careful position sizing (2-3 contracts max).

The system risks 1.4-3.0% per trade depending on grade, so $25K allows 2-4 concurrent positions without overexposure.

### What's next after Phase 1?

**Phase 2: Live Trading Integration**
- Interactive Brokers API integration
- Automated order execution
- Paper trading validation
- Live deployment with small position sizes

See **[docs/PHASE_1_COMPLETE.md](../docs/PHASE_1_COMPLETE.md)** for full Phase 1 summary and Phase 2 roadmap.

---

## Contributing

This is a personal trading system — not open for external contributions. However, if you find bugs or have suggestions, open an issue.

---

## License

Proprietary. For personal use only.

---

## Support

For questions or issues:
1. Check **[docs/PHASE_1_COMPLETE.md](../docs/PHASE_1_COMPLETE.md)** for system capabilities
2. Check `guides/SEEDING_GUIDE.md` for AI learning setup
3. Run `python analyze_learning_state.py` to diagnose performance
4. Review Discord alerts for signal context
5. Check `position_manager.get_risk_summary()` for risk metrics
6. Open a GitHub issue with logs and error messages

---

**War Machine** — Built by traders, for traders. 🎯

*Phase 1 Complete: February 24, 2026*
