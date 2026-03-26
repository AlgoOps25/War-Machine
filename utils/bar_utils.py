from collections import defaultdict

def resample_bars(bars_1m: list, minutes: int) -> list:
    """Resample 1m bars into a higher timeframe bucket (Issue #3 fix)."""
    buckets = defaultdict(list)
    for b in bars_1m:
        dt = b["datetime"]
        floored = dt.replace(minute=(dt.minute // minutes) * minutes, second=0, microsecond=0)
        buckets[floored].append(b)
    
    result = []
    for ts in sorted(buckets):
        bucket = buckets[ts]
        result.append({
            "datetime": ts,
            "open": bucket[0]["open"],
            "high": max(b["high"] for b in bucket),
            "low": min(b["low"] for b in bucket),
            "close": bucket[-1]["close"],
            "volume": sum(b["volume"] for b in bucket),
        })
    return result
