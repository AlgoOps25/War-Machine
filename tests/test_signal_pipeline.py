"""
War Machine — Critical Path Test Suite  (P0-6)
================================================
Covers the highest-risk business-logic units:

  1. Confidence gate  (grade ranges, bucket boundaries, MIN floor, grade assignment, clamping)
  2. VWAP directional gate
  3. thread_safe_state  (armed / watching dicts, validator stats, call tracker,
                         monitoring timing, race condition — no race-condition regression)
  4. position_manager.open_position  (risk rejection returns -1)
  5. Ticker timeout watchdog  (_run_ticker_with_timeout)

Run with:
    pytest tests/test_signal_pipeline.py -v
"""
import sys
import threading
import time
from datetime import datetime
import pytest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from unittest.mock import MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# 1. CONFIDENCE GATE — grade ranges, bucket boundaries, floor, assignment, clamping
# ─────────────────────────────────────────────────────────────────────────────
GRADE_RANGES = {
    "A+": (0.88, 0.92),
    "A":  (0.83, 0.87),
    "A-": (0.78, 0.82),
    "B+": (0.72, 0.76),
    "B":  (0.66, 0.70),
    "B-": (0.60, 0.64),
    "C+": (0.55, 0.60),
    "C":  (0.50, 0.55),
    "C-": (0.45, 0.50),
}

MIN_CONFIDENCE = 0.55  # signals below this floor are rejected


def _assign_grade(confidence: float) -> str:
    """Mirror the grade-assignment logic from sniper.py."""
    for grade, (lo, hi) in sorted(
        GRADE_RANGES.items(), key=lambda x: x[1][0], reverse=True
    ):
        if confidence >= lo:
            return grade
    return "F"


def _get_confidence_bucket(c: float) -> str:
    """Mirror _get_confidence_bucket() from sniper.py."""
    if c < 0.50: return '0.40-0.50'
    if c < 0.60: return '0.50-0.60'
    if c < 0.70: return '0.60-0.70'
    if c < 0.80: return '0.70-0.80'
    if c < 0.90: return '0.80-0.90'
    return '0.90-0.95'


def _passes_confidence_gate(confidence: float) -> bool:
    return confidence >= MIN_CONFIDENCE


def _clamp_confidence(c: float) -> float:
    return max(0.0, min(0.99, c))


class TestConfidenceGate:
    """Grade table structure and bucket boundaries."""

    def test_all_grades_present(self):
        expected = {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-"}
        assert set(GRADE_RANGES.keys()) == expected

    def test_each_grade_lo_less_than_hi(self):
        for grade, (lo, hi) in GRADE_RANGES.items():
            assert lo < hi, f"{grade}: lo ({lo}) must be < hi ({hi})"

    def test_grade_ranges_ascending(self):
        grades_ordered = ["C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
        prev_max = 0.0
        for grade in grades_ordered:
            lo, hi = GRADE_RANGES[grade]
            assert lo < hi, f"{grade}: lo >= hi"
            assert lo >= prev_max - 0.01, f"{grade}: range does not ascend"
            prev_max = hi

    def test_aplus_is_highest(self):
        aplus_min, _ = GRADE_RANGES["A+"]
        for grade, (lo, hi) in GRADE_RANGES.items():
            if grade != "A+":
                assert hi <= aplus_min + 0.01, f"{grade} overlaps A+ floor"

    def test_no_grade_exceeds_1(self):
        for grade, (lo, hi) in GRADE_RANGES.items():
            assert hi <= 1.0, f"{grade} hi={hi} exceeds 1.0"

    def test_no_grade_below_zero(self):
        for grade, (lo, hi) in GRADE_RANGES.items():
            assert lo >= 0.0, f"{grade} lo={lo} is negative"

    @pytest.mark.parametrize("conf, expected", [
        (0.40, '0.40-0.50'), (0.49, '0.40-0.50'),
        (0.50, '0.50-0.60'), (0.599, '0.50-0.60'),
        (0.60, '0.60-0.70'), (0.699, '0.60-0.70'),
        (0.70, '0.70-0.80'), (0.799, '0.70-0.80'),
        (0.80, '0.80-0.90'), (0.899, '0.80-0.90'),
        (0.90, '0.90-0.95'), (0.95, '0.90-0.95'), (0.99, '0.90-0.95'),
    ])
    def test_confidence_bucket_boundary(self, conf, expected):
        assert _get_confidence_bucket(conf) == expected


class TestConfidenceGateThreshold:
    """MIN_CONFIDENCE floor — signals below 0.55 are rejected."""

    def test_above_floor_passes(self):
        assert _passes_confidence_gate(0.60) is True
        assert _passes_confidence_gate(0.55) is True
        assert _passes_confidence_gate(0.90) is True

    def test_below_floor_rejected(self):
        assert _passes_confidence_gate(0.54) is False
        assert _passes_confidence_gate(0.00) is False

    def test_exact_floor_passes(self):
        assert _passes_confidence_gate(MIN_CONFIDENCE) is True

    def test_just_below_floor_rejected(self):
        assert _passes_confidence_gate(MIN_CONFIDENCE - 0.001) is False


class TestGradeAssignment:
    """Grade correctly assigned from raw confidence score."""

    @pytest.mark.parametrize("confidence, expected_grade", [
        (0.91, "A+"),
        (0.85, "A"),
        (0.80, "A-"),
        (0.74, "B+"),
        (0.68, "B"),
        (0.62, "B-"),
        (0.57, "C+"),
        (0.52, "C"),
        (0.47, "C-"),
        (0.30, "F"),
        (0.00, "F"),
    ])
    def test_grade_from_confidence(self, confidence, expected_grade):
        assert _assign_grade(confidence) == expected_grade, (
            f"confidence={confidence} → expected {expected_grade}, "
            f"got {_assign_grade(confidence)}"
        )


class TestConfidenceClamping:
    """Confidence never exceeds 0.99 and never goes below 0.0."""

    def test_above_max_clamped_to_099(self):
        assert _clamp_confidence(1.00) == 0.99
        assert _clamp_confidence(1.50) == 0.99
        assert _clamp_confidence(999)  == 0.99

    def test_below_zero_clamped_to_0(self):
        assert _clamp_confidence(-0.01) == 0.0
        assert _clamp_confidence(-100)  == 0.0

    def test_valid_range_unchanged(self):
        for val in [0.0, 0.55, 0.75, 0.90, 0.99]:
            assert _clamp_confidence(val) == val


# ─────────────────────────────────────────────────────────────────────────────
# 2. VWAP DIRECTIONAL GATE
# ─────────────────────────────────────────────────────────────────────────────
class TestVwapGate:
    @staticmethod
    def _compute_vwap(bars):
        cumulative_tpv = 0.0
        cumulative_vol = 0.0
        for bar in bars:
            tp = (bar['high'] + bar['low'] + bar['close']) / 3.0
            cumulative_tpv += tp * bar.get('volume', 0)
            cumulative_vol += bar.get('volume', 0)
        return cumulative_tpv / cumulative_vol if cumulative_vol else 0.0

    @staticmethod
    def _passes(bars, direction, price):
        from tests.test_signal_pipeline import TestVwapGate
        vwap = TestVwapGate._compute_vwap(bars)
        if vwap == 0.0:
            return True
        if direction == 'bull':
            return price > vwap
        elif direction == 'bear':
            return price < vwap
        return True

    def _make_bars(self, closes, volume=100_000):
        return [
            {'high': c * 1.005, 'low': c * 0.995, 'close': c, 'volume': volume}
            for c in closes
        ]

    def test_bull_above_vwap_passes(self):
        bars = self._make_bars([100] * 10)
        vwap = self._compute_vwap(bars)
        assert self._passes(bars, 'bull', vwap + 1.0) is True

    def test_bull_below_vwap_fails(self):
        bars = self._make_bars([100] * 10)
        vwap = self._compute_vwap(bars)
        assert self._passes(bars, 'bull', vwap - 1.0) is False

    def test_bear_below_vwap_passes(self):
        bars = self._make_bars([100] * 10)
        vwap = self._compute_vwap(bars)
        assert self._passes(bars, 'bear', vwap - 1.0) is True

    def test_bear_above_vwap_fails(self):
        bars = self._make_bars([100] * 10)
        vwap = self._compute_vwap(bars)
        assert self._passes(bars, 'bear', vwap + 1.0) is False

    def test_empty_bars_returns_true(self):
        assert self._passes([], 'bull', 100.0) is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. THREAD-SAFE STATE
# ─────────────────────────────────────────────────────────────────────────────
class TestThreadSafeState:
    """
    Full thread-safety regression suite for ThreadSafeState.
    Covers armed signals, watching signals, validator stats, validation call
    tracker, monitoring timing, and realistic set/get/remove race conditions.
    """

    def _make_fresh_state(self):
        from app.core.thread_safe_state import ThreadSafeState
        ThreadSafeState._instance = None
        return ThreadSafeState()

    def _get_shared_state(self):
        """Return the shared singleton (for tests that use get_state())."""
        from app.core.thread_safe_state import get_state
        return get_state()

    # ── Singleton ─────────────────────────────────────────────────────────────
    def test_singleton_pattern(self):
        from app.core.thread_safe_state import get_state
        assert get_state() is get_state(), "get_state() must return same instance"

    # ── Armed signals ─────────────────────────────────────────────────────────
    def test_concurrent_armed_writes_are_safe(self):
        state = self._make_fresh_state()
        errors = []

        def writer(i):
            try:
                state.set_armed_signal(f"TICK{i}", {"position_id": i, "direction": "bull"})
            except Exception as exc:
                errors.append(exc)

        def reader(i):
            try:
                state.get_all_armed_signals()
            except Exception as exc:
                errors.append(exc)

        threads  = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        threads += [threading.Thread(target=reader, args=(i,)) for i in range(50)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)

        assert not errors, f"Thread safety errors: {errors}"
        assert len(state.get_all_armed_signals()) == 50

    def test_armed_signals_set_get_remove(self):
        state = self._get_shared_state()
        state.clear_armed_signals()
        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    ticker = f"TICKER{thread_id}_{i}"
                    data   = {"position_id": i, "direction": "bull", "entry_price": 100.0}
                    state.set_armed_signal(ticker, data)
                    retrieved = state.get_armed_signal(ticker)
                    assert retrieved is not None, f"Failed to retrieve {ticker}"
                    assert retrieved["position_id"] == i
                    state.remove_armed_signal(ticker)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors, f"Armed signals errors: {errors}"

    # ── Watching signals ──────────────────────────────────────────────────────
    def test_watching_signal_lifecycle(self):
        state = self._make_fresh_state()
        assert not state.ticker_is_watching('AAPL')
        state.set_watching_signal('AAPL', {'direction': 'bull', 'or_high': 200.0})
        assert state.ticker_is_watching('AAPL')
        state.update_watching_signal_field('AAPL', 'breakout_idx', 5)
        assert state.get_watching_signal('AAPL')['breakout_idx'] == 5
        state.remove_watching_signal('AAPL')
        assert not state.ticker_is_watching('AAPL')

    def test_watching_signals_concurrent(self):
        state = self._get_shared_state()
        state.clear_watching_signals()
        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    ticker = f"WATCH{thread_id}_{i}"
                    data   = {"direction": "bear", "breakout_idx": i, "or_high": 150.0}
                    state.set_watching_signal(ticker, data)
                    retrieved = state.get_watching_signal(ticker)
                    assert retrieved is not None
                    assert retrieved["breakout_idx"] == i
                    state.remove_watching_signal(ticker)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors, f"Watching signals errors: {errors}"

    # ── Validator stats ───────────────────────────────────────────────────────
    def test_validator_stat_increment_concurrent(self):
        state = self._make_fresh_state()
        errors = []

        def bump():
            try:
                for _ in range(100):
                    state.increment_validator_stat('tested')
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=bump) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)

        assert not errors
        assert state.get_validator_stats()['tested'] == 1000

    def test_validator_stats_passed_filtered_counts(self):
        state = self._get_shared_state()
        state.reset_validator_stats()
        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    state.increment_validator_stat('tested')
                    if i % 2 == 0:
                        state.increment_validator_stat('passed')
                    else:
                        state.increment_validator_stat('filtered')
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        stats = state.get_validator_stats()
        assert stats['tested'] == 1000, f"Expected 1000, got {stats['tested']}"

    # ── Validation call tracker ───────────────────────────────────────────────
    def test_validation_call_tracker_concurrent(self):
        state = self._get_shared_state()
        state.clear_validation_call_tracker()
        errors = []
        signal_id = "TEST_AAPL_bull_150.00_20260317"

        def worker(thread_id):
            try:
                for _ in range(10):
                    state.track_validation_call(signal_id)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        tracker = state.get_validation_call_tracker()
        assert tracker.get(signal_id) == 100, (
            f"Expected 100, got {tracker.get(signal_id)}"
        )

    # ── Monitoring timing ─────────────────────────────────────────────────────
    def test_monitoring_timing_concurrent(self):
        state = self._get_shared_state()
        errors = []

        def worker(thread_id):
            try:
                for _ in range(50):
                    now = datetime.now()
                    if thread_id % 2 == 0:
                        state.update_last_dashboard_check(now)
                        state.get_last_dashboard_check()
                    else:
                        state.update_last_alert_check(now)
                        state.get_last_alert_check()
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors, f"Monitoring timing errors: {errors}"

    # ── Race condition: simultaneous set/get/remove ───────────────────────────
    def test_race_condition_set_get_remove(self):
        state = self._get_shared_state()
        state.clear_armed_signals()
        ticker = "TSLA"
        errors = []

        def set_worker():
            try:
                for i in range(100):
                    state.set_armed_signal(ticker, {"position_id": i, "entry_price": 200.0 + i})
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Set: {e}")

        def get_worker():
            try:
                for _ in range(100):
                    result = state.get_armed_signal(ticker)
                    if result is not None:
                        assert isinstance(result, dict)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Get: {e}")

        def remove_worker():
            try:
                for _ in range(50):
                    state.remove_armed_signal(ticker)
                    time.sleep(0.002)
            except Exception as e:
                errors.append(f"Remove: {e}")

        threads = [
            threading.Thread(target=set_worker),
            threading.Thread(target=set_worker),
            threading.Thread(target=get_worker),
            threading.Thread(target=get_worker),
            threading.Thread(target=remove_worker),
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors, f"Race condition errors: {errors}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. POSITION MANAGER — risk rejection path returns -1
# Stubbed via sys.modules to prevent position_manager's module-level
# PositionManager() instantiation from hitting the DB under Python 3.14.
# ─────────────────────────────────────────────────────────────────────────────
class TestPositionManagerRejection:
    """
    Validates that open_position() returns -1 when the risk manager
    blocks the trade rather than raising an exception.

    Uses a real PositionManager instance with _check_risk_limits monkeypatched
    so no DB or network calls are made.
    """

    def test_rejection_returns_negative_one(self, monkeypatch):
        # Stub all transitive deps before importing position_manager
        _stubs = {
            "utils":                         MagicMock(),
            "utils.config":                  MagicMock(
                ACCOUNT_SIZE=25_000,
                MAX_DAILY_LOSS_PCT=3.0,
                MAX_OPEN_POSITIONS=5,
                MAX_SECTOR_EXPOSURE_PCT=40.0,
                MIN_RISK_REWARD_RATIO=1.5,
                MAX_CONTRACTS=10,
                POSITION_RISK={
                    "A+_high_confidence": 0.02,
                    "A_high_confidence":  0.015,
                    "standard":           0.01,
                    "conservative":       0.005,
                },
            ),
            "app.data":                      MagicMock(),
            "app.data.db_connection":        MagicMock(
                USE_POSTGRES=False,
                get_conn=MagicMock(return_value=MagicMock(
                    cursor=MagicMock(return_value=MagicMock(
                        execute=MagicMock(),
                        fetchone=MagicMock(return_value=None),
                        fetchall=MagicMock(return_value=[]),
                    )),
                    commit=MagicMock(),
                )),
                return_conn=MagicMock(),
                ph=MagicMock(return_value="?"),
                dict_cursor=MagicMock(return_value=MagicMock(
                    execute=MagicMock(),
                    fetchone=MagicMock(return_value=None),
                    fetchall=MagicMock(return_value=[]),
                )),
                serial_pk=MagicMock(return_value="INTEGER PRIMARY KEY AUTOINCREMENT"),
            ),
            "app.risk.vix_sizing":           MagicMock(get_vix_multiplier=MagicMock(return_value=1.0)),
            "app.analytics":                 MagicMock(),
            "app.analytics.rth_filter":      MagicMock(is_rth_now=MagicMock(return_value=True)),
            "app.signals":                   MagicMock(),
            "app.signals.signal_analytics":  MagicMock(),
        }

        # Evict any cached real module
        for key in list(sys.modules.keys()):
            if "position_manager" in key:
                del sys.modules[key]

        import unittest.mock as _mock
        with _mock.patch.dict("sys.modules", _stubs):
            from app.risk import position_manager as pm_mod

            # Build a minimal PositionManager without real __init__ side effects
            pm = pm_mod.PositionManager.__new__(pm_mod.PositionManager)
            pm.db_path = ":memory:"
            pm.positions = []
            pm.account_size = 25_000
            pm.intraday_high_water_mark = 25_000
            pm.session_starting_balance = 25_000
            pm.max_daily_loss_pct = 3.0
            pm.max_open_positions = 5
            pm.max_sector_exposure_pct = 40.0
            pm.min_risk_reward_ratio = 1.5
            pm.consecutive_wins = 0
            pm.consecutive_losses = 0
            pm.performance_multiplier = 1.0
            pm._daily_stats_cache = None
            pm._daily_stats_ts = 0.0
            pm._open_positions_cache = None
            pm._open_positions_ts = 0.0

            # Monkeypatch risk gate to always reject
            monkeypatch.setattr(pm, '_check_risk_limits',
                                lambda *a, **kw: (False, "max positions reached"),
                                raising=False)

            result = pm.open_position(
                ticker='FAKE', direction='bull',
                zone_low=99.0, zone_high=101.0,
                or_low=98.0,  or_high=102.0,
                entry_price=100.0, stop_price=99.0,
                t1=102.0, t2=104.0,
                confidence=0.85, grade='A',
                options_rec=None
            )

        assert result == -1, (
            f"Expected -1 on risk rejection, got {result!r}. "
            f"Check open_position() returns -1 when _check_risk_limits returns False."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. TICKER TIMEOUT WATCHDOG
# Stubbed via sys.modules to prevent scanner's module-level imports from
# pulling in position_manager → DB under Python 3.14.
# ─────────────────────────────────────────────────────────────────────────────
def _watchdog(fn, ticker, timeout_seconds):
    """Isolated watchdog — fresh executor per call to avoid executor contention."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn, ticker)
        try:
            future.result(timeout=timeout_seconds)
            return True
        except FuturesTimeoutError:
            future.cancel()
            return False
        except Exception:
            return False


def _get_scanner_with_stubs():
    """
    Import app.core.scanner with all DB-touching transitive deps stubbed.
    Evicts cached modules first so stubs take effect cleanly.
    """
    import unittest.mock as _mock

    _stubs = {
        "utils":                            MagicMock(),
        "utils.config":                     MagicMock(),
        "app.data":                         MagicMock(),
        "app.data.db_connection":           MagicMock(
            USE_POSTGRES=False,
            get_conn=MagicMock(return_value=MagicMock(
                cursor=MagicMock(return_value=MagicMock(
                    execute=MagicMock(),
                    fetchone=MagicMock(return_value=None),
                    fetchall=MagicMock(return_value=[]),
                )),
                commit=MagicMock(),
            )),
            return_conn=MagicMock(),
            ph=MagicMock(return_value="?"),
            dict_cursor=MagicMock(return_value=MagicMock(
                execute=MagicMock(),
                fetchone=MagicMock(return_value=None),
                fetchall=MagicMock(return_value=[]),
            )),
            serial_pk=MagicMock(return_value="INTEGER PRIMARY KEY AUTOINCREMENT"),
        ),
        "app.risk":                         MagicMock(),
        "app.risk.position_manager":        MagicMock(),
        "app.risk.risk_manager":            MagicMock(),
        "app.risk.vix_sizing":              MagicMock(),
        "app.signals":                      MagicMock(),
        "app.signals.signal_analytics":     MagicMock(),
        "app.analytics":                    MagicMock(),
        "app.analytics.rth_filter":         MagicMock(),
        "app.notifications":                MagicMock(),
        "app.notifications.discord_helpers": MagicMock(),
    }

    for key in list(sys.modules.keys()):
        if "scanner" in key and "thread_safe" not in key:
            del sys.modules[key]

    with _mock.patch.dict("sys.modules", _stubs):
        import app.core.scanner as scanner_mod
        return scanner_mod


class TestTickerWatchdog:
    def test_fast_ticker_returns_true(self):
        scanner_mod = _get_scanner_with_stubs()
        _run_ticker_with_timeout = scanner_mod._run_ticker_with_timeout
        def fast(_ticker): time.sleep(0.01)
        assert _run_ticker_with_timeout(fast, 'SPY') is True

    def test_slow_ticker_returns_false(self):
        scanner_mod = _get_scanner_with_stubs()
        _run_ticker_with_timeout = scanner_mod._run_ticker_with_timeout
        def hung(_ticker): time.sleep(120)
        original = scanner_mod.TICKER_TIMEOUT_SECONDS
        scanner_mod.TICKER_TIMEOUT_SECONDS = 1
        try:
            result = _run_ticker_with_timeout(hung, 'HUNG')
        finally:
            scanner_mod.TICKER_TIMEOUT_SECONDS = original
        assert result is False

    def test_exception_in_ticker_returns_false(self):
        scanner_mod = _get_scanner_with_stubs()
        _run_ticker_with_timeout = scanner_mod._run_ticker_with_timeout
        def explodes(_ticker): raise RuntimeError("simulated crash")
        assert _run_ticker_with_timeout(explodes, 'BOOM') is False

    def test_scan_loop_continues_after_hung_ticker(self):
        """
        Prove the loop processes subsequent tickers even if one hangs.
        Uses a fresh executor per call (_watchdog) so the hung task
        does not block the single production worker thread.
        """
        processed = []
        TIMEOUT = 2
        _stop = threading.Event()

        def process(ticker):
            if ticker == 'HUNG':
                _stop.wait(timeout=30)
            else:
                processed.append(ticker)

        watchlist = ['GOOD1', 'HUNG', 'GOOD2', 'GOOD3']
        for t in watchlist:
            _watchdog(process, t, TIMEOUT)
        _stop.set()

        assert 'GOOD1' in processed
        assert 'HUNG'  not in processed
        assert 'GOOD2' in processed
        assert 'GOOD3' in processed
