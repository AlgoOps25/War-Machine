"""
A/B Test — signal strategy A/B testing analytics.
Stub implementation: all methods are no-ops so sniper.py loads cleanly.
"""
import hashlib


class ABTest:
    """Tracks A/B test results for signal strategy comparisons."""

    # ── Default param values per variant ──────────────────────────────────
    _PARAM_DEFAULTS = {
        'volume_threshold': {'A': 1.5, 'B': 2.0},
        'min_confidence':   {'A': 0.65, 'B': 0.75},
    }

    def get_variant(self, ticker: str, param: str) -> str:
        """Deterministic variant assignment (A or B) based on ticker+param hash."""
        key = f"{ticker}:{param}"
        digest = int(hashlib.md5(key.encode()).hexdigest(), 16)
        return 'A' if digest % 2 == 0 else 'B'

    def get_param(self, ticker: str, param: str):
        """Return the param value for the variant assigned to *ticker*."""
        variant = self.get_variant(ticker, param)
        defaults = self._PARAM_DEFAULTS.get(param, {'A': None, 'B': None})
        return defaults.get(variant)

    def record_outcome(self, ticker: str, param: str, hit_target: bool, **kwargs):
        """Record a trade outcome for a ticker/param A/B pair. Stub."""
        pass

    def get_variant_stats(self, param: str, days_back: int = 30) -> dict:
        """Return per-variant stats dict. Stub returns zero-filled A/B structure."""
        empty = {'win_rate': 0.0, 'samples': 0, 'avg_pnl': 0.0}
        return {'A': dict(empty), 'B': dict(empty)}

    def get_ab_test_report(self, days_back: int = 30) -> str:
        """Return a human-readable A/B test report string."""
        return "[ABTest] No data — stub implementation."

    # ── Legacy / compat methods ──────────────────────────────────────────

    def record_result(self, variant: str, outcome: str, **kwargs):
        pass

    def get_summary(self) -> dict:
        return {}

    def print_report(self):
        pass

    def reset(self):
        pass


# Module-level singleton
ab_test = ABTest()
