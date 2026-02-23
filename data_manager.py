# Add this method to DataManager class after materialize_5m_bars method

    def store_daily_bars(self, ticker: str, bars: List[Dict]) -> int:
        """
        Store daily EOD bars (separate from intraday bars).
        Used by bulk_downloader for historical data backfills.
        
        Creates a daily_bars table if it doesn't exist.
        Daily bars are OHLCV with date (not datetime) keys.
        
        Args:
            ticker: Stock symbol
            bars: List of bar dicts with 'datetime', 'open', 'high', 'low', 'close', 'volume'
        
        Returns:
            Number of bars stored
        """
        if not bars:
            return 0
        
        # Ensure daily_bars table exists
        conn = get_conn(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS daily_bars (
                id          {serial_pk()},
                ticker      TEXT      NOT NULL,
                date        DATE      NOT NULL,
                open        REAL      NOT NULL,
                high        REAL      NOT NULL,
                low         REAL      NOT NULL,
                close       REAL      NOT NULL,
                volume      INTEGER   NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, date)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_ticker_date
            ON daily_bars(ticker, date DESC)
        """)
        conn.commit()
        
        # Prepare upsert SQL
        if db_connection.USE_POSTGRES:
            upsert_sql = """
                INSERT INTO daily_bars (ticker, date, open, high, low, close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, date)
                DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume
            """
        else:
            upsert_sql = """
                INSERT INTO daily_bars (ticker, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ticker, date)
                DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume
            """
        
        # Convert bars to daily format (extract date from datetime)
        data = []
        for b in bars:
            dt = b["datetime"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            bar_date = dt.date() if isinstance(dt, datetime) else dt
            
            data.append((
                ticker,
                bar_date,
                b["open"],
                b["high"],
                b["low"],
                b["close"],
                b["volume"]
            ))
        
        try:
            cursor = conn.cursor()
            cursor.executemany(upsert_sql, data)
            conn.commit()
            return len(data)
        except Exception as e:
            print(f"[DATA] Error storing daily bars for {ticker}: {e}")
            conn.rollback()
            return 0
        finally:
            conn.close()


# I'll now provide the full updated file:
