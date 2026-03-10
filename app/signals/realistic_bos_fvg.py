"""
app/signals/realistic_bos_fvg.py
==================================
DEPRECATED — Redirects to canonical bos_fvg_detector.py

This file was one of 5 parallel BOS/FVG detectors consolidated
per Issue #9. All logic now lives in app/mtf/bos_fvg_engine.py.

Do NOT add new logic here. Import from bos_fvg_detector instead:
    from app.signals.bos_fvg_detector import detect_bos, detect_fvg
"""

import warnings
warnings.warn(
    "realistic_bos_fvg is deprecated. "
    "Use app.signals.bos_fvg_detector or app.mtf.bos_fvg_engine instead.",
    DeprecationWarning,
    stacklevel=2,
)

from app.signals.bos_fvg_detector import *  # noqa: F401, F403, E402
from app.signals.bos_fvg_detector import detect_bos, detect_fvg, detect_bos_fvg_pattern  # noqa: E402
