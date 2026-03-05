"""
Options Intelligence Module - Smart Options Trade Builder

This module analyzes options chains and builds optimal trade recommendations
based on:
1. Confidence score (determines delta/strike aggressiveness)
2. Greeks analysis (IV rank, theta decay, gamma risk)
3. DTE selection (Days To Expiration based on signal strength)
4. Risk/reward calculation
5. Contract quantity sizing

Usage:
    from app.options import build_options_trade, get_greeks
    
    trade = build_options_trade(
        ticker="NVDA",
        direction="CALL",
        confidence=75
    )
    
    # Returns:
    # {
    #     'ticker': 'NVDA',
    #     'direction': 'CALL',
    #     'strike': 485.0,
    #     'expiration': '2026-03-20',
    #     'dte': 15,
    #     'contract': 'NVDA260320C00485000',
    #     'price': 12.50,
    #     'greeks': {...},
    #     'iv_rank': 65,
    #     'risk_reward': '1:2.5',
    #     'quantity': 2
    # }
"""
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Tradier API configuration (free tier available)
TRADIER_API_KEY = os.getenv('TRADIER_API_KEY', '')
TRADIER_BASE_URL = 'https://api.tradier.com/v1'

# Interactive Brokers configuration (if using IB for Greeks)
IB_ENABLED = os.getenv('IB_ENABLED', 'false').lower() == 'true'


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
    strike = _select_strike(
        ticker=ticker,
        current_price=current_price,
        direction=direction,
        target_delta=target_delta,
        expiration=expiration_date
    )
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 4: GET GREEKS AND IV RANK
    # ══════════════════════════════════════════════════════════════════════════════
    greeks = get_greeks(ticker, strike, expiration_date, direction)
    iv_rank = _get_iv_rank(ticker)
    
    # ══════════════════════════════════════════════════════════════════════════════
    # STEP 5: GET OPTION PRICE
    # ══════════════════════════════════════════════════════════════════════════════
    option_price = _get_option_price(ticker, strike, expiration_date, direction)
    
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
    Fetch Greeks for an option contract.
    
    Returns:
        dict: {'delta': 0.55, 'gamma': 0.03, 'theta': -0.12, 'vega': 0.25, 'iv': 45}
    """
    # TODO: Implement Tradier or IB API call
    # For now, return placeholder Greeks
    return {
        'delta': 0.50,
        'gamma': 0.03,
        'theta': -0.10,
        'vega': 0.20,
        'iv': 40,
        'iv_rank': 50
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
    Find the nearest options expiration date to target DTE.
    
    Returns:
        str: Expiration date in YYYY-MM-DD format
    """
    # TODO: Fetch real expirations from API
    # For now, calculate next Friday (standard weekly expiration)
    today = datetime.now(ZoneInfo("America/New_York"))
    days_ahead = target_dte
    target_date = today + timedelta(days=days_ahead)
    
    # Round to next Friday
    days_until_friday = (4 - target_date.weekday()) % 7
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


def _select_strike(
    ticker: str,
    current_price: float,
    direction: str,
    target_delta: float,
    expiration: str
) -> float:
    """
    Select strike price based on target delta.
    
    TODO: Use real options chain data to find strike matching target delta.
    For now, use price-based approximation.
    """
    # Simplified strike selection (needs real options chain)
    if direction == "CALL":
        # For calls, ATM = delta ~0.50, higher strikes = lower delta
        # Delta 0.65: ~2% OTM
        # Delta 0.55: ~3% OTM
        # Delta 0.45: ~5% OTM
        if target_delta >= 0.60:
            strike = current_price * 1.02  # 2% OTM
        elif target_delta >= 0.50:
            strike = current_price * 1.03  # 3% OTM
        else:
            strike = current_price * 1.05  # 5% OTM
    else:  # PUT
        if target_delta >= 0.60:
            strike = current_price * 0.98  # 2% OTM
        elif target_delta >= 0.50:
            strike = current_price * 0.97  # 3% OTM
        else:
            strike = current_price * 0.95  # 5% OTM
    
    # Round to nearest strike increment ($5 for high-priced stocks, $1 otherwise)
    if current_price > 200:
        strike = round(strike / 5) * 5
    elif current_price > 100:
        strike = round(strike / 2.5) * 2.5
    else:
        strike = round(strike)
    
    return strike


def _get_option_price(ticker: str, strike: float, expiration: str, direction: str) -> float:
    """
    Get option price (mid-point of bid/ask).
    
    TODO: Fetch from Tradier or IB API.
    For now, estimate based on intrinsic + time value.
    """
    # Placeholder pricing (needs real options data)
    current_price = _get_current_price(ticker)
    if current_price is None:
        return 5.00  # Default estimate
    
    # Simple intrinsic + time value estimate
    if direction == "CALL":
        intrinsic = max(0, current_price - strike)
    else:
        intrinsic = max(0, strike - current_price)
    
    time_value = 2.50  # Rough estimate (depends on IV and DTE)
    
    return intrinsic + time_value


def _get_iv_rank(ticker: str) -> float:
    """
    Get IV Rank (0-100, where current IV falls in 1-year range).
    
    IV Rank formula:
    (Current IV - 1Y Low IV) / (1Y High IV - 1Y Low IV) * 100
    
    TODO: Fetch real IV data from Tradier/IB.
    """
    # Placeholder - return moderate IV rank
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
