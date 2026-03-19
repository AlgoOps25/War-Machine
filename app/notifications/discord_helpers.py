"""
Discord Helpers - Enhanced Alert Functions for War Machine
Handles all Discord webhook notifications with rich formatting.

ENHANCEMENTS:
- Company name resolution (yfinance integration)
- Consolidated CALL/PUT formatting (green/red embeds)
- All signal fields exposed (FVG, BOS, MTF, RVOL, greeks)
- Clean, easy-to-read layout
- ML score delta line: 📈 +9pts (68%→77%) shown when |adjustment| >= 1pt

M10 FIX (Mar 10 2026):
- _send_to_discord() now dispatches the HTTP POST on a daemon Thread.
  A webhook outage or high latency can no longer stall the scan loop.
  Errors are caught and logged inside the thread; the caller always
  returns immediately.

PHASE 1.29 (Mar 16 2026):
- send_premarket_watchlist() now posts to DISCORD_WATCHLIST_WEBHOOK_URL
  (separate #watchlist channel) with a rich embed per stage showing
  rank, score, RVOL, gap, catalyst, and price for each ticker.
- Falls back to DISCORD_SIGNALS_WEBHOOK_URL if watchlist URL not set.

VP BIAS (Mar 19 2026):
- send_options_signal_alert() accepts vp_bias param (CALL/PUT/NEUTRAL/AVOID).
  Shown as a VP Bias line in Signal Quality field with emoji indicator.
"""
import requests
import functools
import threading
from typing import Dict, List, Optional
from datetime import datetime
from utils import config

# ══════════════════════════════════════════════════════════════════════════════
# COMPANY NAME RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("[DISCORD] ⚠️  yfinance not installed - company names will show as ticker only")

@functools.lru_cache(maxsize=512)
def get_company_name(symbol: str) -> str:
    """Resolve ticker to company name. Cached to avoid repeated API calls."""
    if not YFINANCE_AVAILABLE:
        return symbol
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        return info.get("longName") or info.get("shortName") or symbol
    except Exception:
        return symbol


# ══════════════════════════════════════════════════════════════════════════════
# EQUITY BOS/FVG SIGNAL ALERT (War Machine Core Scanner)
# ══════════════════════════════════════════════════════════════════════════════
def send_equity_bos_fvg_alert(signal: Dict):
    """
    Rich BOS/FVG equity signal alert with company name and all available fields.
    
    Expected signal dict keys:
      - ticker, direction, entry_price, stop_price, target_1, target_2
      - confirmation_grade, confirmation_score
      - fvg_low, fvg_high, fvg_size_pct
      - bos_strength (optional)
      - timestamp
      - candle_type (optional)
      - mtf_convergence (optional)
      - rvol, volume_rank, gap_pct (optional)
      - vix (optional)
    """
    ticker = signal.get("ticker", "UNKNOWN")
    direction = signal.get("direction", "bull").lower()
    
    # CALL/PUT terminology
    side = "CALL" if direction == "bull" else "PUT"
    color = 0x00FF00 if direction == "bull" else 0xFF0000  # Green for CALL, Red for PUT
    
    # Get company name
    company_name = get_company_name(ticker)
    title = f"{ticker} - {company_name} {side} SIGNAL"
    
    # Core prices
    entry = signal.get("entry_price", 0)
    stop = signal.get("stop_price", 0)
    t1 = signal.get("target_1", 0)
    t2 = signal.get("target_2", 0)
    
    # Calculate R multiples
    risk = abs(entry - stop) if stop else 0
    r1 = abs(t1 - entry) / risk if risk > 0 else 0
    r2 = abs(t2 - entry) / risk if risk > 0 else 0
    avg_r = (r1 + r2) / 2 if risk > 0 else 0
    
    # Grade/score
    grade = signal.get("confirmation_grade", "N/A")
    score = signal.get("confirmation_score", 0)
    
    # FVG
    fvg_low = signal.get("fvg_low", 0)
    fvg_high = signal.get("fvg_high", 0)
    fvg_pct = signal.get("fvg_size_pct", 0)
    
    # BOS
    bos_strength = signal.get("bos_strength", 0) * 100  # Convert to percentage
    
    # Context
    timestamp = signal.get("timestamp", datetime.now())
    candle_type = signal.get("candle_type")
    mtf = signal.get("mtf_convergence")
    rvol = signal.get("rvol")
    volume_rank = signal.get("volume_rank")
    gap_pct = signal.get("gap_pct")
    vix = signal.get("vix")
    
    # Build header line
    header_parts = [f"Grade: **{grade}**", f"Score: **{score:.0f}**"]
    if gap_pct is not None:
        header_parts.append(f"Gap: **{gap_pct:+.1f}%**")
    if isinstance(timestamp, str):
        header_parts.append(f"Time: **{timestamp}**")
    else:
        header_parts.append(f"Time: **{timestamp.strftime('%Y-%m-%d %H:%M:%S')}**")
    
    description = "  •  ".join(header_parts)
    
    fields = []
    
    # 1) Price Levels & R/R
    fields.append({
        "name": "Price Levels",
        "value": (
            f"Entry: **${entry:.2f}**\n"
            f"Stop: **${stop:.2f}**  (Risk **${risk:.2f}**)\n"
            f"T1: **${t1:.2f}**  ({r1:.1f}R)\n"
            f"T2: **${t2:.2f}**  ({r2:.1f}R)\n"
            f"Max Reward (avg): **{avg_r:.1f}R**"
        ),
        "inline": False,
    })
    
    # 2) BOS / FVG
    fields.append({
        "name": "Structure",
        "value": (
            f"FVG: **${fvg_low:.2f} - ${fvg_high:.2f}**  "
            f"(*{fvg_pct:.2f}% range*)\n"
            f"BOS Strength: **{bos_strength:.2f}%**"
        ),
        "inline": False,
    })
    
    # 3) Market Context (RVOL, VIX, Rank)
    context_bits = []
    if rvol is not None:
        tier = "EXPLOSIVE 🚀" if rvol >= 4 else "HOT 🔥" if rvol >= 3 else "ACTIVE ⚡" if rvol >= 2 else "NORMAL"
        context_bits.append(f"RVOL: **{rvol:.1f}x** ({tier})")
    if vix is not None:
        context_bits.append(f"VIX: **{vix:.2f}**")
    if volume_rank is not None:
        context_bits.append(f"Volume Rank: **#{volume_rank}**")
    
    if context_bits:
        fields.append({
            "name": "Market Context",
            "value": "  •  ".join(context_bits),
            "inline": False,
        })
    
    # 4) Confirmation (pattern + MTF)
    conf_bits = []
    if candle_type:
        conf_bits.append(f"Pattern: **{candle_type}**")
    if mtf:
        if mtf >= 4:
            mtf_label = "Ultra-confluence 🌟"
        elif mtf == 3:
            mtf_label = "Strong ⚡⚡"
        elif mtf == 2:
            mtf_label = "Moderate ⚡"
        else:
            mtf_label = "Single TF"
        conf_bits.append(f"MTF: **{mtf} TF** ({mtf_label})")
    
    if conf_bits:
        fields.append({
            "name": "Confirmation",
            "value": "  •  ".join(conf_bits),
            "inline": False,
        })
    
    # Build embed
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"War Machine BOS/FVG | {datetime.now().strftime('%Y-%m-%d %I:%M %p EST')}",
        },
    }
    
    _send_to_discord({"embeds": [embed]})


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONS SIGNAL ALERT (0DTE / Short-term options plays)
# ══════════════════════════════════════════════════════════════════════════════

# VP bias emoji map
_VP_BIAS_EMOJI = {
    'CALL':    '📗',
    'PUT':     '📕',
    'NEUTRAL': '📓',
    'AVOID':   '🚫',
}

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
    rvol: Optional[float] = None,
    volume_rank: Optional[int] = None,
    composite_score: Optional[float] = None,
    mtf_convergence: Optional[int] = None,
    explosive_mover: bool = False,
    ml_adjustment: Optional[float] = None,
    vp_bias: Optional[str] = None,
):
    """
    Options signal alert with CALL/PUT formatting (green/red border).
    Consolidated, easy-to-read layout.

    ml_adjustment: float in pts (e.g. +9.0 or -5.0).  When |adjustment| >= 1pt,
    a ML Score line is appended showing the direction arrow and base→adjusted conf.

    vp_bias: Volume Profile options bias — 'CALL' | 'PUT' | 'NEUTRAL' | 'AVOID'.
    Shown in Signal Quality field with emoji indicator.
    """
    # CALL / PUT and colors
    option_side = "CALL" if direction.lower() == "bull" else "PUT"
    is_call = option_side == "CALL"
    color = 0x00FF00 if is_call else 0xFF0000
    
    # Get company name
    company_name = get_company_name(ticker)
    title = f"{ticker} - {company_name} {option_side} SIGNAL"
    
    # R/R
    risk = abs(entry - stop)
    r1 = abs(t1 - entry) / risk if risk > 0 else 0
    r2 = abs(t2 - entry) / risk if risk > 0 else 0
    avg_r = (r1 + r2) / 2 if risk > 0 else 0
    
    # Header
    conf_pct = confidence * 100
    header_line = f"**{conf_pct:.0f}%** confidence  •  Grade **{grade}**  •  Score **{(composite_score or conf_pct):.0f}**  •  TF **{timeframe}**"
    
    # Append ML delta to header when significant
    if ml_adjustment is not None and abs(ml_adjustment) >= 1.0:
        base_conf_pct = conf_pct - ml_adjustment
        arrow = '📈' if ml_adjustment > 0 else '📉'
        header_line += (
            f"\nML Score   : {arrow} **{ml_adjustment:+.1f}pts**  "
            f"({base_conf_pct:.0f}% → {conf_pct:.0f}%)"
        )

    fields = []
    
    # 1) Signal Quality
    quality_bits = []
    if rvol is not None:
        if rvol >= 4.0:
            tier = "EXPLOSIVE"
        elif rvol >= 3.0:
            tier = "HOT"
        elif rvol >= 2.0:
            tier = "ACTIVE"
        else:
            tier = "NORMAL"
        quality_bits.append(f"RVOL **{rvol:.1f}x** ({tier})")
    if volume_rank is not None:
        quality_bits.append(f"Volume Rank **#{volume_rank}**")
    if mtf_convergence is not None:
        if mtf_convergence >= 4:
            mtf_label = "Ultra-confluence"
        elif mtf_convergence == 3:
            mtf_label = "Strong"
        elif mtf_convergence == 2:
            mtf_label = "Moderate"
        else:
            mtf_label = "Single TF"
        quality_bits.append(f"MTF **{mtf_convergence} TF** ({mtf_label})")
    if vp_bias and vp_bias != 'NEUTRAL':
        vp_emoji = _VP_BIAS_EMOJI.get(vp_bias, '📓')
        quality_bits.append(f"VP Bias {vp_emoji} **{vp_bias}**")
    
    if quality_bits:
        fields.append({
            "name": "Signal Quality",
            "value": " • ".join(quality_bits),
            "inline": False,
        })
    
    # 2) Price & Risk
    fields.append({
        "name": "Price & Risk",
        "value": (
            f"Entry: **${entry:.2f}**\n"
            f"Stop: **${stop:.2f}**  (Risk **${risk:.2f}**)\n"
            f"T1: **${t1:.2f}**  ({r1:.1f}R)\n"
            f"T2: **${t2:.2f}**  ({r2:.1f}R)\n"
            f"Max Reward (avg): **{avg_r:.1f}R**"
        ),
        "inline": False,
    })
    
    # 3) Confirmation
    conf_bits = []
    if confirmation:
        conf_bits.append(f"Pattern: **{confirmation}** ({candle_type or 'Price Action'})")
    if mtf_convergence:
        conf_bits.append(f"Aligned TFs: **{mtf_convergence}**")
    if conf_bits:
        fields.append({
            "name": "Confirmation",
            "value": " • ".join(conf_bits),
            "inline": False,
        })
    
    # 4) Greeks Summary
    if greeks_data and greeks_data.get("details"):
        g = greeks_data["details"]
        delta = abs(g.get("delta", 0.0))
        iv = g.get("iv", 0.0)
        dte = g.get("dte", 0)
        spread = g.get("spread_pct", 0.0)
        liq_ok = g.get("liquidity_ok", False)
        
        fields.append({
            "name": "Greeks Snapshot",
            "value": (
                f"Δ **{delta:.2f}**  •  IV **{iv*100:.0f}%**  •  **{dte} DTE**\n"
                f"Spread **{spread:.1f}%**  •  Liquidity **{'OK' if liq_ok else 'Thin'}**"
            ),
            "inline": False,
        })
    
    # 5) Recommended Contract
    if options_data:
        strike = options_data.get("strike")
        dte = options_data.get("dte", 0)
        delta = abs(options_data.get("delta", 0.0))
        iv = options_data.get("iv", 0.0)
        bid = options_data.get("bid", 0.0)
        ask = options_data.get("ask", 0.0)
        spread_pct = options_data.get("spread_pct", 0.0)
        
        mid = options_data.get("mid")
        if not mid and bid and ask:
            mid = round((bid + ask) / 2, 2)
        limit_entry = options_data.get("limit_entry", mid or 0)
        max_entry = options_data.get("max_entry", ask or 0)
        
        fields.append({
            "name": "Recommended Contract [est — pre-confirmation]",
            "value": (
                f"**{option_side}** @ **${strike}**\n"
                f"{dte} DTE  •  Δ **{delta:.2f}**  •  IV **{iv*100:.0f}%**"
            ),
            "inline": False,
        })
        
        if bid and ask:
            fields.append({
                "name": "Option Entry",
                "value": (
                    f"Limit: **${limit_entry:.2f}**  (Max **${max_entry:.2f}**)\n"
                    f"Bid ${bid:.2f}  •  Ask ${ask:.2f}  •  Spread {spread_pct:.1f}%"
                ),
                "inline": False,
            })
    
    embed = {
        "title": title,
        "description": header_line,
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"War Machine Sniper v2 | {datetime.now().strftime('%Y-%m-%d %I:%M %p EST')}",
        },
    }
    
    _send_to_discord({"embeds": [embed]})


# ══════════════════════════════════════════════════════════════════════════════
# REMAINING ALERT FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

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
        "color": 0xFFA500,
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


def send_premarket_watchlist(
    tickers: List[str],
    scored_tickers: Optional[List[Dict]] = None,
    stage: str = "wide"
):
    """
    PHASE 1.29: Send watchlist to the dedicated #watchlist Discord channel.

    Posts a rich embed with rank, score, RVOL, gap, catalyst, and price
    for each ticker in the current funnel stage.

    Falls back to DISCORD_SIGNALS_WEBHOOK_URL if DISCORD_WATCHLIST_WEBHOOK_URL
    is not configured.

    Args:
        tickers:        Ordered list of ticker symbols.
        scored_tickers: Full scored_tickers list from WatchlistFunnel
                        (contains score, rvol, gap_data, catalyst_data, price).
        stage:          Funnel stage label (wide / narrow / final / live).
    """
    if not tickers:
        return

    stage_labels = {
        "wide":   ("\ud83d\udd0d Wide Scan",    0x1E90FF),   # blue
        "narrow": ("\ud83c\udfaf Narrow",       0xFFA500),   # orange
        "final":  ("\ud83d\ude80 Final Top 3",  0xFF4500),   # red-orange
        "live":   ("\ud83d\udfe2 Live Session", 0x00C853),   # green
    }
    stage_label, color = stage_labels.get(stage, (f"Stage: {stage}", 0x888888))

    # Build a lookup from the scored_tickers list for fast access
    score_map: Dict[str, Dict] = {}
    if scored_tickers:
        for t in scored_tickers:
            score_map[t.get("ticker", "")] = t

    lines = []
    for i, ticker in enumerate(tickers, 1):
        data = score_map.get(ticker, {})
        score = data.get("composite_score", 0)
        rvol  = data.get("rvol", 0)
        price = data.get("price", 0)

        gap_data      = data.get("gap_data") or {}
        gap_pct       = gap_data.get("size_pct", None)
        catalyst_data = data.get("catalyst_data") or {}
        catalyst_type = catalyst_data.get("type", None)

        gap_str      = f"{gap_pct:+.1f}%" if gap_pct is not None else "—"
        catalyst_str = catalyst_type if catalyst_type else "—"
        rvol_str     = f"{rvol:.2f}x" if rvol else "—"
        price_str    = f"${price:.2f}" if price else "—"
        score_str    = f"{score:.1f}" if score else "—"

        lines.append(
            f"`#{i:>2}` **{ticker}**  │  Score: `{score_str}`  RVOL: `{rvol_str}`  "
            f"Gap: `{gap_str}`  Cat: `{catalyst_str}`  @ {price_str}"
        )

    # Discord embed description has a 4096-char limit; chunk if needed
    chunk_size = 15
    chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]

    for idx, chunk in enumerate(chunks):
        part_suffix = f" — Part {idx + 1}/{len(chunks)}" if len(chunks) > 1 else ""
        embed = {
            "title": f"📋 Watchlist — {stage_label}  ({len(tickers)} tickers){part_suffix}",
            "color": color,
            "description": "\n".join(chunk),
            "footer": {
                "text": (
                    f"War Machine  |  "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}"
                )
            },
        }
        _send_to_discord_watchlist({"embeds": [embed]})


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


def _send_to_discord_watchlist(payload: Dict):
    """
    PHASE 1.29: Send to the dedicated watchlist channel.
    Falls back to DISCORD_SIGNALS_WEBHOOK_URL if watchlist URL not configured.
    Dispatched on a daemon thread (non-blocking).
    """
    watchlist_url = (config.DISCORD_WATCHLIST_WEBHOOK_URL or "").strip().rstrip("\n").rstrip("\r")
    fallback_url  = (config.DISCORD_SIGNALS_WEBHOOK_URL  or "").strip().rstrip("\n").rstrip("\r")
    webhook_url   = watchlist_url or fallback_url

    if not webhook_url:
        print("[DISCORD] ❌ No watchlist webhook URL configured.")
        return

    if not watchlist_url:
        print("[DISCORD] ⚠️  DISCORD_WATCHLIST_WEBHOOK_URL not set — falling back to signals channel")

    def _post():
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code not in (200, 204):
                print(f"[DISCORD] ⚠️  Watchlist HTTP {response.status_code}: {response.text[:200]}")
        except Exception as e:
            print(f"[DISCORD] ⚠️  Watchlist send error (non-blocking): {e}")

    t = threading.Thread(target=_post, daemon=True)
    t.start()


def _send_to_discord(payload: Dict):
    """
    Shared HTTP helper — all functions route through here.

    M10 FIX: Dispatches the POST on a daemon Thread so webhook latency
    or outage never blocks the scan loop. The caller always returns
    immediately. Errors are caught and logged inside the thread.
    """
    webhook_url = (config.DISCORD_SIGNALS_WEBHOOK_URL or "").strip().rstrip("\n").rstrip("\r")

    if not webhook_url:
        print("[DISCORD] ❌ No webhook URL configured.")
        return

    def _post():
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=10,
            )
            if response.status_code not in (200, 204):
                print(f"[DISCORD] ⚠️  HTTP {response.status_code}: {response.text[:200]}")
        except Exception as e:
            print(f"[DISCORD] ⚠️  Send error (non-blocking): {e}")

    t = threading.Thread(target=_post, daemon=True)
    t.start()


def test_webhook():
    """Call once at startup to verify Discord is working."""
    webhook_url = (config.DISCORD_SIGNALS_WEBHOOK_URL or "").strip()
    if not webhook_url:
        print("[DISCORD] ❌ DISCORD_SIGNALS_WEBHOOK_URL is empty!")
        return False
    
    print(f"[DISCORD] URL length: {len(webhook_url)} chars")
    print(f"[DISCORD] URL ends with: {repr(webhook_url[-10:])}")
    
    try:
        r = requests.post(webhook_url, json={"content": "🚀 War Machine Online!"}, timeout=10)
        print(f"[DISCORD] Test result: {r.status_code}")
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[DISCORD] Test failed: {e}")
        return False
