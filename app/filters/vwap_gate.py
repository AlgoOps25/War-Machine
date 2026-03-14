"""
vwap_gate.py — VWAP Directional Gate
Extracted from sniper.py (Phase 2 win rate enhancement)

Provides:
    VWAP_GATE_ENABLED   — master toggle
    compute_vwap()      — session VWAP from bars
    passes_vwap_gate()  — bull must be above VWAP, bear must be below
"""

VWAP_GATE_ENABLED = True


def compute_vwap(bars: list) -> float:
    """Compute session VWAP from a list of OHLCV bars."""
    if not bars or len(bars) < 5:
        return 0.0
    cumulative_tpv = 0.0
    cumulative_vol = 0.0
    for bar in bars:
        typical_price = (bar['high'] + bar['low'] + bar['close']) / 3.0
        volume = bar.get('volume', 0)
        cumulative_tpv += typical_price * volume
        cumulative_vol += volume
    if cumulative_vol == 0:
        return 0.0
    return cumulative_tpv / cumulative_vol


def passes_vwap_gate(bars: list, direction: str, current_price: float) -> tuple:
    """
    Returns (passed: bool, reason: str).
    Bull signals require price > VWAP; bear signals require price < VWAP.
    """
    if not VWAP_GATE_ENABLED:
        return True, "VWAP gate disabled"
    vwap = compute_vwap(bars)
    if vwap == 0.0:
        return True, "VWAP unavailable (insufficient data)"
    if direction == "bull":
        if current_price > vwap:
            return True, f"BULL + price above VWAP (${current_price:.2f} > ${vwap:.2f})"
        else:
            return False, f"BULL signal rejected: price below VWAP (${current_price:.2f} < ${vwap:.2f})"
    elif direction == "bear":
        if current_price < vwap:
            return True, f"BEAR + price below VWAP (${current_price:.2f} < ${vwap:.2f})"
        else:
            return False, f"BEAR signal rejected: price above VWAP (${current_price:.2f} > ${vwap:.2f})"
    return True, "Unknown direction"
