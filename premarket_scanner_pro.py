"""
Professional Pre-Market Scanner
Based on Finviz Elite, Trade Ideas, and institutional scanning logic.

3-Tier Detection System:
  Tier 1: Volume Spike Detection (RVOL, absolute volume, dollar volume)
  Tier 2: Gap + Momentum Quality (ATR-normalized gaps, volume confirmation)
  Tier 3: Liquidity + Float Analysis (tradability, institutional interest)

Key Metrics:
  - Relative Volume (RVOL): Current volume vs. 10-day average
  - Dollar Volume: Normalizes volume across price ranges
  - ATR-Normalized Gap: Gap size relative to typical volatility
  - Float: Outstanding shares available for trading
  - Market Cap: Institutional interest threshold

Professional Criteria (Trade Ideas, Finviz Elite standards):
  - RVOL > 1.5x (minimum), 3.0x+ ideal
  - Pre-market volume > 100K shares by 9:00 AM
  - Gap > 1% (minimum), 3%+ ideal
  - ATR > $0.50 (minimum volatility)
  - Market cap > $500M (institutional interest)
  - Price: $5-$500 (liquid range)
  - ADV > 500K shares (daily liquidity)
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import statistics

# Import existing modules
try:
    from ws_feed import get_current_bar
    from data_manager import data_manager
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

import requests
import config


# ══════════════════════════════════════════════════════════════════════════════
# TIER 1: VOLUME SPIKE DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def calculate_relative_volume(
    current_volume: int,
    avg_daily_volume: int,
    time_elapsed_pct: float = 0.25  # 25% of day (pre-market)
) -> float:
    """
    Calculate RVOL (Relative Volume) - Professional standard metric.
    
    Formula: (Current Volume / Expected Volume at this time)
    Expected Volume = Avg Daily Volume × Time Elapsed %
    
    Example: If 9:00 AM (25% of trading day), and stock normally does 1M volume/day:
      Expected volume = 1M × 0.25 = 250K
      If current volume = 500K, RVOL = 500K / 250K = 2.0x
    
    Professional thresholds:
      RVOL > 1.5x = Notable
      RVOL > 2.0x = Strong
      RVOL > 3.0x = Exceptional (institutional activity)
    """
    if avg_daily_volume == 0:
        return 0.0
    
    expected_volume = avg_daily_volume * time_elapsed_pct
    
    if expected_volume == 0:
        return 0.0
    
    return current_volume / expected_volume


def calculate_dollar_volume(price: float, volume: int) -> float:
    """
    Dollar volume normalizes across price ranges.
    $1 stock with 1M volume = $1M dollar volume
    $100 stock with 10K volume = $1M dollar volume
    
    Professional minimum: $5M+ dollar volume for liquidity
    """
    return price * volume


def score_volume_quality(
    current_volume: int,
    avg_daily_volume: int,
    price: float,
    time_pct: float = 0.25
) -> Tuple[float, Dict]:
    """
    Score volume quality using professional metrics.
    
    Returns:
        (score: 0-100, metrics: dict)
    """
    rvol = calculate_relative_volume(current_volume, avg_daily_volume, time_pct)
    dollar_vol = calculate_dollar_volume(price, current_volume)
    
    # Volume score based on RVOL (primary metric)
    if rvol >= 5.0:
        rvol_score = 100  # Extreme institutional activity
    elif rvol >= 3.0:
        rvol_score = 90   # Strong institutional
    elif rvol >= 2.0:
        rvol_score = 75   # Above average
    elif rvol >= 1.5:
        rvol_score = 60   # Notable
    elif rvol >= 1.0:
        rvol_score = 40   # Normal
    else:
        rvol_score = 20   # Below average
    
    # Dollar volume confirmation
    if dollar_vol >= 10_000_000:
        dollar_score = 100
    elif dollar_vol >= 5_000_000:
        dollar_score = 80
    elif dollar_vol >= 2_000_000:
        dollar_score = 60
    elif dollar_vol >= 1_000_000:
        dollar_score = 40
    else:
        dollar_score = 20
    
    # Absolute volume gate
    if current_volume < 50_000:
        volume_gate = 0  # Too low, reject
    elif current_volume < 100_000:
        volume_gate = 50
    else:
        volume_gate = 100
    
    # Weighted composite
    score = (
        rvol_score * 0.50 +      # RVOL is most important
        dollar_score * 0.30 +     # Dollar volume confirms
        volume_gate * 0.20        # Absolute minimum gate
    )
    
    metrics = {
        'rvol': round(rvol, 2),
        'dollar_volume': int(dollar_vol),
        'current_volume': current_volume,
        'rvol_score': rvol_score,
        'dollar_score': dollar_score
    }
    
    return (round(score, 2), metrics)


# ══════════════════════════════════════════════════════════════════════════════
# TIER 2: GAP + MOMENTUM QUALITY
# ══════════════════════════════════════════════════════════════════════════════

def calculate_atr_normalized_gap(
    gap_pct: float,
    atr: float,
    prev_close: float
) -> float:
    """
    Normalize gap by ATR (Average True Range) to account for volatility.
    
    A 5% gap on a low-volatility stock (ATR = $0.20) is more significant
    than a 5% gap on a high-volatility stock (ATR = $5.00).
    
    Professional use: Filters out noise, focuses on true breakouts.
    """
    if prev_close == 0 or atr == 0:
        return 0.0
    
    gap_dollar = abs(gap_pct / 100 * prev_close)
    atr_normalized = gap_dollar / atr
    
    return round(atr_normalized, 2)


def score_gap_quality(
    current_price: float,
    prev_close: float,
    atr: float,
    volume: int,
    avg_volume: int
) -> Tuple[float, Dict]:
    """
    Score gap quality using professional criteria.
    
    Factors:
      - Gap size (raw %)
      - ATR-normalized gap (volatility-adjusted)
      - Volume confirmation (is gap supported?)
      - Direction (both up and down are opportunities)
    
    Returns:
        (score: 0-100, metrics: dict)
    """
    if prev_close == 0:
        return (0.0, {})
    
    gap_pct = ((current_price - prev_close) / prev_close) * 100
    gap_abs = abs(gap_pct)
    direction = "up" if gap_pct > 0 else "down"
    
    # ATR-normalized gap (professional standard)
    atr_norm = calculate_atr_normalized_gap(gap_pct, atr, prev_close)
    
    # Gap size score
    if gap_abs >= 5.0:
        gap_score = 100  # Strong gap
    elif gap_abs >= 3.0:
        gap_score = 85   # Good gap
    elif gap_abs >= 2.0:
        gap_score = 70   # Moderate gap
    elif gap_abs >= 1.0:
        gap_score = 50   # Small gap
    else:
        gap_score = 20   # Minimal gap
    
    # ATR-normalized score (filters noise)
    if atr_norm >= 2.0:
        atr_score = 100  # Well above typical range
    elif atr_norm >= 1.5:
        atr_score = 80   # Above typical range
    elif atr_norm >= 1.0:
        atr_score = 60   # At typical range
    elif atr_norm >= 0.5:
        atr_score = 40   # Below typical range
    else:
        atr_score = 20   # Minimal relative to ATR
    
    # Volume confirmation (gap must be supported)
    vol_ratio = volume / avg_volume if avg_volume > 0 else 0
    if vol_ratio >= 2.0:
        vol_confirm = 100  # Strong volume support
    elif vol_ratio >= 1.5:
        vol_confirm = 80   # Good volume support
    elif vol_ratio >= 1.0:
        vol_confirm = 60   # Average volume
    else:
        vol_confirm = 30   # Weak volume (gap may fade)
    
    # Weighted composite
    score = (
        gap_score * 0.40 +        # Raw gap size
        atr_score * 0.35 +        # Volatility-adjusted gap
        vol_confirm * 0.25        # Volume confirmation
    )
    
    metrics = {
        'gap_pct': round(gap_pct, 2),
        'gap_abs': round(gap_abs, 2),
        'atr_normalized': atr_norm,
        'direction': direction,
        'volume_ratio': round(vol_ratio, 2)
    }
    
    return (round(score, 2), metrics)


# ══════════════════════════════════════════════════════════════════════════════
# TIER 3: LIQUIDITY + FLOAT ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def score_liquidity_quality(
    market_cap: float,
    float_shares: Optional[float],
    avg_daily_volume: int,
    price: float,
    bid_ask_spread_pct: Optional[float] = None
) -> Tuple[float, Dict]:
    """
    Score liquidity and tradability - critical for institutional entry/exit.
    
    Factors:
      - Market cap (institutional threshold)
      - Float (lower = higher volatility potential)
      - Average daily volume (liquidity for exits)
      - Bid-ask spread (slippage risk)
      - Price range (sweet spot $5-$500)
    
    Returns:
        (score: 0-100, metrics: dict)
    """
    # Market cap score (institutional interest)
    if market_cap >= 10_000_000_000:  # $10B+
        mcap_score = 100  # Large cap
    elif market_cap >= 2_000_000_000:  # $2B+
        mcap_score = 90   # Mid cap
    elif market_cap >= 500_000_000:    # $500M+
        mcap_score = 75   # Small cap
    elif market_cap >= 100_000_000:    # $100M+
        mcap_score = 50   # Micro cap
    else:
        mcap_score = 20   # Too small
    
    # Float score (lower float = higher volatility potential)
    float_category = "unknown"
    if float_shares:
        float_millions = float_shares / 1_000_000
        if float_millions < 10:
            float_score = 100  # Ultra-low float (high volatility)
            float_category = "ultra_low"
        elif float_millions < 20:
            float_score = 90   # Very low float
            float_category = "very_low"
        elif float_millions < 50:
            float_score = 80   # Low float
            float_category = "low"
        elif float_millions < 100:
            float_score = 70   # Moderate float
            float_category = "moderate"
        else:
            float_score = 60   # High float (more stable)
            float_category = "high"
    else:
        float_score = 60  # Unknown, assume moderate
    
    # Average daily volume score (liquidity for exits)
    if avg_daily_volume >= 5_000_000:
        adv_score = 100  # Highly liquid
    elif avg_daily_volume >= 2_000_000:
        adv_score = 90   # Very liquid
    elif avg_daily_volume >= 1_000_000:
        adv_score = 80   # Liquid
    elif avg_daily_volume >= 500_000:
        adv_score = 60   # Moderate liquidity
    else:
        adv_score = 30   # Low liquidity
    
    # Price range score (sweet spot for options and day trading)
    if 10 <= price <= 200:
        price_score = 100  # Ideal range
    elif 5 <= price < 10 or 200 < price <= 500:
        price_score = 80   # Acceptable range
    elif price < 5:
        price_score = 30   # Penny stock risk
    else:
        price_score = 60   # High-priced (less volatile %)
    
    # Bid-ask spread score (if available)
    if bid_ask_spread_pct is not None:
        if bid_ask_spread_pct <= 0.1:
            spread_score = 100  # Tight spread
        elif bid_ask_spread_pct <= 0.3:
            spread_score = 80   # Good spread
        elif bid_ask_spread_pct <= 0.5:
            spread_score = 60   # Acceptable spread
        else:
            spread_score = 30   # Wide spread (slippage risk)
    else:
        spread_score = 70  # Unknown, assume moderate
    
    # Weighted composite
    score = (
        mcap_score * 0.25 +       # Market cap threshold
        float_score * 0.20 +      # Float (volatility potential)
        adv_score * 0.30 +        # Daily volume (liquidity)
        price_score * 0.15 +      # Price range
        spread_score * 0.10       # Bid-ask spread
    )
    
    metrics = {
        'market_cap': market_cap,
        'float_millions': float_shares / 1_000_000 if float_shares else None,
        'float_category': float_category,
        'avg_daily_volume': avg_daily_volume,
        'price': price,
        'mcap_score': mcap_score,
        'adv_score': adv_score
    }
    
    return (round(score, 2), metrics)


# ══════════════════════════════════════════════════════════════════════════════
# COMPOSITE PROFESSIONAL SCORE
# ══════════════════════════════════════════════════════════════════════════════

def calculate_professional_score(
    ticker: str,
    current_price: float,
    prev_close: float,
    current_volume: int,
    avg_daily_volume: int,
    market_cap: float,
    atr: float,
    float_shares: Optional[float] = None,
    time_pct: float = 0.25
) -> Dict:
    """
    Calculate comprehensive professional pre-market score.
    
    Returns dict with:
      - composite_score: 0-100 (overall quality)
      - tier_scores: {volume, gap, liquidity}
      - tier_metrics: detailed breakdown
      - pass_threshold: bool (meets professional standards)
    """
    # Tier 1: Volume Spike Detection
    volume_score, volume_metrics = score_volume_quality(
        current_volume, avg_daily_volume, current_price, time_pct
    )
    
    # Tier 2: Gap + Momentum Quality
    gap_score, gap_metrics = score_gap_quality(
        current_price, prev_close, atr, current_volume, avg_daily_volume
    )
    
    # Tier 3: Liquidity + Float Analysis
    liquidity_score, liquidity_metrics = score_liquidity_quality(
        market_cap, float_shares, avg_daily_volume, current_price
    )
    
    # Professional weighted composite
    # Volume is KING in pre-market (institutional activity indicator)
    composite_score = (
        volume_score * 0.45 +      # Volume spike (most important)
        gap_score * 0.35 +         # Gap quality (momentum)
        liquidity_score * 0.20     # Liquidity (tradability)
    )
    
    # Professional threshold gates
    # Must meet ALL minimum criteria to pass
    pass_volume = volume_metrics['rvol'] >= 1.5  # Minimum RVOL
    pass_gap = gap_metrics['gap_abs'] >= 1.0      # Minimum 1% gap
    pass_liquidity = avg_daily_volume >= 500_000  # Minimum daily volume
    pass_threshold = pass_volume and pass_gap and pass_liquidity
    
    return {
        'ticker': ticker,
        'composite_score': round(composite_score, 2),
        'tier_scores': {
            'volume': volume_score,
            'gap': gap_score,
            'liquidity': liquidity_score
        },
        'tier_metrics': {
            'volume': volume_metrics,
            'gap': gap_metrics,
            'liquidity': liquidity_metrics
        },
        'pass_threshold': pass_threshold,
        'timestamp': datetime.now().isoformat()
    }


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_premarket_time_percentage() -> float:
    """
    Calculate what % of trading day has elapsed (for RVOL calculation).
    
    Regular market: 9:30 AM - 4:00 PM (6.5 hours)
    Pre-market: 4:00 AM - 9:30 AM (5.5 hours)
    
    At 9:00 AM: ~25% of expected daily volume should be done
    """
    now = datetime.now().time()
    
    # Market hours: 9:30 AM - 4:00 PM
    market_open = datetime.now().replace(hour=9, minute=30, second=0)
    market_close = datetime.now().replace(hour=16, minute=0, second=0)
    total_market_minutes = (market_close - market_open).total_seconds() / 60  # 390 minutes
    
    # Pre-market elapsed
    premarket_start = datetime.now().replace(hour=4, minute=0, second=0)
    current_time = datetime.now()
    
    if current_time < market_open:
        # Still in pre-market
        premarket_elapsed = (current_time - premarket_start).total_seconds() / 60
        # Estimate % of daily volume based on time
        # Rough heuristic: pre-market volume is ~10-15% of daily volume
        # Spread across 5.5 hours = ~2% per hour
        pct = (premarket_elapsed / total_market_minutes) * 0.5  # Conservative estimate
        return min(pct, 0.25)  # Cap at 25%
    else:
        # Market is open
        market_elapsed = (current_time - market_open).total_seconds() / 60
        return market_elapsed / total_market_minutes


def print_professional_summary(results: List[Dict], top_n: int = 15):
    """Print formatted pre-market scan results (professional layout)."""
    if not results:
        print("\n⚠️  No tickers passed professional screening criteria\n")
        return
    
    print("\n" + "=" * 100)
    print(f"PRE-MARKET PROFESSIONAL SCAN - {datetime.now().strftime('%H:%M:%S ET')}")
    print("=" * 100)
    print(f"{'Rank':<6}{'Ticker':<8}{'Score':<8}{'RVOL':<8}{'Gap%':<9}{'ATR-N':<8}{'Vol':<10}{'MCap':<8}")
    print("-" * 100)
    
    for i, result in enumerate(results[:top_n], 1):
        ticker = result['ticker']
        score = result['composite_score']
        rvol = result['tier_metrics']['volume']['rvol']
        gap_pct = result['tier_metrics']['gap']['gap_pct']
        atr_norm = result['tier_metrics']['gap']['atr_normalized']
        volume = result['tier_metrics']['volume']['current_volume']
        mcap = result['tier_metrics']['liquidity']['market_cap']
        
        # Format market cap
        if mcap >= 1_000_000_000:
            mcap_str = f"${mcap/1_000_000_000:.1f}B"
        else:
            mcap_str = f"${mcap/1_000_000:.0f}M"
        
        print(
            f"{i:<6}"
            f"{ticker:<8}"
            f"{score:<8.1f}"
            f"{rvol:<8.2f}"
            f"{gap_pct:>+7.2f}%  "
            f"{atr_norm:<8.2f}"
            f"{volume:>8,}  "
            f"{mcap_str:<8}"
        )
    
    print("=" * 100)
    print(f"Legend: RVOL=Relative Volume | ATR-N=ATR-Normalized Gap | MCap=Market Cap")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    # Test professional scoring
    print("Testing Professional Pre-Market Scanner...\n")
    
    # Example: Strong pre-market setup
    test_result = calculate_professional_score(
        ticker="NVDA",
        current_price=152.50,
        prev_close=150.00,
        current_volume=500_000,
        avg_daily_volume=2_000_000,
        market_cap=3_750_000_000_000,
        atr=3.50,
        float_shares=24_500_000_000,
        time_pct=0.25
    )
    
    print(f"Ticker: {test_result['ticker']}")
    print(f"Composite Score: {test_result['composite_score']}")
    print(f"Pass Threshold: {test_result['pass_threshold']}")
    print(f"\nTier Scores:")
    print(f"  Volume: {test_result['tier_scores']['volume']}")
    print(f"  Gap: {test_result['tier_scores']['gap']}")
    print(f"  Liquidity: {test_result['tier_scores']['liquidity']}")
    print(f"\nVolume Metrics:")
    print(f"  RVOL: {test_result['tier_metrics']['volume']['rvol']}x")
    print(f"  Dollar Volume: ${test_result['tier_metrics']['volume']['dollar_volume']:,}")
    print(f"\nGap Metrics:")
    print(f"  Gap %: {test_result['tier_metrics']['gap']['gap_pct']}%")
    print(f"  ATR-Normalized: {test_result['tier_metrics']['gap']['atr_normalized']}")
    print(f"  Direction: {test_result['tier_metrics']['gap']['direction']}")
