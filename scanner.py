import requests
import os
import time
from datetime import datetime

EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

SCAN_INTERVAL = 300  # 5 minutes
MIN_MARKET_CAP = 2_000_000_000

def send_discord(msg):
    if not DISCORD_WEBHOOK:
        print("No webhook set")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg})
    except Exception as e:
        print("Discord error:", e)

def get_us_stocks():
    url = f"https://eodhd.com/api/screener?api_token={EODHD_API_KEY}&sort=market_cap.desc&filters=market_cap>{MIN_MARKET_CAP}&limit=200"
    try:
        r = requests.get(url).json()
        return r.get("data", [])
    except Exception as e:
        print("EODHD error:", e)
        return []

def score_stock(stock):
    try:
        price = float(stock.get("close", 0))
        change = float(stock.get("change_p", 0))
        volume = float(stock.get("volume", 0))
        avgvol = float(stock.get("avgvol_200d", 1))

        relvol = volume / avgvol if avgvol else 0

        score = (
            abs(change) * 2 +
            relvol * 3
        )

        return score, relvol, change
    except:
        return 0,0,0

def scan():
    stocks = get_us_stocks()
    scored = []

    for s in stocks:
        score, relvol, change = score_stock(s)
        if score > 5 and relvol > 1.5:
            scored.append((s["code"], score, relvol, change))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:10]

    if not top:
        send_discord("Market quiet — no strong momentum yet. Monitoring.")
        return

    msg = "🔥 **WAR MACHINE — TOP MOMENTUM** 🔥\n\n"
    for t in top:
        msg += f"{t[0]} | Score {round(t[1],2)} | RelVol {round(t[2],2)} | Move {round(t[3],2)}%\n"

    send_discord(msg)

if __name__ == "__main__":
    send_discord("WAR MACHINE STARTED — Elite Scanner Active")
    while True:
        print(f"Scanning {datetime.now()}")
        scan()
        time.sleep(SCAN_INTERVAL)
