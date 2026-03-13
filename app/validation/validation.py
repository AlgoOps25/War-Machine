"""
═══════════════════════════════════════════════════════════════════════════════
UNIFIED VALIDATION MODULE - PRODUCTION
═══════════════════════════════════════════════════════════════════════════════

Consolidates signal_validator.py + regime_filter.py + options_filter.py
into a single validation interface with comprehensive multi-indicator confirmation.

PHASE 3A CONSOLIDATION (Feb 26, 2026):
  - Merged 3 files → 1 active module
  - 72KB → ~65KB (eliminated duplicate imports)
  - Single source of truth for all validation
  - Compatibility stubs maintain zero breaking changes

PHASE 3A PATCH (Mar 6, 2026) — Regime Filter Improvements:
  - VIX-aware dynamic ADX threshold replaces hardcoded 25
      VIX ≤ 20  → effective ADX threshold = 20.0
      VIX 20–25 → effective ADX threshold = 15.0  (elevated VIX compresses ADX)
      VIX > 25  → effective ADX threshold = 12.0  (extreme fear, ADX tanks)
  - RegimeFilter.is_favorable_for_explosive_mover(rvol): bypasses regime gate
    ENTIRELY when RVOL ≥ 3.0x — explosive movers override choppy-tape blocking
  - min_adx default lowered 25.0 → 15.0 (aligns with regime filter change)

PHASE 3A PATCH 2 (Mar 12, 2026) — Bug Fixes:
  - Fix 1 (P0): _calculate_adx() replaced with proper Wilder's smoothed ADX.
    Previous implementation returned a single raw DX snapshot (0–5 early session)
    instead of the 14-period smoothed ADX (15–40 range). Regime was blocking nearly
    all signals in the first 60–90 minutes as a result.
  - Fix 2 (P0): RVOL bypass threshold unified to 3.0x across all call sites.
    is_favorable_for_explosive_mover() default was 4.0x — inconsistent with
    get_ticker_screener_metadata() which already used 3.0x. 3.0–3.9x RVOL tickers
    were getting qualified=True from the screener but still hitting the regime gate.
  - Fix 3 (P1): entryprice NameError + bestoption typo in optimizer branch of
    find_best_strike(). Every call with OPTIONS_OPTIMIZER_ENABLED=True was throwing
    NameError and silently falling back to the slow serial EODHD chain fetch.
  - Fix 4 (P2): Removed ghost earnings guard comment. The docstring claimed an
    earnings guard was active — no such code exists anywhere in the pipeline.

PHASE 1.26a (Mar 13, 2026) — Bug Fix:
  - Fix OPTIONS_OPTIMIZER_ENABLED NameError in find_best_strike().
    The try/except import block set _OPTIMIZER_AVAILABLE but find_best_strike()
    referenced the undefined OPTIONS_OPTIMIZER_ENABLED name, throwing a NameError
    on every ONDS scan cycle. Changed to use _OPTIMIZER_AVAILABLE consistently.

VALIDATION CONFIGURATION:
  • Minimum Final Confidence: 50% (configurable via min_final_confidence)
  • Minimum ADX: 15.0 (VIX-aware dynamic threshold, was 25.0)
  • Minimum Volume Ratio: 1.5x average
  • Daily Bias Penalty: -25% for counter-trend (VPVR can rescue)
  • Regime Penalty: -30% for unfavorable market conditions
  • VIX Threshold: 30+ = VOLATILE regime (unfavorable)
  • ADX Threshold: VIX-aware dynamic (12 / 15 / 20 based on VIX level)

CONFIDENCE ADJUSTMENTS:
  Boosts (additive):
    +10%: Volume 2x+ average
    +8%:  VPVR strong entry (0.85+ score)
    +7%:  EMA full stack alignment
    +5%:  Multiple indicators (ADX 40+, bias aligned, divergence, time zones)
  
  Penalties (subtractive):
    -30%: Unfavorable regime (CHOPPY/VOLATILE)
    -25%: Strong counter-trend to daily bias (rescuable by VPVR 0.85+)
    -10%: DMI conflict
    -8%:  Weak volume
    -5%:  Various indicator conflicts

VALIDATION LAYERS:
  1. SignalValidator - Multi-indicator CFW6 confirmation
  2. RegimeFilter - Market condition detection (VIX/SPY)
  3. OptionsFilter - Options chain analysis with IVR/UOA/GEX
  Note: No earnings guard is implemented. Tickers are not filtered by earnings date.

USAGE:
  from validation import get_validator, get_regime_filter, get_options_filter
  
  # Signal validation with automatic filtering
  validator = get_validator()  # Uses 50% minimum confidence
  should_pass, conf, metadata = validator.validate_signal(...)
  
  # Print formatted summary for monitoring
  if should_pass:
      validator.print_validation_summary(ticker, metadata)
  
  # Custom threshold (aggressive: 40%, conservative: 65%)
  validator = SignalValidator(min_final_confidence=0.65, strict_mode=True)
  
  # Regime filtering (standard)
  regime_filter = get_regime_filter()
  if not regime_filter.is_favorable_regime():
      print("Bad tape - skip signal")
  
  # Regime filtering (explosive mover override — call this INSTEAD of is_favorable_regime)
  if regime_filter.is_favorable_for_explosive_mover(rvol=ticker_rvol):
      process_signal()  # passes if RVOL >= 3x regardless of ADX/regime
  
  # Options validation
  options_filter = get_options_filter()
  is_valid, data, reason = options_filter.validate_signal_for_options(...)

═══════════════════════════════════════════════════════════════════════════════
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from dataclasses import dataclass
import time
import requests

from app.analytics import technical_indicators as ti
from utils import config

# Import IV/GEX modules for options filter
from app.options.iv_tracker import store_iv_observation, compute_ivr, ivr_to_confidence_multiplier
from app.options.gex_engine import compute_gex_levels, get_gex_signal_context

# UOA now comes from options_intelligence (Phase 3C consolidation)
try:
    from app.options.options_intelligence import scan_chain_for_uoa
    from uoa_scanner import format_uoa_summary  # Still in stub for convenience
except ImportError:
    # Fallback if options_intelligence not yet available
    def scan_chain_for_uoa(*args, **kwargs):
        return {
            'uoa_multiplier': 1.0, 'uoa_label': 'UOA-UNAVAILABLE',
            'uoa_detected': False, 'uoa_aligned': False,
            'uoa_opposing': False, 'uoa_max_score': 0.0,
            'uoa_top_aligned': [], 'uoa_top_opposing': []
        }
    def format_uoa_summary(uoa_data):
        return "UOA scanner unavailable"

ET = ZoneInfo("America/New_York")

# Import dependencies (signal validator needs these)
try:
    from daily_bias_engine import bias_engine
    BIAS_ENGINE_ENABLED = True
except ImportError:
    BIAS_ENGINE_ENABLED = False
    bias_engine = None

try:
    from vpvr_calculator import vpvr_calculator
    VPVR_ENABLED = True
except ImportError:
    VPVR_ENABLED = False
    vpvr_calculator = None

try:
    from app.options.options_optimizer import get_optimal_strikes_sync
    _OPTIMIZER_AVAILABLE = True
except ImportError:
    _OPTIMIZER_AVAILABLE = False



# ══════════════════════════════════════════════════════════════════════════════
# REGIME FILTER (from regime_filter.py)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RegimeState:
    """Current market regime state."""
    regime: str              # TRENDING, CHOPPY, VOLATILE
    vix: float              # Current VIX level
    spy_trend: str          # BULL, BEAR, NEUTRAL
    adx: Optional[float]    # Trend strength (0-100)
    favorable: bool         # True = safe to trade
    reason: str             # Why favorable/unfavorable
    timestamp: datetime


class RegimeFilter:
    """
    Market regime detection using VIX and SPY price action.
    
    Regime Classification:
      TRENDING: ADX > dynamic threshold (VIX-aware), VIX < 30, clear directional move
      CHOPPY:   ADX below dynamic threshold, VIX < 20, range-bound action
      VOLATILE: VIX > 30, erratic moves, avoid trading
    
    VIX-Aware ADX Thresholds (Phase 3A Patch):
      VIX ≤ 20:  ADX must be ≥ 20.0 for TRENDING
      VIX 20–25: ADX must be ≥ 15.0 for TRENDING  (elevated VIX compresses ADX)
      VIX > 25:  ADX must be ≥ 12.0 for TRENDING  (extreme fear, ADX tanks further)
    
    Explosive Mover Override (Phase 3A Patch 2):
      RVOL ≥ 3.0x bypasses the regime gate entirely via
      is_favorable_for_explosive_mover(rvol). Call this INSTEAD of
      is_favorable_regime() for tickers with known high RVOL.
    """
    
    def __init__(self):
        self._cache: Optional[RegimeState] = None
        self._cache_ttl = 300  # 5-minute cache
        self._last_check = 0
        
    def is_favorable_regime(self, force_refresh: bool = False) -> bool:
        """Check if current market regime is favorable for trading."""
        state = self.get_regime_state(force_refresh=force_refresh)
        return state.favorable

    def is_favorable_for_explosive_mover(self, rvol: float, rvol_threshold: float = 3.0) -> bool:
        """
        RVOL-based regime override for explosive movers.

        Checks RVOL BEFORE the regime gate. If RVOL >= rvol_threshold, the
        regime check is bypassed entirely — an explosive mover with 3x+
        relative volume warrants a signal attempt regardless of ADX or VIX.

        Threshold unified to 3.0x (was 4.0x) to match screener_integration
        get_ticker_screener_metadata() which uses rvol >= 3.0 for qualified=True.

        Call this method INSTEAD of is_favorable_regime() for tickers where
        the RVOL is known (e.g., from the premarket scanner composite score).

        Args:
            rvol: Relative volume ratio (e.g., 3.5 means 3.5x average volume)
            rvol_threshold: Minimum RVOL to trigger override (default 3.0x)

        Returns:
            True if explosive mover override fires OR standard regime is favorable
        """
        if rvol >= rvol_threshold:
            state = self.get_regime_state()
            print(
                f"[REGIME] ⚡ EXPLOSIVE MOVER OVERRIDE: RVOL={rvol:.1f}x ≥ {rvol_threshold:.0f}x "
                f"— bypassing {state.regime} gate "
                f"(VIX:{state.vix:.1f}, ADX:{state.adx if state.adx is not None else 'N/A'})"
            )
            return True
        return self.is_favorable_regime()
    
    def get_regime_state(self, force_refresh: bool = False) -> RegimeState:
        """Get current market regime state."""
        now = time.time()
        
        if not force_refresh and self._cache and (now - self._last_check) < self._cache_ttl:
            return self._cache
        
        try:
            vix = self._get_vix_level()
            spy_bars = self._get_spy_bars()
            
            if not spy_bars or len(spy_bars) < 14:
                return self._create_state(
                    regime="CHOPPY", vix=vix or 20.0, spy_trend="NEUTRAL",
                    adx=None, favorable=False, reason="Insufficient data for regime analysis"
                )
            
            spy_trend = self._calculate_spy_trend(spy_bars)
            adx = self._calculate_adx(spy_bars)
            regime, favorable, reason = self._classify_regime(vix, adx, spy_trend, spy_bars)
            
            state = self._create_state(
                regime=regime, vix=vix, spy_trend=spy_trend,
                adx=adx, favorable=favorable, reason=reason
            )
            
            self._cache = state
            self._last_check = now
            return state
            
        except Exception as e:
            print(f"[REGIME] Error calculating regime: {e}")
            return self._create_state(
                regime="CHOPPY", vix=20.0, spy_trend="NEUTRAL",
                adx=None, favorable=False, reason=f"Error: {str(e)}"
            )
    
    def _create_state(self, regime: str, vix: float, spy_trend: str, 
                      adx: Optional[float], favorable: bool, reason: str) -> RegimeState:
        return RegimeState(
            regime=regime, vix=vix, spy_trend=spy_trend, adx=adx,
            favorable=favorable, reason=reason, timestamp=datetime.now()
        )
    
    def _get_vix_level(self) -> float:
        """Get current VIX level from data manager."""
        try:
            from app.data.data_manager import data_manager
            try:
                vix_level = data_manager.get_vix_level()
                if vix_level and vix_level > 0:
                    return vix_level
            except:
                pass
            bars = data_manager.get_bars_from_memory("VIX", limit=1)
            if bars and len(bars) > 0:
                return bars[-1]["close"]
            latest_bar = data_manager.get_latest_bar("VIX")
            if latest_bar:
                return latest_bar["close"]
            return 20.0
        except Exception as e:
            print(f"[REGIME] Error fetching VIX: {e}")
            return 20.0
    
    def _get_spy_bars(self, limit: int = 50) -> list:
        """Get recent SPY bars for trend analysis."""
        try:
            from app.data.data_manager import data_manager
            bars = data_manager.get_bars_from_memory("SPY", limit=limit)
            if bars and len(bars) >= 14:
                return bars
            bars = data_manager.get_today_session_bars("SPY")
            if bars and len(bars) >= 14:
                return bars[-limit:] if len(bars) > limit else bars
            bars = data_manager.get_today_5m_bars("SPY")
            if bars and len(bars) >= 14:
                return bars[-limit:] if len(bars) > limit else bars
            return []
        except Exception as e:
            print(f"[REGIME] Error fetching SPY bars: {e}")
            return []
    
    def _calculate_spy_trend(self, bars: list) -> str:
        """Determine SPY trend direction using EMAs."""
        if len(bars) < 20:
            return "NEUTRAL"
        try:
            closes = [b["close"] for b in bars[-20:]]
            ema9 = self._calculate_ema(closes[-9:], 9)
            ema20 = self._calculate_ema(closes, 20)
            current_price = closes[-1]
            
            if ema9 > ema20 and current_price > ema9:
                return "BULL"
            elif ema9 < ema20 and current_price < ema9:
                return "BEAR"
            else:
                return "NEUTRAL"
        except Exception:
            return "NEUTRAL"
    
    def _calculate_adx(self, bars: list, period: int = 14) -> Optional[float]:
        """
        Calculate ADX using Wilder's smoothing (proper implementation).

        Fix (Mar 12, 2026): Previous version returned a single raw DX snapshot
        using a simple EMA on the last 14 bars — this produced values of 0–5
        early in the session, causing CHOPPY regime blocks for the first 60–90
        minutes every day.

        Correct Wilder's ADX algorithm:
          1. Compute TR, +DM, -DM for each bar
          2. Seed smoothed values with simple sum over first `period` bars
          3. Apply Wilder's RMA: smoothed = smoothed - (smoothed / period) + current
          4. DI± = smoothed_DM / smoothed_TR * 100
          5. DX  = |+DI - -DI| / (+DI + -DI) * 100
          6. ADX = Wilder's RMA of DX over `period` bars

        Requires len(bars) >= period * 2 + 1 for a valid seed + one ADX update.
        Returns None if insufficient bars.
        """
        min_bars = period * 2 + 1
        if len(bars) < min_bars:
            return None
        try:
            trs, plus_dms, minus_dms = [], [], []
            for i in range(1, len(bars)):
                high      = bars[i]["high"]
                low       = bars[i]["low"]
                prev_close = bars[i - 1]["close"]
                prev_high  = bars[i - 1]["high"]
                prev_low   = bars[i - 1]["low"]

                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)

                up_move   = high - prev_high
                down_move = prev_low - low
                plus_dms.append(up_move   if up_move   > down_move and up_move   > 0 else 0.0)
                minus_dms.append(down_move if down_move > up_move   and down_move > 0 else 0.0)

            # Seed: simple sum of first `period` values (Wilder's initialisation)
            s_tr       = sum(trs[:period])
            s_plus_dm  = sum(plus_dms[:period])
            s_minus_dm = sum(minus_dms[:period])

            def _di(s_dm, s_tr):
                return (s_dm / s_tr * 100) if s_tr > 0 else 0.0

            def _dx(pdi, mdi):
                return abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0.0

            # Seed ADX with first DX
            adx = _dx(_di(s_plus_dm, s_tr), _di(s_minus_dm, s_tr))

            # Wilder's RMA over remaining bars
            for i in range(period, len(trs)):
                s_tr       = s_tr       - (s_tr       / period) + trs[i]
                s_plus_dm  = s_plus_dm  - (s_plus_dm  / period) + plus_dms[i]
                s_minus_dm = s_minus_dm - (s_minus_dm / period) + minus_dms[i]
                dx  = _dx(_di(s_plus_dm, s_tr), _di(s_minus_dm, s_tr))
                adx = adx - (adx / period) + dx

            return round(adx, 2)

        except Exception as e:
            print(f"[REGIME] ADX calculation error: {e}")
            return None
    
    def _calculate_ema(self, values: list, period: int) -> float:
        """Calculate Exponential Moving Average."""
        if not values:
            return 0.0
        multiplier = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = (value * multiplier) + (ema * (1 - multiplier))
        return ema
    
    def _classify_regime(self, vix: float, adx: Optional[float],
                         spy_trend: str, spy_bars: list) -> Tuple[str, bool, str]:
        """
        Classify market regime and determine if favorable for trading.

        Phase 3A Patch: VIX-aware ADX thresholds replace the hardcoded 25.
        Elevated VIX environments naturally compress ADX readings — a market
        moving directionally with VIX=25 will often show ADX=10–14, which is
        still a tradeable trend. The thresholds scale accordingly:

          VIX > 25  → effective_adx_threshold = 12.0
          VIX > 20  → effective_adx_threshold = 15.0
          VIX ≤ 20  → effective_adx_threshold = 20.0
        """
        # Hard blocks: extreme volatility
        if vix >= 35:
            return ("VOLATILE", False, f"VIX too high ({vix:.1f}) - extreme fear/greed")
        if vix >= 30:
            return ("VOLATILE", False, f"VIX elevated ({vix:.1f}) - elevated volatility")

        # Whipsaw check: too many candle direction reversals
        if len(spy_bars) >= 10:
            recent_bars = spy_bars[-10:]
            reversals = sum(
                1 for i in range(1, len(recent_bars))
                if (recent_bars[i]["close"] - recent_bars[i]["open"]) *
                   (recent_bars[i-1]["close"] - recent_bars[i-1]["open"]) < 0
            )
            if reversals >= 6:
                return ("CHOPPY", False, f"Whipsaw action ({reversals}/10 reversals) - avoid")

        # VIX-aware dynamic ADX threshold
        if vix > 25:
            effective_adx_threshold = 12.0
        elif vix > 20:
            effective_adx_threshold = 15.0
        else:
            effective_adx_threshold = 20.0

        if adx is not None:
            if adx >= effective_adx_threshold:
                if vix < 25:
                    return (
                        "TRENDING", True,
                        f"Strong {spy_trend} trend (ADX: {adx:.0f} ≥ {effective_adx_threshold:.0f}, VIX: {vix:.1f})"
                    )
                else:
                    return (
                        "TRENDING", True,
                        f"{spy_trend} trend with elevated VIX (ADX: {adx:.0f} ≥ {effective_adx_threshold:.0f}, VIX: {vix:.1f})"
                    )
            else:
                return (
                    "CHOPPY", False,
                    f"Weak trend (ADX: {adx:.0f} < {effective_adx_threshold:.0f}) - range-bound"
                )

        if vix < 20 and spy_trend != "NEUTRAL":
            return ("TRENDING", True, f"Low VIX ({vix:.1f}), {spy_trend} bias")

        return ("CHOPPY", False, f"Neutral conditions (VIX: {vix:.1f})")
    
    def print_regime_summary(self) -> None:
        """Print formatted regime summary to console."""
        state = self.get_regime_state()
        emoji = {"TRENDING": "📈" if state.favorable else "📉", "CHOPPY": "〰️", "VOLATILE": "⚡"}[state.regime]
        status = "✅ FAVORABLE" if state.favorable else "🚫 UNFAVORABLE"
        
        print("\n" + "=" * 70)
        print(f"{emoji}  MARKET REGIME: {state.regime}  {status}")
        print("=" * 70)
        print(f"VIX:       {state.vix:.2f}")
        print(f"SPY Trend: {state.spy_trend}")
        if state.adx:
            print(f"ADX:       {state.adx:.1f} (trend strength)")
        print(f"Reason:    {state.reason}")
        print("=" * 70 + "\n")
    
    def reset_cache(self) -> None:
        """Clear cached regime state."""
        self._cache = None
        self._last_check = 0
        print("[REGIME] Cache cleared")


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONS FILTER (from options_filter.py)
# ══════════════════════════════════════════════════════════════════════════════

class OptionsFilter:
    """Filters and analyzes options chains for trading signals."""

    def __init__(self):
        self.api_key = config.EODHD_API_KEY
        self.base_url = "https://eodhd.com/api/mp/unicornbay/options/contracts"

    def _normalize_v2_chain(self, v2_data: List[Dict]) -> Dict:
        """Convert marketplace flat-list format to legacy nested structure."""
        nested: Dict = {}
        for item in v2_data:
            attrs = item.get("attributes", item)
            exp = attrs.get("exp_date", "")
            ctype = attrs.get("type", "").lower()
            strike = str(attrs.get("strike", ""))
            if not exp or ctype not in ("call", "put") or not strike:
                continue
            if exp not in nested:
                nested[exp] = {"calls": {}, "puts": {}}
            bucket = "calls" if ctype == "call" else "puts"
            nested[exp][bucket][strike] = {
                "openInterest": attrs.get("open_interest", 0),
                "volume": attrs.get("volume", 0),
                "bid": attrs.get("bid", 0),
                "ask": attrs.get("ask", 0),
                "delta": attrs.get("delta", 0),
                "impliedVolatility": attrs.get("volatility", 0),
                "theta": attrs.get("theta", 0),
                "gamma": attrs.get("gamma", 0),
                "vega": attrs.get("vega", 0),
                "rho": attrs.get("rho", 0),
                "dte": attrs.get("dte", 0),
            }
        return nested

    def get_options_chain(self, ticker: str) -> Optional[Dict]:
        """Fetch options chain from EODHD Marketplace."""
        today = datetime.now()
        params = {
            "filter[underlying_symbol]": ticker,
            "filter[exp_date_from]": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
            "filter[exp_date_to]": (today + timedelta(days=30)).strftime("%Y-%m-%d"),
            "sort": "exp_date",
            "limit": 1000,
            "api_token": self.api_key,
        }
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            raw = response.json()
            items = raw.get("data", [])
            if isinstance(items, list):
                return {"data": self._normalize_v2_chain(items)}
            return raw
        except Exception as e:
            print(f"[OPTIONS] Error fetching chain for {ticker}: {e}")
            return None

    def filter_by_liquidity(self, option: Dict) -> bool:
        oi = option.get("openInterest", 0)
        volume = option.get("volume", 0)
        bid = option.get("bid", 0)
        ask = option.get("ask", 0)
        if oi < config.MIN_OPTION_OI or volume < config.MIN_OPTION_VOLUME:
            return False
        if ask > 0 and bid > 0:
            mid = (bid + ask) / 2
            if mid > 0 and (ask - bid) / mid > config.MAX_BID_ASK_SPREAD_PCT:
                return False
        return True

    def filter_by_delta(self, option: Dict) -> bool:
        d = abs(option.get("delta", 0))
        return config.TARGET_DELTA_MIN <= d <= config.TARGET_DELTA_MAX

    def filter_by_dte(self, expiration_date: str) -> Tuple[bool, int]:
        try:
            dte = (datetime.strptime(expiration_date, "%Y-%m-%d") - datetime.now()).days
            return (config.MIN_DTE <= dte <= config.MAX_DTE), dte
        except Exception:
            return False, 0

    def calculate_expected_move(self, price: float, iv: float, dte: int) -> float:
        return round(price * iv * ((dte / 365) ** 0.5), 2)

    def find_best_strike(self, ticker, direction, entry_price, target_price, stop_price=0.0):
        """
        Find optimal option strike with parallel Greeks fetching.
        Uses _OPTIMIZER_AVAILABLE for 5-10x speed improvement.
        """
        if _OPTIMIZER_AVAILABLE:
            try:
                strikes = get_optimal_strikes_sync(
                    ticker=ticker,
                    current_price=entry_price,
                    direction=direction,
                    target_delta_min=config.TARGET_DELTA_MIN,
                    target_delta_max=config.TARGET_DELTA_MAX
                )

                if not strikes:
                    print(f"[OPTIONS] {ticker}: No strikes from optimizer")
                    return None

                best_option = strikes[0]
                return best_option

            except Exception as e:
                print(f"[OPTIONS] {ticker}: Optimizer error - {e}, falling back to legacy")
                # Fall through to legacy code below

        chain = self.get_options_chain(ticker)
        if not chain:
            return None

        best_option = None
        best_score = -1

        for expiration_date, options_data in chain.get("data", {}).items():
            is_valid_dte, dte = self.filter_by_dte(expiration_date)
            if not is_valid_dte:
                continue

            option_type = "calls" if direction == "bull" else "puts"
            is_call = (direction == "bull")

            for strike_str, option in options_data.get(option_type, {}).items():
                strike = float(strike_str)
                if not self.filter_by_liquidity(option):
                    continue
                if not self.filter_by_delta(option):
                    continue
                if is_call and not (entry_price * 0.95 <= strike <= entry_price * 1.10):
                    continue
                if not is_call and not (entry_price * 0.90 <= strike <= entry_price * 1.05):
                    continue

                bid = option.get("bid", 0)
                ask = option.get("ask", 0)
                mid = (bid + ask) / 2 if (bid and ask) else 0

                dte_score = 100 - abs(dte - config.IDEAL_DTE)
                oi_score = min(option.get("openInterest", 0) / 1000, 100)
                spread_pct = (ask - bid) / mid if mid > 0 else 999
                spread_score = max(0, 100 - spread_pct * 1000)
                total_score = dte_score + oi_score + spread_score

                if total_score > best_score:
                    best_score = total_score
                    iv = option.get("impliedVolatility", 0)
                    best_option = {
                        "strike": strike, "expiration": expiration_date,
                        "delta": option.get("delta", 0), "theta": option.get("theta", 0),
                        "oi": option.get("openInterest", 0), "volume": option.get("volume", 0),
                        "bid": bid, "ask": ask, "iv": iv, "dte": dte,
                        "expected_move": self.calculate_expected_move(entry_price, iv, dte),
                        "score": total_score
                    }

        if not best_option:
            return None

        # IVR enrichment
        iv = best_option.get("iv", 0)
        if iv and iv > 0:
            store_iv_observation(ticker, iv)
            ivr, obs, reliable = compute_ivr(ticker, iv)
            mult, label = ivr_to_confidence_multiplier(ivr, reliable)
            best_option.update({
                "ivr": ivr, "ivr_obs": obs, "ivr_reliable": reliable,
                "ivr_multiplier": mult, "ivr_label": label
            })
            status = f"IVR={ivr:.0f}" if (ivr is not None and reliable) else "IVR-BUILDING"
            print(f"[IVR] {ticker}: IV={iv*100:.1f}% | {status} ({obs} obs) | {mult:.2f}x [{label}]")
        else:
            best_option.update({
                "ivr": None, "ivr_obs": 0, "ivr_reliable": False,
                "ivr_multiplier": 1.0, "ivr_label": "IVR-NO-DATA"
            })

        # UOA enrichment
        try:
            uoa_result = scan_chain_for_uoa(ticker, direction, entry_price)
            best_option.update(uoa_result)
            if uoa_result.get('uoa_detected'):
                print(f"[UOA] {ticker}: {format_uoa_summary(uoa_result)}")
            else:
                print(f"[UOA] {ticker}: No unusual activity detected")
        except Exception as e:
            print(f"[UOA] {ticker} error: {e}")
            best_option.update({
                "uoa_multiplier": 1.0, "uoa_label": "UOA-ERROR",
                "uoa_detected": False, "uoa_aligned": False,
                "uoa_opposing": False, "uoa_max_score": 0.0,
                "uoa_top_aligned": [], "uoa_top_opposing": []
            })

        # GEX enrichment
        gex_stop_ref = stop_price if stop_price > 0 else best_option.get("strike", entry_price)
        try:
            gex_data = compute_gex_levels(chain, entry_price)
            if gex_data["has_data"]:
                gex_mult, gex_label, gex_ctx = get_gex_signal_context(
                    gex_data, direction, entry_price, gex_stop_ref, target_price
                )
                best_option.update({
                    "gex_multiplier": gex_mult, "gex_label": gex_label,
                    "gamma_pin": gex_data["gamma_pin"], "gamma_flip": gex_data["gamma_flip"],
                    "neg_gex_zone": gex_data["neg_gex_zone"], "total_gex": gex_data["total_gex"],
                    "gex_top_pos": gex_data["top_positive"], "gex_top_neg": gex_data["top_negative"]
                })
                flip_str = f"${gex_data['gamma_flip']:.2f}" if gex_data["gamma_flip"] else "N/A"
                pin_str = f"${gex_data['gamma_pin']:.2f}" if gex_data["gamma_pin"] else "N/A"
                zone = "NEG" if gex_data["neg_gex_zone"] else "POS"
                print(f"[GEX] {ticker}: Pin={pin_str} | Flip={flip_str} | Zone={zone} | {gex_mult:.2f}x [{gex_label}]")
            else:
                print(f"[GEX] {ticker}: No gamma data in chain")
                best_option.update({
                    "gex_multiplier": 1.0, "gex_label": "GEX-NO-DATA",
                    "gamma_pin": None, "gamma_flip": None,
                    "neg_gex_zone": False, "total_gex": 0.0,
                    "gex_top_pos": [], "gex_top_neg": []
                })
        except Exception as e:
            print(f"[GEX] {ticker} error: {e}")
            best_option.update({
                "gex_multiplier": 1.0, "gex_label": "GEX-ERROR",
                "gamma_pin": None, "gamma_flip": None,
                "neg_gex_zone": False, "total_gex": 0.0,
                "gex_top_pos": [], "gex_top_neg": []
            })

        # Limit price entry enrichment
        _bid = best_option["bid"]
        _ask = best_option["ask"]
        _mid = round((_bid + _ask) / 2, 2) if (_bid and _ask) else 0.0
        _spd = round(((_ask - _bid) / _mid) * 100, 1) if _mid > 0 else 0.0
        _ctype = "CALL" if direction == "bull" else "PUT"
        try:
            _m = int(best_option["expiration"][5:7])
            _d = int(best_option["expiration"][8:10])
            _exp_label = f"{_m}/{_d}"
        except Exception:
            _exp_label = best_option["expiration"]
        best_option.update({
            "mid": _mid, "limit_entry": _mid, "max_entry": _ask,
            "contract_type": _ctype, "spread_pct": _spd,
            "contract_label": f"{ticker} ${int(best_option['strike'])}{_ctype[0]} {_exp_label}",
        })
        print(f"[LIMIT-ENTRY] {ticker}: {_ctype} ${int(best_option['strike'])} Bid:${_bid:.2f}  Mid:${_mid:.2f}  Ask:${_ask:.2f}  Spread:{_spd:.1f}%")

        return best_option

    def validate_signal_for_options(self, ticker, direction, entry_price,
                                    target_price, stop_price=0.0) -> Tuple[bool, Optional[Dict], str]:
        """Validate signal for options trading."""
        best_strike = self.find_best_strike(ticker, direction, entry_price, target_price, stop_price=stop_price)
        if not best_strike:
            return False, None, "No suitable options found"

        if abs(target_price - entry_price) > best_strike["expected_move"] * 2:
            return False, best_strike, "Target exceeds 2x expected move"

        if best_strike.get("iv", 0) > 1.0:
            return False, best_strike, f"IV too high ({best_strike['iv']*100:.1f}%)"

        dte = best_strike["dte"]
        mid = (best_strike["bid"] + best_strike["ask"]) / 2 if (best_strike.get("bid") and best_strike.get("ask")) else 0
        theta = abs(best_strike.get("theta", 0))
        if mid > 0 and dte > 0 and theta > 0:
            theta_pct = theta / mid
            if theta_pct > config.MAX_THETA_DECAY_PCT:
                return False, best_strike, f"Theta decay too high ({theta_pct:.1%}/day vs max {config.MAX_THETA_DECAY_PCT:.1%})"

        return True, best_strike, "Options signal validated"


def get_options_recommendation(ticker, direction, entry_price, target_price, stop_price=0.0) -> Optional[Dict]:
    """Get options recommendation (legacy compatibility function)."""
    f = OptionsFilter()
    is_valid, data, reason = f.validate_signal_for_options(ticker, direction, entry_price, target_price, stop_price=stop_price)
    if is_valid and data:
        print(f"[OPTIONS] ✅ {ticker}: {reason}")
        return data
    print(f"[OPTIONS] ⚠️ {ticker}: {reason}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL VALIDATOR (from signal_validator.py)
# ══════════════════════════════════════════════════════════════════════════════

def get_time_of_day_quality(signal_time: datetime) -> Tuple[str, float]:
    """
    Assess signal quality based on time of day.
    Returns: (zone_label, confidence_adjustment)
    """
    current_time = signal_time.time()
    
    if dtime(9, 30) <= current_time < dtime(10, 30):
        return 'MORNING_SESSION', 0.05
    if dtime(15, 0) <= current_time < dtime(16, 0):
        return 'POWER_HOUR', 0.05
    if dtime(10, 30) <= current_time < dtime(11, 30):
        return 'LATE_MORNING', 0.02
    if dtime(13, 30) <= current_time < dtime(15, 0):
        return 'EARLY_AFTERNOON', 0.02
    if dtime(11, 30) <= current_time < dtime(13, 0):
        return 'DEAD_ZONE', -0.03
    if dtime(13, 0) <= current_time < dtime(13, 30):
        return 'LUNCH_RECOVERY', 0.0
    return 'OFF_HOURS', 0.0


class SignalValidator:
    """Multi-indicator signal validation engine."""
    
    def __init__(
        self,
        min_final_confidence: float = 0.50,
        min_adx: float = 15.0,
        min_volume_ratio: float = 1.5,
        enable_vpvr: bool = True,
        enable_daily_bias: bool = True,
        enable_time_filter: bool = True,
        enable_ema_stack: bool = True,
        enable_rsi_divergence: bool = True,
        min_bias_confidence: float = 0.65,
        strict_mode: bool = False
    ):
        self.min_final_confidence = min_final_confidence
        self.min_adx = min_adx
        self.min_volume_ratio = min_volume_ratio
        self.enable_vpvr = enable_vpvr and VPVR_ENABLED
        self.enable_daily_bias = enable_daily_bias and BIAS_ENGINE_ENABLED
        self.enable_time_filter = enable_time_filter
        self.enable_ema_stack = enable_ema_stack
        self.enable_rsi_divergence = enable_rsi_divergence
        self.min_bias_confidence = min_bias_confidence
        self.strict_mode = strict_mode
        
        self.validation_stats = {
            'total_validated': 0, 'passed': 0, 'filtered': 0, 'boosted': 0,
            'bias_penalized': 0, 'vpvr_rescued': 0, 'vpvr_scored': 0,
            'time_zones': {}, 'ema_stack_aligned': 0, 'rsi_divergence_detected': 0,
            'confidence_filtered': 0
        }
        
        # Production initialization banner
        print("[VALIDATOR] ╔════════════════════════════════════════════════╗")
        print("[VALIDATOR] ║  SIGNAL VALIDATOR - PRODUCTION CONFIG          ║")
        print(f"[VALIDATOR] ║  Min Final Confidence: {int(min_final_confidence*100)}%{' '*(24-len(str(int(min_final_confidence*100))))}║")
        print("[VALIDATOR] ╚════════════════════════════════════════════════╝")
        
        if self.enable_daily_bias:
            print(f"[VALIDATOR] Daily bias penalty active (min confidence: {min_bias_confidence*100:.0f}%)")
            print(f"[VALIDATOR] ⭐ Counter-trend signals penalized but can be rescued by VPVR")
        if self.enable_time_filter:
            print(f"[VALIDATOR] Time-of-day quality scoring enabled")
        if self.enable_ema_stack:
            print(f"[VALIDATOR] EMA stack confirmation enabled")
        if self.enable_rsi_divergence:
            print(f"[VALIDATOR] RSI divergence detection enabled")
        if self.enable_vpvr:
            print(f"[VALIDATOR] VPVR entry scoring enabled")
        print(f"[VALIDATOR] ADX threshold: {min_adx} (VIX-aware dynamic threshold in regime filter)")
        print(f"[VALIDATOR] Volume ratio: {min_volume_ratio}x")
    
    def validate_signal(
        self,
        ticker: str,
        signal_direction: str,
        current_price: float,
        current_volume: int,
        base_confidence: float
    ) -> Tuple[bool, float, Dict]:
        """Validate signal with multi-indicator confirmation."""
        self.validation_stats['total_validated'] += 1
        signal_time = datetime.now(ET)
        
        metadata = {
            'timestamp': signal_time.isoformat(),
            'ticker': ticker,
            'direction': signal_direction,
            'base_confidence': base_confidence,
            'checks': {}
        }
        
        confidence_adjustment = 0.0
        failed_checks = []
        passed_checks = []
        counter_trend_penalty = 0.0
        needs_vpvr_rescue = False
        
        # Daily Bias Check
        if self.enable_daily_bias and bias_engine:
            try:
                should_filter, bias_reason = bias_engine.should_filter_signal(ticker, signal_direction)
                bias_data = bias_engine._get_bias_dict()
                
                metadata['checks']['daily_bias'] = {
                    'bias': bias_data['bias'],
                    'confidence': bias_data['confidence'],
                    'should_filter': should_filter,
                    'reason': bias_reason
                }
                
                if should_filter and bias_data['confidence'] >= self.min_bias_confidence:
                    counter_trend_penalty = -0.25
                    confidence_adjustment += counter_trend_penalty
                    failed_checks.append('BIAS_COUNTER_TREND_STRONG')
                    needs_vpvr_rescue = True
                    self.validation_stats['bias_penalized'] += 1
                    print(f"[VALIDATOR] ⚠️  {ticker} counter-trend to {bias_data['bias']} bias (-25%) - VPVR can rescue")
                elif bias_data['bias'] != 'NEUTRAL':
                    if not should_filter:
                        bias_boost = bias_data['confidence'] * 0.10
                        confidence_adjustment += bias_boost
                        passed_checks.append(f"BIAS_ALIGNED_{bias_data['bias']}")
                    else:
                        passed_checks.append('BIAS_WEAK')
            except Exception as e:
                metadata['checks']['daily_bias'] = {'error': str(e)}
        
        # Regime Filter Check
        regime_filter = get_regime_filter()
        try:
            regime_state = regime_filter.get_regime_state()
            metadata['checks']['regime_filter'] = {
                'regime': regime_state.regime,
                'vix': regime_state.vix,
                'spy_trend': regime_state.spy_trend,
                'adx': regime_state.adx,
                'favorable': regime_state.favorable,
                'reason': regime_state.reason
            }
            
            if not regime_state.favorable:
                regime_penalty = -0.30
                confidence_adjustment += regime_penalty
                failed_checks.append(f'REGIME_{regime_state.regime}')
                print(f"[VALIDATOR] WARNING {ticker} in {regime_state.regime} regime (-30%): {regime_state.reason}")
            elif regime_state.regime == 'TRENDING':
                regime_boost = 0.05
                confidence_adjustment += regime_boost
                passed_checks.append('REGIME_TRENDING')
                print(f"[VALIDATOR] OK {ticker} in TRENDING regime (+5%): {regime_state.reason}")
            else:
                passed_checks.append('REGIME_NEUTRAL')
        except Exception as e:
            metadata['checks']['regime_filter'] = {'error': str(e)}
        
        # Time-of-Day Check
        if self.enable_time_filter:
            try:
                time_zone, time_adjustment = get_time_of_day_quality(signal_time)
                metadata['checks']['time_of_day'] = {
                    'zone': time_zone,
                    'time': signal_time.strftime('%H:%M:%S'),
                    'adjustment': time_adjustment
                }
                confidence_adjustment += time_adjustment
                if time_zone not in self.validation_stats['time_zones']:
                    self.validation_stats['time_zones'][time_zone] = 0
                self.validation_stats['time_zones'][time_zone] += 1
                if time_adjustment > 0:
                    passed_checks.append(f'TIME_{time_zone}')
                elif time_adjustment < 0:
                    failed_checks.append(f'TIME_{time_zone}')
                else:
                    passed_checks.append(f'TIME_NEUTRAL')
            except Exception as e:
                metadata['checks']['time_of_day'] = {'error': str(e)}
        
        # EMA Stack Check
        if self.enable_ema_stack:
            try:
                ema9_data = ti.fetch_ema(ticker, period=9)
                ema20_data = ti.fetch_ema(ticker, period=20)
                ema50_data = ti.fetch_ema(ticker, period=50)
                
                if all([ema9_data, ema20_data, ema50_data]):
                    ema9 = ti.get_latest_value(ema9_data, 'ema')
                    ema20 = ti.get_latest_value(ema20_data, 'ema')
                    ema50 = ti.get_latest_value(ema50_data, 'ema')
                    
                    if all([ema9, ema20, ema50]):
                        if signal_direction == 'BUY':
                            full_stack = (current_price > ema9 > ema20 > ema50)
                            partial_stack = (current_price > ema9 and ema9 > ema20)
                        else:
                            full_stack = (current_price < ema9 < ema20 < ema50)
                            partial_stack = (current_price < ema9 and ema9 < ema20)
                        
                        metadata['checks']['ema_stack'] = {
                            'ema9': round(ema9, 2),
                            'ema20': round(ema20, 2),
                            'ema50': round(ema50, 2),
                            'full_stack': full_stack,
                            'partial_stack': partial_stack
                        }
                        
                        if full_stack:
                            confidence_adjustment += 0.07
                            passed_checks.append('EMA_FULL_STACK')
                            self.validation_stats['ema_stack_aligned'] += 1
                        elif partial_stack:
                            confidence_adjustment += 0.03
                            passed_checks.append('EMA_PARTIAL_STACK')
                        else:
                            confidence_adjustment -= 0.04
                            failed_checks.append('EMA_NO_STACK')
                    else:
                        metadata['checks']['ema_stack'] = {'error': 'Missing EMA values'}
                else:
                    metadata['checks']['ema_stack'] = {'error': 'Failed to fetch EMA data'}
            except Exception as e:
                metadata['checks']['ema_stack'] = {'error': str(e)}
        
        # RSI Divergence Check
        if self.enable_rsi_divergence:
            try:
                div_result, div_details = ti.check_rsi_divergence(ticker, signal_direction, lookback_bars=10)
                if div_result and div_details:
                    metadata['checks']['rsi_divergence'] = div_details
                    if div_result == 'BEARISH_DIV':
                        if signal_direction == 'SELL':
                            confidence_adjustment += 0.05
                            passed_checks.append('RSI_DIV_FAVORABLE')
                        else:
                            confidence_adjustment -= 0.05
                            failed_checks.append('RSI_DIV_WARNING')
                        self.validation_stats['rsi_divergence_detected'] += 1
                    elif div_result == 'BULLISH_DIV':
                        if signal_direction == 'BUY':
                            confidence_adjustment += 0.05
                            passed_checks.append('RSI_DIV_FAVORABLE')
                        else:
                            confidence_adjustment -= 0.05
                            failed_checks.append('RSI_DIV_WARNING')
                        self.validation_stats['rsi_divergence_detected'] += 1
            except Exception as e:
                metadata['checks']['rsi_divergence'] = {'error': str(e)}
        
        # ADX Check
        try:
            is_trending, adx_value = ti.check_trend_strength(ticker, self.min_adx)
            metadata['checks']['adx'] = {
                'value': adx_value,
                'passed': is_trending,
                'threshold': self.min_adx
            }
            if adx_value:
                if adx_value >= 40:
                    confidence_adjustment += 0.05
                    passed_checks.append('ADX_STRONG')
                elif adx_value >= self.min_adx:
                    passed_checks.append('ADX_OK')
                else:
                    confidence_adjustment -= 0.05
                    failed_checks.append('ADX_WEAK')
        except Exception as e:
            metadata['checks']['adx'] = {'error': str(e)}
        
        # Volume Check
        try:
            is_confirmed, volume_ratio = ti.check_volume_confirmation(ticker, current_volume, self.min_volume_ratio)
            metadata['checks']['volume'] = {
                'ratio': volume_ratio,
                'passed': is_confirmed,
                'threshold': self.min_volume_ratio
            }
            if volume_ratio:
                if volume_ratio >= 2.0:
                    confidence_adjustment += 0.10
                    passed_checks.append('VOLUME_STRONG')
                elif volume_ratio >= self.min_volume_ratio:
                    confidence_adjustment += 0.03
                    passed_checks.append('VOLUME_OK')
                else:
                    confidence_adjustment -= 0.08
                    failed_checks.append('VOLUME_WEAK')
        except Exception as e:
            metadata['checks']['volume'] = {'error': str(e)}
        
        # DMI Check
        try:
            trend_direction = ti.get_trend_direction(ticker)
            metadata['checks']['dmi'] = {'direction': trend_direction}
            if trend_direction:
                expected_direction = 'BULLISH' if signal_direction == 'BUY' else 'BEARISH'
                if trend_direction == expected_direction:
                    confidence_adjustment += 0.05
                    passed_checks.append('DMI_ALIGNED')
                else:
                    confidence_adjustment -= 0.10
                    failed_checks.append('DMI_CONFLICT')
        except Exception as e:
            metadata['checks']['dmi'] = {'error': str(e)}
        
        # CCI Check
        try:
            cci_data = ti.fetch_cci(ticker)
            if cci_data:
                cci_value = ti.get_latest_value(cci_data, 'cci')
                metadata['checks']['cci'] = {'value': cci_value}
                if cci_value is not None:
                    if signal_direction == 'BUY':
                        if cci_value < -100:
                            confidence_adjustment += 0.05
                            passed_checks.append('CCI_OVERSOLD')
                        elif cci_value > 100:
                            confidence_adjustment -= 0.05
                            failed_checks.append('CCI_OVERBOUGHT')
                    else:
                        if cci_value > 100:
                            confidence_adjustment += 0.05
                            passed_checks.append('CCI_OVERBOUGHT')
                        elif cci_value < -100:
                            confidence_adjustment -= 0.05
                            failed_checks.append('CCI_OVERSOLD')
        except Exception as e:
            metadata['checks']['cci'] = {'error': str(e)}
        
        # Bollinger Bands Check
        try:
            is_squeezed, band_width = ti.check_bollinger_squeeze(ticker)
            metadata['checks']['bbands'] = {
                'band_width': band_width,
                'is_squeezed': is_squeezed
            }
            if is_squeezed:
                confidence_adjustment += 0.05
                passed_checks.append('BB_SQUEEZE')
        except Exception as e:
            metadata['checks']['bbands'] = {'error': str(e)}
        
        # VPVR Check
        vpvr_rescue_applied = False
        if self.enable_vpvr and vpvr_calculator:
            try:
                from app.data.data_manager import data_manager
                bars = data_manager.get_today_session_bars(ticker)
                
                if bars and len(bars) >= 78:
                    vpvr = vpvr_calculator.calculate_vpvr(bars, lookback_bars=78)
                    
                    if vpvr and vpvr['poc'] is not None:
                        entry_score, entry_reason = vpvr_calculator.get_entry_score(current_price, vpvr)
                        
                        metadata['checks']['vpvr'] = {
                            'poc': vpvr['poc'],
                            'vah': vpvr['vah'],
                            'val': vpvr['val'],
                            'entry_score': round(entry_score, 2),
                            'entry_reason': entry_reason,
                            'hvn_zones': vpvr['hvn_zones'][:2] if len(vpvr['hvn_zones']) > 2 else vpvr['hvn_zones'],
                            'lvn_zones': vpvr['lvn_zones'][:2] if len(vpvr['lvn_zones']) > 2 else vpvr['lvn_zones']
                        }
                        
                        self.validation_stats['vpvr_scored'] += 1
                        
                        # VPVR Rescue Logic
                        if needs_vpvr_rescue and entry_score >= 0.85:
                            rescue_boost = abs(counter_trend_penalty) * 0.80
                            confidence_adjustment += rescue_boost
                            passed_checks.append('VPVR_RESCUE')
                            failed_checks.remove('BIAS_COUNTER_TREND_STRONG')
                            vpvr_rescue_applied = True
                            self.validation_stats['vpvr_rescued'] += 1
                            print(f"[VPVR] ✨ {ticker} RESCUED: Excellent entry at {entry_reason} overrides bias penalty (+{rescue_boost:.2%})")
                        
                        # Standard VPVR scoring
                        if entry_score >= 0.85:
                            if not vpvr_rescue_applied:
                                confidence_adjustment += 0.08
                                passed_checks.append('VPVR_STRONG')
                            print(f"[VPVR] ✅ {ticker} strong entry: {entry_reason}")
                        elif entry_score >= 0.70:
                            confidence_adjustment += 0.03
                            passed_checks.append('VPVR_GOOD')
                            print(f"[VPVR] 🟢 {ticker} good entry: {entry_reason}")
                        elif entry_score < 0.50:
                            confidence_adjustment -= 0.05
                            failed_checks.append('VPVR_WEAK')
                            print(f"[VPVR] ⚠️  {ticker} weak entry: {entry_reason}")
                        else:
                            passed_checks.append('VPVR_NEUTRAL')
                            print(f"[VPVR] 🟡 {ticker} neutral entry: {entry_reason}")
                        
                        if vpvr_rescue_applied:
                            metadata['checks']['vpvr']['rescued'] = True
                    else:
                        metadata['checks']['vpvr'] = {'error': 'Insufficient VPVR data'}
                else:
                    metadata['checks']['vpvr'] = {'error': f'Need 78+ bars, got {len(bars) if bars else 0}'}
            except Exception as e:
                metadata['checks']['vpvr'] = {'error': str(e)}
        
        # Calculate final confidence
        adjusted_confidence = max(0.0, min(1.0, base_confidence + confidence_adjustment))
        
        if adjusted_confidence < self.min_final_confidence:
            should_pass = False
            self.validation_stats['confidence_filtered'] += 1
            print(f"[VALIDATOR] ❌ {ticker} FILTERED: {adjusted_confidence*100:.1f}% < {self.min_final_confidence*100:.1f}% minimum")
        elif self.strict_mode:
            critical_failures = ['VOLUME_WEAK', 'DMI_CONFLICT', 'ADX_WEAK']
            should_pass = not any(fail in failed_checks for fail in critical_failures)
        else:
            should_pass = len(passed_checks) >= len(failed_checks)
        
        # Update stats
        if should_pass:
            self.validation_stats['passed'] += 1
            if confidence_adjustment > 0:
                self.validation_stats['boosted'] += 1
        else:
            self.validation_stats['filtered'] += 1
        
        # Add summary to metadata
        metadata['summary'] = {
            'should_pass': should_pass,
            'adjusted_confidence': round(adjusted_confidence, 3),
            'confidence_adjustment': round(confidence_adjustment, 3),
            'passed_checks': passed_checks,
            'failed_checks': failed_checks,
            'check_score': f"{len(passed_checks)}/{len(passed_checks) + len(failed_checks)}",
            'vpvr_rescued': vpvr_rescue_applied,
            'min_confidence_met': adjusted_confidence >= self.min_final_confidence
        }
        
        return should_pass, adjusted_confidence, metadata
    
    def print_validation_summary(self, ticker: str, metadata: Dict) -> None:
        """Print formatted validation summary for production monitoring."""
        summary = metadata.get('summary', {})
        checks = metadata.get('checks', {})
        
        result = "✅ PASS" if summary.get('should_pass') else "❌ FAIL"
        
        conf = summary.get('adjusted_confidence', 0)
        if conf >= 0.80:
            quality = "🔵 STRONG"
        elif conf >= 0.65:
            quality = "🟢 GOOD"
        elif conf >= 0.50:
            quality = "🟡 FAIR"
        else:
            quality = "🔴 WEAK"
        
        base = metadata.get('base_confidence', 0)
        adj = summary.get('confidence_adjustment', 0)
        conf_change = f"+{adj*100:.1f}%" if adj >= 0 else f"{adj*100:.1f}%"
        
        print("=" * 70)
        print(f"🎯 VALIDATION SUMMARY: {ticker}")
        print("=" * 70)
        print(f"Result:     {result}")
        print(f"Quality:    {quality}")
        print(f"Confidence: {base*100:.1f}% → {conf*100:.1f}% ({conf_change})")
        print(f"Score:      {summary.get('check_score', 'N/A')} checks passed")
        print("")
        
        regime = checks.get('regime_filter', {})
        if regime and 'regime' in regime:
            status = "✓" if regime.get('favorable') else "✗"
            print(f"Regime:     {status} {regime['regime']} (VIX: {regime.get('vix', 0):.1f})")
            print("")
        
        passed = summary.get('passed_checks', [])
        if passed:
            print(f"Passed:     {', '.join(passed[:5])}")
            if len(passed) > 5:
                print(f"            +{len(passed)-5} more")
            print("")
        
        failed = summary.get('failed_checks', [])
        if failed:
            print(f"Failed:     {', '.join(failed)}")
            print("")
        
        if summary.get('vpvr_rescued'):
            print("✨ VPVR RESCUE: Counter-trend signal saved by excellent entry point!")
            print("")
        
        print("=" * 70)
    
    def get_validation_stats(self) -> Dict:
        """Get validation statistics."""
        total = self.validation_stats['total_validated']
        if total == 0:
            return self.validation_stats
        
        stats = {
            **self.validation_stats,
            'pass_rate': round(self.validation_stats['passed'] / total, 3),
            'filter_rate': round(self.validation_stats['filtered'] / total, 3),
            'boost_rate': round(self.validation_stats['boosted'] / total, 3),
            'bias_penalty_rate': round(self.validation_stats['bias_penalized'] / total, 3),
            'vpvr_rescue_rate': round(self.validation_stats['vpvr_rescued'] / total, 3),
            'ema_stack_rate': round(self.validation_stats['ema_stack_aligned'] / total, 3),
            'rsi_div_rate': round(self.validation_stats['rsi_divergence_detected'] / total, 3),
            'vpvr_scored_rate': round(self.validation_stats['vpvr_scored'] / total, 3),
            'confidence_filter_rate': round(self.validation_stats['confidence_filtered'] / total, 3)
        }
        
        if self.validation_stats['time_zones']:
            stats['time_zone_distribution'] = self.validation_stats['time_zones']
        
        return stats
    
    def reset_stats(self):
        """Reset validation statistics."""
        self.validation_stats = {
            'total_validated': 0, 'passed': 0, 'filtered': 0, 'boosted': 0,
            'bias_penalized': 0, 'vpvr_rescued': 0, 'vpvr_scored': 0,
            'time_zones': {}, 'ema_stack_aligned': 0, 'rsi_divergence_detected': 0,
            'confidence_filtered': 0
        }


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCES & FACTORY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

_validator_instance: Optional[SignalValidator] = None
_regime_filter_instance: Optional[RegimeFilter] = None
_options_filter_instance: Optional[OptionsFilter] = None


def get_validator() -> SignalValidator:
    """Get or create global validator instance."""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = SignalValidator(
            min_final_confidence=0.50,
            min_adx=15.0,
            min_volume_ratio=1.5,
            enable_vpvr=True,
            enable_daily_bias=True,
            enable_time_filter=True,
            enable_ema_stack=True,
            enable_rsi_divergence=True,
            min_bias_confidence=0.65,
            strict_mode=False
        )
    return _validator_instance


def get_regime_filter() -> RegimeFilter:
    """Get or create global regime filter instance."""
    global _regime_filter_instance
    if _regime_filter_instance is None:
        _regime_filter_instance = RegimeFilter()
    return _regime_filter_instance


def get_options_filter() -> OptionsFilter:
    """Get or create global options filter instance."""
    global _options_filter_instance
    if _options_filter_instance is None:
        _options_filter_instance = OptionsFilter()
    return _options_filter_instance


# Export all public APIs
__all__ = [
    # Classes
    'SignalValidator',
    'RegimeFilter',
    'RegimeState',
    'OptionsFilter',
    # Factory functions
    'get_validator',
    'get_regime_filter',
    'get_options_filter',
    # Helper functions
    'get_time_of_day_quality',
    'get_options_recommendation',
]


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("VALIDATION MODULE - Unified Testing")
    print("=" * 70 + "\n")
    
    print("Testing SignalValidator...")
    validator = get_validator()
    print(f"✅ SignalValidator initialized")
    
    print("\nTesting RegimeFilter...")
    regime = get_regime_filter()
    regime.print_regime_summary()
    
    print("\nTesting OptionsFilter...")
    opts = get_options_filter()
    print(f"✅ OptionsFilter initialized")
    
    print("\n" + "=" * 70)
    print("All validation components operational!")
    print("=" * 70)
