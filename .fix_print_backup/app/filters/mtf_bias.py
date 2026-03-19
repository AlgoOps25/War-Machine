"""
mtf_bias.py — Multi-Timeframe Bias Engine (Phase 1.34)
Nitro Trades top-down methodology: 1H -> 15m -> 5m

Layers:
  1. 1H Bias Gate     — BOS direction on 1H must match signal direction
  2. 15m Structure    — BOS direction on 15m must match signal direction
  3. Confidence Adj   — fully aligned = +0.08, 15m only = no boost, conflicted = REJECT

Phase 1.35: Stats tracking — every evaluate() result recorded to mtf_bias_stats table.
"""

from typing import Optional
from datetime import datetime

MTF_BIAS_ENABLED = True
MIN_BARS_1H      = 5
MIN_BARS_15M     = 8
CONF_BOOST_FULL  = +0.08
CONF_PENALTY     = -0.10


BOS_LOOKBACK = 8  # Backtest-optimized (Phase 1.35 sweep: lb=8 → WR=91% avgR=0.50)

def _detect_bos(bars: list) -> Optional[str]:
    """Bull BOS = last close breaks prior 8-bar high. Bear BOS = breaks prior 8-bar low."""
    if not bars or len(bars) < BOS_LOOKBACK + 1:
        return None
    lookback   = bars[-(BOS_LOOKBACK + 1):-1]  # last 8 bars before the current
    last_close = bars[-1]["close"]
    if last_close > max(b["high"] for b in lookback):
        return "bull"
    if last_close < min(b["low"]  for b in lookback):
        return "bear"
    return None

def _compute_vwap(bars: list) -> float:
    if not bars or len(bars) < 3:
        return 0.0
    tpv = vol = 0.0
    for b in bars:
        tp   = (b["high"] + b["low"] + b["close"]) / 3.0
        v    = b.get("volume", 0) or 0
        tpv += tp * v
        vol += v
    return tpv / vol if vol > 0 else 0.0


class MTFBiasEngine:

    def __init__(self, enabled: bool = MTF_BIAS_ENABLED):
        self.enabled = enabled
        self._db_ready = False
        self._init_stats_db()

    # ── Phase 1.35: Stats DB ─────────────────────────────────────────────────
    def _init_stats_db(self):
        """Create mtf_bias_stats table if it doesn't exist."""
        try:
            from app.data.db_connection import get_conn, return_conn
            conn = get_conn()
            try:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS mtf_bias_stats (
                        id          SERIAL PRIMARY KEY,
                        ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        ticker      TEXT      NOT NULL,
                        direction   TEXT      NOT NULL,
                        passed      BOOLEAN   NOT NULL,
                        bias_1h     TEXT,
                        bias_15m    TEXT,
                        vwap_1h     REAL,
                        conf_adj    REAL      NOT NULL,
                        reason      TEXT
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_mtf_bias_stats_ticker
                    ON mtf_bias_stats(ticker, ts DESC)
                """)
                conn.commit()
                self._db_ready = True
            finally:
                return_conn(conn)
        except Exception as e:
            print(f"[MTF-BIAS] Stats DB init failed (non-fatal): {e}")
            self._db_ready = False

    def record_stat(self, ticker: str, direction: str, result: dict):
        """
        Persist one evaluate() result to mtf_bias_stats.
        Call this from sniper.py after evaluate() returns.
        Non-fatal — never blocks signal flow.
        """
        if not self._db_ready:
            return
        try:
            from app.data.db_connection import get_conn, return_conn, ph
            p = ph()
            conn = get_conn()
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    INSERT INTO mtf_bias_stats
                        (ticker, direction, passed, bias_1h, bias_15m, vwap_1h, conf_adj, reason)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
                """, (
                    ticker,
                    direction,
                    result["pass"],
                    result.get("bias_1h"),
                    result.get("bias_15m"),
                    result.get("vwap_1h", 0.0),
                    result.get("confidence_adj", 0.0),
                    result.get("reason", ""),
                ))
                conn.commit()
            finally:
                return_conn(conn)
        except Exception as e:
            print(f"[MTF-BIAS] record_stat error (non-fatal): {e}")

    # ── Core evaluate ────────────────────────────────────────────────────────
    def evaluate(
        self,
        direction:     str,
        bars_1h:       list,
        bars_15m:      list,
        current_price: float = 0.0,
    ) -> dict:
        """
        Returns:
          {"pass": bool, "confidence_adj": float, "bias_1h": str|None,
           "bias_15m": str|None, "vwap_1h": float, "reason": str}
        """
        if not self.enabled:
            return self._ok(None, None, 0.0, 0.0, "MTF bias disabled")

        bias_1h = vwap_1h = None
        has_1h  = bool(bars_1h and len(bars_1h) >= MIN_BARS_1H)
        if has_1h:
            bias_1h = _detect_bos(bars_1h)
            vwap_1h = _compute_vwap(bars_1h)

        bias_15m = None
        has_15m  = bool(bars_15m and len(bars_15m) >= MIN_BARS_15M)
        if has_15m:
            bias_15m = _detect_bos(bars_15m)

        aligned_1h  = (bias_1h  == direction) if bias_1h  else None
        aligned_15m = (bias_15m == direction) if bias_15m else None

        if aligned_15m is False:
            return self._fail(bias_1h, bias_15m, vwap_1h,
                f"15m BOS={bias_15m} conflicts with {direction} signal")

        if aligned_1h is False:
            return self._fail(bias_1h, bias_15m, vwap_1h,
                f"1H BOS={bias_1h} conflicts with {direction} signal")

        if has_1h and vwap_1h and current_price:
            above = current_price > vwap_1h
            if direction == "bull" and not above:
                return self._fail(bias_1h, bias_15m, vwap_1h,
                    f"BULL but price ${current_price:.2f} < 1H VWAP ${vwap_1h:.2f}")
            if direction == "bear" and above:
                return self._fail(bias_1h, bias_15m, vwap_1h,
                    f"BEAR but price ${current_price:.2f} > 1H VWAP ${vwap_1h:.2f}")

        if aligned_1h and aligned_15m:
            return self._ok(bias_1h, bias_15m, vwap_1h, CONF_BOOST_FULL,
                f"MTF ALIGNED: 1H={bias_1h} 15m={bias_15m} -> +{CONF_BOOST_FULL:.0%}")
        if aligned_15m:
            return self._ok(bias_1h, bias_15m, vwap_1h, 0.0,
                f"15m aligned ({bias_15m}); 1H unavailable — no boost")
        return self._ok(bias_1h, bias_15m, vwap_1h, 0.0,
            "MTF: no clear structure detected — pass, no boost")

    @staticmethod
    def _ok(bias_1h, bias_15m, vwap_1h, adj, reason):
        return {"pass": True,  "confidence_adj": adj,          "bias_1h": bias_1h,
                "bias_15m": bias_15m, "vwap_1h": vwap_1h or 0.0, "reason": reason}

    @staticmethod
    def _fail(bias_1h, bias_15m, vwap_1h, reason):
        return {"pass": False, "confidence_adj": CONF_PENALTY,  "bias_1h": bias_1h,
                "bias_15m": bias_15m, "vwap_1h": vwap_1h or 0.0, "reason": reason}


mtf_bias_engine = MTFBiasEngine()
