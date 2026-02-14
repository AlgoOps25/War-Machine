import requests
import os
import time
from datetime import datetime
import pytz

print("FORCE REDEPLOY V2", datetime.now())

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

SCAN_INTERVAL = 300  # 5 minutes
MARKET_CAP_MIN = 2_000_000_000
MAX_UNIVERSE = 1000

est = pytz.timezone("US/Eastern")

def send(msg):
    if not DISCORD_WEBHOOK:
        print("No Discord webhook")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg})
    except Exception as e:
        print("Discord error:", e)

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

def build_universe():
    url = f"https://eodhd.com/api/screener?api_token={EODHD_API_KEY}&sort=market_cap.desc&filters=market_cap>{MARKET_CAP_MIN}&limit={MAX_UNIVERSE}"
    try:
        r = requests.get(url).json()
        data = r.get("data", [])
        tickers = [x["code"] for x in data if "code" in x]
        print(f"Universe built: {len(tickers)} stocks")
        return tickers
    except Exception as e:
        print("Universe build error:", e)
        return []

def get_quote(ticker):
    try:
        url = f"https://eodhd.com/api/real-time/{ticker}.US?api_token={EODHD_API_KEY}&fmt=json"
        r = requests.get(url).json()
        return r
    except:
        return None

def score(stock):
    try:
        change = abs(float(stock.get("change_p", 0)))
        volume = float(stock.get("volume", 0))
        avgvol = float(stock.get("avgVolume", 1))

        relvol = volume / avgvol if avgvol else 0
        momentum = change * 2 + relvol * 3
        return momentum, relvol, change
    except:
        return 0,0,0

def run_scan(universe, phase):
    movers = []

    for t in universe[:300]:  # scan 300 per cycle to stay fast
        q = get_quote(t)
        if not q:
            continue

        m, rv, ch = score(q)
        if m > 6 and rv > 1.5:
            movers.append((t, m, rv, ch))

    movers.sort(key=lambda x: x[1], reverse=True)
    top = movers[:10]

    if not top:
        print("No movers this cycle")
        return

    if phase == "premarket":
        header = "🌅 PREMARKET MOMENTUM"
    elif phase == "afterhours":
        header = "🌙 AFTER HOURS LEADERS"
    else:
        header = "🔥 WAR MACHINE — TOP MOMENTUM"

    msg = header + "\n\n"
    for t in top:
        msg += f"{t[0]} | Score {round(t[1],2)} | RelVol {round(t[2],2)} | Move {round(t[3],2)}%\n"

    send(msg)

if __name__ == "__main__":
    send("⚔️ WAR MACHINE v2 ONLINE")
    universe = build_universe()

    while True:
        phase = market_phase()

        if phase == "sleep":
            print("Sleeping until 8AM EST")
            time.sleep(600)
            continue

        print(f"Scanning phase: {phase} | {datetime.now(est)}")

        if not universe:
            universe = build_universe()

        run_scan(universe, phase)
        time.sleep(SCAN_INTERVAL)
