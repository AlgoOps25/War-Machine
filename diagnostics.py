# Quick diagnostic - run this
from data_manager import data_manager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Check what data we actually have
ticker = 'SPY'
bars_1m = data_manager.get_bars_from_memory(ticker, limit=100)

if bars_1m:
    print(f"\n✅ Found {len(bars_1m)} 1m bars for {ticker}")
    print(f"   Date range: {bars_1m[0]['datetime']} to {bars_1m[-1]['datetime']}")
    print(f"   Latest bar date: {bars_1m[-1]['datetime'].date()}")
else:
    print(f"\n❌ No bars found for {ticker}")

# Check 5m table directly
bars_5m = data_manager.get_today_5m_bars(ticker)
print(f"\n5m bars (today): {len(bars_5m)}")

# Try getting yesterday's date
yesterday = (datetime.now(ET) - timedelta(days=1)).date()
print(f"\nYesterday was: {yesterday}")
print(f"Today is: {datetime.now(ET).date()}")
