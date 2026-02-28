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

print(" Deep debugging TSLA...")
end = datetime.now()
start = end - timedelta(days=7)
df = fetch_eodhd_intraday("TSLA", start, end)

bars = df.to_dict("records")
detector = BreakoutDetector(
    volume_multiplier=2.0,
    lookback_bars=12,
    min_candle_body_pct=0.2,
    min_bars_since_breakout=0
)

# Manual check of latest bar
latest = bars[-1]
support, resistance = detector.calculate_support_resistance(bars[:-1], "TSLA")
ema_volume = detector.calculate_ema_volume(bars[:-1])
atr = detector.calculate_atr(bars, "TSLA")
candle_strength = detector.analyze_candle_strength(latest)
pdh, pdl = detector.get_pdh_pdl("TSLA")

print(f"\n Latest Bar Analysis:")
print(f"   Time: {latest.get('datetime', 'N/A')}")
print(f"   Close: ${latest['close']:.2f}")
print(f"   Volume: {latest['volume']:,}")
print(f"   Volume Ratio: {latest['volume'] / ema_volume:.2f}x" if ema_volume > 0 else "   Volume Ratio: N/A")

print(f"\n Key Levels:")
print(f"   Resistance: ${resistance:.2f}")
print(f"   Support: ${support:.2f}")
print(f"   PDH: ${pdh:.2f}" if pdh else "   PDH: None")
print(f"   PDL: ${pdl:.2f}" if pdl else "   PDL: None")
print(f"   ATR: ${atr:.2f}")

print(f"\n Candle Strength:")
print(f"   Direction: {candle_strength['direction']}")
print(f"   Body%: {candle_strength['body_pct']*100:.1f}%")
print(f"   Is Strong: {candle_strength['is_strong']}")
print(f"   Has Rejection: {candle_strength['has_rejection']}")

print(f"\n Breakout Checks:")
print(f"   Close > Resistance: {latest['close'] > resistance} ({latest['close']:.2f} vs {resistance:.2f})")
print(f"   Close < Support: {latest['close'] < support} ({latest['close']:.2f} vs {support:.2f})")
print(f"   Volume >= 2.0x: {latest['volume'] / ema_volume >= 2.0 if ema_volume > 0 else False}")

# Try detection
result = detector.detect_breakout(bars, "TSLA")
print(f"\n Result: {result}")
