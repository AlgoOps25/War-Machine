"""
Options DTE Selector - Data-Driven Expiration Selection

Responsibilities:
  - Fetch options chain from EODHD for 0DTE and 1DTE contracts
  - Analyze liquidity (open interest, volume)
  - Assess theta decay rates
  - Check bid/ask spreads
  - Compare implied volatility levels
  - Score and recommend optimal DTE based on market conditions
  - Provide strike recommendations with Greeks analysis

 DTE Selection Logic:
  - Time remaining until market close
  - Options liquidity (OI > 100, Volume > 50)
  - Theta decay acceptability (< $0.15/day for late session)
  - Bid/ask spread tightness (< 10% of mid price)
  - IV premium comparison (0DTE vs 1DTE)
  - Volume activity (> 25 contracts)
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import requests
import os

ET = ZoneInfo("America/New_York")


class OptionsDTESelector:
    """Intelligent DTE selection based on real-time options market data."""
    
    def __init__(self, eodhd_api_key: Optional[str] = None):
        """
        Initialize with EODHD API credentials.
        
        Args:
            eodhd_api_key: EODHD API key (defaults to EODHD_API_KEY env var)
        """
        self.api_key = eodhd_api_key or os.getenv('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError("EODHD_API_KEY not provided or found in environment")
        
        # Thresholds for decision-making
        self.min_open_interest = 100
        self.min_volume = 50
        self.min_total_volume = 25
        self.max_spread_pct = 10.0  # 10% of mid price
        self.max_iv_premium_pct = 20.0  # 0DTE IV can't be >20% higher than 1DTE
        
        print("[OPTIONS-DTE] Selector initialized with EODHD data integration")
    
    def calculate_optimal_dte(self, 
                             ticker: str, 
                             entry_price: float,
                             direction: str,
                             confidence: float,
                             current_time: Optional[datetime] = None) -> Dict:
        """
        Calculate optimal DTE using real-time market data.
        
        Args:
            ticker: Stock ticker symbol
            entry_price: Expected entry price
            direction: 'BUY' or 'SELL'
            confidence: Signal confidence (0-100)
            current_time: Current time (defaults to now ET)
        
        Returns:
            Dict with DTE recommendation and strike suggestions
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        # Calculate time remaining
        market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        time_remaining_hours = (market_close - current_time).total_seconds() / 3600
        
        # Early exit if market already closed
        if time_remaining_hours <= 0:
            return self._create_skip_response(
                "Market closed - no options trading",
                time_remaining_hours
            )
        
        # Fetch options data from EODHD
        try:
            options_data = self.fetch_options_chain(ticker, entry_price, direction)
            if not options_data:
                return self._create_fallback_response(
                    "No options data available from EODHD",
                    time_remaining_hours
                )
        except Exception as e:
            print(f"[OPTIONS-DTE] Error fetching options: {e}")
            return self._create_fallback_response(
                f"API error: {str(e)}",
                time_remaining_hours
            )
        
        # Separate 0DTE and 1DTE contracts
        dte_0_contracts = [opt for opt in options_data if opt['dte'] == 0]
        dte_1_contracts = [opt for opt in options_data if opt['dte'] == 1]
        
        if not dte_0_contracts and not dte_1_contracts:
            return self._create_fallback_response(
                "No 0DTE or 1DTE contracts found",
                time_remaining_hours
            )
        
        # Analyze market conditions
        factors = self._analyze_dte_factors(
            dte_0_contracts,
            dte_1_contracts,
            time_remaining_hours
        )
        
        # Calculate score for 0DTE viability
        score_0dte = self._calculate_dte_score(factors)
        max_score = 10.5
        score_threshold = 0.7  # Need 70% confidence for 0DTE
        
        # Make DTE decision
        if dte_0_contracts and (score_0dte / max_score) >= score_threshold:
            selected_dte = 0
            selected_contracts = dte_0_contracts
            reasoning = self._get_dte_reasoning(factors, "0DTE")
        elif dte_1_contracts:
            selected_dte = 1
            selected_contracts = dte_1_contracts
            reasoning = self._get_dte_reasoning(factors, "1DTE")
        else:
            return self._create_skip_response(
                "No viable contracts available",
                time_remaining_hours
            )
        
        # Select best strikes
        best_strikes = self.select_best_strikes(
            selected_contracts,
            entry_price,
            direction
        )
        
        if not best_strikes:
            return self._create_fallback_response(
                f"No quality {selected_dte}DTE strikes found",
                time_remaining_hours
            )
        
        # Build response
        return {
            'dte': selected_dte,
            'expiry_date': best_strikes[0]['exp_date'],
            'recommended_strikes': best_strikes[:2],  # Top 2 strikes
            'reasoning': reasoning,
            'data_factors': factors,
            'time_remaining_hours': round(time_remaining_hours, 2),
            'score': round(score_0dte, 2),
            'max_score': max_score,
            'confidence_pct': round((score_0dte / max_score) * 100, 1)
        }
    
    def fetch_options_chain(self, 
                           ticker: str, 
                           price: float, 
                           direction: str) -> List[Dict]:
        """
        Fetch options chain from EODHD for 0DTE and 1DTE expiries.
        
        Args:
            ticker: Stock ticker
            price: Current stock price
            direction: 'BUY' or 'SELL'
        
        Returns:
            List of option contract dicts with DTE calculated
        """
        today = datetime.now(ET).date()
        
        # Get next trading day expirations
        dte_0_date = self._get_next_trading_day(today, offset=0)
        dte_1_date = self._get_next_trading_day(today, offset=1)
        
        option_type = "call" if direction == "BUY" else "put"
        
        # Strike range: ±5% from current price
        strike_low = int(price * 0.95)
        strike_high = int(price * 1.05)
        
        # EODHD Options API endpoint
        url = "https://eodhd.com/api/options/{ticker}".format(ticker=ticker)
        
        params = {
            "api_token": self.api_key,
            "from": str(dte_0_date),
            "to": str(dte_1_date),
            "contract_name": option_type
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"[OPTIONS-DTE] EODHD API error: {e}")
            return []
        
        if not data or 'data' not in data:
            print(f"[OPTIONS-DTE] No options data returned for {ticker}")
            return []
        
        # Parse and enrich contracts
        contracts = []
        for contract in data['data']:
            try:
                exp_date = datetime.strptime(contract['expirationDate'], '%Y-%m-%d').date()
                dte = (exp_date - today).days
                
                # Only include 0DTE and 1DTE
                if dte not in [0, 1]:
                    continue
                
                # Filter by strike range
                strike = float(contract.get('strike', 0))
                if strike < strike_low or strike > strike_high:
                    continue
                
                contracts.append({
                    'contract': contract.get('contractName', ''),
                    'strike': strike,
                    'exp_date': str(exp_date),
                    'dte': dte,
                    'bid': float(contract.get('bid', 0)),
                    'ask': float(contract.get('ask', 0)),
                    'last_price': float(contract.get('lastPrice', 0)),
                    'volume': int(contract.get('volume', 0)),
                    'open_interest': int(contract.get('openInterest', 0)),
                    'delta': float(contract.get('delta', 0)),
                    'gamma': float(contract.get('gamma', 0)),
                    'theta': float(contract.get('theta', 0)),
                    'vega': float(contract.get('vega', 0)),
                    'volatility': float(contract.get('impliedVolatility', 0))
                })
            except (KeyError, ValueError) as e:
                # Skip malformed contracts
                continue
        
        print(f"[OPTIONS-DTE] Fetched {len(contracts)} contracts for {ticker} (0DTE/1DTE {option_type}s)")
        return contracts
    
    def _analyze_dte_factors(self, 
                            dte_0_contracts: List[Dict],
                            dte_1_contracts: List[Dict],
                            time_remaining_hours: float) -> Dict:
        """
        Analyze market conditions to determine DTE viability.
        
        Returns:
            Dict of boolean factors for DTE decision
        """
        factors = {
            'time_adequate': time_remaining_hours >= 1.5,
            'dte_0_liquid': self._check_liquidity(dte_0_contracts),
            'dte_0_theta_acceptable': self._check_theta_decay(dte_0_contracts, time_remaining_hours),
            'dte_0_spread_tight': self._check_bid_ask_spread(dte_0_contracts),
            'iv_favorable': self._check_iv_levels(dte_0_contracts, dte_1_contracts),
            'volume_sufficient': self._check_volume(dte_0_contracts)
        }
        
        return factors
    
    def _check_liquidity(self, contracts: List[Dict]) -> bool:
        """Check if contracts have sufficient liquidity."""
        if not contracts:
            return False
        
        avg_oi = sum(c.get('open_interest', 0) for c in contracts) / len(contracts)
        avg_volume = sum(c.get('volume', 0) for c in contracts) / len(contracts)
        
        return avg_oi > self.min_open_interest and avg_volume > self.min_volume
    
    def _check_theta_decay(self, contracts: List[Dict], time_remaining_hours: float) -> bool:
        """Check if theta decay is acceptable given time remaining."""
        if not contracts:
            return False
        
        avg_theta = abs(sum(c.get('theta', 0) for c in contracts) / len(contracts))
        
        if time_remaining_hours >= 4:
            return True  # Theta OK with plenty of time
        elif time_remaining_hours >= 2:
            return avg_theta < 0.15  # Moderate theta acceptable
        else:
            return avg_theta < 0.08  # Only minimal theta acceptable
    
    def _check_bid_ask_spread(self, contracts: List[Dict]) -> bool:
        """Check if bid/ask spreads are tight enough for good execution."""
        if not contracts:
            return False
        
        tight_spreads = []
        for c in contracts:
            bid = c.get('bid', 0)
            ask = c.get('ask', 0)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread_pct = ((ask - bid) / mid) * 100
                tight_spreads.append(spread_pct < self.max_spread_pct)
        
        return len(tight_spreads) > 0 and sum(tight_spreads) / len(tight_spreads) > 0.7
    
    def _check_iv_levels(self, dte_0_contracts: List[Dict], dte_1_contracts: List[Dict]) -> bool:
        """Compare IV between 0DTE and 1DTE - prefer 0DTE if not inflated."""
        if not dte_0_contracts or not dte_1_contracts:
            return True  # Can't compare, assume OK
        
        avg_iv_0 = sum(c.get('volatility', 0) for c in dte_0_contracts) / len(dte_0_contracts)
        avg_iv_1 = sum(c.get('volatility', 0) for c in dte_1_contracts) / len(dte_1_contracts)
        
        if avg_iv_1 == 0:
            return True
        
        # 0DTE IV should not be >20% higher than 1DTE
        iv_premium = ((avg_iv_0 - avg_iv_1) / avg_iv_1) * 100
        return iv_premium < self.max_iv_premium_pct
    
    def _check_volume(self, contracts: List[Dict]) -> bool:
        """Verify today's volume is active."""
        if not contracts:
            return False
        
        total_volume = sum(c.get('volume', 0) for c in contracts)
        return total_volume > self.min_total_volume
    
    def _calculate_dte_score(self, factors: Dict) -> float:
        """Calculate weighted score for 0DTE viability."""
        score = 0.0
        score += 3.0 if factors['time_adequate'] else 0  # Critical
        score += 2.0 if factors['dte_0_liquid'] else 0  # Very important
        score += 2.0 if factors['dte_0_theta_acceptable'] else 0  # Very important
        score += 1.5 if factors['dte_0_spread_tight'] else 0  # Important
        score += 1.0 if factors['iv_favorable'] else 0  # Nice to have
        score += 1.0 if factors['volume_sufficient'] else 0  # Nice to have
        return score
    
    def _get_dte_reasoning(self, factors: Dict, selected_dte: str) -> str:
        """Generate human-readable reasoning for DTE selection."""
        reasoning = []
        
        if selected_dte == "0DTE":
            reasoning.append("✅ SELECTED: 0DTE (Expires Today)")
            if factors['time_adequate']:
                reasoning.append("✅ Time Adequate: >1.5 hours remaining")
            if factors['dte_0_liquid']:
                reasoning.append("✅ Liquidity Strong: Good OI and Volume")
            if factors['dte_0_theta_acceptable']:
                reasoning.append("✅ Theta Acceptable: Decay manageable")
            if factors['dte_0_spread_tight']:
                reasoning.append("✅ Spread Tight: <10% execution cost")
            if factors['iv_favorable']:
                reasoning.append("✅ IV Fair: Not inflated vs 1DTE")
            if factors['volume_sufficient']:
                reasoning.append("✅ Volume Active: Market participation")
        else:
            reasoning.append("📅 SELECTED: 1DTE (Expires Tomorrow)")
            reasons = []
            if not factors['time_adequate']:
                reasons.append("⏰ Limited time (<1.5 hrs)")
            if not factors['dte_0_liquid']:
                reasons.append("💧 0DTE liquidity weak")
            if not factors['dte_0_theta_acceptable']:
                reasons.append("⏳ 0DTE theta too aggressive")
            if not factors['dte_0_spread_tight']:
                reasons.append("📊 0DTE spreads too wide")
            if not factors['iv_favorable']:
                reasons.append("📈 0DTE IV inflated")
            if not factors['volume_sufficient']:
                reasons.append("📉 0DTE volume low")
            
            if reasons:
                reasoning.append("Reasons for 1DTE preference:")
                reasoning.extend(reasons)
        
        return "\n".join(reasoning)
    
    def select_best_strikes(self, 
                           contracts: List[Dict],
                           entry_price: float,
                           direction: str) -> List[Dict]:
        """
        Select best strike recommendations based on Greeks and liquidity.
        
        Scoring criteria:
        - Delta: 0.4-0.6 for balance (10 pts max)
        - Open Interest: Higher is better (10 pts max)
        - Bid/Ask Spread: Tighter is better (10 pts max)
        
        Returns:
            List of top-scored contracts with metadata
        """
        scored_contracts = []
        
        for c in contracts:
            delta = abs(c.get('delta', 0))
            oi = c.get('open_interest', 0)
            bid = c.get('bid', 0)
            ask = c.get('ask', 0)
            
            if bid <= 0 or ask <= 0:
                continue  # Skip contracts with no pricing
            
            spread = ((ask - bid) / ((ask + bid) / 2)) * 100
            
            # Scoring
            delta_score = 10 if 0.4 <= delta <= 0.6 else (5 if 0.3 <= delta <= 0.7 else 0)
            oi_score = min(oi / 100, 10)  # Max 10 for OI > 1000
            spread_score = max(10 - spread, 0)  # Max 10 for 0% spread
            
            total_score = delta_score + oi_score + spread_score
            
            scored_contracts.append({
                'contract': c.get('contract'),
                'strike': c.get('strike'),
                'exp_date': c.get('exp_date'),
                'delta': delta,
                'theta': c.get('theta'),
                'gamma': c.get('gamma'),
                'vega': c.get('vega'),
                'bid': bid,
                'ask': ask,
                'mid_price': (bid + ask) / 2,
                'spread_pct': round(spread, 2),
                'open_interest': oi,
                'volume': c.get('volume'),
                'implied_volatility': c.get('volatility'),
                'score': round(total_score, 2)
            })
        
        # Sort by score descending
        scored_contracts.sort(key=lambda x: x['score'], reverse=True)
        return scored_contracts
    
    def _get_next_trading_day(self, start_date: date, offset: int = 0) -> date:
        """
        Get next trading day (skip weekends).
        
        Args:
            start_date: Starting date
            offset: Days ahead (0 = today if trading day, 1 = next trading day)
        
        Returns:
            Next trading day
        """
        current = start_date + timedelta(days=offset)
        
        # Skip weekends
        while current.weekday() >= 5:  # 5=Saturday, 6=Sunday
            current += timedelta(days=1)
        
        return current
    
    def _create_skip_response(self, reason: str, time_remaining: float) -> Dict:
        """Create response for skipped signal."""
        return {
            'dte': None,
            'expiry_date': None,
            'recommended_strikes': [],
            'reasoning': f"🚫 SKIP SIGNAL: {reason}",
            'data_factors': {},
            'time_remaining_hours': round(time_remaining, 2),
            'score': 0,
            'max_score': 0,
            'confidence_pct': 0
        }
    
    def _create_fallback_response(self, reason: str, time_remaining: float) -> Dict:
        """
        Create fallback response using time-based logic.
        
        Updated logic (March 2026):
        - Accounts for realistic 45-60 minute hold times (not aspirational 15-30 min)
        - Factors in EODHD data lag (1-3 minutes)
        - Optimized for choppy market conditions where moves take longer
        - Prioritizes 1DTE liquidity and flexibility for late-day signals
        """
        if time_remaining >= 3.5:
            # Plenty of time for 0DTE intraday scalp
            dte = 0
            dte_text = "0DTE (Expires Today)"
        elif time_remaining >= 1.0:
            # Not enough time for fast 0DTE scalp - use 1DTE for flexibility
            dte = 1
            dte_text = "1DTE (Expires Tomorrow)"
        else:
            # Too close to market close
            return self._create_skip_response(
                "Too close to market close (<1 hour)",
                time_remaining
            )
        
        return {
            'dte': dte,
            'expiry_date': str(self._get_next_trading_day(datetime.now(ET).date(), dte)),
            'recommended_strikes': [],
            'reasoning': f"⚠️ Fallback to time-based: {dte_text}\nReason: {reason}",
            'data_factors': {},
            'time_remaining_hours': round(time_remaining, 2),
            'score': 0,
            'max_score': 0,
            'confidence_pct': 0
        }


# ========================================
# GLOBAL INSTANCE
# ========================================
try:
    dte_selector = OptionsDTESelector()
except ValueError as e:
    print(f"[OPTIONS-DTE] ⚠️  Initialization failed: {e}")
    dte_selector = None


# ========================================
# CONVENIENCE FUNCTION
# ========================================
def get_optimal_dte(ticker: str, 
                   entry_price: float,
                   direction: str,
                   confidence: float) -> Optional[Dict]:
    """Convenience function to get DTE recommendation."""
    if dte_selector is None:
        return None
    
    return dte_selector.calculate_optimal_dte(
        ticker=ticker,
        entry_price=entry_price,
        direction=direction,
        confidence=confidence
    )
