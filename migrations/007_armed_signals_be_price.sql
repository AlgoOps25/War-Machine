-- Migration 007: Add be_price to armed_signals_persist
-- Fixes BUG-ARM-3: be_price was stored in-memory only; after a restart
-- the break-even trigger was silently dropped from reloaded signals.
-- Safe to run multiple times (ADD COLUMN IF NOT EXISTS).

ALTER TABLE armed_signals_persist
    ADD COLUMN IF NOT EXISTS be_price NUMERIC(12,4);
