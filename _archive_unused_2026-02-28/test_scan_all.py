import sys
sys.path.insert(0, ".")
from breakout_detector import BreakoutDetector
from datetime import datetime, timedelta
import requests
import pandas as pd
import os

def fetch_eodhd_intraday(ticker: str, from_date: datetime, to_date: datetime) -> pd.DataFrame:
    from_ts = int(from_date.timestamp())
    to_ts = int(to_date.timestamp())
    
    url = f"https://eodhd.com/api/intraday/{ticker}.US"
    params = {
        "api_token": os.environ.get("EODHD_API_KEY"),
        "fmt": "json",
        "interval": "1m",
        "from": from_ts,
        "to": to_ts
    }
    
    response = requests.get(url, params=params, timeout=30)
    data = response.json()
    
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
    return df

print(" Scanning TSLA for valid breakout moments...")
end = datetime.now()
start = end - timedelta(days=7)
df = fetch_eodhd_intraday("TSLA", start, end)

detector = BreakoutDetector(
    volume_multiplier=2.0,
    lookback_bars=12,
    min_candle_body_pct=0.2,
    min_bars_since_breakout=0
)

signals_found = []

# Scan through bars starting after lookback period
for i in range(100, len(df)):
    bars_subset = df.iloc[:i+1].to_dict("records")
    result = detector.detect_breakout(bars_subset, "TSLA")
    
    if result:
        signals_found.append({
            'time': bars_subset[-1].get('datetime'),
            'entry': result.get('entry'),
            'type': result.get('type'),
            'confidence': result.get('confidence')
        })

print(f"\n Found {len(signals_found)} valid signals!")

if signals_found:
    print(f"\nFirst 10 signals:")
    for sig in signals_found[:10]:
        print(f"  {sig['time']} | ${sig['entry']:.2f} | {sig['type']} | {sig['confidence']}%")
else:
    print("\n Zero signals - detector is rejecting everything!")
