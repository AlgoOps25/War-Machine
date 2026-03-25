"""
Volume Profile Analyzer — Merged Production Module

Merged from:
  - app/validation/volume_profile.py  (live validation layer, sniper.py Step 6.6)
  - app/indicators/volume_profile.py  (algorithm engine, was unwired)

What this module does:
  Builds an intraday Volume Profile (POC, VAH, VAL, HVN, LVN) from OHLCV bars
  and exposes three layers of output for the War Machine signal pipeline:

  1. PROFILE BUILD  -- build_profile()         pure math, cached per ticker
  2. VALIDATION     -- validate_entry()         pass/fail gate, sniper.py Step 6.6
  3. ENRICHMENT     -- get_options_context()    options-specific signal dict

Algorithm choices (justified):
  - 50 price bins       : 20c resolution on $10 range (vs 50c at 20 bins)
  - Proportional vol    : volume spread across full bar H-L range (not 3-point sampling)
  - CME expansion       : value area expands toward highest adjacent volume (no left-bias)
  - Percentile HVN/LVN  : adaptive to session volume, returns volume_ratio for grading
  - 5-min cache         : one build per ticker per 5 min, critical for real-time loop
  - Pure Python         : no numpy dependency

sniper.py Step 6.6 call signature is UNCHANGED:
  is_valid, reason, vp_data = get_volume_analyzer().validate_entry(
      ticker, direction, entry_price, bars
  )
  vp_data now also includes: confidence_boost, options_bias (backwards compatible)
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import statistics

ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Simple in-process TTL cache for validate_entry results
# ---------------------------------------------------------------------------
_CACHE_TTL = timedelta(minutes=5)
_entry_cache: Dict[str, tuple] = {}   # ticker -> (result_tuple, expiry)


def _cache_key(ticker: str, direction: str, entry_price: float) -> str:
    return f"{ticker}:{direction}:{entry_price:.2f}"


class VolumeProfileAnalyzer:
    """
    Unified Volume Profile engine for real-time options trade detection.

    Responsibilities:
      - Build intraday volume profiles with institutional-grade precision
      - Validate breakout entries against volume structure
      - Enrich signals with options-specific context (HVN resistance,
        LVN thin zones, POC breakout conviction, confidence boost)
    """

    def __init__(
        self,
        num_bins: int = 50,
        value_area_pct: float = 0.70,
        high_volume_threshold: float = 1.5,
        cache_ttl_seconds: int = 300,
    ):
        self.num_bins = num_bins
        self.value_area_pct = value_area_pct
        self.high_volume_threshold = high_volume_threshold
        self.cache_ttl_seconds = cache_ttl_seconds
        # {ticker: (profile_dict, build_timestamp)}
        self._cache: Dict[str, Tuple[Dict, datetime]] = {}

    # =========================================================================
    # PROFILE BUILDING
    # =========================================================================

    def _calculate_price_levels(self, bars: List[Dict]) -> List[float]:
        highs = [b['high'] for b in bars]
        lows  = [b['low']  for b in bars]
        session_high = max(highs)
        session_low  = min(lows)
        price_range = session_high - session_low
        if price_range == 0:
            return [session_low]
        level_size = price_range / self.num_bins
        return [session_low + i * level_size for i in range(self.num_bins + 1)]

    def _distribute_volume(self, bars: List[Dict], price_levels: List[float]) -> Dict[float, float]:
        volume_at_price: Dict[float, float] = {level: 0.0 for level in price_levels}
        for bar in bars:
            bar_high   = bar['high']
            bar_low    = bar['low']
            bar_volume = bar['volume']
            levels_in_range = [
                lvl for lvl in price_levels
                if bar_low <= lvl <= bar_high
            ]
            if not levels_in_range:
                closest = min(price_levels, key=lambda x: abs(x - bar['close']))
                levels_in_range = [closest]
            vol_per_level = bar_volume / len(levels_in_range)
            for lvl in levels_in_range:
                volume_at_price[lvl] += vol_per_level
        return volume_at_price

    def _find_poc(self, volume_at_price: Dict[float, float]) -> float:
        if not volume_at_price:
            return 0.0
        return max(volume_at_price.items(), key=lambda x: x[1])[0]

    def _find_value_area(
        self, volume_at_price: Dict[float, float], poc: float
    ) -> Tuple[float, float]:
        if not volume_at_price:
            return 0.0, 0.0
        total_volume  = sum(volume_at_price.values())
        target_volume = total_volume * self.value_area_pct
        sorted_levels = sorted(volume_at_price.keys())
        try:
            poc_idx = sorted_levels.index(poc)
        except ValueError:
            return sorted_levels[0], sorted_levels[-1]
        va_volume   = volume_at_price[poc]
        va_low_idx  = poc_idx
        va_high_idx = poc_idx
        while va_volume < target_volume:
            can_up   = va_high_idx < len(sorted_levels) - 1
            can_down = va_low_idx  > 0
            if not can_up and not can_down:
                break
            vol_above = volume_at_price[sorted_levels[va_high_idx + 1]] if can_up   else -1
            vol_below = volume_at_price[sorted_levels[va_low_idx  - 1]] if can_down else -1
            if vol_above >= vol_below and can_up:
                va_high_idx += 1
                va_volume   += volume_at_price[sorted_levels[va_high_idx]]
            elif can_down:
                va_low_idx -= 1
                va_volume  += volume_at_price[sorted_levels[va_low_idx]]
            else:
                va_high_idx += 1
                va_volume   += volume_at_price[sorted_levels[va_high_idx]]
        return sorted_levels[va_low_idx], sorted_levels[va_high_idx]

    def _find_hvn_lvn(
        self, volume_at_price: Dict[float, float]
    ) -> Tuple[List[Dict], List[Dict]]:
        if not volume_at_price:
            return [], []
        volumes      = list(volume_at_price.values())
        avg_volume   = statistics.mean(volumes)
        sorted_vols  = sorted(volumes)
        n            = len(sorted_vols)
        p80_idx = max(0, int(n * 0.80) - 1)
        p20_idx = max(0, int(n * 0.20) - 1)
        threshold_high = sorted_vols[p80_idx]
        threshold_low  = sorted_vols[p20_idx]
        hvn_list: List[Dict] = []
        lvn_list: List[Dict] = []
        for price, volume in volume_at_price.items():
            ratio    = round(volume / avg_volume, 2) if avg_volume > 0 else 0.0
            pct_rank = round(sum(1 for v in volumes if v <= volume) / n, 2)
            node = {
                'price':           round(price, 2),
                'volume':          volume,
                'volume_ratio':    ratio,
                'percentile_rank': pct_rank,
            }
            if volume >= threshold_high:
                hvn_list.append(node)
            elif volume <= threshold_low and volume > 0:
                lvn_list.append(node)
        hvn_list.sort(key=lambda x: x['volume'], reverse=True)
        lvn_list.sort(key=lambda x: x['volume'])
        return hvn_list, lvn_list

    def _is_cache_valid(self, ticker: str) -> bool:
        if ticker not in self._cache:
            return False
        _, ts = self._cache[ticker]
        age = (datetime.now(ET) - ts).total_seconds()
        return age < self.cache_ttl_seconds

    def _empty_profile(self) -> Dict:
        return {
            'poc': 0, 'vah': 0, 'val': 0,
            'high_volume_nodes': [], 'low_volume_nodes': [],
            'hvn_levels': [], 'lvn_levels': [],
            'profile': [], 'total_volume': 0,
            'session_high': 0, 'session_low': 0,
            'timestamp': None,
        }

    # =========================================================================
    # PUBLIC -- PROFILE BUILD
    # =========================================================================

    def build_profile(
        self, bars: List[Dict], ticker: str = "unknown", use_cache: bool = True
    ) -> Dict:
        if use_cache and self._is_cache_valid(ticker):
            return self._cache[ticker][0]
        if not bars or len(bars) < 3:
            return self._empty_profile()
        price_levels = self._calculate_price_levels(bars)
        if len(price_levels) < 2:
            return self._empty_profile()
        volume_at_price    = self._distribute_volume(bars, price_levels)
        poc                = self._find_poc(volume_at_price)
        val, vah           = self._find_value_area(volume_at_price, poc)
        hvn_list, lvn_list = self._find_hvn_lvn(volume_at_price)
        total_volume = sum(b['volume'] for b in bars)
        profile_bins = [(round(p, 2), v) for p, v in sorted(volume_at_price.items())]
        result = {
            'poc':               round(poc, 2),
            'vah':               round(vah, 2),
            'val':               round(val, 2),
            'high_volume_nodes': hvn_list[:10],
            'low_volume_nodes':  lvn_list[:10],
            'hvn_levels':        [n['price'] for n in hvn_list[:10]],
            'lvn_levels':        [n['price'] for n in lvn_list[:10]],
            'profile':           profile_bins,
            'total_volume':      total_volume,
            'session_high':      round(max(b['high'] for b in bars), 2),
            'session_low':       round(min(b['low']  for b in bars), 2),
            'timestamp':         datetime.now(ET),
        }
        if use_cache:
            self._cache[ticker] = (result, datetime.now(ET))
        return result

    def analyze_session_profile(self, bars: List[Dict]) -> Dict:
        """Backwards-compat alias for build_profile()."""
        return self.build_profile(bars, ticker="_legacy", use_cache=False)

    def clear_cache(self, ticker: Optional[str] = None) -> None:
        if ticker:
            self._cache.pop(ticker, None)
        else:
            self._cache.clear()

    # =========================================================================
    # PUBLIC -- VALIDATION  (sniper.py Step 6.6 contract)
    # =========================================================================

    def validate_breakout(
        self, profile: Dict, breakout_price: float, direction: str
    ) -> Tuple[bool, str]:
        """
        Pass/fail check: is the breakout occurring at a favorable volume level?

        Logic (in priority order):
          1. Near LVN  -> PASS  (low resistance, price can move freely)
          2. Near HVN  -> FAIL  (institutional wall, high resistance)
          3. Bull above VAH -> PASS  (clearing institutional buying zone)
          4. Bull below VAL -> FAIL  (no institutional support)
          5. Bear below VAL -> PASS  (clearing institutional selling zone)
          6. Bear above VAH -> FAIL  (no institutional pressure)
          7. Default   -> PASS  (neutral volume context)
        """
        if not profile or profile.get('total_volume', 0) == 0:
            return True, "No volume profile data"

        poc        = profile['poc']
        vah        = profile['vah']
        val        = profile['val']
        hvn_levels = profile.get('hvn_levels', [])
        lvn_levels = profile.get('lvn_levels', [])

        for lvn in lvn_levels:
            if lvn > 0 and abs(breakout_price - lvn) / breakout_price < 0.01:
                return True, f"Breakout near LVN (${lvn:.2f}) - Low resistance"

        for hvn in hvn_levels:
            if hvn > 0 and abs(breakout_price - hvn) / breakout_price < 0.01:
                return False, f"Breakout near HVN (${hvn:.2f}) - High resistance"

        if direction == 'bull':
            if breakout_price > vah:
                return True,  f"Bullish breakout above VAH (${vah:.2f})"
            if breakout_price < val:
                return False, f"Bullish breakout below VAL (${val:.2f}) - Weak"
        else:
            if breakout_price < val:
                return True,  f"Bearish breakout below VAL (${val:.2f})"
            if breakout_price > vah:
                return False, f"Bearish breakout above VAH (${vah:.2f}) - Weak"

        return True, "Neutral volume profile context"

    def validate_entry(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        bars: List[Dict],
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        Primary entry point for sniper.py Step 6.6.
        Builds (or retrieves cached) volume profile and validates the entry price.

        Returns:
            (is_valid, reason, vp_data)

        vp_data keys:
            poc, vah, val, distance_from_poc_pct, volume_rank,
            confidence_boost, options_bias
        """
        profile = self.build_profile(bars, ticker=ticker, use_cache=True)

        if not profile or profile.get('total_volume', 0) == 0:
            return (True, "Volume profile unavailable (insufficient bars)", None)

        is_valid, reason = self.validate_breakout(profile, entry_price, direction)

        poc          = profile.get('poc', 0)
        distance_pct = abs(entry_price - poc) / poc if poc > 0 else 0.0

        volume_rank = "N/A"
        try:
            profile_bins = profile.get('profile', [])
            if profile_bins:
                closest  = min(profile_bins, key=lambda x: abs(x[0] - entry_price))
                max_vol  = max(v for _, v in profile_bins) or 1
                volume_rank = f"{closest[1] / max_vol:.0%}"
        except Exception:
            pass

        opts = self.get_options_context(entry_price, profile, direction)

        vp_data = {
            'poc':                   round(poc, 2),
            'vah':                   round(profile.get('vah', 0), 2),
            'val':                   round(profile.get('val', 0), 2),
            'distance_from_poc_pct': round(distance_pct, 4),
            'volume_rank':           volume_rank,
            'confidence_boost':      opts['confidence_boost'],
            'options_bias':          opts['options_bias'],
        }

        return (is_valid, reason, vp_data)

    # =========================================================================
    # PUBLIC -- SIGNAL ENRICHMENT
    # =========================================================================

    def get_nearest_hvn(
        self, price: float, profile: Dict, direction: str = 'above'
    ) -> Optional[Dict]:
        hvns = profile.get('high_volume_nodes', [])
        if direction == 'above':
            candidates = [n for n in hvns if n['price'] > price]
            return min(candidates, key=lambda x: x['price']) if candidates else None
        else:
            candidates = [n for n in hvns if n['price'] < price]
            return max(candidates, key=lambda x: x['price']) if candidates else None

    def is_in_low_volume_zone(
        self, price: float, profile: Dict, tolerance_pct: float = 0.01
    ) -> bool:
        lvns = profile.get('low_volume_nodes', [])
        for lvn in lvns:
            if lvn['price'] > 0:
                tol = lvn['price'] * tolerance_pct
                if abs(price - lvn['price']) <= tol:
                    return True
        return False

    def check_poc_breakout(
        self, price: float, profile: Dict, direction: str = 'bull'
    ) -> bool:
        poc = profile.get('poc', 0)
        if poc == 0:
            return False
        return price > poc if direction == 'bull' else price < poc

    def check_value_area_breakout(
        self, price: float, profile: Dict, direction: str = 'bull'
    ) -> bool:
        vah = profile.get('vah', 0)
        val = profile.get('val', 0)
        if vah == 0 or val == 0:
            return False
        return price > vah if direction == 'bull' else price < val

    def get_options_context(
        self, price: float, profile: Dict, direction: str = 'bull'
    ) -> Dict:
        """
        Synthesize all volume profile signals into an options-specific decision dict.

        confidence_boost logic (additive to signal confidence score):
          +0.10  POC breakout in trade direction
          +0.05  Value area breakout in direction
          +0.05  Entry near HVN below (bull) / above (bear)  (support confluence)
          -0.05  Entry near HVN in path of trade  (resistance in the way)
          -0.10  Entry in LVN zone  (thin air, high slippage/gap risk)
          Clipped to range [-0.15, +0.15]

        options_bias:
          'CALL'    -- bullish volume structure supports call entry
          'PUT'     -- bearish volume structure supports put entry
          'NEUTRAL' -- no strong volume signal in either direction
          'AVOID'   -- entry in LVN zone, high slippage risk, skip trade
        """
        if not profile or profile.get('total_volume', 0) == 0:
            return {
                'nearest_call_resistance': None,
                'nearest_put_support':     None,
                'in_low_volume_zone':      False,
                'poc_breakout':            False,
                'va_breakout':             False,
                'confidence_boost':        0.0,
                'options_bias':            'NEUTRAL',
            }

        in_lvn    = self.is_in_low_volume_zone(price, profile)
        poc_break = self.check_poc_breakout(price, profile, direction)
        va_break  = self.check_value_area_breakout(price, profile, direction)
        hvn_above = self.get_nearest_hvn(price, profile, direction='above')
        hvn_below = self.get_nearest_hvn(price, profile, direction='below')

        hvn_in_path = hvn_above if direction == 'bull' else hvn_below
        hvn_support = hvn_below if direction == 'bull' else hvn_above

        boost = 0.0
        if in_lvn:
            boost -= 0.10
        if poc_break:
            boost += 0.10
        if va_break:
            boost += 0.05
        if hvn_in_path and hvn_in_path['volume_ratio'] >= self.high_volume_threshold:
            boost -= 0.05
        if hvn_support and hvn_support['volume_ratio'] >= self.high_volume_threshold:
            boost += 0.05
        boost = round(max(-0.15, min(0.15, boost)), 2)

        if in_lvn:
            options_bias = 'AVOID'
        elif direction == 'bull' and (poc_break or va_break) and boost > 0:
            options_bias = 'CALL'
        elif direction == 'bear' and (poc_break or va_break) and boost > 0:
            options_bias = 'PUT'
        elif boost <= -0.05:
            options_bias = 'AVOID'
        else:
            options_bias = 'NEUTRAL'

        return {
            'nearest_call_resistance': hvn_above['price'] if hvn_above else None,
            'nearest_put_support':     hvn_below['price'] if hvn_below else None,
            'in_low_volume_zone':      in_lvn,
            'poc_breakout':            poc_break,
            'va_breakout':             va_break,
            'confidence_boost':        boost,
            'options_bias':            options_bias,
        }


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================

_volume_analyzer: Optional[VolumeProfileAnalyzer] = None


def get_volume_analyzer() -> VolumeProfileAnalyzer:
    """Return the shared VolumeProfileAnalyzer singleton."""
    global _volume_analyzer
    if _volume_analyzer is None:
        _volume_analyzer = VolumeProfileAnalyzer()
    return _volume_analyzer
