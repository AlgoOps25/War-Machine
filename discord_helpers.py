\"\"\"
Discord notification helpers with options chain integration.
\"\"\"
import requests
from typing import Dict, Optional
from datetime import datetime
import config

def send_options_signal_alert(
    ticker: str,
    direction: str,
    entry: float,
    stop: float,
    t1: float,
    t2: float,
    confidence: float,
    timeframe: str,
    options_data: Optional[Dict] = None
):
    \"\"\"Send enhanced Discord alert with CFW6 confirmation and options recommendation\"\"\"
    direction_emoji = \"🐂\" if direction == \"bull\" else \"🐻\"
    color = 0x00FF00 if direction == \"bull\" else 0xFF0000
    
    # Calculate risk:reward
    risk = abs(entry - stop)
    reward_t1 = abs(t1 - entry)
    rr_t1 = round(reward_t1 / risk, 2) if risk > 0 else 0
    
    embed = {
        \"title\": f\"{direction_emoji} CFW6 SIGNAL DETECTED: {ticker} ({timeframe})\",
        \"color\": color,
        \"fields\": [
            {\"name\": \"Entry\", \"value\": f\"${entry:.2f}\", \"inline\": True},
            {\"name\": \"Stop Loss\", \"value\": f\"${stop:.2f}\", \"inline\": True},
            {\"name\": \"Target 1 (2R)\", \"value\": f\"${t1:.2f} (RR: {rr_t1})\", \"inline\": True},
            {\"name\": \"Target 2 (MTF)\", \"value\": f\"${t2:.2f}\", \"inline\": True},
            {\"name\": \"Confidence\", \"value\": f\"{confidence:.1%}\", \"inline\": True}
        ],
        \"footer\": {\"text\": f\"War Machine Sniper | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\"}
    }
    
    if options_data:
        embed[\"fields\"].append({
            \"name\": \"Recommended Option\",
            \"value\": f\"{options_data.get('symbol', 'N/A')} | Strike: ${options_data.get('strike', 0)} | DTE: {options_data.get('dte', 0)}\",
            \"inline\": False
        })
    
    _send_to_discord({\"embeds\": [embed]})

def send_scaling_alert(ticker: str, price: float, remaining: int, pnl: float):
    \"\"\"Alert for T1 scaling out\"\"\"
    embed = {
        \"title\": f\"✂️ SCALING OUT: {ticker}\",
        \"color\": 0xFFA500, # Orange
        \"description\": f\"Hit **Target 1** at ${price:.2f}. Sold 50%. Remaining: **{remaining} contracts**.\",
        \"fields\": [
            {\"name\": \"T1 P&L\", \"value\": f\"${pnl:+.2f}\", \"inline\": True},
            {\"name\": \"Stop Loss\", \"value\": \"Moved to **Break Even**\", \"inline\": True}
        ]
    }
    _send_to_discord({\"embeds\": [embed]})

def send_exit_alert(ticker: str, price: float, reason: str, total_pnl: float):
    \"\"\"Alert for full position exit\"\"\"
    win = total_pnl > 0
    emoji = \"✅\" if win else \"❌\"
    color = 0x00FF00 if win else 0xFF0000
    
    embed = {
        \"title\": f\"{emoji} POSITION CLOSED: {ticker}\",
        \"color\": color,
        \"fields\": [
            {\"name\": \"Exit Price\", \"value\": f\"${price:.2f}\", \"inline\": True},
            {\"name\": \"Reason\", \"value\": reason, \"inline\": True},
            {\"name\": \"Total P&L\", \"value\": f\"${total_pnl:+.2f}\", \"inline\": False}
        ]
    }
    _send_to_discord({\"embeds\": [embed]})

def send_simple_message(message: str):
    \"\"\"Send a plain text message\"\"\"
    _send_to_discord({\"content\": message})

def _send_to_discord(payload: Dict):
    if not config.DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f\"[DISCORD] Error: {e}\")
