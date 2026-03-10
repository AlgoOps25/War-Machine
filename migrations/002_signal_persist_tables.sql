-- Migration 002: Signal Persistence Tables
-- Fixes: no such table: armed_signals_persist / watching_signals_persist
-- Safe to run multiple times (IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS armed_signals_persist (
    id               SERIAL PRIMARY KEY,
    ticker           VARCHAR(20)   NOT NULL,
    position_id      VARCHAR(64),
    direction        VARCHAR(10)   NOT NULL,
    entry_price      NUMERIC(12,4),
    stop_price       NUMERIC(12,4),
    t1               NUMERIC(12,4),
    t2               NUMERIC(12,4),
    confidence       NUMERIC(6,2),
    grade            VARCHAR(5),
    signal_type      VARCHAR(32),
    validation_data  JSONB,
    saved_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_armed_saved_at
    ON armed_signals_persist (saved_at);

CREATE TABLE IF NOT EXISTS watching_signals_persist (
    id               SERIAL PRIMARY KEY,
    ticker           VARCHAR(20)   NOT NULL,
    direction        VARCHAR(10)   NOT NULL,
    breakout_bar_dt  TIMESTAMPTZ,
    or_high          NUMERIC(12,4),
    or_low           NUMERIC(12,4),
    signal_type      VARCHAR(32),
    saved_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watching_saved_at
    ON watching_signals_persist (saved_at);

CREATE INDEX IF NOT EXISTS idx_watching_ticker
    ON watching_signals_persist (ticker);
