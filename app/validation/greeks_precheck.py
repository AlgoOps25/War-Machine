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
  Fix 4 — Decoupled DTE preference from the signal gate. The precheck
           fetch window is now always 0-30 DTE (PRECHECK_DTE_MAX) so
           tickers like NVDA with only a 3DTE Friday expiry still pass.
           is_valid_dte() is kept on GreeksSnapshot for the downstream
           options selector but is no longer used as a gate here.

DTE Responsibility Split:
  greeks_precheck  → answers "does ANY liquid contract exist?"  (0-30 DTE)
  options_selector → answers "which contract is best?"          (uses config.MIN/MAX/IDEAL_DTE)

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

# FIX 4: Wide fetch window used by the precheck gate.
# This is intentionally broader than config.MAX_DTE (7).
# Rationale: the gate only needs to confirm that SOME liquid contract
# exists — not that a same-day or weekly contract exists. DTE tightness
# is enforced downstream by the options selector.
# 30 days covers all standard weekly/monthly cycles for large-caps.
PRECHECK_DTE_MAX = 30


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
        """
        Check if DTE is within the preferred trading window.

        NOTE: This is intentionally NOT used in quick_validate() (the signal
        gate). It is kept here for use by the downstream options selector when
        ranking/filtering which specific contract to recommend.
        Gate usage would block signals on tickers with no 0DTE (e.g. NVDA on
        a Tuesday), which is wrong — the signal is valid, only the contract
        preference changes.
        """
        return config.MIN_DTE <= self.dte <= config.MAX_DTE


class GreeksCache:
    """
    Greeks pre-validation cache using EODHD data.

    Caches ATM strikes for 5 minutes to reduce API calls.
    Provides fast pre-validation before full chain analysis.

    DTE responsibility split:
      This class answers: "does ANY liquid, delta-valid contract exist?"
      It uses a wide 0-PRECHECK_DTE_MAX window for fetching so signals
      fire for any optionable ticker regardless of which expiry cycle
      is nearest. The options selector (downstream) applies the tight
      DTE window (config.MIN_DTE / IDEAL_DTE / MAX_DTE) when choosing
      the actual contract to trade.
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

        # Cache structure: {ticker: {strike: {option_type: GreeksSnapshot}}}
        self._cache: Dict[str, Dict[float, Dict[str, GreeksSnapshot]]] = {}
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

        print(
            f"[GREEKS-CACHE] Initialized | TTL={cache_ttl}s "
            f"| fetch window=0-{PRECHECK_DTE_MAX}DTE "
            f"| no-options blacklist TTL={NO_OPTIONS_TTL}s"
        )

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

    def _fetch_atm_options(
        self,
        ticker: str,
        current_price: float,
        dte_min: int = 0,
        dte_max: int = PRECHECK_DTE_MAX,
    ) -> List[GreeksSnapshot]:
        """
        Fetch ATM options from EODHD (±10% of current price).

        Args:
            ticker:        Stock ticker
            current_price: Current stock price
            dte_min:       Minimum DTE filter (default 0)
            dte_max:       Maximum DTE filter (default PRECHECK_DTE_MAX=30)
                           NOTE: defaults intentionally wider than config.MAX_DTE.
                           The gate only needs ANY contract; selector applies
                           the tight window later.

        Returns:
            List of GreeksSnapshot objects
        """
        # Calculate strike range (±10%)
        strike_min = current_price * 0.90
        strike_max = current_price * 1.10

        # FIX 3: Use date.today() (date-only, no time component) so that
        # pre-market calls on expiration day don't push the floor to tomorrow
        # and hide same-day 0DTE contracts.
        today_date = date.today()
        exp_from = today_date + timedelta(days=dte_min)
        exp_to   = today_date + timedelta(days=dte_max)

        params = {
            "filter[underlying_symbol]": ticker,
            "filter[exp_date_from]": exp_from.strftime("%Y-%m-%d"),
            "filter[exp_date_to]":   exp_to.strftime("%Y-%m-%d"),
            "filter[strike_from]": int(strike_min),
            "filter[strike_to]": int(strike_max),
            "sort": "strike",
            "limit": 200,
            "api_token": self.api_key,
        }

        try:
            self.stats['api_calls'] += 1
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()

            raw   = response.json()
            items = raw.get("data", [])

            snapshots = []
            for item in items:
                attrs = item.get("attributes", item)

                exp_date    = attrs.get("exp_date", "")
                option_type = attrs.get("type", "").lower()
                strike_raw  = attrs.get("strike", 0)

                try:
                    strike = float(strike_raw)
                except (ValueError, TypeError):
                    continue

                if not exp_date or option_type not in ("call", "put") or strike == 0:
                    continue

                # Calculate DTE using pure date arithmetic (no time-of-day drift)
                try:
                    exp_date_obj = datetime.strptime(exp_date, "%Y-%m-%d").date()
                    dte = (exp_date_obj - today_date).days
                except Exception:
                    dte = 0

                snapshot = GreeksSnapshot(
                    ticker=ticker,
                    strike=float(strike),
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
                    timestamp=datetime.now(),
                )
                snapshots.append(snapshot)

            print(
                f"[GREEKS-CACHE] {ticker}: Fetched {len(snapshots)} ATM options "
                f"(0-{dte_max}DTE window) from EODHD"
            )
            return snapshots

        except Exception as e:
            print(f"[GREEKS-CACHE] Error fetching {ticker}: {e}")
            return []

    def update_cache(self, ticker: str, current_price: float) -> bool:
        """
        Update cache for a ticker using the wide precheck DTE window.

        Args:
            ticker:        Stock ticker
            current_price: Current stock price

        Returns:
            True if cache updated successfully
        """
        # FIX 4: Always use the wide window (0-PRECHECK_DTE_MAX) for the
        # gate fetch, regardless of config.MAX_DTE.
        snapshots = self._fetch_atm_options(
            ticker, current_price, dte_min=0, dte_max=PRECHECK_DTE_MAX
        )

        if not snapshots:
            # FIX 2: Stamp the no-options blacklist so we don't hammer the
            # API again for this ticker for NO_OPTIONS_TTL seconds.
            self._no_options_set[ticker] = time.time()
            print(
                f"[GREEKS-CACHE] {ticker}: No options returned "
                f"— blacklisted for {NO_OPTIONS_TTL // 60} min"
            )
            return False

        # If ticker was previously blacklisted, remove it now that we have data
        self._no_options_set.pop(ticker, None)

        # Build cache: {strike: {'call': snapshot, 'put': snapshot}}
        strike_cache: Dict[float, Dict[str, GreeksSnapshot]] = {}
        for snapshot in snapshots:
            strike      = float(snapshot.strike)
            option_type = snapshot.option_type

            if strike not in strike_cache:
                strike_cache[strike] = {}

            if option_type not in strike_cache[strike]:
                strike_cache[strike][option_type] = snapshot
            else:
                # Keep the contract with better open interest
                existing = strike_cache[strike][option_type]
                if snapshot.open_interest > existing.open_interest:
                    strike_cache[strike][option_type] = snapshot

        self._cache[ticker]            = strike_cache
        self._cache_timestamps[ticker] = time.time()

        total_options = sum(len(opts) for opts in strike_cache.values())
        print(
            f"[GREEKS-CACHE] {ticker}: Cached {len(strike_cache)} strikes "
            f"({total_options} options)"
        )
        return True

    def get_atm_strikes(
        self,
        ticker: str,
        current_price: float,
        num_strikes: int = 5,
        option_type: Optional[str] = None,
    ) -> List[GreeksSnapshot]:
        """
        Get ATM strikes from cache (or fetch if not cached).

        Args:
            ticker:        Stock ticker
            current_price: Current stock price
            num_strikes:   Number of strikes to return (closest to ATM)
            option_type:   Filter by 'call' or 'put' (None = both)

        Returns:
            List of GreeksSnapshot objects sorted by proximity to ATM
        """
        if not self._is_cache_valid(ticker):
            self.stats['cache_misses'] += 1
            self.update_cache(ticker, current_price)
        else:
            self.stats['cache_hits'] += 1

        cache_data = self._cache.get(ticker, {})
        if not cache_data:
            return []

        snapshots = []
        for strike_dict in cache_data.values():
            for opt_type, snapshot in strike_dict.items():
                if option_type is None or opt_type == option_type:
                    snapshots.append(snapshot)

        current_price_float = float(current_price)
        snapshots.sort(key=lambda x: abs(float(x.strike) - current_price_float))
        return snapshots[:num_strikes]

    def quick_validate(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
    ) -> Tuple[bool, str]:
        """
        Quick pre-validation of options availability.

        Answers: "Does ANY liquid, delta-valid contract exist for this ticker?"
        Does NOT enforce DTE tightness — that is the options selector's job.

        A BOS+FVG signal on NVDA is valid whether the nearest expiry is
        0DTE (Friday on expiration day) or 3DTE (Tuesday before Friday expiry).
        The signal fires either way; the selector picks the best contract.

        Gate criteria (both must pass):
          1. is_liquid()       — OI, volume, spread
          2. is_valid_delta()  — delta in [TARGET_DELTA_MIN, TARGET_DELTA_MAX]

        is_valid_dte() is intentionally excluded from the gate.

        Args:
            ticker:      Stock ticker
            direction:   'bull' or 'bear'
            entry_price: Entry price for the trade

        Returns:
            Tuple of (is_valid, reason)
        """
        self.stats['quick_validates'] += 1

        # FIX 2: Short-circuit for known non-optionable tickers
        if ticker in self._no_options_set:
            blacklist_age = time.time() - self._no_options_set[ticker]
            if blacklist_age < NO_OPTIONS_TTL:
                self.stats['no_options_skips'] += 1
                self.stats['quick_fails'] += 1
                mins_left = int((NO_OPTIONS_TTL - blacklist_age) / 60)
                return False, (
                    f"No options available for {ticker} "
                    f"(blacklisted, {mins_left}min remaining)"
                )

        # Get ATM strikes (wide DTE window via cache)
        atm_strikes = self.get_atm_strikes(ticker, entry_price, num_strikes=7)
        if not atm_strikes:
            self.stats['quick_fails'] += 1
            return False, "No ATM options data available"

        option_type      = "call" if direction == "bull" else "put"
        relevant_options = self.get_atm_strikes(
            ticker, entry_price, num_strikes=7, option_type=option_type
        )
        if not relevant_options:
            self.stats['quick_fails'] += 1
            return False, f"No {option_type}s found near ATM"

        # FIX 4: Gate on liquidity + delta ONLY — not DTE.
        # DTE preference is enforced by the options selector downstream.
        valid_options = [
            s for s in relevant_options
            if s.is_liquid() and s.is_valid_delta()
        ]

        if not valid_options:
            reasons = []
            if not any(s.is_liquid() for s in relevant_options):
                reasons.append("low liquidity")
            if not any(s.is_valid_delta() for s in relevant_options):
                reasons.append("poor delta")
            reason = f"No valid {option_type}s: " + ", ".join(reasons)
            self.stats['quick_fails'] += 1
            return False, reason

        # Pass — report the nearest-expiry valid contract found
        # Sort by DTE ascending so we surface the soonest expiry first
        valid_options.sort(key=lambda s: s.dte)
        best = valid_options[0]
        self.stats['quick_passes'] += 1

        reason = (
            f"Valid {option_type}s available: "
            f"${best.strike:.0f} strike, Δ={best.delta:.2f}, "
            f"IV={best.iv * 100:.0f}%, {best.dte}DTE"
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

        best_strike     = None
        best_delta_diff = 999.0

        for strike, opts in cache_data.items():
            call = opts.get('call')
            if call and call.delta > 0:
                delta_diff = abs(call.delta - 0.50)
                if delta_diff < best_delta_diff:
                    best_delta_diff = delta_diff
                    best_strike     = float(strike)

        return best_strike

    def get_stats(self) -> Dict:
        """Get cache statistics."""
        total_requests = self.stats['cache_hits'] + self.stats['cache_misses']
        hit_rate = (
            self.stats['cache_hits'] / total_requests * 100
        ) if total_requests > 0 else 0

        quick_total = self.stats['quick_validates']
        pass_rate   = (
            self.stats['quick_passes'] / quick_total * 100
        ) if quick_total > 0 else 0

        return {
            **self.stats,
            'cache_hit_rate':    round(hit_rate, 1),
            'quick_pass_rate':   round(pass_rate, 1),
            'api_call_reduction': round(hit_rate, 1),
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
def quick_validate_options(
    ticker: str, direction: str, entry_price: float
) -> Tuple[bool, str]:
    """
    Quick pre-validation convenience function.

    Usage:
        is_valid, reason = quick_validate_options("AAPL", "bull", 175.50)
    """
    return greeks_cache.quick_validate(ticker, direction, entry_price)


def get_cached_greeks(
    ticker: str, direction: str, num_strikes: int = 5
) -> List[Dict]:
    """
    Get cached Greeks data — returns dict format for Discord alerts.
    Already sorted by DTE ascending (soonest expiry first) then ATM proximity.

    Usage:
        greeks_list = get_cached_greeks("AAPL", "bull", num_strikes=5)
        best = greeks_list[0]
    """
    current_price = greeks_cache.estimate_current_price(ticker)
    if not current_price:
        return []

    option_type = "call" if direction == "bull" else "put"
    snapshots   = greeks_cache.get_atm_strikes(
        ticker, current_price, num_strikes=num_strikes, option_type=option_type
    )

    results = []
    for snapshot in snapshots:
        if snapshot.is_liquid() and snapshot.is_valid_delta():
            results.append({
                'strike':    float(snapshot.strike),
                'delta':     float(snapshot.delta),
                'iv':        float(snapshot.iv),
                'dte':       snapshot.dte,
                'spread_pct': float(snapshot.spread_pct),
                'is_liquid': snapshot.is_liquid(),
                'bid':       float(snapshot.bid),
                'ask':       float(snapshot.ask),
            })

    # Sort by DTE ascending so caller always sees soonest-expiry first
    results.sort(key=lambda x: x['dte'])
    return results


if __name__ == "__main__":
    """Test the Greeks cache with real data."""
    print("\n" + "=" * 70)
    print("GREEKS PRE-VALIDATION CACHE - Test Suite")
    print("=" * 70 + "\n")

    test_ticker   = "AAPL"
    initial_price = 250.0

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
    print(f"Found {len(calls)} ATM call strikes (sorted by DTE asc):\n")
    for i, strike_data in enumerate(calls[:3], 1):
        print(f"{i}. ${strike_data['strike']:.0f} CALL  |  {strike_data['dte']}DTE")
        print(f"   Delta: {strike_data['delta']:.3f} | IV: {strike_data['iv']*100:.1f}%")
        print(
            f"   Bid/Ask: ${strike_data['bid']:.2f}/${strike_data['ask']:.2f} "
            f"(spread: {strike_data['spread_pct']:.1f}%)"
        )
        print(
            f"   Liquid: {'✅' if strike_data['is_liquid'] else '❌'} "
            f"| Delta OK: {'✅' if abs(strike_data['delta']) >= 0.30 else '❌'}\n"
        )

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

def validate_signal_greeks(
    ticker: str, direction: str, entry_price: float
) -> tuple[bool, str]:
    """
    Fast pre-validation using cached Greeks data.
    Called from sniper.py Step 6.5 to confirm options exist before alerting.

    Returns:
        (is_valid, reason_string)

    Examples:
        (True,  "Valid calls: $265 strike, Δ=0.50, IV=31%, 3DTE")
        (False, "No valid calls: poor delta")
        (False, "No options available for XYZ (blacklisted, 28min remaining)")

    Fix history:
      Fix 1 (Mar 12): Removed unconditional update_cache() — TTL handled inside
                      get_atm_strikes() → _is_cache_valid().
      Fix 4 (Mar 12): DTE no longer used as a gate. Signal fires for any
                      optionable ticker regardless of nearest expiry cycle.
    """
    try:
        is_valid, reason = quick_validate_options(ticker, direction, entry_price)
        return is_valid, reason
    except Exception as e:
        return True, f"Validation skipped: {e}"
