"""
Earnings Calendar Filter — DISABLED

The EODHD /api/calendar/earnings endpoint requires the Fundamentals Data Feed
add-on which is not included in the current plan (returns 403 Forbidden).

All public functions are retained as silent no-ops so callers (scanner.py,
sniper.py) require zero changes. Re-enable by restoring the API implementation
if/when the EODHD plan is upgraded to include calendar data.

Original behaviour:
  - bulk_prefetch_earnings() fetched upcoming earnings dates at startup
  - has_earnings_soon() flagged tickers with earnings within 2 calendar days
  - clear_earnings_cache() reset the cache at EOD
"""

# No-op cache — always returns "no earnings" so no signals are blocked
_earnings_cache: dict = {}


def fetch_earnings_calendar(tickers: list, days_ahead: int = 7) -> dict:
    """Disabled — returns empty calendar (no earnings for any ticker)."""
    return {t: None for t in tickers}


def has_earnings_soon(ticker: str, window_days: int = 2) -> tuple:
    """
    Disabled — always returns (False, None).
    Callers treat this as "no earnings soon" and proceed normally.
    """
    return False, None


def bulk_prefetch_earnings(tickers: list) -> None:
    """Disabled — silent no-op. No API calls made."""
    pass


def clear_earnings_cache() -> None:
    """Disabled — silent no-op."""
    _earnings_cache.clear()
