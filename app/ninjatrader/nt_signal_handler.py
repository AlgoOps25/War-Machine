"""
app/ninjatrader/nt_signal_handler.py

Routes actionable NTSignal objects from the NTBridge into the War Machine
signal pipeline: risk gate → options gate → Discord alert.

Design principles:
  - Fully crash-isolated: any exception logs a warning and returns False.
    A bad NTSignal must never disrupt the equity/options scan loop.
  - Stateless: no class, no global mutable state. One function per concern.
  - Opt-in gates: each downstream gate is guarded by its own try/except so
    a missing module (options, validation) degrades gracefully.

Feature NT-5 (2026-04-08):
  NT-5: process_nt_signal() implemented. Consumer thread in scanner.py now
  calls this instead of logging only. Routes: risk gate → options gate →
  Discord alert with structured embed.
"""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from app.ninjatrader.nt_bridge import NTSignal, Direction

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Minimum confidence to forward signal downstream.
# Divergence signals (0.85) always clear this. Agreement signals (0.70)
# also clear it. Reduce to 0.60 to let inside-VA signals through.
_MIN_CONFIDENCE: float = float(os.getenv("NT_MIN_CONFIDENCE", "0.65"))


def process_nt_signal(signal: NTSignal) -> bool:
    """
    Route an actionable NTSignal through the War Machine pipeline.

    Steps:
        1. Confidence gate — drop low-quality signals early.
        2. Risk gate — halt if daily circuit breaker is tripped.
        3. Options gate — attach options context if available.
        4. Discord alert — send structured notification.

    Args:
        signal: An NTSignal with direction BUY or SELL.

    Returns:
        True if the signal was successfully forwarded.
        False if dropped by any gate or if an exception occurred.
    """
    if not signal.is_actionable():
        return False

    bar = signal.bar

    try:
        # ── 1. Confidence gate ───────────────────────────────────────────
        if signal.confidence < _MIN_CONFIDENCE:
            logger.debug(
                "[NT-SIGNAL] %s dropped — confidence %.2f < threshold %.2f",
                signal.direction.value, signal.confidence, _MIN_CONFIDENCE,
            )
            return False

        # ── 2. Risk gate ─────────────────────────────────────────────────
        # Respect the same daily circuit breaker used by the equity scanner.
        try:
            from app.risk.position_manager import position_manager as _pm
            if _pm.has_loss_streak(max_consecutive_losses=3):
                logger.warning(
                    "[NT-SIGNAL] %s blocked — daily circuit breaker active",
                    signal.direction.value,
                )
                return False
        except Exception as e:
            logger.warning("[NT-SIGNAL] Risk gate unavailable (%s) — proceeding", e)

        # ── 3. Options gate ──────────────────────────────────────────────
        options_context: dict = {}
        try:
            from app.options import build_options_trade
            # NQ futures signals map to QQQ options as the closest liquid proxy.
            options_ticker = _futures_to_options_proxy(bar.symbol)
            if options_ticker:
                options_context = build_options_trade(
                    ticker    = options_ticker,
                    direction = signal.direction.value,
                    confidence= signal.confidence,
                ) or {}
        except Exception as e:
            logger.debug("[NT-SIGNAL] Options gate skipped (%s)", e)

        # ── 4. Discord alert ─────────────────────────────────────────────
        _send_discord_alert(signal, options_context)

        logger.info(
            "[NT-SIGNAL] ✅ Forwarded | %s %s | conf=%.2f | %s",
            bar.symbol,
            signal.direction.value,
            signal.confidence,
            signal.reason,
        )
        return True

    except Exception as e:
        logger.warning("[NT-SIGNAL] Unhandled error processing signal: %s", e, exc_info=True)
        return False


def _futures_to_options_proxy(symbol: str) -> str | None:
    """
    Map a NinjaTrader futures symbol to its closest liquid options proxy.

    NQ / MNQ → QQQ   (Nasdaq futures → QQQ options)
    ES / MES → SPY   (S&P futures    → SPY options)
    YM / MYM → DIA   (Dow futures    → DIA options)
    RTY / M2K→ IWM   (Russell futures→ IWM options)

    Returns None if no mapping exists — options gate is skipped.
    """
    sym = symbol.upper()
    if any(s in sym for s in ("NQ", "MNQ")):
        return "QQQ"
    if any(s in sym for s in ("ES", "MES")):
        return "SPY"
    if any(s in sym for s in ("YM", "MYM")):
        return "DIA"
    if any(s in sym for s in ("RTY", "M2K")):
        return "IWM"
    return None


def _send_discord_alert(signal: NTSignal, options_context: dict) -> None:
    """
    Send a structured Discord notification for an NTSignal.

    Falls back silently if the Discord webhook is unavailable.
    """
    try:
        from app.notifications.discord_helpers import send_simple_message

        bar        = signal.bar
        direction  = signal.direction.value
        emoji      = "🟢" if signal.direction == Direction.BUY else "🔴"
        conf_pct   = int(signal.confidence * 100)
        now_et     = datetime.now(ET).strftime("%I:%M:%S %p ET")
        proxy      = _futures_to_options_proxy(bar.symbol)

        # Core signal block
        lines = [
            f"{emoji} **NinjaTrader Signal — {direction}**",
            f"Symbol  : `{bar.symbol}`",
            f"Time    : {now_et}",
            f"Close   : `{bar.close:.2f}`",
            f"VWAP    : `{bar.vwap:.2f}`  |  POC : `{bar.poc:.2f}`",
            f"VAH/VAL : `{bar.vah:.2f}` / `{bar.val:.2f}`",
            f"CumDelta: `{bar.cum_delta:+.0f}`",
            f"Confidence : **{conf_pct}%**",
            f"Reason  : _{signal.reason}_",
        ]

        # Options block (if available)
        if options_context:
            lines.append("")
            lines.append(f"📊 Options proxy: `{proxy}`")
            for k, v in options_context.items():
                lines.append(f"  {k}: {v}")

        message = "\n".join(lines)
        send_simple_message(message)

    except Exception as e:
        logger.debug("[NT-SIGNAL] Discord alert failed (%s) — non-fatal", e)
