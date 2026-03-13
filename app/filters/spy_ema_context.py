# app/filters/spy_ema_context.py
# SHIM — kept for backward-compat with any stale imports.
# Real logic lives in app/filters/market_regime_context.py (Phase 1.25)
from app.filters.market_regime_context import (
    get_market_regime as get_spy_ema_regime,
    print_market_regime as print_spy_regime,
    get_market_regime,
    print_market_regime,
    send_regime_discord,
)

def is_long_allowed(regime: dict) -> bool:
    """Shim — always returns True. Hard blocks removed in Phase 1.25."""
    return True

def is_short_allowed(regime: dict) -> bool:
    """Shim — always returns True. Hard blocks removed in Phase 1.25."""
    return True
