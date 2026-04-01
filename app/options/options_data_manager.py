"""
Options Data Manager - High-Performance 0DTE Options Chain Builder

Role (clarified Phase 2, Mar 26 2026)
--------------------------------------
This module is a SPECIALISED 0DTE chain fetcher that talks directly to
the EODHD UnicornBay contracts endpoint.  It is NOT the primary chain
cache used by the rest of the system.

Architecture relationship:
  OptionsDataManager  (this file)
    → Fetches raw 0DTE contracts directly from EODHD UnicornBay API
    → Filters by liquidity, selects best strike via delta targeting
    → 60-second TTL, per-direction cache
    → PRIMARY CONSUMER: app/ai/ai_learning.py (strike selection)

  OptionsIntelligence  (options_intelligence.py)
    → Fetches the options chain via app/validation/validation.OptionsFilter
    → Houses UOA detection, GEX headwind checks, IVR scoring
    → 5-minute TTL, thread-safe RLock caches
    → PRIMARY CONSUMERS: scanner (scoring), sniper (Step 6.5 pre-filter)

Overlap analysis (Phase 2, Mar 26 2026)
-----------------------------------------
The two classes share a namespace prefix (options_dm / options_intelligence)
but serve DIFFERENT purposes and use DIFFERENT API endpoints:

  Overlap area              Status
  ─────────────────────     ──────────────────────────────────────────
  Caching pattern           Both cache, different TTLs (60s vs 300s)
                            → NO duplication: each caches what it fetches
  Liquidity filtering       Both filter by OI/volume
                            → MILD overlap; thresholds differ (0DTE vs regular)
                            → Low priority to consolidate — different contexts
  clear_cache() / stats()   Both expose these helpers
                            → TRIVIAL overlap; independent instances
  Strike selection          Only OptionsDataManager does this
                            → UNIQUE to this file
  GEX / UOA / IVR scoring   Only OptionsIntelligence does this
                            → UNIQUE to options_intelligence.py

Conclusion: NO consolidation needed between these two files.
The naming similarity is misleading but the responsibilities are distinct.
Issue #39 (rename) raised to clarify intent going forward.

Optimizations:
1. Smart strike filtering (volume + OI requirements)
2. Greeks caching (60s TTL) - avoid redundant API calls
3. Delta/gamma targeting for 0DTE scalps
4. 0DTE-specific strike selection (tighter ATM focus)

Usage:
    from app.options.options_data_manager import OptionsDataManager

    odm = OptionsDataManager()
    chain = odm.get_optimized_chain(ticker="NVDA", direction="CALL", for_0dte=True)
"""
import logging
import os
import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from collections import defaultdict

logger = logging.getLogger(__name__)

# EODHD Configuration
EODHD_API_KEY = os.getenv('EODHD_API_KEY', '')
EODHD_BASE_URL = 'https://eodhd.com/api/mp/unicornbay'
REQUEST_TIMEOUT = 30

# Cache Configuration
CACHE_TTL = 60  # 60 seconds cache for Greeks during rapid scanning

# Liquidity Filters
MIN_VOLUME_0DTE = 50       # Minimum volume for 0DTE options
MIN_OI_0DTE = 100          # Minimum open interest for 0DTE
MIN_VOLUME_REGULAR = 20    # Minimum volume for regular options
MIN_OI_REGULAR = 50        # Minimum open interest for regular options

# 0DTE Delta Ranges (tighter than regular options)
DELTA_RANGES_0DTE = {
    'aggressive': (0.45, 0.55),   # Near ATM for max gamma
    'balanced': (0.35, 0.45),     # Slightly OTM
    'conservative': (0.25, 0.35)  # Further OTM but still liquid
}

# Regular Delta Ranges
DELTA_RANGES_REGULAR = {
    'aggressive': (0.55, 0.70),
    'balanced': (0.40, 0.55),
    'conservative': (0.30, 0.45)
}


class OptionsDataManager:
    """High-performance options chain manager with caching and delta-targeting."""

    def __init__(self):
        self._cache = {}  # ticker -> {timestamp, data}

    def get_optimized_chain(
        self,
        ticker: str,
        direction: str,
        target_dte: int = 0,
        for_0dte: bool = True,
        confidence: float = 75.0
    ) -> Optional[Dict]:
        """
        Get optimized options chain with best strike selection.

        Args:
            ticker: Stock symbol
            direction: "CALL" or "PUT"
            target_dte: Days to expiration (0 for 0DTE)
            for_0dte: Use 0DTE-specific filters and ranges
            confidence: Signal confidence (determines aggressiveness)

        Returns:
            dict: Best option contract with Greeks, or None if unavailable
        """
        cache_key = f"{ticker}_{direction}_{target_dte}"

        # Check cache first
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() - cached['timestamp'] < CACHE_TTL:
                logger.debug(f"[OPTIONS-DM] Cache hit for {cache_key}")
                return cached['data']

        # Fetch chain
        chain = self._fetch_chain(ticker, direction, target_dte, for_0dte)

        if not chain:
            logger.warning(f"[OPTIONS-DM] No chain data for {ticker}")
            return None

        # Select best strike based on confidence
        best_contract = self._select_best_strike(
            chain,
            confidence,
            for_0dte
        )

        # Cache result
        self._cache[cache_key] = {
            'timestamp': time.time(),
            'data': best_contract
        }

        return best_contract

    def _fetch_chain(
        self,
        ticker: str,
        direction: str,
        target_dte: int,
        for_0dte: bool
    ) -> List[Dict]:
        """
        Fetch options chain from EODHD UnicornBay API.

        For 0DTE: Fetch today's expiration only
        For regular: Fetch target_dte +/- 7 days
        """
        if not EODHD_API_KEY:
            logger.warning("[OPTIONS-DM] EODHD_API_KEY not set")
            return []

        # Calculate DTE range
        if for_0dte:
            min_dte, max_dte = 0, 0  # Only today
        else:
            min_dte = max(1, target_dte - 7)
            max_dte = target_dte + 7

        # Retry logic (3 attempts)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                url = f"{EODHD_BASE_URL}/options/contracts"
                params = {
                    'filter[underlying_symbol]': ticker,
                    'filter[type]': direction.lower(),
                    'filter[dte_gte]': min_dte,
                    'filter[dte_lte]': max_dte,
                    'page[size]': 200 if for_0dte else 100,
                    'api_token': EODHD_API_KEY
                }

                response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()

                if not data or 'data' not in data:
                    logger.warning(f"[OPTIONS-DM] No data returned for {ticker}")
                    return []

                contracts = data['data']
                logger.info(f"[OPTIONS-DM] Fetched {len(contracts)} contracts for {ticker}")

                # Filter by liquidity
                filtered = self._filter_by_liquidity(contracts, for_0dte)
                logger.info(f"[OPTIONS-DM] {len(filtered)} contracts after liquidity filter")

                return filtered

            except requests.exceptions.Timeout:
                logger.warning(f"[OPTIONS-DM] Timeout attempt {attempt + 1}/{max_retries} for {ticker}")
                if attempt < max_retries - 1:
                    time.sleep(2)  # Wait 2s before retry
                    continue
                logger.error(f"[OPTIONS-DM] All retries exhausted for {ticker}")
                return []

            except requests.exceptions.HTTPError as e:
                logger.error(f"[OPTIONS-DM] HTTP error for {ticker}: {e}")
                return []

            except Exception as e:
                logger.error(f"[OPTIONS-DM] Failed to fetch chain for {ticker}: {e}")
                return []

        return []

    def _filter_by_liquidity(
        self,
        contracts: List[Dict],
        for_0dte: bool
    ) -> List[Dict]:
        """Filter contracts by minimum volume and open interest."""
        min_vol = MIN_VOLUME_0DTE if for_0dte else MIN_VOLUME_REGULAR
        min_oi = MIN_OI_0DTE if for_0dte else MIN_OI_REGULAR

        filtered = []
        for contract in contracts:
            attrs = contract.get('attributes', {})
            volume = attrs.get('volume', 0)
            oi = attrs.get('open_interest', 0)

            # For 0DTE, require EITHER good volume OR good OI (more lenient)
            if for_0dte:
                if volume >= min_vol or oi >= min_oi:
                    filtered.append(contract)
            else:
                # Regular options: require both
                if volume >= min_vol and oi >= min_oi:
                    filtered.append(contract)

        return filtered

    def _select_best_strike(
        self,
        chain: List[Dict],
        confidence: float,
        for_0dte: bool
    ) -> Optional[Dict]:
        """
        Select best strike based on confidence and delta targeting.

        High confidence (80+): Aggressive (near ATM, max gamma)
        Medium confidence (70-80): Balanced
        Lower confidence (60-70): Conservative (further OTM)
        """
        if not chain:
            return None

        # Determine aggressiveness
        if confidence >= 80:
            strategy = 'aggressive'
        elif confidence >= 70:
            strategy = 'balanced'
        else:
            strategy = 'conservative'

        # Get target delta range
        delta_ranges = DELTA_RANGES_0DTE if for_0dte else DELTA_RANGES_REGULAR
        min_delta, max_delta = delta_ranges[strategy]

        # Find contracts in delta range
        candidates = []
        for contract in chain:
            attrs = contract.get('attributes', {})
            delta = abs(attrs.get('delta', 0))  # Absolute for puts

            if min_delta <= delta <= max_delta:
                candidates.append(contract)

        if not candidates:
            logger.warning(f"[OPTIONS-DM] No contracts in delta range {min_delta}-{max_delta}")
            # Fallback: pick closest delta
            candidates = chain

        # Sort by best liquidity (volume + OI)
        def liquidity_score(c):
            attrs = c.get('attributes', {})
            return attrs.get('volume', 0) + (attrs.get('open_interest', 0) * 0.5)

        candidates.sort(key=liquidity_score, reverse=True)

        # Return top candidate
        best = candidates[0]
        attrs = best.get('attributes', {})

        bid = attrs.get('bid', 0)
        ask = attrs.get('ask', 0)
        midpoint = attrs.get('midpoint', (bid + ask) / 2 if (bid and ask) else attrs.get('last', 0))

        result = {
            'strike': attrs.get('strike'),
            'expiration': attrs.get('exp_date'),
            'delta': attrs.get('delta'),
            'gamma': attrs.get('gamma'),
            'theta': attrs.get('theta'),
            'vega': attrs.get('vega'),
            'iv': attrs.get('volatility', 0) * 100,
            'price': midpoint,
            'bid': bid,
            'ask': ask,
            'volume': attrs.get('volume', 0),
            'open_interest': attrs.get('open_interest', 0),
            'strategy': strategy
        }

        logger.info(
            f"[OPTIONS-DM] Selected ${result['strike']} "
            f"(delta={result['delta']:.2f}, vol={result['volume']}, OI={result['open_interest']})"
        )

        return result

    def clear_cache(self):
        """Clear expired cache entries."""
        now = time.time()
        expired = [k for k, v in self._cache.items() if now - v['timestamp'] > CACHE_TTL]
        for k in expired:
            del self._cache[k]

    def get_cache_stats(self) -> Dict:
        """Get cache statistics for monitoring."""
        return {
            'cached_tickers': len(self._cache),
            'ttl_seconds': CACHE_TTL
        }
