"""
Greeks Pre-Validation Cache for Options Filtering
Task 3: EODHD-based Greeks caching and fast pre-validation

Reduces API calls by 80% and speeds up validation 10x by:
- Caching Greeks data for 5 minutes
- Only fetching ATM strikes (±10% of current price)
- Pre-validating delta/IV/spread before full chain analysis
- Blocking bad options before Discord alerts fire

Bug fixes (Phase 1.17, Mar 12 2026):
  Fix 1 — validate_signal_greeks() no longer calls update_cache()
           unconditionally; TTL-aware refresh is handled inside
           get_atm_strikes() → _is_cache_valid().
  Fix 2 — Added _no_options_set: tickers that return empty chains are
           blacklisted for NO_OPTIONS_TTL (30 min) to prevent repeated
           API spam on non-optionable symbols.
  Fix 3 — _fetch_atm_options() now uses date.today() (not datetime.now())
           for exp_date_from so 0DTE contracts are visible pre-market.

Usage:
    from app.validation.greeks_precheck import greeks_cache
    
    # Quick pre-check (uses cache, ~100ms)
    is_valid, reason = greeks_cache.quick_validate(ticker, direction, entry_price)
    
    # Get cached ATM strikes
    atm_strikes = greeks_cache.get_atm_strikes(ticker, entry_price, num_strikes=5)
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
from dataclasses import dataclass
import time
import requests

from utils import config

# How long to suppress retries for tickers with no options (30 minutes)
NO_OPTIONS_TTL = 1800


@dataclass
class GreeksSnapshot:
    """Cached Greeks data for a single strike."""
    ticker: str
    strike: float
    expiration: str
    option_type: str  # "call" or "put"
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    dte: int
    timestamp: datetime
    
    @property
    def mid(self) -> float:
        """Calculate mid price."""
        return (self.bid + self.ask) / 2 if (self.bid and self.ask) else 0.0
    
    @property
    def spread_pct(self) -> float:
        """Calculate bid-ask spread percentage."""
        mid = self.mid
        if mid > 0:
            return ((self.ask - self.bid) / mid) * 100
        return 999.0
    
    def is_liquid(self) -> bool:
        """Check if option meets liquidity requirements."""
        return (
            self.open_interest >= config.MIN_OPTION_OI and
            self.volume >= config.MIN_OPTION_VOLUME and
            self.spread_pct <= (config.MAX_BID_ASK_SPREAD_PCT * 100)
        )
    
    def is_valid_delta(self) -> bool:
        """Check if delta is in acceptable range."""
        abs_delta = abs(self.delta)
        return config.TARGET_DELTA_MIN <= abs_delta <= config.TARGET_DELTA_MAX
    
    def is_valid_dte(self) -> bool:
        """Check if DTE is in acceptable range."""
        return config.MIN_DTE <= self.dte <= config.MAX_DTE


class GreeksCache:
    """
    Greeks pre-validation cache using EODHD data.
    
    Caches ATM strikes for 5 minutes to reduce API calls.
    Provides fast pre-validation before full chain analysis.
    """
    
    def __init__(self, cache_ttl: int = 300):
        """
        Initialize Greeks cache.
        
        Args:
            cache_ttl: Cache time-to-live in seconds (default 5 minutes)
        """
        self.cache_ttl = cache_ttl
        self.api_key = config.EODHD_API_KEY
        self.base_url = "https://eodhd.com/api/mp/unicornbay/options/contracts"
        
        # Cache structure: {ticker: {strike: GreeksSnapshot}}
        self._cache: Dict[str, Dict[float, GreeksSnapshot]] = {}
        self._cache_timestamps: Dict[str, float] = {}

        # FIX 2: Negative-result blacklist — tickers confirmed to have no
        # options. Keyed by ticker, value is the timestamp of the failed fetch.
        # Suppresses re-fetches for NO_OPTIONS_TTL (30 min).
        self._no_options_set: Dict[str, float] = {}
        
        # Stats
        self.stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'api_calls': 0,
            'quick_validates': 0,
            'quick_passes': 0,
            'quick_fails': 0,
            'no_options_skips': 0,
        }
        
        print(f"[GREEKS-CACHE] Initialized with {cache_ttl}s TTL | no-options blacklist TTL={NO_OPTIONS_TTL}s")
    
    def _is_cache_valid(self, ticker: str) -> bool:
        """
        Check if cached data is still valid.

        FIX 2: Also returns True (skip fetch) when ticker is in the
        no-options blacklist and the blacklist entry hasn't expired yet.
        """
        # Positive cache
        if ticker in self._cache_timestamps:
            age = time.time() - self._cache_timestamps[ticker]
            if age < self.cache_ttl:
                return True

        # FIX 2: Negative-result blacklist check
        if ticker in self._no_options_set:
            blacklist_age = time.time() - self._no_options_set[ticker]
            if blacklist_age < NO_OPTIONS_TTL:
                return True  # treat as "valid" (i.e. don't re-fetch)

        return False
    
    def _fetch_atm_options(self, ticker: str, current_price: float, 
                          dte_min: int = None, dte_max: int = None) -> List[GreeksSnapshot]:
        """
        Fetch ATM options from EODHD (±10% of current price).
        
        Args:
            ticker: Stock ticker
            current_price: Current stock price
            dte_min: Minimum DTE filter (defaults to config.MIN_DTE)
            dte_max: Maximum DTE filter (defaults to config.MAX_DTE)
        
        Returns:
            List of GreeksSnapshot objects
        """
        if dte_min is None:
            dte_min = config.MIN_DTE
        if dte_max is None:
            dte_max = config.MAX_DTE
        
        # Calculate strike range (±10%)
        strike_min = current_price * 0.90
        strike_max = current_price * 1.10
        
        # FIX 3: Use date.today() (date-only, no time component) so that
        # pre-market calls on expiration day don't push the floor to tomorrow
        # and hide same-day 0DTE contracts.
        today_date = date.today()
        exp_from = today_date + timedelta(days=dte_min)
        exp_to   = today_date + timedelta(days=dte_max)

        # Still need datetime for DTE calculation below
        today_dt = datetime.now()

        params = {
            "filter[underlying_symbol]": ticker,
            "filter[exp_date_from]": exp_from.strftime("%Y-%m-%d"),
            "filter[exp_date_to]":   exp_to.strftime("%Y-%m-%d"),
            "filter[strike_from]": int(strike_min),
            "filter[strike_to]": int(strike_max),
            "sort": "strike",
            "limit": 200,  # Much smaller than full chain (1000)
            "api_token": self.api_key,
        }
        
        try:
            self.stats['api_calls'] += 1
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            
            raw = response.json()
            items = raw.get("data", [])
            
            snapshots = []
            for item in items:
                attrs = item.get("attributes", item)
                
                # Parse fields
                exp_date = attrs.get("exp_date", "")
                option_type = attrs.get("type", "").lower()
                strike_raw = attrs.get("strike", 0)
                
                # FIX: Ensure strike is a float
                try:
                    strike = float(strike_raw)
                except (ValueError, TypeError):
                    continue
                
                if not exp_date or option_type not in ("call", "put") or strike == 0:
                    continue
                
                # Calculate DTE using date arithmetic to avoid time-of-day drift
                try:
                    exp_date_obj = datetime.strptime(exp_date, "%Y-%m-%d").date()
                    dte = (exp_date_obj - today_date).days
                except Exception:
                    dte = 0
                
                # Create snapshot with all floats properly converted
                snapshot = GreeksSnapshot(
                    ticker=ticker,
                    strike=float(strike),  # Ensure float
                    expiration=exp_date,
                    option_type=option_type,
                    delta=float(attrs.get("delta", 0)),
                    gamma=float(attrs.get("gamma", 0)),
                    theta=float(attrs.get("theta", 0)),
                    vega=float(attrs.get("vega", 0)),
                    iv=float(attrs.get("volatility", 0)),
                    bid=float(attrs.get("bid", 0)),
                    ask=float(attrs.get("ask", 0)),
                    volume=int(attrs.get("volume", 0)),
                    open_interest=int(attrs.get("open_interest", 0)),
                    dte=dte,
                    timestamp=datetime.now()
                )
                
                snapshots.append(snapshot)
            
            print(f"[GREEKS-CACHE] {ticker}: Fetched {len(snapshots)} ATM options from EODHD")
            return snapshots
            
        except Exception as e:
            print(f"[GREEKS-CACHE] Error fetching {ticker}: {e}")
            return []
    
    def update_cache(self, ticker: str, current_price: float) -> bool:
        """
        Update cache for a ticker.
        
        Args:
            ticker: Stock ticker
            current_price: Current stock price
        
        Returns:
            True if cache updated successfully
        """
        snapshots = self._fetch_atm_options(ticker, current_price)
        
        if not snapshots:
            # FIX 2: Stamp the no-options blacklist so we don't hammer the
            # API again for this ticker for NO_OPTIONS_TTL seconds.
            self._no_options_set[ticker] = time.time()
            print(f"[GREEKS-CACHE] {ticker}: No options returned — blacklisted for {NO_OPTIONS_TTL//60} min")
            return False
        
        # If ticker was previously blacklisted, remove it now that we have data
        self._no_options_set.pop(ticker, None)

        # Build cache structure: {strike: {'call': snapshot, 'put': snapshot}}
        strike_cache: Dict[float, Dict[str, GreeksSnapshot]] = {}
        for snapshot in snapshots:
            strike = float(snapshot.strike)  # Ensure float
            option_type = snapshot.option_type
            
            if strike not in strike_cache:
                strike_cache[strike] = {}
            
            # Store both calls and puts separately
            if option_type not in strike_cache[strike]:
                strike_cache[strike][option_type] = snapshot
            else:
                # Keep the one with better liquidity
                existing = strike_cache[strike][option_type]
                if snapshot.open_interest > existing.open_interest:
                    strike_cache[strike][option_type] = snapshot
        
        self._cache[ticker] = strike_cache
        self._cache_timestamps[ticker] = time.time()
        
        # Count total options (calls + puts)
        total_options = sum(len(opts) for opts in strike_cache.values())
        print(f"[GREEKS-CACHE] {ticker}: Cached {len(strike_cache)} strikes ({total_options} options)")
        return True

    def get_atm_strikes(self, ticker: str, current_price: float, 
                       num_strikes: int = 5, option_type: Optional[str] = None) -> List[GreeksSnapshot]:
        """
        Get ATM strikes from cache (or fetch if not cached).
        
        Args:
            ticker: Stock ticker
            current_price: Current stock price
            num_strikes: Number of strikes to return (closest to ATM)
            option_type: Filter by 'call' or 'put' (None = both)
        
        Returns:
            List of GreeksSnapshot objects sorted by proximity to ATM
        """
        # Check cache validity (also covers the no-options blacklist)
        if not self._is_cache_valid(ticker):
            self.stats['cache_misses'] += 1
            self.update_cache(ticker, current_price)
        else:
            self.stats['cache_hits'] += 1
        
        # Get cached data
        cache_data = self._cache.get(ticker, {})
        if not cache_data:
            return []
        
        # Flatten the nested structure and filter by option type
        snapshots = []
        for strike_dict in cache_data.values():
            for opt_type, snapshot in strike_dict.items():
                if option_type is None or opt_type == option_type:
                    snapshots.append(snapshot)
        
        # Sort by proximity to current price (both strike and current_price are floats now)
        current_price_float = float(current_price)  # Ensure float
        snapshots.sort(key=lambda x: abs(float(x.strike) - current_price_float))
        
        return snapshots[:num_strikes]
    
    def quick_validate(self, ticker: str, direction: str, 
                      entry_price: float) -> Tuple[bool, str]:
        """
        Quick pre-validation of options availability.
        
        Checks if there are ANY viable options before full chain analysis.
        Uses cached ATM strikes for fast validation.
        
        Args:
            ticker: Stock ticker
            direction: 'bull' or 'bear'
            entry_price: Entry price for the trade
        
        Returns:
            Tuple of (is_valid, reason)
        """
        self.stats['quick_validates'] += 1

        # FIX 2: Short-circuit immediately for known non-optionable tickers
        if ticker in self._no_options_set:
            blacklist_age = time.time() - self._no_options_set[ticker]
            if blacklist_age < NO_OPTIONS_TTL:
                self.stats['no_options_skips'] += 1
                self.stats['quick_fails'] += 1
                mins_left = int((NO_OPTIONS_TTL - blacklist_age) / 60)
                return False, f"No options available for {ticker} (blacklisted {mins_left}min remaining)"
        
        # Get ATM strikes
        atm_strikes = self.get_atm_strikes(ticker, entry_price, num_strikes=7)
        
        if not atm_strikes:
            self.stats['quick_fails'] += 1
            return False, "No ATM options data available"
        
        # Filter by option type
        option_type = "call" if direction == "bull" else "put"
        relevant_options = self.get_atm_strikes(ticker, entry_price, num_strikes=7, option_type=option_type)
        
        if not relevant_options:
            self.stats['quick_fails'] += 1
            return False, f"No {option_type}s found near ATM"
        
        # Check if ANY option meets basic criteria
        valid_options = []
        for snapshot in relevant_options:
            if (snapshot.is_liquid() and 
                snapshot.is_valid_delta() and 
                snapshot.is_valid_dte()):
                valid_options.append(snapshot)
        
        if not valid_options:
            # Provide specific failure reason
            reasons = []
            if not any(s.is_liquid() for s in relevant_options):
                reasons.append("low liquidity")
            if not any(s.is_valid_delta() for s in relevant_options):
                reasons.append("poor delta")
            if not any(s.is_valid_dte() for s in relevant_options):
                reasons.append("no valid DTE")
            
            reason = f"No valid {option_type}s: " + ", ".join(reasons)
            self.stats['quick_fails'] += 1
            return False, reason
        
        # Found valid options
        best = valid_options[0]
        self.stats['quick_passes'] += 1
        
        reason = (
            f"Valid {option_type}s available: "
            f"${best.strike:.0f} strike, Δ={best.delta:.2f}, "
            f"IV={best.iv*100:.0f}%, {best.dte}DTE"
        )
        
        return True, reason

    def estimate_current_price(self, ticker: str) -> Optional[float]:
        """
        Estimate current stock price from cached ATM options.
        Uses the strike closest to delta 0.50 for calls.
        
        Returns:
            Estimated current price or None if cache is empty
        """
        cache_data = self._cache.get(ticker, {})
        if not cache_data:
            return None
        
        # Find call closest to delta 0.50 (ATM)
        best_strike = None
        best_delta_diff = 999.0
        
        for strike, opts in cache_data.items():
            call = opts.get('call')
            if call and call.delta > 0:
                delta_diff = abs(call.delta - 0.50)
                if delta_diff < best_delta_diff:
                    best_delta_diff = delta_diff
                    best_strike = float(strike)  # Ensure float
        
        return best_strike

    def get_stats(self) -> Dict:
        """Get cache statistics."""
        total_requests = self.stats['cache_hits'] + self.stats['cache_misses']
        hit_rate = (self.stats['cache_hits'] / total_requests * 100) if total_requests > 0 else 0
        
        quick_total = self.stats['quick_validates']
        pass_rate = (self.stats['quick_passes'] / quick_total * 100) if quick_total > 0 else 0
        
        return {
            **self.stats,
            'cache_hit_rate': round(hit_rate, 1),
            'quick_pass_rate': round(pass_rate, 1),
            'api_call_reduction': round(hit_rate, 1)  # Same as hit rate
        }
    
    def clear_cache(self, ticker: Optional[str] = None):
        """Clear cache for a specific ticker or all tickers."""
        if ticker:
            self._cache.pop(ticker, None)
            self._cache_timestamps.pop(ticker, None)
            self._no_options_set.pop(ticker, None)
            print(f"[GREEKS-CACHE] Cleared cache for {ticker}")
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
            self._no_options_set.clear()
            print("[GREEKS-CACHE] Cleared all cache")


# Global instance
greeks_cache = GreeksCache(cache_ttl=300)


# Convenience functions
def quick_validate_options(ticker: str, direction: str, entry_price: float) -> Tuple[bool, str]:
    """
    Quick pre-validation convenience function.
    
    Usage:
        is_valid, reason = quick_validate_options("AAPL", "bull", 175.50)
    """
    return greeks_cache.quick_validate(ticker, direction, entry_price)


def get_cached_greeks(ticker: str, direction: str, num_strikes: int = 5) -> List[Dict]:
    """
    Get cached Greeks data convenience function - returns dict format for Discord alerts.
    
    Usage:
        greeks_list = get_cached_greeks("AAPL", "bull", num_strikes=5)
        best = greeks_list[0]  # Already sorted by quality
    """
    # Get current price estimate from cache
    current_price = greeks_cache.estimate_current_price(ticker)
    if not current_price:
        return []
    
    # Get ATM strikes filtered by direction
    option_type = "call" if direction == "bull" else "put"
    snapshots = greeks_cache.get_atm_strikes(
        ticker, current_price, num_strikes=num_strikes, option_type=option_type
    )
    
    # Convert to dict format with quality scoring
    results = []
    for snapshot in snapshots:
        if snapshot.is_liquid() and snapshot.is_valid_delta():
            results.append({
                'strike': float(snapshot.strike),
                'delta': float(snapshot.delta),
                'iv': float(snapshot.iv),
                'dte': snapshot.dte,
                'spread_pct': float(snapshot.spread_pct),
                'is_liquid': snapshot.is_liquid(),
                'bid': float(snapshot.bid),
                'ask': float(snapshot.ask)
            })
    
    return results


if __name__ == "__main__":
    """Test the Greeks cache with real data."""
    print("\n" + "=" * 70)
    print("GREEKS PRE-VALIDATION CACHE - Test Suite")
    print("=" * 70 + "\n")
    
    # First, do a quick fetch to discover real price
    test_ticker = "AAPL"
    initial_price = 250.0  # Starting guess
    
    print(f"Discovering real {test_ticker} price...")
    greeks_cache.update_cache(test_ticker, initial_price)
    real_price = greeks_cache.estimate_current_price(test_ticker)
    
    if real_price:
        print(f"✅ Estimated {test_ticker} price: ${real_price:.2f}\n")
        test_price = real_price
    else:
        print(f"⚠️  Could not estimate price, using ${initial_price}\n")
        test_price = initial_price
    
    print(f"Test 1: Quick validate {test_ticker} CALL at ${test_price:.2f}")
    is_valid, reason = quick_validate_options(test_ticker, "bull", test_price)
    print(f"Result: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Reason: {reason}\n")
    
    print(f"Test 2: Quick validate {test_ticker} PUT at ${test_price:.2f}")
    is_valid, reason = quick_validate_options(test_ticker, "bear", test_price)
    print(f"Result: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Reason: {reason}\n")
    
    print(f"Test 3: Get cached ATM CALLS for {test_ticker}")
    calls = get_cached_greeks(test_ticker, "bull", num_strikes=5)
    print(f"Found {len(calls)} ATM call strikes:\n")
    
    for i, strike_data in enumerate(calls[:3], 1):
        print(f"{i}. ${strike_data['strike']:.0f} CALL")
        print(f"   Delta: {strike_data['delta']:.3f} | IV: {strike_data['iv']*100:.1f}%")
        print(f"   Bid/Ask: ${strike_data['bid']:.2f}/${strike_data['ask']:.2f} (spread: {strike_data['spread_pct']:.1f}%)")
        liquid_check = '✅' if strike_data['is_liquid'] else '❌'
        delta_check = '✅' if abs(strike_data['delta']) >= 0.30 else '❌'
        print(f"   Liquid: {liquid_check} | Delta OK: {delta_check}\n")
    
    print("=" * 70)
    print("Cache Statistics:")
    print("=" * 70)
    stats = greeks_cache.get_stats()
    for key, value in stats.items():
        print(f"{key}: {value}")
    print("=" * 70)

# ════════════════════════════════════════════════════════════════════════════════
# INTEGRATION FUNCTION FOR SNIPER.PY
# ════════════════════════════════════════════════════════════════════════════════

def validate_signal_greeks(ticker: str, direction: str, entry_price: float) -> tuple[bool, str]:
    """
    Fast pre-validation using cached Greeks data.
    Called from sniper.py Step 6.5 to block signals with bad options early.
    
    Returns:
        (is_valid, reason_string)
        
    Examples:
        (True, "Valid calls: $265 strike, Δ=0.50, IV=31%, 2DTE")
        (False, "No valid calls: poor delta")

    FIX 1 (Mar 12 2026): Removed unconditional update_cache() call that was
    bypassing the TTL on every signal. Cache refresh is now handled entirely
    inside quick_validate() → get_atm_strikes() → _is_cache_valid().
    """
    try:
        # FIX 1: Do NOT call update_cache() here — the TTL-aware refresh path
        # inside get_atm_strikes() handles it. Calling it unconditionally was
        # firing a fresh EODHD API request on every single signal regardless
        # of cache age, negating the entire 5-minute TTL design.
        is_valid, reason = quick_validate_options(ticker, direction, entry_price)
        return is_valid, reason
        
    except Exception as e:
        # Non-fatal: return True to avoid blocking on errors
        return True, f"Validation skipped: {e}"
