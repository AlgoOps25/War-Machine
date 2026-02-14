import requests
import os
import time
from datetime import datetime
import pytz

print("⚔️ WAR MACHINE ELITE ACTIVE v3 STARTING")

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

SCAN_INTERVAL = 300  # 5 min
MARKET_CAP_MIN = 2_000_000_000
MAX_UNIVERSE = 1000

est = pytz.timezone("US/Eastern")

# =========================
# DISCORD
# =========================
def send(msg):
    if not DISCORD_WEBHOOK:
        print("No webhook set")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e:
        print("Discord error:", e)

# =========================
# MARKET PHASE
# =========================
def market_phase():
    now = datetime.now(est)
    h = now.hour
    m = now.minute

    if h < 8:
        return "sleep"
    if 8 <= h < 9 or (h == 9 and m < 30):
        return "premarket"
    if (h > 9 or (h == 9 and m >= 30)) and h < 16:
        return "market"
    if 16 <= h < 20:
        return "afterhours"
    return "sleep"

# =========================
# BUILD UNIVERSE
# =========================
def build_universe():
    print("Building universe...")
    url = f"https://eodhd.com/api/screener?api_token={EODHD_API_KEY}&sort=market_cap.desc&filters=market_cap>{MARKET_CAP_MIN}&limit={MAX_UNIVERSE}"

    try:
        r = requests.get(url, timeout=20).json()
        data = r.get("data", [])
        tickers = [x["code"] for x in data if "code" in x]
        print(f"Universe built: {len(tickers)} stocks")
        return tickers
    except Exception as e:
        print("Universe error:", e)
        return []

# =========================
# GET REALTIME
# =========================
def get_quote(ticker):
    try:
        url = f"https://eodhd.com/api/real-time/{ticker}.US?api_token={EODHD_API_KEY}&fmt=json"
        r = requests.get(url, timeout=10).json()
        return r
    except:
        return None

# =========================
# ELITE SCORING ENGINE
# =========================
def score(stock):
    try:
        change = float(stock.get("change_p", 0))
        volume = float(stock.get("volume", 0))
        avgvol = float(stock.get("avgVolume", 1))
        price = float(stock.get("close", 0))

        if price < 5:
            return 0

        relvol = volume / avgvol if avgvol else 0

        # momentum build
        momentum = abs(change) * 1.8

        # volume expansion
        volume_score = relvol * 2.2

        # not extended filter
        extension_penalty = 0
        if abs(change) > 12:
            extension_penalty = 4

        total = momentum + volume_score - extension_penalty

        return total, relvol, change, price
    except:
        return 0,0,0,0

# =========================
# SCAN
# =========================
def run_scan(universe, phase):
    print("Scanning market...")

    movers = []

    for t in universe[:350]:
        q = get_quote(t)
        if not q:
            continue

        s, rv, ch, price = score(q)

        if s > 7 and rv > 1.3:
            movers.append((t, s, rv, ch, price))

    movers.sort(key=lambda x: x[1], reverse=True)
    top = movers[:5]

    if not top:
        print("No elite movers detected")
        return

    if phase == "premarket":
        header = "🌅 ELITE PREMARKET WATCH"
    elif phase == "afterhours":
        header = "🌙 AFTER HOURS BUILD"
    else:
        header = "🔥 WAR MACHINE ELITE ACTIVE — TOP 5"

    msg = header + "\n\n"

    for t in top:
        msg += f"{t[0]} | Score {round(t[1],2)} | RelVol {round(t[2],2)} | Move {round(t[3],2)}% | ${round(t[4],2)}\n"

    send(msg)

# =========================
# MAIN LOOP
# =========================
if __name__ == "__main__":
    send("⚔️ WAR MACHINE ELITE ACTIVE v3 ONLINE")

    universe = build_universe()

    while True:
        phase = market_phase()

        if phase == "sleep":
            print("Sleeping until 8AM EST")
            time.sleep(600)
            continue

        print(f"Phase: {phase} | {datetime.now(est)}")

        if not universe:
            universe = build_universe()

        run_scan(universe, phase)
        time.sleep(SCAN_INTERVAL)
