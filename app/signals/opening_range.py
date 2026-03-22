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

PHASE B1 (MAR 12, 2026):
  - classify_secondary_range(): 10:00-10:30 Power Hour consolidation range.
    Provides a mid-session BOS anchor when the 9:30 OR is stale (no signal fired
    by 10:00) or after a confirmed OR breakout exhausts and price re-consolidates.
  - get_secondary_range_levels(): convenience function returns sr_high/sr_low for
    use in sniper.py detect_breakout_after_or() equivalent on the second range.
  - Secondary range is only computed once the 10:30 window closes.
    Before 10:30 the function returns None to avoid premature classification.
  - Classifications: SECONDARY_TIGHT / SECONDARY_NORMAL / SECONDARY_WIDE
    (same ATR ratio thresholds as primary OR).
  - Cache is per-session, never expires (window is immutable after 10:30).

PHASE B1 BUG FIX (MAR 17, 2026):
  BUG #6: _extract_secondary_bars() called dt.time() on tz-aware datetimes without
           first converting to ET. A UTC-aware bar at 14:05 UTC (= 10:05 ET) read as
           14:05 and was excluded from the 10:00-10:30 window, allowing outlier/premarket
           bars with corrupted prices (e.g. $1336.72 for TSEM) to slip through instead.
           Fix 1: Convert dt to ET before calling .time() in _extract_secondary_bars().
           Fix 2: Price sanity clamp — reject any bar where high > sr_low_estimate * 5
                  to guard against future tick/timestamp corruption in price fields.
           Same ET-coercion fix applied to _extract_or_bars() and _extract_session_bars()
           for consistency (those paths were less affected due to earlier window times).
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import numpy as np

from app.data.data_manager import data_manager
import logging
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# How long (minutes) a DYNAMIC cache entry is valid before re-evaluation.
# TIGHT/NORMAL/WIDE entries never expire (the true 9:30-9:40 window is immutable).
OR_CACHE_DYNAMIC_TTL = timedelta(minutes=30)

# Price sanity multiplier for secondary range bars.
# Any bar whose high exceeds (median_close * SR_PRICE_SANITY_MULT) is discarded
# as a corrupted tick/timestamp-leaked-into-price value.
SR_PRICE_SANITY_MULT = 5.0


def _to_et_time(dt) -> Optional[time]:
    """
    Return the ET wall-clock time for a datetime that may be:
      - tz-aware (any tz)  → convert to ET first
      - tz-naive           → assume already ET
      - a string           → parse via fromisoformat, then convert

    Returns None if dt is None or unparseable.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(ET)
    return dt.time()


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

    Phase B1 additions:
      - classify_secondary_range(): 10:00-10:30 Power Hour range (immutable after 10:30).
      - get_secondary_range_levels(): returns sr_high/sr_low/sr_range_pct dict.

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

        # Secondary range cache (Phase B1)
        # Structure: ticker -> secondary range result dict (immutable once set)
        self.sr_cache: Dict[str, Dict] = {}

        logger.info("[OR] Opening Range Detector initialized")
        logger.info(f"[OR] Window: 9:30-9:40 AM ET (10 minutes)")
        logger.info(f"[OR] Thresholds: TIGHT<{self.tight_threshold} ATR, WIDE>{self.wide_threshold} ATR")
        logger.info(f"[OR] Scan frequencies: Tight={self.scan_freq_tight}s, Normal={self.scan_freq_normal}s")
        logger.info(f"[OR] Mid-session fallback: DYNAMIC range (9:30->now) if OR missed")
        logger.info(f"[OR] DYNAMIC cache TTL: {int(OR_CACHE_DYNAMIC_TTL.total_seconds() // 60)} min")
        logger.info(f"[OR] Secondary Range: 10:00-10:30 AM ET (Power Hour) — Phase B1")

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
            logger.info(f"[OR] {ticker} DYNAMIC cache expired — re-evaluating with accumulated bars")
            del self.or_cache[ticker]

        # ── Get today's session bars ──────────────────────────────────
        bars_1m = data_manager.get_today_session_bars(ticker)

        if not bars_1m:
            logger.info(f"[OR] {ticker} - No session bars available")
            return None

        # ── Try to extract the real 9:30-9:40 OR first ───────────────────
        or_bars = self._extract_or_bars(bars_1m)

        if or_bars:
            # Happy path — OR window was captured (or was just re-evaluated and
            # enough bars now exist to build a real OR)
            return self._classify_from_bars(ticker, or_bars, classification_label=None,
                                            current_time=current_time)

        # ── Fallback: mid-session restart, OR was missed ──────────────
        logger.info(f"[OR] {ticker} - OR window missed (mid-session restart) — using DYNAMIC session range")
        session_bars = self._extract_session_bars(bars_1m)

        if not session_bars:
            logger.info(f"[OR] {ticker} - No bars found in session window (9:30->now)")
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

    # ------------------------------------------------------------------
    # PHASE B1: SECONDARY RANGE (10:00-10:30 Power Hour)
    # ------------------------------------------------------------------

    def classify_secondary_range(
        self,
        ticker: str,
        current_time: Optional[datetime] = None,
    ) -> Optional[Dict]:
        """
        Classify the 10:00-10:30 AM ET 'Power Hour' consolidation range.

        This provides a mid-session BOS anchor when:
          - The 9:30 OR produced no signal before 10:00, OR
          - Price has exhausted the initial OR move and re-consolidated

        Only evaluated AFTER the 10:30 window closes.  Before 10:30 returns None.
        Result is cached permanently (the window is immutable).

        Classifications (same ATR ratio logic as primary OR):
          SECONDARY_TIGHT  : < 0.5 ATR  — strong compression, breakout likely
          SECONDARY_NORMAL : 0.5-1.5 ATR — standard mid-day range
          SECONDARY_WIDE   : > 1.5 ATR   — choppy; require higher confidence

        Returns dict with keys:
            sr_high, sr_low, sr_range, sr_range_pct, sr_range_atr,
            classification, bar_count, timestamp
        or None if:
            - Before 10:30 AM
            - Fewer than SECONDARY_RANGE_MIN_BARS bars in the window
            - Range < SECONDARY_RANGE_MIN_PCT (too tight to be useful)
        """
        if current_time is None:
            current_time = datetime.now(ET)

        from utils import config

        # Window not yet closed
        if current_time.time() < config.SECONDARY_RANGE_END:
            return None

        # Return cached result
        if ticker in self.sr_cache:
            return self.sr_cache[ticker]

        bars_1m = data_manager.get_today_session_bars(ticker)
        if not bars_1m:
            return None

        sr_bars = self._extract_secondary_bars(bars_1m)

        if len(sr_bars) < config.SECONDARY_RANGE_MIN_BARS:
            print(
                f"[OR-SR] {ticker} — only {len(sr_bars)} bars in 10:00-10:30 "
                f"(need {config.SECONDARY_RANGE_MIN_BARS}) — skipping secondary range"
            )
            return None

        # ── Price sanity clamp (Phase B1 Bug Fix #6) ─────────────────
        # Estimate a reference price from the median close of valid bars,
        # then discard any bar whose high exceeds reference * SR_PRICE_SANITY_MULT.
        # This catches timestamp-leaked-into-price corruption (e.g. $1336 for TSEM).
        closes = [b["close"] for b in sr_bars if b.get("close") and b["close"] > 0]
        if closes:
            ref_price = float(np.median(closes))
            sane_bars = [
                b for b in sr_bars
                if b.get("high", 0) <= ref_price * SR_PRICE_SANITY_MULT
                and b.get("low",  0) >= ref_price / SR_PRICE_SANITY_MULT
            ]
            discarded = len(sr_bars) - len(sane_bars)
            if discarded > 0:
                print(
                    f"[OR-SR] {ticker} ⚠️  Discarded {discarded} bar(s) with "
                    f"corrupted price (ref=${ref_price:.2f}, mult={SR_PRICE_SANITY_MULT}x)"
                )
            sr_bars = sane_bars

        if len(sr_bars) < config.SECONDARY_RANGE_MIN_BARS:
            print(
                f"[OR-SR] {ticker} — only {len(sr_bars)} sane bars after price clamp "
                f"(need {config.SECONDARY_RANGE_MIN_BARS}) — skipping secondary range"
            )
            return None

        sr_high     = max(b["high"] for b in sr_bars)
        sr_low      = min(b["low"]  for b in sr_bars)
        sr_range    = sr_high - sr_low
        sr_range_pct = (sr_range / sr_low) * 100 if sr_low > 0 else 0

        if (sr_range / sr_low) < config.SECONDARY_RANGE_MIN_PCT:
            print(
                f"[OR-SR] {ticker} — secondary range {sr_range_pct:.2f}% "
                f"< min {config.SECONDARY_RANGE_MIN_PCT*100:.1f}% — too tight, skipping"
            )
            return None

        atr = self._calculate_atr(ticker)
        sr_range_atr = (sr_range / atr) if atr and atr > 0 else 0.0

        if sr_range_atr < self.tight_threshold:
            classification = "SECONDARY_TIGHT"
        elif sr_range_atr > self.wide_threshold:
            classification = "SECONDARY_WIDE"
        else:
            classification = "SECONDARY_NORMAL"

        result = {
            "ticker":        ticker,
            "sr_high":       round(sr_high, 4),
            "sr_low":        round(sr_low, 4),
            "sr_range":      round(sr_range, 4),
            "sr_range_pct":  round(sr_range_pct, 3),
            "sr_range_atr":  round(sr_range_atr, 3),
            "classification": classification,
            "bar_count":     len(sr_bars),
            "timestamp":     current_time.isoformat(),
        }

        self.sr_cache[ticker] = result

        emoji_map = {
            "SECONDARY_TIGHT":  "\U0001f3af",
            "SECONDARY_NORMAL": "\u2705",
            "SECONDARY_WIDE":   "\u26a0\ufe0f",
        }
        emoji = emoji_map.get(classification, "\u2705")
        print(
            f"[OR-SR] {ticker} {emoji} {classification} | "
            f"Range: ${sr_range:.3f} ({sr_range_pct:.2f}%) | "
            f"ATR Ratio: {sr_range_atr:.2f}x | Bars: {len(sr_bars)} | "
            f"Level: ${sr_low:.2f}\u2014${sr_high:.2f}"
        )

        return result

    def get_secondary_range_levels(self, ticker: str) -> Dict:
        """
        Return secondary range high/low for use as BOS anchor in sniper.py.

        Returns:
            {
              'sr_high':       float,
              'sr_low':        float,
              'sr_range_pct':  float,   # % width
              'classification': str,
              'bar_count':     int
            }
            or {} if secondary range not yet available or insufficient data.
        """
        sr = self.classify_secondary_range(ticker)
        if sr is None:
            return {}
        return {
            "sr_high":        sr["sr_high"],
            "sr_low":         sr["sr_low"],
            "sr_range_pct":   sr["sr_range_pct"],
            "classification": sr["classification"],
            "bar_count":      sr["bar_count"],
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
        """Clear OR and secondary range caches (called at market open for new session)."""
        or_count    = len(self.or_cache)
        alert_count = len(self.alerts_sent)
        sr_count    = len(self.sr_cache)
        self.or_cache.clear()
        self.alerts_sent.clear()
        self.sr_cache.clear()
        print(
            f"[OR] Session cache cleared "
            f"({or_count} OR entries, {sr_count} secondary entries, {alert_count} alerts reset)"
        )

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

        # Append secondary range summary if window has closed
        if current_time.time() >= time(10, 30):
            sr_lines = []
            for ticker in tickers:
                sr = self.sr_cache.get(ticker)
                if sr:
                    sr_lines.append(
                        f"  \u2022 {ticker} {sr['classification']} "
                        f"${sr['sr_low']:.2f}\u2014${sr['sr_high']:.2f} "
                        f"({sr['sr_range_pct']:.2f}%)"
                    )
            if sr_lines:
                summary += "\U0001f552 **SECONDARY RANGE (10:00-10:30)**:\n"
                summary += "\n".join(sr_lines) + "\n\n"

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
            logger.info(f"[OR] {ticker} - Could not calculate ATR")
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
            logger.info(f"[OR]   \U0001f680 Expansion breakout likely — scanning every {scan_frequency}s")
            logger.info(f"[OR]   \U0001f4c8 Confidence boost: +{confidence_adjustment*100:.0f}%")
        elif classification == 'WIDE':
            logger.info(f"[OR]   \u23f3 Consolidation likely — min confidence raised to {min_confidence*100:.0f}%")
        elif classification == 'DYNAMIC':
            logger.info(f"[OR]   \U0001f504 Mid-session fallback — {len(bars)} bars from 9:30 used as range")
            logger.info(f"[OR]   \U0001f551 Will re-evaluate in {int(OR_CACHE_DYNAMIC_TTL.total_seconds() // 60)} min")

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

        PHASE B1 FIX: Use _to_et_time() so tz-aware UTC datetimes are correctly
        converted to ET before the window comparison.
        """
        if end_time is None:
            end_time = self.or_end_time

        or_bars = []
        for bar in bars_1m:
            bar_time = _to_et_time(bar.get('datetime'))
            if bar_time is None:
                continue
            if self.or_start_time <= bar_time < end_time:
                or_bars.append(bar)

        return or_bars

    def _extract_session_bars(self, bars_1m: List[Dict]) -> List[Dict]:
        """
        Extract all bars from 9:30 AM onwards (session bars).

        PHASE 1.17: Used as fallback when OR window was missed.
        Returns everything from 9:30 to the most recent bar.

        PHASE B1 FIX: Use _to_et_time() for correct tz handling.
        """
        session_bars = []
        for bar in bars_1m:
            bar_time = _to_et_time(bar.get('datetime'))
            if bar_time is None:
                continue
            if bar_time >= self.or_start_time:
                session_bars.append(bar)
        return session_bars

    def _extract_secondary_bars(self, bars_1m: List[Dict]) -> List[Dict]:
        """
        Extract bars within the secondary range window (10:00-10:30 ET).

        PHASE B1 BUG FIX (#6): Previously called dt.time() directly on tz-aware
        datetimes, which returned UTC wall time instead of ET wall time.
        A 10:05 AM ET bar stored as UTC (14:05) was read as 14:05 and excluded
        from the 10:00-10:30 filter — allowing out-of-window bars with corrupted
        prices to remain in sr_bars and produce wildly wrong sr_high values.

        Fix: delegate to _to_et_time() which always converts to ET before .time().
        """
        from utils import config
        sr_bars = []
        for bar in bars_1m:
            bar_time = _to_et_time(bar.get('datetime'))
            if bar_time is None:
                continue
            if config.SECONDARY_RANGE_START <= bar_time < config.SECONDARY_RANGE_END:
                sr_bars.append(bar)
        return sr_bars

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


def get_secondary_range_levels(ticker: str) -> Dict:
    """
    Phase B1: Get secondary (10:00-10:30) range high/low for use as BOS anchor.

    Returns:
        {'sr_high': float, 'sr_low': float, 'sr_range_pct': float,
         'classification': str, 'bar_count': int}
        or {} if window not yet closed or insufficient data.
    """
    return or_detector.get_secondary_range_levels(ticker)

# ========================================
# PHASE 5 #24 — OR Scanner Functions
# (extracted from app/core/sniper.py)
# ========================================
def compute_opening_range_from_bars(bars):
    """Compute OR high/low from 9:30-9:40 bars."""
    from utils.time_helpers import _bar_time
    or_bars = [b for b in bars if _bar_time(b) and time(9, 30) <= _bar_time(b) < time(9, 40)]
    if len(or_bars) < 3:
        return None, None
    return max(b["high"] for b in or_bars), min(b["low"] for b in or_bars)


def compute_premarket_range(bars):
    """Compute premarket high/low from 4:00-9:30 bars."""
    from utils.time_helpers import _bar_time
    pm_bars = [b for b in bars if _bar_time(b) and time(4, 0) <= _bar_time(b) < time(9, 30)]
    if len(pm_bars) < 10:
        return None, None
    return max(b["high"] for b in pm_bars), min(b["low"] for b in pm_bars)


def detect_breakout_after_or(bars, or_high, or_low):
    """Scan bars after 9:45 for ORB breakout. Returns (direction, idx) or (None, None)."""
    from utils.time_helpers import _bar_time
    from utils import config
    for i, bar in enumerate(bars):
        bt = _bar_time(bar)
        if bt is None or bt < time(9, 45):
            continue
        if bt >= time(11, 0):          # ← add this hard ceiling
            break
        if bar["close"] > or_high * (1 + config.ORB_BREAK_THRESHOLD):
            logger.info(f"[BREAKOUT] BULL idx {i} ${bar['close']:.2f}")
            return "bull", i
        if bar["close"] < or_low * (1 - config.ORB_BREAK_THRESHOLD):
            logger.info(f"[BREAKOUT] BEAR idx {i} ${bar['close']:.2f}")
            return "bear", i
    return None, None


def detect_fvg_after_break(bars, breakout_idx, direction):
    """Find first FVG after a breakout. Returns (fvg_low, fvg_high) or (None, None)."""
    from utils import config
    min_pct = getattr(config, 'FVG_MIN_PCT', 0.001)
    search_bars = bars[breakout_idx:]

    for i in range(2, len(search_bars)):
        c0 = search_bars[i - 2]
        c2 = search_bars[i]

        if direction == "bull":
            gap = c2["low"] - c0["high"]
            if gap > 0 and (gap / c0["high"]) >= min_pct:
                return c0["high"], c2["low"]

        elif direction == "bear":
            gap = c0["low"] - c2["high"]
            if gap > 0 and (gap / c0["low"]) >= min_pct:
                return c2["high"], c0["low"]

    return None, None

# ========================================
# USAGE EXAMPLE
# ========================================
if __name__ == "__main__":
    test_ticker = "SPY"
    logger.info(f"Testing OR detection for {test_ticker}...\n")
    or_data = classify_or(test_ticker)
    if or_data:
        logger.info(f"\nOR Classification:")
        logger.info(f"  Ticker:          {or_data['ticker']}")
        logger.info(f"  Range:           ${or_data['or_range']} ({or_data['or_range_pct']}%)")
        logger.info(f"  ATR:             ${or_data['atr']}")
        logger.info(f"  ATR Ratio:       {or_data['or_range_atr']}x")
        logger.info(f"  Classification:  {or_data['classification']}")
        logger.info(f"  Bars used:       {or_data['bar_count']}")
        logger.info(f"  Scan Frequency:  {or_data['scan_frequency']}s")
        logger.info(f"  Confidence Adj:  +{or_data['confidence_adjustment']*100:.0f}%")
        logger.info(f"  Min Confidence:  {or_data['min_confidence']*100:.0f}%")

        levels = get_session_levels(test_ticker)
        if levels:
            logger.info(f"\nSession Levels:")
            logger.info(f"  Session High: ${levels['session_high']}")
            logger.info(f"  Session Low:  ${levels['session_low']}")
            logger.info(f"  Session Open: ${levels['session_open']}")
            logger.info(f"  Bars:         {levels['bar_count']}")

        sr_levels = get_secondary_range_levels(test_ticker)
        if sr_levels:
            logger.info(f"\nSecondary Range (10:00-10:30):")
            logger.info(f"  SR High:         ${sr_levels['sr_high']}")
            logger.info(f"  SR Low:          ${sr_levels['sr_low']}")
            logger.info(f"  SR Range %:      {sr_levels['sr_range_pct']}%")
            logger.info(f"  Classification:  {sr_levels['classification']}")
            logger.info(f"  Bars:            {sr_levels['bar_count']}")
        else:
            logger.info("\nSecondary Range: not yet available (before 10:30) or insufficient data")
    else:
        logger.info("OR not yet complete or insufficient data")
