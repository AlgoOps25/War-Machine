import requests
import os
import config

def _send_to_discord(payload: Dict):
    """Shared HTTP helper — all functions route through here."""
    print(f"[DISCORD] Webhook URL: {'✅ Set (' + config.DISCORD_WEBHOOK_URL[:30] + '...)' if config.DISCORD_WEBHOOK_URL else '❌ EMPTY'}")
    if not config.DISCORD_WEBHOOK_URL:
        print("[DISCORD] No webhook URL configured.")
        return
    try:
        response = requests.post(
            config.DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10
        )
        print(f"[DISCORD] Response: {response.status_code}")
        response.raise_for_status()
    except Exception as e:
        print(f"[DISCORD] Error: {e}")

# Test 1: Direct hardcoded URL test
webhook_url = "https://discord.com/api/webhooks/1471917294891307100/onHzBfoozy0UK91wBi-7w0lC3NzF_eiiW2sUAuWLZogpWfMAk5Azfr7DcFyaGeKDM_Sa"

payload = {
    "content": "🧪 War Machine - Direct webhook test",
    "embeds": [{
        "title": "✅ Discord Integration Working",
        "description": "If you see this, the webhook URL is valid.",
        "color": 0x00FF00
    }]
}

print("Sending test message...")
try:
    r = requests.post(webhook_url, json=payload, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
    if r.status_code == 204:
        print("✅ SUCCESS - Discord webhook is working!")
    else:
        print("❌ FAILED - Check response above")
except Exception as e:
    print(f"❌ Exception: {e}")

# Test 2: Check if env var is being read correctly
print("\n--- ENV VAR TEST ---")
env_val = os.getenv("DISCORD_WEBHOOK_URL", "NOT SET")
print(f"DISCORD_WEBHOOK_URL from env: {env_val[:50] if env_val != 'NOT SET' else 'NOT SET'}")
