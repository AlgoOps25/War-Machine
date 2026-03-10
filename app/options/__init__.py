"""
Options Intelligence Module - Smart Options Trade Builder

This module analyzes options chains and builds optimal trade recommendations based on:
1. Confidence score (determines delta/strike aggressiveness)
2. Greeks analysis (IV rank, theta decay, gamma risk)
3. DTE selection (Days To Expiration based on signal strength)
4. Risk/reward calculation
5. Contract quantity sizing

PHASE 1.14: Real EODHD Options Data Integration (UnicornBay API)
- Fetches real Greeks from EODHD UnicornBay marketplace API
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

# Guard OptionsDataManager import so a transient failure doesn't kill the whole module
try:
    from app.options.options_data_manager import OptionsDataManager
    _options_dm = OptionsDataManager()
except Exception as _odm_err:
    import logging as _log
    _log.getLogger(__name__).warning(
        f"[OPTIONS] OptionsDataManager unavailable: {_odm_err} — 0DTE fast-path disabled"
    )
    _options_dm = None

logger = logging.getLogger(__name__)

# EODHD UnicornBay Options API configuration
EODHD_API_KEY = os.getenv('EODHD_API_KEY', '')
EODHD_BASE_URL = 'https://eodhd.com/api/mp/unicornbay'

# Request timeout
REQUEST_TIMEOUT = 30


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

    # ═══════════════════════════════════════════════════════════════════
    # STEP 1: GET CURRENT PRICE
    # ═══════════════════════════════════════════════════════════════════
    if current_price is None:
        current_price = _get_current_price(ticker)
        if current_price is None:
            logger.error(
                f"[OPTIONS] Failed to fetch price for {ticker}",
                extra={'component': 'options', 'symbol': ticker}
            )
            return None

    # ═══════════════════════════════════════════════════════════════════
    # STEP 2: DETERMINE DTE (DAYS TO EXPIRATION)
    # ═══════════════════════════════════════════════════════════════════
    dte = _calculate_optimal_dte(confidence)
    target_date = datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=dte)

    # ═══════════════════════════════════════════════════════════════════
    # STEP 3: SELECT STRIKE (BASED ON CONFIDENCE)
    # ═══════════════════════════════════════════════════════════════════
    target_delta = _confidence_to_delta(confidence)
    strike, greeks, expiration_date = _select_strike_with_greeks(
        ticker=ticker,
        current_price=current_price,
        direction=direction,
        target_delta=target_delta,
        target_date=target_date
    )

    # ═══════════════════════════════════════════════════════════════════
    # STEP 4: GET IV RANK
    # ═══════════════════════════════════════════════════════════════════
    iv_rank = _get_iv_rank(ticker)

    # ═══════════════════════════════════════════════════════════════════
    # STEP 5: GET OPTION PRICE
    # ═══════════════════════════════════════════════════════════════════
    option_price = greeks.get('price', 5.00)  # Use price from options chain

    # ═══════════════════════════════════════════════════════════════════
    # STEP 6: CALCULATE QUANTITY (RISK-BASED POSITION SIZING)
    # ═══════════════════════════════════════════════════════════════════
    max_risk = account_balance * risk_per_trade
    quantity = _calculate_quantity(option_price, max_risk)

    # ═══════════════════════════════════════════════════════════════════
    # STEP 7: BUILD CONTRACT SYMBOL (OCC FORMAT)
    # ═══════════════════════════════════════════════════════════════════
    contract_symbol = _build_contract_symbol(ticker, expiration_date, direction, strike)

    # ═══════════════════════════════════════════════════════════════════
    # STEP 8: CALCULATE RISK/REWARD
    # ═══════════════════════════════════════════════════════════════════
    risk_reward = f"1:{2.5}"  # Placeholder - calculate based on targets

    # Calculate actual DTE from selected expiration
    actual_dte = (datetime.strptime(expiration_date, '%Y-%m-%d').date() -
                  datetime.now(ZoneInfo("America/New_York")).date()).days

    trade = {
        'ticker': ticker,
        'direction': direction,
        'strike': strike,
        'expiration': expiration_date,
        'dte': actual_dte,
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

def build_0dte_trade(
    ticker: str,
    direction: str,
    confidence: float,
    current_price: float = None,
    account_balance: float = 5000.0,
    risk_per_trade: float = 0.02
) -> dict:
    """
    Build optimized 0DTE options trade using high-performance data manager.

    Key differences from regular build_options_trade:
    - Uses parallel Greeks fetching (faster)
    - Tighter delta ranges for 0DTE (max gamma exposure)
    - Stricter liquidity filters (volume + OI requirements)
    - 60-second caching to avoid redundant API calls

    Args:
        ticker: Stock symbol
        direction: "CALL" or "PUT"
        confidence: Signal confidence (0-100)
        current_price: Current stock price
        account_balance: Trading account balance
        risk_per_trade: Risk percentage per trade

    Returns:
        dict: Optimized 0DTE trade recommendation
    """
    logger.info(
        f"[OPTIONS] Building 0DTE {direction} for {ticker} (confidence={confidence:.1f}%)",
        extra={'component': 'options', 'symbol': ticker, 'direction': direction}
    )

    # Get current price if not provided
    if current_price is None:
        current_price = _get_current_price(ticker)
        if current_price is None:
            logger.error(f"[OPTIONS] Failed to fetch price for {ticker}")
            return None

    # If data manager failed to load, fall back to regular build
    if _options_dm is None:
        logger.warning(f"[OPTIONS] OptionsDataManager not available, falling back to standard build")
        return build_options_trade(
            ticker=ticker,
            direction=direction,
            confidence=confidence,
            current_price=current_price,
            account_balance=account_balance,
            risk_per_trade=risk_per_trade
        )

    # Use optimized data manager for 0DTE
    contract = _options_dm.get_optimized_chain(
        ticker=ticker,
        direction=direction,
        target_dte=0,  # 0DTE
        for_0dte=True,
        confidence=confidence
    )

    if not contract:
        logger.warning(f"[OPTIONS] No suitable 0DTE contract for {ticker}")
        # Fallback to regular build
        return build_options_trade(
            ticker=ticker,
            direction=direction,
            confidence=confidence,
            current_price=current_price,
            account_balance=account_balance,
            risk_per_trade=risk_per_trade
        )

    # Extract contract details
    strike = contract['strike']
    expiration = contract['expiration']
    option_price = contract['price']
    greeks = {
        'delta': contract['delta'],
        'gamma': contract['gamma'],
        'theta': contract['theta'],
        'vega': contract['vega'],
        'iv': contract['iv'],
        'price': option_price,
        'bid': contract['bid'],
        'ask': contract['ask'],
        'volume': contract['volume'],
        'open_interest': contract['open_interest']
    }

    # Calculate quantity
    max_risk = account_balance * risk_per_trade
    quantity = _calculate_quantity(option_price, max_risk)

    # Build contract symbol
    exp_date = datetime.strptime(expiration, '%Y-%m-%d')
    contract_symbol = _build_contract_symbol(ticker, expiration, direction, strike)

    # Get IV Rank
    iv_rank = _get_iv_rank(ticker)

    # Calculate DTE
    dte = (exp_date.date() - datetime.now(ZoneInfo("America/New_York")).date()).days

    trade = {
        'ticker': ticker,
        'direction': direction,
        'strike': strike,
        'expiration': expiration,
        'dte': dte,
        'contract': contract_symbol,
        'price': option_price,
        'greeks': greeks,
        'iv_rank': iv_rank,
        'risk_reward': f"1:{2.5}",
        'quantity': quantity,
        'total_cost': option_price * quantity * 100,
        'max_risk': max_risk,
        'confidence': confidence,
        'strategy': contract.get('strategy', 'balanced'),
        'is_0dte': True
    }

    logger.info(
        f"[OPTIONS] 0DTE trade built: {contract_symbol} x{quantity} @ ${option_price:.2f} "
        f"(delta={greeks['delta']:.2f}, vol={greeks['volume']}, OI={greeks['open_interest']})",
        extra={'component': 'options', 'symbol': ticker, 'trade': trade}
    )

    return trade

def get_greeks(ticker: str, strike: float = None, expiration: str = None, direction: str = "CALL") -> dict:
    """
    Fetch Greeks for an option contract from EODHD UnicornBay API.

    Returns:
        dict: {'delta': 0.55, 'gamma': 0.03, 'theta': -0.12, 'vega': 0.25, 'iv': 45, 'price': 12.50}
    """
    if not EODHD_API_KEY:
        logger.warning("[OPTIONS] EODHD_API_KEY not set - using placeholder Greeks")
        return _get_placeholder_greeks()

    try:
        # Fetch specific contracts from UnicornBay API with filters
        url = f"{EODHD_BASE_URL}/options/contracts"
        params = {
            'filter[underlying_symbol]': ticker,
            'filter[type]': direction.lower(),
            'filter[strike]': strike,
            'filter[exp_date]': expiration,
            'page[size]': 10,  # Should only return 1 contract
            'api_token': EODHD_API_KEY
        }

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if not data or 'data' not in data:
            logger.warning(f"[OPTIONS] No options data for {ticker}")
            return _get_placeholder_greeks()

        contracts = data['data']
        if not contracts:
            logger.warning(f"[OPTIONS] No contracts found for {ticker} ${strike} {direction} {expiration}")
            return _get_placeholder_greeks()

        # Should only be one matching contract
        attrs = contracts[0].get('attributes', {})

        bid = attrs.get('bid', 0)
        ask = attrs.get('ask', 0)
        midpoint = attrs.get('midpoint', (bid + ask) / 2 if (bid and ask) else attrs.get('last', 5.0))

        return {
            'delta': attrs.get('delta', 0.5),
            'gamma': attrs.get('gamma', 0.03),
            'theta': attrs.get('theta', -0.10),
            'vega': attrs.get('vega', 0.20),
            'iv': attrs.get('volatility', 0.40) * 100,  # Convert decimal to percentage
            'price': midpoint,
            'bid': bid,
            'ask': ask,
            'volume': attrs.get('volume', 0),
            'open_interest': attrs.get('open_interest', 0)
        }

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"[OPTIONS] No options data available for {ticker} (404)")
        elif e.response.status_code == 401:
            logger.error(f"[OPTIONS] API authentication failed (401) - check EODHD_API_KEY")
        elif e.response.status_code == 400:
            logger.warning(f"[OPTIONS] Bad request (400) - filters may not be supported")
        else:
            logger.error(f"[OPTIONS] HTTP error fetching Greeks: {e}")
        return _get_placeholder_greeks()
    except requests.exceptions.Timeout:
        logger.warning(f"[OPTIONS] API timeout for {ticker}")
        return _get_placeholder_greeks()
    except Exception as e:
        logger.error(f"[OPTIONS] Failed to fetch Greeks: {e}")
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
    """Get current stock price from data manager or API."""
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
        return 30  # 4 weeks


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
    target_date: datetime
) -> tuple:
    """
    Select strike price based on target delta using real options chain from UnicornBay API.

    Returns:
        tuple: (strike, greeks_dict, expiration_date)
    """
    if not EODHD_API_KEY:
        strike, greeks = _fallback_strike_selection(current_price, direction, target_delta)
        exp_date = _calculate_fallback_expiration((target_date - datetime.now(ZoneInfo("America/New_York")).date()).days)
        return strike, greeks, exp_date

    try:
        # Calculate target DTE range
        target_dte = (target_date - datetime.now(ZoneInfo("America/New_York")).date()).days
        min_dte = max(1, target_dte - 7)  # Look 7 days before target
        max_dte = target_dte + 7  # Look 7 days after target

        # Fetch options contracts from UnicornBay API with filters
        url = f"{EODHD_BASE_URL}/options/contracts"
        params = {
            'filter[underlying_symbol]': ticker,
            'filter[type]': direction.lower(),  # Filter by call/put in API
            'filter[dte_gte]': min_dte,  # Min DTE
            'filter[dte_lte]': max_dte,  # Max DTE
            'page[size]': 100,  # Limit results
            'api_token': EODHD_API_KEY
        }

        logger.info(f"[OPTIONS] Fetching {direction.lower()} contracts for {ticker} (DTE {min_dte}-{max_dte})")

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if not data or 'data' not in data:
            logger.warning(f"[OPTIONS] No options data returned for {ticker}")
            strike, greeks = _fallback_strike_selection(current_price, direction, target_delta)
            exp_date = _calculate_fallback_expiration(target_dte)
            return strike, greeks, exp_date

        contracts = data['data']
        if not contracts:
            logger.warning(f"[OPTIONS] No contracts found for {ticker}")
            strike, greeks = _fallback_strike_selection(current_price, direction, target_delta)
            exp_date = _calculate_fallback_expiration(target_dte)
            return strike, greeks, exp_date

        logger.info(f"[OPTIONS] Received {len(contracts)} contracts")

        # Group by expiration date
        from collections import defaultdict
        by_expiration = defaultdict(list)

        for contract in contracts:
            attrs = contract.get('attributes', {})
            exp_date_str = attrs.get('exp_date')

            if not exp_date_str:
                continue

            try:
                exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
                dte = (exp_date - datetime.now(ZoneInfo("America/New_York")).date()).days

                # Only consider valid contracts
                if dte > 0:
                    by_expiration[exp_date].append({
                        'attrs': attrs,
                        'dte': dte
                    })
            except Exception:
                continue

        if not by_expiration:
            logger.warning(f"[OPTIONS] No valid expirations found")
            strike, greeks = _fallback_strike_selection(current_price, direction, target_delta)
            exp_date = _calculate_fallback_expiration(target_dte)
            return strike, greeks, exp_date

        # Find expiration closest to target date
        closest_exp = min(by_expiration.keys(),
                         key=lambda d: abs((d - datetime.now(ZoneInfo("America/New_York")).date()).days - target_dte))

        logger.info(f"[OPTIONS] Selected expiration {closest_exp} (target DTE: {target_dte}, actual: {(closest_exp - datetime.now(ZoneInfo('America/New_York')).date()).days})")

        # From contracts with closest expiration, find best delta match
        candidates = by_expiration[closest_exp]
        best_contract = None
        min_delta_diff = float('inf')

        for item in candidates:
            attrs = item['attrs']
            contract_delta = abs(attrs.get('delta', 0))  # Use absolute for puts
            delta_diff = abs(contract_delta - target_delta)

            # Also prefer contracts with reasonable liquidity
            open_interest = attrs.get('open_interest', 0)
            volume = attrs.get('volume', 0)

            # Penalty for low liquidity (but don't exclude completely)
            liquidity_penalty = 0
            if open_interest < 10:
                liquidity_penalty = 0.05

            adjusted_diff = delta_diff + liquidity_penalty

            if adjusted_diff < min_delta_diff:
                min_delta_diff = adjusted_diff
                best_contract = item

        if best_contract:
            attrs = best_contract['attrs']
            strike = attrs.get('strike', current_price)
            bid = attrs.get('bid', 0)
            ask = attrs.get('ask', 0)
            midpoint = attrs.get('midpoint', (bid + ask) / 2 if (bid and ask) else attrs.get('last', 5.0))

            greeks = {
                'delta': attrs.get('delta', target_delta),
                'gamma': attrs.get('gamma', 0.03),
                'theta': attrs.get('theta', -0.10),
                'vega': attrs.get('vega', 0.20),
                'iv': attrs.get('volatility', 0.40) * 100,  # Convert decimal to percentage
                'price': midpoint,
                'bid': bid,
                'ask': ask,
                'volume': attrs.get('volume', 0),
                'open_interest': attrs.get('open_interest', 0)
            }

            expiration_str = closest_exp.strftime('%Y-%m-%d')
            logger.info(
                f"[OPTIONS] Selected ${strike} {direction} exp {expiration_str} "
                f"(delta={greeks['delta']:.2f}, target={target_delta:.2f}, "
                f"OI={greeks['open_interest']}, vol={greeks['volume']})"
            )
            return strike, greeks, expiration_str

        logger.warning(f"[OPTIONS] No suitable contract found")
        strike, greeks = _fallback_strike_selection(current_price, direction, target_delta)
        exp_date = _calculate_fallback_expiration(target_dte)
        return strike, greeks, exp_date

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"[OPTIONS] No options chain for {ticker} (404)")
        elif e.response.status_code == 401:
            logger.error(f"[OPTIONS] API authentication failed (401)")
        elif e.response.status_code == 400:
            logger.warning(f"[OPTIONS] Bad request (400) - filters may not be supported, falling back")
        else:
            logger.error(f"[OPTIONS] HTTP error: {e}")
        strike, greeks = _fallback_strike_selection(current_price, direction, target_delta)
        exp_date = _calculate_fallback_expiration(target_dte)
        return strike, greeks, exp_date
    except requests.exceptions.Timeout:
        logger.warning(f"[OPTIONS] API timeout - using fallback")
        strike, greeks = _fallback_strike_selection(current_price, direction, target_delta)
        exp_date = _calculate_fallback_expiration(target_dte)
        return strike, greeks, exp_date
    except Exception as e:
        logger.error(f"[OPTIONS] Failed to fetch options chain: {e}")
        import traceback
        logger.error(traceback.format_exc())
        strike, greeks = _fallback_strike_selection(current_price, direction, target_delta)
        exp_date = _calculate_fallback_expiration(target_dte)
        return strike, greeks, exp_date



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

# Export both functions
__all__ = ['build_options_trade', 'build_0dte_trade', 'get_greeks']
