-- Migration 006: Futures Signals Table
-- Dedicated table for NQ/MNQ ORB signals so futures P&L tracking is
-- completely separate from the equity armed_signals_persist table.
-- Options/equity queries are unaffected — they never read this table.
-- Safe to run multiple times (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS futures_signals (
    id               SERIAL PRIMARY KEY,
    symbol           VARCHAR(10)   NOT NULL,          -- e.g. MNQ, NQ
    direction        VARCHAR(10)   NOT NULL,          -- BULL / BEAR
    entry_price      NUMERIC(12,4),
    stop_price       NUMERIC(12,4),
    t1               NUMERIC(12,4),
    t2               NUMERIC(12,4),
    confidence       NUMERIC(6,4),                   -- 0.0–1.0
    grade            VARCHAR(5),                     -- A / B / C
    signal_type      VARCHAR(32)   DEFAULT 'FUTURES_ORB',
    entry_type       VARCHAR(32),                    -- FVG / MOMENTUM_CONTINUATION
    validation_data  JSONB,                          -- or_high, or_low, atr, dollar_risk, etc.
    outcome          VARCHAR(16),                    -- WIN / LOSS / SCRATCH / NULL (open)
    exit_price       NUMERIC(12,4),
    pnl_pts          NUMERIC(10,4),                  -- points P&L
    pnl_usd          NUMERIC(12,2),                  -- dollar P&L (pts × point_value × contracts)
    saved_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    closed_at        TIMESTAMPTZ                     -- NULL until signal resolves
);

CREATE INDEX IF NOT EXISTS idx_futures_signals_symbol
    ON futures_signals (symbol);

CREATE INDEX IF NOT EXISTS idx_futures_signals_saved_at
    ON futures_signals (saved_at);

CREATE INDEX IF NOT EXISTS idx_futures_signals_outcome
    ON futures_signals (outcome)
    WHERE outcome IS NOT NULL;

COMMENT ON TABLE futures_signals IS
    'NQ/MNQ ORB signals — isolated from equity armed_signals_persist. '
    'Tracks futures-specific P&L (pnl_pts, pnl_usd). '
    'Options system never reads this table.';
