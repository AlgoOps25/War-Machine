-- daily_technicals: per-ticker, per-trading-day indicator snapshot
-- Used by walk_forward_backtest.py fetch_session_context() to avoid
-- per-session EODHD API calls during backtesting.
--
-- Populated by: scripts/database/load_historical_data.py --indicators
-- Updated daily by pre-market routine.

CREATE TABLE IF NOT EXISTS daily_technicals (
    ticker      VARCHAR(20)  NOT NULL,
    date        DATE         NOT NULL,
    ema20       NUMERIC(12,4),
    adx14       NUMERIC(8,4),
    rsi14       NUMERIC(8,4),
    atr14       NUMERIC(10,4),
    prior_close NUMERIC(12,4),
    fetched_at  TIMESTAMPTZ  DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_tech_ticker_date
    ON daily_technicals (ticker, date DESC);
