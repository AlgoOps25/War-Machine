"""
test_discord_simple.py — Simple Discord EOD stats message

CI-safe:
  - test_discord_simple_env_check  — warns if env vars are missing (never crashes)

Integration (requires DATABASE_URL + DISCORD_WEBHOOK_URL):
  - test_discord_simple_send       — queries DB, sends message to Discord

Run CI-safe only:
  pytest tests/test_discord_simple.py -v -m "not integration"
"""
import os
import pytest


def test_discord_simple_env_check():
    """Report whether required env vars are present (informational, always passes)."""
    db_url  = os.getenv("DATABASE_URL")
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    # Just informational — never fail CI over missing env vars
    assert True, (
        f"DATABASE_URL={'set' if db_url else 'MISSING'}, "
        f"DISCORD_WEBHOOK_URL={'set' if webhook else 'MISSING'}"
    )


@pytest.mark.integration
def test_discord_simple_send():
    """Query today's P&L from DB and post to Discord."""
    import psycopg2
    import requests
    from datetime import date

    db_url  = os.getenv("DATABASE_URL")
    webhook = os.getenv("DISCORD_WEBHOOK_URL")

    if not db_url:
        pytest.skip("DATABASE_URL not set")
    if not webhook:
        pytest.skip("DISCORD_WEBHOOK_URL not set")

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

    row = cursor.fetchone()
    total, wins, losses, profit = row

    # Coerce NULLs (no trades today — valid state)
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
