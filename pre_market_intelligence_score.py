"""
Pre-Market Intelligence Score (PMIS)
Multi-factor ranking system for watchlist prioritization
"""

def calculate_pmis(ticker: str, premarket_data: dict) -> float:
    """
    Pre-Market Intelligence Score (0-100)
    Higher = better setup for CFW6 strategy
    """
    score = 0
    
    # Factor 1: Gap Size (0-20 points)
    gap_pct = abs(premarket_data.get("gap_pct", 0))
    if 3 <= gap_pct < 5:
        score += 10
    elif 5 <= gap_pct < 8:
        score += 15
    elif gap_pct >= 8:
        score += 20
    
    # Factor 2: Pre-Market Volume (0-20 points)
    pm_volume = premarket_data.get("pm_volume", 0)
    avg_volume = premarket_data.get("avg_volume", 1)
    rel_volume = pm_volume / avg_volume if avg_volume > 0 else 0
    
    if rel_volume >= 3.0:
        score += 20
    elif rel_volume >= 2.0:
        score += 15
    elif rel_volume >= 1.5:
        score += 10
    
    # Factor 3: Options Liquidity (0-15 points)
    avg_options_volume = premarket_data.get("avg_options_volume", 0)
    if avg_options_volume >= 10000:
        score += 15
    elif avg_options_volume >= 5000:
        score += 10
    elif avg_options_volume >= 1000:
        score += 5
    
    # Factor 4: IV Rank (0-15 points)
    iv_rank = premarket_data.get("iv_rank", 50)
    if 30 <= iv_rank <= 70:  # Sweet spot for premium
        score += 15
    elif 20 <= iv_rank <= 80:
        score += 10
    
    # Factor 5: Catalyst Present (0-15 points)
    has_earnings = premarket_data.get("has_earnings", False)
    has_news = premarket_data.get("has_news", False)
    
    if has_earnings:
        score += 10
    if has_news:
        score += 5
    
    # Factor 6: Previous Day Structure (0-15 points)
    # Check if price is near key levels (PDH, PDL, VWAP)
    near_key_level = premarket_data.get("near_key_level", False)
    if near_key_level:
        score += 15
    
    return min(score, 100)  # Cap at 100


def build_intelligent_watchlist() -> List[Dict]:
    """
    Build scored watchlist with PMIS ranking.
    Returns top 20 highest-scoring tickers.
    """
    # Fetch all pre-market data
    all_tickers = fetch_premarket_universe()  # ~500-1000 tickers
    
    scored_tickers = []
    
    for ticker_data in all_tickers:
        ticker = ticker_data["ticker"]
        
        # Calculate PMIS
        pmis = calculate_pmis(ticker, ticker_data)
        
        # Only consider high scores
        if pmis >= 50:
            scored_tickers.append({
                "ticker": ticker,
                "pmis": pmis,
                "gap_pct": ticker_data.get("gap_pct", 0),
                "pm_volume": ticker_data.get("pm_volume", 0),
                "catalyst": ticker_data.get("catalyst", "None")
            })
    
    # Sort by PMIS (highest first)
    scored_tickers.sort(key=lambda x: x["pmis"], reverse=True)
    
    # Return top 20
    return scored_tickers[:20]
