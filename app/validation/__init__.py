"""
app/validation — Public API

Two validation pipelines live in this package:

  SignalValidator  (validation.py)
    Weighted confidence-adjustment model used by sniper.py.
    Layers: regime, time-of-day, EMA stack, RSI divergence, ADX,
    volume, DMI, CCI, Bollinger, VPVR, daily bias.
    Entry points: get_validator(), get_regime_filter(), get_options_filter()

  validate_signal  (cfw6_gate_validator.py)
    Six-gate sequential pipeline intended for scanner.py.
    Gates: time-of-day, regime/RVOL, volume, Greeks, ML, min-confidence.
    Currently imported by scanner.py but disabled (validate_signal = None).
    Re-enable by removing that override line in scanner.py.

Additional modules:
  greeks_precheck.py  — GreeksCache + validate_signal_greeks() used by sniper.py
"""
from app.validation.validation import (
    SignalValidator,
    RegimeFilter,
    RegimeState,
    OptionsFilter,
    get_validator,
    get_regime_filter,
    get_options_filter,
    get_time_of_day_quality,
    get_options_recommendation,
)
from app.validation.cfw6_gate_validator import validate_signal

__all__ = [
    # validation.py — sniper.py pipeline
    'SignalValidator',
    'RegimeFilter',
    'RegimeState',
    'OptionsFilter',
    'get_validator',
    'get_regime_filter',
    'get_options_filter',
    'get_time_of_day_quality',
    'get_options_recommendation',
    # cfw6_gate_validator.py — scanner.py pipeline
    'validate_signal',
]
