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

# Get data
print(" Fetching TSLA data...")
end = datetime.now()
start = end - timedelta(days=7)
df = fetch_eodhd_intraday("TSLA", start, end)

print(f" Got {len(df)} bars")

# Look for high-volume bars manually
df['avg_vol'] = df['volume'].rolling(20).mean()
df['vol_ratio'] = df['volume'] / df['avg_vol']

# Find bars with 2x+ volume
high_vol = df[df['vol_ratio'] >= 2.0].copy()
print(f"\n Found {len(high_vol)} bars with 2x+ volume")

if len(high_vol) > 0:
    print(f"\nTop 5 high-volume bars:")
    high_vol_sorted = high_vol.nlargest(5, 'vol_ratio')
    for idx, row in high_vol_sorted.iterrows():
        print(f"  {row['datetime']} | ${row['close']:.2f} | Vol: {row['volume']:,} ({row['vol_ratio']:.1f}x)")

# Check PDH/PDL detection
detector = BreakoutDetector(volume_multiplier=2.0, lookback_bars=12)
bars = df.to_dict("records")

# Check what PDH/PDL would be
from breakout_detector import BreakoutDetector
pdh, pdl = detector.get_pdh_pdl("TSLA")
print(f"\n PDH: ${pdh if pdh else 'None'} | PDL: ${pdl if pdl else 'None'}")

# Try detection
result = detector.detect_breakout(bars, "TSLA")
print(f"\n Breakout result: {result}")
