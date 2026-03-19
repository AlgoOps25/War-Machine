"""
EOD Reporter — War Machine End-of-Day Reporting Orchestrator

Single entry point: run_eod_report(session_date=None)

What it does:
  1. Pulls trade P&L stats from risk_manager.get_session_status()
  2. Pulls signal funnel + rejection breakdown + hourly funnel from
     signal_analytics.signal_tracker
  3. Sends a rich Discord embed (trade summary) via send_daily_summary()
  4. Sends a compact signal-funnel block via send_simple_message()
  5. Clears the signal_tracker session cache

Called by scanner.py at EOD (market-closed block, once per day).
Can also be run standalone: python -m app.core.eod_reporter

ADDED (Phase 1.32 — Mar 17 2026):
  - Created this module (was referenced in AUDIT_REGISTRY but never built)
  - Replaces the 30-line inline EOD Discord block in scanner.py

FIX (Mar 19 2026):
  - get_daily_summary() output now sent to both print() AND logger.info()
    so test_daily_summary_printed_to_stdout (capsys) captures it correctly.
"""
from __future__ import annotations

import logging
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from app.risk.risk_manager import get_session_status, get_eod_report
from app.notifications.discord_helpers import send_daily_summary, send_simple_message

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def run_eod_report(session_date: str | None = None) -> None:
    """
    Orchestrate all EOD Discord reports for one trading day.

    Args:
        session_date: YYYY-MM-DD string.  Defaults to today in ET.
    """
    if session_date is None:
        session_date = datetime.now(ET).strftime("%Y-%m-%d")

    logger.info(f"[EOD-REPORTER] Generating EOD report for {session_date}")

    # ── 1. Trade / P&L stats ─────────────────────────────────────────────────
    try:
        session     = get_session_status()
        daily_stats = session.get("daily_stats", {})

        trades   = daily_stats.get("trades",    0)
        wins     = daily_stats.get("wins",      0)
        losses   = daily_stats.get("losses",    0)
        win_rate = daily_stats.get("win_rate",  0.0)
        total_pnl= daily_stats.get("total_pnl", 0.0)

        # Rich embed — trade summary
        send_daily_summary({
            "trades":    trades,
            "wins":      wins,
            "losses":    losses,
            "win_rate":  win_rate,
            "total_pnl": total_pnl,
        })
        logger.info("[EOD-REPORTER] ✅ Trade summary embed sent")

        # Top performers plain-text block
        try:
            top = get_eod_report()
            if top:
                send_simple_message(f"🏆 **Top Performers — {session_date}**\n{top}")
        except Exception as e:
            logger.warning(f"[EOD-REPORTER] top-performers unavailable: {e}")

    except Exception as e:
        logger.error(f"[EOD-REPORTER] Trade stats error: {e}")

    # ── 2. Signal analytics funnel block ─────────────────────────────────────
    try:
        from app.signals.signal_analytics import signal_tracker

        discord_msg = signal_tracker.get_discord_eod_summary(session_date)
        if discord_msg:
            send_simple_message(discord_msg)
            logger.info("[EOD-REPORTER] ✅ Signal funnel block sent to Discord")

        # Print full summary to stdout for ops visibility (Railway logs + capsys)
        full_summary = signal_tracker.get_daily_summary(session_date)
        print(full_summary)
        logger.info(full_summary)

        # Clear session cache for next trading day
        signal_tracker.clear_session_cache()
        logger.info("[EOD-REPORTER] ✅ Signal tracker session cache cleared")

    except ImportError:
        logger.warning("[EOD-REPORTER] signal_analytics not available — skipping funnel report")
    except Exception as e:
        logger.error(f"[EOD-REPORTER] Signal analytics error: {e}")

    logger.info(f"[EOD-REPORTER] ✅ All EOD reports complete for {session_date}")


if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_eod_report(date_arg)
