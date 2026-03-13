"""
opening_range.py
Tracks the 5-minute opening range for top watchlist tickers
and generates ORB signals at 9:35 AM ET.
"""

import logging
from datetime import datetime, time
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

ORB_FORMATION_END = time(9, 35)   # 5-min ORB window closes
ORB_SIGNAL_WINDOW = time(9, 55)   # signals only valid within 20 min of open
ORB_VOLUME_MULTIPLIER = 1.5       # bar volume must exceed this × premarket avg


@dataclass
class OpeningRange:
    ticker: str
    premarket_score: float
    premarket_rvol: float
    premarket_gap_pct: float
    prev_close: float

    high: Optional[float] = None
    low: Optional[float] = None
    bars: list = field(default_factory=list)
    signal_fired: bool = False
    signal_type: Optional[str] = None  # 'LONG' | 'SHORT'
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None

    def update(self, bar: dict):
        """Ingest a 1-min bar during 9:30–9:35 formation window."""
        self.bars.append(bar)
        prices = [b['high'] for b in self.bars]
        lows   = [b['low']  for b in self.bars]
        self.high = max(prices)
        self.low  = min(lows)
        logger.debug(f"[ORB] {self.ticker} range building: H={self.high} L={self.low} ({len(self.bars)} bars)")

    def evaluate(self, bar: dict) -> Optional[dict]:
        """
        Called at/after 9:35 on each new bar.
        Returns signal dict if breakout confirmed, else None.
        """
        if self.signal_fired:
            return None
        if self.high is None or self.low is None:
            return None

        close  = bar['close']
        volume = bar['volume']
        vwap   = bar.get('vwap', close)

        range_size = self.high - self.low
        atr_filter = range_size < 3.0  # skip if ORB too tight (choppy open)

        # --- LONG setup ---
        if (close > self.high
                and close > vwap
                and volume >= ORB_VOLUME_MULTIPLIER * self._avg_premarket_vol()):

            self.signal_type = 'LONG'
            self.entry  = self.high          # buy stop just above ORB high
            self.stop   = self.low           # stop below ORB low
            self.target = self.entry + (self.entry - self.stop) * 2  # 2R target
            self.signal_fired = True

        # --- SHORT / fade setup ---
        # Only on no-catalyst gap stocks (gap without news = likely fade)
        elif (close < self.low
                and close < vwap
                and self.premarket_rvol > 50
                and self.premarket_gap_pct > 3.0
                and volume >= ORB_VOLUME_MULTIPLIER * self._avg_premarket_vol()):

            self.signal_type = 'SHORT'
            self.entry  = self.low
            self.stop   = self.high
            self.target = self.entry - (self.stop - self.entry) * 1.5
            self.signal_fired = True

        if self.signal_fired:
            signal = self._build_signal()
            logger.info(
                f"[ORB] 🚀 {self.ticker} {self.signal_type} signal | "
                f"Entry={self.entry:.2f} Stop={self.stop:.2f} "
                f"Target={self.target:.2f} | R={range_size:.2f}"
            )
            return signal

        return None

    def _avg_premarket_vol(self) -> float:
        """Average per-bar volume seen during ORB formation."""
        if not self.bars:
            return 1
        return sum(b['volume'] for b in self.bars) / len(self.bars)

    def _build_signal(self) -> dict:
        risk = abs(self.entry - self.stop)
        return {
            'ticker':           self.ticker,
            'signal_type':      self.signal_type,
            'entry':            round(self.entry, 2),
            'stop':             round(self.stop, 2),
            'target':           round(self.target, 2),
            'risk_per_share':   round(risk, 2),
            'premarket_score':  self.premarket_score,
            'premarket_rvol':   self.premarket_rvol,
            'gap_pct':          self.premarket_gap_pct,
            'timestamp':        datetime.now().isoformat(),
            'source':           'ORB',
        }


class OpeningRangeTracker:
    """
    Manages OpeningRange instances for all watchlist tickers.
    Feed 1-min bars into this; it handles timing logic internally.
    """

    def __init__(self, watchlist: list[dict]):
        """
        watchlist: list of dicts with keys:
            ticker, premarket_score, premarket_rvol, premarket_gap_pct, prev_close
        """
        self.ranges: dict[str, OpeningRange] = {}
        for item in watchlist:
            self.ranges[item['ticker']] = OpeningRange(**item)
            logger.info(f"[ORB] Registered {item['ticker']} | score={item['premarket_score']} RVOL={item['premarket_rvol']}x")

    def process_bar(self, ticker: str, bar: dict) -> Optional[dict]:
        """
        Call this for every 1-min bar received from WebSocket.
        Returns a signal dict if an ORB breakout is confirmed.
        """
        if ticker not in self.ranges:
            return None

        now = datetime.now().time()
        orb = self.ranges[ticker]

        # Phase 1: 9:30–9:35 — build the range
        if now < ORB_FORMATION_END:
            orb.update(bar)
            return None

        # Phase 2: 9:35–9:55 — evaluate for breakout
        if now <= ORB_SIGNAL_WINDOW:
            return orb.evaluate(bar)

        # After 9:55 — ORB window expired, no new signals
        return None

    def get_range(self, ticker: str) -> Optional[OpeningRange]:
        return self.ranges.get(ticker)
