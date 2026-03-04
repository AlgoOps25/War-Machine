-- Signal Outcomes Tracking Schema for War Machine
-- Run this to create tables: psql $DATABASE_URL -f signal_outcomes_schema.sql

-- Main signal tracking table
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    signal_time TIMESTAMP NOT NULL,
    pattern VARCHAR(50) NOT NULL,
    confidence INTEGER NOT NULL,
    
    -- Entry/Exit data
    entry_price DECIMAL(10,2) NOT NULL,
    stop_loss DECIMAL(10,2) NOT NULL,
    target_1 DECIMAL(10,2) NOT NULL,
    target_2 DECIMAL(10,2) NOT NULL,
    exit_price DECIMAL(10,2),
    exit_time TIMESTAMP,
    
    -- Market context
    regime VARCHAR(10),
    vix_level DECIMAL(5,2),
    spy_trend VARCHAR(10),
    rvol DECIMAL(6,2),
    score INTEGER,
    explosive_override BOOLEAN DEFAULT FALSE,
    
    -- Outcome tracking
    outcome VARCHAR(10),  -- WIN, LOSS, BREAKEVEN
    hit_t1 BOOLEAN DEFAULT FALSE,
    hit_t2 BOOLEAN DEFAULT FALSE,
    stopped_out BOOLEAN DEFAULT FALSE,
    hold_minutes INTEGER,
    profit_pct DECIMAL(8,2),
    profit_r DECIMAL(6,2),  -- Profit in R-multiples
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Pattern performance aggregate table
CREATE TABLE IF NOT EXISTS pattern_performance (
    pattern VARCHAR(50) PRIMARY KEY,
    total_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    win_rate DECIMAL(5,2),
    avg_profit_pct DECIMAL(8,2),
    avg_hold_minutes INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ML training data table
CREATE TABLE IF NOT EXISTS ml_training_data (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signal_outcomes(id),
    
    -- Features
    rvol DECIMAL(6,2),
    vix DECIMAL(5,2),
    score INTEGER,
    time_of_day VARCHAR(5),  -- HH:MM format
    confidence INTEGER,
    regime VARCHAR(10),
    
    -- Labels
    outcome BOOLEAN,  -- TRUE = WIN, FALSE = LOSS
    profit_r DECIMAL(6,2),
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_signal_time ON signal_outcomes(signal_time);
CREATE INDEX IF NOT EXISTS idx_ticker ON signal_outcomes(ticker);
CREATE INDEX IF NOT EXISTS idx_pattern ON signal_outcomes(pattern);
CREATE INDEX IF NOT EXISTS idx_outcome ON signal_outcomes(outcome);
CREATE INDEX IF NOT EXISTS idx_ml_training_signal ON ml_training_data(signal_id);

-- Bootstrap with NVDA winner from today (60% gain)
INSERT INTO signal_outcomes (
    ticker, signal_time, pattern, confidence,
    entry_price, stop_loss, target_1, target_2,
    regime, vix_level, spy_trend, rvol, score, explosive_override,
    outcome, exit_price, exit_time, hit_t1, hit_t2, hold_minutes, profit_pct, profit_r
) VALUES (
    'NVDA',
    '2026-03-04 09:40:00',
    'GAP_MOVER',
    88,
    181.61,
    180.15,
    184.50,
    187.00,
    'NEUTRAL',
    22.4,
    'NEUTRAL',
    4.0,
    88,
    TRUE,
    'WIN',
    184.50,
    '2026-03-04 10:01:00',
    TRUE,
    FALSE,
    21,
    1.59,
    1.99
) ON CONFLICT DO NOTHING;

-- Feed ML training with NVDA data
INSERT INTO ml_training_data (signal_id, rvol, vix, score, time_of_day, confidence, regime, outcome, profit_r)
SELECT 
    id,
    4.0,
    22.4,
    88,
    '09:40',
    88,
    'NEUTRAL',
    TRUE,
    1.99
FROM signal_outcomes
WHERE ticker = 'NVDA' AND signal_time = '2026-03-04 09:40:00'
ON CONFLICT DO NOTHING;

SELECT 'Schema created successfully! NVDA winner loaded as training data.' as status;