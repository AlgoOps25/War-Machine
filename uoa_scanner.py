"""
Unusual Options Activity (UOA) Scanner

Detects smart money flow through unusual options volume/OI patterns.
Integrates with options_filter.py to boost/penalize signal confidence.

What is UOA?
  Unusual Options Activity occurs when an option's volume significantly exceeds
  its historical average, indicating informed institutional flow ("smart money").
  High volume + high OI + tight spreads = credible directional bet.

UOA Score Formula:
  UOA_Score = (Volume / Avg_Volume) × (OI / Avg_OI) × Spread_Quality
  
  Where:
    - Volume Ratio: Current daily volume vs 20-day average volume
    - OI Ratio: Current OI vs 20-day average OI
    - Spread Quality: Inverse of bid-ask spread % (tighter = better)

Thresholds:
  - Volume > 2.0x average = unusual
  - OI > 1.5x average = institutional interest
  - UOA Score > 3.0 = strong unusual activity
  - UOA Score > 5.0 = extreme unusual activity (smart money)

Alignment Logic:
  Signal Direction | UOA Type      | Multiplier | Label
  -----------------|---------------|------------|-------------------
  Bull (LONG)      | Call UOA      | 1.10       | UOA-ALIGNED-CALL
  Bull (LONG)      | Put UOA       | 0.85       | UOA-OPPOSING-PUT
  Bear (SHORT)     | Put UOA       | 1.10       | UOA-ALIGNED-PUT
  Bear (SHORT)     | Call UOA      | 0.85       | UOA-OPPOSING-CALL
  Any              | No UOA        | 1.00       | UOA-NEUTRAL

Integration:
  Called by options_filter.py after best strike is selected.
  Returns UOA metadata + confidence multiplier.
"""
from typing import Dict, List, Optional, Tuple
import statistics


# UOA detection thresholds
MIN_VOLUME_RATIO = 2.0      # Volume must be 2x+ average to qualify as unusual
MIN_OI_RATIO = 1.5          # OI must be 1.5x+ average for institutional signal
MIN_UOA_SCORE = 3.0         # Minimum score to qualify as "strong UOA"
EXTREME_UOA_SCORE = 5.0     # Score threshold for "extreme UOA" (smart money)
MAX_SPREAD_PCT = 0.10       # 10% max bid-ask spread (filter out illiquid options)

# Confidence multipliers
ALIGNED_MULTIPLIER = 1.10   # +10% confidence when UOA aligns with signal direction
OPPOSING_MULTIPLIER = 0.85  # -15% confidence when UOA opposes signal direction


def calculate_uoa_score(
    volume: int,
    open_interest: int,
    bid: float,
    ask: float,
    avg_volume: Optional[float] = None,
    avg_oi: Optional[float] = None
) -> Tuple[float, Dict]:
    """
    Calculate UOA score for a single option contract.
    
    Args:
        volume: Current daily volume
        open_interest: Current open interest
        bid: Bid price
        ask: Ask price
        avg_volume: 20-day average volume (optional - defaults to volume/2)
        avg_oi: 20-day average OI (optional - defaults to OI/1.5)
    
    Returns:
        (uoa_score: float, metadata: dict)
        
        uoa_score: Composite score indicating unusual activity strength
        metadata: Breakdown of volume_ratio, oi_ratio, spread_quality, etc.
    """
    # Default averages if not provided (conservative estimates)
    # Real implementation would fetch historical data from EODHD API
    if avg_volume is None:
        avg_volume = max(volume / 2.0, 1)  # Assume current is 2x average
    if avg_oi is None:
        avg_oi = max(open_interest / 1.5, 1)  # Assume current is 1.5x average
    
    # Volume ratio: current vs average
    volume_ratio = volume / avg_volume if avg_volume > 0 else 0
    
    # OI ratio: current vs average
    oi_ratio = open_interest / avg_oi if avg_oi > 0 else 0
    
    # Spread quality: inverse of bid-ask spread %
    # Tighter spreads = higher quality = more credible signal
    mid = (bid + ask) / 2 if (bid and ask) else 0
    spread_pct = (ask - bid) / mid if mid > 0 else 999
    
    # Filter out illiquid options with wide spreads
    if spread_pct > MAX_SPREAD_PCT:
        return 0.0, {
            'volume_ratio': volume_ratio,
            'oi_ratio': oi_ratio,
            'spread_pct': spread_pct,
            'spread_quality': 0,
            'is_liquid': False,
            'reason': f'Spread too wide ({spread_pct:.1%} > {MAX_SPREAD_PCT:.1%})'
        }
    
    # Spread quality: 1.0 for tight spreads (1%), 0.5 for wide spreads (10%)
    spread_quality = max(0, 1.0 - (spread_pct / MAX_SPREAD_PCT))
    
    # UOA Score = Volume × OI × Quality
    uoa_score = volume_ratio * oi_ratio * spread_quality
    
    metadata = {
        'volume_ratio': round(volume_ratio, 2),
        'oi_ratio': round(oi_ratio, 2),
        'spread_pct': round(spread_pct, 4),
        'spread_quality': round(spread_quality, 2),
        'is_liquid': True,
        'is_unusual': volume_ratio >= MIN_VOLUME_RATIO,
        'has_institutional': oi_ratio >= MIN_OI_RATIO
    }
    
    return round(uoa_score, 2), metadata


def scan_chain_for_uoa(
    chain_data: dict,
    signal_direction: str,
    entry_price: float,
    max_strikes: int = 10
) -> Dict:
    """
    Scan entire options chain for unusual activity and determine alignment.
    
    Args:
        chain_data: Nested options chain dict from EODHD
                    {expiry: {"calls": {strike: {...}}, "puts": {strike: {...}}}}
        signal_direction: "bull" or "bear"
        entry_price: Current stock price
        max_strikes: Maximum strikes to scan around ATM (default 10 = ±5 strikes)
    
    Returns:
        {
            'uoa_detected': bool,
            'uoa_aligned': bool,
            'uoa_opposing': bool,
            'uoa_multiplier': float,
            'uoa_label': str,
            'uoa_max_score': float,
            'uoa_top_aligned': List[Dict],   # Top 3 aligned UOA strikes
            'uoa_top_opposing': List[Dict]   # Top 3 opposing UOA strikes
        }
    """
    call_uoa_strikes = []
    put_uoa_strikes = []
    
    # Scan all expirations and strikes
    for expiration, options_data in chain_data.get("data", {}).items():
        
        # Scan calls
        for strike_str, option in options_data.get("calls", {}).items():
            strike = float(strike_str)
            
            # Only scan strikes within reasonable range of ATM
            if abs(strike - entry_price) / entry_price > 0.10:  # ±10% from ATM
                continue
            
            volume = option.get("volume", 0)
            oi = option.get("openInterest", 0)
            bid = option.get("bid", 0)
            ask = option.get("ask", 0)
            
            if not all([volume, oi, bid, ask]):
                continue
            
            uoa_score, metadata = calculate_uoa_score(volume, oi, bid, ask)
            
            if uoa_score >= MIN_UOA_SCORE:
                call_uoa_strikes.append({
                    'strike': strike,
                    'expiration': expiration,
                    'type': 'CALL',
                    'uoa_score': uoa_score,
                    'volume': volume,
                    'oi': oi,
                    'metadata': metadata
                })
        
        # Scan puts
        for strike_str, option in options_data.get("puts", {}).items():
            strike = float(strike_str)
            
            # Only scan strikes within reasonable range of ATM
            if abs(strike - entry_price) / entry_price > 0.10:  # ±10% from ATM
                continue
            
            volume = option.get("volume", 0)
            oi = option.get("openInterest", 0)
            bid = option.get("bid", 0)
            ask = option.get("ask", 0)
            
            if not all([volume, oi, bid, ask]):
                continue
            
            uoa_score, metadata = calculate_uoa_score(volume, oi, bid, ask)
            
            if uoa_score >= MIN_UOA_SCORE:
                put_uoa_strikes.append({
                    'strike': strike,
                    'expiration': expiration,
                    'type': 'PUT',
                    'uoa_score': uoa_score,
                    'volume': volume,
                    'oi': oi,
                    'metadata': metadata
                })
    
    # Sort by UOA score (highest first)
    call_uoa_strikes.sort(key=lambda x: x['uoa_score'], reverse=True)
    put_uoa_strikes.sort(key=lambda x: x['uoa_score'], reverse=True)
    
    # Get max scores
    max_call_score = call_uoa_strikes[0]['uoa_score'] if call_uoa_strikes else 0
    max_put_score = put_uoa_strikes[0]['uoa_score'] if put_uoa_strikes else 0
    max_uoa_score = max(max_call_score, max_put_score)
    
    # Determine alignment based on signal direction
    uoa_detected = max_uoa_score >= MIN_UOA_SCORE
    
    if not uoa_detected:
        return {
            'uoa_detected': False,
            'uoa_aligned': False,
            'uoa_opposing': False,
            'uoa_multiplier': 1.0,
            'uoa_label': 'UOA-NEUTRAL',
            'uoa_max_score': 0.0,
            'uoa_top_aligned': [],
            'uoa_top_opposing': []
        }
    
    # Alignment logic:
    # Bull signal: Call UOA = aligned, Put UOA = opposing
    # Bear signal: Put UOA = aligned, Call UOA = opposing
    if signal_direction == "bull":
        aligned_strikes = call_uoa_strikes
        opposing_strikes = put_uoa_strikes
        aligned_type = "CALL"
        opposing_type = "PUT"
    else:  # bear
        aligned_strikes = put_uoa_strikes
        opposing_strikes = call_uoa_strikes
        aligned_type = "PUT"
        opposing_type = "CALL"
    
    max_aligned_score = aligned_strikes[0]['uoa_score'] if aligned_strikes else 0
    max_opposing_score = opposing_strikes[0]['uoa_score'] if opposing_strikes else 0
    
    # Determine dominant UOA (which side has stronger signal)
    uoa_aligned = max_aligned_score > max_opposing_score
    uoa_opposing = max_opposing_score > max_aligned_score
    
    # Calculate confidence multiplier
    if uoa_aligned:
        multiplier = ALIGNED_MULTIPLIER
        label = f"UOA-ALIGNED-{aligned_type}(score={max_aligned_score:.1f})"
    elif uoa_opposing:
        multiplier = OPPOSING_MULTIPLIER
        label = f"UOA-OPPOSING-{opposing_type}(score={max_opposing_score:.1f})"
    else:
        # Tie or ambiguous
        multiplier = 1.0
        label = "UOA-MIXED"
    
    return {
        'uoa_detected': True,
        'uoa_aligned': uoa_aligned,
        'uoa_opposing': uoa_opposing,
        'uoa_multiplier': multiplier,
        'uoa_label': label,
        'uoa_max_score': max_uoa_score,
        'uoa_top_aligned': aligned_strikes[:3],     # Top 3 aligned strikes
        'uoa_top_opposing': opposing_strikes[:3]    # Top 3 opposing strikes
    }


def format_uoa_summary(uoa_data: Dict) -> str:
    """
    Format UOA scan results for Discord/console logging.
    
    Args:
        uoa_data: Output from scan_chain_for_uoa()
    
    Returns:
        Formatted string summary
    """
    if not uoa_data.get('uoa_detected'):
        return "No unusual options activity detected"
    
    lines = []
    lines.append(f"🎯 UOA Detected: {uoa_data['uoa_label']}")
    lines.append(f"   Max Score: {uoa_data['uoa_max_score']:.1f}")
    lines.append(f"   Multiplier: {uoa_data['uoa_multiplier']:.2f}x")
    
    if uoa_data.get('uoa_top_aligned'):
        lines.append("\n   Top Aligned Strikes:")
        for strike_data in uoa_data['uoa_top_aligned'][:3]:
            lines.append(
                f"     ${strike_data['strike']:.0f} {strike_data['type']} | "
                f"Score: {strike_data['uoa_score']:.1f} | "
                f"Vol: {strike_data['volume']:,} | OI: {strike_data['oi']:,}"
            )
    
    if uoa_data.get('uoa_top_opposing'):
        lines.append("\n   ⚠️ Opposing Strikes:")
        for strike_data in uoa_data['uoa_top_opposing'][:3]:
            lines.append(
                f"     ${strike_data['strike']:.0f} {strike_data['type']} | "
                f"Score: {strike_data['uoa_score']:.1f} | "
                f"Vol: {strike_data['volume']:,} | OI: {strike_data['oi']:,}"
            )
    
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test UOA scanner with mock data
    print("Testing UOA Scanner...\n")
    
    # Mock options chain with unusual call activity
    mock_chain = {
        "data": {
            "2026-02-28": {
                "calls": {
                    "450": {
                        "volume": 5000,        # 5x average (1000)
                        "openInterest": 3000,   # 2x average (1500)
                        "bid": 2.50,
                        "ask": 2.55            # Tight 2% spread
                    },
                    "455": {
                        "volume": 8000,        # 8x average
                        "openInterest": 4000,   # 2.7x average
                        "bid": 1.80,
                        "ask": 1.85            # Tight spread
                    }
                },
                "puts": {
                    "445": {
                        "volume": 800,          # Normal volume
                        "openInterest": 1200,
                        "bid": 1.20,
                        "ask": 1.25
                    }
                }
            }
        }
    }
    
    # Test bullish signal (should align with call UOA)
    print("="*60)
    print("TEST 1: Bullish Signal with Call UOA (ALIGNED)")
    print("="*60)
    result = scan_chain_for_uoa(mock_chain, "bull", entry_price=450.0)
    print(format_uoa_summary(result))
    print(f"\nConfidence Impact: {(result['uoa_multiplier'] - 1) * 100:+.0f}%\n")
    
    # Test bearish signal (should oppose call UOA)
    print("="*60)
    print("TEST 2: Bearish Signal with Call UOA (OPPOSING)")
    print("="*60)
    result = scan_chain_for_uoa(mock_chain, "bear", entry_price=450.0)
    print(format_uoa_summary(result))
    print(f"\nConfidence Impact: {(result['uoa_multiplier'] - 1) * 100:+.0f}%\n")
