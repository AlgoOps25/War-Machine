"""
test_vix.py — VIX Data Fetch Tests

CI-safe:
  - test_vix_data_manager_importable  — checks if data_manager imports cleanly

Integration (requires live DB with bars stored):
  - test_vix_get_bars_from_memory     — get_bars_from_memory('VIX') returns list
  - test_vix_get_bars_api             — get_bars('VIX', timeframe='1m') hits API

Run CI-safe only:
  pytest tests/test_vix.py -v -m "not integration"
"""
import sys
import pytest
from pathlib import Path

# Ensure project root is on sys.path regardless of where pytest is invoked from
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from data_manager import data_manager
    _DM_AVAILABLE = True
except ImportError:
    _DM_AVAILABLE = False
    data_manager   = None

needs_dm = pytest.mark.skipif(
    not _DM_AVAILABLE,
    reason="data_manager not importable — check sys.path / missing deps"
)


def test_vix_data_manager_importable():
    """data_manager must import cleanly from the project root."""
    assert _DM_AVAILABLE, (
        "data_manager failed to import. "
        "Ensure the project root is on sys.path and all dependencies are installed."
    )


@pytest.mark.integration
@needs_dm
def test_vix_get_bars_from_memory():
    """get_bars_from_memory('VIX') should return a list (may be empty if no data)."""
    bars = data_manager.get_bars_from_memory("VIX", limit=1)
    assert isinstance(bars, list), f"Expected list, got {type(bars)}"


@pytest.mark.integration
@needs_dm
def test_vix_get_bars_api():
    """get_bars('VIX', timeframe='1m') should return a list or None without crashing."""
    if not hasattr(data_manager, 'get_bars'):
        pytest.skip("data_manager has no get_bars method")
    bars = data_manager.get_bars("VIX", timeframe="1m", limit=1)
    assert bars is None or isinstance(bars, list), (
        f"get_bars returned unexpected type: {type(bars)}"
    )
