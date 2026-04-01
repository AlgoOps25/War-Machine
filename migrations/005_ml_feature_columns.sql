-- Migration 005: Add 5 new ML feature columns to signals table
-- 47.P3-2 (2026-04-01)
--
-- These columns feed the expanded LIVE_FEATURE_COLS vector in ml_trainer.py.
-- All are NULLABLE so existing rows degrade gracefully (ml_trainer fills
-- missing values with the column median at training time).
--
-- Safe to re-run: all statements use ADD COLUMN IF NOT EXISTS.

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS gex_distance  NUMERIC(10, 6),  -- abs(price - GEX pin) / price
    ADD COLUMN IF NOT EXISTS spy_5m_bias   NUMERIC(6, 4),   -- SPY 5-min EMA bias at signal time (-1/0/+1 or continuous)
    ADD COLUMN IF NOT EXISTS rvol_ratio    NUMERIC(8, 4);   -- rvol / 20-day avg rvol (cross-ticker normalisation)

-- ivr is already stored as iv_rank (aliased in SELECT, no new column needed).
-- time_to_close is computed in the SELECT query (no storage column needed).

COMMENT ON COLUMN signals.gex_distance IS
    'Absolute distance from current price to nearest GEX gamma wall, normalised by price. '
    'Lower = more pinned. Populated by scanner at signal creation time. Nullable.';

COMMENT ON COLUMN signals.spy_5m_bias IS
    'SPY 5-minute EMA directional bias recorded at signal time. '
    'Continuous value (positive = bullish, negative = bearish) or discretised −1/0/+1. Nullable.';

COMMENT ON COLUMN signals.rvol_ratio IS
    'Relative volume ratio: rvol / 20-day average rvol for the ticker. '
    'Normalises raw RVOL across tickers with different baseline volumes. Nullable.';
