"""
tests/test_eod_reporter.py

Unit tests for app/core/eod_reporter.run_eod_report().

All external dependencies are mocked:
  - app.risk.risk_manager.get_session_status
  - app.risk.risk_manager.get_eod_report
  - app.notifications.discord_helpers.send_daily_summary
  - app.notifications.discord_helpers.send_simple_message
  - app.signals.signal_analytics.signal_tracker

No DB, no Discord, no network access.
"""
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
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


def _make_tracker_mock(
    discord_msg="\U0001f4ca Signal funnel block",
    daily_summary="=== DAILY SUMMARY ===",
):
    tracker = MagicMock()
    tracker.get_discord_eod_summary.return_value = discord_msg
    tracker.get_daily_summary.return_value = daily_summary
    return tracker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunEodReport:

    def _run(self, session=None, top_performers="SPY +2.1R",
             tracker=None, session_date="2026-03-17"):
        """Helper: patch all deps and call run_eod_report."""
        if session is None:
            session = DEFAULT_SESSION
        if tracker is None:
            tracker = _make_tracker_mock()

        with patch("app.core.eod_reporter.get_session_status", return_value=session), \
             patch("app.core.eod_reporter.get_eod_report", return_value=top_performers), \
             patch("app.core.eod_reporter.send_daily_summary") as mock_summary, \
             patch("app.core.eod_reporter.send_simple_message") as mock_msg, \
             patch("app.signals.signal_analytics.signal_tracker", tracker), \
             patch("app.core.eod_reporter.signal_tracker", tracker, create=True):
            from app.core import eod_reporter
            # Force re-import of signal_tracker inside function scope
            with patch.dict("sys.modules", {"app.signals.signal_analytics": MagicMock(signal_tracker=tracker)}):
                eod_reporter.run_eod_report(session_date)
            return mock_summary, mock_msg, tracker

    # ------------------------------------------------------------------
    # 1. Happy path — send_daily_summary called with correct trade stats
    # ------------------------------------------------------------------
    def test_send_daily_summary_called_with_trade_stats(self):
        with patch("app.core.eod_reporter.get_session_status", return_value=DEFAULT_SESSION), \
             patch("app.core.eod_reporter.get_eod_report", return_value="SPY +2.1R"), \
             patch("app.core.eod_reporter.send_daily_summary") as mock_summary, \
             patch("app.core.eod_reporter.send_simple_message"), \
             patch.dict("sys.modules", {"app.signals.signal_analytics": MagicMock(signal_tracker=_make_tracker_mock())}):
            from app.core import eod_reporter
            eod_reporter.run_eod_report("2026-03-17")

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
        tracker = _make_tracker_mock(discord_msg="")
        with patch("app.core.eod_reporter.get_session_status", return_value=DEFAULT_SESSION), \
             patch("app.core.eod_reporter.get_eod_report", return_value="NVDA +3.2R"), \
             patch("app.core.eod_reporter.send_daily_summary"), \
             patch("app.core.eod_reporter.send_simple_message") as mock_msg, \
             patch.dict("sys.modules", {"app.signals.signal_analytics": MagicMock(signal_tracker=tracker)}):
            from app.core import eod_reporter
            eod_reporter.run_eod_report("2026-03-17")

        calls = [str(c) for c in mock_msg.call_args_list]
        assert any("NVDA +3.2R" in c for c in calls)

    # ------------------------------------------------------------------
    # 3. No top performers call when get_eod_report returns empty string
    # ------------------------------------------------------------------
    def test_no_top_performers_message_when_empty(self):
        tracker = _make_tracker_mock(discord_msg="")
        msgs_sent = []
        with patch("app.core.eod_reporter.get_session_status", return_value=DEFAULT_SESSION), \
             patch("app.core.eod_reporter.get_eod_report", return_value=""), \
             patch("app.core.eod_reporter.send_daily_summary"), \
             patch("app.core.eod_reporter.send_simple_message", side_effect=msgs_sent.append), \
             patch.dict("sys.modules", {"app.signals.signal_analytics": MagicMock(signal_tracker=tracker)}):
            from app.core import eod_reporter
            eod_reporter.run_eod_report("2026-03-17")

        top_perf_calls = [m for m in msgs_sent if "Top Performers" in str(m)]
        assert len(top_perf_calls) == 0

    # ------------------------------------------------------------------
    # 4. Signal funnel Discord block sent when tracker returns content
    # ------------------------------------------------------------------
    def test_signal_funnel_discord_block_sent(self):
        tracker = _make_tracker_mock(discord_msg="\U0001f4ca Signal funnel block content")
        msgs_sent = []
        with patch("app.core.eod_reporter.get_session_status", return_value=DEFAULT_SESSION), \
             patch("app.core.eod_reporter.get_eod_report", return_value=""), \
             patch("app.core.eod_reporter.send_daily_summary"), \
             patch("app.core.eod_reporter.send_simple_message", side_effect=msgs_sent.append), \
             patch.dict("sys.modules", {"app.signals.signal_analytics": MagicMock(signal_tracker=tracker)}):
            from app.core import eod_reporter
            eod_reporter.run_eod_report("2026-03-17")

        funnel_calls = [m for m in msgs_sent if "Signal funnel block content" in str(m)]
        assert len(funnel_calls) == 1

    # ------------------------------------------------------------------
    # 5. clear_session_cache() called after sending
    # ------------------------------------------------------------------
    def test_clear_session_cache_called(self):
        tracker = _make_tracker_mock()
        with patch("app.core.eod_reporter.get_session_status", return_value=DEFAULT_SESSION), \
             patch("app.core.eod_reporter.get_eod_report", return_value=""), \
             patch("app.core.eod_reporter.send_daily_summary"), \
             patch("app.core.eod_reporter.send_simple_message"), \
             patch.dict("sys.modules", {"app.signals.signal_analytics": MagicMock(signal_tracker=tracker)}):
            from app.core import eod_reporter
            eod_reporter.run_eod_report("2026-03-17")

        tracker.clear_session_cache.assert_called_once()

    # ------------------------------------------------------------------
    # 6. get_daily_summary() output printed to stdout
    # ------------------------------------------------------------------
    def test_daily_summary_printed_to_stdout(self, capsys):
        tracker = _make_tracker_mock(daily_summary="=== FULL SUMMARY OUTPUT ===")
        with patch("app.core.eod_reporter.get_session_status", return_value=DEFAULT_SESSION), \
             patch("app.core.eod_reporter.get_eod_report", return_value=""), \
             patch("app.core.eod_reporter.send_daily_summary"), \
             patch("app.core.eod_reporter.send_simple_message"), \
             patch.dict("sys.modules", {"app.signals.signal_analytics": MagicMock(signal_tracker=tracker)}):
            from app.core import eod_reporter
            eod_reporter.run_eod_report("2026-03-17")

        captured = capsys.readouterr()
        assert "=== FULL SUMMARY OUTPUT ===" in captured.out

    # ------------------------------------------------------------------
    # 7. Graceful degradation when signal_analytics is unavailable
    # ------------------------------------------------------------------
    def test_graceful_degradation_when_signal_analytics_missing(self):
        """Should not raise — just skips funnel block and logs warning."""
        import sys
        # Remove module from sys.modules to simulate ImportError path
        sa_key = "app.signals.signal_analytics"
        original = sys.modules.pop(sa_key, None)
        try:
            with patch("app.core.eod_reporter.get_session_status", return_value=DEFAULT_SESSION), \
                 patch("app.core.eod_reporter.get_eod_report", return_value=""), \
                 patch("app.core.eod_reporter.send_daily_summary"), \
                 patch("app.core.eod_reporter.send_simple_message"):
                from app.core import eod_reporter
                # Should complete without raising
                eod_reporter.run_eod_report("2026-03-17")
        except ImportError:
            pytest.fail("run_eod_report raised ImportError — graceful degradation broken")
        finally:
            if original is not None:
                sys.modules[sa_key] = original

    # ------------------------------------------------------------------
    # 8. Graceful degradation when get_session_status raises
    # ------------------------------------------------------------------
    def test_graceful_degradation_when_session_status_raises(self):
        """Should not propagate exception — logs error and continues."""
        tracker = _make_tracker_mock()
        try:
            with patch("app.core.eod_reporter.get_session_status", side_effect=Exception("DB down")), \
                 patch("app.core.eod_reporter.get_eod_report", return_value=""), \
                 patch("app.core.eod_reporter.send_daily_summary"), \
                 patch("app.core.eod_reporter.send_simple_message"), \
                 patch.dict("sys.modules", {"app.signals.signal_analytics": MagicMock(signal_tracker=tracker)}):
                from app.core import eod_reporter
                eod_reporter.run_eod_report("2026-03-17")
        except Exception as e:
            pytest.fail(f"run_eod_report propagated exception: {e}")
