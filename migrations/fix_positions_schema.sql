-- Migration: Add missing P&L tracking columns to positions table
-- Run this manually in your PostgreSQL console or via Railway CLI

-- Add realized_pnl column (tracks actual profit/loss when closed)
ALTER TABLE positions 
ADD COLUMN IF NOT EXISTS realized_pnl REAL DEFAULT 0;

-- Add unrealized_pnl column (tracks floating profit/loss for open positions)
ALTER TABLE positions 
ADD COLUMN IF NOT EXISTS unrealized_pnl REAL DEFAULT 0;

-- Add current_price column (tracks real-time price for unrealized P&L calculation)
ALTER TABLE positions 
ADD COLUMN IF NOT EXISTS current_price REAL;

-- Verify columns exist
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'positions' 
  AND column_name IN ('realized_pnl', 'unrealized_pnl', 'current_price');

-- Expected output:
--   column_name     | data_type | column_default
-- ------------------+-----------+----------------
--   realized_pnl    | real      | 0
--   unrealized_pnl  | real      | 0
--   current_price   | real      | NULL
