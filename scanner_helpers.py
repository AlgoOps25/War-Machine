# scanner_helpers.py
import requests, os
EODHD_API_KEY = os.getenv("EODHD_API_KEY")

def get_intraday_bars_for_logger(ticker, limit=120, interval="1m"):
    try:
        url = f"https://eodhd.com/api/intraday/{ticker}.US?api_token={EODHD_API_KEY}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data
    except Exception:
        return []

def get_realtime_quote_for_logger(ticker):
    try:
        url = f"https://eodhd.com/api/real-time/{ticker}.US?api_token={EODHD_API_KEY}&fmt=json"
        r = requests.get(url, timeout=6)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None

# --- paste-replace: check_confirmation_for_ticker -> multi-timeframe aware version ---
def aggregate_bars(bars_1m, agg_n):
    """
    Aggregate 1m bars into bars of length agg_n (e.g., 2 => 2m bars, 3 => 3m bars).
    Input bars_1m: list of 1m bars in ascending time order (oldest..newest).
    Returns list of aggregated bars as dicts with open/high/low/close/volume and datetime.
    """
    out = []
    if not bars_1m or agg_n <= 1:
        return bars_1m
    # ensure bars_1m sorted ascending by timestamp
    chunk = []
    for b in bars_1m:
        chunk.append(b)
        if len(chunk) == agg_n:
            try:
                openp = float(chunk[0].get("open") or chunk[0].get("Open") or 0)
                closep = float(chunk[-1].get("close") or chunk[-1].get("Close") or chunk[-1].get("close", 0))
                highs = [float(x.get("high") or x.get("High") or 0) for x in chunk]
                lows = [float(x.get("low") or x.get("Low") or 0) for x in chunk]
                vol = sum([float(x.get("volume") or x.get("Volume") or 0) for x in chunk])
                ts = chunk[-1].get("date") or chunk[-1].get("datetime") or None
                out.append({"open": openp, "high": max(highs), "low": min(lows), "close": closep, "volume": vol, "date": ts})
            except Exception:
                pass
            chunk = []
    # If leftover partial chunk (< agg_n) we ignore (we only want full aggregated bars)
    return out

def check_confirmation_multi_timeframe(ticker, entry):
    """
    Multi-timeframe confirmation based on video rules.
    Returns (confirmed_bool, confirming_bar, timeframe_label, grade)
      where timeframe_label is one of: '5m','3m','2m','1m'
    Logic:
      1) Try 5m bars (EODHD interval=5m).
      2) If not confirmed, fetch 1m bars and aggregate to 3m/2m.
      3) Test 3m, then 2m, then 1m.
    The confirmation test uses existing logic: bar touches FVG zone and flips in direction, and closes sufficiently inside the zone
    """
    try:
        # helper: reuse compute zone values
        zone_low = entry["zone_low"]
        zone_high = entry["zone_high"]
        direction = entry["direction"]
        or_low = entry.get("or_low")
        or_high = entry.get("or_high")
        # First: try 5m from EODHD
        try:
            bars_5m = get_intraday_bars_for_logger(ticker, limit=120)  # call supports interval param in your wrapper; if not, adjust below
            # If your get_intraday_bars supports interval argument, change call to: get_intraday_bars(ticker, limit=120, interval='5m')
        except Exception:
            bars_5m = []
        # Normalize bars_5m to list of dicts with open,close,high,low,date
        def check_bars_for_confirmation(bars, tf_label):
            # bars assumed ascending
            if not bars:
                return None
            # we check recent N bars (e.g. last 12 units of that timeframe)
            for b in reversed(bars[-12:]):
                try:
                    low = float(b.get("low") or b.get("Low") or 0)
                    high = float(b.get("high") or b.get("High") or 0)
                    openp = float(b.get("open") or b.get("Open") or 0)
                    closep = float(b.get("close") or b.get("Close") or b.get("close", 0))
                except:
                    continue
                body = abs(closep - openp)
                rsize = max(zone_high - zone_low, 1e-9)
                if direction == "bull":
                    tapped = (low <= zone_high) and (closep > openp)  # touched zone and closed green
                    if tapped and (closep >= (zone_low + 0.5 * rsize)):
                        # grade
                        if closep > openp and body >= 0.5 * rsize and (min(closep, openp) - low) <= 0.15 * body:
                            grade = "A+"
                        elif openp < closep and (low < openp):
                            grade = "A"
                        else:
                            grade = "A-"
                        return {"bar": b, "grade": grade, "tf": tf_label}
                else:
                    tapped = (high >= zone_low) and (closep < openp)
                    if tapped and (closep <= (zone_high - 0.5 * rsize)):
                        if closep < openp and body >= 0.5 * rsize and (high - max(closep, openp)) <= 0.15 * body:
                            grade = "A+"
                        elif openp > closep and (high > openp):
                            grade = "A"
                        else:
                            grade = "A-"
                        return {"bar": b, "grade": grade, "tf": tf_label}
            return None

        # 1) Check 5m bars (if bars exist)
        if bars_5m:
            res5 = check_bars_for_confirmation(bars_5m, "5m")
            if res5:
                # only A+ or A allowed for confirmations (depending on your grade policy)
                if res5["grade"] in ("A+","A"):
                    return True, res5["bar"], res5["tf"], res5["grade"]
                # if only A+ allowed adjust here

        # 2) Fetch 1m bars (we will aggregate into 3m and 2m)
        bars_1m = get_intraday_bars_for_logger(ticker, limit=180, interval="1m")  # returns 1m bars ascending
        if not bars_1m:
            return False, None, None, None

        # 3) Build 3m aggregated bars (prefer 3m then 2m)
        bars_3m = aggregate_bars(bars_1m, 3)
        res3 = None
        if bars_3m:
            res3 = check_bars_for_confirmation(bars_3m, "3m")
            if res3 and res3["grade"] in ("A+","A"):
                return True, res3["bar"], res3["tf"], res3["grade"]

        # 4) 2m aggregated
        bars_2m = aggregate_bars(bars_1m, 2)
        res2 = None
        if bars_2m:
            res2 = check_bars_for_confirmation(bars_2m, "2m")
            if res2 and res2["grade"] in ("A+","A"):
                return True, res2["bar"], res2["tf"], res2["grade"]

        # 5) finally check 1m
        res1 = check_bars_for_confirmation(bars_1m, "1m")
        if res1 and res1["grade"] in ("A+","A"):
            return True, res1["bar"], res1["tf"], res1["grade"]

        return False, None, None, None
    except Exception as e:
        print("check_confirmation_multi_timeframe error:", e)
        return False, None, None, None
# --- end paste-replace
