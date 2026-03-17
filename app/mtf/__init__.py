"""
app.mtf package

Exports:
    scan_bos_fvg             — primary BOS+FVG signal detector
    enhance_signal_with_mtf  — MTF convergence boost
    run_mtf_trend_step       — Step 8.5 MTF trend alignment
    enrich_signal_with_smc   — SMC context enrichment (CHoCH/Inducement/OB/Phase)
    MTFTrendValidator        — class
    MTFValidator             — alias
    get_mtf_trend_validator  — factory
    mtf_validator            — singleton
    validate_signal_mtf      — convenience function
"""

from app.mtf.bos_fvg_engine   import scan_bos_fvg
from app.mtf.mtf_integration  import enhance_signal_with_mtf, run_mtf_trend_step
from app.mtf.mtf_validator     import (
    MTFTrendValidator,
    MTFValidator,
    get_mtf_trend_validator,
    mtf_validator,
    validate_signal_mtf,
)
from app.mtf.smc_engine        import enrich_signal_with_smc

__all__ = [
    'scan_bos_fvg',
    'enhance_signal_with_mtf',
    'run_mtf_trend_step',
    'enrich_signal_with_smc',
    'MTFTrendValidator',
    'MTFValidator',
    'get_mtf_trend_validator',
    'mtf_validator',
    'validate_signal_mtf',
]
