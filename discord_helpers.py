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
    """Send enhanced Discord alert with options recommendation."""
    
    direction_emoji = "🐂" if direction == "bull" else "🐻"
    color = 0x00ff00 if direction == "bull" else 0xff0000
    
    # Build basic embed
    embed = {
        "title": f"{direction_emoji} {ticker} {direction.upper()} SIGNAL",
        "color": color,
        "fields": [
            {"name": "Entry", "value": f"${entry:.2f}", "inline": True},
            {"name": "Stop", "value": f"${stop:.2f}", "inline": True},
            {"name": "Confidence", "value": f"{confidence*100:.1f}%", "inline": True},
            {"name": "T1", "value": f"${t1:.2f}", "inline": True},
            {"name": "T2", "value": f"${t2:.2f}", "inline": True},
            {"name": "Timeframe", "value": timeframe, "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat()
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
        
        option_type = "C" if direction == "bull" else "P"
        
        embed["fields"].extend([
            {"name": "━━━━━━ OPTIONS ━━━━━━", "value": "\u200b", "inline": False},
            {"name": "Suggested Strike", "value": f"${strike}{option_type} {expiration}", "inline": False},
            {"name": "Delta", "value": f"{abs(delta):.2f}", "inline": True},
            {"name": "OI", "value": f"{oi:,}", "inline": True},
            {"name": "Spread", "value": f"${spread:.2f}", "inline": True},
            {"name": "IV", "value": f"{iv*100:.1f}%", "inline": True},
            {"name": "DTE", "value": f"{dte} days", "inline": True},
            {"name": "Expected Move", "value": f"${expected_move:.2f}", "inline": True},
        ])
    else:
        embed["fields"].append({
            "name": "⚠️ Options", 
            "value": "No suitable options found for this signal", 
            "inline": False
        })
    
    payload = {
        "embeds": [embed]
    }
    
    try:
        response = requests.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        print(f"[DISCORD] Alert sent for {ticker}")
    except Exception as e:
        print(f"[DISCORD] Failed to send alert: {e}")
