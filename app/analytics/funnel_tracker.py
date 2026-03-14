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

    # ── Per-stage log helpers ────────────────────────────────────────────────

    def log_screened(self, ticker: str, passed: bool = True, **kwargs):
        """Log a ticker through the SCREENED stage."""
        pass

    def log_bos(self, ticker: str, passed: bool = True, **kwargs):
        """Log a ticker through the BOS stage."""
        pass

    def log_fvg(self, ticker: str, passed: bool = True, confidence: float = 0.0, reason: str = "", **kwargs):
        """Log a ticker through the FVG stage."""
        pass

    def log_validator(self, ticker: str, passed: bool = True, confidence: float = 0.0, reason: str = "", **kwargs):
        """Log a ticker through the VALIDATOR stage."""
        pass

    def log_armed(self, ticker: str, confidence: float = 0.0, **kwargs):
        """Log a ticker reaching the ARMED stage."""
        pass

    def log_fired(self, ticker: str, confidence: float = 0.0, **kwargs):
        """Log a ticker reaching the FIRED stage."""
        pass

    def log_filled(self, ticker: str, **kwargs):
        """Log a ticker reaching the FILLED stage."""
        pass

    # ── Reporting helpers ────────────────────────────────────────────────────

    def get_stage_conversion(self, stage: str) -> dict:
        """Return conversion stats for *stage*. Stub returns zero-filled dict."""
        return {"total": 0, "passed": 0, "conversion_rate": 0.0}

    def get_rejection_reasons(self, limit: int = 10) -> list:
        """Return list of (reason, count) tuples for top rejection reasons."""
        return []

    def get_daily_summary(self) -> dict:
        return {}

    def get_daily_report(self) -> str:
        """Return a human-readable daily funnel report string."""
        return "[FunnelTracker] No data — stub implementation."

    def print_eod_report(self):
        pass

    def reset(self):
        pass


# Module-level singleton
funnel_tracker = FunnelTracker()


# ── Module-level convenience wrappers ────────────────────────────────────────

def log_screened(ticker: str, **kwargs):
    """Convenience wrapper — funnel_tracker.log_screened()."""
    funnel_tracker.log_screened(ticker, **kwargs)


def log_bos(ticker: str, **kwargs):
    """Convenience wrapper — funnel_tracker.log_bos()."""
    funnel_tracker.log_bos(ticker, **kwargs)


def log_fvg(ticker: str, **kwargs):
    """Convenience wrapper — funnel_tracker.log_fvg()."""
    funnel_tracker.log_fvg(ticker, **kwargs)


def log_validator(ticker: str, **kwargs):
    """Convenience wrapper — funnel_tracker.log_validator()."""
    funnel_tracker.log_validator(ticker, **kwargs)


def log_armed(ticker: str, **kwargs):
    """Convenience wrapper — funnel_tracker.log_armed()."""
    funnel_tracker.log_armed(ticker, **kwargs)


def log_fired(ticker: str, **kwargs):
    """Convenience wrapper — funnel_tracker.log_fired()."""
    funnel_tracker.log_fired(ticker, **kwargs)


def log_filled(ticker: str, **kwargs):
    """Convenience wrapper — funnel_tracker.log_filled()."""
    funnel_tracker.log_filled(ticker, **kwargs)
