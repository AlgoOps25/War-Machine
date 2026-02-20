"""
Earnings Calendar Filter
Fetches upcoming earnings dates from EODHD and flags tickers
that have earnings within a configurable window (default: 2 days).

Why this matters:
  - Earnings events inflate IV significantly (IV crush risk on options buys)
  - Price action pre-earnings is often irrational / gap-and-trap prone
  - BOS+FVG signals near earnings have lower follow-through probability

Flow:
  1. bulk_prefetch_earnings() called once at scanner startup — warms cache for all tickers
  2. has_earnings_soon() called per-ticker in process_ticker() Step 3c — instant cache hit
  3. clear_earnings_cache() called at EOD — ensures fresh data next session

Cache TTL: 4 hours (refresh mid-session in case of pre-announcement date changes)
"""
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import config

# ── Cache ─────────────────────────────────────────────────────────────────────
# {ticker: {"has_earnings": bool, "report_date": str|None, "fetched_at": datetime}}
_earnings_cache: dict = {}

CACHE_TTL_HOURS      = 4   # re-fetch if cache entry is older than this
EARNINGS_WINDOW_DAYS = 2   # flag ticker if earnings within this many calendar days


def _now_et() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def _cache_valid(entry: dict) -> bool:
    """Return True if a cache entry is still within TTL."""
    fetched_at = entry.get("fetched_at")
    if fetched_at is None:
        return False
    age_hours = (_now_et() - fetched_at).total_seconds() / 3600
    return age_hours < CACHE_TTL_HOURS


def fetch_earnings_calendar(tickers: list, days_ahead: int = 7) -> dict:
    """
    Fetch earnings dates for a list of tickers from EODHD calendar API.

    Endpoint: GET /api/calendar/earnings
    Params:   from, to (YYYY-MM-DD), symbols (comma-separated, .US suffix)

    Returns:
      dict mapping ticker -> report_date string ("YYYY-MM-DD") or None
    """
    today     = _now_et().date()
    from_date = today.strftime("%Y-%m-%d")
    to_date   = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # EODHD requires exchange suffix on symbols
    symbols_str = ",".join(f"{t}.US" for t in tickers)

    url    = "https://eodhd.com/api/calendar/earnings"
    params = {
        "api_token": config.EODHD_API_KEY,
        "from":      from_date,
        "to":        to_date,
        "symbols":   symbols_str,
        "fmt":       "json"
    }

    result = {t: None for t in tickers}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        earnings_list = data.get("earnings", [])
        for item in earnings_list:
            # Strip .US suffix to match internal ticker format
            code        = item.get("code", "").replace(".US", "")
            report_date = item.get("report_date") or item.get("date")
            if code in result and report_date:
                result[code] = report_date

        print(f"[EARNINGS] Calendar fetched: {len(earnings_list)} events "
              f"({from_date} → {to_date}) for {len(tickers)} tickers")

    except Exception as e:
        # Fail open: if EODHD earnings calendar is unavailable, don't block signals.
        # Worst case is we take a trade near earnings; still safer than blocking all signals.
        print(f"[EARNINGS] API error: {e} — proceeding without earnings filter (fail-open)")

    return result


def has_earnings_soon(ticker: str,
                      window_days: int = EARNINGS_WINDOW_DAYS) -> tuple:
    """
    Check if a ticker has earnings within the next `window_days` calendar days.

    Returns:
      (has_earnings: bool, report_date: str | None)

    Cache behavior:
      - First call per ticker fetches from EODHD and caches for CACHE_TTL_HOURS.
      - Subsequent calls within TTL return instantly from cache.
      - bulk_prefetch_earnings() pre-warms the cache at startup so this
        function never triggers a cold API call during the scan loop.
    """
    # ── Cache hit ─────────────────────────────────────────────────────────────
    if ticker in _earnings_cache:
        entry = _earnings_cache[ticker]
        if _cache_valid(entry):
            return entry["has_earnings"], entry.get("report_date")

    # ── Cache miss or stale — single-ticker fetch ────────────────────────────────
    calendar    = fetch_earnings_calendar([ticker], days_ahead=window_days + 1)
    report_date = calendar.get(ticker)
    has_earnings = False

    if report_date:
        today = _now_et().date()
        try:
            rdate      = datetime.strptime(report_date, "%Y-%m-%d").date()
            days_until = (rdate - today).days
            has_earnings = (0 <= days_until <= window_days)
        except Exception:
            has_earnings = False

    _earnings_cache[ticker] = {
        "has_earnings": has_earnings,
        "report_date":  report_date,
        "fetched_at":   _now_et()
    }

    return has_earnings, report_date


def bulk_prefetch_earnings(tickers: list) -> None:
    """
    Pre-fetch and cache earnings dates for all watchlist tickers at startup.

    Call once from scanner.py after the data backfill, before the scan loop.
    Eliminates cold API calls during live scanning so has_earnings_soon()
    always returns from cache during market hours.

    Prints a summary of flagged tickers so you know before the day starts
    which symbols the scanner will skip and why.
    """
    print(f"[EARNINGS] Bulk prefetch: {len(tickers)} tickers...")
    calendar   = fetch_earnings_calendar(tickers, days_ahead=EARNINGS_WINDOW_DAYS + 1)
    today      = _now_et().date()
    flagged    = []

    for ticker, report_date in calendar.items():
        has_earnings = False
        days_until   = None

        if report_date:
            try:
                rdate      = datetime.strptime(report_date, "%Y-%m-%d").date()
                days_until = (rdate - today).days
                has_earnings = (0 <= days_until <= EARNINGS_WINDOW_DAYS)
            except Exception:
                pass

        _earnings_cache[ticker] = {
            "has_earnings": has_earnings,
            "report_date":  report_date,
            "fetched_at":   _now_et()
        }

        if has_earnings:
            flagged.append((ticker, report_date, days_until))

    if flagged:
        print(f"[EARNINGS] ⚠️  {len(flagged)} ticker(s) flagged — will skip during scan:")
        for ticker, rdate, days in flagged:
            when = "TODAY" if days == 0 else f"in {days}d"
            print(f"  ❌  {ticker:<6} earnings {when} ({rdate})")
    else:
        print(f"[EARNINGS] ✅ No earnings events in next {EARNINGS_WINDOW_DAYS}d — all tickers clear")


def clear_earnings_cache() -> None:
    """Clear the in-memory earnings cache at EOD for fresh data next session."""
    _earnings_cache.clear()
    print("[EARNINGS] Cache cleared for new trading day")
