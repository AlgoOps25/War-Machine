"""
Options Intelligence Layer
Consolidated options data management and unusual activity detection.

Consolidates:
  - options_data_manager.py (36KB) - Caching, scoring, validation
  - uoa_scanner.py (14KB) - Unusual options activity detection

Key Features:
  - Options chain caching (5-minute TTL, thread-safe)
  - Unusual Options Activity (UOA) detection (OI change, volume spikes)
  - Live GEX levels computation and tracking
  - IV Rank monitoring with change detection
  - Fast tradability scoring for scanner pre-filter
  - Real-time metrics for signal validation

Integration Points:
  - Scanner: get_options_score() for watchlist ranking
  - Sniper: validate_for_trading() for early signal gate (Step 6.5)
  - Sniper: get_live_gex() for real-time gamma exposure
  - Position Manager: monitor_position_gex() for exit timing

validate_for_trading() return schema:
  tradeable:          bool  - Should signal proceed?
  reason:             str   - Concise pass/fail (e.g. GEX-NEG|IVR-32|OI-1200|VOL-450)
  gex_context:        str   - One-line GEX summary (e.g. GEX-NEG|PIN-$225|FLIP-$218)
  tradeable_warnings: list  - Soft flags present even when tradeable=True
  gex_data:           dict  - Full GEX levels dict (None only if chain unavailable)
  ivr_data:           dict  - IV rank dict (None if unavailable)

Performance:
  - Cache hit: ~0.1ms (in-memory lookup)
  - Cache miss: ~200ms (API call + computation)
  - Refresh cycle: Every 5 minutes (background)
  - Thread-safe with locks for concurrent access

FIX #20 (Mar 27 2026): UOA scoring was completely dead in production.
  _calculate_uoa_score() requires avg_volume/avg_oi baseline arguments but
  both callers passed None, so every call early-returned 0.0. Fixed by
  computing chain-relative median baselines before each scan loop and passing
  them per-contract. UOA detection is now fully operational.
"""

import logging
import statistics
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from utils import config

# Import existing modules
from .gex_engine import compute_gex_levels, get_gex_signal_context
from .iv_tracker import compute_ivr, store_iv_observation

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# UOA DETECTION CONSTANTS
# ══════════════════════════════════════════════════════════════════════

# UOA detection thresholds
MIN_VOLUME_RATIO = 2.0      # Volume must be 2x+ average to qualify as unusual
MIN_OI_RATIO = 1.5          # OI must be 1.5x+ average for institutional signal
MIN_UOA_SCORE = 3.0         # Minimum score to qualify as "strong UOA"
EXTREME_UOA_SCORE = 5.0     # Score threshold for "extreme UOA" (smart money)
MAX_SPREAD_PCT = 0.10       # 10% max bid-ask spread (filter out illiquid options)

# Confidence multipliers
ALIGNED_MULTIPLIER = 1.10   # +10% confidence when UOA aligns with signal direction
OPPOSING_MULTIPLIER = 0.85  # -15% confidence when UOA opposes signal direction


class OptionsIntelligence:
    """Unified options data manager with UOA detection."""
    
    def __init__(self, cache_ttl_seconds: int = 300):
        """
        Args:
            cache_ttl_seconds: Time-to-live for cached data (default: 5 minutes)
        """
        self.cache_ttl = cache_ttl_seconds
        
        # Thread-safe caches
        self._lock = threading.RLock()
        self._chain_cache: Dict[str, Dict] = {}  # ticker -> {data, timestamp}
        self._score_cache: Dict[str, Dict] = {}  # ticker -> {score, timestamp}
        self._gex_cache: Dict[str, Dict] = {}    # ticker -> {gex_data, timestamp}
        self._ivr_cache: Dict[str, Dict] = {}    # ticker -> {ivr_data, timestamp}
        self._uoa_cache: Dict[str, Dict] = {}    # ticker -> {uoa_data, timestamp}
        
        # Historical tracking for change detection
        self._prev_chains: Dict[str, Dict] = {}  # ticker -> previous chain snapshot
        
        logger.info("[OPTIONS-DM] Initialized with 5-minute cache TTL")
    
    # ══════════════════════════════════════════════════════════════════════
    # CORE: CHAIN FETCHING & CACHING
    # ══════════════════════════════════════════════════════════════════════
    
    def get_chain(self, ticker: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        Get options chain with intelligent caching.
        
        Args:
            ticker: Stock ticker
            force_refresh: Bypass cache and fetch fresh data
        
        Returns:
            Options chain dict or None if unavailable
        """
        now = time.time()
        
        with self._lock:
            if not force_refresh and ticker in self._chain_cache:
                cached = self._chain_cache[ticker]
                age = now - cached['timestamp']
                if age < self.cache_ttl:
                    return cached['data']

            chain = None
            try:
                from app.validation.validation import OptionsFilter
                _filter = OptionsFilter()
                chain = _filter.get_options_chain(ticker)
            except Exception as e:
                logger.info(f"[OPTIONS-DM] Chain fetch error for {ticker}: {e}")
                chain = None

            if chain:
                if ticker in self._chain_cache:
                    self._prev_chains[ticker] = self._chain_cache[ticker]['data']
                
                self._chain_cache[ticker] = {
                    'data': chain,
                    'timestamp': now
                }
                
                self._score_cache.pop(ticker, None)
                self._gex_cache.pop(ticker, None)
                self._uoa_cache.pop(ticker, None)
                
                return chain
            
            return None
    
    # ══════════════════════════════════════════════════════════════════════
    # SCANNER INTEGRATION: Fast Options Scoring
    # ══════════════════════════════════════════════════════════════════════
    
    def get_options_score(self, ticker: str) -> Dict:
        """
        Fast options scoring for scanner watchlist ranking.
        
        Returns dict with:
            tradeable: bool - Has liquid options?
            score: float (0-100) - Composite options quality score
            uoa_score: float - Unusual options activity score
            gex_score: float - Gamma exposure favorability
            ivr_score: float - IV rank score (low = good for buyers)
            liquidity_score: float - Options liquidity score
            details: dict - Breakdown of metrics
        """
        now = time.time()
        
        with self._lock:
            if ticker in self._score_cache:
                cached = self._score_cache[ticker]
                age = now - cached['timestamp']
                if age < self.cache_ttl:
                    return cached['data']
        
        chain = self.get_chain(ticker)
        
        if not chain or not chain.get('data'):
            return {
                'tradeable': False,
                'score': 0.0,
                'uoa_score': 0.0,
                'gex_score': 0.0,
                'ivr_score': 0.0,
                'liquidity_score': 0.0,
                'details': {'error': 'No options chain'}
            }
        
        try:
            from app.data.data_manager import data_manager
            bars = data_manager.get_today_5m_bars(ticker)
            current_price = bars[-1]['close'] if bars else 0
        except Exception:
            current_price = 0
        
        if current_price == 0:
            return {
                'tradeable': False,
                'score': 0.0,
                'uoa_score': 0.0,
                'gex_score': 0.0,
                'ivr_score': 0.0,
                'liquidity_score': 0.0,
                'details': {'error': 'No current price'}
            }
        
        liquidity = self._compute_liquidity_score(chain, current_price)
        uoa = self._compute_uoa_score(ticker, chain, current_price)
        gex = self._compute_gex_score(ticker, chain, current_price)
        ivr = self._compute_ivr_score(ticker, chain)
        
        total_score = liquidity['score'] + uoa['score'] + gex['score'] + ivr['score']
        tradeable = liquidity['tradeable'] and liquidity['score'] >= 15
        
        result = {
            'tradeable': tradeable,
            'score': round(total_score, 1),
            'uoa_score': round(uoa['score'], 1),
            'gex_score': round(gex['score'], 1),
            'ivr_score': round(ivr['score'], 1),
            'liquidity_score': round(liquidity['score'], 1),
            'details': {
                'liquidity': liquidity,
                'uoa': uoa,
                'gex': gex,
                'ivr': ivr
            }
        }
        
        with self._lock:
            self._score_cache[ticker] = {'data': result, 'timestamp': now}
        
        return result
    
    # ══════════════════════════════════════════════════════════════════════
    # SIGNAL VALIDATION: Pre-Filter Gate (Step 6.5)
    # ══════════════════════════════════════════════════════════════════════
    
    def validate_for_trading(self, ticker: str, direction: str,
                             entry_price: float) -> Dict:
        """
        Fast pre-validation for signal generation (Step 6.5, before confirmation).

        Checks (in order of severity):
          1. Chain availability   → hard fail if no chain
          2. Liquidity            → hard fail if OI/vol/spread below thresholds
          3a. GEX flip zone       → soft warn when price is in positive GEX
          3b. Gamma pin drag      → hard fail when pin is >2% on wrong side
          3c. Pin-near-cap        → soft warn when pin within 3% likely to cap move
        """
        warnings = []

        chain = self.get_chain(ticker)

        if not chain or not chain.get('data'):
            return {
                'tradeable': False,
                'reason': 'No options chain available',
                'gex_context': 'NO-CHAIN',
                'tradeable_warnings': [],
                'gex_data': None,
                'ivr_data': None
            }

        liquidity = self._compute_liquidity_score(chain, entry_price)
        gex_data = compute_gex_levels(chain, entry_price)

        if not liquidity['tradeable']:
            return {
                'tradeable': False,
                'reason': f"Insufficient liquidity: {liquidity['reason']}",
                'gex_context': 'LIQ-FAIL',
                'tradeable_warnings': [],
                'gex_data': gex_data,
                'ivr_data': None
            }

        gex_context_parts = []

        if gex_data.get('has_data'):
            pin      = gex_data.get('gamma_pin')
            flip     = gex_data.get('gamma_flip')
            neg_zone = gex_data.get('neg_gex_zone', False)

            gex_context_parts.append('GEX-NEG' if neg_zone else 'GEX-POS')
            if pin:
                gex_context_parts.append(f'PIN-${pin:.2f}')
            if flip:
                gex_context_parts.append(f'FLIP-${flip:.2f}')

            if flip and not neg_zone:
                if direction == 'bull' and flip > entry_price:
                    flip_dist_pct = ((flip - entry_price) / entry_price) * 100
                    if flip_dist_pct < 1.0:
                        warnings.append(f'NEAR-GEX-FLIP@${flip:.2f}({flip_dist_pct:.1f}%-away)')
                    else:
                        warnings.append(f'POS-GEX-ZONE|FLIP-CEIL@${flip:.2f}')
                elif direction == 'bear' and flip < entry_price:
                    flip_dist_pct = ((entry_price - flip) / entry_price) * 100
                    if flip_dist_pct < 1.0:
                        warnings.append(f'NEAR-GEX-FLIP@${flip:.2f}({flip_dist_pct:.1f}%-away)')
                    else:
                        warnings.append(f'POS-GEX-ZONE|FLIP-FLOOR@${flip:.2f}')

            if pin:
                if direction == 'bull':
                    pin_pct = (pin - entry_price) / entry_price
                    if pin_pct < -0.02:
                        return {
                            'tradeable': False,
                            'reason': f'GEX pin drag below bull entry @ ${pin:.2f} ({abs(pin_pct)*100:.1f}% below)',
                            'gex_context': '|'.join(gex_context_parts),
                            'tradeable_warnings': warnings,
                            'gex_data': gex_data,
                            'ivr_data': None
                        }
                    elif 0.0 < pin_pct < 0.03:
                        warnings.append(f'PIN-CAP-NEAR@${pin:.2f}({pin_pct*100:.1f}%-above)')
                elif direction == 'bear':
                    pin_pct = (entry_price - pin) / entry_price
                    if pin_pct < -0.02:
                        return {
                            'tradeable': False,
                            'reason': f'GEX pin drag above bear entry @ ${pin:.2f} ({abs(pin_pct)*100:.1f}% above)',
                            'gex_context': '|'.join(gex_context_parts),
                            'tradeable_warnings': warnings,
                            'gex_data': gex_data,
                            'ivr_data': None
                        }
                    elif 0.0 < pin_pct < 0.03:
                        warnings.append(f'PIN-FLOOR-NEAR@${pin:.2f}({pin_pct*100:.1f}%-below)')

        ivr_data = self._get_ivr_data(ticker, chain)

        if ivr_data and ivr_data.get('ivr_reliable'):
            ivr_label = f"IVR-{ivr_data['ivr']:.0f}"
        elif ivr_data:
            ivr_label = 'IVR-BUILDING'
        else:
            ivr_label = 'IVR-N/A'

        liq_label = f"OI-{liquidity.get('max_oi', 0):.0f}|VOL-{liquidity.get('max_vol', 0):.0f}"
        gex_ctx = '|'.join(gex_context_parts) if gex_context_parts else 'GEX-N/A'
        reason  = f"{gex_ctx}|{ivr_label}|{liq_label}"
        if warnings:
            reason += '|WARN:' + '+'.join(warnings)

        return {
            'tradeable': True,
            'reason': reason,
            'gex_context': gex_ctx,
            'tradeable_warnings': warnings,
            'gex_data': gex_data,
            'ivr_data': ivr_data
        }
    
    # ══════════════════════════════════════════════════════════════════════
    # LIVE MONITORING: Real-Time GEX Updates
    # ══════════════════════════════════════════════════════════════════════
    
    def get_live_gex(self, ticker: str, current_price: float,
                     force_refresh: bool = False) -> Dict:
        """Get real-time GEX levels for active position monitoring."""
        now = time.time()
        
        if not force_refresh:
            with self._lock:
                if ticker in self._gex_cache:
                    cached = self._gex_cache[ticker]
                    if now - cached['timestamp'] < 60:
                        return cached['data']
        
        chain = self.get_chain(ticker, force_refresh=force_refresh)
        if not chain:
            return {'has_data': False}
        
        gex_data = compute_gex_levels(chain, current_price)
        if not gex_data['has_data']:
            return {'has_data': False}
        
        pin  = gex_data['gamma_pin']
        flip = gex_data['gamma_flip']
        
        result = {
            'has_data': True,
            'gamma_pin': pin,
            'gamma_flip': flip,
            'neg_gex_zone': gex_data['neg_gex_zone'],
            'zone': 'NEGATIVE' if gex_data['neg_gex_zone'] else 'POSITIVE',
            'pin_distance': ((pin - current_price) / current_price) * 100 if pin else None,
            'pin_headwind': False,
            'total_gex': gex_data['total_gex'],
            'top_positive': gex_data['top_positive'],
            'top_negative': gex_data['top_negative']
        }
        
        with self._lock:
            self._gex_cache[ticker] = {'data': result, 'timestamp': now}
        
        return result
    
    # ══════════════════════════════════════════════════════════════════════
    # INTERNAL: Scoring Components
    # ══════════════════════════════════════════════════════════════════════
    
    def _compute_liquidity_score(self, chain: Dict, current_price: float) -> Dict:
        """Compute liquidity score (0-30 points) for ATM options."""
        data = chain.get('data', {})
        if not data:
            return {'score': 0.0, 'tradeable': False, 'reason': 'No chain data'}
        
        atm_calls = []
        atm_puts = []
        
        for expiry, opts in data.items():
            for strike_str, opt in opts.get('calls', {}).items():
                if abs(float(strike_str) - current_price) / current_price <= 0.02:
                    atm_calls.append(opt)
            for strike_str, opt in opts.get('puts', {}).items():
                if abs(float(strike_str) - current_price) / current_price <= 0.02:
                    atm_puts.append(opt)
        
        if not atm_calls and not atm_puts:
            return {'score': 0.0, 'tradeable': False, 'reason': 'No ATM strikes'}
        
        max_oi = 0
        max_vol = 0
        min_spread = 999.0
        
        for opt in atm_calls + atm_puts:
            oi  = opt.get('openInterest', 0)
            vol = opt.get('volume', 0)
            bid = opt.get('bid', 0)
            ask = opt.get('ask', 0)
            max_oi  = max(max_oi, oi)
            max_vol = max(max_vol, vol)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                if mid > 0:
                    min_spread = min(min_spread, (ask - bid) / mid)
        
        if max_oi < config.MIN_OPTION_OI:
            return {'score': 0.0, 'tradeable': False,
                    'reason': f'Low OI ({max_oi} < {config.MIN_OPTION_OI})',
                    'max_oi': max_oi, 'max_vol': max_vol}
        if max_vol < config.MIN_OPTION_VOLUME:
            return {'score': 0.0, 'tradeable': False,
                    'reason': f'Low volume ({max_vol} < {config.MIN_OPTION_VOLUME})',
                    'max_oi': max_oi, 'max_vol': max_vol}
        if min_spread > config.MAX_BID_ASK_SPREAD_PCT:
            return {'score': 0.0, 'tradeable': False,
                    'reason': f'Wide spread ({min_spread:.1%} > {config.MAX_BID_ASK_SPREAD_PCT:.1%})',
                    'max_oi': max_oi, 'max_vol': max_vol, 'min_spread': min_spread}
        
        oi_score     = min(max_oi  / 5000, 1.0) * 15
        vol_score    = min(max_vol / 1000, 1.0) * 10
        spread_score = max(0, (config.MAX_BID_ASK_SPREAD_PCT - min_spread) / config.MAX_BID_ASK_SPREAD_PCT) * 5
        
        return {
            'score': oi_score + vol_score + spread_score,
            'tradeable': True,
            'reason': 'Liquid',
            'max_oi': max_oi,
            'max_vol': max_vol,
            'min_spread': min_spread
        }
    
    def _compute_uoa_score(self, ticker: str, chain: Dict, current_price: float) -> Dict:
        """
        Compute Unusual Options Activity score (0-30 points).

        FIX #20 (Mar 27 2026): Previously every call to _calculate_uoa_score()
        returned 0.0 because avg_volume/avg_oi were never passed (both None).
        Fix: collect all volume/OI values from the scan window first, compute
        median as the chain-relative baseline, then pass per-contract.
        """
        data = chain.get('data', {})
        if not data:
            return {'score': 0.0, 'detected': False, 'reason': 'No chain data'}

        # —— FIX #20: Build chain-relative baselines before scoring loop ——
        all_volumes = []
        all_ois = []
        for expiration, options_data in data.items():
            for opts_dict in (options_data.get('calls', {}), options_data.get('puts', {})):
                for strike_str, option in opts_dict.items():
                    if abs(float(strike_str) - current_price) / current_price > 0.10:
                        continue
                    v = option.get('volume', 0)
                    o = option.get('openInterest', 0)
                    if v > 0:
                        all_volumes.append(v)
                    if o > 0:
                        all_ois.append(o)

        if not all_volumes or not all_ois:
            return {'score': 0.0, 'detected': False, 'reason': 'No volume/OI data for baseline'}

        avg_volume = statistics.median(all_volumes)
        avg_oi     = statistics.median(all_ois)
        # —— end FIX #20 ——

        call_uoa_scores = []
        put_uoa_scores  = []

        for expiration, options_data in data.items():
            for strike_str, option in options_data.get('calls', {}).items():
                strike = float(strike_str)
                if abs(strike - current_price) / current_price > 0.10:
                    continue
                volume = option.get('volume', 0)
                oi     = option.get('openInterest', 0)
                bid    = option.get('bid', 0)
                ask    = option.get('ask', 0)
                if not all([volume, oi, bid, ask]):
                    continue
                uoa_score, _ = self._calculate_uoa_score(volume, oi, bid, ask, avg_volume, avg_oi)
                if uoa_score >= MIN_UOA_SCORE:
                    call_uoa_scores.append(uoa_score)

            for strike_str, option in options_data.get('puts', {}).items():
                strike = float(strike_str)
                if abs(strike - current_price) / current_price > 0.10:
                    continue
                volume = option.get('volume', 0)
                oi     = option.get('openInterest', 0)
                bid    = option.get('bid', 0)
                ask    = option.get('ask', 0)
                if not all([volume, oi, bid, ask]):
                    continue
                uoa_score, _ = self._calculate_uoa_score(volume, oi, bid, ask, avg_volume, avg_oi)
                if uoa_score >= MIN_UOA_SCORE:
                    put_uoa_scores.append(uoa_score)

        max_call_score = max(call_uoa_scores) if call_uoa_scores else 0
        max_put_score  = max(put_uoa_scores)  if put_uoa_scores  else 0
        max_uoa_score  = max(max_call_score, max_put_score)

        if max_uoa_score == 0:
            return {'score': 0.0, 'detected': False, 'reason': 'No UOA detected'}

        score    = min(max_uoa_score / EXTREME_UOA_SCORE, 1.0) * 30
        uoa_type = 'CALL' if max_call_score > max_put_score else 'PUT'

        return {
            'score': score,
            'detected': True,
            'reason': f'{uoa_type}-UOA(score={max_uoa_score:.1f})',
            'max_score': max_uoa_score,
            'call_score': max_call_score,
            'put_score': max_put_score
        }
    
    def _calculate_uoa_score(self, volume: int, open_interest: int,
                            bid: float, ask: float,
                            avg_volume: Optional[float] = None,
                            avg_oi: Optional[float] = None) -> Tuple[float, Dict]:
        """
        Calculate UOA score for a single option contract.

        Requires avg_volume and avg_oi chain-relative baselines (computed by
        callers via median of all scanned strikes). Returns 0.0 with reason
        string if baselines are missing — callers must always pass them.
        """
        if avg_volume is None or avg_oi is None:
            return 0.0, {
                'volume_ratio': 0.0, 'oi_ratio': 0.0, 'spread_pct': 0.0,
                'spread_quality': 0.0, 'is_liquid': False,
                'reason': 'No baseline avg_volume/avg_oi provided'
            }

        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        oi_ratio     = open_interest / avg_oi if avg_oi > 0 else 0

        mid        = (bid + ask) / 2 if (bid and ask) else 0
        spread_pct = (ask - bid) / mid if mid > 0 else 999

        if spread_pct > MAX_SPREAD_PCT:
            return 0.0, {
                'volume_ratio': volume_ratio, 'oi_ratio': oi_ratio,
                'spread_pct': spread_pct, 'spread_quality': 0, 'is_liquid': False,
                'reason': f'Spread too wide ({spread_pct:.1%} > {MAX_SPREAD_PCT:.1%})'
            }

        spread_quality = max(0, 1.0 - (spread_pct / MAX_SPREAD_PCT))
        uoa_score      = volume_ratio * oi_ratio * spread_quality

        return round(uoa_score, 2), {
            'volume_ratio':     round(volume_ratio, 2),
            'oi_ratio':         round(oi_ratio, 2),
            'spread_pct':       round(spread_pct, 4),
            'spread_quality':   round(spread_quality, 2),
            'is_liquid':        True,
            'is_unusual':       volume_ratio >= MIN_VOLUME_RATIO,
            'has_institutional': oi_ratio >= MIN_OI_RATIO
        }
    
    def _compute_gex_score(self, ticker: str, chain: Dict, current_price: float) -> Dict:
        """Compute GEX favorability score (0-25 points)."""
        gex_data = compute_gex_levels(chain, current_price)
        if not gex_data['has_data']:
            return {'score': 0.0, 'reason': 'No GEX data'}
        
        score   = 0.0
        factors = []
        
        if gex_data['neg_gex_zone']:
            score += 15
            factors.append('NEG-GEX-ZONE')
        
        pin = gex_data['gamma_pin']
        if pin:
            if pin > current_price * 1.01:
                score += 10
                factors.append(f'PIN-ABOVE@{pin:.2f}')
            elif pin < current_price * 0.99:
                score += 5
                factors.append(f'PIN-BELOW@{pin:.2f}')
        
        return {
            'score': min(score, 25),
            'reason': '+'.join(factors) if factors else 'Neutral',
            'gamma_pin': pin,
            'gamma_flip': gex_data['gamma_flip'],
            'neg_gex_zone': gex_data['neg_gex_zone']
        }
    
    def _compute_ivr_score(self, ticker: str, chain: Dict) -> Dict:
        """Compute IV Rank score (0-15 points). Low IVR = good for option buyers."""
        ivr_data = self._get_ivr_data(ticker, chain)
        if not ivr_data or not ivr_data.get('ivr_reliable'):
            return {'score': 5.0, 'reason': 'IVR-BUILDING', 'ivr': None}
        
        ivr = ivr_data['ivr']
        if ivr < 30:   score, reason = 15, f'IVR-LOW({ivr:.0f})'
        elif ivr < 50: score, reason = 10, f'IVR-FAIR({ivr:.0f})'
        elif ivr < 70: score, reason =  5, f'IVR-ELEVATED({ivr:.0f})'
        else:          score, reason =  0, f'IVR-HIGH({ivr:.0f})'
        
        return {
            'score': score, 'reason': reason, 'ivr': ivr,
            'current_iv': ivr_data.get('current_iv'),
            'iv_change':  ivr_data.get('iv_change')
        }
    
    def _get_ivr_data(self, ticker: str, chain: Dict) -> Optional[Dict]:
        """Get IV Rank data from first available ATM call."""
        data = chain.get('data', {})
        if not data:
            return None
        for expiry, opts in data.items():
            for strike_str, opt in opts.get('calls', {}).items():
                iv = opt.get('impliedVolatility', 0)
                if iv and iv > 0:
                    store_iv_observation(ticker, iv)
                    ivr, obs, reliable = compute_ivr(ticker, iv)
                    return {
                        'current_iv': iv, 'ivr': ivr,
                        'ivr_obs': obs, 'ivr_reliable': reliable,
                        'iv_change': None
                    }
        return None
    
    # ══════════════════════════════════════════════════════════════════════
    # UOA DETECTION: Full Chain Scan
    # ══════════════════════════════════════════════════════════════════════
    
    def scan_chain_for_uoa(self, ticker: str, signal_direction: str,
                          entry_price: float, max_strikes: int = 10) -> Dict:
        """
        Scan entire options chain for unusual activity and determine alignment.

        FIX #20 (Mar 27 2026): Same baseline fix as _compute_uoa_score().
        Median volume/OI computed from all scanned strikes before scoring loop.
        """
        chain = self.get_chain(ticker)
        
        if not chain or not chain.get('data'):
            return {
                'uoa_detected': False, 'uoa_aligned': False, 'uoa_opposing': False,
                'uoa_multiplier': 1.0, 'uoa_label': 'UOA-NEUTRAL',
                'uoa_max_score': 0.0, 'uoa_top_aligned': [], 'uoa_top_opposing': []
            }

        # —— FIX #20: Build chain-relative baselines before scoring loop ——
        all_volumes = []
        all_ois = []
        for expiration, options_data in chain.get('data', {}).items():
            for opts_dict in (options_data.get('calls', {}), options_data.get('puts', {})):
                for strike_str, option in opts_dict.items():
                    if abs(float(strike_str) - entry_price) / entry_price > 0.10:
                        continue
                    v = option.get('volume', 0)
                    o = option.get('openInterest', 0)
                    if v > 0: all_volumes.append(v)
                    if o > 0: all_ois.append(o)

        if not all_volumes or not all_ois:
            return {
                'uoa_detected': False, 'uoa_aligned': False, 'uoa_opposing': False,
                'uoa_multiplier': 1.0, 'uoa_label': 'UOA-NEUTRAL',
                'uoa_max_score': 0.0, 'uoa_top_aligned': [], 'uoa_top_opposing': []
            }

        avg_volume = statistics.median(all_volumes)
        avg_oi     = statistics.median(all_ois)
        # —— end FIX #20 ——

        call_uoa_strikes = []
        put_uoa_strikes  = []
        
        for expiration, options_data in chain.get('data', {}).items():
            for strike_str, option in options_data.get('calls', {}).items():
                strike = float(strike_str)
                if abs(strike - entry_price) / entry_price > 0.10:
                    continue
                volume = option.get('volume', 0)
                oi     = option.get('openInterest', 0)
                bid    = option.get('bid', 0)
                ask    = option.get('ask', 0)
                if not all([volume, oi, bid, ask]):
                    continue
                uoa_score, metadata = self._calculate_uoa_score(volume, oi, bid, ask, avg_volume, avg_oi)
                if uoa_score >= MIN_UOA_SCORE:
                    call_uoa_strikes.append({
                        'strike': strike, 'expiration': expiration, 'type': 'CALL',
                        'uoa_score': uoa_score, 'volume': volume, 'oi': oi, 'metadata': metadata
                    })

            for strike_str, option in options_data.get('puts', {}).items():
                strike = float(strike_str)
                if abs(strike - entry_price) / entry_price > 0.10:
                    continue
                volume = option.get('volume', 0)
                oi     = option.get('openInterest', 0)
                bid    = option.get('bid', 0)
                ask    = option.get('ask', 0)
                if not all([volume, oi, bid, ask]):
                    continue
                uoa_score, metadata = self._calculate_uoa_score(volume, oi, bid, ask, avg_volume, avg_oi)
                if uoa_score >= MIN_UOA_SCORE:
                    put_uoa_strikes.append({
                        'strike': strike, 'expiration': expiration, 'type': 'PUT',
                        'uoa_score': uoa_score, 'volume': volume, 'oi': oi, 'metadata': metadata
                    })
        
        call_uoa_strikes.sort(key=lambda x: x['uoa_score'], reverse=True)
        put_uoa_strikes.sort(key=lambda x: x['uoa_score'],  reverse=True)
        
        max_call_score = call_uoa_strikes[0]['uoa_score'] if call_uoa_strikes else 0
        max_put_score  = put_uoa_strikes[0]['uoa_score']  if put_uoa_strikes  else 0
        max_uoa_score  = max(max_call_score, max_put_score)
        
        if max_uoa_score < MIN_UOA_SCORE:
            return {
                'uoa_detected': False, 'uoa_aligned': False, 'uoa_opposing': False,
                'uoa_multiplier': 1.0, 'uoa_label': 'UOA-NEUTRAL',
                'uoa_max_score': 0.0, 'uoa_top_aligned': [], 'uoa_top_opposing': []
            }
        
        if signal_direction == 'bull':
            aligned_strikes  = call_uoa_strikes
            opposing_strikes = put_uoa_strikes
            aligned_type     = 'CALL'
            opposing_type    = 'PUT'
        else:
            aligned_strikes  = put_uoa_strikes
            opposing_strikes = call_uoa_strikes
            aligned_type     = 'PUT'
            opposing_type    = 'CALL'
        
        max_aligned_score  = aligned_strikes[0]['uoa_score']  if aligned_strikes  else 0
        max_opposing_score = opposing_strikes[0]['uoa_score'] if opposing_strikes else 0
        
        uoa_aligned  = max_aligned_score  > max_opposing_score
        uoa_opposing = max_opposing_score > max_aligned_score
        
        if uoa_aligned:
            multiplier = ALIGNED_MULTIPLIER
            label = f'UOA-ALIGNED-{aligned_type}(score={max_aligned_score:.1f})'
        elif uoa_opposing:
            multiplier = OPPOSING_MULTIPLIER
            label = f'UOA-OPPOSING-{opposing_type}(score={max_opposing_score:.1f})'
        else:
            multiplier = 1.0
            label = 'UOA-MIXED'
        
        return {
            'uoa_detected':    True,
            'uoa_aligned':     uoa_aligned,
            'uoa_opposing':    uoa_opposing,
            'uoa_multiplier':  multiplier,
            'uoa_label':       label,
            'uoa_max_score':   max_uoa_score,
            'uoa_top_aligned':   aligned_strikes[:3],
            'uoa_top_opposing':  opposing_strikes[:3]
        }
    
    # ══════════════════════════════════════════════════════════════════════
    # CACHE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════
    
    def clear_cache(self, ticker: Optional[str] = None):
        """Clear cache for specific ticker or all tickers."""
        with self._lock:
            if ticker:
                for cache in (self._chain_cache, self._score_cache, self._gex_cache,
                              self._ivr_cache, self._uoa_cache, self._prev_chains):
                    cache.pop(ticker, None)
                logger.info(f"[OPTIONS-DM] Cleared cache for {ticker}")
            else:
                for cache in (self._chain_cache, self._score_cache, self._gex_cache,
                              self._ivr_cache, self._uoa_cache, self._prev_chains):
                    cache.clear()
                logger.info("[OPTIONS-DM] Cleared all caches")
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        with self._lock:
            return {
                'chains_cached': len(self._chain_cache),
                'scores_cached': len(self._score_cache),
                'gex_cached':    len(self._gex_cache),
                'ivr_cached':    len(self._ivr_cache),
                'uoa_cached':    len(self._uoa_cache),
                'cache_ttl':     self.cache_ttl
            }


# ══════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ══════════════════════════════════════════════════════════════════════
options_intelligence = OptionsIntelligence(cache_ttl_seconds=300)

# Backward compatibility alias (used by ai_learning.get_options_flow_weight)
options_dm = options_intelligence


# ══════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════

def get_options_score(ticker: str) -> Dict:
    """Get options score for ticker (scanner integration)."""
    return options_intelligence.get_options_score(ticker)


def validate_for_trading(ticker: str, direction: str, entry_price: float) -> Dict:
    """Validate ticker for options trading (signal pre-filter, Step 6.5)."""
    return options_intelligence.validate_for_trading(ticker, direction, entry_price)


def get_live_gex(ticker: str, current_price: float) -> Dict:
    """Get live GEX levels (position monitoring)."""
    return options_intelligence.get_live_gex(ticker, current_price)


def scan_chain_for_uoa(ticker: str, signal_direction: str, entry_price: float) -> Dict:
    """Scan options chain for unusual activity."""
    return options_intelligence.scan_chain_for_uoa(ticker, signal_direction, entry_price)


def clear_options_cache(ticker: Optional[str] = None):
    """Clear options cache."""
    options_intelligence.clear_cache(ticker)
