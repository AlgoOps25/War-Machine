# Phase 4 Monitoring Dashboard Guide

Comprehensive performance visibility for the War Machine trading system.

## Overview

The Monitoring Dashboard provides real-time insights into:
- Signal funnel conversion rates (where signals drop off)
- Win rate breakdown by grade, signal type, and ticker
- Confidence multiplier effectiveness (IVR, UOA, GEX, MTF)
- Validator performance (which checks matter most)
- Learning engine adaptations (ticker-specific multipliers)

---

## Quick Start

### 1. Basic Usage

```python
from monitoring_dashboard import dashboard

# Print live session summary
dashboard.print_live_summary()

# Print comprehensive EOD report
dashboard.print_eod_report()

# Send EOD summary to Discord
dashboard.send_discord_summary()
```

### 2. Command Line Usage

```bash
# Live session stats
python monitoring_dashboard.py live

# End-of-day report
python monitoring_dashboard.py eod

# Send to Discord
python monitoring_dashboard.py discord
```

---

## Integration with main.py

### Option 1: Manual Checks (Recommended)

Add to your `main.py` at strategic points:

```python
from monitoring_dashboard import dashboard

# During trading session (every hour)
def check_performance():
    dashboard.print_live_summary()

# At market close (3:55 PM ET)
def end_of_day():
    dashboard.print_eod_report()
    dashboard.send_discord_summary()
```

### Option 2: Automatic Integration

Add to `sniper.py` at EOD close:

```python
# In process_ticker() when force close triggers
if is_force_close_time(bars_session[-1]):
    position_manager.close_all_eod({ticker: bars_session[-1]["close"]})
    
    # Print validator stats
    print_validation_stats()
    
    # NEW: Print Phase 4 analytics summary
    if PHASE_4_ENABLED:
        try:
            from monitoring_dashboard import dashboard
            print("\n" + "="*80)
            dashboard.print_eod_report()
            dashboard.send_discord_summary()
        except Exception as e:
            print(f"[DASHBOARD] Error: {e}")
    
    return
```

---

## Dashboard Sections Explained

### 1. Signal Funnel Analysis

**What it shows:**
```
Generated:   12
Validated:    8  (66.7% conversion)
Armed:        5  (62.5% conversion)
Traded:       4  (80.0% conversion)
Overall:  33.3% (Generated → Traded)
```

**How to interpret:**
- **Generated → Validated**: How many signals pass multi-indicator checks?
  - Low %: Validator too strict or patterns generating in bad conditions
  - High %: Validator aligned with CFW6 patterns

- **Validated → Armed**: How many pass confirmation?
  - Low %: Confirmation layer rejecting too many or setups not retesting
  - High %: Strong FVG zones with good retest behavior

- **Armed → Traded**: How many armed signals convert to positions?
  - Low %: Position manager rejecting (correlation, risk limits, circuit breaker)
  - High %: Risk controls not blocking good setups

- **Overall (Gen → Traded)**: Total efficiency
  - Target: 30-40% (balance between quality and quantity)
  - <20%: System too restrictive, missing opportunities
  - >60%: Possibly too loose, quality may suffer

### 2. Performance by Grade

**What it shows:**
```
A+:  5 trades |  80.0% WR | Avg: $+125.50 | Total: $+627.50
A :  8 trades |  62.5% WR | Avg: $+85.25  | Total: $+682.00
A-:  3 trades |  33.3% WR | Avg: $-45.00  | Total: $-135.00
```

**How to interpret:**
- **A+ Grade**: Should be your highest win rate (target: 70-80%)
  - If lower: Confidence thresholds may need adjustment
  - If higher: Consider loosening A+ requirements slightly

- **A Grade**: Solid performers (target: 60-70%)
  - Bulk of your trades should be here
  - Compare avg P&L vs A+ to validate risk/reward

- **A- Grade**: Marginal setups (target: 50-60%)
  - If <50%: Consider removing A- entirely or raising confidence floor
  - If >60%: May be undervaluing these setups

### 3. Validator Performance

**What it shows:**
```
Passed: 8 | Failed: 4 | Pass Rate: 66.7%
Top Rejection Reasons:
  • VOLUME_WEAK: 3
  • DMI_CONFLICT: 2
  • ADX_WEAK: 1
```

**How to interpret:**
- **Pass Rate**: Balance between filtering and opportunity
  - <50%: Validator too strict, missing trades
  - >80%: Validator too loose, not adding value
  - Target: 60-70%

- **Top Rejections**: Which checks filter most
  - Focus optimization efforts here
  - If one check dominates rejections, may need threshold adjustment
  - Cross-reference with win rate: Do rejected signals actually lose?

### 4. Multiplier Impact

**What it shows:**
```
IVR:   Avg 1.050 |  5 trades | 80.0% WR
UOA:   Avg 1.075 |  3 trades | 66.7% WR
GEX:   Avg 1.025 |  7 trades | 71.4% WR
MTF:   Avg 0.030 |  4 trades | 75.0% WR
```

**How to interpret:**
- **Avg Value**: Typical confidence boost from multiplier
  - IVR/UOA/GEX: 1.0 = neutral, >1.0 = boost, <1.0 = penalty
  - MTF: Absolute boost value (0.00-0.10 typical)

- **Trades Boosted**: How often multiplier activates
  - Low count: Multiplier rarely available (data issue?)
  - High count with low win rate: Multiplier may be misleading

- **Win Rate**: Does the multiplier predict success?
  - Higher than baseline: Multiplier is working
  - Lower than baseline: Multiplier logic needs revision

### 5. Signal Type Comparison

**What it shows:**
```
CFW6_OR:        6 trades | 66.7% WR | Avg: $+95.50
CFW6_INTRADAY:  4 trades | 75.0% WR | Avg: $+110.25
```

**How to interpret:**
- **OR-Anchored**: Traditional opening range breakout signals
  - Typically higher volume (market open momentum)
  - May have larger R:R but lower win rate

- **Intraday BOS**: Fallback patterns when OR is choppy
  - Often cleaner setups (no OR noise)
  - May have tighter stops but higher win rate

- **Strategy**: If one significantly outperforms, consider:
  - Adjusting confidence thresholds differently by type
  - Prioritizing the stronger signal type

### 6. Learning Engine Status

**What it shows:**
```
Boosted Tickers (Multiplier > 1.0):
  SPY: 1.125x
  AAPL: 1.085x
  NVDA: 1.050x

Penalized Tickers (Multiplier < 1.0):
  AMD: 0.950x
  TSLA: 0.925x
```

**How to interpret:**
- **Boosted**: AI learned these tickers work well with your strategy
  - Higher multipliers = more historical wins
  - Focus scanning on these tickers

- **Penalized**: AI learned these tickers underperform
  - Lower multipliers = more historical losses
  - Consider avoiding or requiring higher confidence

- **Adaptation**: Multipliers should change over time
  - Static values: Learning engine may not be updating (check logs)
  - Extreme values (>1.3 or <0.7): May need smoothing

---

## Discord Integration

### Setup

1. Ensure `discord_helpers.py` is configured with your webhook URL
2. Dashboard automatically uses the same webhook as trade alerts

### Customization

Modify `send_discord_summary()` in `monitoring_dashboard.py` to add:
- Performance charts (use Discord embeds)
- Custom alerts (win rate thresholds)
- Comparison to previous days

### Example EOD Discord Message

```
📡 WAR MACHINE - EOD SUMMARY
📅 Tuesday, February 24, 2026

Signal Funnel:
Generated: 12 → Validated: 8 → Armed: 5 → Traded: 4
Efficiency: 33.3% (Gen → Traded)

Performance by Grade:
A+: 2 trades | 100.0% WR | $+250.00
A: 2 trades | 50.0% WR | $+50.00
```

---

## Troubleshooting

### "No data available" / Empty reports

**Cause**: Phase 4 tracking not collecting data yet

**Fix**:
1. Verify `signal_analytics.py` exists and imports successfully
2. Check that `sniper.py` and `position_manager.py` have Phase 4 integration
3. Run system for at least one signal generation cycle
4. Check database: `SELECT COUNT(*) FROM signal_events;`

### Validator stats showing 0/0

**Cause**: Validator not recording results to `signal_events` table

**Fix**:
1. Verify `signal_validator.py` is being called from `sniper.py`
2. Check that validation results are passed to `signal_tracker.record_validation_result()`
3. Enable validator debug logging to see if checks are running

### Learning engine showing no tickers

**Cause**: No historical trade data or AI not trained yet

**Fix**:
1. Run system for at least 10-20 trades to build history
2. Check `ai_learning.py` is recording trades correctly
3. Verify `positions` table has closed trades with P&L data

### Discord messages not sending

**Cause**: `discord_helpers.py` not configured or webhook invalid

**Fix**:
1. Check `config.py` has valid `DISCORD_WEBHOOK_URL`
2. Test webhook directly: `curl -X POST -H 'Content-Type: application/json' -d '{"content":"test"}' YOUR_WEBHOOK_URL`
3. Check Railway logs for Discord API errors

---

## Advanced Usage

### Custom Date Ranges

```python
from monitoring_dashboard import dashboard
from datetime import datetime

# Specific date analysis
date = "2026-02-24"
funnel = dashboard.get_signal_funnel(date)
print(f"Funnel efficiency: {funnel['conversion_rates']['gen_to_traded']:.1f}%")

# Last 7 days performance
by_grade = dashboard.get_performance_by_grade(lookback_days=7)
for grade, stats in by_grade.items():
    print(f"{grade}: {stats['win_rate']:.1f}% WR over {stats['trades']} trades")
```

### Programmatic Alerts

```python
from monitoring_dashboard import dashboard

# Alert if win rate drops below threshold
stats = dashboard.get_performance_by_grade(lookback_days=1)
for grade, data in stats.items():
    if data['win_rate'] < 50:
        print(f"⚠️ ALERT: {grade} win rate dropped to {data['win_rate']}%")
        # Send alert via Discord or other notification system
```

### Export to CSV

```python
import csv
from monitoring_dashboard import dashboard

by_ticker = dashboard.get_performance_by_ticker(lookback_days=30)

with open('ticker_performance.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Ticker', 'Trades', 'Win Rate', 'Avg P&L', 'Total P&L'])
    for ticker, stats in by_ticker.items():
        writer.writerow([
            ticker,
            stats['trades'],
            f"{stats['win_rate']:.1f}%",
            f"${stats['avg_pnl']:.2f}",
            f"${stats['total_pnl']:.2f}"
        ])
```

---

## Next Steps

### Immediate (Day 1)
1. Run `python monitoring_dashboard.py live` during trading session
2. Review signal funnel - identify bottlenecks
3. Check grade performance - validate confidence thresholds
4. Setup EOD Discord alerts

### Short Term (Week 1)
1. Analyze validator effectiveness over 5+ days
2. Tune multiplier weights based on win correlation
3. Identify top/bottom performing tickers
4. Adjust confidence floors if needed

### Long Term (Month 1)
1. Build historical performance database
2. A/B test validator threshold changes
3. Optimize signal type weighting (OR vs Intraday)
4. Develop custom performance metrics

---

## API Reference

### MonitoringDashboard Class

#### `get_signal_funnel(date: Optional[str] = None) -> Dict`
Returns signal funnel conversion rates for specified date.

#### `get_performance_by_grade(lookback_days: int = 30) -> Dict[str, Dict]`
Returns win rate and P&L breakdown by signal grade.

#### `get_performance_by_ticker(lookback_days: int = 30, min_trades: int = 3) -> Dict[str, Dict]`
Returns win rate and P&L breakdown by ticker.

#### `get_performance_by_signal_type(lookback_days: int = 30) -> Dict[str, Dict]`
Compares OR-anchored vs Intraday BOS signal performance.

#### `get_confidence_distribution(date: Optional[str] = None) -> Dict`
Analyzes confidence score distribution and accuracy by bucket.

#### `get_multiplier_impact(lookback_days: int = 7) -> Dict`
Analyzes effectiveness of confidence multipliers (IVR, UOA, GEX, MTF, ticker).

#### `get_validator_stats(date: Optional[str] = None) -> Dict`
Returns validator pass/fail rates and top rejection reasons.

#### `get_learning_engine_status() -> Dict`
Returns AI ticker multipliers (boosted and penalized tickers).

#### `print_live_summary()`
Prints formatted real-time session summary to console.

#### `print_eod_report()`
Prints comprehensive end-of-day performance report.

#### `send_discord_summary()`
Sends EOD summary to Discord webhook.

---

## Support

For issues or questions:
1. Check Railway logs for error messages
2. Verify database schema matches Phase 4 requirements
3. Test each dashboard method individually to isolate issues
4. Review commit history for recent changes that may affect tracking

**Dashboard Version**: 1.0 (Thread 1 Complete)
**Last Updated**: February 24, 2026
