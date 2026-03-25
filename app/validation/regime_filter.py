"""
regime_filter.py — Market Regime Detection
Extracted from validation.py (Phase 3A consolidation) to reduce file size.
RegimeFilter + RegimeState live here; validation.py re-exports them.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
import time
import logging

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


@dataclass
class RegimeState:
    """Current market regime state."""
    regime: str
    vix: float
    spy_trend: str
    adx: Optional[float]
    favorable: bool
    reason: str
    timestamp: datetime


class RegimeFilter:
    """
    Market regime detection using VIX and SPY price action.

    Regime Classification:
      TRENDING: ADX > dynamic threshold (VIX-aware), VIX < 30, clear directional move
      CHOPPY:   ADX below dynamic threshold, VIX < 20, range-bound action
      VOLATILE: VIX > 30, erratic moves, avoid trading

    VIX-Aware ADX Thresholds (Phase 3A Patch):
      VIX <= 20:  ADX must be >= 20.0 for TRENDING
      VIX 20-25:  ADX must be >= 15.0 for TRENDING
      VIX > 25:   ADX must be >= 12.0 for TRENDING

    Explosive Mover Override (Phase 3A Patch 2):
      RVOL >= 3.0x bypasses the regime gate entirely.
    """

    def __init__(self):
        self._cache: Optional[RegimeState] = None
        self._cache_ttl = 300
        self._last_check = 0

    def is_favorable_regime(self, force_refresh: bool = False) -> bool:
        return self.get_regime_state(force_refresh=force_refresh).favorable

    def is_favorable_for_explosive_mover(self, rvol: float, rvol_threshold: float = 3.0) -> bool:
        if rvol >= rvol_threshold:
            state = self.get_regime_state()
            logger.info(
                f"[REGIME] EXPLOSIVE MOVER OVERRIDE: RVOL={rvol:.1f}x >= {rvol_threshold:.0f}x "
                f"— bypassing {state.regime} gate "
                f"(VIX:{state.vix:.1f}, ADX:{state.adx if state.adx is not None else 'N/A'})"
            )
            return True
        return self.is_favorable_regime()

    def get_regime_state(self, force_refresh: bool = False) -> RegimeState:
        now = time.time()
        if not force_refresh and self._cache and (now - self._last_check) < self._cache_ttl:
            return self._cache
        try:
            vix      = self._get_vix_level()
            spy_bars = self._get_spy_bars()
            if not spy_bars or len(spy_bars) < 14:
                return self._create_state(
                    regime="CHOPPY", vix=vix or 20.0, spy_trend="NEUTRAL",
                    adx=None, favorable=False, reason="Insufficient data for regime analysis"
                )
            spy_trend = self._calculate_spy_trend(spy_bars)
            adx       = self._calculate_adx(spy_bars)
            regime, favorable, reason = self._classify_regime(vix, adx, spy_trend, spy_bars)
            state = self._create_state(regime=regime, vix=vix, spy_trend=spy_trend,
                                       adx=adx, favorable=favorable, reason=reason)
            self._cache     = state
            self._last_check = now
            return state
        except Exception as e:
            logger.info(f"[REGIME] Error calculating regime: {e}")
            return self._create_state(
                regime="CHOPPY", vix=20.0, spy_trend="NEUTRAL",
                adx=None, favorable=False, reason=f"Error: {str(e)}"
            )

    def _create_state(self, regime, vix, spy_trend, adx, favorable, reason) -> RegimeState:
        return RegimeState(regime=regime, vix=vix, spy_trend=spy_trend,
                           adx=adx, favorable=favorable, reason=reason,
                           timestamp=datetime.now(ET))

    def _get_vix_level(self) -> float:
        try:
            from app.data.data_manager import data_manager
            try:
                v = data_manager.get_vix_level()
                if v and v > 0:
                    return v
            except Exception:
                pass
            bars = data_manager.get_bars_from_memory("VIX", limit=1)
            if bars:
                return bars[-1]["close"]
            lb = data_manager.get_latest_bar("VIX")
            if lb:
                return lb["close"]
        except Exception as e:
            logger.info(f"[REGIME] VIX fetch error: {e}")
        return 20.0

    def _get_spy_bars(self, limit: int = 50) -> list:
        try:
            from app.data.data_manager import data_manager
            bars = data_manager.get_bars_from_memory("SPY", limit=limit)
            if bars and len(bars) >= 14:
                return bars
            bars = data_manager.get_today_session_bars("SPY")
            if bars and len(bars) >= 14:
                return bars[-limit:]
            bars = data_manager.get_today_5m_bars("SPY")
            if bars and len(bars) >= 14:
                return bars[-limit:]
        except Exception as e:
            logger.info(f"[REGIME] SPY bars error: {e}")
        return []

    def _calculate_spy_trend(self, bars: list) -> str:
        if len(bars) < 20:
            return "NEUTRAL"
        try:
            closes = [b["close"] for b in bars[-20:]]
            ema9  = self._calculate_ema(closes[-9:], 9)
            ema20 = self._calculate_ema(closes, 20)
            price = closes[-1]
            if ema9 > ema20 and price > ema9:
                return "BULL"
            if ema9 < ema20 and price < ema9:
                return "BEAR"
        except Exception:
            pass
        return "NEUTRAL"

    def _calculate_adx(self, bars: list, period: int = 14) -> Optional[float]:
        """
        Wilder's smoothed ADX — proper implementation (Mar 12 2026 fix).
        Requires len(bars) >= period*2+1.
        """
        if len(bars) < period * 2 + 1:
            return None
        try:
            trs, plus_dms, minus_dms = [], [], []
            for i in range(1, len(bars)):
                h, l, pc = bars[i]["high"], bars[i]["low"], bars[i-1]["close"]
                ph, pl   = bars[i-1]["high"], bars[i-1]["low"]
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
                up, dn = h - ph, pl - l
                plus_dms.append(up if up > dn and up > 0 else 0.0)
                minus_dms.append(dn if dn > up and dn > 0 else 0.0)

            s_tr = sum(trs[:period])
            s_pd = sum(plus_dms[:period])
            s_md = sum(minus_dms[:period])

            def _di(sd, st): return (sd / st * 100) if st > 0 else 0.0
            def _dx(p, m):   return abs(p - m) / (p + m) * 100 if (p + m) > 0 else 0.0

            adx = _dx(_di(s_pd, s_tr), _di(s_md, s_tr))
            for i in range(period, len(trs)):
                s_tr = s_tr - (s_tr / period) + trs[i]
                s_pd = s_pd - (s_pd / period) + plus_dms[i]
                s_md = s_md - (s_md / period) + minus_dms[i]
                adx  = adx  - (adx  / period) + _dx(_di(s_pd, s_tr), _di(s_md, s_tr))
            return round(adx, 2)
        except Exception as e:
            logger.info(f"[REGIME] ADX error: {e}")
            return None

    def _calculate_ema(self, values: list, period: int) -> float:
        if not values:
            return 0.0
        m, ema = 2 / (period + 1), values[0]
        for v in values[1:]:
            ema = v * m + ema * (1 - m)
        return ema

    def _classify_regime(self, vix, adx, spy_trend, spy_bars) -> Tuple[str, bool, str]:
        if vix >= 35:
            return "VOLATILE", False, f"VIX too high ({vix:.1f}) — extreme fear/greed"
        if vix >= 30:
            return "VOLATILE", False, f"VIX elevated ({vix:.1f}) — elevated volatility"

        if len(spy_bars) >= 10:
            recent = spy_bars[-10:]
            reversals = sum(
                1 for i in range(1, len(recent))
                if (recent[i]["close"] - recent[i]["open"]) *
                   (recent[i-1]["close"] - recent[i-1]["open"]) < 0
            )
            if reversals >= 6:
                return "CHOPPY", False, f"Whipsaw action ({reversals}/10 reversals) — avoid"

        effective_adx = 12.0 if vix > 25 else (15.0 if vix > 20 else 20.0)

        if adx is not None:
            if adx >= effective_adx:
                if vix < 25:
                    return "TRENDING", True, \
                        f"Strong {spy_trend} trend (ADX:{adx:.0f}>={effective_adx:.0f}, VIX:{vix:.1f})"
                else:
                    return "TRENDING", spy_trend != "NEUTRAL", \
                        f"{spy_trend} trend elevated VIX (ADX:{adx:.0f}>={effective_adx:.0f}, VIX:{vix:.1f})"
            else:
                return "CHOPPY", False, \
                    f"Weak trend (ADX:{adx:.0f}<{effective_adx:.0f}) — range-bound"

        if vix < 20 and spy_trend != "NEUTRAL":
            return "TRENDING", True, f"Low VIX ({vix:.1f}), {spy_trend} bias"
        return "CHOPPY", False, f"Neutral conditions (VIX:{vix:.1f})"

    def print_regime_summary(self) -> None:
        state = self.get_regime_state()
        emoji  = {"TRENDING": "📈" if state.favorable else "📉", "CHOPPY": "〰️", "VOLATILE": "⚡"}.get(state.regime, "?")
        status = "✅ FAVORABLE" if state.favorable else "🚫 UNFAVORABLE"
        logger.info("=" * 70)
        logger.info(f"{emoji}  MARKET REGIME: {state.regime}  {status}")
        logger.info(f"VIX:{state.vix:.2f}  SPY:{state.spy_trend}  ADX:{state.adx if state.adx else 'N/A'}")
        logger.info(f"Reason: {state.reason}")
        logger.info("=" * 70)

    def reset_cache(self) -> None:
        self._cache = None
        self._last_check = 0
        logger.info("[REGIME] Cache cleared")
