# Audit fixes applied March 26, 2026

\"\"\"
sniper_pipeline.py - CFW6 Signal Pipeline
Phase 1.38d: Multi-Timeframe (MTF) Bias & Scorecard-v2 Calibration
\"\"\"
from __future__ import annotations
import logging
from datetime import time
from zoneinfo import ZoneInfo
from utils import config
from utils.config import RVOL_SIGNAL_GATE, RVOL_CEILING, BEAR_SIGNALS_ENABLED
from utils.time_helpers import _now_et
from app.data.data_manager import data_manager
from app.validation.validation import get_regime_filter
from app.validation.cfw6_confirmation import wait_for_confirmation, grade_signal_with_confirmations
from app.risk.trade_calculator import compute_stop_and_targets, get_adaptive_fvg_threshold
from app.filters.vwap_gate import compute_vwap, passes_vwap_gate
from app.core.arm_signal import arm_ticker
from app.core.signal_scorecard import build_scorecard, SCORECARD_GATE_MIN
from app.analytics.cooldown_tracker import is_on_cooldown, set_cooldown
from app.ai.ai_learning import compute_confidence, AILearningEngine
from app.ai.ml_confidence_boost import MLConfidenceBooster
from app.options.dte_selector import get_ideal_dte
from app.filters.dead_zone_suppressor import is_dead_zone
from app.filters.gex_pin_gate import is_in_gex_pin_zone

logger = logging.getLogger(__name__)
_ET = ZoneInfo(\"America/New_York\")

def _resample_bars(bars_1m: list, minutes: int) -> list:
    \"\"\"Resample 1m bars into a higher timeframe bucket (Hoisted: 19.H-6).\"\"\"
    from collections import defaultdict
    buckets = defaultdict(list)
    for b in bars_1m:
        dt = b[\"datetime\"]
        floored = dt.replace(
            minute=(dt.minute // minutes) * minutes,
            second=0, microsecond=0
        )
        buckets[floored].append(b)
    result = []
    for ts in sorted(buckets):
        bucket = buckets[ts]
        result.append({
            \"datetime\": ts,
            \"open\":     bucket[0][\"open\"],
            \"high\":     max(b[\"high\"] for b in bucket),
            \"low\":      min(b[\"low\"] for b in bucket),
            \"close\":    bucket[-1][\"close\"],
            \"volume\":   sum(b[\"volume\"] for b in bucket),
        })
    return result

def run_signal_pipeline(ticker, bars_session, bars_1m_raw, rvol, or_range_pct, or_high, or_low, direction, zone_low, zone_high, entry_price, options_rec=None):
    \"\"\"Core signal pipeline with Phase 1.38d logic.\"\"\"
    
    # --- PHASE 1.38c/d: HARD FILTERS ---
    now_et = _now_et()
    if now_et.time() > time(11, 0):
        logger.info(f\"[{ticker}] 🚫 TIME GATE: {now_et.strftime('%H:%M')} > 11:00 AM — signal dropped\")
        return False

    if or_range_pct < 0.025:
        logger.info(f\"[{ticker}] 🚫 OR RANGE GATE: {or_range_pct:.2%} < 2.5% — signal dropped\")
        return False

    if rvol < 1.3:
        logger.info(f\"[{ticker}] 🚫 RVOL GATE: {rvol:.2f}x < 1.3x floor — signal dropped\")
        return False

    fvg_size_pct = (abs(zone_high - zone_low) / entry_price) * 100
    if fvg_size_pct < 0.04:
        logger.info(f\"[{ticker}] 🚫 FVG SIZE GATE: {fvg_size_pct:.3f}% < 0.04% — signal dropped\")
        return False

    # --- PHASE 1.38d: MTF Trend \"Power\" Logic ---
    _mtf_bias_adj = 0.0
    # Assuming MTF_TREND_ENABLED is a global or config check
    if getattr(config, \"MTF_TREND_ENABLED\", True):
        try:
            _bars_15m = _resample_bars(bars_1m_raw, 15)
            if len(_bars_15m) >= 2:
                _is_aligned = (direction == 'bull' and _bars_15m[-1]['close'] > _bars_15m[-1]['open']) or \
                              (direction == 'bear' and _bars_15m[-1]['close'] < _bars_15m[-1]['open'])
                if _is_aligned:
                    _mtf_bias_adj = 0.05
                    logger.info(f\"[{ticker}] ✅ MTF-TREND: Aligned — +5% Confidence\")
                else:
                    if rvol < 1.8:
                        logger.info(f\"[{ticker}] 🚫 MTF-RVOL GATE: Counter-trend rvol {rvol:.2f}x < 1.8x required — signal dropped\")
                        return False
                    else:
                        logger.info(f\"[{ticker}] ⚠️  MTF-TREND: Counter-trend — High RVOL {rvol:.2f}x overrides\")
        except Exception as _mtf_err:
            logger.warning(f\"[{ticker}] MTF bias check skipped (non-fatal): {_mtf_err}\")

    # --- PHASE 1.38d: Scorecard-v2 Calibration ---
    _sc = build_scorecard(
        ticker=ticker, 
        direction=direction, 
        grade=\"A\", 
        options_rec=options_rec,
        mtf_trend_boost=_mtf_bias_adj,
        rvol=rvol,
    )
    _sc.confidence = min(_sc.confidence, 0.75)

    if _sc.score < SCORECARD_GATE_MIN:
        logger.info(f\"[{ticker}] 🚫 SCORECARD-GATE: {_sc.score:.1f} < {SCORECARD_GATE_MIN} — signal dropped\")
        return False
    
    # Arm the ticker
    return arm_ticker(
        ticker=ticker,
        direction=direction,
        zone_low=zone_low,
        zone_high=zone_high,
        entry_price=entry_price,
        confidence=_sc.confidence,
        options_rec=options_rec
    )
