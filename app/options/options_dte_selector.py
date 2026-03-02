"""
Options DTE Selector - Data-Driven Expiration Selection

Responsibilities:
  - Fetch options chain from EODHD for 0DTE and 1DTE contracts
  - Query historical trade outcomes via DTEHistoricalAdvisor
  - Analyze liquidity (open interest, volume)
  - Assess theta decay rates
  - Check bid/ask spreads
  - Compare implied volatility levels
  - Evaluate market regime context (ADX, VIX, target distance)
  - Score and recommend optimal DTE using composite model
  - Provide strike recommendations with Greeks analysis

DTE Selection Scoring Model (0-10 points):
  1. Historical Performance (0-4 pts, 40% weight)
     - Win rates from actual trades under similar conditions
     - Confidence-weighted by sample size
  
  2. Live Options Quality (0-3.5 pts, 35% weight)
     - Liquidity: OI > 100, Volume > 50 (1.0 pt)
     - Theta: Acceptable decay for time remaining (1.0 pt)
     - Spreads: < 10% bid/ask spread (0.75 pt)
     - IV: Not inflated vs 1DTE (0.5 pt)
     - Volume: > 25 contracts today (0.25 pt)
  
  3. Market Regime Context (0-2.5 pts, 25% weight)
     - ADX bucket appropriate for DTE (1.0 pt)
     - VIX bucket favorable (0.75 pt)
     - Target distance realistic for timeframe (0.75 pt)

  Threshold: 6.0 points (60%) required for 0DTE
  Below threshold: Use 1DTE for safer time buffer
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import requests
import os

# Import historical advisor
try:
    from app.options.dte_historical_advisor import dte_historical_advisor
    HISTORICAL_ADVISOR_AVAILABLE = dte_historical_advisor is not None
except ImportError:
    print("[OPTIONS-DTE] ⚠️  DTEHistoricalAdvisor not available")
    dte_historical_advisor = None
    HISTORICAL_ADVISOR_AVAILABLE = False

ET = ZoneInfo("America/New_York")


class OptionsDTESelector:
    """Intelligent DTE selection using historical outcomes + live market data."""
    
    def __init__(self, eodhd_api_key: Optional[str] = None):
        """
        Initialize with EODHD API credentials.
        
        Args:
            eodhd_api_key: EODHD API key (defaults to EODHD_API_KEY env var)
        """
        self.api_key = eodhd_api_key or os.getenv('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError("EODHD_API_KEY not provided or found in environment")
        
        # Live options quality thresholds
        self.min_open_interest = 100
        self.min_volume = 50
        self.min_total_volume = 25
        self.max_spread_pct = 10.0
        self.max_iv_premium_pct = 20.0
        
        # Scoring weights
        self.weight_historical = 0.40  # 40% weight to historical win rates
        self.weight_live_options = 0.35  # 35% weight to live options quality
        self.weight_regime = 0.25  # 25% weight to market regime context
        
        # Decision threshold
        self.dte_0_threshold = 6.0  # Need 6/10 points for 0DTE
        
        print("[OPTIONS-DTE] Selector initialized with historical learning + EODHD integration")
    
    def calculate_optimal_dte(self, 
                             ticker: str, 
                             entry_price: float,
                             direction: str,
                             confidence: float,
                             adx: float,
                             vix: float,
                             t1_price: float,
                             t2_price: Optional[float] = None,
                             grade: str = 'A',
                             current_time: Optional[datetime] = None) -> Dict:
        """
        Calculate optimal DTE using composite scoring model.
        
        Args:
            ticker: Stock ticker symbol
            entry_price: Expected entry price
            direction: 'bull' or 'bear'
            confidence: Signal confidence (0-1)
            adx: Current ADX value (trend strength)
            vix: Current VIX level (market volatility)
            t1_price: Target 1 price
            t2_price: Target 2 price (optional)
            grade: Signal grade ('A+', 'A', 'A-')
            current_time: Current time (defaults to now ET)
        
        Returns:
            Dict with DTE recommendation, strikes, and detailed scoring breakdown
        """
        if current_time is None:
            current_time = datetime.now(ET)
        
        # Calculate time remaining and context
        market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        time_remaining_hours = (market_close - current_time).total_seconds() / 3600
        hour_of_day = current_time.hour
        
        # Calculate target distance
        target_pct = abs((t1_price - entry_price) / entry_price * 100)
        
        # Early exit if market closed or too late
        if time_remaining_hours <= 0:
            return self._create_skip_response(
                "Market closed - no options trading",
                time_remaining_hours
            )
        
        if time_remaining_hours < 0.5:
            return self._create_skip_response(
                "Too close to market close (<30 min remaining)",
                time_remaining_hours
            )
        
        # Fetch historical recommendation
        historical_rec = None
        if HISTORICAL_ADVISOR_AVAILABLE:
            try:
                historical_rec = dte_historical_advisor.get_recommendation(
                    hour_of_day=hour_of_day,
                    adx=adx,
                    vix=vix,
                    target_pct=target_pct,
                    grade=grade,
                    direction=direction
                )
            except Exception as e:
                print(f"[OPTIONS-DTE] Historical advisor error: {e}")
                historical_rec = None
        
        # Fetch live options data from EODHD
        try:
            options_data = self.fetch_options_chain(ticker, entry_price, direction)
            if not options_data:
                return self._create_no_data_response(
                    "No options data available from EODHD",
                    time_remaining_hours,
                    historical_rec
                )
        except Exception as e:
            print(f"[OPTIONS-DTE] Error fetching options: {e}")
            return self._create_no_data_response(
                f"API error: {str(e)}",
                time_remaining_hours,
                historical_rec
            )
        
        # Separate 0DTE and 1DTE contracts
        dte_0_contracts = [opt for opt in options_data if opt['dte'] == 0]
        dte_1_contracts = [opt for opt in options_data if opt['dte'] == 1]
        
        if not dte_0_contracts and not dte_1_contracts:
            return self._create_no_data_response(
                "No 0DTE or 1DTE contracts found",
                time_remaining_hours,
                historical_rec
            )
        
        # Calculate composite score
        score_breakdown = self._calculate_composite_score(
            dte_0_contracts=dte_0_contracts,
            dte_1_contracts=dte_1_contracts,
            time_remaining_hours=time_remaining_hours,
            historical_rec=historical_rec,
            adx=adx,
            vix=vix,
            target_pct=target_pct
        )
        
        total_score = score_breakdown['total_score']
        max_score = 10.0
        
        # Make DTE decision
        if dte_0_contracts and total_score >= self.dte_0_threshold:
            selected_dte = 0
            selected_contracts = dte_0_contracts
            decision_reason = "Score exceeds 0DTE threshold"
        elif dte_1_contracts:
            selected_dte = 1
            selected_contracts = dte_1_contracts
            decision_reason = "Score below 0DTE threshold, using 1DTE for safety"
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
            # Fallback to other DTE if no quality strikes
            if selected_dte == 0 and dte_1_contracts:
                selected_dte = 1
                selected_contracts = dte_1_contracts
                best_strikes = self.select_best_strikes(selected_contracts, entry_price, direction)
                decision_reason = "No quality 0DTE strikes, falling back to 1DTE"
            
            if not best_strikes:
                return self._create_skip_response(
                    f"No quality strikes found for {selected_dte}DTE",
                    time_remaining_hours
                )
        
        # Build detailed reasoning
        reasoning = self._format_reasoning(
            selected_dte=selected_dte,
            score_breakdown=score_breakdown,
            decision_reason=decision_reason
        )
        
        # Build response
        return {
            'dte': selected_dte,
            'expiry_date': best_strikes[0]['exp_date'],
            'recommended_strikes': best_strikes[:2],  # Top 2 strikes
            'reasoning': reasoning,
            'score_breakdown': score_breakdown,
            'time_remaining_hours': round(time_remaining_hours, 2),
            'total_score': round(total_score, 2),
            'max_score': max_score,
            'confidence_pct': round((total_score / max_score) * 100, 1),
            'context': {
                'hour_of_day': hour_of_day,
                'adx': round(adx, 2),
                'vix': round(vix, 2),
                'target_pct': round(target_pct, 2),
                'grade': grade,
                'direction': direction
            }
        }
    
    def _calculate_composite_score(
        self,
        dte_0_contracts: List[Dict],
        dte_1_contracts: List[Dict],
        time_remaining_hours: float,
        historical_rec: Optional[Dict],
        adx: float,
        vix: float,
        target_pct: float
    ) -> Dict:
        """
        Calculate composite score using historical + live + regime factors.
        
        Returns dict with score breakdown and reasoning.
        """
        breakdown = {
            'historical_score': 0.0,
            'historical_max': 4.0,
            'historical_reasoning': '',
            
            'live_options_score': 0.0,
            'live_options_max': 3.5,
            'live_options_factors': {},
            
            'regime_score': 0.0,
            'regime_max': 2.5,
            'regime_factors': {},
            
            'total_score': 0.0
        }
        
        # 1. Historical Performance Score (0-4 points)
        if historical_rec and historical_rec.get('confidence', 0) > 0:
            hist_confidence = historical_rec['confidence']
            recommended_dte = historical_rec.get('recommended_dte')
            
            if recommended_dte == 0:
                # Historical data supports 0DTE
                breakdown['historical_score'] = 4.0 * hist_confidence
                breakdown['historical_reasoning'] = (
                    f"Historical: {historical_rec['win_rate_0dte']:.1f}% win rate for 0DTE "
                    f"vs {historical_rec['win_rate_1dte']:.1f}% for 1DTE "
                    f"({historical_rec['sample_size_0dte']} + {historical_rec['sample_size_1dte']} samples)"
                )
            elif recommended_dte == 1:
                # Historical data favors 1DTE - penalize 0DTE score
                breakdown['historical_score'] = 1.0 * (1 - hist_confidence)
                breakdown['historical_reasoning'] = (
                    f"Historical: {historical_rec['win_rate_1dte']:.1f}% win rate for 1DTE "
                    f"vs {historical_rec['win_rate_0dte']:.1f}% for 0DTE - favors 1DTE"
                )
        else:
            breakdown['historical_reasoning'] = "Insufficient historical data (using live + regime only)"
        
        # 2. Live Options Quality Score (0-3.5 points)
        live_factors = self._analyze_live_options_quality(
            dte_0_contracts,
            dte_1_contracts,
            time_remaining_hours
        )
        breakdown['live_options_factors'] = live_factors
        
        live_score = 0.0
        if live_factors['liquid']: live_score += 1.0
        if live_factors['theta_ok']: live_score += 1.0
        if live_factors['spreads_tight']: live_score += 0.75
        if live_factors['iv_fair']: live_score += 0.5
        if live_factors['volume_active']: live_score += 0.25
        
        breakdown['live_options_score'] = live_score
        
        # 3. Market Regime Context Score (0-2.5 points)
        regime_factors = self._analyze_regime_context(
            adx=adx,
            vix=vix,
            target_pct=target_pct,
            time_remaining_hours=time_remaining_hours
        )
        breakdown['regime_factors'] = regime_factors
        
        regime_score = 0.0
        if regime_factors['adx_favorable']: regime_score += 1.0
        if regime_factors['vix_favorable']: regime_score += 0.75
        if regime_factors['target_realistic']: regime_score += 0.75
        
        breakdown['regime_score'] = regime_score
        
        # Calculate total
        breakdown['total_score'] = (
            breakdown['historical_score'] +
            breakdown['live_options_score'] +
            breakdown['regime_score']
        )
        
        return breakdown
    
    def _analyze_live_options_quality(self,
                                      dte_0_contracts: List[Dict],
                                      dte_1_contracts: List[Dict],
                                      time_remaining_hours: float) -> Dict:
        """Analyze live options chain quality for 0DTE."""
        return {
            'liquid': self._check_liquidity(dte_0_contracts),
            'theta_ok': self._check_theta_decay(dte_0_contracts, time_remaining_hours),
            'spreads_tight': self._check_bid_ask_spread(dte_0_contracts),
            'iv_fair': self._check_iv_levels(dte_0_contracts, dte_1_contracts),
            'volume_active': self._check_volume(dte_0_contracts)
        }
    
    def _analyze_regime_context(self,
                                adx: float,
                                vix: float,
                                target_pct: float,
                                time_remaining_hours: float) -> Dict:
        """Analyze market regime context for DTE appropriateness."""
        # ADX assessment (0DTE favors strong trends)
        if adx >= 25:
            adx_favorable = True
            adx_reason = f"Strong trend (ADX {adx:.1f}) supports quick 0DTE moves"
        elif adx >= 15:
            adx_favorable = time_remaining_hours >= 2.0
            adx_reason = f"Moderate trend (ADX {adx:.1f}) - need >2hrs for 0DTE"
        else:
            adx_favorable = time_remaining_hours >= 3.0
            adx_reason = f"Choppy (ADX {adx:.1f}) - need >3hrs for 0DTE safety"
        
        # VIX assessment (High VIX = larger swings, favor 1DTE for buffer)
        if vix >= 25:
            vix_favorable = False
            vix_reason = f"High VIX ({vix:.1f}) - volatile, prefer 1DTE buffer"
        elif vix >= 15:
            vix_favorable = True
            vix_reason = f"Normal VIX ({vix:.1f}) - 0DTE acceptable"
        else:
            vix_favorable = True
            vix_reason = f"Low VIX ({vix:.1f}) - calm market, 0DTE favorable"
        
        # Target distance vs time remaining
        # Rule: Need ~60 min per 0.5% move in choppy conditions
        estimated_time_needed = target_pct * 2 * 60  # Minutes
        time_available = time_remaining_hours * 60  # Minutes
        time_buffer = time_available / estimated_time_needed if estimated_time_needed > 0 else 10
        
        target_realistic = time_buffer >= 1.2  # Need 20% time buffer
        target_reason = f"Target {target_pct:.2f}% needs ~{estimated_time_needed:.0f}min, have {time_available:.0f}min (buffer: {time_buffer:.1f}x)"
        
        return {
            'adx_favorable': adx_favorable,
            'adx_reason': adx_reason,
            'vix_favorable': vix_favorable,
            'vix_reason': vix_reason,
            'target_realistic': target_realistic,
            'target_reason': target_reason
        }
    
    def _format_reasoning(self,
                         selected_dte: int,
                         score_breakdown: Dict,
                         decision_reason: str) -> str:
        """Format detailed reasoning for DTE selection."""
        lines = []
        
        # Header
        dte_label = "0DTE (Expires Today)" if selected_dte == 0 else "1DTE (Expires Tomorrow)"
        lines.append(f"{'✅' if selected_dte == 0 else '📅'} SELECTED: {dte_label}")
        lines.append(f"Reason: {decision_reason}")
        lines.append("")
        
        # Score breakdown
        lines.append("📊 Score Breakdown:")
        lines.append(f"  Total: {score_breakdown['total_score']:.1f}/10.0 (Threshold: {self.dte_0_threshold})")
        lines.append("")
        
        # Historical
        lines.append(f"  1️⃣ Historical ({score_breakdown['historical_score']:.1f}/{score_breakdown['historical_max']} pts):")
        lines.append(f"     {score_breakdown['historical_reasoning']}")
        lines.append("")
        
        # Live options
        lines.append(f"  2️⃣ Live Options Quality ({score_breakdown['live_options_score']:.1f}/{score_breakdown['live_options_max']} pts):")
        live = score_breakdown['live_options_factors']
        lines.append(f"     {'✅' if live['liquid'] else '❌'} Liquidity (OI/Volume)")
        lines.append(f"     {'✅' if live['theta_ok'] else '❌'} Theta Decay")
        lines.append(f"     {'✅' if live['spreads_tight'] else '❌'} Bid/Ask Spreads")
        lines.append(f"     {'✅' if live['iv_fair'] else '❌'} IV Not Inflated")
        lines.append(f"     {'✅' if live['volume_active'] else '❌'} Volume Active")
        lines.append("")
        
        # Regime
        lines.append(f"  3️⃣ Market Regime ({score_breakdown['regime_score']:.1f}/{score_breakdown['regime_max']} pts):")
        regime = score_breakdown['regime_factors']
        lines.append(f"     {'✅' if regime['adx_favorable'] else '❌'} {regime['adx_reason']}")
        lines.append(f"     {'✅' if regime['vix_favorable'] else '❌'} {regime['vix_reason']}")
        lines.append(f"     {'✅' if regime['target_realistic'] else '❌'} {regime['target_reason']}")
        
        return "\n".join(lines)
    
    # ========================================
    # Live Options Chain Analysis (Unchanged)
    # ========================================
    
    def fetch_options_chain(self, 
                           ticker: str, 
                           price: float, 
                           direction: str) -> List[Dict]:
        """Fetch options chain from EODHD for 0DTE and 1DTE expiries."""
        today = datetime.now(ET).date()
        
        dte_0_date = self._get_next_trading_day(today, offset=0)
        dte_1_date = self._get_next_trading_day(today, offset=1)
        
        option_type = "call" if direction == "bull" else "put"
        
        strike_low = int(price * 0.95)
        strike_high = int(price * 1.05)
        
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
        
        print(f"[OPTIONS-DTE] Fetched {len(contracts)} contracts for {ticker} (0DTE/1DTE {option_type}s)")
        return contracts
    
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
            return True
        elif time_remaining_hours >= 2:
            return avg_theta < 0.15
        else:
            return avg_theta < 0.08
    
    def _check_bid_ask_spread(self, contracts: List[Dict]) -> bool:
        """Check if bid/ask spreads are tight enough."""
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
        """Compare IV between 0DTE and 1DTE."""
        if not dte_0_contracts or not dte_1_contracts:
            return True
        
        avg_iv_0 = sum(c.get('volatility', 0) for c in dte_0_contracts) / len(dte_0_contracts)
        avg_iv_1 = sum(c.get('volatility', 0) for c in dte_1_contracts) / len(dte_1_contracts)
        
        if avg_iv_1 == 0:
            return True
        
        iv_premium = ((avg_iv_0 - avg_iv_1) / avg_iv_1) * 100
        return iv_premium < self.max_iv_premium_pct
    
    def _check_volume(self, contracts: List[Dict]) -> bool:
        """Verify today's volume is active."""
        if not contracts:
            return False
        total_volume = sum(c.get('volume', 0) for c in contracts)
        return total_volume > self.min_total_volume
    
    def select_best_strikes(self, 
                           contracts: List[Dict],
                           entry_price: float,
                           direction: str) -> List[Dict]:
        """Select best strike recommendations based on Greeks and liquidity."""
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
            'score_breakdown': {},
            'time_remaining_hours': round(time_remaining, 2),
            'total_score': 0,
            'max_score': 0,
            'confidence_pct': 0
        }
    
    def _create_no_data_response(self, reason: str, time_remaining: float, historical_rec: Optional[Dict]) -> Dict:
        """Create response when no live options data, using historical only."""
        if historical_rec and historical_rec.get('confidence', 0) >= 0.6:
            # Trust historical data if confidence is high
            dte = historical_rec['recommended_dte']
            return {
                'dte': dte,
                'expiry_date': str(self._get_next_trading_day(datetime.now(ET).date(), dte)),
                'recommended_strikes': [],
                'reasoning': f"⚠️ No live options data. Using historical recommendation only.\n{historical_rec['reasoning']}",
                'score_breakdown': {},
                'time_remaining_hours': round(time_remaining, 2),
                'total_score': 0,
                'max_score': 0,
                'confidence_pct': round(historical_rec['confidence'] * 100, 1)
            }
        else:
            return self._create_skip_response(
                f"{reason} - Insufficient historical data for fallback",
                time_remaining
            )


# ========================================
# GLOBAL INSTANCE
# ========================================
try:
    dte_selector = OptionsDTESelector()
except ValueError as e:
    print(f"[OPTIONS-DTE] ⚠️  Initialization failed: {e}")
    dte_selector = None


# ========================================
# CONVENIENCE FUNCTION (UPDATED SIGNATURE)
# ========================================
def get_optimal_dte(ticker: str, 
                   entry_price: float,
                   direction: str,
                   confidence: float,
                   adx: float,
                   vix: float,
                   t1_price: float,
                   t2_price: Optional[float] = None,
                   grade: str = 'A') -> Optional[Dict]:
    """Convenience function to get DTE recommendation with full context."""
    if dte_selector is None:
        return None
    
    return dte_selector.calculate_optimal_dte(
        ticker=ticker,
        entry_price=entry_price,
        direction=direction,
        confidence=confidence,
        adx=adx,
        vix=vix,
        t1_price=t1_price,
        t2_price=t2_price,
        grade=grade
    )
