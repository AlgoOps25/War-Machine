"""
Position Sizing & Risk Management
Kelly Criterion + Fixed Fractional
"""

ACCOUNT_SIZE = 5000
MAX_RISK_PER_TRADE_PCT = 0.02  # 2% = $100 max risk per trade
MAX_CONTRACTS = 1  # Your constraint

def calculate_position_size(
    entry_price: float,
    stop_price: float,
    confidence: float,
    contract_multiplier: int = 100
) -> Dict:
    """
    Calculate optimal position size.
    
    Returns:
    {
        "contracts": int,
        "risk_dollars": float,
        "risk_pct": float,
        "kelly_fraction": float
    }
    """
    # Risk per share
    risk_per_share = abs(entry_price - stop_price)
    
    # Max risk allowed
    max_risk_dollars = ACCOUNT_SIZE * MAX_RISK_PER_TRADE_PCT
    
    # Kelly Criterion (simplified)
    # Kelly = (Win% × Avg Win) - (Loss% × Avg Loss) / Avg Win
    # Using confidence as proxy for win rate
    win_rate = confidence
    avg_rr = 2.0  # CFW6 targets 2R minimum
    
    kelly_fraction = (win_rate * avg_rr - (1 - win_rate)) / avg_rr
    kelly_fraction = max(0.01, min(kelly_fraction, 0.25))  # Cap at 25%
    
    # Calculate contracts
    kelly_risk = ACCOUNT_SIZE * kelly_fraction
    suggested_risk = min(kelly_risk, max_risk_dollars)
    
    # Options: 1 contract = 100 shares
    risk_per_contract = risk_per_share * contract_multiplier
    suggested_contracts = int(suggested_risk / risk_per_contract)
    
    # Apply hard limit
    final_contracts = min(suggested_contracts, MAX_CONTRACTS)
    final_risk = final_contracts * risk_per_contract
    
    return {
        "contracts": final_contracts,
        "risk_dollars": round(final_risk, 2),
        "risk_pct": round((final_risk / ACCOUNT_SIZE) * 100, 2),
        "kelly_fraction": round(kelly_fraction, 4),
        "premium_per_contract": entry_price,
        "max_loss": round(final_risk, 2)
    }
