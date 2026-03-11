"""
test_greeks_discord.py — Greeks Cache + Discord Integration Tests

CI-safe tests (run automatically):
  - test_greeks_precheck_importable  — checks if greeks_precheck is importable
  - test_discord_helpers_importable  — checks if discord_helpers is importable

Integration tests (require live Tradier API key + Discord webhook):
  - test_greeks_aapl_validation      — live AAPL call validation via Tradier
  - test_discord_alert_with_greeks   — live Discord alert send with Greeks data

Run CI-safe only:
  pytest tests/test_greeks_discord.py -v -m "not integration"

Run all (with live credentials):
  pytest tests/test_greeks_discord.py -v
"""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo


try:
    from app.validation.greeks_precheck import validate_signal_greeks, get_cached_greeks
    _GREEKS_AVAILABLE = True
except ImportError:
    _GREEKS_AVAILABLE = False

try:
    from app.discord_helpers import send_options_signal_alert
    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# CI-SAFE TESTS
# ─────────────────────────────────────────────────────────────────────────────
def test_greeks_precheck_importable():
    """app.validation.greeks_precheck should import cleanly."""
    assert _GREEKS_AVAILABLE, (
        "app.validation.greeks_precheck failed to import — "
        "check for missing deps or syntax errors"
    )


def test_discord_helpers_importable():
    """app.discord_helpers should import cleanly."""
    assert _DISCORD_AVAILABLE, (
        "app.discord_helpers failed to import — "
        "check for missing deps or syntax errors"
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS (require live Tradier API + Discord webhook)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _GREEKS_AVAILABLE, reason="greeks_precheck not importable")
def test_greeks_aapl_validation():
    """Live AAPL call Greeks validation via Tradier (requires live API key)."""
    ticker      = "AAPL"
    direction   = "bull"
    entry_price = 265.00

    is_valid, reason = validate_signal_greeks(ticker, direction, entry_price)
    assert isinstance(is_valid, bool),  "is_valid must be bool"
    assert isinstance(reason,   str),   "reason must be str"
    assert len(reason) > 0,             "reason must not be empty"

    if is_valid:
        greeks_list = get_cached_greeks(ticker, direction)
        if greeks_list:
            best = greeks_list[0]
            assert 'strike'     in best
            assert 'delta'      in best
            assert 'iv'         in best
            assert 'dte'        in best
            assert 'spread_pct' in best
            assert 'is_liquid'  in best
            assert 0 < abs(best['delta']) <= 1.0,    f"Delta out of range: {best['delta']}"
            assert best['iv'] > 0,                   f"IV must be positive: {best['iv']}"
            assert best['dte'] >= 0,                 f"DTE must be non-negative: {best['dte']}"


@pytest.mark.integration
@pytest.mark.skipif(
    not (_GREEKS_AVAILABLE and _DISCORD_AVAILABLE),
    reason="greeks_precheck or discord_helpers not importable"
)
def test_discord_alert_with_greeks():
    """
    Sends a live Discord alert with Greeks data.
    Requires DISCORD_WEBHOOK_URL to be set.
    This test sends a REAL message — only run manually.
    """
    is_valid, reason = validate_signal_greeks("AAPL", "bull", 265.00)

    greeks_data = {
        'is_valid': is_valid,
        'reason':   reason,
        'best_strike': 265 if is_valid else None,
        'details': {
            'delta': 0.50, 'iv': 0.314, 'dte': 2,
            'spread_pct': 4.4, 'liquidity_ok': True
        }
    }

    # This will raise if Discord webhook URL is not configured
    send_options_signal_alert(
        ticker="AAPL",
        direction="bull",
        entry=265.00,
        stop=262.50,
        t1=267.50,
        t2=270.00,
        confidence=0.75,
        timeframe="5m",
        grade="A",
        options_data={
            'contract_label': '$265C 2DTE',
            'strike': 265, 'dte': 2,
            'delta': 0.50, 'theta': -0.15,
            'iv': 0.314, 'bid': 3.30,
            'ask': 3.45, 'mid': 3.38,
            'limit_entry': 3.35, 'max_entry': 3.45,
            'spread_pct': 4.4
        },
        confirmation="A+",
        candle_type="Hammer",
        greeks_data=greeks_data
    )
