"""
test_discord_reports.py — Discord EOD Report System Tests

CI-safe:
  - test_discord_reports_src_importable  — checks if src.reporting is importable

Integration (requires DATABASE_URL + Discord webhook):
  - test_discord_eod_report_generates    — live report generation + optional send

Run CI-safe only:
  pytest tests/test_discord_reports.py -v -m "not integration"
"""
import os
import pytest

try:
    from src.reporting.performance_reporter import PerformanceReporter
    _SRC_REPORTING_AVAILABLE = True
except ImportError:
    _SRC_REPORTING_AVAILABLE = False
    PerformanceReporter = None


def test_discord_reports_src_importable():
    """src.reporting.performance_reporter must import cleanly."""
    assert _SRC_REPORTING_AVAILABLE, (
        "src.reporting.performance_reporter failed to import. "
        "Check that the src/ directory exists and is on sys.path, "
        "and that all dependencies (psycopg2, etc.) are installed."
    )


@pytest.mark.integration
@pytest.mark.skipif(not _SRC_REPORTING_AVAILABLE, reason="src.reporting not importable")
def test_discord_eod_report_generates():
    """Generate EOD report from live DB; optionally send to Discord."""
    import psycopg2
    from datetime import date

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")

    webhook = os.getenv("DISCORD_WEBHOOK_URL")  # optional

    db = psycopg2.connect(db_url)
    reporter = PerformanceReporter(db, webhook)

    report = reporter.generate_eod_report(date.today())

    if report is None:
        pytest.skip("No signal data for today — normal if no trades logged")

    assert 'date'         in report
    assert 'total_signals' in report
    assert 'wins'         in report
    assert 'losses'       in report
    assert 'win_rate'     in report
    assert report['total_signals'] >= 0

    if webhook:
        success = reporter.send_to_discord(report)
        assert success, "Discord send returned False"

    db.close()
