"""
Opening Range (OR) Detection - Task 7

Responsibilities:
  - Classify Opening Range (9:30-9:40) as TIGHT, NORMAL, or WIDE
  - Alert at 9:38 for tight OR forming (expansion breakout likely)
  - Raise confidence threshold for wide OR (consolidation filter)
  - Provide dynamic scan frequency recommendations
  - Boost confidence for tight OR breakouts

Classification:
  - TIGHT: < 0.5 ATR (expansion likely, scan aggressively)
  - NORMAL: 0.5-1.5 ATR (standard behavior)
  - WIDE: > 1.5 ATR (consolidation likely, require higher confidence)

Impact: Capture 9:30-9:40 early moves, filter choppy wide ORs

PHASE 1.17 FIXES (MAR 10, 2026):
  BUG #1: _extract_or_bars() used bar['timestamp'] but data_manager returns bar['datetime'] — KeyError
           silently returned [] on every call, causing perpetual 'No OR bars found'
  BUG #2: No mid-session fallback — if OR window was missed (restart after 9:40), classify_or()
           returned None forever. Now falls back to session range (9:30->now) with DYNAMIC label.
  BUG #3: _calculate_atr() only used today's bars — returned None before 14 bars accumulated.
           Now uses get_bars_from_memory() (historical DB) first, falls back to today's bars.
  BUG #4: calculate_support_resistance() in breakout_detector.py only used rolling 12 bars.
           Opening range is now exposed via get_session_levels() so breakout_detector can
           always anchor to the 9:30 session high/low regardless of current time.
  BUG #5 (Phase 1.17 final): or_cache DYNAMIC entries never expired intraday.
           If system restarted at 9:42 it stayed DYNAMIC all day even after 60+ real bars
           accumulated that would qualify for TIGHT/NORMAL/WIDE.
           Fix: DYNAMIC entries expire after OR_CACHE_DYNAMIC_TTL (30 min) so classify_or()
           re-evaluates on the next call and may promote to a real classification.
           TIGHT/NORMAL/WIDE entries never expire — they reflect the true 9:30-9:40 window.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import numpy as np

from app.data.data_manager import data_manager

ET = ZoneInfo("America/New_York")

# How long (minutes) a DYNAMIC cache entry is valid before re-evaluation.
# TIGHT/NORMAL/WIDE entries never expire (the true 9:30-9:40 window is immutable).
OR_CACHE_DYNAMIC_TTL = timedelta(minutes=30)


class OpeningRangeDetector:
    """
    Detect and classify Opening Range for intraday trading.

    OR Window: 9:30-9:40 AM ET (10 minutes)
    Fallback:  If OR was missed (mid-session restart), uses full session
               range (9:30 -> now) and labels it DYNAMIC.

    Classification Logic:
      - Calculate ATR(14) from historical bars (DB), fall back to today's
      - Measure OR range (high - low)
      - Compare OR range to ATR
      - Classify as TIGHT / NORMAL / WIDE / DYNAMIC

    Cache behaviour (Phase 1.17 fix):
      - TIGHT / NORMAL / WIDE: cached permanently for the session (true OR window,
        values cannot change after 9:40).
      - DYNAMIC: cached for OR_CACHE_DYNAMIC_TTL (30 min). After expiry, the next
        call to classify_or() re-evaluates using all accumulated session bars.
        This allows a 9:42 restart to eventually promote from DYNAMIC -> TIGHT/NORMAL/WIDE
        once enough bars are available.

    Trading Rules:
      - TIGHT OR:   Scan every 30s at 9:40+, +5% confidence boost
      - NORMAL OR:  Scan every 45s (standard), normal thresholds
      - WIDE OR:    Scan every 45s, raise threshold to 75%
      - DYNAMIC OR: Mid-session fallback, treat as NORMAL
    """

    def __init__(self):
        # OR window parameters
        self.or_start_time = time(9, 30)   # 9:30 AM ET
        self.or_end_time   = time(9, 40)   # 9:40 AM ET
        self.or_alert_time = time(9, 38)   # Alert time for tight OR forming

        # Classification thresholds (ATR multipliers)
        self.tight_threshold = 0.5    # < 0.5 ATR = TIGHT
        self.wide_threshold  = 1.5    # > 1.5 ATR = WIDE

        # Confidence adjustments
        self.tight_or_boost         = 0.05   # +5% for tight OR breakouts
        self.wide_or_min_confidence = 0.75   # 75% minimum for wide OR

        # Scan frequency recommendations (seconds)
        self.scan_freq_tight  = 30
        self.scan_freq_normal = 45
        self.scan_freq_wide   = 45

        # Session cache
        # Structure: ticker -> OR result dict
        # DYNAMIC entries also carry '_cached_at' (datetime) for TTL check.
        self.or_cache:     Dict[str, Dict] = {}   # ticker -> OR data
        self.alerts_sent:  Dict[str, bool] = {}   # ticker -> alert sent flag

        print("[OR] Opening Range Detector initialized")
        print(f"[OR] Window: 9:30-9:40 AM ET (10 minutes)")
        print(f"[OR] Thresholds: TIGHT<{self.tight_threshold} ATR, WIDE>{self.wide_threshold} ATR")
        print(f"[OR] Scan frequencies: Tight={self.scan_freq_tight}s, Normal={self.scan_freq_normal}s")
        print(f"[OR] Mid-session fallback: DYNAMIC range (9:30->now) if OR missed")
        print(f"[OR] DYNAMIC cache TTL: {int(OR_CACHE_DYNAMIC_TTL.total_seconds() // 60)} min")

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def classify_or(self, ticker: str, current_time: Optional[datetime] = None) -> Optional[Dict]:
        """
        Classify Opening Range for a ticker.

        Phase 1.17: Two paths:
          1. OR window complete (>= 9:40): extract 9:30-9:40 bars  (original logic, fixed key)
          2. OR window missed (restart after 9:40 with no OR bars): fall back to
             full session range 9:30->now, labelled DYNAMIC.

        Cache behaviour:
          - TIGHT/NORMAL/WIDE: cached for the full session (immutable after 9:40).
          - DYNAMIC: cached for OR_CACHE_DYNAMIC_TTL (30 min), then re-evaluated
            so bars that accumulated after restart can promote to a real classification.

        Returns:
            OR classification dict or None if no session bars at all.
        """
        if current_time is None:
            current_time = datetime.now(ET)

        # Before OR window closes, do not classify yet
        if not self._is_or_complete(current_time):
            return None

        # Return cached result if still valid
        if ticker in self.or_cache:
            cached = self.or_cache[ticker]
            if cached.get('classification') != 'DYNAMIC':
                # TIGHT / NORMAL / WIDE never expire
                return cached
            # DYNAMIC: check TTL
            cached_at = cached.get('_cached_at')
            if cached_at and (current_time.replace(tzinfo=None) - cached_at.replace(tzinfo=None)) < OR_CACHE_DYNAMIC_TTL:
                return cached
            # TTL expired — evict and re-evaluate
            print(f"[OR] {ticker} DYNAMIC cache expired — re-evaluating with accumulated bars")
            del self.or_cache[ticker]

        # ── Get today's session bars ──────────────────────────────────
        bars_1m = data_manager.get_today_session_bars(ticker)

        if not bars_1m:
            print(f"[OR] {ticker} - No session bars available")
            return None

        # ── Try to extract the real 9:30-9:40 OR first ───────────────
        or_bars = self._extract_or_bars(bars_1m)

        if or_bars:
            # Happy path — OR window was captured (or was just re-evaluated and
            # enough bars now exist to build a real OR)
            return self._classify_from_bars(ticker, or_bars, classification_label=None,
                                            current_time=current_time)

        # ── Fallback: mid-session restart, OR was missed ──────────────
        print(f"[OR] {ticker} - OR window missed (mid-session restart) — using DYNAMIC session range")
        session_bars = self._extract_session_bars(bars_1m)

        if not session_bars:
            print(f"[OR] {ticker} - No bars found in session window (9:30->now)")
            return None

        return self._classify_from_bars(ticker, session_bars, classification_label="DYNAMIC",
                                        current_time=current_time)

    def get_session_levels(self, ticker: str) -> Dict:
        """
        Return session-anchored high/low/open since 9:30 AM.

        Phase 1.17: Exposed for breakout_detector.py so that
        calculate_support_resistance() can always anchor to the session
        open structure regardless of the rolling lookback window.

        Returns:
            {
              'session_high': float,
              'session_low':  float,
              'session_open': float,   # first 9:30 bar open
              'bar_count':    int
            }
            or {} if no session bars.
        """
        bars_1m = data_manager.get_today_session_bars(ticker)
        if not bars_1m:
            return {}

        session_bars = self._extract_session_bars(bars_1m)
        if not session_bars:
            return {}

        return {
            "session_high":  round(max(b["high"]  for b in session_bars), 4),
            "session_low":   round(min(b["low"]   for b in session_bars), 4),
            "session_open":  round(session_bars[0]["open"], 4),
            "bar_count":     len(session_bars),
        }

    def should_alert_or_forming(self, ticker: str, current_time: Optional[datetime] = None) -> bool:
        """
        Check if we should send 'OR forming' alert (at 9:38 AM for tight OR).
        """
        if current_time is None:
            current_time = datetime.now(ET)

        if current_time.time() < self.or_alert_time:
            return False
        if ticker in self.alerts_sent:
            return False

        bars_1m = data_manager.get_today_session_bars(ticker)
        if not bars_1m or len(bars_1m) < 8:
            return False

        or_bars_so_far = self._extract_or_bars(bars_1m, end_time=time(9, 38))
        if not or_bars_so_far or len(or_bars_so_far) < 8:
            return False

        or_high  = max(b['high'] for b in or_bars_so_far)
        or_low   = min(b['low']  for b in or_bars_so_far)
        or_range = or_high - or_low
        atr      = self._calculate_atr(ticker)

        if atr is None or atr == 0:
            return False

        if (or_range / atr) < self.tight_threshold:
            self.alerts_sent[ticker] = True
            return True

        return False

    def should_scan_now(self, ticker: str, current_time: Optional[datetime] = None) -> bool:
        if current_time is None:
            current_time = datetime.now(ET)
        if not self._is_or_complete(current_time):
            return True
        or_data = self.classify_or(ticker, current_time)
        return True  # scan frequency handled by scanner loop

    def adjust_signal_confidence(self, signal: Dict, current_time: Optional[datetime] = None) -> Dict:
        if current_time is None:
            current_time = datetime.now(ET)
        ticker  = signal['ticker']
        or_data = self.classify_or(ticker, current_time)
        if or_data is None:
            return signal

        original_confidence   = signal.get('confidence', 0)
        confidence_adjustment = or_data['confidence_adjustment']

        if confidence_adjustment > 0:
            signal['confidence'] = min(100, original_confidence + (confidence_adjustment * 100))
            signal['or_boost']   = confidence_adjustment

        if or_data['classification'] == 'WIDE':
            min_confidence = or_data['min_confidence'] * 100
            if signal['confidence'] < min_confidence:
                signal['or_filtered']       = True
                signal['or_filter_reason']  = f"Wide OR requires {min_confidence:.0f}% confidence"

        signal['or'] = or_data
        return signal

    def get_scan_frequency(self, ticker: str, current_time: Optional[datetime] = None) -> int:
        if current_time is None:
            current_time = datetime.now(ET)
        if not self._is_or_complete(current_time):
            return self.scan_freq_normal
        or_data = self.classify_or(ticker, current_time)
        if or_data is None:
            return self.scan_freq_normal
        return or_data['scan_frequency']

    def clear_cache(self) -> None:
        """Clear OR cache (called at market open for new session)."""
        or_count    = len(self.or_cache)
        alert_count = len(self.alerts_sent)
        self.or_cache.clear()
        self.alerts_sent.clear()
        print(f"[OR] Session cache cleared ({or_count} OR entries, {alert_count} alerts reset)")

    def get_or_summary(self, tickers: List[str], current_time: Optional[datetime] = None) -> str:
        if current_time is None:
            current_time = datetime.now(ET)
        if not self._is_or_complete(current_time):
            return "\u23f3 Opening Range (9:30-9:40) still forming..."

        summary        = "\U0001f4ca Opening Range Summary:\n\n"
        tight_tickers  = []
        wide_tickers   = []
        normal_tickers = []
        dynamic_tickers= []

        for ticker in tickers:
            or_data = self.classify_or(ticker, current_time)
            if or_data is None:
                continue
            label = f"{ticker} ({or_data['or_range_atr']:.2f}x ATR)"
            cls   = or_data['classification']
            if cls == 'TIGHT':    tight_tickers.append(label)
            elif cls == 'WIDE':   wide_tickers.append(label)
            elif cls == 'DYNAMIC': dynamic_tickers.append(label)
            else:                 normal_tickers.append(label)

        if tight_tickers:
            summary += "\U0001f3af **TIGHT OR** (expansion likely):\n"
            for t in tight_tickers:
                summary += f"  \u2022 {t}\n"
            summary += "\n"
        if normal_tickers:
            summary += "\u2705 **NORMAL OR**:\n"
            for t in normal_tickers:
                summary += f"  \u2022 {t}\n"
            summary += "\n"
        if wide_tickers:
            summary += "\u26a0\ufe0f **WIDE OR** (consolidation likely):\n"
            for t in wide_tickers:
                summary += f"  \u2022 {t}\n"
            summary += "\n"
        if dynamic_tickers:
            summary += "\U0001f504 **DYNAMIC** (mid-session restart, using session range):\n"
            for t in dynamic_tickers:
                summary += f"  \u2022 {t}\n"
            summary += "\n"

        return summary.strip()

    # ------------------------------------------------------------------
    # PRIVATE HELPERS
    # ------------------------------------------------------------------

    def _classify_from_bars(
        self,
        ticker: str,
        bars: List[Dict],
        classification_label: Optional[str],
        current_time: datetime,
    ) -> Optional[Dict]:
        """
        Shared classification logic for both normal OR bars and session fallback bars.

        Args:
            classification_label: If set (e.g. 'DYNAMIC'), skip ATR ratio
                                  classification and use that label directly.
        """
        or_high     = max(b['high'] for b in bars)
        or_low      = min(b['low']  for b in bars)
        or_range    = or_high - or_low
        or_range_pct= (or_range / or_low) * 100 if or_low > 0 else 0

        atr = self._calculate_atr(ticker)

        if atr is None or atr == 0:
            print(f"[OR] {ticker} - Could not calculate ATR")
            return None

        or_range_atr = or_range / atr

        # Determine classification
        if classification_label == "DYNAMIC":
            classification        = "DYNAMIC"
            scan_frequency        = self.scan_freq_normal
            confidence_adjustment = 0.0
            min_confidence        = 0.60
        elif or_range_atr < self.tight_threshold:
            classification        = 'TIGHT'
            scan_frequency        = self.scan_freq_tight
            confidence_adjustment = self.tight_or_boost
            min_confidence        = 0.60
        elif or_range_atr > self.wide_threshold:
            classification        = 'WIDE'
            scan_frequency        = self.scan_freq_wide
            confidence_adjustment = 0.0
            min_confidence        = self.wide_or_min_confidence
        else:
            classification        = 'NORMAL'
            scan_frequency        = self.scan_freq_normal
            confidence_adjustment = 0.0
            min_confidence        = 0.60

        result = {
            'ticker':               ticker,
            'or_high':              round(or_high, 2),
            'or_low':               round(or_low, 2),
            'or_range':             round(or_range, 2),
            'or_range_pct':         round(or_range_pct, 2),
            'or_range_atr':         round(or_range_atr, 2),
            'atr':                  round(atr, 2),
            'classification':       classification,
            'scan_frequency':       scan_frequency,
            'confidence_adjustment': confidence_adjustment,
            'min_confidence':       min_confidence,
            'bar_count':            len(bars),
            'timestamp':            current_time.isoformat(),
            # Internal TTL field — only meaningful for DYNAMIC entries.
            # Stored as tz-naive ET datetime for consistent comparison.
            '_cached_at':           current_time.replace(tzinfo=None),
        }

        # Cache it
        self.or_cache[ticker] = result

        # Log
        emoji_map = {'TIGHT': '\U0001f3af', 'WIDE': '\u26a0\ufe0f',
                     'DYNAMIC': '\U0001f504', 'NORMAL': '\u2705'}
        emoji = emoji_map.get(classification, '\u2705')
        print(f"[OR] {ticker} {emoji} {classification} | "
              f"Range: ${or_range:.2f} ({or_range_pct:.2f}%) | "
              f"ATR Ratio: {or_range_atr:.2f}x | Bars: {len(bars)}")

        if classification == 'TIGHT':
            print(f"[OR]   \U0001f680 Expansion breakout likely — scanning every {scan_frequency}s")
            print(f"[OR]   \U0001f4c8 Confidence boost: +{confidence_adjustment*100:.0f}%")
        elif classification == 'WIDE':
            print(f"[OR]   \u23f3 Consolidation likely — min confidence raised to {min_confidence*100:.0f}%")
        elif classification == 'DYNAMIC':
            print(f"[OR]   \U0001f504 Mid-session fallback — {len(bars)} bars from 9:30 used as range")
            print(f"[OR]   \U0001f551 Will re-evaluate in {int(OR_CACHE_DYNAMIC_TTL.total_seconds() // 60)} min")

        return result

    def _is_or_complete(self, current_time: datetime) -> bool:
        """True if OR window (9:30-9:40) has closed."""
        return current_time.time() >= self.or_end_time

    def _extract_or_bars(self, bars_1m: List[Dict],
                          end_time: Optional[time] = None) -> List[Dict]:
        """
        Extract bars within OR window (9:30-9:40).

        PHASE 1.17 FIX: data_manager returns bar['datetime'] (datetime object),
        NOT bar['timestamp'] (string). Previous code threw KeyError on every bar
        causing perpetual empty OR.
        """
        if end_time is None:
            end_time = self.or_end_time

        or_bars = []
        for bar in bars_1m:
            dt = bar.get('datetime')
            if dt is None:
                continue
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            bar_time = dt.time()
            if self.or_start_time <= bar_time < end_time:
                or_bars.append(bar)

        return or_bars

    def _extract_session_bars(self, bars_1m: List[Dict]) -> List[Dict]:
        """
        Extract all bars from 9:30 AM onwards (session bars).

        PHASE 1.17: Used as fallback when OR window was missed.
        Returns everything from 9:30 to the most recent bar.
        """
        session_bars = []
        for bar in bars_1m:
            dt = bar.get('datetime')
            if dt is None:
                continue
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if dt.time() >= self.or_start_time:
                session_bars.append(bar)
        return session_bars

    def _calculate_atr(self, ticker: str, period: int = 14) -> Optional[float]:
        """
        Calculate ATR(14) for a ticker.

        PHASE 1.17 FIX: Now uses get_bars_from_memory() (historical DB bars)
        first so ATR is available immediately at session open or after restart,
        not just after 14 intraday bars accumulate. Falls back to today's bars
        if historical unavailable.
        """
        bars = data_manager.get_bars_from_memory(ticker, limit=60)

        if not bars or len(bars) < 5:
            bars = data_manager.get_today_session_bars(ticker)

        if not bars or len(bars) < 2:
            return None

        true_ranges = []
        for i in range(1, min(len(bars), period + 1)):
            high       = bars[i]['high']
            low        = bars[i]['low']
            prev_close = bars[i - 1]['close']
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low  - prev_close)
            )
            true_ranges.append(tr)

        if not true_ranges:
            return None

        return float(np.mean(true_ranges))


# ========================================
# GLOBAL INSTANCE
# ========================================
or_detector = OpeningRangeDetector()


# ========================================
# CONVENIENCE FUNCTIONS
# ========================================
def classify_or(ticker: str) -> Optional[Dict]:
    """Classify Opening Range for a ticker."""
    return or_detector.classify_or(ticker)


def get_session_levels(ticker: str) -> Dict:
    """Get session-anchored high/low/open since 9:30 AM."""
    return or_detector.get_session_levels(ticker)


def should_alert_or_forming(ticker: str) -> bool:
    """Check if OR forming alert should be sent (9:38 AM for tight OR)."""
    return or_detector.should_alert_or_forming(ticker)


def adjust_signal_for_or(signal: Dict) -> Dict:
    """Adjust signal confidence based on OR classification."""
    return or_detector.adjust_signal_confidence(signal)


def get_scan_frequency(ticker: str) -> int:
    """Get recommended scan frequency based on OR."""
    return or_detector.get_scan_frequency(ticker)


# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    test_ticker = "SPY"
    print(f"Testing OR detection for {test_ticker}...\n")
    or_data = classify_or(test_ticker)
    if or_data:
        print(f"\nOR Classification:")
        print(f"  Ticker:          {or_data['ticker']}")
        print(f"  Range:           ${or_data['or_range']} ({or_data['or_range_pct']}%)")
        print(f"  ATR:             ${or_data['atr']}")
        print(f"  ATR Ratio:       {or_data['or_range_atr']}x")
        print(f"  Classification:  {or_data['classification']}")
        print(f"  Bars used:       {or_data['bar_count']}")
        print(f"  Scan Frequency:  {or_data['scan_frequency']}s")
        print(f"  Confidence Adj:  +{or_data['confidence_adjustment']*100:.0f}%")
        print(f"  Min Confidence:  {or_data['min_confidence']*100:.0f}%")

        levels = get_session_levels(test_ticker)
        if levels:
            print(f"\nSession Levels:")
            print(f"  Session High: ${levels['session_high']}")
            print(f"  Session Low:  ${levels['session_low']}")
            print(f"  Session Open: ${levels['session_open']}")
            print(f"  Bars:         {levels['bar_count']}")
    else:
        print("OR not yet complete or insufficient data")
