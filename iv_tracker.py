"""
IV Rank Tracker
Stores historical implied volatility (IV) observations and computes IV Rank (IVR).

IVR formula:
  IVR = (current_iv - min_iv_lookback) / (max_iv_lookback - min_iv_lookback) x 100

Why IVR matters for options buying:
  When IV is historically low (cheap), options cost less for the same expected move.
  Buying options with low IVR gives you more premium efficiency and less IV crush risk.
  Buying options with high IVR means paying an inflated premium that can deflate even
  if the underlying moves in your direction.

IVR → Confidence Multiplier table:
  IVR   0–20  : IV historically cheap     → options CHEAP to buy  → +15% confidence
  IVR  20–40  : IV below-average           → options reasonable   →  +8% confidence
  IVR  40–60  : IV neutral                 → no adjustment        →   0% change
  IVR  60–80  : IV elevated               → options expensive    → -10% confidence
  IVR  80–100 : IV extreme / crush risk   → avoid options buy    → -25% confidence

Data lifecycle:
  - store_iv_observation() is called each time an options best-strike is computed
  - compute_ivr() uses the last LOOKBACK_DAYS days of stored observations
  - Requires MIN_OBSERVATIONS before producing a reliable IVR (else returns neutral)
  - DB table: iv_history (ticker TEXT, iv REAL, recorded_at TIMESTAMP)
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MIN_OBSERVATIONS = 10   # data points required before IVR is considered reliable
LOOKBACK_DAYS    = 30   # rolling lookback window for min/max IV computation


def _now_et() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def store_iv_observation(ticker: str, iv: float) -> None:
    """
    Persist a single IV observation to the iv_history table.

    Called from options_filter.py whenever a valid best-strike is found.
    Silent no-op if iv is zero/None or if DB is unavailable.
    """
    if not iv or iv <= 0:
        return
    try:
        from db_connection import get_conn, ph
        conn   = get_conn()
        cursor = conn.cursor()
        p      = ph()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS iv_history (
                id          SERIAL PRIMARY KEY,
                ticker      TEXT        NOT NULL,
                iv          REAL        NOT NULL,
                recorded_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_iv_history_ticker_time
            ON iv_history (ticker, recorded_at)
        """)
        cursor.execute(
            f"INSERT INTO iv_history (ticker, iv) VALUES ({p}, {p})",
            (ticker, round(iv, 6))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[IVR] store error for {ticker}: {e}")


def compute_ivr(ticker: str, current_iv: float,
                lookback_days: int = LOOKBACK_DAYS) -> tuple:
    """
    Compute IV Rank for a ticker over the past `lookback_days` calendar days.

    Returns:
      (ivr: float|None, observations: int, is_reliable: bool)

      - ivr         : 0–100 IV Rank, or None if insufficient history
      - observations: number of data points used in the calculation
      - is_reliable : True when observations >= MIN_OBSERVATIONS
    """
    if not current_iv or current_iv <= 0:
        return None, 0, False

    try:
        from db_connection import get_conn, ph
        conn   = get_conn()
        cursor = conn.cursor()
        p      = ph()

        cutoff = _now_et() - timedelta(days=lookback_days)

        cursor.execute(
            f"""
            SELECT MIN(iv), MAX(iv), COUNT(*)
            FROM   iv_history
            WHERE  ticker      = {p}
              AND  recorded_at >= {p}
              AND  iv          > 0
            """,
            (ticker, cutoff)
        )
        row = cursor.fetchone()
        conn.close()

        if not row or row[2] is None:
            return None, 0, False

        min_iv, max_iv, count = float(row[0]), float(row[1]), int(row[2])

        if count < MIN_OBSERVATIONS:
            return None, count, False

        if max_iv <= min_iv:
            # Flat IV history — assign neutral rank
            return 50.0, count, True

        ivr = ((current_iv - min_iv) / (max_iv - min_iv)) * 100.0
        ivr = max(0.0, min(100.0, ivr))
        return round(ivr, 1), count, True

    except Exception as e:
        print(f"[IVR] compute error for {ticker}: {e}")
        return None, 0, False


def ivr_to_confidence_multiplier(ivr, is_reliable: bool) -> tuple:
    """
    Map an IVR value to a (multiplier, label) pair.

    When IVR is unavailable (not yet reliable), returns (1.0, "IVR-BUILDING")
    so signals are not blocked during the data-accumulation period.

    Returns:
      (multiplier: float, label: str)
    """
    if ivr is None or not is_reliable:
        return 1.0, "IVR-BUILDING"

    if ivr < 20:
        return 1.15, f"IVR-LOW({ivr:.0f})"
    elif ivr < 40:
        return 1.08, f"IVR-BELOW-AVG({ivr:.0f})"
    elif ivr < 60:
        return 1.00, f"IVR-NEUTRAL({ivr:.0f})"
    elif ivr < 80:
        return 0.90, f"IVR-HIGH({ivr:.0f})"
    else:
        return 0.75, f"IVR-EXTREME({ivr:.0f})"
