"""
earnings_eve_monitor.py
Runs at 3:30 PM ET daily. Scans watchlist for tickers reporting
after close tonight and sends a Discord alert with IV rank,
expected move, and options skew.
"""

import os
import logging
import requests
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_EARNINGS_EVE")
UNUSUAL_WHALES_KEY  = os.getenv("UNUSUAL_WHALES_API_KEY")
TRADIER_TOKEN       = os.getenv("TRADIER_API_TOKEN")
TRADIER_BASE        = "https://api.tradier.com/v1"

ALERT_TIME_ET = (15, 30)   # 3:30 PM — run once daily


# ─────────────────────────────────────────────
#  Data Fetchers
# ─────────────────────────────────────────────

def get_earnings_tonight(tickers: list[str]) -> list[str]:
    """
    Returns tickers from the list reporting after close today.
    Uses Unusual Whales earnings calendar endpoint.
    """
    today = date.today().isoformat()
    reporting = []

    for ticker in tickers:
        try:
            url = f"https://api.unusualwhales.com/api/earnings/{ticker}"
            headers = {"Authorization": f"Bearer {UNUSUAL_WHALES_KEY}"}
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code != 200:
                continue
            data = r.json().get("data", {})
            report_date = data.get("date", "")
            timing      = data.get("timing", "").lower()  # 'after_close' | 'before_open'
            if report_date == today and "after" in timing:
                reporting.append(ticker)
                logger.info(f"[EVE] {ticker} reports after close tonight")
        except Exception as e:
            logger.warning(f"[EVE] Earnings fetch failed for {ticker}: {e}")

    return reporting


def get_options_metrics(ticker: str) -> Optional[dict]:
    """
    Fetches IV rank, expected move, and call/put skew from Tradier.
    Returns None if data unavailable.
    """
    try:
        # Get IV / greeks via Tradier options chain
        url = f"{TRADIER_BASE}/markets/options/strikes"
        headers = {
            "Authorization": f"Bearer {TRADIER_TOKEN}",
            "Accept": "application/json"
        }
        # Nearest expiry
        exp_url = f"{TRADIER_BASE}/markets/options/expirations"
        exp_r = requests.get(exp_url, headers=headers,
                             params={"symbol": ticker}, timeout=5)
        expirations = exp_r.json().get("expirations", {}).get("date", [])
        if not expirations:
            return None
        nearest_exp = expirations[0]

        # Full chain for nearest expiry
        chain_url = f"{TRADIER_BASE}/markets/options/chains"
        chain_r = requests.get(chain_url, headers=headers,
                               params={"symbol": ticker,
                                       "expiration": nearest_exp,
                                       "greeks": "true"}, timeout=8)
        options = chain_r.json().get("options", {}).get("option", [])
        if not options:
            return None

        # Get current stock price
        quote_r = requests.get(
            f"{TRADIER_BASE}/markets/quotes",
            headers=headers,
            params={"symbols": ticker},
            timeout=5
        )
        price = quote_r.json()["quotes"]["quote"]["last"]

        # Find ATM options
        calls = [o for o in options if o["option_type"] == "call"]
        puts  = [o for o in options if o["option_type"] == "put"]

        atm_call = min(calls, key=lambda o: abs(o["strike"] - price), default=None)
        atm_put  = min(puts,  key=lambda o: abs(o["strike"] - price), default=None)

        if not atm_call or not atm_put:
            return None

        atm_iv      = (atm_call["greeks"]["mid_iv"] + atm_put["greeks"]["mid_iv"]) / 2
        call_volume = sum(o.get("volume", 0) for o in calls)
        put_volume  = sum(o.get("volume", 0) for o in puts)
        cp_ratio    = round(call_volume / put_volume, 2) if put_volume > 0 else 0

        # Expected move = ATM straddle price (call ask + put ask)
        expected_move     = round(atm_call["ask"] + atm_put["ask"], 2)
        expected_move_pct = round((expected_move / price) * 100, 1)

        return {
            "price":              round(price, 2),
            "atm_iv":             round(atm_iv * 100, 1),   # as percentage
            "expected_move":      expected_move,
            "expected_move_pct":  expected_move_pct,
            "call_put_ratio":     cp_ratio,
            "call_volume":        call_volume,
            "put_volume":         put_volume,
            "expiry":             nearest_exp,
        }

    except Exception as e:
        logger.warning(f"[EVE] Options fetch failed for {ticker}: {e}")
        return None


# ─────────────────────────────────────────────
#  Discord Alert
# ─────────────────────────────────────────────

def send_eve_alert(ticker: str, metrics: Optional[dict]):
    """Sends a pre-earnings Discord alert."""
    if metrics:
        skew = "🟢 Bullish" if metrics["call_put_ratio"] > 1.2 \
               else "🔴 Bearish" if metrics["call_put_ratio"] < 0.8 \
               else "⚪ Neutral"

        description = (
            f"**Price:** ${metrics['price']}\n"
            f"**ATM IV:** {metrics['atm_iv']}%\n"
            f"**Expected Move:** ±${metrics['expected_move']} "
            f"({metrics['expected_move_pct']}%)\n"
            f"**Options Skew:** {skew} "
            f"(C/P ratio = {metrics['call_put_ratio']})\n"
            f"**Call Vol:** {metrics['call_volume']:,} | "
            f"**Put Vol:** {metrics['put_volume']:,}\n"
            f"**Nearest Expiry:** {metrics['expiry']}"
        )
    else:
        description = "⚠️ Options data unavailable — monitor manually."

    payload = {
        "embeds": [{
            "title":       f"📅 EARNINGS TONIGHT: {ticker}",
            "description": description,
            "color":       0xF4A261,   # orange
            "footer":      {"text": "War Machine • Earnings Eve Monitor"},
            "timestamp":   datetime.utcnow().isoformat(),
        }]
    }

    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        r.raise_for_status()
        logger.info(f"[EVE] Discord alert sent for {ticker}")
    except Exception as e:
        logger.error(f"[EVE] Discord send failed for {ticker}: {e}")


# ─────────────────────────────────────────────
#  Main Entry
# ─────────────────────────────────────────────

def run_earnings_eve_scan(universe: list[str]):
    """
    Call this once at 3:30 PM ET.
    universe = your full ticker universe (not just watchlist).
    """
    now = datetime.now()
    logger.info(f"[EVE] Running earnings eve scan at {now.strftime('%H:%M')} ET")

    reporting_tonight = get_earnings_tonight(universe)

    if not reporting_tonight:
        logger.info("[EVE] No tickers reporting after close tonight.")
        return

    logger.info(f"[EVE] {len(reporting_tonight)} ticker(s) reporting tonight: {reporting_tonight}")

    for ticker in reporting_tonight:
        metrics = get_options_metrics(ticker)
        send_eve_alert(ticker, metrics)
