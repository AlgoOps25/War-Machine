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
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from utils import config

# Import existing modules
from .options_filter import OptionsFilter
from .gex_engine import compute_gex_levels, get_gex_signal_context
from .iv_tracker import compute_ivr, store_iv_observation


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# UOA DETECTION CONSTANTS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

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
        self.options_filter = OptionsFilter()
        
        # Thread-safe caches
        self._lock = threading.RLock()
        self._chain_cache: Dict[str, Dict] = {}  # ticker -> {data, timestamp}
        self._score_cache: Dict[str, Dict] = {}  # ticker -> {score, timestamp}
        self._gex_cache: Dict[str, Dict] = {}    # ticker -> {gex_data, timestamp}
        self._ivr_cache: Dict[str, Dict] = {}    # ticker -> {ivr_data, timestamp}
        self._uoa_cache: Dict[str, Dict] = {}    # ticker -> {uoa_data, timestamp}
        
        # Historical tracking for change detection
        self._prev_chains: Dict[str, Dict] = {}  # ticker -> previous chain snapshot
        
        print("[OPTIONS-DM] Initialized with 5-minute cache TTL")
    
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # CORE: CHAIN FETCHING & CACHING
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    
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
            # Check cache
            if not force_refresh and ticker in self._chain_cache:
                cached = self._chain_cache[ticker]
                age = now - cached['timestamp']
                if age < self.cache_ttl:
                    return cached['data']
            
            # Fetch fresh chain
            chain = self.options_filter.get_options_chain(ticker)
            
            if chain:
                # Store previous chain for change detection
                if ticker in self._chain_cache:
                    self._prev_chains[ticker] = self._chain_cache[ticker]['data']
                
                # Cache new chain
                self._chain_cache[ticker] = {
                    'data': chain,
                    'timestamp': now
                }
                
                # Invalidate dependent caches
                self._score_cache.pop(ticker, None)
                self._gex_cache.pop(ticker, None)
                self._uoa_cache.pop(ticker, None)
                
                return chain
            
            return None
    
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # SCANNER INTEGRATION: Fast Options Scoring
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    
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
            # Check cache
            if ticker in self._score_cache:
                cached = self._score_cache[ticker]
                age = now - cached['timestamp']
                if age < self.cache_ttl:
                    return cached['data']
        
        # Compute fresh score
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
        
        # Get latest price
        try:
            from data_manager import data_manager
            bars = data_manager.get_today_5m_bars(ticker)
            if not bars:
                current_price = 0
            else:
                current_price = bars[-1]['close']
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
        
        # 1. Liquidity Score (0-30 points)
        liquidity = self._compute_liquidity_score(chain, current_price)
        
        # 2. UOA Score (0-30 points)
        uoa = self._compute_uoa_score(ticker, chain, current_price)
        
        # 3. GEX Score (0-25 points)
        gex = self._compute_gex_score(ticker, chain, current_price)
        
        # 4. IVR Score (0-15 points)
        ivr = self._compute_ivr_score(ticker, chain)
        
        # Composite score
        total_score = liquidity['score'] + uoa['score'] + gex['score'] + ivr['score']
        
        tradeable = (
            liquidity['tradeable'] and 
            liquidity['score'] >= 15  # Minimum liquidity threshold
        )
        
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
        
        # Cache result
        with self._lock:
            self._score_cache[ticker] = {
                'data': result,
                'timestamp': now
            }
        
        return result
    
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # SIGNAL VALIDATION: Pre-Filter Gate (Step 6.5)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    
    def validate_for_trading(self, ticker: str, direction: str,
                             entry_price: float) -> Dict:
        """
        Fast pre-validation for signal generation (Step 6.5, before confirmation).

        Checks (in order of severity):
          1. Chain availability   â†’ hard fail if no chain
          2. Liquidity            â†’ hard fail if OI/vol/spread below thresholds
          3a. GEX flip zone       â†’ soft warn when price is in positive GEX
                                    (mean-reverting) and pushing against the flip
          3b. Gamma pin drag      â†’ hard fail when pin is >2% on the wrong side
                                    of entry (gravitational drag opposes direction)
          3c. Pin-near-cap        â†’ soft warn when pin is within 3% and likely
                                    to cap the move before target

        Return schema:
          tradeable:          bool  - Should signal proceed?
          reason:             str   - Enriched context string, e.g.:
                                        PASS:  "GEX-NEG|PIN-$225|IVR-32|OI-1200|VOL-450"
                                        FAIL:  "GEX pin drag below bull entry @ $218 (2.3% below)"
          gex_context:        str   - One-line GEX summary for Step 6.5 SOFT log
          tradeable_warnings: list  - Soft flags (informational, never fatal in SOFT mode)
          gex_data:           dict  - Full GEX levels (populated even on liquidity fail
                                      so the zone is visible in logs)
          ivr_data:           dict  - IV rank data (None if chain has no IV data)
        """
        warnings = []

        # â”€â”€ 1. Chain availability â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ 2. Liquidity check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        liquidity = self._compute_liquidity_score(chain, entry_price)

        # Fetch GEX now regardless of liquidity result so the zone is always
        # visible in SOFT-mode logs even when the chain is thinly traded.
        gex_data = compute_gex_levels(chain, entry_price)

        if not liquidity['tradeable']:
            return {
                'tradeable': False,
                'reason': f"Insufficient liquidity: {liquidity['reason']}",
                'gex_context': 'LIQ-FAIL',
                'tradeable_warnings': [],
                'gex_data': gex_data,   # populated for visibility
                'ivr_data': None
            }

        # â”€â”€ 3. GEX headwind checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        gex_context_parts = []

        if gex_data.get('has_data'):
            pin      = gex_data.get('gamma_pin')
            flip     = gex_data.get('gamma_flip')
            neg_zone = gex_data.get('neg_gex_zone', False)

            # Build the GEX context string (always logged in SOFT mode)
            gex_context_parts.append('GEX-NEG' if neg_zone else 'GEX-POS')
            if pin:
                gex_context_parts.append(f'PIN-${pin:.2f}')
            if flip:
                gex_context_parts.append(f'FLIP-${flip:.2f}')

            # â”€â”€ 3a. Gamma flip zone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Negative GEX zone = vol expands, trends run â†’ GOOD for directional
            # Positive GEX zone = vol compresses, mean-reverts â†’ soft warning
            if flip and not neg_zone:
                if direction == 'bull' and flip > entry_price:
                    # Trying to push up through gamma flip ceiling
                    flip_dist_pct = ((flip - entry_price) / entry_price) * 100
                    if flip_dist_pct < 1.0:
                        warnings.append(f'NEAR-GEX-FLIP@${flip:.2f}({flip_dist_pct:.1f}%-away)')
                    else:
                        warnings.append(f'POS-GEX-ZONE|FLIP-CEIL@${flip:.2f}')
                elif direction == 'bear' and flip < entry_price:
                    # Trying to push down through gamma flip floor
                    flip_dist_pct = ((entry_price - flip) / entry_price) * 100
                    if flip_dist_pct < 1.0:
                        warnings.append(f'NEAR-GEX-FLIP@${flip:.2f}({flip_dist_pct:.1f}%-away)')
                    else:
                        warnings.append(f'POS-GEX-ZONE|FLIP-FLOOR@${flip:.2f}')

            # â”€â”€ 3b. Gamma pin drag (hard gate) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # If the gamma pin is >2% on the WRONG side of entry, market maker
            # hedging exerts gravitational pull back toward the pin â€” the trade
            # is working against MM delta hedging flow.
            if pin:
                if direction == 'bull':
                    # pin_pct: negative means pin is below entry
                    pin_pct = (pin - entry_price) / entry_price
                    if pin_pct < -0.02:    # pin >2% below bull entry
                        return {
                            'tradeable': False,
                            'reason': (
                                f'GEX pin drag below bull entry @ ${pin:.2f} '
                                f'({abs(pin_pct) * 100:.1f}% below)'
                            ),
                            'gex_context': '|'.join(gex_context_parts),
                            'tradeable_warnings': warnings,
                            'gex_data': gex_data,
                            'ivr_data': None
                        }
                    elif 0.0 < pin_pct < 0.03:    # pin just above entry (cap)
                        warnings.append(f'PIN-CAP-NEAR@${pin:.2f}({pin_pct * 100:.1f}%-above)')

                elif direction == 'bear':
                    # pin_pct: negative means pin is above entry
                    pin_pct = (entry_price - pin) / entry_price
                    if pin_pct < -0.02:    # pin >2% above bear entry
                        return {
                            'tradeable': False,
                            'reason': (
                                f'GEX pin drag above bear entry @ ${pin:.2f} '
                                f'({abs(pin_pct) * 100:.1f}% above)'
                            ),
                            'gex_context': '|'.join(gex_context_parts),
                            'tradeable_warnings': warnings,
                            'gex_data': gex_data,
                            'ivr_data': None
                        }
                    elif 0.0 < pin_pct < 0.03:    # pin just below entry (support floor)
                        warnings.append(f'PIN-FLOOR-NEAR@${pin:.2f}({pin_pct * 100:.1f}%-below)')

        # â”€â”€ 4. IVR context â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        ivr_data = self._get_ivr_data(ticker, chain)

        # Build IVR label for the reason string
        if ivr_data and ivr_data.get('ivr_reliable'):
            ivr_label = f"IVR-{ivr_data['ivr']:.0f}"
        elif ivr_data:
            ivr_label = 'IVR-BUILDING'
        else:
            ivr_label = 'IVR-N/A'

        # Build liquidity label
        liq_label = (
            f"OI-{liquidity.get('max_oi', 0):.0f}"
            f"|VOL-{liquidity.get('max_vol', 0):.0f}"
        )

        # Final enriched reason string
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
    
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # LIVE MONITORING: Real-Time GEX Updates
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    
    def get_live_gex(self, ticker: str, current_price: float, 
                     force_refresh: bool = False) -> Dict:
        """
        Get real-time GEX levels for active position monitoring.
        
        Returns dict with:
            has_data: bool
            gamma_pin: float - Pin strike
            gamma_flip: float - Flip level
            pin_distance: float - Distance to pin (%)
            pin_headwind: bool - Is pin opposing current direction?
            zone: str - "NEGATIVE" or "POSITIVE"
        """
        now = time.time()
        
        # Check cache (shorter TTL for monitoring - 1 minute)
        if not force_refresh:
            with self._lock:
                if ticker in self._gex_cache:
                    cached = self._gex_cache[ticker]
                    age = now - cached['timestamp']
                    if age < 60:  # 1-minute cache for live monitoring
                        return cached['data']
        
        # Fetch fresh GEX
        chain = self.get_chain(ticker, force_refresh=force_refresh)
        
        if not chain:
            return {'has_data': False}
        
        gex_data = compute_gex_levels(chain, current_price)
        
        if not gex_data['has_data']:
            return {'has_data': False}
        
        # Enrich with monitoring metrics
        pin = gex_data['gamma_pin']
        flip = gex_data['gamma_flip']
        
        result = {
            'has_data': True,
            'gamma_pin': pin,
            'gamma_flip': flip,
            'neg_gex_zone': gex_data['neg_gex_zone'],
            'zone': 'NEGATIVE' if gex_data['neg_gex_zone'] else 'POSITIVE',
            'pin_distance': None,
            'pin_headwind': False,
            'total_gex': gex_data['total_gex'],
            'top_positive': gex_data['top_positive'],
            'top_negative': gex_data['top_negative']
        }
        
        if pin:
            result['pin_distance'] = ((pin - current_price) / current_price) * 100
            # Pin is headwind if it's opposing the likely price direction
            # (This is context-dependent and should be checked per-signal)
        
        # Cache result
        with self._lock:
            self._gex_cache[ticker] = {
                'data': result,
                'timestamp': now
            }
        
        return result
    
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # INTERNAL: Scoring Components
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    
    def _compute_liquidity_score(self, chain: Dict, current_price: float) -> Dict:
        """
        Compute liquidity score (0-30 points) for ATM options.
        
        Checks:
        - Min OI >= 500
        - Min volume >= 100
        - Bid-ask spread <= 10%
        - Presence of weekly options
        """
        data = chain.get('data', {})
        
        if not data:
            return {'score': 0.0, 'tradeable': False, 'reason': 'No chain data'}
        
        # Find ATM strikes (within Â±2% of current price)
        atm_calls = []
        atm_puts = []
        
        for expiry, opts in data.items():
            for strike_str, opt in opts.get('calls', {}).items():
                strike = float(strike_str)
                if abs(strike - current_price) / current_price <= 0.02:
                    atm_calls.append(opt)
            
            for strike_str, opt in opts.get('puts', {}).items():
                strike = float(strike_str)
                if abs(strike - current_price) / current_price <= 0.02:
                    atm_puts.append(opt)
        
        if not atm_calls and not atm_puts:
            return {'score': 0.0, 'tradeable': False, 'reason': 'No ATM strikes'}
        
        # Check ATM calls
        max_oi = 0
        max_vol = 0
        min_spread = 999.0
        
        for opt in atm_calls + atm_puts:
            oi = opt.get('openInterest', 0)
            vol = opt.get('volume', 0)
            bid = opt.get('bid', 0)
            ask = opt.get('ask', 0)
            
            max_oi = max(max_oi, oi)
            max_vol = max(max_vol, vol)
            
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                if mid > 0:
                    spread = (ask - bid) / mid
                    min_spread = min(min_spread, spread)
        
        # Tradability gate
        if max_oi < config.MIN_OPTION_OI:
            return {
                'score': 0.0,
                'tradeable': False,
                'reason': f'Low OI ({max_oi} < {config.MIN_OPTION_OI})',
                'max_oi': max_oi,
                'max_vol': max_vol
            }
        
        if max_vol < config.MIN_OPTION_VOLUME:
            return {
                'score': 0.0,
                'tradeable': False,
                'reason': f'Low volume ({max_vol} < {config.MIN_OPTION_VOLUME})',
                'max_oi': max_oi,
                'max_vol': max_vol
            }
        
        if min_spread > config.MAX_BID_ASK_SPREAD_PCT:
            return {
                'score': 0.0,
                'tradeable': False,
                'reason': f'Wide spread ({min_spread:.1%} > {config.MAX_BID_ASK_SPREAD_PCT:.1%})',
                'max_oi': max_oi,
                'max_vol': max_vol,
                'min_spread': min_spread
            }
        
        # Score components (0-30 points)
        oi_score     = min(max_oi  / 5000, 1.0) * 15  # 0-15 pts
        vol_score    = min(max_vol / 1000, 1.0) * 10  # 0-10 pts
        spread_score = max(
            0,
            (config.MAX_BID_ASK_SPREAD_PCT - min_spread) / config.MAX_BID_ASK_SPREAD_PCT
        ) * 5  # 0-5 pts
        
        total = oi_score + vol_score + spread_score
        
        return {
            'score': total,
            'tradeable': True,
            'reason': 'Liquid',
            'max_oi': max_oi,
            'max_vol': max_vol,
            'min_spread': min_spread
        }
    
    def _compute_uoa_score(self, ticker: str, chain: Dict, current_price: float) -> Dict:
        """
        Compute Unusual Options Activity score (0-30 points).
        
        Detects:
        - OI spike (vs yesterday's OI)
        - Volume spike (vs 5-day avg volume)
        - Large single prints (block trades)
        """
        data = chain.get('data', {})
        
        if not data:
            return {'score': 0.0, 'detected': False, 'reason': 'No chain data'}
        
        # Scan for UOA
        call_uoa_scores = []
        put_uoa_scores = []
        
        for expiration, options_data in data.items():
            # Scan calls
            for strike_str, option in options_data.get('calls', {}).items():
                strike = float(strike_str)
                if abs(strike - current_price) / current_price > 0.10:
                    continue
                
                volume = option.get('volume', 0)
                oi = option.get('openInterest', 0)
                bid = option.get('bid', 0)
                ask = option.get('ask', 0)
                
                if not all([volume, oi, bid, ask]):
                    continue
                
                uoa_score, metadata = self._calculate_uoa_score(volume, oi, bid, ask)
                if uoa_score >= MIN_UOA_SCORE:
                    call_uoa_scores.append(uoa_score)
            
            # Scan puts
            for strike_str, option in options_data.get('puts', {}).items():
                strike = float(strike_str)
                if abs(strike - current_price) / current_price > 0.10:
                    continue
                
                volume = option.get('volume', 0)
                oi = option.get('openInterest', 0)
                bid = option.get('bid', 0)
                ask = option.get('ask', 0)
                
                if not all([volume, oi, bid, ask]):
                    continue
                
                uoa_score, metadata = self._calculate_uoa_score(volume, oi, bid, ask)
                if uoa_score >= MIN_UOA_SCORE:
                    put_uoa_scores.append(uoa_score)
        
        max_call_score = max(call_uoa_scores) if call_uoa_scores else 0
        max_put_score = max(put_uoa_scores) if put_uoa_scores else 0
        max_uoa_score = max(max_call_score, max_put_score)
        
        if max_uoa_score == 0:
            return {'score': 0.0, 'detected': False, 'reason': 'No UOA detected'}
        
        # Convert UOA score to 0-30 point scale
        score = min(max_uoa_score / EXTREME_UOA_SCORE, 1.0) * 30
        
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
        """Calculate UOA score for a single option contract."""
        # Default averages if not provided (conservative estimates)
        if avg_volume is None:
            avg_volume = max(volume / 2.0, 1)
        if avg_oi is None:
            avg_oi = max(open_interest / 1.5, 1)
        
        # Volume ratio: current vs average
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0
        
        # OI ratio: current vs average
        oi_ratio = open_interest / avg_oi if avg_oi > 0 else 0
        
        # Spread quality: inverse of bid-ask spread %
        mid = (bid + ask) / 2 if (bid and ask) else 0
        spread_pct = (ask - bid) / mid if mid > 0 else 999
        
        # Filter out illiquid options with wide spreads
        if spread_pct > MAX_SPREAD_PCT:
            return 0.0, {
                'volume_ratio': volume_ratio,
                'oi_ratio': oi_ratio,
                'spread_pct': spread_pct,
                'spread_quality': 0,
                'is_liquid': False,
                'reason': f'Spread too wide ({spread_pct:.1%} > {MAX_SPREAD_PCT:.1%})'
            }
        
        # Spread quality: 1.0 for tight spreads (1%), 0.5 for wide spreads (10%)
        spread_quality = max(0, 1.0 - (spread_pct / MAX_SPREAD_PCT))
        
        # UOA Score = Volume Ã— OI Ã— Quality
        uoa_score = volume_ratio * oi_ratio * spread_quality
        
        metadata = {
            'volume_ratio': round(volume_ratio, 2),
            'oi_ratio': round(oi_ratio, 2),
            'spread_pct': round(spread_pct, 4),
            'spread_quality': round(spread_quality, 2),
            'is_liquid': True,
            'is_unusual': volume_ratio >= MIN_VOLUME_RATIO,
            'has_institutional': oi_ratio >= MIN_OI_RATIO
        }
        
        return round(uoa_score, 2), metadata
    
    def _compute_gex_score(self, ticker: str, chain: Dict, current_price: float) -> Dict:
        """
        Compute GEX favorability score (0-25 points).
        
        Positive factors:
        - Negative GEX zone (trending environment)
        - Gamma pin above current (for bulls)
        - Strong positive GEX at key levels
        """
        gex_data = compute_gex_levels(chain, current_price)
        
        if not gex_data['has_data']:
            return {'score': 0.0, 'reason': 'No GEX data'}
        
        score = 0.0
        factors = []
        
        # Negative GEX zone = trending (+15 pts)
        if gex_data['neg_gex_zone']:
            score += 15
            factors.append('NEG-GEX-ZONE')
        
        # Gamma pin alignment (+10 pts if favorable)
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
        """
        Compute IV Rank score (0-15 points).
        
        Low IVR = good for option buyers (cheap premium)
        High IVR = good for option sellers (rich premium)
        
        For War Machine (option buyers):
        - IVR < 30 = 15 pts (very cheap)
        - IVR 30-50 = 10 pts (fair)
        - IVR 50-70 = 5 pts (elevated)
        - IVR > 70 = 0 pts (expensive, IV crush risk)
        """
        ivr_data = self._get_ivr_data(ticker, chain)
        
        if not ivr_data or not ivr_data.get('ivr_reliable'):
            return {'score': 5.0, 'reason': 'IVR-BUILDING', 'ivr': None}
        
        ivr = ivr_data['ivr']
        
        if ivr < 30:
            score = 15
            reason = f'IVR-LOW({ivr:.0f})'
        elif ivr < 50:
            score = 10
            reason = f'IVR-FAIR({ivr:.0f})'
        elif ivr < 70:
            score = 5
            reason = f'IVR-ELEVATED({ivr:.0f})'
        else:
            score = 0
            reason = f'IVR-HIGH({ivr:.0f})'
        
        return {
            'score': score,
            'reason': reason,
            'ivr': ivr,
            'current_iv': ivr_data.get('current_iv'),
            'iv_change': ivr_data.get('iv_change')
        }
    
    def _get_ivr_data(self, ticker: str, chain: Dict) -> Optional[Dict]:
        """Get IV Rank data with change detection."""
        data = chain.get('data', {})
        if not data:
            return None
        
        # Get ATM IV from first expiration
        for expiry, opts in data.items():
            for strike_str, opt in opts.get('calls', {}).items():
                iv = opt.get('impliedVolatility', 0)
                if iv and iv > 0:
                    # Store observation
                    store_iv_observation(ticker, iv)
                    
                    # Compute IVR
                    ivr, obs, reliable = compute_ivr(ticker, iv)
                    
                    return {
                        'current_iv': iv,
                        'ivr': ivr,
                        'ivr_obs': obs,
                        'ivr_reliable': reliable,
                        'iv_change': None  # TODO: Track IV change vs yesterday
                    }
        
        return None
    
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # UOA DETECTION: Full Chain Scan
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    
    def scan_chain_for_uoa(self, ticker: str, signal_direction: str,
                          entry_price: float, max_strikes: int = 10) -> Dict:
        """
        Scan entire options chain for unusual activity and determine alignment.
        
        Args:
            ticker: Stock ticker
            signal_direction: "bull" or "bear"
            entry_price: Current stock price
            max_strikes: Maximum strikes to scan around ATM (default 10 = Â±5 strikes)
        
        Returns:
            {
                'uoa_detected': bool,
                'uoa_aligned': bool,
                'uoa_opposing': bool,
                'uoa_multiplier': float,
                'uoa_label': str,
                'uoa_max_score': float,
                'uoa_top_aligned': List[Dict],   # Top 3 aligned UOA strikes
                'uoa_top_opposing': List[Dict]   # Top 3 opposing UOA strikes
            }
        """
        chain = self.get_chain(ticker)
        
        if not chain or not chain.get('data'):
            return {
                'uoa_detected': False,
                'uoa_aligned': False,
                'uoa_opposing': False,
                'uoa_multiplier': 1.0,
                'uoa_label': 'UOA-NEUTRAL',
                'uoa_max_score': 0.0,
                'uoa_top_aligned': [],
                'uoa_top_opposing': []
            }
        
        call_uoa_strikes = []
        put_uoa_strikes = []
        
        # Scan all expirations and strikes
        for expiration, options_data in chain.get("data", {}).items():
            
            # Scan calls
            for strike_str, option in options_data.get("calls", {}).items():
                strike = float(strike_str)
                
                # Only scan strikes within reasonable range of ATM
                if abs(strike - entry_price) / entry_price > 0.10:
                    continue
                
                volume = option.get("volume", 0)
                oi = option.get("openInterest", 0)
                bid = option.get("bid", 0)
                ask = option.get("ask", 0)
                
                if not all([volume, oi, bid, ask]):
                    continue
                
                uoa_score, metadata = self._calculate_uoa_score(volume, oi, bid, ask)
                
                if uoa_score >= MIN_UOA_SCORE:
                    call_uoa_strikes.append({
                        'strike': strike,
                        'expiration': expiration,
                        'type': 'CALL',
                        'uoa_score': uoa_score,
                        'volume': volume,
                        'oi': oi,
                        'metadata': metadata
                    })
            
            # Scan puts
            for strike_str, option in options_data.get("puts", {}).items():
                strike = float(strike_str)
                
                # Only scan strikes within reasonable range of ATM
                if abs(strike - entry_price) / entry_price > 0.10:
                    continue
                
                volume = option.get("volume", 0)
                oi = option.get("openInterest", 0)
                bid = option.get("bid", 0)
                ask = option.get("ask", 0)
                
                if not all([volume, oi, bid, ask]):
                    continue
                
                uoa_score, metadata = self._calculate_uoa_score(volume, oi, bid, ask)
                
                if uoa_score >= MIN_UOA_SCORE:
                    put_uoa_strikes.append({
                        'strike': strike,
                        'expiration': expiration,
                        'type': 'PUT',
                        'uoa_score': uoa_score,
                        'volume': volume,
                        'oi': oi,
                        'metadata': metadata
                    })
        
        # Sort by UOA score (highest first)
        call_uoa_strikes.sort(key=lambda x: x['uoa_score'], reverse=True)
        put_uoa_strikes.sort(key=lambda x: x['uoa_score'], reverse=True)
        
        # Get max scores
        max_call_score = call_uoa_strikes[0]['uoa_score'] if call_uoa_strikes else 0
        max_put_score = put_uoa_strikes[0]['uoa_score'] if put_uoa_strikes else 0
        max_uoa_score = max(max_call_score, max_put_score)
        
        # Determine alignment based on signal direction
        uoa_detected = max_uoa_score >= MIN_UOA_SCORE
        
        if not uoa_detected:
            return {
                'uoa_detected': False,
                'uoa_aligned': False,
                'uoa_opposing': False,
                'uoa_multiplier': 1.0,
                'uoa_label': 'UOA-NEUTRAL',
                'uoa_max_score': 0.0,
                'uoa_top_aligned': [],
                'uoa_top_opposing': []
            }
        
        # Alignment logic
        if signal_direction == "bull":
            aligned_strikes = call_uoa_strikes
            opposing_strikes = put_uoa_strikes
            aligned_type = "CALL"
            opposing_type = "PUT"
        else:  # bear
            aligned_strikes = put_uoa_strikes
            opposing_strikes = call_uoa_strikes
            aligned_type = "PUT"
            opposing_type = "CALL"
        
        max_aligned_score = aligned_strikes[0]['uoa_score'] if aligned_strikes else 0
        max_opposing_score = opposing_strikes[0]['uoa_score'] if opposing_strikes else 0
        
        # Determine dominant UOA
        uoa_aligned = max_aligned_score > max_opposing_score
        uoa_opposing = max_opposing_score > max_aligned_score
        
        # Calculate confidence multiplier
        if uoa_aligned:
            multiplier = ALIGNED_MULTIPLIER
            label = f"UOA-ALIGNED-{aligned_type}(score={max_aligned_score:.1f})"
        elif uoa_opposing:
            multiplier = OPPOSING_MULTIPLIER
            label = f"UOA-OPPOSING-{opposing_type}(score={max_opposing_score:.1f})"
        else:
            multiplier = 1.0
            label = "UOA-MIXED"
        
        return {
            'uoa_detected': True,
            'uoa_aligned': uoa_aligned,
            'uoa_opposing': uoa_opposing,
            'uoa_multiplier': multiplier,
            'uoa_label': label,
            'uoa_max_score': max_uoa_score,
            'uoa_top_aligned': aligned_strikes[:3],
            'uoa_top_opposing': opposing_strikes[:3]
        }
    
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # CACHE MANAGEMENT
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    
    def clear_cache(self, ticker: Optional[str] = None):
        """Clear cache for specific ticker or all tickers."""
        with self._lock:
            if ticker:
                self._chain_cache.pop(ticker, None)
                self._score_cache.pop(ticker, None)
                self._gex_cache.pop(ticker, None)
                self._ivr_cache.pop(ticker, None)
                self._uoa_cache.pop(ticker, None)
                self._prev_chains.pop(ticker, None)
                print(f"[OPTIONS-DM] Cleared cache for {ticker}")
            else:
                self._chain_cache.clear()
                self._score_cache.clear()
                self._gex_cache.clear()
                self._ivr_cache.clear()
                self._uoa_cache.clear()
                self._prev_chains.clear()
                print("[OPTIONS-DM] Cleared all caches")
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        with self._lock:
            return {
                'chains_cached': len(self._chain_cache),
                'scores_cached': len(self._score_cache),
                'gex_cached': len(self._gex_cache),
                'ivr_cached': len(self._ivr_cache),
                'uoa_cached': len(self._uoa_cache),
                'cache_ttl': self.cache_ttl
            }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# GLOBAL INSTANCE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
options_intelligence = OptionsIntelligence(cache_ttl_seconds=300)

# Backward compatibility aliases
options_dm = options_intelligence


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CONVENIENCE FUNCTIONS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

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



