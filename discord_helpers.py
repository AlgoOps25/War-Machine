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
        # ── Contract summary ─────────────────────────────────────────────
        contract_label = (
            options_data.get("contract_label")
            or f"${options_data.get('strike', '?')}"
               f"{'C' if str(options_data.get('contract_type', '')).upper().startswith('C') else 'P'}"
        )
        dte   = options_data.get("dte", 0)
        delta = options_data.get("delta", 0)
        theta = options_data.get("theta", 0)
        iv    = options_data.get("iv", 0)

        fields.append({
            "name": "📋 Recommended Option",
            "value": (
                f"`{contract_label}`\n"
                f"DTE: **{dte}**  |  \u0394 {delta:+.2f}  |  "
                f"\u03b8 {theta:.3f}  |  IV: {iv*100:.0f}%"
            ),
            "inline": False
        })

        # ── Limit price entry range ────────────────────────────────────────
        bid         = options_data.get("bid", 0)
        ask         = options_data.get("ask", 0)
        mid         = options_data.get("mid") or (round((bid + ask) / 2, 2) if bid and ask else 0)
        limit_entry = options_data.get("limit_entry", mid)
        max_entry   = options_data.get("max_entry", ask)
        spread_pct  = options_data.get("spread_pct", 0)

        if ask > 0 and bid > 0:
            spread_emoji = "\u2705" if spread_pct < 5 else ("\u26a0\ufe0f" if spread_pct < 10 else "\ud83d\udea8")
            fields.append({
                "name": "💲 Limit Entry",
                "value": (
                    f"**Place: ${limit_entry:.2f}**  \u2192  Max: **${max_entry:.2f}**\n"
                    f"Bid: ${bid:.2f}  |  Ask: ${ask:.2f}  |  "
                    f"Spread: {spread_pct:.1f}% {spread_emoji}"
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
        "title": f"\u2702\ufe0f SCALING OUT: {ticker}",
        "color": 0xFFA500,  # Orange
        "description": (
            f"**Target 1** hit at **${price:.2f}**\n"
            f"Sold **{contracts_closed} contract(s)** \u2014 "
            f"**{contracts_remaining} contract(s)** still running for T2."
        ),
        "fields": [
            {"name": "💰 Partial P&L",   "value": f"${partial_pnl:+.2f}",          "inline": True},
            {"name": "🛡\ufe0f New Stop",      "value": f"${breakeven_price:.2f} (BE)",   "inline": True},
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
    """Alert for full position close \u2014 stop, T2, or EOD."""
    win = total_pnl > 0
    emoji = "\u2705" if win else "\u274c"
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
        pmis = score.get("pmis", "\u2014")
        gap = score.get("gap_pct", None)
        line = f"**{t}**"
        if gap is not None:
            line += f"  {gap:+.1f}%"
        if pmis != "\u2014":
            line += f"  PMIS: {pmis}"
        ticker_lines.append(line)

    chunk_size = 20
    chunks = [ticker_lines[i:i + chunk_size] for i in range(0, len(ticker_lines), chunk_size)]

    for idx, chunk in enumerate(chunks):
        embed = {
            "title": f"📋 Pre-Market Watchlist ({len(tickers)} tickers)" + (f" \u2014 Part {idx+1}" if len(chunks) > 1 else ""),
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
    emoji = "\U0001f7e2" if total_pnl >= 0 else "\U0001f534"

    embed = {
        "title": f"{emoji} Daily Summary \u2014 {datetime.now().strftime('%B %d, %Y')}",
        "color": color,
        "fields": [
            {"name": "📊 Total Trades", "value": str(trades),              "inline": True},
            {"name": "\u2705 Wins",          "value": str(wins),                "inline": True},
            {"name": "\u274c Losses",        "value": str(losses),              "inline": True},
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
    """Shared HTTP helper \u2014 all functions route through here."""
    # Strip any invisible whitespace/newlines from URL (Railway injection bug)
    webhook_url = (config.DISCORD_WEBHOOK_URL or "").strip().rstrip("\n").rstrip("\r")

    if not webhook_url:
        print("[DISCORD] \u274c No webhook URL configured.")
        return

    print(f"[DISCORD] Sending to: {webhook_url[:60]}...")

    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10
        )
        print(f"[DISCORD] Response: {response.status_code}")
        if response.status_code not in (200, 204):
            print(f"[DISCORD] Body: {response.text[:200]}")
        response.raise_for_status()
    except Exception as e:
        print(f"[DISCORD] Error: {e}")

def test_webhook():
    """Call once at startup to verify Discord is working."""
    webhook_url = (config.DISCORD_WEBHOOK_URL or "").strip()
    if not webhook_url:
        print("[DISCORD] \u274c DISCORD_WEBHOOK_URL is empty!")
        return False

    # Show exactly what URL we have (check for hidden characters)
    print(f"[DISCORD] URL length: {len(webhook_url)} chars")
    print(f"[DISCORD] URL ends with: {repr(webhook_url[-10:])}")  # Shows hidden chars

    try:
        r = requests.post(webhook_url, json={"content": "\U0001f680 War Machine Online!"}, timeout=10)
        print(f"[DISCORD] Test result: {r.status_code}")
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[DISCORD] Test failed: {e}")
        return False
