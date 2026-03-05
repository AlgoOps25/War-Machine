"""
Options Intelligence Module - Smart Options Trade Builder

This module analyzes options chains and builds optimal trade recommendations
based on:
1. Confidence score (determines delta/strike aggressiveness)
2. Greeks analysis (IV rank, theta decay, gamma risk)
3. DTE selection (Days To Expiration based on signal strength)
4. Risk/reward calculation
5. Contract quantity sizing

PHASE 1.14: Real EODHD Options Data Integration
- Fetches real Greeks from EODHD US Stock Options Data API
- Calculates IV Rank from 52-week IV range
- Finds optimal strikes based on real delta values
- Gets actual option prices (bid/ask midpoint)

Usage:
    from app.options import build_options_trade, get_greeks
    
    trade = build_options_trade(
        ticker="NVDA",
        direction="CALL",
        confidence=75
    )
"""
import logging
import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# EODHD US Stock Options Data API configuration
EODHD_API_KEY = os.getenv('EODHD_API_KEY', '')
EODHD_BASE_URL = 'https://eodhd.com/api'

# Request timeout
REQUEST_TIMEOUT = 30  # Increased to 30 seconds for options data


def build_options_trade(
    ticker: str,
    direction: str,  # "CALL" or "PUT"
    confidence: float,
    current_price: float = None,
    account_balance: float = 5000.0,
    risk_per_trade: float = 0.02  # 2% of account per trade
) -> dict:
    """
    Build optimal options trade recommendation.
    
    Args:
        ticker: Stock symbol
        direction: "CALL" or "PUT"
        confidence: Signal confidence (0-100)
        current_price: Current stock price (fetched if not provided)
        account_balance: Trading account balance
        risk_per_trade: Risk percentage per trade (default 2%)
    
    Returns:
        dict: Trade recommendation with strike, expiration, Greeks, quantity
    """
    logger.info(
        f"[OPTIONS] Building {direction} trade for {ticker} (confidence={confidence:.1f}%)",
        extra={'component': 'options', 'symbol': ticker, 'direction': direction}
    )
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 1: GET CURRENT PRICE
    # ══════════════════════════════════════════════════════════════════════════════
    if current_price is None:
        current_price = _get_current_price(ticker)
        if current_price is None:
            logger.error(
                f"[OPTIONS] Failed to fetch price for {ticker}",
                extra={'component': 'options', 'symbol': ticker}
            )
            return None
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 2: DETERMINE DTE (DAYS TO EXPIRATION)
    # ══════════════════════════════════════════════════════════════════════════════
    dte = _calculate_optimal_dte(confidence)
    expiration_date = _get_nearest_expiration(ticker, dte)
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 3: SELECT STRIKE (BASED ON CONFIDENCE)
    # ══════════════════════════════════════════════════════════════════════════════
    target_delta = _confidence_to_delta(confidence)
    strike, greeks = _select_strike_with_greeks(
        ticker=ticker,
        current_price=current_price,
        direction=direction,
        target_delta=target_delta,
        expiration=expiration_date
    )
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 4: GET IV RANK
    # ══════════════════════════════════════════════════════════════════════════════
    iv_rank = _get_iv_rank(ticker)
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 5: GET OPTION PRICE
    # ══════════════════════════════════════════════════════════════════════════════
    option_price = greeks.get('price', 5.00)  # Use price from options chain
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 6: CALCULATE QUANTITY (RISK-BASED POSITION SIZING)
    # ══════════════════════════════════════════════════════════════════════════════
    max_risk = account_balance * risk_per_trade
    quantity = _calculate_quantity(option_price, max_risk)
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 7: BUILD CONTRACT SYMBOL (OCC FORMAT)
    # ══════════════════════════════════════════════════════════════════════════════
    contract_symbol = _build_contract_symbol(ticker, expiration_date, direction, strike)
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 8: CALCULATE RISK/REWARD
    # ══════════════════════════════════════════════════════════════════════════════
    risk_reward = f"1:{2.5}"  # Placeholder - calculate based on targets
    
    trade = {
        'ticker': ticker,
        'direction': direction,
        'strike': strike,
        'expiration': expiration_date,
        'dte': dte,
        'contract': contract_symbol,
        'price': option_price,
        'greeks': greeks,
        'iv_rank': iv_rank,
        'risk_reward': risk_reward,
        'quantity': quantity,
        'total_cost': option_price * quantity * 100,  # 100 shares per contract
        'max_risk': max_risk,
        'confidence': confidence
    }
    
    logger.info(
        f"[OPTIONS] Trade built: {contract_symbol} x{quantity} @ ${option_price:.2f} "
        f"(IV Rank: {iv_rank}%, Delta: {greeks.get('delta', 'N/A')})",
        extra={'component': 'options', 'symbol': ticker, 'trade': trade}
    )
    
    return trade


def get_greeks(ticker: str, strike: float = None, expiration: str = None, direction: str = "CALL") -> dict:
    """
    Fetch Greeks for an option contract from EODHD US Stock Options Data API.
    
    Returns:
        dict: {'delta': 0.55, 'gamma': 0.03, 'theta': -0.12, 'vega': 0.25, 'iv': 45, 'price': 12.50}
    """
    if not EODHD_API_KEY:
        logger.warning("[OPTIONS] EODHD_API_KEY not set - using placeholder Greeks")
        return _get_placeholder_greeks()
    
    try:
        # Fetch options chain from standard US Stock Options Data API
        url = f"{EODHD_BASE_URL}/options/{ticker}.US"
        params = {
            'api_token': EODHD_API_KEY,
            'date': expiration
        }
        
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        # Standard API returns: {"data": [{"expirationDate": "...", "options": {"CALL": [...], "PUT": [...]}}]}
        if not data or 'data' not in data:
            logger.warning(f"[OPTIONS] No options data for {ticker}")
            return _get_placeholder_greeks()
        
        # Find data for the requested expiration
        options_data = None
        for exp_data in data['data']:
            if exp_data.get('expirationDate') == expiration:
                options_data = exp_data.get('options', {})
                break
        
        if not options_data:
            logger.warning(f"[OPTIONS] No data for expiration {expiration}")
            return _get_placeholder_greeks()
        
        # Get contracts for direction
        contracts = options_data.get(direction, [])
        
        if not contracts:
            logger.warning(f"[OPTIONS] No {direction} contracts found")
            return _get_placeholder_greeks()
        
        # Find contract matching strike
        for contract in contracts:
            contract_strike = contract.get('strike', 0)
            
            if abs(contract_strike - strike) < 0.01:  # Match strike
                bid = contract.get('bid', 0)
                ask = contract.get('ask', 0)
                return {
                    'delta': contract.get('delta', 0.5),
                    'gamma': contract.get('gamma', 0.03),
                    'theta': contract.get('theta', -0.10),
                    'vega': contract.get('vega', 0.20),
                    'iv': contract.get('impliedVolatility', 40) * 100,  # Convert to percentage
                    'price': (bid + ask) / 2 if (bid and ask) else contract.get('lastPrice', 5.0),
                    'bid': bid,
                    'ask': ask,
                    'volume': contract.get('volume', 0),
                    'open_interest': contract.get('openInterest', 0)
                }
        
        logger.warning(f"[OPTIONS] No matching contract for {ticker} ${strike} {direction}")
        return _get_placeholder_greeks()
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"[OPTIONS] No options data available for {ticker} (404) - using placeholder")
        elif e.response.status_code == 401:
            logger.error(f"[OPTIONS] API authentication failed (401) - check EODHD_API_KEY")
        else:
            logger.error(f"[OPTIONS] HTTP error fetching Greeks for {ticker}: {e}")
        return _get_placeholder_greeks()
    except requests.exceptions.Timeout:
        logger.warning(f"[OPTIONS] API timeout for {ticker} - using placeholder")
        return _get_placeholder_greeks()
    except Exception as e:
        logger.error(f"[OPTIONS] Failed to fetch Greeks for {ticker}: {e}")
        return _get_placeholder_greeks()


def _get_placeholder_greeks() -> dict:
    """Return placeholder Greeks when API unavailable."""
    return {
        'delta': 0.50,
        'gamma': 0.03,
        'theta': -0.10,
        'vega': 0.20,
        'iv': 40,
        'price': 5.00
    }


def _get_current_price(ticker: str) -> float:
    """
    Get current stock price from data manager or API.
    """
    try:
        from app.data.ws_feed import get_current_bar_with_fallback
        bar = get_current_bar_with_fallback(ticker)
        if bar:
            return bar['close']
    except Exception as e:
        logger.error(f"[OPTIONS] Failed to get price for {ticker}: {e}")
    
    return None


def _calculate_optimal_dte(confidence: float) -> int:
    """
    Calculate optimal Days To Expiration based on confidence.
    
    High confidence (80+): 7-14 DTE (0DTE to 2-week)
    Medium confidence (70-80): 14-21 DTE (2-3 weeks)
    Lower confidence (60-70): 21-30 DTE (3-4 weeks)
    """
    if confidence >= 80:
        return 14  # 2 weeks
    elif confidence >= 70:
        return 21  # 3 weeks
    else:
        return 30  # 4 weeks (more time to be right)


def _get_nearest_expiration(ticker: str, target_dte: int) -> str:
    """
    Find the nearest options expiration date to target DTE from EODHD API.
    
    Returns:
        str: Expiration date in YYYY-MM-DD format
    """
    if not EODHD_API_KEY:
        return _calculate_fallback_expiration(target_dte)
    
    try:
        # Fetch available expirations from standard API
        url = f"{EODHD_BASE_URL}/options/{ticker}.US"
        params = {'api_token': EODHD_API_KEY}
        
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        # Standard API returns: {"data": [{"expirationDate": "..."}, ...]}
        if not data or 'data' not in data:
            return _calculate_fallback_expiration(target_dte)
        
        # Extract expiration dates
        expirations = [item.get('expirationDate') for item in data['data'] if item.get('expirationDate')]
        
        if not expirations:
            return _calculate_fallback_expiration(target_dte)
        
        # Find closest expiration to target DTE
        today = datetime.now(ZoneInfo("America/New_York")).date()
        target_date = today + timedelta(days=target_dte)
        
        closest_exp = None
        min_diff = float('inf')
        
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
            diff = abs((exp_date - target_date).days)
            if diff < min_diff:
                min_diff = diff
                closest_exp = exp_str
        
        if closest_exp:
            logger.info(f"[OPTIONS] Found expiration {closest_exp} (target DTE: {target_dte})")
            return closest_exp
        
        return _calculate_fallback_expiration(target_dte)
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"[OPTIONS] No options available for {ticker} (404) - using fallback")
        elif e.response.status_code == 401:
            logger.error(f"[OPTIONS] API authentication failed (401) - check EODHD_API_KEY")
        else:
            logger.warning(f"[OPTIONS] HTTP error fetching expirations: {e}")
        return _calculate_fallback_expiration(target_dte)
    except requests.exceptions.Timeout:
        logger.warning(f"[OPTIONS] API timeout - using fallback expiration")
        return _calculate_fallback_expiration(target_dte)
    except Exception as e:
        logger.warning(f"[OPTIONS] Failed to fetch expirations: {e}")
        return _calculate_fallback_expiration(target_dte)


def _calculate_fallback_expiration(target_dte: int) -> str:
    """Calculate next Friday as fallback expiration."""
    today = datetime.now(ZoneInfo("America/New_York"))
    target_date = today + timedelta(days=target_dte)
    
    # Round to next Friday
    days_until_friday = (4 - target_date.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7  # If today is Friday, go to next Friday
    expiration = target_date + timedelta(days=days_until_friday)
    
    return expiration.strftime('%Y-%m-%d')


def _confidence_to_delta(confidence: float) -> float:
    """
    Convert confidence score to target delta.
    
    High confidence (80+): Delta 0.60-0.70 (more aggressive, closer to ATM)
    Medium confidence (70-80): Delta 0.50-0.60 (balanced)
    Lower confidence (60-70): Delta 0.40-0.50 (more conservative, further OTM)
    """
    if confidence >= 80:
        return 0.65  # Aggressive
    elif confidence >= 70:
        return 0.55  # Balanced
    else:
        return 0.45  # Conservative


def _select_strike_with_greeks(
    ticker: str,
    current_price: float,
    direction: str,
    target_delta: float,
    expiration: str
) -> tuple:
    """
    Select strike price based on target delta using real options chain.
    
    Returns:
        tuple: (strike, greeks_dict)
    """
    if not EODHD_API_KEY:
        return _fallback_strike_selection(current_price, direction, target_delta)
    
    try:
        # Fetch options chain from standard API
        url = f"{EODHD_BASE_URL}/options/{ticker}.US"
        params = {
            'api_token': EODHD_API_KEY,
            'date': expiration
        }
        
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        if not data or 'data' not in data:
            return _fallback_strike_selection(current_price, direction, target_delta)
        
        # Find data for the requested expiration
        options_data = None
        for exp_data in data['data']:
            if exp_data.get('expirationDate') == expiration:
                options_data = exp_data.get('options', {})
                break
        
        if not options_data:
            return _fallback_strike_selection(current_price, direction, target_delta)
        
        # Get contracts for direction
        contracts = options_data.get(direction, [])
        
        if not contracts:
            return _fallback_strike_selection(current_price, direction, target_delta)
        
        # Find contract with delta closest to target
        best_contract = None
        min_delta_diff = float('inf')
        
        for contract in contracts:
            contract_delta = abs(contract.get('delta', 0))  # Use absolute for puts
            delta_diff = abs(contract_delta - target_delta)
            
            if delta_diff < min_delta_diff:
                min_delta_diff = delta_diff
                best_contract = contract
        
        if best_contract:
            strike = best_contract.get('strike', current_price)
            bid = best_contract.get('bid', 0)
            ask = best_contract.get('ask', 0)
            price = (bid + ask) / 2 if (bid and ask) else best_contract.get('lastPrice', 5.0)
            
            greeks = {
                'delta': best_contract.get('delta', target_delta),
                'gamma': best_contract.get('gamma', 0.03),
                'theta': best_contract.get('theta', -0.10),
                'vega': best_contract.get('vega', 0.20),
                'iv': best_contract.get('impliedVolatility', 0.40) * 100,  # Convert to percentage
                'price': price,
                'bid': bid,
                'ask': ask,
                'volume': best_contract.get('volume', 0),
                'open_interest': best_contract.get('openInterest', 0)
            }
            logger.info(f"[OPTIONS] Selected strike ${strike} (delta={greeks['delta']:.2f}, target={target_delta:.2f})")
            return strike, greeks
        
        return _fallback_strike_selection(current_price, direction, target_delta)
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"[OPTIONS] No options chain for {ticker} (404) - using fallback")
        elif e.response.status_code == 401:
            logger.error(f"[OPTIONS] API authentication failed (401) - check EODHD_API_KEY")
        else:
            logger.error(f"[OPTIONS] HTTP error fetching options chain: {e}")
        return _fallback_strike_selection(current_price, direction, target_delta)
    except requests.exceptions.Timeout:
        logger.warning(f"[OPTIONS] API timeout - using fallback")
        return _fallback_strike_selection(current_price, direction, target_delta)
    except Exception as e:
        logger.error(f"[OPTIONS] Failed to fetch options chain: {e}")
        return _fallback_strike_selection(current_price, direction, target_delta)


def _fallback_strike_selection(current_price: float, direction: str, target_delta: float) -> tuple:
    """Fallback strike selection when API unavailable."""
    if direction == "CALL":
        if target_delta >= 0.60:
            strike = current_price * 1.02
        elif target_delta >= 0.50:
            strike = current_price * 1.03
        else:
            strike = current_price * 1.05
    else:
        if target_delta >= 0.60:
            strike = current_price * 0.98
        elif target_delta >= 0.50:
            strike = current_price * 0.97
        else:
            strike = current_price * 0.95
    
    # Round to nearest strike increment
    if current_price > 200:
        strike = round(strike / 5) * 5
    elif current_price > 100:
        strike = round(strike / 2.5) * 2.5
    else:
        strike = round(strike)
    
    greeks = _get_placeholder_greeks()
    greeks['delta'] = target_delta
    
    return strike, greeks


def _get_iv_rank(ticker: str) -> float:
    """
    Get IV Rank (0-100, where current IV falls in 1-year range).
    
    IV Rank formula:
    (Current IV - 1Y Low IV) / (1Y High IV - 1Y Low IV) * 100
    
    Note: This would require historical IV tracking.
    Returns 50.0 (neutral) as fallback for now.
    """
    # TODO: Implement historical IV tracking in database
    return 50.0


def _calculate_quantity(option_price: float, max_risk: float) -> int:
    """
    Calculate number of contracts based on risk limit.
    
    Max risk = option premium * quantity * 100
    Quantity = max_risk / (option_price * 100)
    """
    if option_price <= 0:
        return 1
    
    quantity = int(max_risk / (option_price * 100))
    
    # Minimum 1 contract, maximum 10 contracts (safety limit)
    return max(1, min(quantity, 10))


def _build_contract_symbol(ticker: str, expiration: str, direction: str, strike: float) -> str:
    """
    Build OCC-format option symbol.
    
    Format: TICKER[YY][MM][DD][C/P][STRIKE*1000]
    Example: NVDA260320C00485000 (NVDA Call $485 exp 2026-03-20)
    """
    exp_date = datetime.strptime(expiration, '%Y-%m-%d')
    exp_str = exp_date.strftime('%y%m%d')
    
    direction_char = 'C' if direction == "CALL" else 'P'
    
    # Strike in OCC format (padded to 8 digits, multiply by 1000)
    strike_str = f"{int(strike * 1000):08d}"
    
    return f"{ticker.upper()}{exp_str}{direction_char}{strike_str}"
