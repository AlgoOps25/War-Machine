"""
Screener Integration Helper  —  War Machine v3.1

Bridge between dynamic_screener.py (which uses get_scored_tickers / run_all_passes)
and the rest of the system that needs per-ticker metadata.

get_screener() / DynamicScreener class never existed in v3.1 — this file
now uses the correct functional API.

Patch (Mar 12, 2026): is_explosive_mover() default rvol_threshold lowered
  4.0 → 3.0 to match get_ticker_screener_metadata() (rvol >= 3.0 for qualified).
  Previously, tickers with 3.0–3.9x RVOL got qualified=True from the screener
  but is_explosive_mover() returned False, causing inconsistent downstream behavior.
"""
from typing import Dict, Optional, List
import traceback



def get_ticker_screener_metadata(ticker: str) -> Dict:
    """Return screener metadata for a single ticker.

    Looks the ticker up in the most-recent scored list from
    dynamic_screener.get_scored_tickers().  Falls back to a safe
    default if the screener hasn't run yet or the ticker isn't
    in the current scan.

    Returns dict with keys:
        qualified : bool  (score >= 80 AND rvol >= 3.0)
        score     : int   (0-100)
        rvol      : float (relative-volume multiplier)
        tier      : str   ('A', 'B', 'C', or None)
    """
    default = {'qualified': False, 'score': 0, 'rvol': 0.0, 'tier': None}

    try:
        from app.screening.dynamic_screener import get_scored_tickers
        scored = get_scored_tickers(max_tickers=100)

        ticker_data = next(
            (t for t in scored if t.get('ticker') == ticker.upper()),
            None
        )

        if not ticker_data:
            return default

        score = ticker_data.get('score', 0)
        rvol  = ticker_data.get('rvol',  0.0)
        tier  = ticker_data.get('rvol_tier', None)   # 'A', 'B', or 'C'

        return {
            'qualified': (score >= 80 and rvol >= 3.0),
            'score':     score,
            'rvol':      rvol,
            'tier':      tier,
        }

    except Exception as e:
        print(f"[SCREENER-INTEGRATION] EXPLOSIVE Metadata fetch error for {ticker}: {e}")
        print(f"[SCREENER-INTEGRATION] Traceback: {traceback.format_exc()}")
        return default


def get_screener_instance() -> Optional[List[Dict]]:
    """Back-compat shim — returns the current scored list instead of a class instance."""
    try:
        from app.screening.dynamic_screener import get_scored_tickers
        return get_scored_tickers()
    except Exception as e:
        print(f"[SCREENER-INTEGRATION] Failed to get screener data: {e}")
        return None


def is_explosive_mover(
    ticker: str,
    score_threshold: int   = 80,
    rvol_threshold:  float = 3.0,
) -> bool:
    """Return True if ticker meets both score and RVOL thresholds.

    Threshold unified to 3.0x (was 4.0x) to match get_ticker_screener_metadata()
    and RegimeFilter.is_favorable_for_explosive_mover().
    """
    meta = get_ticker_screener_metadata(ticker)
    return meta['score'] >= score_threshold and meta['rvol'] >= rvol_threshold
