import os
import requests
from learning_engine import start_background as start_learning
import sniper
import scanner

# ===== LOAD KEYS =====
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# ===== DISCORD ALERT =====
def send_discord(message):
    if not DISCORD_WEBHOOK:
        print(message)
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception as e:
        print("Discord error:", e)

# ===== START BOT =====
if __name__ == "__main__":

    send_discord("⚔️ WAR MACHINE GOD MODE PRO — FULLY ONLINE")

    print("⚔️ WAR MACHINE STARTING")

    # Start learning engine
    try:
        start_learning()
        print("Learning engine started")
    except Exception as e:
        print("Learning engine error:", e)

    # Start sniper fast monitor
    try:
        sniper.start_fast_monitor()
        print("Sniper monitor started")
    except Exception as e:
        print("Sniper start error:", e)

    # Start scanner loop (MAIN ENGINE)
    try:
        scanner.start_scanner_loop()
    except Exception as e:
        print("Scanner crashed:", e)
