# discord_bot.py
import os
import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

def send(msg):
    if not DISCORD_WEBHOOK:
        print("No Discord webhook configured.")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e:
        print("Discord send error:", e)
