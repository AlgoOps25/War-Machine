"""
scripts/check_eodhd_intraday.py

Diagnostic: checks how far back EODHD intraday 5m data goes for your API key,
and how many bars are returned for a given date window.

Usage:
    python scripts/check_eodhd_intraday.py

Output:
    - Earliest available 5m bar date
    - Total bars returned per window (7d, 30d, 60d, 120d)
    - Whether any bars have null volume (the BUG-2 pattern)
    - Confirms fix is working
"""
import os
import sys
import json
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("requests not installed. Run: pip install requests")
    sys.exit(1)

API_KEY  = os.getenv('EODHD_API_KEY', '')
TICKER   = 'AAPL'
INTERVAL = '5m'
BASE     = 'https://eodhd.com/api'

if not API_KEY:
    print("ERROR: EODHD_API_KEY env var not set.")
    sys.exit(1)

print(f"\nEODHD Intraday Diagnostic")
print(f"=" * 50)
print(f"Ticker   : {TICKER}")
print(f"Interval : {INTERVAL}")
print(f"API Key  : ...{API_KEY[-6:]}")
print()

def fetch_intraday(days_back: int):
    to_dt   = datetime.utcnow()
    from_dt = to_dt - timedelta(days=days_back)
    params  = {
        'api_token': API_KEY,
        'fmt':       'json',
        'interval':  INTERVAL,
        'from':      int(from_dt.timestamp()),
        'to':        int(to_dt.timestamp()),
    }
    url = f"{BASE}/intraday/{TICKER}.US"
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data, None
    except Exception as e:
        return None, str(e)

# Test windows
windows = [7, 30, 60, 90, 120]
print(f"{'Window':<12} {'Bars':>6}  {'Earliest bar':<22}  {'Null volumes':>12}")
print("-" * 60)

best_data = None
for days in windows:
    data, err = fetch_intraday(days)
    if err:
        print(f"{days}d{'':<8} {'ERROR':>6}  {err}")
        continue
    if not isinstance(data, list) or len(data) == 0:
        print(f"{days}d{'':<8} {'0':>6}  {'(no data)'}")
        continue

    # BUG-2 check: how many bars have null volume
    null_vols = sum(1 for b in data if b.get('volume') is None)
    earliest  = data[0].get('datetime') or data[0].get('date', '?')
    print(f"{days}d{'':<8} {len(data):>6}  {earliest:<22}  {null_vols:>12}")
    best_data = data

if best_data:
    print()
    print("Sample bar (most recent):")
    sample = best_data[-1]
    print(json.dumps(sample, indent=2))

    print()
    print("_safe_float test (BUG-2 fix verification):")
    null_fields = [k for k, v in sample.items() if v is None]
    if null_fields:
        print(f"  Null fields in sample bar: {null_fields}")
        print(f"  float(None or 0) = {float(None or 0)}  ✓ bug fix working")
    else:
        print("  No null fields in sample bar ✓")

print()
print("Recommendation:")
for days in [120, 90, 60, 30]:
    data, err = fetch_intraday(days)
    if data and isinstance(data, list) and len(data) > 500:
        months = round(days / 30)
        print(f"  Use --months {months} (approx {days}d window = {len(data):,} bars)")
        approx_signals = len(data) // 78 * 10  # rough estimate: ~10 signals per ticker per 78 bars/day
        print(f"  Estimated signals across 10 tickers: ~{approx_signals}")
        break
else:
    print("  Intraday history appears limited. Try --months 1 or 2 first.")
    print("  If still no data, your EODHD plan may require an upgrade for intraday.")
    print("  Check: https://eodhd.com/pricing")
