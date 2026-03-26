"""
risk_manager.py — Unified Risk Orchestration Layer
====================================================
Single entry point for ALL risk decisions in War Machine.

What this replaces:
  - Scattered risk checks across scanner.py, signal handlers, and individual modules
  - Duplicate circuit-breaker checks in multiple places
  - Inconsistent VIX/threshold logic per signal type

What callers should use:
  - evaluate_signal()   → Gate a signal through all risk layers before opening a trade
  - open_trade()        → Open a position after signal is approved
  - close_trade()       → Close a position by ID
  - check_exits()       → Scan open positions for stop/target hits
  - get_session_status() → Full session snapshot for Discord/logging

Internal modules wired in:
  - position_manager    → Sizing, circuit breaker, P&L tracking, DB writes
  - trade_calculator    → ATR-based stops, targets, confidence decay
  - vix_sizing          → VIX regime multiplier
  - dynamic_thresholds  → Adaptive confidence floor per signal type + grade
"""

import os
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Internal risk modules ───────────────────────────────────────────────────
from app.risk.position_manager import position_manager
from app.risk.trade_calculator import (
    compute_stop_and_targets,
    get_adaptive_fvg_threshold,
    get_adaptive_orb_threshold,
    apply_confidence_decay,
    calculate_atr,
)
from app.risk.vix_sizing import get_vix_regime, get_vix_multiplier
from app.risk.dynamic_thresholds import get_dynamic_threshold, get_threshold_stats

# ── Kill switch ───────────────────────────────────────────────────────────────
# Live-read on every evaluate_signal() call — toggleable via Railway env var
# without a redeploy (no module-level constant).

def _kill_switch_live() -> bool:
    """Re-read KILL_SWITCH from env on every call so it can be toggled without redeploy."""
    return os.getenv("KILL_SWITCH", "0").strip() == "1"


# =============================================================================
# SIGNAL EVALUATION (Pre-trade gate)
# =============================================================================

def evaluate_signal(
    ticker: str,
    direction: str,
    grade: str,
    confidence: float,
    signal_type: str,
    bars: List[Dict],
    entry_price: float,
    or_high: float,
    or_low: float,
    candles_waited: int = 0,
) -> Dict:
    """
    Gate a signal through every risk layer before a trade is opened.

    Checks (in order — fail-fast):
      1. Kill switch (env var override — re-read live on every call)
      2. Circuit breaker (daily loss limit from position_manager)
      3. Max drawdown from intraday high water mark
      4. Position count ceiling
      5. Duplicate ticker check
      6. Confidence decay (penalise delayed confirmations)
      7. Dynamic confidence threshold (time-of-day + VIX + win-rate + ATR adjusted)
      8. VIX regime hard block (crisis mode — VIX > 40 blocks new trades)
      9. Stop/target calculation — rejects if stop is None (tight tape guard)
     10. R:R validation

    Args:
        ticker:         Stock symbol
        direction:      "bull" or "bear"
        grade:          "A+", "A", or "A-"
        confidence:     Raw confidence score from ai_learning (0.0–1.0)
        signal_type:    "CFW6_OR" or "CFW6_INTRADAY"
        bars:           List of OHLCV bar dicts (used for ATR / stop calc)
        entry_price:    Proposed entry price
        or_high:        Opening range high
        or_low:         Opening range low
        candles_waited: Number of 5m candles waited for confirmation

    Returns:
        dict with keys:
          approved   (bool)   — True if all checks pass
          reason     (str)    — Human-readable reason if rejected
          confidence (float)  — Decay-adjusted confidence
          stop       (float)  — Calculated stop loss price
          t1         (float)  — Target 1 price
          t2         (float)  — Target 2 price
          vix_regime (dict)   — Current VIX snapshot
          threshold  (float)  — Dynamic confidence threshold used
    """

    # ── 1. Kill switch (live re-read — P1 fix 2026-03-25) ──────────────────────────
    if _kill_switch_live():
        return _reject("KILL SWITCH active — no new positions", confidence, entry_price, or_high, or_low, bars, direction, grade)

    # ── 2 & 3: Fetch stats once; pass into both circuit-breaker and drawdown ─
    stats = position_manager.get_daily_stats()

    breached, reason = position_manager.check_circuit_breaker(stats=stats)
    if breached:
        return _reject(reason, confidence, entry_price, or_high, or_low, bars, direction, grade)

    breached, reason = position_manager.check_max_drawdown(stats=stats)
    if breached:
        return _reject(reason, confidence, entry_price, or_high, or_low, bars, direction, grade)

    # ── 4. Position count ────────────────────────────────────────────────────────────
    open_positions = position_manager.get_open_positions()
    from utils import config as _cfg
    max_pos = getattr(_cfg, "MAX_OPEN_POSITIONS", 5)
    if len(open_positions) >= max_pos:
        return _reject(
            f"Max open positions reached ({max_pos})",
            confidence, entry_price, or_high, or_low, bars, direction, grade,
        )

    # ── 5. Duplicate ticker check ────────────────────────────────────────────────────
    for pos in open_positions:
        if pos["ticker"] == ticker:
            return _reject(
                f"Position already open for {ticker}",
                confidence, entry_price, or_high, or_low, bars, direction, grade,
            )

    # ── 6. Confidence decay ───────────────────────────────────────────────────────────
    decayed_confidence = apply_confidence_decay(confidence, candles_waited)

    # ── 7. Dynamic confidence threshold (FIX #26: pass bars + ticker for ATR bucket) ─
    threshold = get_dynamic_threshold(signal_type, grade, bars_session=bars, ticker=ticker)
    if decayed_confidence < threshold:
        return _reject(
            f"Confidence {decayed_confidence:.2f} below dynamic threshold {threshold:.2f} "
            f"({signal_type}/{grade})",
            decayed_confidence, entry_price, or_high, or_low, bars, direction, grade,
        )

    # ── 8. VIX crisis block ──────────────────────────────────────────────────────────
    vix_regime = get_vix_regime()
    if vix_regime["regime"] == "crisis":
        return _reject(
            f"VIX CRISIS MODE ({vix_regime['vix']:.1f}) — all new positions blocked",
            decayed_confidence, entry_price, or_high, or_low, bars, direction, grade,
            vix_regime=vix_regime,
        )

    # ── 9. Stop/target calculation ────────────────────────────────────────────────────
    # FIX P0 (2026-03-25): compute_stop_and_targets() returns (None, None, None) when
    # calculate_stop_loss_by_grade() fires the 10.C-4 guard (stop >= entry on bull, or
    # stop <= entry on bear).  This happens on A+ signals during tight high-vol tape.
    # Previously this None propagated into validate_risk_reward() and crashed.
    # Now we reject cleanly with a human-readable reason.
    stop, t1, t2 = compute_stop_and_targets(bars, direction, or_high, or_low, entry_price, grade)
    if stop is None:
        return _reject(
            f"Invalid stop computed (stop >= entry) — tight tape {grade} signal rejected",
            decayed_confidence, entry_price, or_high, or_low, bars, direction, grade,
            vix_regime=vix_regime,
        )

    # ── 10. R:R validation ───────────────────────────────────────────────────────────
    rr_valid, rr_ratio = position_manager.validate_risk_reward(entry_price, stop, t2)
    if not rr_valid:
        return _reject(
            f"R:R {rr_ratio:.2f} below minimum {position_manager.min_risk_reward_ratio:.2f}",
            decayed_confidence, entry_price, or_high, or_low, bars, direction, grade,
        )

    logger.info(
        f"[RISK] APPROVED {ticker} {direction.upper()} {grade} | "
        f"Conf: {decayed_confidence:.2f} >= {threshold:.2f} | "
        f"R:R: {rr_ratio:.2f} | VIX: {vix_regime['vix']:.1f} ({vix_regime['regime']})"
    )

    return {
        "approved":   True,
        "reason":     "OK",
        "confidence": decayed_confidence,
        "stop":       stop,
        "t1":         t1,
        "t2":         t2,
        "vix_regime": vix_regime,
        "threshold":  threshold,
        "rr_ratio":   round(rr_ratio, 2),
    }


def _reject(
    reason: str,
    confidence: float,
    entry_price: float,
    or_high: float,
    or_low: float,
    bars: List[Dict],
    direction: str,
    grade: str,
    vix_regime: Optional[Dict] = None,
) -> Dict:
    """Build a standardised rejection response."""
    stop, t1, t2 = (0.0, 0.0, 0.0)
    try:
        _s, _t1, _t2 = compute_stop_and_targets(bars, direction, or_high, or_low, entry_price, grade)
        if _s is not None:
            stop, t1, t2 = _s, _t1, _t2
    except Exception:
        pass

    logger.info(f"[RISK] REJECTED — {reason}")
    return {
        "approved":   False,
        "reason":     reason,
        "confidence": confidence,
        "stop":       stop,
        "t1":         t1,
        "t2":         t2,
        "vix_regime": vix_regime or {},
        "threshold":  0.0,
        "rr_ratio":   0.0,
    }


# =============================================================================
# TRADE EXECUTION HELPERS
# =============================================================================

def open_trade(
    ticker: str,
    direction: str,
    grade: str,
    confidence: float,
    entry_price: float,
    stop: float,
    t1: float,
    t2: float,
    zone_low: float,
    zone_high: float,
    or_low: float,
    or_high: float,
    options_rec: Optional[Dict] = None,
) -> int:
    """
    Open a position via position_manager after evaluate_signal() has approved.

    Returns:
        int: position_id (>= 1 on success, -1 on failure)
    """
    return position_manager.open_position(
        ticker=ticker,
        direction=direction,
        zone_low=zone_low,
        zone_high=zone_high,
        or_low=or_low,
        or_high=or_high,
        entry_price=entry_price,
        stop_price=stop,
        t1=t1,
        t2=t2,
        confidence=confidence,
        grade=grade,
        options_rec=options_rec,
    )


def close_trade(position_id: int, exit_price: float, reason: str) -> None:
    """Close a single position by ID."""
    position_manager.close_position(position_id, exit_price, reason)


def close_all_eod(current_prices: Dict[str, float]) -> None:
    """Force-close all open positions at end of day (0DTE 3:55 PM sweep)."""
    position_manager.close_all_eod(current_prices)


def check_exits(current_prices: Dict[str, float]) -> None:
    """
    Scan all open positions for stop/T1/T2 hits.
    Call this on every price update tick in the scanner loop.
    """
    position_manager.check_exits(current_prices)


# =============================================================================
# ADAPTIVE PARAMETER HELPERS (delegated to trade_calculator)
# =============================================================================

def get_fvg_threshold(bars: List[Dict], ticker: str) -> Tuple[float, float]:
    return get_adaptive_fvg_threshold(bars, ticker)


def get_orb_threshold(bars: List[Dict], breakout_idx: int) -> float:
    return get_adaptive_orb_threshold(bars, breakout_idx)


# =============================================================================
# SESSION STATUS (for Discord / EOD logging)
# =============================================================================

def get_session_status() -> Dict:
    """
    Return a full session snapshot for logging and Discord alerts.

    FIX #5: fetches daily_stats and open_positions exactly once, then
    passes them into sub-calls to eliminate redundant DB checkouts.

    Keys returned:
      daily_stats      — trades, wins, losses, total_pnl, win_rate
      open_positions   — list of currently open position dicts
      circuit_breaker  — (is_breached: bool, reason: str)
      vix_regime       — current VIX level, regime, multiplier
      threshold_stats  — current dynamic threshold adjustments
      kill_switch      — True if KILL_SWITCH env var is active (live read)
      risk_summary     — formatted string for printing/Discord
    """
    daily_stats    = position_manager.get_daily_stats()
    open_positions = position_manager.get_open_positions()

    circuit_breaker = position_manager.check_circuit_breaker(stats=daily_stats)
    vix_regime_data = get_vix_regime()
    threshold_data  = get_threshold_stats()

    risk_summary = position_manager.get_risk_summary(open_positions=open_positions)

    return {
        "daily_stats":     daily_stats,
        "open_positions":  open_positions,
        "circuit_breaker": circuit_breaker,
        "vix_regime":      vix_regime_data,
        "threshold_stats": threshold_data,
        "kill_switch":     _kill_switch_live(),  # P1: live read
        "risk_summary":    risk_summary,
    }


def get_eod_report() -> str:
    """Return formatted EOD performance report string."""
    return position_manager.generate_report()


def get_loss_streak() -> bool:
    """
    Return True if today's trades end with 3+ consecutive losses.
    Used by scanner.py to pause scanning after a losing streak.
    """
    return position_manager.has_loss_streak(max_consecutive_losses=3)
