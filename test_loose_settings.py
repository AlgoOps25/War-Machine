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

print(" Testing TSLA with LOOSE settings...")
end = datetime.now()
start = end - timedelta(days=7)
df = fetch_eodhd_intraday("TSLA", start, end)

print(f" Got {len(df)} bars\n")

# Test 1: Current strict settings
detector_strict = BreakoutDetector(
    volume_multiplier=2.0,
    lookback_bars=12,
    min_candle_body_pct=0.4,  # 40% body
    min_bars_since_breakout=1
)
bars = df.to_dict("records")
result_strict = detector_strict.detect_breakout(bars, "TSLA")
print(f" STRICT (40% body, 1 bar confirm): {result_strict is not None}")

# Test 2: Looser body requirement
detector_loose = BreakoutDetector(
    volume_multiplier=2.0,
    lookback_bars=12,
    min_candle_body_pct=0.2,  # 20% body
    min_bars_since_breakout=0  # No confirmation wait
)
result_loose = detector_loose.detect_breakout(bars, "TSLA")
print(f" LOOSE (20% body, no confirm): {result_loose is not None}")
if result_loose:
    print(f"   Entry: ${result_loose.get('entry'):.2f}")
    print(f"   Stop: ${result_loose.get('stop'):.2f}")
    print(f"   Confidence: {result_loose.get('confidence')}%")
    print(f"   Type: {result_loose.get('type')}")
