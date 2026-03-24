"""
Load Historical Data from EODHD API

Fetches 1-minute intraday bars AND daily technical indicators
(EMA20, ADX14, RSI14, ATR14, prior_close) for specified tickers
and stores them in PostgreSQL (intraday_bars + daily_technicals).

Usage:
    # Candles only (original behaviour)
    python scripts/database/load_historical_data.py

    # Candles + indicators (recommended before backtesting)
    python scripts/database/load_historical_data.py --indicators

    # Indicators only (fast daily refresh, no candle re-pull)
    python scripts/database/load_historical_data.py --indicators-only

    # Use all tickers from or_timing config
    python scripts/database/load_historical_data.py --indicators --all

    # Custom tickers
    python scripts/database/load_historical_data.py --indicators --tickers SPY,QQQ,META

Requires:
    - EODHD_API_KEY in environment or .env file
    - DATABASE_URL pointing to PostgreSQL
"""

import sys
import os
import argparse
import json
import time
import requests
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.data.data_manager import data_manager
from app.data.db_connection import get_conn, return_conn, ph

ET = ZoneInfo("America/New_York")

EODHD_API_KEY  = os.getenv("EODHD_API_KEY", "")
EODHD_BASE_URL = "https://eodhd.com/api/intraday"
TECH_URL       = "https://eodhd.com/api/technical/{ticker}.US"
EOD_URL        = "https://eodhd.com/api/eod/{ticker}.US"

# Default ticker list (original)
DEFAULT_TICKERS = [
    "AAPL", "NVDA", "TSLA", "SPY", "QQQ",
    "AMZN", "MSFT", "META", "GOOGL", "AMD",
]

# Market hours filter — only store bars within regular session
MARKET_OPEN_H,  MARKET_OPEN_M  = 9,  30
MARKET_CLOSE_H, MARKET_CLOSE_M = 16,  0


# ═══════════════════════════════════════════════════════════════
# CANDLE HELPERS (unchanged logic, now PostgreSQL-aware)
# ═══════════════════════════════════════════════════════════════

def fetch_intraday_bars(ticker: str, from_date: str, to_date: str) -> List[Dict]:
    url = f"{EODHD_BASE_URL}/{ticker}.US"
    params = {
        "api_token": EODHD_API_KEY,
        "interval":  "1m",
        "from":      from_date,
        "to":        to_date,
        "fmt":       "json",
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            print(f"  ⚠️  API Error for {ticker}: {data['error']}")
            return []
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  ❌ Request failed for {ticker}: {e}")
        return []


def convert_to_storage_format(ticker: str, bars: List[Dict]) -> List[Dict]:
    """Convert EODHD bars to War Machine format, keeping only market-hours bars."""
    converted = []
    for bar in bars:
        try:
            dt_str = bar.get("datetime", "")
            if not dt_str:
                continue
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)

            # Skip weekends
            if dt.weekday() >= 5:
                continue

            # Keep only regular session bars (9:30–16:00 ET)
            bar_mins = dt.hour * 60 + dt.minute
            open_mins  = MARKET_OPEN_H  * 60 + MARKET_OPEN_M
            close_mins = MARKET_CLOSE_H * 60 + MARKET_CLOSE_M
            if not (open_mins <= bar_mins < close_mins):
                continue

            converted.append({
                "ticker":    ticker,
                "timestamp": dt,
                "open":      float(bar["open"]),
                "high":      float(bar["high"]),
                "low":       float(bar["low"]),
                "close":     float(bar["close"]),
                "volume":    int(bar["volume"]) if bar.get("volume") else 0,
            })
        except Exception as e:
            print(f"  ⚠️  Skipping malformed bar for {ticker}: {e}")
    return converted


def cache_bars_to_database(ticker: str, bars: List[Dict]):
    if not bars:
        return
    for bar in bars:
        data_manager.cache_bar(ticker, bar)
    print(f"  ✅ Cached {len(bars)} bars for {ticker}")


# ═══════════════════════════════════════════════════════════════
# INDICATOR HELPERS
# ═══════════════════════════════════════════════════════════════

def _fetch_indicator_series(ticker: str, function: str, period: int,
                             from_date: str, to_date: str) -> Dict[str, float]:
    """Fetch daily indicator values from EODHD. Returns {date_str: value}."""
    try:
        r = requests.get(
            TECH_URL.format(ticker=ticker),
            params={"api_token": EODHD_API_KEY, "function": function,
                    "period": period, "from": from_date, "to": to_date, "fmt": "json"},
            timeout=15,
        )
        if r.status_code != 200 or not r.json():
            return {}
        result = {}
        for row in r.json():
            d = str(row.get("date", ""))[:10]
            if not d:
                continue
            val = row.get("adx") if function == "adx" else row.get("value")
            if val is not None:
                result[d] = float(val)
        return result
    except Exception as e:
        print(f"  ⚠️  {function} fetch error for {ticker}: {e}")
        return {}


def _fetch_eod_closes(ticker: str, from_date: str, to_date: str) -> Dict[str, float]:
    """Fetch EOD closes. Returns {date_str: close}."""
    try:
        r = requests.get(
            EOD_URL.format(ticker=ticker),
            params={"api_token": EODHD_API_KEY, "from": from_date,
                    "to": to_date, "fmt": "json"},
            timeout=15,
        )
        if r.status_code != 200 or not r.json():
            return {}
        return {str(row["date"])[:10]: float(row["close"]) for row in r.json()}
    except Exception as e:
        print(f"  ⚠️  EOD close fetch error for {ticker}: {e}")
        return {}


def _ensure_daily_technicals_table():
    """Create daily_technicals table if it doesn't exist."""
    sql_path = Path(__file__).parent / "create_daily_technicals.sql"
    if not sql_path.exists():
        print("  ⚠️  create_daily_technicals.sql not found — skipping table creation")
        return
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(sql_path.read_text())
    conn.commit()
    return_conn(conn)


def fetch_and_store_indicators(ticker: str, from_date: str, to_date: str) -> int:
    """
    Fetch EMA20, ADX14, RSI14, ATR14 + prior_close for all WEEKDAY dates
    in the range and upsert into daily_technicals.

    prior_close for date D = EOD close of the previous trading day.
    Only weekday dates with at least one non-null indicator are stored.
    """
    print(f"  {ticker}: fetching indicators {from_date} → {to_date}")

    ema   = _fetch_indicator_series(ticker, "ema", 20, from_date, to_date)
    adx   = _fetch_indicator_series(ticker, "adx", 14, from_date, to_date)
    rsi   = _fetch_indicator_series(ticker, "rsi", 14, from_date, to_date)
    atr   = _fetch_indicator_series(ticker, "atr", 14, from_date, to_date)
    close = _fetch_eod_closes(ticker, from_date, to_date)

    # Build prior_close map from sorted trading days
    sorted_days = sorted(close.keys())
    prior_close_map: Dict[str, float] = {}
    for i, d in enumerate(sorted_days):
        if i > 0:
            prior_close_map[d] = close[sorted_days[i - 1]]

    # All dates that have at least one indicator — weekdays only
    all_dates = set(ema) | set(adx) | set(rsi) | set(atr)
    rows = []
    for d in sorted(all_dates):
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        if dt.weekday() >= 5:          # skip weekends
            continue
        rows.append({
            "ticker":      ticker,
            "date":        d,
            "ema20":       ema.get(d),
            "adx14":       adx.get(d),
            "rsi14":       rsi.get(d),
            "atr14":       atr.get(d),
            "prior_close": prior_close_map.get(d),
        })

    if not rows:
        print(f"  ⚠️  No indicator rows for {ticker}")
        return 0

    p   = ph()
    sql = (
        f"INSERT INTO daily_technicals "
        f"(ticker, date, ema20, adx14, rsi14, atr14, prior_close) "
        f"VALUES ({p},{p},{p},{p},{p},{p},{p}) "
        f"ON CONFLICT (ticker, date) DO UPDATE SET "
        f"ema20={p}, adx14={p}, rsi14={p}, atr14={p}, prior_close={p}, fetched_at=NOW()"
    )
    conn = get_conn()
    cur  = conn.cursor()
    for row in rows:
        vals = (
            row["ticker"], row["date"],
            row["ema20"], row["adx14"], row["rsi14"], row["atr14"], row["prior_close"],
            row["ema20"], row["adx14"], row["rsi14"], row["atr14"], row["prior_close"],
        )
        cur.execute(sql, vals)
    conn.commit()
    return_conn(conn)

    print(f"  ✅ {len(rows)} indicator rows upserted for {ticker}")
    return len(rows)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Load historical candles + indicators")
    parser.add_argument("--tickers", default="",
                        help="Comma-separated tickers (default: built-in list)")
    parser.add_argument("--all", action="store_true",
                        help="Load all tickers from ticker_or_config.json")
    parser.add_argument("--days", type=int, default=120,
                        help="Lookback days (default: 120)")
    parser.add_argument("--indicators", action="store_true",
                        help="Also fetch and store daily indicators")
    parser.add_argument("--indicators-only", action="store_true",
                        help="Skip candle fetch, only update indicators")
    args = parser.parse_args()

    if not EODHD_API_KEY:
        print("❌ EODHD_API_KEY not set")
        sys.exit(1)

    # Resolve ticker list
    if args.all:
        cfg_path = (
            Path(__file__).resolve().parents[2]
            / "scripts" / "analysis" / "output" / "or_timing" / "ticker_or_config.json"
        )
        tickers = list(json.loads(cfg_path.read_text()).keys())
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = DEFAULT_TICKERS

    end_dt   = datetime.now(ET)
    start_dt = end_dt - timedelta(days=args.days)
    from_str = start_dt.strftime("%Y-%m-%d")
    to_str   = end_dt.strftime("%Y-%m-%d")

    fetch_candles    = not args.indicators_only
    fetch_indicators = args.indicators or args.indicators_only

    print("=" * 70)
    print("LOAD HISTORICAL DATA — War Machine")
    print("=" * 70)
    print(f"Tickers  : {len(tickers)}")
    print(f"Range    : {from_str} → {to_str} ({args.days} days)")
    print(f"Candles  : {'YES' if fetch_candles else 'NO'}")
    print(f"Indicators: {'YES' if fetch_indicators else 'NO'}")
    print()

    # Ensure table exists before writing
    if fetch_indicators:
        _ensure_daily_technicals_table()

    total_bars = 0
    total_rows = 0

    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker}")

        if fetch_candles:
            bars = fetch_intraday_bars(ticker, from_str, to_str)
            if bars:
                converted = convert_to_storage_format(ticker, bars)
                cache_bars_to_database(ticker, converted)
                total_bars += len(converted)
            else:
                print(f"  ⚠️  No candle data for {ticker}")

        if fetch_indicators:
            total_rows += fetch_and_store_indicators(ticker, from_str, to_str)
            time.sleep(0.4)   # 4 indicator calls already done; small pause
        elif i < len(tickers):
            time.sleep(3)     # original rate-limit for candles-only

        print()

    print("=" * 70)
    print("DONE")
    print(f"  Candle bars   : {total_bars:,}")
    print(f"  Indicator rows: {total_rows:,}")
    print("=" * 70)


if __name__ == "__main__":
    main()
