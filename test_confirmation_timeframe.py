# test_confirmation_timeframe.py -- quick unit test for multi-TF confirmation
from datetime import datetime, timedelta
import json
from scanner_helpers import get_intraday_bars_for_logger  # optional
# We'll import the multi-TF function directly from scanner.py if it's in same folder
from scanner import check_confirmation_multi_timeframe

# create fake 1m bars (ascending times)
def make_1m_bars(base_price=100.0, count=30, start_dt=None):
    start_dt = start_dt or datetime.utcnow()
    bars = []
    for i in range(count):
        openp = base_price + (i * 0.01)
        closep = openp + (0.02 if i % 7 == 0 else -0.01)
        high = max(openp, closep) + 0.02
        low = min(openp, closep) - 0.02
        ts = (start_dt + timedelta(minutes=i)).isoformat()
        bars.append({"open": openp, "high": high, "low": low, "close": closep, "volume": 1000, "date": ts})
    return bars

# simulate entry dict with FVG zone
entry = {"direction":"bull", "zone_low":100.0, "zone_high":100.8, "or_low":99.5, "or_high":101.2}
# NOTE: the check_confirmation_multi_timeframe function will call get_intraday_bars()
# If you don't want network calls you can temporarily monkeypatch it in your test to return the fake bars.
# Example monkeypatch:
import scanner
scanner.get_intraday_bars = lambda ticker, limit=180: make_1m_bars(base_price=100.0, count=120)

confirmed, bar, tf, grade = check_confirmation_multi_timeframe("FAKE", entry)
print("confirmed:", confirmed)
print("timeframe:", tf)
print("grade:", grade)
print("bar:", bar)
