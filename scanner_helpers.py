# scanner_helpers.py
import requests
import os

EODHD_API_KEY = os.getenv("EODHD_API_KEY")


# =========================================================
# 🔥 CORE INTRADAY FETCH (FIXED + STABLE)
# =========================================================
def get_intraday_bars_for_logger(ticker, limit=120, interval="1m"):
    """
    Pull intraday bars from EODHD.
    Returns list of bars sorted oldest -> newest
    """

    if not EODHD_API_KEY:
        print("❌ EODHD_API_KEY missing")
        return []

    try:
        symbol = f"{ticker}.US"

        url = (
            f"https://eodhd.com/api/intraday/{symbol}"
            f"?api_token={EODHD_API_KEY}"
            f"&interval={interval}"
            f"&fmt=json"
            f"&limit={limit}"
        )

        r = requests.get(url, timeout=15)

        if r.status_code != 200:
            print(f"❌ EODHD HTTP {r.status_code} for {ticker}")
            return []

        data = r.json()

        if not data:
            print(f"❌ {ticker} NO DATA FROM EODHD")
            return []

        # Sometimes EODHD wraps in {"data": []}
        if isinstance(data, dict) and "data" in data:
            bars = data["data"]
        else:
            bars = data

        if not isinstance(bars, list) or len(bars) == 0:
            print(f"❌ {ticker} EMPTY BAR LIST")
            return []

        # sort oldest -> newest
        try:
            bars.sort(key=lambda x: x.get("datetime") or x.get("date") or "")
        except:
            pass

        print(f"✅ {ticker} bars fetched: {len(bars)}")
        return bars

    except Exception as e:
        print(f"❌ EODHD fetch error {ticker}:", e)
        return []


# =========================================================
# REALTIME QUOTE
# =========================================================
def get_realtime_quote_for_logger(ticker):
    try:
        symbol = f"{ticker}.US"
        url = f"https://eodhd.com/api/real-time/{symbol}?api_token={EODHD_API_KEY}&fmt=json"

        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None

        return r.json()
    except Exception as e:
        print("quote error:", e)
        return None


# =========================================================
# AGGREGATION (1m -> 2m/3m)
# =========================================================
def aggregate_bars(bars_1m, agg_n):
    out = []

    if not bars_1m or agg_n <= 1:
        return bars_1m

    chunk = []

    for b in bars_1m:
        chunk.append(b)

        if len(chunk) == agg_n:
            try:
                openp = float(chunk[0].get("open", 0))
                closep = float(chunk[-1].get("close", 0))
                highs = [float(x.get("high", 0)) for x in chunk]
                lows = [float(x.get("low", 0)) for x in chunk]
                vol = sum([float(x.get("volume", 0)) for x in chunk])
                ts = chunk[-1].get("datetime") or chunk[-1].get("date")

                out.append({
                    "open": openp,
                    "high": max(highs),
                    "low": min(lows),
                    "close": closep,
                    "volume": vol,
                    "datetime": ts
                })
            except:
                pass

            chunk = []

    return out


# =========================================================
# 🔥 MULTI TIMEFRAME CONFIRMATION ENGINE
# =========================================================
def check_confirmation_multi_timeframe(ticker, entry):
    try:
        zone_low = entry["zone_low"]
        zone_high = entry["zone_high"]
        direction = entry["direction"]

        # ============================================
        # 1️⃣ CHECK 5m FIRST (REAL 5m ENDPOINT)
        # ============================================
        bars_5m = get_intraday_bars_for_logger(ticker, limit=120, interval="5m")

        def check_bars(bars, tf_label):
            if not bars:
                return None

            for b in reversed(bars[-12:]):
                try:
                    low = float(b.get("low", 0))
                    high = float(b.get("high", 0))
                    openp = float(b.get("open", 0))
                    closep = float(b.get("close", 0))
                except:
                    continue

                body = abs(closep - openp)
                zone_size = max(zone_high - zone_low, 0.01)

                if direction == "bull":
                    tapped = (low <= zone_high) and closep > openp
                    if tapped and closep >= zone_low + 0.5 * zone_size:
                        grade = "A+" if body > zone_size * 0.6 else "A"
                        return {"bar": b, "grade": grade, "tf": tf_label}

                else:
                    tapped = (high >= zone_low) and closep < openp
                    if tapped and closep <= zone_high - 0.5 * zone_size:
                        grade = "A+" if body > zone_size * 0.6 else "A"
                        return {"bar": b, "grade": grade, "tf": tf_label}

            return None

        if bars_5m:
            res5 = check_bars(bars_5m, "5m")
            if res5:
                return True, res5["bar"], res5["tf"], res5["grade"]

        # ============================================
        # 2️⃣ GET 1m DATA
        # ============================================
        bars_1m = get_intraday_bars_for_logger(ticker, limit=200, interval="1m")

        if not bars_1m:
            print(f"❌ {ticker} NO 1M DATA")
            return False, None, None, None

        # ============================================
        # 3️⃣ 3m
        # ============================================
        bars_3m = aggregate_bars(bars_1m, 3)
        res3 = check_bars(bars_3m, "3m")
        if res3:
            return True, res3["bar"], res3["tf"], res3["grade"]

        # ============================================
        # 4️⃣ 2m
        # ============================================
        bars_2m = aggregate_bars(bars_1m, 2)
        res2 = check_bars(bars_2m, "2m")
        if res2:
            return True, res2["bar"], res2["tf"], res2["grade"]

        # ============================================
        # 5️⃣ 1m FINAL
        # ============================================
        res1 = check_bars(bars_1m, "1m")
        if res1:
            return True, res1["bar"], res1["tf"], res1["grade"]

        return False, None, None, None

    except Exception as e:
        print("confirmation error:", e)
        return False, None, None, None
