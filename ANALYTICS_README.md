# War Machine Signal Analytics System

**Phase 4.0 Integration** - Data-Driven Confirmation Analysis

## Overview

This analytics system tracks your trading signals from generation through execution to outcome, enabling data-driven optimization of your confirmation criteria. It's designed to answer the key question: **"Which confirmation patterns actually lead to winning trades?"**

## What It Does

### 📊 Core Capabilities

1. **Signal Logging** - Automatically tracks every signal generated:
   - Entry, stop, and target prices
   - Signal grade and confidence
   - Generation and fill timestamps
   - Win/loss outcomes and returns

2. **Performance Analysis**:
   - Win rates by signal grade (A+, A, A-)
   - Time-to-failure patterns (immediate vs delayed)
   - Hold time analysis for winners vs losers
   - Quick failure detection (< 5 minutes)

3. **Data Enrichment** (Optional):
   - Post-breakout price action (3-bar confirmation)
   - Volume confirmation patterns
   - Breakout hold rates
   - ML feature generation for advanced modeling

4. **Automated Reporting**:
   - Daily performance summaries
   - Weekly analysis with recommendations
   - Validation statistics
   - Quick database views

## Quick Start (5 Minutes)

### Step 1: Create Database Schema

```bash
python create_analytics_schema.py
```

This creates `signal_analytics.db` with the necessary tables.

### Step 2: Generate Sample Data (Testing)

```bash
python populate_sample_signals.py
```

This creates 50 sample signals with realistic patterns for testing.

### Step 3: View Your Data

```bash
python view_signals.py
```

See overall statistics, grade performance, and recent signals.

### Step 4: Run Analysis

```bash
python daily_analysis.py      # Quick daily summary
python run_full_analysis.py   # Comprehensive analysis
```

## Integration with Existing Code

### Option A: Quick Integration (Recommended)

Add these 3 lines to your signal generation:

```python
from signal_analytics_integration import log_signal, log_fill, log_close

# When signal is generated:
signal_id = log_signal(
    ticker="AAPL",
    direction="BULL",
    grade="A",
    confidence=75,
    entry=150.00,
    stop=148.50,
    t1=152.00,
    t2=154.00
)

# When position is filled:
log_fill(signal_id)

# When position closes:
log_close(signal_id, exit_price=152.50, outcome='win')  # or 'loss'
```

### Option B: Full Integration (Detailed Control)

See `integration_example.py` for complete integration patterns with your existing:
- `signal_generator.py`
- `position_manager.py`
- `position_execution.py`

## Integration Points

### 1. Signal Generation (`signal_generator.py`)

**Current Code:**
```python
def check_ticker(self, ticker: str) -> Optional[Dict]:
    # ... existing breakout detection ...
    
    signal = {
        'ticker': ticker,
        'signal': 'BUY',
        'confidence': 75,
        # ... rest of signal ...
    }
    
    return signal
```

**Add Analytics:**
```python
from signal_analytics_integration import analytics_logger

def check_ticker(self, ticker: str) -> Optional[Dict]:
    # ... existing breakout detection ...
    
    signal = {
        'ticker': ticker,
        'signal': 'BUY',
        'confidence': 75,
        # ... rest of signal ...
    }
    
    # ⭐ LOG SIGNAL
    signal_id = analytics_logger.log_signal_generated(
        ticker=signal['ticker'],
        direction='BULL' if signal['signal'] == 'BUY' else 'BEAR',
        grade=signal.get('grade', 'A'),
        confidence=signal['confidence'] / 100.0,
        entry_price=signal['entry'],
        stop_price=signal['stop'],
        t1_price=signal.get('t1', signal['target']),
        t2_price=signal.get('t2', signal['target'])
    )
    
    signal['signal_id'] = signal_id  # Store for later
    
    return signal
```

### 2. Position Execution (`position_manager.py`)

**Current Code:**
```python
def open_position(self, ticker: str, entry_price: float, ...):
    # ... insert position into database ...
    
    position_id = cursor.lastrowid
    return position_id
```

**Add Analytics:**
```python
from signal_analytics_integration import analytics_logger

def open_position(self, ticker: str, entry_price: float, 
                  signal_id: str = None, ...):
    # ... insert position into database ...
    
    position_id = cursor.lastrowid
    
    # ⭐ LOG FILL
    if signal_id:
        analytics_logger.log_signal_filled(signal_id)
    
    return position_id
```

### 3. Position Closing (`position_manager.py`)

**Current Code:**
```python
def close_position(self, position_id: int, exit_price: float, exit_reason: str):
    # ... calculate P&L ...
    
    pnl = calculate_pnl()
    
    # Update position status
    cursor.execute("UPDATE positions SET status='CLOSED', pnl=? ...", ...)
```

**Add Analytics:**
```python
from signal_analytics_integration import analytics_logger

def close_position(self, position_id: int, exit_price: float, exit_reason: str):
    # Get signal_id from position (if tracked)
    cursor.execute("SELECT signal_id FROM positions WHERE id=?", (position_id,))
    signal_id = cursor.fetchone()
    
    # ... calculate P&L ...
    pnl = calculate_pnl()
    outcome = 'win' if pnl > 0 else 'loss'
    
    # Update position status
    cursor.execute("UPDATE positions SET status='CLOSED', pnl=? ...", ...)
    
    # ⭐ LOG OUTCOME
    if signal_id:
        analytics_logger.log_signal_closed(
            signal_id=signal_id,
            exit_price=exit_price,
            outcome=outcome
        )
```

## Database Schema

### `signals` Table

```sql
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT UNIQUE,              -- Unique identifier
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,            -- 'BULL' or 'BEAR'
    grade TEXT,                         -- 'A+', 'A', 'A-'
    confidence REAL,                    -- 0.0 to 1.0
    generated_at TIMESTAMP,             -- When signal was created
    filled_at TIMESTAMP,                -- When position was entered
    closed_at TIMESTAMP,                -- When position was closed
    signal_time TIMESTAMP,
    entry_price REAL,
    stop_price REAL,
    t1_price REAL,
    t2_price REAL,
    outcome TEXT,                       -- 'win', 'loss', or 'pending'
    return_pct REAL,                    -- Percentage return
    hold_time_minutes REAL,             -- How long position was held
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `confirmations` Table (Advanced)

```sql
CREATE TABLE confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT,
    ticker TEXT,
    timestamp TIMESTAMP,
    volume_ratio REAL,                  -- Breakout volume vs average
    breakout_hold_rate REAL,            -- % of bars that held above entry
    bars_above_entry INTEGER,           -- Count of bars above entry
    post_breakout_high REAL,
    post_breakout_low REAL,
    immediate_rejection BOOLEAN,        -- Did first bar close below entry?
    FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
);
```

## Command-Line Interface

Use `analytics_commands.py` for quick access:

```bash
python analytics_commands.py view       # View current signals
python analytics_commands.py daily      # Run daily analysis
python analytics_commands.py full       # Run full analysis
python analytics_commands.py sample     # Generate sample data
python analytics_commands.py clear      # Clear all signals (WARNING)
python analytics_commands.py schema     # Recreate database
```

## Analysis Scripts

### `daily_analysis.py`

**Run daily after market close (4:15 PM ET)**

Outputs:
- Today's performance (wins, losses, P&L)
- Last 7 days performance by date
- Grade performance (all-time)
- Quick failure analysis
- Recent signals (last 10)

### `run_full_analysis.py`

**Run weekly or after significant changes**

Outputs:
- Grade performance with detailed win rates
- Losing signal timing analysis (immediate vs delayed failures)
- Winning signal hold time patterns
- Post-breakout behavior analysis (with EODHD data)
- Data-driven recommendations

Generates:
- `full_analysis_report_YYYYMMDD_HHMMSS.txt`
- `ml_features_YYYYMMDD_HHMMSS.csv` (if EODHD available)

### `view_signals.py`

**Quick database viewer**

Shows:
- Overall statistics
- Performance by grade
- Recent signals (last 10)

## Automated Scheduling

### Option 1: Manual Schedule (cron/Task Scheduler)

**Linux/Mac (crontab):**
```bash
# Edit crontab
crontab -e

# Add daily analysis at 4:15 PM
15 16 * * 1-5 cd /path/to/War-Machine && python daily_analysis.py

# Add full analysis on Fridays at 5:00 PM
0 17 * * 5 cd /path/to/War-Machine && python run_full_analysis.py
```

**Windows (Task Scheduler):**
```powershell
# Create daily task
schtasks /create /sc daily /tn "WarMachine_DailyAnalysis" /tr "python C:\path\to\War-Machine\daily_analysis.py" /st 16:15

# Create weekly task (Fridays)
schtasks /create /sc weekly /d FRI /tn "WarMachine_FullAnalysis" /tr "python C:\path\to\War-Machine\run_full_analysis.py" /st 17:00
```

### Option 2: Built-in Scheduler

```bash
python schedule_analysis.py
```

This runs a persistent scheduler that:
- Executes daily analysis at 4:15 PM ET
- Executes full analysis on Fridays at 4:15 PM ET

## EODHD Data Enrichment (Optional)

If you have EODHD API access and `data_manager.py` configured:

### Enrichment Features

1. **Post-Breakout Bars**: Fetches 3 bars immediately after signal generation
2. **Confirmation Metrics**:
   - Breakout hold rate (% of bars that stayed above/below entry)
   - Volume analysis (breakout bar vs average)
   - Price action (immediate rejection detection)
3. **ML Features**: Generates feature matrix for advanced modeling

### Usage

```python
from eodhd_historical_enrichment import SignalEnricher

enricher = SignalEnricher()

# Enrich recent signals
recent_signals = get_recent_signals()
enriched = enricher.enrich_signal_list(recent_signals)

# Build ML features
features_df = enricher.build_ml_features_dataframe(enriched)
features_df.to_csv('ml_features.csv', index=False)
```

**Note**: This is automatically included in `run_full_analysis.py`

## Understanding the Reports

### Grade Performance Table

```
grade  total_signals  wins  losses  avg_win_pct  avg_loss_pct  avg_return_pct  avg_confidence  win_rate
-----  -------------  ----  ------  -----------  ------------  --------------  --------------  --------
A+               15    11       4         3.20         -1.80            1.73            0.85     73.33
A                22    13       9         2.80         -1.60            0.95            0.76     59.09
A-               13     6       7         2.50         -1.70           -0.15            0.68     46.15
```

**Interpretation:**
- A+ signals have highest win rate (73%) and best average return
- A- signals are near breakeven (-0.15% avg return)
- Higher confidence correlates with better performance

### Losing Signal Timing

```
Total Losses: 20
Immediate Failures (<5 min): 13 (65.0%)
Quick Failures (5-15 min): 5 (25.0%)
Delayed Failures (15+ min): 2 (10.0%)
Median Hold Time: 4.5 minutes
```

**Interpretation:**
- Most losing signals fail within 5 minutes
- Indicates entry timing issues (buying at resistance top)
- Suggests implementing 2-bar holding period requirement

### Winning Hold Time Analysis

```
A+ Grade (11 signals):
  Median Hold: 35.0 minutes
  Avg Hold: 42.3 minutes
  Range: 15 - 95 minutes
  Avg Return: 3.20%
```

**Interpretation:**
- Winners take longer to develop (35+ min median)
- Quick exits (< 15 min) are more likely to be losers
- Supports holding winners longer

## Recommendations from Analysis

Based on data patterns, the system generates recommendations like:

### Priority 1: Quick Wins
- **Entry 0.15% above breakout** - Confirms breakout is holding
- **2-bar holding period** - Wait for confirmation before entry
- **Widen stops to 2.0 ATR** - Give breakouts room to breathe

### Priority 2: Data-Driven
- **Hold rate filter** - Require X% of bars to hold above entry
- **Volume confirmation** - Adjust based on enrichment data
- **Confidence penalty** - Lower confidence for weak patterns

### Priority 3: Advanced
- **ML-based confirmation** - Train model on enriched features
- **Retest/pullback entry** - Wait for better entry on pullback
- **Multi-timeframe convergence** - Require alignment across TFs

## Workflow Integration

### Morning Routine (Pre-Market)

1. Review yesterday's analysis:
   ```bash
   python daily_analysis.py
   ```

2. Check validation stats (if using signal_validator):
   ```python
   from signal_generator import signal_generator
   signal_generator.print_validation_stats()
   ```

### Intraday (Market Hours)

Signals automatically log to database as they:
- Generate (in `signal_generator.py`)
- Fill (in `position_manager.py`)
- Close (in `position_manager.py`)

No manual intervention required.

### End of Day (After Close)

1. Generate daily report:
   ```bash
   python daily_analysis.py
   ```

2. Weekly (Fridays) - run full analysis:
   ```bash
   python run_full_analysis.py
   ```

3. Review recommendations and adjust strategy

## Troubleshooting

### Database Not Found

```
⚠️ Analytics database not found: signal_analytics.db
   Run: python create_analytics_schema.py
```

**Solution**: Run schema creation script

### No Signals in Database

```
No signals generated today.
```

**Solution**: 
1. Check integration is complete in signal_generator.py
2. Generate sample data for testing: `python populate_sample_signals.py`
3. Verify signals are being generated at all

### EODHD Enrichment Error

```
⚠️ EODHD enrichment error: EODHD client not available
```

**Solution**: 
1. Verify `data_manager.py` exists and is configured
2. Check EODHD API key is set
3. Enrichment is optional - basic analysis will still run

### Module Import Errors

```
❌ Module import error: No module named 'signal_analytics_integration'
```

**Solution**: 
1. Ensure all files are in the same directory
2. Check Python path includes current directory
3. Verify file names match exactly

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   War Machine Trading System                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              signal_generator.py (Signal Creation)           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ breakout_detector → signal → log_signal_generated()   │  │
│  │                              ↓                        │  │
│  │                    signal_analytics.db                │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│           position_manager.py (Position Execution)           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ open_position() → log_signal_filled()                 │  │
│  │ close_position() → log_signal_closed()                │  │
│  │                              ↓                        │  │
│  │                    signal_analytics.db                │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Analysis & Reports                        │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ daily_analysis.py     → Daily summary                 │  │
│  │ run_full_analysis.py  → Weekly deep dive              │  │
│  │ view_signals.py       → Quick database view           │  │
│  │                              ↓                        │  │
│  │              Recommendations & Insights               │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Files Overview

### Core Integration
- `signal_analytics_integration.py` - Main integration layer (3 functions)
- `create_analytics_schema.py` - Database schema setup

### Analysis Scripts
- `analyze_confirmation_patterns.py` - Pattern analysis engine
- `eodhd_historical_enrichment.py` - Data enrichment (optional)
- `run_full_analysis.py` - Comprehensive analysis pipeline
- `daily_analysis.py` - Quick daily summary

### Utilities
- `view_signals.py` - Quick database viewer
- `populate_sample_signals.py` - Test data generator
- `analytics_commands.py` - CLI interface
- `schedule_analysis.py` - Automated scheduler
- `check_schema.py` - Database inspector

### Documentation
- `ANALYTICS_README.md` - This file
- `integration_example.py` - Code integration examples

## Performance Impact

### Database Operations
- Signal logging: < 1ms per signal
- Fill/close logging: < 1ms per operation
- Daily analysis: < 100ms
- Full analysis: 1-5 seconds (depends on signal count)

### Storage
- ~1KB per signal
- 50 signals/day = 50KB/day = ~1MB/month
- Database auto-vacuums on schema recreation

### Memory
- All operations use cursor-based queries
- No in-memory caching of full dataset
- Minimal memory footprint

## Next Steps

1. **Test with Sample Data**:
   ```bash
   python create_analytics_schema.py
   python populate_sample_signals.py
   python daily_analysis.py
   ```

2. **Integrate with Your Code**:
   - Add 3 logging calls to signal_generator.py
   - Add signal_id tracking to position_manager.py
   - Test with live paper trading

3. **Run Analysis**:
   - Daily: After market close
   - Weekly: Friday evening
   - Review and adjust strategy

4. **Advanced Features** (Phase 2):
   - ML model training on enriched features
   - Real-time confirmation scoring
   - Automated strategy adjustment

## Support

For issues or questions:
1. Check troubleshooting section above
2. Verify database schema: `python check_schema.py`
3. Test with sample data first
4. Review integration examples in `integration_example.py`

---

**Phase 4.0 - Data-Driven Trading**

*"Stop guessing. Start measuring."*
