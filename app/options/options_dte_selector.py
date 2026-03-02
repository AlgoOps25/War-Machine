"""
Options DTE Selector - Data-Driven Expiration Selection

THREE-LAYER ARCHITECTURE:

1. PRIMARY FOUNDATION (70% weight): Historical Market Pattern Analysis
   - Analyzes 90 days of EODHD 1-min bars (SPY proxy)
   - Measures time-to-target by context: hour, ADX regime, VIX level
   - Answers: "How long do +0.75% moves typically take at 2:30 PM in choppy/high-VIX conditions?"
   - Recommends 0DTE if >70% of moves complete in <60 min, else 1DTE
   - This is REAL MARKET DATA, not arbitrary thresholds

2. SECONDARY VALIDATION (30% weight): Live Options Market Data
   - Fetches real-time options chain from EODHD
   - Analyzes liquidity, theta decay, bid/ask spreads, IV levels
   - Can override historical recommendation if market conditions extreme
   - Provides strike recommendations with Greeks

3. TERTIARY FEEDBACK LOOP (future): Personal Trade Outcomes
   - Not yet implemented - requires trade history
   - Will validate: "Did my 0DTE selections match my actual hold times?"
   - Calibrates system over time with your specific execution patterns

Usage:
    from options_dte_selector import get_optimal_dte
    
    result = get_optimal_dte(
        ticker='SPY',
        entry_price=520.50,
        direction='BUY',
        confidence=0.82,
        adx=12.5,
        vix=21.3,
        target_pct=0.75
    )
    
    print(f"Recommended DTE: {result['dte']}")
    print(f"Reasoning:\n{result['reasoning']}")
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import requests
import os

# Import historical analyzer
try:
    from app.options.dte_historical_analyzer import get_historical_dte_recommendation
    HISTORICAL_AVAILABLE = True
except ImportError:
    print("[OPTIONS-DTE] ⚠️  Historical analyzer not available, using live-only mode")
    HISTORICAL_AVAILABLE = False
    get_historical_dte_recommendation = None

ET = ZoneInfo("America/New_York")


class OptionsDTESelector:
    """Intelligent DTE selection using historical patterns + live market data."""
    
    def __init__(self, eodhd_api_key: Optional[str] = None):
        """
        Initialize with EODHD API credentials.
        
        Args:
            eodhd_api_key: EODHD API key (defaults to EODHD_API_KEY env var)
        """
        self.api_key = eodhd_api_key or os.getenv('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError("EODHD_API_KEY not provided or found in environment")
        
        # Thresholds for live data validation
        self.min_open_interest = 100
        self.min_volume = 50
        self.min_total_volume = 25
        self.max_spread_pct = 10.0
        self.max_iv_premium_pct = 20.0
        
        # Weighting for combined score
        self.historical_weight = 0.70  # 70% weight to historical patterns
        self.live_weight = 0.30  # 30% weight to live market data
        
        print("[OPTIONS-DTE] Selector initialized with historical + live data integration")
    
    def calculate_optimal_dte(
        self,
        ticker: str,
        entry_price: float,
        direction: str,
        confidence: float,
        adx: Optional[float] = None,
        vix: Optional[float] = None,
        target_pct: Optional[float] = None,
        current_time: Optional[datetime] = None
    ) -> Dict:
        """
        Calculate optimal DTE using historical patterns + live market data.
        
        Args:
            ticker: Stock ticker symbol
            entry_price: Expected entry price
            direction: 'BUY' or 'SELL'
            confidence: Signal confidence (0-100)
            adx: Current ADX value (required for historical analysis)
            vix: Current VIX value (required for historical analysis)
            target_pct: Target profit percentage (e.g., 0.75 for 0.75%)
            current_time: Current time (defaults to now ET)
        
        Returns:
            Dict with DTE recommendation and detailed reasoning
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        # Calculate time remaining
        market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        time_remaining_hours = (market_close - current_time).total_seconds() / 3600
        
        # Early exit if market closed
        if time_remaining_hours <= 0:
            return self._create_skip_response(
                "Market closed - no options trading",
                time_remaining_hours
            )
        
        # Skip if too close to close (< 1 hour)
        if time_remaining_hours < 1.0:
            return self._create_skip_response(
                "Too close to market close (<1 hour remaining)",
                time_remaining_hours
            )
        
        # === LAYER 1: HISTORICAL ANALYSIS (PRIMARY) ===
        historical_rec = None
        if HISTORICAL_AVAILABLE and adx is not None and vix is not None and target_pct is not None:
            try:
                historical_rec = get_historical_dte_recommendation(
                    hour_of_day=current_time.hour,
                    adx=adx,
                    vix=vix,
                    target_pct=target_pct,
                    time_remaining_hours=time_remaining_hours
                )
            except Exception as e:
                print(f"[OPTIONS-DTE] Historical analysis error: {e}")
                historical_rec = None
        
        # === LAYER 2: LIVE OPTIONS DATA (SECONDARY) ===
        live_analysis = None
        try:
            options_data = self.fetch_options_chain(ticker, entry_price, direction)
            if options_data:
                dte_0_contracts = [opt for opt in options_data if opt['dte'] == 0]
                dte_1_contracts = [opt for opt in options_data if opt['dte'] == 1]
                
                if dte_0_contracts or dte_1_contracts:
                    live_analysis = self._analyze_live_options(
                        dte_0_contracts,
                        dte_1_contracts,
                        time_remaining_hours
                    )
        except Exception as e:
            print(f"[OPTIONS-DTE] Live options analysis error: {e}")
            live_analysis = None
        
        # === COMBINE RECOMMENDATIONS ===
        final_decision = self._combine_recommendations(
            historical_rec,
            live_analysis,
            time_remaining_hours
        )
        
        # === SELECT STRIKES (if live data available) ===
        if live_analysis and live_analysis['contracts_available']:
            selected_contracts = (
                live_analysis['dte_0_contracts'] 
                if final_decision['dte'] == 0 
                else live_analysis['dte_1_contracts']
            )
            best_strikes = self.select_best_strikes(
                selected_contracts,
                entry_price,
                direction
            )
        else:
            best_strikes = []
        
        # Build final response
        return {
            'dte': final_decision['dte'],
            'expiry_date': final_decision['expiry_date'],
            'recommended_strikes': best_strikes[:2] if best_strikes else [],
            'reasoning': final_decision['reasoning'],
            'historical_analysis': historical_rec,
            'live_analysis': live_analysis,
            'combined_score': final_decision['combined_score'],
            'confidence_pct': final_decision['confidence_pct'],
            'time_remaining_hours': round(time_remaining_hours, 2)
        }
    
    def _combine_recommendations(
        self,
        historical_rec: Optional[Dict],
        live_analysis: Optional[Dict],
        time_remaining_hours: float
    ) -> Dict:
        """
        Combine historical + live recommendations with weighted scoring.
        
        Scoring:
        - Historical: 0-100 (confidence from pattern analysis)
        - Live: 0-100 (quality score from options data)
        - Combined: (historical * 0.70) + (live * 0.30)
        
        Decision:
        - If combined score for 0DTE >= 70, select 0DTE
        - Else select 1DTE
        - If no data available, fall back to time-only logic
        """
        # Extract scores
        hist_score_0dte = 0
        hist_score_1dte = 0
        
        if historical_rec:
            if historical_rec['recommended_dte'] == 0:
                hist_score_0dte = historical_rec['confidence']
                hist_score_1dte = 100 - historical_rec['confidence']
            elif historical_rec['recommended_dte'] == 1:
                hist_score_1dte = historical_rec['confidence']
                hist_score_0dte = 100 - historical_rec['confidence']
        
        live_score_0dte = 0
        live_score_1dte = 0
        
        if live_analysis:
            live_score_0dte = live_analysis['dte_0_score']
            live_score_1dte = live_analysis['dte_1_score']
        
        # Weighted combination
        if historical_rec or live_analysis:
            combined_0dte = (
                (hist_score_0dte * self.historical_weight) +
                (live_score_0dte * self.live_weight)
            )
            combined_1dte = (
                (hist_score_1dte * self.historical_weight) +
                (live_score_1dte * self.live_weight)
            )
            
            # Decision threshold
            if combined_0dte >= 70:
                selected_dte = 0
                confidence = combined_0dte
            else:
                selected_dte = 1
                confidence = combined_1dte
            
            # Build reasoning
            reasoning_lines = []
            reasoning_lines.append(f"{'✅ SELECTED: 0DTE' if selected_dte == 0 else '📅 SELECTED: 1DTE'}")
            reasoning_lines.append(f"Combined Score: {confidence:.1f}/100\n")
            
            if historical_rec:
                reasoning_lines.append("📊 HISTORICAL ANALYSIS (70% weight):")
                reasoning_lines.append(f"   {historical_rec['reasoning']}")
                reasoning_lines.append(f"   Confidence: {historical_rec['confidence']:.1f}%")
                reasoning_lines.append(f"   Sample Size: {historical_rec['sample_size']} moves")
                if historical_rec.get('p50_hold_time_min'):
                    reasoning_lines.append(f"   Median Hold Time: {historical_rec['p50_hold_time_min']:.0f} min\n")
            
            if live_analysis:
                reasoning_lines.append("💹 LIVE OPTIONS DATA (30% weight):")
                reasoning_lines.append(f"   0DTE Quality: {live_score_0dte:.1f}/100")
                reasoning_lines.append(f"   1DTE Quality: {live_score_1dte:.1f}/100")
                if live_analysis.get('factors'):
                    factors = live_analysis['factors']
                    if selected_dte == 0:
                        if factors.get('dte_0_liquid'): reasoning_lines.append("   ✅ 0DTE liquidity strong")
                        if factors.get('dte_0_theta_acceptable'): reasoning_lines.append("   ✅ 0DTE theta acceptable")
                        if factors.get('dte_0_spread_tight'): reasoning_lines.append("   ✅ 0DTE spreads tight")
            
            reasoning = "\n".join(reasoning_lines)
            
        else:
            # No data - fall back to time-only
            if time_remaining_hours >= 3.5:
                selected_dte = 0
                confidence = 50
                reasoning = f"⚠️  FALLBACK (time-only): 0DTE - {time_remaining_hours:.1f}hrs remaining"
            elif time_remaining_hours >= 1.0:
                selected_dte = 1
                confidence = 50
                reasoning = f"⚠️  FALLBACK (time-only): 1DTE - {time_remaining_hours:.1f}hrs remaining"
            else:
                selected_dte = None
                confidence = 0
                reasoning = "🚫 SKIP: Too close to market close"
        
        # Get expiry date
        if selected_dte is not None:
            expiry_date = str(self._get_next_trading_day(
                datetime.now(ET).date(),
                selected_dte
            ))
        else:
            expiry_date = None
        
        return {
            'dte': selected_dte,
            'expiry_date': expiry_date,
            'combined_score': round(confidence, 1) if selected_dte is not None else 0,
            'confidence_pct': round(confidence, 1) if selected_dte is not None else 0,
            'reasoning': reasoning
        }
    
    def _analyze_live_options(
        self,
        dte_0_contracts: List[Dict],
        dte_1_contracts: List[Dict],
        time_remaining_hours: float
    ) -> Dict:
        """
        Analyze live options data and score 0DTE vs 1DTE quality.
        
        Returns quality scores 0-100 for each DTE.
        """
        factors_0 = self._evaluate_contracts(dte_0_contracts, time_remaining_hours)
        factors_1 = self._evaluate_contracts(dte_1_contracts, time_remaining_hours)
        
        # Calculate scores (0-100)
        score_0 = self._calculate_contract_score(factors_0)
        score_1 = self._calculate_contract_score(factors_1)
        
        return {
            'dte_0_contracts': dte_0_contracts,
            'dte_1_contracts': dte_1_contracts,
            'dte_0_score': score_0,
            'dte_1_score': score_1,
            'factors': {
                'dte_0_liquid': factors_0['liquid'],
                'dte_0_theta_acceptable': factors_0['theta_ok'],
                'dte_0_spread_tight': factors_0['spread_ok'],
                'dte_1_liquid': factors_1['liquid'],
                'dte_1_theta_acceptable': factors_1['theta_ok'],
                'dte_1_spread_tight': factors_1['spread_ok']
            },
            'contracts_available': len(dte_0_contracts) > 0 or len(dte_1_contracts) > 0
        }
    
    def _evaluate_contracts(self, contracts: List[Dict], time_remaining: float) -> Dict:
        """Evaluate contract quality factors."""
        if not contracts:
            return {'liquid': False, 'theta_ok': False, 'spread_ok': False, 'volume_ok': False}
        
        avg_oi = sum(c.get('open_interest', 0) for c in contracts) / len(contracts)
        avg_volume = sum(c.get('volume', 0) for c in contracts) / len(contracts)
        avg_theta = abs(sum(c.get('theta', 0) for c in contracts) / len(contracts))
        
        # Spread check
        tight_spreads = 0
        for c in contracts:
            bid = c.get('bid', 0)
            ask = c.get('ask', 0)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread_pct = ((ask - bid) / mid) * 100
                if spread_pct < self.max_spread_pct:
                    tight_spreads += 1
        
        spread_ok = (tight_spreads / len(contracts)) > 0.7 if contracts else False
        
        return {
            'liquid': avg_oi > self.min_open_interest and avg_volume > self.min_volume,
            'theta_ok': avg_theta < (0.15 if time_remaining >= 2 else 0.08),
            'spread_ok': spread_ok,
            'volume_ok': sum(c.get('volume', 0) for c in contracts) > self.min_total_volume
        }
    
    def _calculate_contract_score(self, factors: Dict) -> float:
        """Convert factors to 0-100 score."""
        score = 0
        if factors['liquid']: score += 30
        if factors['theta_ok']: score += 30
        if factors['spread_ok']: score += 25
        if factors['volume_ok']: score += 15
        return score
    
    def fetch_options_chain(
        self,
        ticker: str,
        price: float,
        direction: str
    ) -> List[Dict]:
        """Fetch options chain from EODHD for 0DTE and 1DTE."""
        today = datetime.now(ET).date()
        dte_0_date = self._get_next_trading_day(today, offset=0)
        dte_1_date = self._get_next_trading_day(today, offset=1)
        
        option_type = "call" if direction == "BUY" else "put"
        strike_low = int(price * 0.95)
        strike_high = int(price * 1.05)
        
        url = f"https://eodhd.com/api/options/{ticker}"
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
            return []
        
        contracts = []
        for contract in data['data']:
            try:
                exp_date = datetime.strptime(contract['expirationDate'], '%Y-%m-%d').date()
                dte = (exp_date - today).days
                
                if dte not in [0, 1]:
                    continue
                
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
            except (KeyError, ValueError):
                continue
        
        return contracts
    
    def select_best_strikes(
        self,
        contracts: List[Dict],
        entry_price: float,
        direction: str
    ) -> List[Dict]:
        """Select best strikes based on Greeks and liquidity."""
        scored_contracts = []
        
        for c in contracts:
            delta = abs(c.get('delta', 0))
            oi = c.get('open_interest', 0)
            bid = c.get('bid', 0)
            ask = c.get('ask', 0)
            
            if bid <= 0 or ask <= 0:
                continue
            
            spread = ((ask - bid) / ((ask + bid) / 2)) * 100
            
            delta_score = 10 if 0.4 <= delta <= 0.6 else (5 if 0.3 <= delta <= 0.7 else 0)
            oi_score = min(oi / 100, 10)
            spread_score = max(10 - spread, 0)
            
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
        
        scored_contracts.sort(key=lambda x: x['score'], reverse=True)
        return scored_contracts
    
    def _get_next_trading_day(self, start_date: date, offset: int = 0) -> date:
        """Get next trading day (skip weekends)."""
        current = start_date + timedelta(days=offset)
        while current.weekday() >= 5:
            current += timedelta(days=1)
        return current
    
    def _create_skip_response(self, reason: str, time_remaining: float) -> Dict:
        """Create response for skipped signal."""
        return {
            'dte': None,
            'expiry_date': None,
            'recommended_strikes': [],
            'reasoning': f"🚫 SKIP SIGNAL: {reason}",
            'historical_analysis': None,
            'live_analysis': None,
            'combined_score': 0,
            'confidence_pct': 0,
            'time_remaining_hours': round(time_remaining, 2)
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
def get_optimal_dte(
    ticker: str,
    entry_price: float,
    direction: str,
    confidence: float,
    adx: Optional[float] = None,
    vix: Optional[float] = None,
    target_pct: Optional[float] = None
) -> Optional[Dict]:
    """Convenience function to get DTE recommendation."""
    if dte_selector is None:
        return None
    
    return dte_selector.calculate_optimal_dte(
        ticker=ticker,
        entry_price=entry_price,
        direction=direction,
        confidence=confidence,
        adx=adx,
        vix=vix,
        target_pct=target_pct
    )
