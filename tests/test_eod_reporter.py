"""
tests/test_eod_reporter.py

Unit tests for app/core/eod_reporter.run_eod_report().

Strategy: stub the entire import chain in sys.modules BEFORE eod_reporter
is imported so Python never tries to exec risk_manager → position_manager
(which has a module-level PositionManager() instantiation that hits the DB
and fails under Python 3.14 strict UTF-8 / no-DB conditions).

All external dependencies are mocked:
  - app.risk.risk_manager          (entire module stub)
  - app.notifications.discord_helpers (entire module stub)
  - app.signals.signal_analytics   (entire module stub)

No DB, no Discord, no network access.
"""
import sys
import importlib
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module-level sys.modules stubs — installed ONCE before any import of
# eod_reporter so the chain never reaches position_manager.
# ---------------------------------------------------------------------------

def _make_risk_manager_stub(session, top):
    stub = MagicMock()
    stub.get_session_status.return_value = session
    stub.get_eod_report.return_value = top
    return stub


def _make_discord_stub():
    stub = MagicMock()
    stub.send_daily_summary = MagicMock()
    stub.send_simple_message = MagicMock()
    return stub


def _make_signal_analytics_stub(discord_msg="📊 Signal funnel block", daily_summary="=== DAILY SUMMARY ==="):
    tracker = MagicMock()
    tracker.get_discord_eod_summary.return_value = discord_msg
    tracker.get_daily_summary.return_value = daily_summary
    stub = MagicMock()
    stub.signal_tracker = tracker
    return stub, tracker


# ---------------------------------------------------------------------------
# Fixtures / default data
# ---------------------------------------------------------------------------

DEFAULT_SESSION = {
    "daily_stats": {
        "trades":    5,
        "wins":      3,
        "losses":    2,
        "win_rate":  60.0,
        "total_pnl": 320.50,
    },
    "open_positions": [],
}

EMPTY_SESSION = {
    "daily_stats": {
        "trades":    0,
        "wins":      0,
        "losses":    0,
        "win_rate":  0.0,
        "total_pnl": 0.0,
    },
    "open_positions": [],
}


# ---------------------------------------------------------------------------
# Helper: run eod_reporter with fully isolated sys.modules
# ---------------------------------------------------------------------------

def _run_eod_report(
    session=None,
    top_performers="SPY +2.1R",
    discord_msg="📊 Signal funnel block",
    daily_summary="=== DAILY SUMMARY ===",
    session_date="2026-03-17",
    session_status_side_effect=None,
    signal_analytics_missing=False,
):
    """
    Isolate eod_reporter from its real dependencies by patching sys.modules
    before import, then reload the module so fresh bindings are created.

    Returns (send_daily_summary_mock, send_simple_message_mock, tracker_mock)
    """
    if session is None:
        session = DEFAULT_SESSION

    risk_stub    = _make_risk_manager_stub(session, top_performers)
    discord_stub = _make_discord_stub()

    if session_status_side_effect:
        risk_stub.get_session_status.side_effect = session_status_side_effect
        risk_stub.get_session_status.return_value = None

    if signal_analytics_missing:
        sa_stub, tracker = None, None
    else:
        sa_stub, tracker = _make_signal_analytics_stub(discord_msg, daily_summary)

    # Keys that must be stubbed to prevent real imports
    stubs = {
        "app.risk.risk_manager":              risk_stub,
        "app.notifications.discord_helpers":  discord_stub,
    }
    if signal_analytics_missing:
        # Remove so the ImportError branch in run_eod_report() fires
        stubs["app.signals.signal_analytics"] = None  # will be popped below
    else:
        stubs["app.signals.signal_analytics"] = sa_stub

    # Also stub any transitive deps that position_manager would pull
    transitive = [
        "app.risk.position_manager",
        "app.risk.risk_manager",
        "app.data.db_connection",
        "app.data",
        "app.risk",
        "utils.config",
        "utils",
    ]
    for key in transitive:
        if key not in stubs:
            stubs[key] = MagicMock()

    # Remove eod_reporter from cache so reload picks up fresh bindings
    for key in list(sys.modules.keys()):
        if "eod_reporter" in key:
            del sys.modules[key]

    with patch.dict("sys.modules", stubs):
        # If signal_analytics is meant to be missing, ensure it raises ImportError
        if signal_analytics_missing:
            sys.modules.pop("app.signals.signal_analytics", None)

        import app.core.eod_reporter as eod_reporter
        eod_reporter.get_session_status = risk_stub.get_session_status
        eod_reporter.get_eod_report     = risk_stub.get_eod_report
        eod_reporter.send_daily_summary  = discord_stub.send_daily_summary
        eod_reporter.send_simple_message = discord_stub.send_simple_message

        eod_reporter.run_eod_report(session_date)

    return discord_stub.send_daily_summary, discord_stub.send_simple_message, tracker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunEodReport:

    # ------------------------------------------------------------------
    # 1. Happy path — send_daily_summary called with correct trade stats
    # ------------------------------------------------------------------
    def test_send_daily_summary_called_with_trade_stats(self):
        mock_summary, _, _ = _run_eod_report()

        mock_summary.assert_called_once()
        payload = mock_summary.call_args[0][0]
        assert payload["trades"]    == 5
        assert payload["wins"]      == 3
        assert payload["losses"]    == 2
        assert payload["win_rate"]  == 60.0
        assert payload["total_pnl"] == 320.50

    # ------------------------------------------------------------------
    # 2. Top performers plain-text block sent when available
    # ------------------------------------------------------------------
    def test_top_performers_sent_as_simple_message(self):
        _, mock_msg, _ = _run_eod_report(top_performers="NVDA +3.2R", discord_msg="")

        calls = [str(c) for c in mock_msg.call_args_list]
        assert any("NVDA +3.2R" in c for c in calls)

    # ------------------------------------------------------------------
    # 3. No top performers call when get_eod_report returns empty string
    # ------------------------------------------------------------------
    def test_no_top_performers_message_when_empty(self):
        _, mock_msg, _ = _run_eod_report(top_performers="", discord_msg="")

        calls = [str(c) for c in mock_msg.call_args_list]
        top_perf_calls = [c for c in calls if "Top Performers" in c]
        assert len(top_perf_calls) == 0

    # ------------------------------------------------------------------
    # 4. Signal funnel Discord block sent when tracker returns content
    # ------------------------------------------------------------------
    def test_signal_funnel_discord_block_sent(self):
        _, mock_msg, _ = _run_eod_report(
            top_performers="",
            discord_msg="📊 Signal funnel block content",
        )

        calls = [str(c) for c in mock_msg.call_args_list]
        funnel_calls = [c for c in calls if "Signal funnel block content" in c]
        assert len(funnel_calls) == 1

    # ------------------------------------------------------------------
    # 5. clear_session_cache() called after sending
    # ------------------------------------------------------------------
    def test_clear_session_cache_called(self):
        _, _, tracker = _run_eod_report()
        tracker.clear_session_cache.assert_called_once()

    # ------------------------------------------------------------------
    # 6. get_daily_summary() output printed to stdout
    # ------------------------------------------------------------------
    def test_daily_summary_printed_to_stdout(self, capsys):
        _run_eod_report(daily_summary="=== FULL SUMMARY OUTPUT ===")

        captured = capsys.readouterr()
        assert "=== FULL SUMMARY OUTPUT ===" in captured.out

    # ------------------------------------------------------------------
    # 7. Graceful degradation when signal_analytics is unavailable
    # ------------------------------------------------------------------
    def test_graceful_degradation_when_signal_analytics_missing(self):
        """Should not raise — just skips funnel block and logs warning."""
        try:
            _run_eod_report(signal_analytics_missing=True)
        except ImportError:
            pytest.fail("run_eod_report raised ImportError — graceful degradation broken")
        except Exception as e:
            pytest.fail(f"run_eod_report raised unexpected exception: {e}")

    # ------------------------------------------------------------------
    # 8. Graceful degradation when get_session_status raises
    # ------------------------------------------------------------------
    def test_graceful_degradation_when_session_status_raises(self):
        """Should not propagate exception — logs error and continues."""
        try:
            _run_eod_report(session_status_side_effect=Exception("DB down"))
        except Exception as e:
            pytest.fail(f"run_eod_report propagated exception: {e}")
