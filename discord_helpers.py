"""
Discord Helpers - Alert Functions for War Machine
Handles all Discord webhook notifications.
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
    grade: str = "A",
    options_data: Optional[Dict] = None
):
    """Send enhanced Discord alert with CFW6 signal and options recommendation."""
    direction_emoji = "🐂" if direction == "bull" else "🐻"
    color = 0x00FF00 if direction == "bull" else 0xFF0000

    # Calculate risk:reward
    risk = abs(entry - stop)
    reward_t1 = abs(t1 - entry)
    reward_t2 = abs(t2 - entry)
    rr_t1 = round(reward_t1 / risk, 2) if risk > 0 else 0
    rr_t2 = round(reward_t2 / risk, 2) if risk > 0 else 0

    fields = [
        {"name": "📥 Entry",          "value": f"${entry:.2f}",                     "inline": True},
        {"name": "🛑 Stop Loss",       "value": f"${stop:.2f}",                      "inline": True},
        {"name": "🎯 Target 1 (2R)",   "value": f"${t1:.2f}  (RR: {rr_t1}x)",       "inline": True},
        {"name": "🎯 Target 2 (3.5R)", "value": f"${t2:.2f}  (RR: {rr_t2}x)",       "inline": True},
        {"name": "📊 Confidence",      "value": f"{confidence:.1%}",                 "inline": True},
        {"name": "🏅 Grade",           "value": grade,                               "inline": True},
    ]

    if options_data:
        fields.append({
            "name": "📋 Recommended Option",
            "value": (
                f"{options_data.get('symbol', 'N/A')}  |  "
                f"Strike: ${options_data.get('strike', 0)}  |  "
                f"DTE: {options_data.get('dte', 0)}"
            ),
            "inline": False
        })

    embed = {
        "title": f"{direction_emoji} CFW6 SIGNAL: {ticker} ({timeframe})",
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"War Machine Sniper  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S EST')}"
        }
    }

    _send_to_discord({"embeds": [embed]})


def send_scaling_alert(
    ticker: str,
    price: float,
    contracts_closed: int,
    contracts_remaining: int,
    partial_pnl: float,
    breakeven_price: float
):
    """Alert when T1 is hit and 50% of position is scaled out."""
    embed = {
        "title": f"✂️ SCALING OUT: {ticker}",
        "color": 0xFFA500,  # Orange
        "description": (
            f"**Target 1** hit at **${price:.2f}**\n"
            f"Sold **{contracts_closed} contract(s)** — "
            f"**{contracts_remaining} contract(s)** still running for T2."
        ),
        "fields": [
            {"name": "💰 Partial P&L",   "value": f"${partial_pnl:+.2f}",          "inline": True},
            {"name": "🛡️ New Stop",      "value": f"${breakeven_price:.2f} (BE)",   "inline": True},
            {"name": "🎯 Next Target",   "value": "Target 2 (3.5R)",               "inline": True},
        ],
        "footer": {
            "text": f"War Machine  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S EST')}"
        }
    }
    _send_to_discord({"embeds": [embed]})


def send_exit_alert(
    ticker: str,
    price: float,
    reason: str,
    total_pnl: float
):
    """Alert for full position close — stop, T2, or EOD."""
    win = total_pnl > 0
    emoji = "✅" if win else "❌"
    color = 0x00FF00 if win else 0xFF0000

    embed = {
        "title": f"{emoji} POSITION CLOSED: {ticker}",
        "color": color,
        "fields": [
            {"name": "💵 Exit Price", "value": f"${price:.2f}",        "inline": True},
            {"name": "📌 Reason",     "value": reason,                 "inline": True},
            {"name": "💰 Total P&L",  "value": f"${total_pnl:+.2f}",  "inline": False},
        ],
        "footer": {
            "text": f"War Machine  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S EST')}"
        }
    }
    _send_to_discord({"embeds": [embed]})


def send_premarket_watchlist(tickers: list, scores: Optional[Dict] = None):
    """Send the pre-market watchlist to Discord before market open."""
    ticker_lines = []
    for t in tickers:
        score = scores.get(t, {}) if scores else {}
        pmis = score.get("pmis", "—")
        gap = score.get("gap_pct", None)
        line = f"**{t}**"
        if gap is not None:
            line += f"  {gap:+.1f}%"
        if pmis != "—":
            line += f"  PMIS: {pmis}"
        ticker_lines.append(line)

    chunk_size = 20
    chunks = [ticker_lines[i:i + chunk_size] for i in range(0, len(ticker_lines), chunk_size)]

    for idx, chunk in enumerate(chunks):
        embed = {
            "title": f"📋 Pre-Market Watchlist ({len(tickers)} tickers)" + (f" — Part {idx+1}" if len(chunks) > 1 else ""),
            "color": 0x1E90FF,  # Blue
            "description": "\n".join(chunk),
            "footer": {
                "text": f"War Machine Pre-Market  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S EST')}"
            }
        }
        _send_to_discord({"embeds": [embed]})


def send_daily_summary(stats: Dict):
    """Send end-of-day performance summary."""
    win_rate = stats.get("win_rate", 0)
    total_pnl = stats.get("total_pnl", 0)
    trades = stats.get("trades", 0)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)

    color = 0x00FF00 if total_pnl >= 0 else 0xFF0000
    emoji = "🟢" if total_pnl >= 0 else "🔴"

    embed = {
        "title": f"{emoji} Daily Summary — {datetime.now().strftime('%B %d, %Y')}",
        "color": color,
        "fields": [
            {"name": "📊 Total Trades", "value": str(trades),              "inline": True},
            {"name": "✅ Wins",          "value": str(wins),                "inline": True},
            {"name": "❌ Losses",        "value": str(losses),              "inline": True},
            {"name": "🎯 Win Rate",      "value": f"{win_rate:.1f}%",       "inline": True},
            {"name": "💰 Net P&L",       "value": f"${total_pnl:+.2f}",    "inline": True},
        ],
        "footer": {
            "text": f"War Machine  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S EST')}"
        }
    }
    _send_to_discord({"embeds": [embed]})


def send_simple_message(message: str):
    """Send a plain text message to Discord."""
    _send_to_discord({"content": message})


def _send_to_discord(payload: Dict):
    """Shared HTTP helper — all functions route through here."""
    if not config.DISCORD_WEBHOOK_URL:
        print("[DISCORD] No webhook URL configured.")
        return
    try:
        response = requests.post(
            config.DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
    except Exception as e:
        print(f"[DISCORD] Error: {e}")
