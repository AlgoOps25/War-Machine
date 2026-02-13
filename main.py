import os
import requests
import time
from datetime import datetime

# ===== LOAD KEYS FROM RAILWAY =====
EODHD_API_KEY = os.getenv("EODHD_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
MODE = os.getenv("MODE")

# ===== DISCORD ALERT FUNCTION =====
def send_discord(message):
    try:
        data = {"content": message}
        requests.post(DISCORD_WEBHOOK, json=data, timeout=10)
    except Exception as e:
        print("Discord error:", e)

# ===== GET TOP ACTIVE STOCKS =====
def get_market_movers():
    url = f"https://eodhd.com/api/screener?api_token={EODHD_API_KEY}&sort=volume&order=desc&limit=15"
    
    try:
        r = requests.get(url, timeout=20)
        data = r.json()
        return data
    except Exception as e:
        print("EODHD error:", e)
        return []

# ===== BUILD WATCHLIST =====
def build_watchlist():
    movers = get_market_movers()
    watch = []

    for stock in movers:
        try:
            price = float(stock.get("close", 0))
            volume = int(stock.get("volume", 0))
            symbol = stock.get("code")

            if price > 2 and volume > 1_000_000:
                watch.append(symbol)
        except:
            pass

    return watch[:5]

# ===== MAIN LOOP =====
def run():
    print("WAR MACHINE STARTED")

    send_discord("⚔️ WAR MACHINE ONLINE (Railway Live)")

    while True:
        try:
            now = datetime.now().strftime("%H:%M:%S")
            watchlist = build_watchlist()

            if watchlist:
                msg = f"📊 Top Momentum Watchlist ({now})\n"
                for t in watchlist:
                    msg += f"- {t}\n"
                send_discord(msg)

            else:
                send_discord("No strong movers detected.")

            time.sleep(300)  # every 5 min

        except Exception as e:
            print("Loop error:", e)
            time.sleep(60)

# ===== START =====
if __name__ == "__main__":
    run()
