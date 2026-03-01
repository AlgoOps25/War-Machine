import sys
sys.path.insert(0, ".")
from breakout_detector import BreakoutDetector
from datetime import datetime, timedelta
import requests
import pandas as pd
import os

# EODHD fetch function (copied from backtest)
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

# Test with TSLA
print(" Testing TSLA for last 5 trading days...")
detector = BreakoutDetector(volume_multiplier=2.0, lookback_bars=12)

end = datetime.now()
start = end - timedelta(days=7)
df = fetch_eodhd_intraday("TSLA", start, end)

print(f"\n Got {len(df)} bars")
if len(df) > 0:
    print(f"Date range: {df['datetime'].min()} to {df['datetime'].max()}")
    print(f"\n Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    print(f" Max volume: {df['volume'].max():,}")
    
    # Test detection
    bars = df.to_dict("records")
    result = detector.detect_breakout(bars, "TSLA")
    
    if result:
        print(f"\n BREAKOUT FOUND!")
        print(f"   Type: {result.get('type')}")
        print(f"   Entry: ${result.get('entry'):.2f}")
        print(f"   Confidence: {result.get('confidence')}%")
    else:
        print(f"\n NO BREAKOUT - Detector is too strict or no valid patterns")
        
        # Check what might be failing
        print(f"\n Diagnostic:")
        print(f"   Min bars needed: 100")
        print(f"   Bars available: {len(df)}")
        print(f"   Volume multiplier: 2.0x")
        print(f"   Lookback: 12 bars")
else:
    print(" No data returned!")
