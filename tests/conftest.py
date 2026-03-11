"""
War Machine — Shared pytest fixtures  (Phase 1.23)
===================================================
Provides lightweight, dependency-free fixtures used across the test suite.
All heavy external deps (psycopg2, websockets, EODHD API) are mocked so
tests run cleanly in CI without any live credentials or network access.
"""
import os
import time
import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Environment stubs — prevent modules that read env vars at import time
# from crashing when DATABASE_URL / API keys are absent in CI.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def ci_env_stubs(monkeypatch):
    """Set safe dummy env vars for every test automatically."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("EODHD_API_KEY", "TESTKEY")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    monkeypatch.setenv("TRADIER_API_KEY", "TESTKEY")
    yield


# ─────────────────────────────────────────────────────────────────────────────
# Mock OHLCV bars — standard 1-minute bar list used by signal / VWAP tests
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_bars():
    """Return 20 synthetic 1-min bars around price 100."""
    base = 100.0
    bars = []
    for i in range(20):
        close = base + i * 0.10
        bars.append({
            'open':   close - 0.05,
            'high':   close + 0.10,
            'low':    close - 0.10,
            'close':  close,
            'volume': 150_000 + i * 1_000,
            'timestamp': int(time.time()) - (20 - i) * 60,
        })
    return bars


@pytest.fixture
def breakout_bars(mock_bars):
    """
    Extend mock_bars with a clear OR breakout: last bar closes well above
    the opening range high (OR high = 100.95 from bars[0..9]).
    """
    bars = list(mock_bars)
    bars.append({
        'open':   101.80,
        'high':   102.50,
        'low':    101.70,
        'close':  102.40,
        'volume': 400_000,
        'timestamp': int(time.time()),
    })
    return bars


# ─────────────────────────────────────────────────────────────────────────────
# Mock DB connection — avoids psycopg2 dependency in unit tests
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_db_conn():
    """Lightweight psycopg2 connection mock with cursor support."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cursor
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Minimal signal dict — mirrors the shape sniper.py passes around internally
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def signal_dict():
    return {
        'ticker':       'TEST',
        'direction':    'bull',
        'entry_price':  100.0,
        'stop_price':   99.0,
        'target_1':     102.0,
        'target_2':     104.0,
        'or_high':      101.0,
        'or_low':       99.0,
        'zone_high':    101.5,
        'zone_low':     99.5,
        'confidence':   0.75,
        'grade':        'B+',
        'rvol':         3.2,
        'atr':          0.85,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Temporary cache directory — keeps file-system tests hermetic
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_cache_dir(tmp_path):
    """Isolated cache directory that is deleted after each test."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    return cache


# ─────────────────────────────────────────────────────────────────────────────
# Mock config — safe stand-in for utils.config so tests never need .env
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.MARKET_OPEN  = __import__('datetime').time(9, 30)
    cfg.MARKET_CLOSE = __import__('datetime').time(16, 0)
    cfg.MIN_RVOL     = 2.0
    cfg.MIN_SCORE    = 60
    cfg.MAX_POSITIONS = 3
    cfg.MAX_DAILY_LOSS = 500.0
    return cfg
