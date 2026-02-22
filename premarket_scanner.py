"""
Pre-Market Scanner (4 AM - 9:30 AM EST)
Builds intelligent watchlist before market opens and assesses daily
market risk based on the EODHD economic events calendar.

New exports:
  get_session_risk()  — call from main.py at session start to get
                        risk_level (HIGH/MEDIUM/LOW) and adjust
                        MAX_CONTRACTS / confidence thresholds.
  get_economic_events() — raw EODHD economic calendar fetch for today.
"""
import requests
from datetime import datetime
from typing import List, Dict
import config
# FIX #6: removed 'import yfinance as yf' — yf.Ticker().calendar silently fails
#         and the bare except: pass always returned False, disabling earnings filtering.
#         earnings_filter.has_earnings_soon() is the correct system-wide guard.

# ------------------------------------------------------------------ #
#  Watchlist universe                                                  #
# ------------------------------------------------------------------ #

SCAN_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
    "NFLX", "ADBE", "CRM",  "INTC", "CSCO", "JPM",  "BAC",  "GS",
    "MS",   "WFC",  "UNH",  "JNJ",  "PFE",  "ABBV", "MRK",  "WMT",
    "HD",   "COST", "NKE",  "MCD",  "SPY",  "QQQ",  "IWM",  "DIA"
]

# ------------------------------------------------------------------ #
#  Economic calendar                                                   #
# ------------------------------------------------------------------ #

# Keywords that flag a HIGH-IMPACT event regardless of the API impact field.
# Matched case-insensitively against the event name/type string.
HIGH_IMPACT_KEYWORDS = [
    "FOMC", "Federal Reserve", "Fed Rate", "Interest Rate Decision",
    "CPI",  "Consumer Price Index", "Inflation",
    "NFP",  "Non-Farm Payroll", "Nonfarm Payroll", "Nonfarm",
    "GDP",  "Gross Domestic Product",
    "PCE",  "Personal Consumption Expenditure",
    "PPI",  "Producer Price Index",
    "Unemployment Rate", "Initial Jobless Claims",
    "ISM Manufacturing", "ISM Services", "ISM Non-Manufacturing",
    "Retail Sales",
    "JOLTS", "Job Openings",
    "Jackson Hole",
]


def get_economic_events(date_str: str = None) -> List[Dict]:
    """
    Fetch US economic events from EODHD for a given date.

    Endpoint: GET /api/economic-events
    Params:   from, to, country=US, api_token

    Returns a flat list of event dicts. Handles both array and
    wrapped ({"response": [...]}) response shapes defensively.
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    url    = "https://eodhd.com/api/economic-events"
    params = {
        "api_token": config.EODHD_API_KEY,
        "from":      date_str,
        "to":        date_str,
        "country":   "US",
        "fmt":       "json",
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        raw = response.json()
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            # Try common wrapper keys
            for key in ("response", "data", "events", "result"):
                if key in raw and isinstance(raw[key], list):
                    return raw[key]
        return []
    except Exception as e:
        print(f"[ECON] Error fetching economic events: {e}")
        return []


def _event_name(event: Dict) -> str:
    """Extract event name from any of the known field aliases."""
    return str(
        event.get("type") or
        event.get("event") or
        event.get("name") or
        event.get("indicator") or
        "Unknown Event"
    )


def _event_time(event: Dict) -> str:
    """Extract a clean HH:MM time string from the event date field."""
    raw = str(event.get("date", ""))
    if " " in raw:
        return raw.split(" ")[1][:5]   # "2026-02-23 14:00:00" -> "14:00"
    if "T" in raw:
        return raw.split("T")[1][:5]   # ISO format
    return "--:--"


def _is_high_impact(event: Dict) -> bool:
    """
    Classify an event as high-impact via:
      1. Explicit impact/importance field ("High", "high", "3", "HIGH")
      2. Keyword match on event name against HIGH_IMPACT_KEYWORDS
    """
    impact = str(
        event.get("impact") or
        event.get("importance") or
        event.get("priority") or
        ""
    ).lower()
    if impact in ("high", "3", "h"):
        return True
    name_lower = _event_name(event).lower()
    return any(kw.lower() in name_lower for kw in HIGH_IMPACT_KEYWORDS)


def get_session_risk() -> Dict:
    """
    Assess today's market risk level from the EODHD economic calendar.

    Returns:
        {
          "risk_level":     "HIGH" | "MEDIUM" | "LOW",
          "high_events":    [list of high-impact event dicts],
          "all_events":     [all US events today],
          "recommendation": str,
          "event_count":    int,
          "high_count":     int,
        }

    Usage in main.py:
        risk = get_session_risk()
        if risk["risk_level"] == "HIGH":
            effective_max_contracts = config.MAX_CONTRACTS // 2
            effective_conf_floor    = 0.80
        else:
            effective_max_contracts = config.MAX_CONTRACTS
            effective_conf_floor    = config.MIN_CONFIDENCE_OR
    """
    today      = datetime.now().strftime("%Y-%m-%d")
    all_events = get_economic_events(today)

    high_events = [e for e in all_events if _is_high_impact(e)]
    med_events  = [e for e in all_events if not _is_high_impact(e)]

    if high_events:
        risk_level     = "HIGH"
        recommendation = (
            "HIGH-IMPACT DAY: Avoid entries 30 min before/after announcements. "
            "Reduce MAX_CONTRACTS by 50%. Raise confidence floor to 0.80."
        )
    elif med_events:
        risk_level     = "MEDIUM"
        recommendation = "Medium-impact events scheduled. Normal sizing, heightened awareness."
    else:
        risk_level     = "LOW"
        recommendation = "No major scheduled events. Normal operation."

    return {
        "risk_level":     risk_level,
        "high_events":    high_events,
        "all_events":     all_events,
        "recommendation": recommendation,
        "event_count":    len(all_events),
        "high_count":     len(high_events),
    }


def _print_risk_banner(risk: Dict) -> None:
    """Print formatted economic risk summary to console."""
    lvl = risk["risk_level"]
    icon = {"HIGH": "\U0001f6a8", "MEDIUM": "\u26a0\ufe0f", "LOW": "\u2705"}.get(lvl, "\u2139\ufe0f")

    print(f"[ECON] {icon}  Market Risk: {lvl}  |  "
          f"{risk['event_count']} events today  |  "
          f"{risk['high_count']} high-impact")

    if risk["high_events"]:
        for e in risk["high_events"]:
            name    = _event_name(e)
            t       = _event_time(e)
            est     = e.get("estimate", e.get("forecast", "--"))
            prev    = e.get("previous", "--")
            print(f"  \U0001f534 {t} ET | {name}  est={est}  prev={prev}")
    elif risk["all_events"]:
        for e in risk["all_events"][:3]:
            print(f"  \U0001f7e1 {_event_time(e)} ET | {_event_name(e)}")

    print(f"  \u21b3 {risk['recommendation']}")


# ------------------------------------------------------------------ #
#  Earnings filter                                                     #
# ------------------------------------------------------------------ #

def has_earnings_today(ticker: str) -> bool:
    """
    FIX #6: Returns True if ticker has earnings within the guard window.
    Delegates to earnings_filter.has_earnings_soon() which uses the EODHD
    earnings calendar — the same guard already active in sniper.process_ticker().
    Previously used yfinance .calendar which silently errors on most tickers
    and a bare except: pass that caused the function to always return False,
    effectively disabling the pre-market earnings filter entirely.
    """
    try:
        from earnings_filter import has_earnings_soon
        has_earns, earns_date = has_earnings_soon(ticker)
        return has_earns
    except Exception as e:
        print(f"[PREMARKET] Earnings check error for {ticker}: {e}")
        return False


# ------------------------------------------------------------------ #
#  Gap scanner                                                         #
# ------------------------------------------------------------------ #

def get_gap_movers(min_gap_pct: float = 2.0) -> List[Dict]:
    """
    Find stocks gapping significantly in pre-market.
    Uses EODHD bulk real-time quotes via s= parameter.
    """
    primary = f"{SCAN_UNIVERSE[0]}.US"
    extra   = ",".join(f"{t}.US" for t in SCAN_UNIVERSE[1:])

    url = f"https://eodhd.com/api/real-time/{primary}"
    params = {
        "api_token": config.EODHD_API_KEY,
        "s":   extra,
        "fmt": "json"
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            return []

        gap_stocks = []
        for item in items:
            if not isinstance(item, dict):
                continue

            code          = item.get("code", "")
            ticker        = code.replace(".US", "") if code else ""
            if not ticker:
                continue

            prev_close    = float(item.get("previousClose", 0) or 0)
            current_price = float(item.get("close", 0) or item.get("open", 0) or 0)
            volume        = int(item.get("volume", 0) or 0)

            if prev_close > 0 and current_price > 0:
                gap_pct = ((current_price - prev_close) / prev_close) * 100

                if abs(gap_pct) >= min_gap_pct:
                    gap_stocks.append({
                        "ticker":     ticker,
                        "gap_pct":    round(gap_pct, 2),
                        "price":      current_price,
                        "prev_close": prev_close,
                        "volume":     volume
                    })

        gap_stocks.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
        return gap_stocks[:30]
    except Exception as e:
        print(f"[PREMARKET] Gap scanner error: {e}")
        return []


# ------------------------------------------------------------------ #
#  Master watchlist builder                                            #
# ------------------------------------------------------------------ #

def build_premarket_watchlist() -> List[str]:
    """Build master pre-market watchlist with scoring and earnings filter."""
    print("\n" + "=" * 60)
    print(f"PRE-MARKET WATCHLIST - {datetime.now().strftime('%I:%M:%S %p')}")
    print("=" * 60)

    # 0 — Economic calendar risk assessment (NEW)
    print("[ECON] Checking economic calendar...")
    risk = get_session_risk()
    _print_risk_banner(risk)
    print()

    watchlist = set()

    # 1 — Gap movers
    print("[PREMARKET] Scanning gap movers...")
    gaps = get_gap_movers()
    for stock in gaps[:15]:
        watchlist.add(stock["ticker"])
        direction = "\U0001f4c8" if stock["gap_pct"] > 0 else "\U0001f4c9"
        print(f"  {direction} {stock['ticker']}: {stock['gap_pct']:+.2f}%")

    # 2 — Core liquid tickers always included
    core = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "MSFT"]
    for ticker in core:
        watchlist.add(ticker)

    # 3 — Filter earnings (now actually works)
    tickers = sorted(list(watchlist))
    clean   = []
    for t in tickers:
        if has_earnings_today(t):
            print(f"[EARNINGS] \u26a0\ufe0f  Removing {t} \u2014 earnings within guard window")
        else:
            clean.append(t)

    final_list = clean

    print(f"\n\u2705 Watchlist: {len(final_list)} tickers")
    print(f"{', '.join(final_list)}")
    print("=" * 60 + "\n")

    return final_list
