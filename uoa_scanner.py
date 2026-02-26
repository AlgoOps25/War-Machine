"""
Unusual Options Activity (UOA) Scanner - STUB (Phase 3C)

This module has been consolidated into options_intelligence.py.
This stub provides backward compatibility.

Consolidated modules:
  - options_data_manager.py
  - uoa_scanner.py
  → options_intelligence.py
"""

# Forward all imports to the new consolidated module
from options_intelligence import (
    scan_chain_for_uoa,
    MIN_VOLUME_RATIO,
    MIN_OI_RATIO,
    MIN_UOA_SCORE,
    EXTREME_UOA_SCORE,
    MAX_SPREAD_PCT,
    ALIGNED_MULTIPLIER,
    OPPOSING_MULTIPLIER
)

# Legacy function names (no longer needed, but kept for compatibility)
def calculate_uoa_score(*args, **kwargs):
    """Legacy function - now internal to OptionsIntelligence class."""
    raise NotImplementedError(
        "calculate_uoa_score() is now private. "
        "Use scan_chain_for_uoa() instead."
    )

def format_uoa_summary(uoa_data: dict) -> str:
    """Format UOA scan results for logging."""
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

__all__ = [
    'scan_chain_for_uoa',
    'format_uoa_summary',
    'MIN_VOLUME_RATIO',
    'MIN_OI_RATIO',
    'MIN_UOA_SCORE',
    'EXTREME_UOA_SCORE',
    'MAX_SPREAD_PCT',
    'ALIGNED_MULTIPLIER',
    'OPPOSING_MULTIPLIER'
]
