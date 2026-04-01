-- Migration: Add DTE tracking columns to positions table
-- Adds columns to enable historical DTE learning:
--   dte_selected:  Which DTE was chosen (0 or 1)
--   adx_at_entry:  ADX value when signal fired
--   vix_at_entry:  VIX value when signal fired
--   target_pct_t1: Target 1 distance as percentage
--
-- Safe to run multiple times (ADD COLUMN IF NOT EXISTS)
-- Run: psql $DATABASE_URL -f migrations/add_dte_tracking_columns.sql

ALTER TABLE positions ADD COLUMN IF NOT EXISTS dte_selected   INTEGER;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS adx_at_entry   NUMERIC(8,4);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS vix_at_entry   NUMERIC(8,4);
ALTER TABLE positions ADD COLUMN IF NOT EXISTS target_pct_t1  NUMERIC(8,4);
