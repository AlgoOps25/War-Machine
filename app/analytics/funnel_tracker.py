# funnel_tracker.py — logic lives in app/analytics/funnel_analytics.py
# This shim keeps all imports from app.analytics.funnel_tracker working.
# Falls back to a lightweight in-memory stub when the DB is unavailable
# (e.g. CI) so tests can run without a live PostgreSQL connection.

from collections import defaultdict
from typing import Dict, List, Optional, Tuple


class _InMemoryFunnelTracker:
    """Pure in-memory fallback — no DB required."""

    STAGES = ['SCREENED', 'BOS', 'FVG', 'VALIDATOR', 'ARMED', 'FIRED', 'FILLED']

    def __init__(self):
        self._counters: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {'total': 0, 'passed': 0, 'failed': 0}
        )
        self._rejections: List[Tuple[str, int]] = []
        self._rejection_counts: Dict[str, int] = defaultdict(int)

    def record_stage(
        self,
        ticker: str,
        stage: str,
        passed: bool,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        signal_id: Optional[str] = None,
    ):
        c = self._counters[stage]
        c['total'] += 1
        if passed:
            c['passed'] += 1
        else:
            c['failed'] += 1
            if reason:
                self._rejection_counts[reason] += 1

    def get_stage_conversion(self, stage: str, session: Optional[str] = None) -> Dict:
        c = self._counters.get(stage, {'total': 0, 'passed': 0, 'failed': 0})
        total = c['total']
        passed = c['passed']
        failed = c['failed']
        rate = round((passed / total * 100) if total > 0 else 0.0, 1)
        return {'total': total, 'passed': passed, 'failed': failed, 'conversion_rate': rate}

    def get_rejection_reasons(self, session: Optional[str] = None, limit: int = 10) -> List:
        sorted_reasons = sorted(
            self._rejection_counts.items(), key=lambda x: x[1], reverse=True
        )
        return sorted_reasons[:limit]

    def get_daily_report(self, session: Optional[str] = None) -> str:
        lines = ["=" * 40, "SIGNAL FUNNEL REPORT (in-memory)", "=" * 40]
        for stage in self.STAGES:
            stats = self.get_stage_conversion(stage)
            if stats['total'] > 0:
                lines.append(
                    f"{stage:<12} total={stats['total']}  "
                    f"passed={stats['passed']}  "
                    f"conv={stats['conversion_rate']:.1f}%"
                )
        lines.append("=" * 40)
        return "\n".join(lines) if len(lines) > 3 else "\n".join(lines + ["  No data"])

    def get_hourly_breakdown(self, session: Optional[str] = None) -> Dict:
        return {}


try:
    from app.analytics.funnel_analytics import (
        FunnelTracker,
        funnel_tracker,
        record_scan,
        get_funnel_stats,
    )
except Exception:
    FunnelTracker  = _InMemoryFunnelTracker
    funnel_tracker = _InMemoryFunnelTracker()
    def record_scan(*a, **kw): pass
    def get_funnel_stats(*a, **kw): return {}


# Convenience log_* helpers — always available
def log_screened(ticker: str, passed: bool = True, reason: str = None):
    funnel_tracker.record_stage(ticker, 'SCREENED', passed, reason)

def log_bos(ticker: str, passed: bool = True, reason: str = None):
    funnel_tracker.record_stage(ticker, 'BOS', passed, reason)

def log_fvg(ticker: str, passed: bool = True, reason: str = None, confidence: float = None):
    funnel_tracker.record_stage(ticker, 'FVG', passed, reason, confidence)

def log_validator(ticker: str, passed: bool = True, reason: str = None, confidence: float = None):
    funnel_tracker.record_stage(ticker, 'VALIDATOR', passed, reason, confidence)

def log_armed(ticker: str, passed: bool = True, confidence: float = None):
    funnel_tracker.record_stage(ticker, 'ARMED', passed, None, confidence)

def log_fired(ticker: str, passed: bool = True, confidence: float = None):
    funnel_tracker.record_stage(ticker, 'FIRED', passed, None, confidence)

def log_filled(ticker: str, passed: bool = True):
    funnel_tracker.record_stage(ticker, 'FILLED', passed)
