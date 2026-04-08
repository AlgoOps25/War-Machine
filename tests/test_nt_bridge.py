"""
tests/test_nt_bridge.py

Unit tests for app.ninjatrader.nt_bridge — SignalEngine and NTBarData.
No network I/O. All tests run offline using mock NTBarData objects.
"""

import pytest
from datetime import datetime
from app.ninjatrader.nt_bridge import NTBarData, NTSignal, SignalEngine, Direction


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_bar(
    close=18200.0,
    cum_delta=100.0,
    vwap=18190.0,
    poc=18180.0,
    # VA window is tight (18150–18195) so close≥18200 is OUTSIDE — full confidence.
    # Tests that explicitly want inside-VA behaviour pass their own vah/val.
    vah=18195.0,
    val=18150.0,
    open_=18195.0,
    high=18210.0,
    low=18185.0,
    volume=1000,
    symbol="NQ JUN26",
) -> NTBarData:
    return NTBarData(
        symbol    = symbol,
        timestamp = datetime(2026, 4, 8, 9, 35, 0),
        open      = open_,
        high      = high,
        low       = low,
        close     = close,
        volume    = volume,
        cum_delta = cum_delta,
        vwap      = vwap,
        poc       = poc,
        vah       = vah,
        val       = val,
    )


# ── NTBarData tests ────────────────────────────────────────────────────────────

class TestNTBarData:
    def test_from_dict_parses_correctly(self):
        data = {
            "symbol": "NQ JUN26", "timestamp": "2026-04-08T09:35:00",
            "open": "18200.25", "high": "18215.50", "low": "18195.00",
            "close": "18210.75", "volume": "1842",
            "cum_delta": "312.0", "vwap": "18205.10",
            "poc": "18200.00", "vah": "18220.00", "val": "18185.00",
        }
        bar = NTBarData.from_dict(data)
        assert bar.symbol    == "NQ JUN26"
        assert bar.close     == pytest.approx(18210.75)
        assert bar.cum_delta == pytest.approx(312.0)
        assert bar.volume    == 1842

    def test_from_dict_raises_on_missing_key(self):
        with pytest.raises(KeyError):
            NTBarData.from_dict({"symbol": "NQ JUN26"})  # missing all other fields


# ── SignalEngine tests ─────────────────────────────────────────────────────────

class TestSignalEngineInit:
    def test_first_bar_returns_flat(self):
        engine = SignalEngine()
        bar    = make_bar()
        signal = engine.evaluate(bar)
        assert signal.direction == Direction.FLAT
        assert signal.confidence == 0.0
        assert "Initializing" in signal.reason


class TestBullishDivergence:
    def test_bullish_divergence_above_poc_above_vwap_returns_buy(self):
        """
        Price down, delta up, above POC, above VWAP, outside VA → BUY divergence @ 0.85.
        VA window (val=18150, vah=18195) is below close (18195–18200) so
        both bars sit outside the Value Area — full confidence applies.
        """
        engine = SignalEngine()
        bar1   = make_bar(close=18200.0, cum_delta=50.0,  vwap=18190.0, poc=18180.0,
                          vah=18195.0, val=18150.0)
        bar2   = make_bar(close=18196.0, cum_delta=120.0, vwap=18190.0, poc=18180.0,
                          vah=18195.0, val=18150.0)
        engine.evaluate(bar1)
        signal = engine.evaluate(bar2)
        assert signal.direction  == Direction.BUY
        assert signal.confidence == pytest.approx(0.85)
        assert "divergence" in signal.reason.lower()

    def test_bullish_divergence_below_poc_returns_flat(self):
        """Bullish divergence but price below POC — layers conflict → not BUY."""
        engine = SignalEngine()
        bar1   = make_bar(close=18170.0, cum_delta=50.0,  vwap=18190.0, poc=18180.0,
                          vah=18165.0, val=18130.0)
        bar2   = make_bar(close=18165.0, cum_delta=120.0, vwap=18190.0, poc=18180.0,
                          vah=18162.0, val=18130.0)
        engine.evaluate(bar1)
        signal = engine.evaluate(bar2)
        assert signal.direction != Direction.BUY


class TestBearishDivergence:
    def test_bearish_divergence_below_poc_below_vwap_returns_sell(self):
        """
        Price up, delta down, below POC, below VWAP, outside VA → SELL divergence @ 0.85.
        VA window (val=18120, vah=18158) keeps close (18160–18165) outside VA.
        """
        engine = SignalEngine()
        bar1   = make_bar(close=18160.0, cum_delta=200.0, vwap=18190.0, poc=18180.0,
                          vah=18158.0, val=18120.0)
        bar2   = make_bar(close=18165.0, cum_delta=80.0,  vwap=18190.0, poc=18180.0,
                          vah=18158.0, val=18120.0)
        engine.evaluate(bar1)
        signal = engine.evaluate(bar2)
        assert signal.direction  == Direction.SELL
        assert signal.confidence == pytest.approx(0.85)
        assert "divergence" in signal.reason.lower()

    def test_bearish_divergence_above_poc_returns_flat(self):
        """Bearish divergence but price above POC — layers conflict → not SELL."""
        engine = SignalEngine()
        bar1   = make_bar(close=18200.0, cum_delta=200.0, vwap=18190.0, poc=18180.0,
                          vah=18195.0, val=18150.0)
        bar2   = make_bar(close=18205.0, cum_delta=80.0,  vwap=18190.0, poc=18180.0,
                          vah=18195.0, val=18150.0)
        engine.evaluate(bar1)
        signal = engine.evaluate(bar2)
        assert signal.direction != Direction.SELL


class TestAgreementSignals:
    def test_agreement_buy_above_poc_above_vwap(self):
        """
        Price up + delta up, above POC + above VWAP, outside VA → BUY @ 0.70.
        vah=18195 keeps close=18200/18210 outside the Value Area.
        """
        engine = SignalEngine()
        bar1   = make_bar(close=18200.0, cum_delta=100.0, vwap=18190.0, poc=18180.0,
                          vah=18195.0, val=18150.0)
        bar2   = make_bar(close=18210.0, cum_delta=180.0, vwap=18190.0, poc=18180.0,
                          vah=18195.0, val=18150.0)
        engine.evaluate(bar1)
        signal = engine.evaluate(bar2)
        assert signal.direction  == Direction.BUY
        assert signal.confidence == pytest.approx(0.70)

    def test_agreement_sell_below_poc_below_vwap(self):
        """
        Price down + delta down, below POC + below VWAP, outside VA → SELL @ 0.70.
        vah=18145 keeps close=18150/18160 outside the Value Area.
        """
        engine = SignalEngine()
        bar1   = make_bar(close=18160.0, cum_delta=100.0, vwap=18190.0, poc=18180.0,
                          vah=18145.0, val=18100.0)
        bar2   = make_bar(close=18150.0, cum_delta=40.0,  vwap=18190.0, poc=18180.0,
                          vah=18145.0, val=18100.0)
        engine.evaluate(bar1)
        signal = engine.evaluate(bar2)
        assert signal.direction  == Direction.SELL
        assert signal.confidence == pytest.approx(0.70)


class TestValueAreaConfidenceReduction:
    def test_inside_value_area_reduces_confidence(self):
        """Signals inside Value Area get 0.6x confidence multiplier."""
        engine = SignalEngine()
        # Price inside VA (val=18150, vah=18250) — agreement BUY signal
        bar1   = make_bar(close=18200.0, cum_delta=100.0, vwap=18190.0, poc=18180.0,
                          vah=18250.0, val=18150.0)
        bar2   = make_bar(close=18210.0, cum_delta=180.0, vwap=18190.0, poc=18180.0,
                          vah=18250.0, val=18150.0)
        engine.evaluate(bar1)
        signal = engine.evaluate(bar2)
        assert signal.direction == Direction.BUY
        assert signal.confidence == pytest.approx(0.70 * 0.6, abs=0.01)

    def test_outside_value_area_full_confidence(self):
        """Signals outside Value Area keep full confidence."""
        engine = SignalEngine()
        bar1   = make_bar(close=18200.0, cum_delta=100.0, vwap=18190.0, poc=18180.0,
                          vah=18195.0, val=18150.0)  # close=18200 > vah=18195 → outside VA
        bar2   = make_bar(close=18210.0, cum_delta=180.0, vwap=18190.0, poc=18180.0,
                          vah=18195.0, val=18150.0)
        engine.evaluate(bar1)
        signal = engine.evaluate(bar2)
        assert signal.direction == Direction.BUY
        assert signal.confidence == pytest.approx(0.70)


class TestNTSignalHelpers:
    def test_is_actionable_buy(self):
        bar    = make_bar()
        signal = NTSignal(direction=Direction.BUY, confidence=0.85, reason="test", bar=bar)
        assert signal.is_actionable() is True

    def test_is_actionable_flat(self):
        bar    = make_bar()
        signal = NTSignal(direction=Direction.FLAT, confidence=0.0, reason="test", bar=bar)
        assert signal.is_actionable() is False

    def test_generated_at_populated(self):
        bar    = make_bar()
        signal = NTSignal(direction=Direction.SELL, confidence=0.70, reason="test", bar=bar)
        assert isinstance(signal.generated_at, datetime)
