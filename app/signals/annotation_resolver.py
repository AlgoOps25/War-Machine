"""
Annotation Resolver
===================
Converts a human-posted R:R annotation from #chart-annotations into a live
futures signal and submits it to the War Machine position pipeline.

INTEGRATION
-----------
This module has NO bot or listener of its own.  Call resolve_annotation()
from whichever part of the codebase already reads incoming Discord messages
(e.g. your existing discord_helpers / webhook handler).

Example (inside your existing message handler):
    from app.signals.annotation_resolver import parse_annotation, resolve_annotation

    def on_annotation_message(content: str, posted_at):
        result = parse_annotation(content)
        if result:
            rr_ratio, direction_hint = result
            resolve_annotation(rr_ratio, direction_hint, "NQM25", posted_at)

PIPELINE
--------
1. Pull live 1-min bars via data_manager.get_today_session_bars() -- same
   source used by opening_range.py and breakout_detector.py.
2. Compute ATR via or_detector._calculate_atr() for consistency.
3. Auto-detect direction from BOS (detect_breakout_after_or) unless caller
   provides an explicit direction hint.
4. Validate:
     a. Minimum R:R gate  (config.MIN_RISK_REWARD_RATIO, default 1.5)
     b. BOS confirmation  (detect_breakout_after_or)
     c. All War Machine risk gates via position_manager.can_open_position()
5. Call position_manager.open_position() with signal_type="DISCORD_ANNOTATION".
6. Send rich Discord embed via _send_annotation_to_discord() to the dedicated
   DISCORD_ANNOTATIONS_WEBHOOK_URL (falls back to #signals if not set).

ANNOT-2 (Apr 3 2026):
- _notify() upgraded from plain-text message to rich embed (green/red,
  Price Levels field, ATR + Position ID in footer).
- Routes through _send_annotation_to_discord() so alerts land in
  #chart-annotations channel rather than #signals.
"""

import logging
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from utils import config
from app.data.data_manager import data_manager
from app.signals.opening_range import (
    or_detector,
    detect_breakout_after_or,
    compute_opening_range_from_bars,
)
from app.risk.position_manager import PositionManager

logger = logging.getLogger(__name__)

_ET      = ZoneInfo("America/New_York")
_MIN_RR  = getattr(config, "MIN_RISK_REWARD_RATIO", 1.5)

# Shared PositionManager instance
_pm: Optional[PositionManager] = None


def _get_pm() -> PositionManager:
    global _pm
    if _pm is None:
        _pm = PositionManager()
    return _pm


# ── Regex for callers that don't want to parse themselves ─────────────────────
# Matches: "3.31"  "LONG 4.1"  "bull 2.5"  "SHORT 3.0"  "bear 2.0"
ANNOTATION_RE = re.compile(
    r"^\s*(?:(long|bull|short|bear)\s+)?(\d+\.\d+)\s*$",
    re.IGNORECASE,
)


def parse_annotation(text: str) -> Optional[tuple]:
    """
    Parse a raw annotation string from #chart-annotations.

    Returns:
        (rr_ratio: float, direction_hint: str | None)  on match
        None                                            on no match

    direction_hint is normalised to "bull" | "bear" | None.
    """
    m = ANNOTATION_RE.match(text.strip())
    if not m:
        return None
    raw_dir = m.group(1)
    rr      = float(m.group(2))
    if raw_dir:
        direction = "bull" if raw_dir.lower() in ("long", "bull") else "bear"
    else:
        direction = None
    return rr, direction


# ── Core resolver ─────────────────────────────────────────────────────────────

def resolve_annotation(
    rr_ratio:       float,
    direction_hint: Optional[str],
    symbol:         str,
    posted_at:      datetime,
) -> None:
    """
    Convert an annotated R:R value into a War Machine futures position.

    Synchronous -- safe to call from any thread or async context via
    asyncio.to_thread().

    Args:
        rr_ratio:       R:R from the annotation (e.g. 3.31).
        direction_hint: "bull", "bear", or None (auto-detect from BOS).
        symbol:         Futures contract symbol (e.g. "NQM25").
        posted_at:      Timestamp of the Discord message (for logging).
    """
    tag = f"[ANNOTATION {symbol} R:{rr_ratio}]"

    # ── 1. Min R:R gate ───────────────────────────────────────────────────────
    if rr_ratio < _MIN_RR:
        logger.info(f"{tag} Skipped -- R:R {rr_ratio} < min {_MIN_RR}")
        return

    # ── 2. Live bars via data_manager ─────────────────────────────────────────
    bars = data_manager.get_today_session_bars(symbol)
    if not bars or len(bars) < 5:
        logger.warning(f"{tag} Skipped -- insufficient session bars ({len(bars) if bars else 0})")
        return

    # ── 3. OR levels for BOS anchor ───────────────────────────────────────────
    or_high, or_low = compute_opening_range_from_bars(bars)
    if or_high is None or or_low is None:
        or_high = max(b["high"] for b in bars)
        or_low  = min(b["low"]  for b in bars)
        logger.info(f"{tag} OR not available -- using session range ${or_low:.2f}-${or_high:.2f}")

    # ── 4. BOS detection / direction ──────────────────────────────────────────
    bos_direction, bos_idx = detect_breakout_after_or(bars, or_high, or_low)

    if direction_hint:
        direction = direction_hint
        if bos_direction and bos_direction != direction:
            logger.info(
                f"{tag} Skipped -- caller says {direction} but BOS fired {bos_direction}"
            )
            return
        if not bos_direction:
            logger.info(f"{tag} Skipped -- no BOS confirmed for explicit {direction} hint")
            return
    else:
        if not bos_direction:
            logger.info(f"{tag} Skipped -- no BOS detected (auto-direction)")
            return
        direction = bos_direction

    # ── 5. ATR via or_detector ─────────────────────────────────────────────────
    atr = or_detector._calculate_atr(symbol)
    if not atr or atr <= 0:
        atr = sum(b["high"] - b["low"] for b in bars[-14:]) / min(14, len(bars))

    # ── 6. Build entry / stop / targets ───────────────────────────────────────
    latest_bar = bars[-1]
    entry      = latest_bar["close"]
    stop_dist  = atr
    t1_dist    = atr * (rr_ratio / 2)
    t2_dist    = atr * rr_ratio

    if direction == "bull":
        stop = entry - stop_dist
        t1   = entry + t1_dist
        t2   = entry + t2_dist
    else:
        stop = entry + stop_dist
        t1   = entry - t1_dist
        t2   = entry - t2_dist

    logger.info(
        f"{tag} {direction.upper()} | "
        f"entry={entry:.2f}  stop={stop:.2f}  "
        f"T1={t1:.2f}  T2={t2:.2f}  ATR={atr:.2f}"
    )

    # ── 7. Open position via existing War Machine pipeline ────────────────────
    pm     = _get_pm()
    pos_id = pm.open_position(
        ticker       = symbol,
        direction    = direction,
        zone_low     = or_low,
        zone_high    = or_high,
        or_low       = or_low,
        or_high      = or_high,
        entry_price  = entry,
        stop_price   = stop,
        t1           = t1,
        t2           = t2,
        confidence   = 0.70,
        grade        = "A",
        signal_type  = "DISCORD_ANNOTATION",
    )

    if pos_id and pos_id > 0:
        logger.info(f"{tag} \u2705 Position opened -- ID {pos_id}")
        _notify(symbol, direction, entry, stop, t1, t2, rr_ratio, atr, pos_id)
    else:
        logger.info(f"{tag} \u274c open_position rejected (risk gate, duplicate, or RTH guard)")


# ── Discord notification ───────────────────────────────────────────────────────

def _notify(
    symbol: str, direction: str,
    entry: float, stop: float, t1: float, t2: float,
    rr: float, atr: float, pos_id: int,
) -> None:
    """Rich embed annotation alert routed to DISCORD_ANNOTATIONS_WEBHOOK_URL.

    ANNOT-2: Upgraded from plain text to structured embed so the alert is
    visually consistent with other War Machine signal alerts.
    Non-fatal on any failure.
    """
    try:
        from app.notifications.discord_helpers import _send_annotation_to_discord

        is_long = direction == "bull"
        color   = 0x00FF00 if is_long else 0xFF0000
        side    = "LONG \U0001f7e2" if is_long else "SHORT \U0001f534"

        risk = abs(entry - stop)
        r1   = abs(t1 - entry) / risk if risk > 0 else 0
        r2   = abs(t2 - entry) / risk if risk > 0 else 0

        embed = {
            "title": f"{side}  {symbol}  \u2014  Annotation Signal  (R:R {rr}:1)",
            "color": color,
            "fields": [
                {
                    "name": "Price Levels",
                    "value": (
                        f"Entry : **{entry:.2f}**\n"
                        f"Stop  : **{stop:.2f}**  (Risk **{risk:.2f}**)\n"
                        f"T1    : **{t1:.2f}**  ({r1:.1f}R)\n"
                        f"T2    : **{t2:.2f}**  ({r2:.1f}R)"
                    ),
                    "inline": False,
                },
            ],
            "footer": {
                "text": (
                    f"War Machine Annotation | ATR {atr:.2f} | "
                    f"Pos ID {pos_id} | "
                    f"{datetime.now().strftime('%Y-%m-%d %I:%M %p ET')}"
                )
            },
        }

        _send_annotation_to_discord({"embeds": [embed]})

    except Exception as exc:
        logger.warning(f"[ANNOTATION] Discord notify failed (non-fatal): {exc}")
