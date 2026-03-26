"""
app/core/sniper_log.py
======================
Structured pre-arm trade logger for War Machine.

PURPOSE:
    Provides log_proposed_trade() — a single structured INFO log line
    written immediately after the stop-tightness guard in arm_ticker(),
    before position_manager.open_position() is called.

    This gives a clean, grep-friendly audit trail of every signal that
    reached the arming stage, independent of whether the position is
    accepted or rejected by the risk manager.

    Without this log there is a visibility gap: a signal can pass all
    scorecard / filter gates but still be rejected by position_manager
    (max positions, correlation, drawdown circuit-breaker) with no
    record of the proposed entry parameters.

CALLED BY:
    app/core/arm_signal.py  →  arm_ticker()

FIX (2026-03-26):
    Created this module. arm_signal.py imported it via:
        from app.core.sniper_log import log_proposed_trade
    but the file never existed, raising an ImportError on every arm
    attempt and silently blocking all trade execution.
"""

import logging

logger = logging.getLogger(__name__)


def log_proposed_trade(
    ticker: str,
    signal_type: str,
    direction: str,
    entry_price: float,
    confidence: float,
    grade: str,
) -> None:
    """
    Write a single structured INFO log line for every proposed trade.

    This is a pure logging function — it has no side effects, never
    raises, and never blocks execution.

    Args:
        ticker:       Ticker symbol (e.g. "NVDA")
        signal_type:  "CFW6_OR" or "CFW6_INTRADAY"
        direction:    "bull" or "bear"
        entry_price:  Proposed entry price at signal time
        confidence:   Scorecard-derived confidence (0.60–0.85)
        grade:        CFW6 confirmation grade ("A+", "A", "A-", "B+", "B")

    Log format (grep key: [PROPOSED-TRADE]):
        [PROPOSED-TRADE] NVDA CFW6_OR BULL | Entry:$123.45 | 72.3% (A)
    """
    try:
        mode = "[OR]" if signal_type == "CFW6_OR" else "[INTRADAY]"
        logger.info(
            f"[PROPOSED-TRADE] {ticker} {signal_type} {direction.upper()} {mode} | "
            f"Entry:${entry_price:.2f} | "
            f"Confidence:{confidence * 100:.1f}% | "
            f"Grade:{grade}"
        )
    except Exception:
        # Never let a logging call crash the arm path
        pass
