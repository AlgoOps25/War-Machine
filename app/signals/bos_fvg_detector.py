"""
app/signals/bos_fvg_detector.py
================================
CANONICAL BOS/FVG Detector — single source of truth.

All BOS/FVG detection logic lives in app/mtf/bos_fvg_engine.py.
This module re-exports everything from there so any import of
`bos_fvg_detector` continues to work without modification.

Retired detector files (DO NOT add logic to these):
  - aggressive_bos_detector.py   → redirects here
  - comprehensive_detector.py    → redirects here
  - enhanced_bos_fvg_v2.py       → redirects here
  - hybrid_bos_detector.py       → redirects here
  - realistic_bos_fvg.py         → redirects here

Usage:
    from app.signals.bos_fvg_detector import detect_bos, detect_fvg
    # or
    from app.mtf.bos_fvg_engine import detect_bos, detect_fvg
"""

# Re-export everything from the canonical engine
from app.mtf.bos_fvg_engine import *  # noqa: F401, F403
from app.mtf.bos_fvg_engine import (
    detect_bos,
    detect_fvg,
    detect_bos_fvg_pattern,
    BOSResult,
    FVGResult,
)

__all__ = [
    "detect_bos",
    "detect_fvg",
    "detect_bos_fvg_pattern",
    "BOSResult",
    "FVGResult",
]
