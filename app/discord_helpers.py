"""
Discord Helpers - Alert Functions for War Machine
Handles all Discord webhook notifications.
"""
import requests
from typing import Dict, Optional
from datetime import datetime
from utils import config


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
    options_data: Optional[Dict] = None,
    confirmation: Optional[str] = None,
    candle_type: Optional[str] = None,
    greeks_data: Optional[Dict] = None,
    # NEW: Performance metrics
    rvol: Optional[float] = None,
    volume_rank: Optional[int] = None,
    composite_score: Optional[float] = None,
    mtf_convergence: Optional[int] = None,
    explosive_mover: bool = False
):
    """Send enhanced Discord alert with options signal (ENHANCED v2)."""
    # Determine option type (CALL/PUT)
    option_type = "CALL" if direction == "bull" else "PUT"
    color = 0x00FF00 if direction == "bull" else 0xFF0000  # Green for CALL, Red for PUT
    
    # Grade emoji
    grade_emoji = {
        "A+": "🟢",
        "A": "🟡", 
        "B": "🟠",
        "C": "🔴"
    }.get(grade, "⚪")
    
    # Build title with badges
    title_parts = [f"{ticker} {option_type}"]
    
    # Add explosive mover badge
    if explosive_mover:
        title_parts.append("🚀")
    
    # Add MTF convergence badge
    if mtf_convergence and mtf_convergence >= 3:
        title_parts.append(f"⚡{mtf_convergence}TF")
    
    title = " ".join(title_parts)
    
    # Calculate risk:reward
    risk = abs(entry - stop)
    reward_t1 = abs(t1 - entry)
    reward_t2 = abs(t2 - entry)
    rr_t1 = round(reward_t1 / risk, 2) if risk > 0 else 0
    rr_t2 = round(reward_t2 / risk, 2) if risk > 0 else 0
    
    # Build fields
    fields = []
    
    # ══ SIGNAL QUALITY ══════════════════════════════════════════════════
    quality_parts = []
    
    # Confidence bar
    conf_pct = confidence * 100
    conf_bars = "█" * int(conf_pct / 10)
    quality_parts.append(f"**{conf_pct:.0f}%** {conf_bars}")
    
    # Grade with explosive badge
    if explosive_mover:
        quality_parts.append(f"{grade_emoji} **{grade}** 🚀")
    else:
        quality_parts.append(f"{grade_emoji} **{grade}**")
    
    # RVOL indicator (enhanced)
    if rvol:
        if rvol >= 4.0:
            rvol_emoji = "🚀"  # Explosive tier
            rvol_label = "EXPLOSIVE"
        elif rvol >= 3.0:
            rvol_emoji = "🔥"  # Hot tier
            rvol_label = "HOT"
        elif rvol >= 2.0:
            rvol_emoji = "⚡"  # Active tier
            rvol_label = "ACTIVE"
        else:
            rvol_emoji = "📊"  # Normal tier
            rvol_label = "NORMAL"
        quality_parts.append(f"{rvol_emoji} **{rvol:.1f}x** {rvol_label}")
    
    # Composite score with tier classification
    if composite_score:
        if composite_score >= 90:
            score_tier = "S-TIER"
        elif composite_score >= 80:
            score_tier = "A-TIER"
        elif composite_score >= 70:
            score_tier = "B-TIER"
        else:
            score_tier = "C-TIER"
        quality_parts.append(f"📈 **{composite_score:.0f}** ({score_tier})")
    
    # Volume rank (if provided)
    if volume_rank:
        quality_parts.append(f"🏆 **#{volume_rank}** rank")
    
    fields.append({
        "name": "📊 Signal Quality",
        "value": " | ".join(quality_parts),
        "inline": False
    })

    
    # ══ ENTRY & TARGETS ═════════════════════════════════════════════════
    fields.append({
        "name": "🔥 Entry",
        "value": f"**${entry:.2f}**",
        "inline": True
    })
    
    fields.append({
        "name": "🛑 Stop Loss",
        "value": f"${stop:.2f}",
        "inline": True
    })
    
    fields.append({
        "name": "📏 Risk",
        "value": f"${risk:.2f}",
        "inline": True
    })
    
    fields.append({
        "name": "🎯 T1 (50%)",
        "value": f"${t1:.2f} (**{rr_t1:.1f}R**)",
        "inline": True
    })
    
    fields.append({
        "name": "🎯 T2 (50%)",
        "value": f"${t2:.2f} (**{rr_t2:.1f}R**)",
        "inline": True
    })
    
    fields.append({
        "name": "💰 Max Gain",
        "value": f"**{(rr_t1 + rr_t2) / 2:.1f}R**",
        "inline": True
    })
    
    # ══ CONFIRMATION ════════════════════════════════════════════════════
    if confirmation or mtf_convergence:
        conf_parts = []
        
        if confirmation:
            conf_emoji_map = {
                "A+": "🟢",
                "A": "🟡",
                "A-": "🟠"
            }
            conf_parts.append(f"{conf_emoji_map.get(confirmation, '⚪')} **{confirmation}** {candle_type or 'Pattern'}")
        
        if mtf_convergence:
            if mtf_convergence >= 4:
                mtf_emoji = "🌟"  # 4+ timeframes
                mtf_label = "ULTRA-CONVERGENCE"
            elif mtf_convergence >= 3:
                mtf_emoji = "⚡⚡"  # 3 timeframes
                mtf_label = "STRONG"
            elif mtf_convergence >= 2:
                mtf_emoji = "⚡"  # 2 timeframes
                mtf_label = "MODERATE"
            else:
                mtf_emoji = "📊"  # 1 timeframe
                mtf_label = "SINGLE"
            conf_parts.append(f"{mtf_emoji} **{mtf_convergence} TF** {mtf_label}")
        
        fields.append({
            "name": "✅ Confirmation",
            "value": " | ".join(conf_parts),
            "inline": False
        })
    
    # ══ GREEKS QUALITY ══════════════════════════════════════════════════
    if greeks_data:
        greeks_details = greeks_data.get("details", {})
        if greeks_details:
            delta = greeks_details.get("delta", 0)
            iv = greeks_details.get("iv", 0)
            dte = greeks_details.get("dte", 0)
            spread = greeks_details.get("spread_pct", 0)
            liquidity = greeks_details.get("liquidity_ok", False)
            
            # Quality checks
            delta_check = "✅" if abs(delta) >= 0.30 else "⚠️"
            iv_check = "✅" if iv < 0.60 else "⚠️"
            spread_check = "✅" if spread < 5 else "⚠️"
            liq_check = "✅" if liquidity else "❌"
            
            # Delta color indicator
            abs_delta = abs(delta)
            if abs_delta >= 0.50:
                delta_emoji = "🟢"  # ATM/ITM
            elif abs_delta >= 0.35:
                delta_emoji = "🟡"  # Slightly OTM
            else:
                delta_emoji = "🟠"  # Further OTM
            
            greeks_summary = (
                f"{delta_emoji} Δ **{abs_delta:.2f}** {delta_check} | "
                f"IV **{iv*100:.0f}%** {iv_check} | "
                f"**{dte}DTE**\n"
                f"Spread **{spread:.1f}%** {spread_check} | "
                f"Liquidity {liq_check}"
            )
            
            fields.append({
                "name": "🎲 Greeks Quality",
                "value": greeks_summary,
                "inline": False
            })
    
    # ══ RECOMMENDED OPTION ══════════════════════════════════════════════
    if options_data:
        strike = options_data.get('strike')
        dte = options_data.get('dte', 0)
        delta = options_data.get('delta', 0)
        iv = options_data.get('iv', 0)
        
        option_summary = (
            f"**{option_type}** @ **${strike}**\n"
            f"Δ={abs(delta):.2f} | IV={iv*100:.0f}% | {dte}DTE"
        )
        
        fields.append({
            "name": "📋 Recommended Contract",
            "value": option_summary,
            "inline": False
        })
        
        # Limit entry with bid/ask
        bid = options_data.get("bid", 0)
        ask = options_data.get("ask", 0)
        mid = options_data.get("mid") or (round((bid + ask) / 2, 2) if bid and ask else 0)
        limit_entry = options_data.get("limit_entry", mid)
        max_entry = options_data.get("max_entry", ask)
        spread_pct = options_data.get("spread_pct", 0)
        
        if ask > 0 and bid > 0:
            spread_emoji = "✅" if spread_pct < 5 else "⚠️"
            entry_summary = (
                f"**Place: ${limit_entry:.2f}** — Max: **${max_entry:.2f}**\n"
                f"Bid: ${bid:.2f} | Ask: ${ask:.2f} | Spread: {spread_pct:.1f}% {spread_emoji}"
            )
            
            fields.append({
                "name": "💲 Limit Entry",
                "value": entry_summary,
                "inline": False
            })
    
    # Build embed
    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"War Machine Sniper v2 | {datetime.now().strftime('%Y-%m-%d %I:%M %p EST')}"
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
    # Strip any invisible whitespace/newlines from URL (Railway injection bug)
    webhook_url = (config.DISCORD_WEBHOOK_URL or "").strip().rstrip("\n").rstrip("\r")

    if not webhook_url:
        print("[DISCORD] ❌ No webhook URL configured.")
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
        print("[DISCORD] ❌ DISCORD_WEBHOOK_URL is empty!")
        return False

    # Show exactly what URL we have (check for hidden characters)
    print(f"[DISCORD] URL length: {len(webhook_url)} chars")
    print(f"[DISCORD] URL ends with: {repr(webhook_url[-10:])}")  # Shows hidden chars

    try:
        r = requests.post(webhook_url, json={"content": "🚀 War Machine Online!"}, timeout=10)
        print(f"[DISCORD] Test result: {r.status_code}")
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[DISCORD] Test failed: {e}")
        return False
