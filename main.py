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

def main():
    import os
    import sys
    
    print("\n" + "="*60)
    print("WAR MACHINE - STARTUP DIAGNOSTICS")
    print("="*60)
    
    # Check Python version
    print(f"Python: {sys.version}")
    
    # Check environment variables
    api_key = os.getenv("EODHD_API_KEY", "")
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    print(f"EODHD API Key: {'✅ Set (' + api_key[:10] + '...)' if api_key else '❌ MISSING'}")
    print(f"Discord Webhook: {'✅ Set (' + webhook[:30] + '...)' if webhook else '❌ MISSING'}")
    
    # Check current time
    from datetime import datetime
    now = datetime.now()
    print(f"Current Time: {now.strftime('%I:%M:%S %p EST')} on {now.strftime('%A, %B %d, %Y')}")
    
    # Check if market hours
    from scanner import is_market_open
    print(f"Market Status: {'🟢 OPEN' if is_market_open() else '🔴 CLOSED'}")
    
    print("="*60 + "\n")
    
    if not api_key:
        print("❌ FATAL: EODHD_API_KEY not set. Cannot continue.")
        return
    
    if not webhook:
        print("⚠️ WARNING: DISCORD_WEBHOOK_URL not set. No alerts will be sent.")
    
    # Start scanner
    from scanner import start_scanner_loop
    start_scanner_loop()

if __name__ == "__main__":
    main()
