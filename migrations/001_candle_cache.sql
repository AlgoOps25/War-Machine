-- Phase 1: Candle Cache Table
CREATE TABLE IF NOT EXISTS candle_cache (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    datetime TIMESTAMP NOT NULL,
    open NUMERIC(12,4) NOT NULL,
    high NUMERIC(12,4) NOT NULL,
    low NUMERIC(12,4) NOT NULL,
    close NUMERIC(12,4) NOT NULL,
    volume BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, timeframe, datetime)
);

CREATE INDEX idx_candle_lookup ON candle_cache(ticker, timeframe, datetime DESC);
CREATE INDEX idx_candle_timeframe ON candle_cache(timeframe, datetime DESC);
CREATE INDEX idx_candle_created ON candle_cache(created_at DESC);

-- Cache metadata tracking
CREATE TABLE IF NOT EXISTS cache_metadata (
    ticker VARCHAR(10) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    first_bar_time TIMESTAMP,
    last_bar_time TIMESTAMP,
    bar_count INTEGER DEFAULT 0,
    last_cache_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cache_status VARCHAR(20) DEFAULT 'active',
    PRIMARY KEY(ticker, timeframe)
);

CREATE INDEX idx_cache_status ON cache_metadata(cache_status, last_cache_time);
