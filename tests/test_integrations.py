"""
War Machine — Integration Test Suite
======================================
Consolidates all external-service integration tests into one file.
CI-safe tests run automatically (no credentials needed).
Integration tests are marked @pytest.mark.integration and skipped in CI.

Covers:
  1. Discord EOD stats webhook
       - test_discord_env_check          — env var presence (always passes)
       - test_discord_eod_send           — live EOD P&L message to Discord   [@integration]

  2. Greeks + Discord alert
       - test_greeks_precheck_importable — app.validation.greeks_precheck imports cleanly
       - test_discord_helpers_importable — app.notifications.discord_helpers imports cleanly
       - test_greeks_aapl_validation     — live AAPL call Greeks via Tradier  [@integration]
       - test_discord_alert_with_greeks  — live Discord alert with Greeks data [@integration]

Run CI-safe only (default):
    pytest tests/test_integrations.py -v -m "not integration"

Run all (requires live credentials):
    pytest tests/test_integrations.py -v
"""
import os
import pytest
from datetime import datetime, date
from zoneinfo import ZoneInfo


# ── Import guards ─────────────────────────────────────────────────────────────
try:
    from app.validation.greeks_precheck import validate_signal_greeks, get_cached_greeks
    _GREEKS_AVAILABLE = True
except ImportError:
    _GREEKS_AVAILABLE = False

try:
    from app.notifications.discord_helpers import send_options_signal_alert
    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# 1. DISCORD EOD STATS
# ─────────────────────────────────────────────────────────────────────────────
def test_discord_env_check():
    """
    Report whether required env vars are present.
    Informational only — never fails CI over missing credentials.
    """
    db_url  = os.getenv("DATABASE_URL")
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    assert True, (
        f"DATABASE_URL={'set' if db_url else 'MISSING'}, "
        f"DISCORD_WEBHOOK_URL={'set' if webhook else 'MISSING'}"
    )


@pytest.mark.integration
def test_discord_eod_send():
    """Query today's P&L from DB and post an EOD summary to Discord."""
    import psycopg2
    import requests

    db_url  = os.getenv("DATABASE_URL")
    webhook = os.getenv("DISCORD_WEBHOOK_URL")

    if not db_url:     pytest.skip("DATABASE_URL not set")
    if not webhook:    pytest.skip("DISCORD_WEBHOOK_URL not set")

    db     = psycopg2.connect(db_url)
    cursor = db.cursor()
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'WIN'  THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
            ROUND(SUM(CASE WHEN outcome IS NOT NULL THEN profit_pct END), 2) as total_profit
        FROM signal_outcomes
        WHERE DATE(signal_time) = CURRENT_DATE
    """)
    row    = cursor.fetchone()
    total, wins, losses, profit = row
    total  = total  or 0
    wins   = wins   or 0
    losses = losses or 0
    profit = profit or 0.0
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0

    message = (
        f"**WAR MACHINE EOD** - {date.today()}\n\n"
        f"Trades: {total} | W/L: {wins}/{losses} ({win_rate:.0f}% WR)\n"
        f"Total P&L: {profit:+.2f}%"
    )
    response = requests.post(webhook, json={"content": message})
    assert response.status_code == 204, (
        f"Discord webhook returned {response.status_code}: {response.text}"
    )
    db.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. GREEKS PRECHECK + DISCORD ALERT
# ─────────────────────────────────────────────────────────────────────────────
def test_greeks_precheck_importable():
    """app.validation.greeks_precheck must import cleanly."""
    assert _GREEKS_AVAILABLE, (
        "app.validation.greeks_precheck failed to import — "
        "check for missing deps or syntax errors"
    )


def test_discord_helpers_importable():
    """app.notifications.discord_helpers must import cleanly."""
    assert _DISCORD_AVAILABLE, (
        "app.notifications.discord_helpers failed to import — "
        "check for missing deps or syntax errors"
    )


@pytest.mark.integration
@pytest.mark.skipif(not _GREEKS_AVAILABLE, reason="greeks_precheck not importable")
def test_greeks_aapl_validation():
    """Live AAPL call Greeks validation via Tradier (requires live API key)."""
    is_valid, reason = validate_signal_greeks("AAPL", "bull", 265.00)
    assert isinstance(is_valid, bool), "is_valid must be bool"
    assert isinstance(reason,   str),  "reason must be str"
    assert len(reason) > 0,            "reason must not be empty"

    if is_valid:
        greeks_list = get_cached_greeks("AAPL", "bull")
        if greeks_list:
            best = greeks_list[0]
            for key in ('strike', 'delta', 'iv', 'dte', 'spread_pct', 'is_liquid'):
                assert key in best, f"Missing key: {key}"
            assert 0 < abs(best['delta']) <= 1.0
            assert best['iv']  > 0
            assert best['dte'] >= 0


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
    send_options_signal_alert(
        ticker="AAPL", direction="bull",
        entry=265.00, stop=262.50, t1=267.50, t2=270.00,
        confidence=0.75, timeframe="5m", grade="A",
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
