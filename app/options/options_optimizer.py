"""
0DTE Options Chain Optimizer
Parallel Greeks fetching, smart strike filtering, delta/gamma targeting.

PHASE 3B - March 8, 2026
Michael's 0DTE trading optimization

TEST MODE: Use --test flag for simulated data when market is closed
"""
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import time
import random


def generate_test_strike_data(
    ticker: str,
    strike: float,
    current_price: float,
    option_type: str,
    expiration: str
) -> Dict:
    """
    Generate realistic test data for a strike when market is closed.
    
    Uses realistic Greeks calculations based on moneyness to simulate
    actual market conditions for testing/demo purposes.
    """
    # Calculate moneyness (distance from ATM)
    if option_type == "call":
        moneyness = (strike - current_price) / current_price
        # Calls: ITM (negative moneyness) = higher delta
        base_delta = max(0.05, min(0.95, 0.50 - (moneyness * 2)))
    else:
        moneyness = (current_price - strike) / current_price
        # Puts: ITM (positive moneyness) = higher delta (negative)
        base_delta = -max(0.05, min(0.95, 0.50 - (moneyness * 2)))
    
    # Add some randomness to simulate market variance
    delta = base_delta + random.uniform(-0.05, 0.05)
    delta = max(-0.95, min(0.95, delta))
    
    # Calculate realistic Greeks
    gamma = abs(delta) * (1 - abs(delta)) * 0.04  # Max gamma near ATM
    theta = -abs(delta) * 0.15  # Time decay proportional to delta
    vega = abs(delta) * (1 - abs(delta)) * 0.25  # Max vega near ATM
    iv = 0.25 + random.uniform(-0.05, 0.10)  # 20-35% IV range
    
    # Generate bid/ask based on moneyness (ATM = tighter spreads)
    if abs(moneyness) < 0.02:  # ATM
        mid = 2.50 + random.uniform(-0.50, 0.50)
        spread = 0.05
    elif abs(moneyness) < 0.05:  # Near ATM
        mid = 1.80 + random.uniform(-0.40, 0.40)
        spread = 0.08
    else:  # OTM/ITM
        mid = 0.80 + random.uniform(-0.30, 0.30)
        spread = 0.12
    
    bid = max(0.01, mid - spread)
    ask = mid + spread
    
    # Volume and OI (higher near ATM)
    if abs(moneyness) < 0.05:
        volume = random.randint(500, 5000)
        oi = random.randint(1000, 10000)
    else:
        volume = random.randint(100, 1000)
        oi = random.randint(200, 2000)
    
    return {
        "strike": strike,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "iv": iv,
        "bid": round(bid, 2),
        "ask": round(ask, 2),
        "volume": volume,
        "oi": oi,
        "last": round(mid, 2)
    }


class OptionsChainOptimizer:
    """
    Optimized options chain fetcher for 0DTE trading.
    - Parallel Greeks fetching (7 strikes simultaneously)
    - Smart strike filtering (only relevant strikes)
    - Delta/gamma targeting (0.30-0.50 sweet spot)
    - Test mode for weekend/offline development
    """
    
    def __init__(self, test_mode: bool = False):
        # Import config only when needed to avoid circular imports
        try:
            from utils import config
            self.api_key = config.EODHD_API_KEY
        except:
            self.api_key = None
        
        self.base_url = "https://eodhd.com/api/mp/unicornbay/options-contracts"
        self.session: Optional[aiohttp.ClientSession] = None
        self.test_mode = test_mode
        
        # Performance tracking
        self.stats = {
            "total_fetches": 0,
            "parallel_fetches": 0,
            "strikes_filtered": 0,
            "time_saved_sec": 0.0
        }
        
        if self.test_mode:
            print("[OPTIONS-OPT] 🧪 TEST MODE: Using simulated data")
    
    async def __aenter__(self):
        """Async context manager entry"""
        if not self.test_mode:
            self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    def get_smart_strike_range(
        self,
        current_price: float,
        direction: str,
        num_strikes: int = 7
    ) -> Tuple[float, float]:
        """
        Calculate optimal strike range for 0DTE options.
        
        Args:
            current_price: Current stock price
            direction: "bull" (calls) or "bear" (puts)
            num_strikes: Number of strikes to fetch (default 7: ITM-3 to OTM+3)
        
        Returns:
            (min_strike, max_strike) tuple
        """
        # Strike spacing (typically $0.50 for liquid stocks, $1.00 for less liquid)
        spacing = 0.50 if current_price < 100 else 1.00
        
        # Calculate ATM strike (rounded to nearest strike price)
        atm_strike = round(current_price / spacing) * spacing
        
        if direction == "bull":
            # Calls: Focus slightly ITM to slightly OTM
            # ITM-2 to OTM+4 for bullish bias
            min_strike = atm_strike - (2 * spacing)
            max_strike = atm_strike + (4 * spacing)
        else:
            # Puts: Focus slightly ITM to slightly OTM
            # ITM-2 to OTM+4 for bearish bias
            min_strike = atm_strike - (4 * spacing)
            max_strike = atm_strike + (2 * spacing)
        
        return (min_strike, max_strike)
    
    async def fetch_strike_greeks_async(
        self,
        ticker: str,
        strike: float,
        expiration: str,
        option_type: str,
        current_price: Optional[float] = None
    ) -> Optional[Dict]:
        """
        Fetch Greeks for a single strike asynchronously.
        
        Args:
            ticker: Stock symbol
            strike: Strike price
            expiration: Expiration date (YYYY-MM-DD)
            option_type: "call" or "put"
            current_price: Current stock price (used in test mode)
        
        Returns:
            Dict with Greeks or None on error
        """
        # TEST MODE: Generate simulated data
        if self.test_mode:
            if current_price is None:
                return None
            await asyncio.sleep(0.05)  # Simulate network delay
            return generate_test_strike_data(ticker, strike, current_price, option_type, expiration)
        
        # PRODUCTION MODE: Real API call
        if not self.session:
            print("[OPTIONS-OPT] ⚠️  Session not initialized - use async with")
            return None
        
        params = {
            "filter[underlying_symbol]": ticker,
            "filter[expdate]": expiration,
            "filter[strike]": strike,
            "filter[type]": option_type,
            "apitoken": self.api_key,
            "limit": 1
        }
        
        try:
            async with self.session.get(self.base_url, params=params, timeout=5) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                items = data.get("data", [])
                
                if not items:
                    return None
                
                attrs = items[0].get("attributes", {})
                
                return {
                    "strike": strike,
                    "delta": attrs.get("delta", 0),
                    "gamma": attrs.get("gamma", 0),
                    "theta": attrs.get("theta", 0),
                    "vega": attrs.get("vega", 0),
                    "iv": attrs.get("volatility", 0),
                    "bid": attrs.get("bid", 0),
                    "ask": attrs.get("ask", 0),
                    "volume": attrs.get("volume", 0),
                    "oi": attrs.get("openinterest", 0),
                    "last": attrs.get("last", 0)
                }
        except Exception as e:
            print(f"[OPTIONS-OPT] ❌ Error fetching {ticker} {strike}{option_type[0].upper()}: {e}")
            return None
    
    async def fetch_optimal_strikes_parallel(
        self,
        ticker: str,
        current_price: float,
        direction: str,
        target_delta_min: float = 0.30,
        target_delta_max: float = 0.50
    ) -> List[Dict]:
        """
        Fetch optimal strikes in parallel with delta/gamma filtering.
        
        Args:
            ticker: Stock symbol
            current_price: Current stock price
            direction: "bull" (calls) or "bear" (puts)
            target_delta_min: Minimum delta (default 0.30)
            target_delta_max: Maximum delta (default 0.50)
        
        Returns:
            List of strike dicts sorted by score (best first)
        """
        start_time = time.time()
        self.stats["total_fetches"] += 1
        
        # Get smart strike range
        min_strike, max_strike = self.get_smart_strike_range(current_price, direction)
        
        # Find 0DTE expiration (today or tomorrow if <2.5 hours left)
        now_et = datetime.now()
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        hours_left = (market_close - now_et).total_seconds() / 3600
        
        if hours_left < 2.5:
            # Use tomorrow's expiration (1DTE)
            expiration = (now_et + timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"[OPTIONS-OPT] 🕐 Using 1DTE ({hours_left:.1f}h left today)")
        else:
            # Use today's expiration (0DTE)
            expiration = now_et.strftime("%Y-%m-%d")
            print(f"[OPTIONS-OPT] 🎯 Using 0DTE ({hours_left:.1f}h left)")
        
        # Generate strike list
        spacing = 0.50 if current_price < 100 else 1.00
        strikes = []
        current_strike = min_strike
        while current_strike <= max_strike:
            strikes.append(current_strike)
            current_strike += spacing
        
        option_type = "call" if direction == "bull" else "put"
        
        print(f"[OPTIONS-OPT] ⚡ Fetching {len(strikes)} strikes in parallel...")
        print(f"[OPTIONS-OPT]    Range: ${min_strike:.2f} - ${max_strike:.2f}")
        print(f"[OPTIONS-OPT]    Target Δ: {target_delta_min:.2f} - {target_delta_max:.2f}")
        
        # Fetch all strikes in parallel
        tasks = [
            self.fetch_strike_greeks_async(ticker, strike, expiration, option_type, current_price=current_price)
            for strike in strikes
        ]
        
        results = await asyncio.gather(*tasks)
        self.stats["parallel_fetches"] += len(tasks)
        
        # Filter valid results with target delta range
        valid_strikes = []
        for result in results:
            if result is None:
                continue
            
            delta = abs(result["delta"])
            
            # Must have liquidity
            if result["bid"] == 0 or result["ask"] == 0:
                self.stats["strikes_filtered"] += 1
                continue
            
            # Must be in target delta range
            if not (target_delta_min <= delta <= target_delta_max):
                self.stats["strikes_filtered"] += 1
                continue
            
            # Calculate spread
            mid = (result["bid"] + result["ask"]) / 2
            spread_pct = ((result["ask"] - result["bid"]) / mid * 100) if mid > 0 else 999
            
            # Filter wide spreads (>15%)
            if spread_pct > 15:
                self.stats["strikes_filtered"] += 1
                continue
            
            # Score the strike (higher is better)
            score = self._score_strike(result, spread_pct, target_delta_min, target_delta_max)
            result["score"] = score
            result["spread_pct"] = spread_pct
            result["mid"] = mid
            
            valid_strikes.append(result)
        
        # Sort by score (best first)
        valid_strikes.sort(key=lambda x: x["score"], reverse=True)
        
        elapsed = time.time() - start_time
        self.stats["time_saved_sec"] += max(0, (len(strikes) * 0.3) - elapsed)  # Estimate 300ms per serial fetch
        
        print(f"[OPTIONS-OPT] ✅ Found {len(valid_strikes)}/{len(strikes)} valid strikes in {elapsed:.2f}s")
        
        if valid_strikes:
            best = valid_strikes[0]
            print(f"[OPTIONS-OPT] 🏆 BEST: ${best['strike']:.2f} "
                  f"Δ={best['delta']:.3f} γ={best['gamma']:.4f} "
                  f"Bid/Ask=${best['bid']:.2f}/${best['ask']:.2f} "
                  f"Score={best['score']:.1f}")
        
        return valid_strikes
    
    def _score_strike(
        self,
        strike_data: Dict,
        spread_pct: float,
        target_delta_min: float,
        target_delta_max: float
    ) -> float:
        """
        Score a strike based on Greeks and liquidity.
        
        Args:
            strike_data: Strike data with Greeks
            spread_pct: Bid-ask spread percentage
            target_delta_min: Target min delta
            target_delta_max: Target max delta
        
        Returns:
            Score (0-100, higher is better)
        """
        score = 100.0
        
        delta = abs(strike_data["delta"])
        gamma = strike_data["gamma"]
        volume = strike_data["volume"]
        oi = strike_data["oi"]
        
        # Delta targeting (prefer middle of range)
        target_delta = (target_delta_min + target_delta_max) / 2
        delta_distance = abs(delta - target_delta)
        delta_score = max(0, 30 - (delta_distance * 100))  # Max 30 points
        
        # Gamma preference (higher gamma = more responsive)
        gamma_score = min(20, gamma * 5000)  # Max 20 points
        
        # Liquidity score
        volume_score = min(15, volume / 100)  # Max 15 points
        oi_score = min(15, oi / 100)  # Max 15 points
        
        # Spread tightness (lower is better)
        spread_score = max(0, 20 - spread_pct)  # Max 20 points
        
        total_score = delta_score + gamma_score + volume_score + oi_score + spread_score
        
        return round(total_score, 1)
    
    def get_stats(self) -> Dict:
        """Get performance statistics"""
        return {
            **self.stats,
            "avg_strikes_per_fetch": (
                round(self.stats["parallel_fetches"] / self.stats["total_fetches"], 1)
                if self.stats["total_fetches"] > 0 else 0
            ),
            "time_saved_min": round(self.stats["time_saved_sec"] / 60, 2)
        }
    
    def print_stats(self):
        """Print performance statistics"""
        stats = self.get_stats()
        print("\n" + "="*70)
        print("OPTIONS CHAIN OPTIMIZER - PERFORMANCE STATS")
        print("="*70)
        print(f"Total Fetches:          {stats['total_fetches']}")
        print(f"Strikes Fetched:        {stats['parallel_fetches']}")
        print(f"Avg Strikes/Fetch:      {stats['avg_strikes_per_fetch']}")
        print(f"Strikes Filtered:       {stats['strikes_filtered']}")
        print(f"Time Saved:             {stats['time_saved_min']:.2f} minutes")
        print("="*70 + "\n")


# Synchronous wrapper for existing code compatibility
def get_optimal_strikes_sync(
    ticker: str,
    current_price: float,
    direction: str,
    target_delta_min: float = 0.30,
    target_delta_max: float = 0.50,
    test_mode: bool = False
) -> List[Dict]:
    """
    Synchronous wrapper for get_optimal_strikes_parallel.
    Use this in existing non-async code.
    
    Args:
        ticker: Stock symbol
        current_price: Current stock price
        direction: "bull" (calls) or "bear" (puts)
        target_delta_min: Minimum delta (default 0.30)
        target_delta_max: Maximum delta (default 0.50)
        test_mode: Use simulated data instead of API (default False)
    
    Returns:
        List of strike dicts sorted by score (best first)
    """
    async def _run():
        async with OptionsChainOptimizer(test_mode=test_mode) as optimizer:
            return await optimizer.fetch_optimal_strikes_parallel(
                ticker, current_price, direction, target_delta_min, target_delta_max
            )
    
    return asyncio.run(_run())


# Example usage
if __name__ == "__main__":
    import sys
    
    # Check for test mode flag
    test_mode = "--test" in sys.argv or "--demo" in sys.argv
    
    print("=" * 70)
    print("0DTE OPTIONS CHAIN OPTIMIZER - TEST SUITE")
    print("=" * 70)
    
    if test_mode:
        print("🧪 RUNNING IN TEST MODE (simulated data)\n")
    else:
        now = datetime.now()
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6
        market_hours = 9 <= now.hour < 16
        
        if is_weekend or not market_hours:
            print("🔴 WARNING: Market is closed")
            print("💡 Run with --test flag to see simulated data demo")
            print("   Example: python -m app.options.options_optimizer --test\n")
        else:
            print("🟢 Market is open - using LIVE DATA\n")
    
    print("Testing 0DTE Options Chain Optimizer...\n")
    
    # Test with AAPL
    ticker = "AAPL"
    current_price = 225.50
    direction = "bull"  # Looking for calls
    
    print(f"Ticker:   {ticker}")
    print(f"Price:    ${current_price}")
    print(f"Strategy: {direction.upper()} (calls)")
    print(f"Target Δ: 0.30 - 0.50\n")
    
    strikes = get_optimal_strikes_sync(ticker, current_price, direction, test_mode=test_mode)
    
    if strikes:
        print(f"\n✅ SUCCESS: Found {len(strikes)} optimal strikes")
        print("=" * 70)
        
        for i, strike in enumerate(strikes[:3], 1):
            print(f"\n#{i} STRIKE: ${strike['strike']:.2f}")
            print(f"   Score:     {strike['score']:.1f}/100")
            print(f"   Delta:     {strike['delta']:.3f}")
            print(f"   Gamma:     {strike['gamma']:.4f}")
            print(f"   Theta:     {strike['theta']:.3f}")
            print(f"   IV:        {strike['iv']*100:.1f}%")
            print(f"   Bid/Ask:   ${strike['bid']:.2f} / ${strike['ask']:.2f}")
            print(f"   Mid:       ${strike['mid']:.2f}")
            print(f"   Spread:    {strike['spread_pct']:.1f}%")
            print(f"   Volume:    {strike['volume']:,}")
            print(f"   OI:        {strike['oi']:,}")
        
        if len(strikes) > 3:
            print(f"\n   ... and {len(strikes) - 3} more strikes")
        
        print("\n" + "=" * 70)
        print("RECOMMENDATION:")
        best = strikes[0]
        print(f"BUY {ticker} ${int(best['strike'])}C")
        print(f"LIMIT PRICE: ${best['mid']:.2f} (mid)")
        print(f"MAX PRICE:   ${best['ask']:.2f} (ask)")
        print("=" * 70)
    else:
        print("\n❌ FAILURE: No optimal strikes found")
        if not test_mode:
            print("💡 This is expected on weekends - try --test flag for demo")
        print("=" * 70)
