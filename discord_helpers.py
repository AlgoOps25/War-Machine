"""
Discord notification helpers with options chain integration.
"""

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
    """Send enhanced Discord alert with CFW6 confirmation and options recommendation."""
    
    direction_emoji = "🐂" if direction == "bull" else "🐻"
    color = 0x00ff00 if direction == "bull" else 0xff0000
    
    # Calculate risk:reward
    risk = abs(entry - stop)
    reward_t1 = abs(t1 - entry)
    rr_t1 = round(reward_t1 / risk, 2) if risk > 0 else 0
    
    # Build basic embed
    embed = {
        "title": f"{direction_emoji} {ticker} {direction.upper()} SIGNAL - CFW6",
        "color": color,
        "fields": [
            {"name": "Entry", "value": f"${entry:.2f}", "inline": True},
            {"name": "Stop", "value": f"${stop:.2f}", "inline": True},
            {"name": "Confidence", "value": f"{confidence*100:.1f}%", "inline": True},
            {"name": "T1", "value": f"${t1:.2f}", "inline": True},
            {"name": "T2", "value": f"${t2:.2f}", "inline": True},
            {"name": "R:R", "value": f"1:{rr_t1}", "inline": True},
            {"name": "Timeframe", "value": timeframe, "inline": True},
            {"name": "Risk", "value": f"${risk:.2f}", "inline": True},
            {"name": "Strategy", "value": "ORB + FVG + CFW6", "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "War Machine • Options Signal Engine"}
    }
    
    # Add options recommendation if available
    if options_data:
        strike = options_data.get("strike", 0)
        expiration = options_data.get("expiration", "N/A")
        delta = options_data.get("delta", 0)
        oi = options_data.get("oi", 0)
        bid = options_data.get("bid", 0)
        ask = options_data.get("ask", 0)
        iv = options_data.get("iv", 0)
        dte = options_data.get("dte", 0)
        expected_move = options_data.get("expected_move", 0)
        
        spread = ask - bid if (ask and bid) else 0
        mid = (bid + ask) / 2 if (bid and ask) else 0
        
        option_type = "C" if direction == "bull" else "P"
        
        embed["fields"].extend([
            {"name": "━━━━━━━━━━ OPTIONS ━━━━━━━━━━", "value": "\u200b", "inline": False},
            {"name": "Suggested Strike", "value": f"${strike:.0f}{option_type} exp {expiration}", "inline": False},
            {"name": "Mid Price", "value": f"${mid:.2f}", "inline": True},
            {"name": "Delta", "value": f"{abs(delta):.2f}", "inline": True},
            {"name": "DTE", "value": f"{dte} days", "inline": True},
            {"name": "OI", "value": f"{oi:,}", "inline": True},
            {"name": "Spread", "value": f"${spread:.2f}", "inline": True},
            {"name": "IV", "value": f"{iv*100:.1f}%", "inline": True},
            {"name": "Expected Move", "value": f"${expected_move:.2f}", "inline": True},
            {"name": "Volume", "value": f"{options_data.get('volume', 0):,}", "inline": True},
            {"name": "Score", "value": f"{options_data.get('score', 0):.0f}/300", "inline": True},
        ])
    else:
        embed["fields"].append({
            "name": "⚠️ Options", 
            "value": "No suitable options found (low liquidity or poor IV)", 
            "inline": False
        })
    
    payload = {
        "embeds": [embed]
    }
    
    try:
        response = requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        print(f"[DISCORD] ✅ Alert sent for {ticker} {direction.upper()}")
    except Exception as e:
        print(f"[DISCORD] ❌ Failed to send alert: {e}")


def send_simple_message(message: str):
    """Send simple text message to Discord (for debugging/status)."""
    try:
        payload = {"content": message}
        response = requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"[DISCORD] Error sending message: {e}")
