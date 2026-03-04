-- War Machine Signal Analytics Database Schema
-- PostgreSQL Tables for Signal Tracking and ML Training

-- Table 1: Signal Outcomes (main tracking table)
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    signal_time TIMESTAMP NOT NULL,
    pattern VARCHAR(50),
    confidence INTEGER,
    
    -- Entry data
    entry_price DECIMAL(10, 2),
    stop_loss DECIMAL(10, 2),
    target_1 DECIMAL(10, 2),
    target_2 DECIMAL(10, 2),
    
    -- Market context
    regime VARCHAR(20),
    vix_level DECIMAL(5, 2),
    spy_trend VARCHAR(10),
    rvol DECIMAL(5, 2),
    score INTEGER,
    
    -- Outcome data
    outcome VARCHAR(10),  -- WIN, LOSS, BREAKEVEN
    exit_price DECIMAL(10, 2),
    exit_time TIMESTAMP,
    hold_minutes INTEGER,
    profit_pct DECIMAL(6, 2),
    profit_r DECIMAL(4, 2),  -- R-multiple (profit/risk)
    
    -- Flags
    hit_t1 BOOLEAN DEFAULT FALSE,
    hit_t2 BOOLEAN DEFAULT FALSE,
    stopped_out BOOLEAN DEFAULT FALSE,
    explosive_override BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for fast queries
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_ticker ON signal_outcomes(ticker);
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_date ON signal_outcomes(DATE(signal_time));
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_outcome ON signal_outcomes(outcome);

-- Table 2: Pattern Performance (aggregate stats)
CREATE TABLE IF NOT EXISTS pattern_performance (
    id SERIAL PRIMARY KEY,
    pattern VARCHAR(50) UNIQUE NOT NULL,
    total_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    win_rate DECIMAL(5, 2),
    avg_profit_pct DECIMAL(6, 2),
    avg_hold_minutes INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Table 3: ML Training Features
CREATE TABLE IF NOT EXISTS ml_training_data (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signal_outcomes(id),
    
    -- Features (input to ML model)
    rvol DECIMAL(5, 2),
    vix DECIMAL(5, 2),
    score INTEGER,
    time_of_day VARCHAR(10),
    confidence INTEGER,
    regime VARCHAR(20),
    
    -- Target (output/label)
    outcome BOOLEAN,  -- TRUE = WIN, FALSE = LOSS
    profit_r DECIMAL(4, 2),
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for ML queries
CREATE INDEX IF NOT EXISTS idx_ml_training_outcome ON ml_training_data(outcome);
CREATE INDEX IF NOT EXISTS idx_ml_training_signal ON ml_training_data(signal_id);

-- Insert today's NVDA winner (manual entry for bootstrapping)
INSERT INTO signal_outcomes (
    ticker, signal_time, pattern, confidence,
    entry_price, stop_loss, target_1, target_2,
    regime, vix_level, spy_trend, rvol, score,
    explosive_override,
    outcome, exit_price, exit_time, hold_minutes, profit_pct, profit_r,
    hit_t1, hit_t2
) VALUES (
    'NVDA', 
    '2026-03-04 09:40:00',
    'BOS/FVG Breakout',
    100,
    181.61,
    180.16,
    183.79,
    185.24,
    'CHOPPY',
    22.4,
    'NEUTRAL',
    4.0,
    85,
    TRUE,
    'WIN',
    184.50,
    '2026-03-04 10:01:00',
    21,
    1.59,
    1.99,
    TRUE,
    FALSE
) ON CONFLICT DO NOTHING;
