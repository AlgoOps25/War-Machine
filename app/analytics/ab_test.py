# ab_test.py — logic lives in app/analytics/ab_test_framework.py
# This shim keeps all imports from app.analytics.ab_test working.
# Falls back to a lightweight in-memory stub when the DB is unavailable
# (e.g. CI) so tests can run without a live PostgreSQL connection.

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Optional


class _InMemoryABTest:
    """Pure in-memory fallback A/B tester — no DB required."""

    EXPERIMENTS = {
        'volume_threshold':   {'A': 2.0,  'B': 3.0},
        'min_confidence':     {'A': 60,   'B': 70},
        'cooldown_minutes':   {'A': 10,   'B': 15},
        'atr_stop_multiplier':{'A': 2.0,  'B': 2.5},
        'lookback_bars':      {'A': 10,   'B': 15},
    }

    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._outcomes: Dict[str, list] = defaultdict(list)

    def _session(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def get_variant(self, ticker: str, param: str) -> str:
        key = f"{ticker}_{param}_{self._session()}"
        if key not in self._cache:
            h = hashlib.md5(key.encode()).hexdigest()
            self._cache[key] = 'A' if int(h[:8], 16) % 2 == 0 else 'B'
        return self._cache[key]

    def get_param(self, ticker: str, param: str) -> Any:
        if param not in self.EXPERIMENTS:
            return None
        variant = self.get_variant(ticker, param)
        return self.EXPERIMENTS[param][variant]

    def record_outcome(self, ticker: str, param: str, hit_target: bool):
        if param not in self.EXPERIMENTS:
            return
        variant = self.get_variant(ticker, param)
        self._outcomes[f"{param}_{variant}"].append(int(hit_target))

    def get_variant_stats(self, param: str, days_back: int = 30) -> Dict:
        stats = {}
        for variant in ('A', 'B'):
            results = self._outcomes.get(f"{param}_{variant}", [])
            samples = len(results)
            wins = sum(results)
            stats[variant] = {
                'samples': samples,
                'wins': wins,
                'win_rate': round((wins / samples * 100) if samples > 0 else 0.0, 1),
            }
        return stats

    def check_winners(self, days_back: int = 30) -> Dict:
        return {}

    def get_ab_test_report(self, days_back: int = 30) -> str:
        lines = ["=" * 40, "A/B TEST REPORT (in-memory)", "=" * 40]
        for param in self.EXPERIMENTS:
            stats = self.get_variant_stats(param, days_back)
            lines.append(
                f"{param}: A={stats['A']['win_rate']:.1f}% (n={stats['A']['samples']})  "
                f"B={stats['B']['win_rate']:.1f}% (n={stats['B']['samples']})"
            )
        lines.append("=" * 40)
        return "\n".join(lines)

    # Legacy compat
    def record_result(self, *a, **kw): pass
    def get_summary(self) -> dict: return {}
    def print_report(self): pass
    def reset(self): pass


try:
    from app.analytics.ab_test_framework import (
        ABTestFramework,
        ab_test_framework,
        run_ab_test,
    )
    ab_test = ab_test_framework
except Exception:
    ABTestFramework   = _InMemoryABTest
    ab_test_framework = _InMemoryABTest()
    ab_test           = ab_test_framework
    def run_ab_test(*a, **kw): return {}
