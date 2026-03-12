"""
Funnel Tracker — outcome tracking for watchlist funnel analytics.
Stub implementation: all methods are no-ops so sniper.py loads cleanly.
Full implementation can be added later without breaking any callers.
"""


class FunnelTracker:
    """Tracks watchlist funnel stage outcomes for analytics."""

    def record_outcome(self, ticker: str, stage: str, outcome: str, **kwargs):
        pass

    def record_signal(self, ticker: str, signal_type: str, **kwargs):
        pass

    def record_filter(self, ticker: str, filter_name: str, reason: str = "", **kwargs):
        pass

    def get_daily_summary(self) -> dict:
        return {}

    def print_eod_report(self):
        pass

    def reset(self):
        pass


# Module-level singleton
funnel_tracker = FunnelTracker()
