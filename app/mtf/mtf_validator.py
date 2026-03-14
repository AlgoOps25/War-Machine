"""
Multi-Timeframe (MTF) Trend Validator

Responsibilities:
  - Validate signals across multiple timeframes (1m, 5m, 15m, 30m)
  - Check for bullish/bearish trend alignment across TFs
  - Analyze volume profile consistency
  - Detect divergences that invalidate signals
  - Boost confidence when all TFs align

Impact: Reduce false breakouts, cleaner entries, higher win rate

NOTE: Direction convention — sniper.py uses 'bull'/'bear'.
      This module normalises to 'BUY'/'SELL' internally via _norm_direction().
      Always pass sniper direction strings; normalisation is automatic.

MOVED: app/signals/mtf_validator.py → app/mtf/mtf_validator.py
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np

from app.data.data_manager import data_manager

ET = ZoneInfo("America/New_York")

# Direction normaliser — sniper uses 'bull'/'bear'; this module uses 'BUY'/'SELL'
_DIR_MAP = {'bull': 'BUY', 'bear': 'SELL', 'BUY': 'BUY', 'SELL': 'SELL'}

def _norm_direction(direction: str) -> str:
    """Normalise 'bull'/'bear' -> 'BUY'/'SELL'. Passes through already-normalised values."""
    return _DIR_MAP.get(direction, direction.upper())


class MTFTrendValidator:
    """
    Multi-Timeframe trend validator for signal confirmation.

    Checks signal across 4 timeframes:
      - 1m: Entry precision
      - 5m: Primary signal timeframe
      - 15m: Trend confirmation
      - 30m: Macro trend alignment

    Scoring System:
      - Each TF gets 0-10 score based on:
        * Price action (higher highs/lower lows)
        * Volume confirmation
        * Momentum (RSI, slope)
      - Overall score: Weighted average (30m=35%, 15m=30%, 5m=25%, 1m=10%)
      - Confidence boost: +0-15% based on alignment
    """

    def __init__(self):
        self.timeframes = ['1m', '5m', '15m', '30m']
        self.weights = {
            '30m': 0.35,
            '15m': 0.30,
            '5m':  0.25,
            '1m':  0.10
        }
        self.min_bars = {'1m': 20, '5m': 12, '15m': 8, '30m': 6}
        self.min_overall_score = 6.0
        self.strong_alignment_threshold = 8.0
        print("[MTF-TREND] Multi-Timeframe Trend Validator initialized")
        print(f"[MTF-TREND] Timeframes: {', '.join(self.timeframes)}")

    def validate_signal(self, ticker: str, direction: str, entry_price: float) -> Dict:
        """
        Validate signal trend alignment across 1m/5m/15m/30m.

        Args:
            ticker:      Stock ticker
            direction:   'bull' or 'bear' (sniper convention) — normalised internally
            entry_price: Signal entry price

        Returns:
            Dict with keys: passes, overall_score, tf_scores, confidence_boost,
                            divergences, summary, timestamp
        """
        direction = _norm_direction(direction)

        bars_1m = data_manager.get_today_session_bars(ticker)
        bars_5m = data_manager.get_today_5m_bars(ticker)
        bars_15m = self._aggregate_to_15m(bars_1m) if bars_1m else []
        bars_30m = self._aggregate_to_30m(bars_1m) if bars_1m else []

        score_1m  = self._score_timeframe(bars_1m,  direction, entry_price, '1m')
        score_5m  = self._score_timeframe(bars_5m,  direction, entry_price, '5m')
        score_15m = self._score_timeframe(bars_15m, direction, entry_price, '15m')
        score_30m = self._score_timeframe(bars_30m, direction, entry_price, '30m')

        overall_score = (
            score_30m * self.weights['30m'] +
            score_15m * self.weights['15m'] +
            score_5m  * self.weights['5m']  +
            score_1m  * self.weights['1m']
        )

        passes = overall_score >= self.min_overall_score

        if overall_score >= self.strong_alignment_threshold:
            confidence_boost = 0.15
        elif overall_score >= 7.0:
            confidence_boost = 0.10
        elif overall_score >= 6.0:
            confidence_boost = 0.05
        else:
            confidence_boost = 0.0

        divergences = self._detect_divergences(
            scores={'1m': score_1m, '5m': score_5m, '15m': score_15m, '30m': score_30m},
            direction=direction
        )

        if divergences:
            confidence_boost = max(0, confidence_boost - 0.05)

        result = {
            'ticker': ticker,
            'direction': direction,
            'passes': passes,
            'overall_score': round(overall_score, 1),
            'tf_scores': {
                '1m':  round(score_1m,  1),
                '5m':  round(score_5m,  1),
                '15m': round(score_15m, 1),
                '30m': round(score_30m, 1)
            },
            'confidence_boost': confidence_boost,
            'divergences': divergences,
            'summary': self._generate_summary(overall_score, divergences),
            'timestamp': datetime.now(ET).isoformat()
        }

        emoji = "\u2705" if passes else "\u274c"
        print(f"[MTF-TREND] {ticker} {emoji} | Score: {overall_score:.1f}/10 | "
              f"30m:{score_30m:.1f} 15m:{score_15m:.1f} 5m:{score_5m:.1f} 1m:{score_1m:.1f}")
        if divergences:
            print(f"[MTF-TREND]   \u26a0\ufe0f  Divergences: {', '.join(divergences)}")
        if confidence_boost > 0:
            print(f"[MTF-TREND]   \U0001f4c8 Confidence Boost: +{confidence_boost*100:.0f}%")

        return result

    # ── scoring helpers ──────────────────────────────────────────────────────

    def _score_timeframe(self, bars: List[Dict], direction: str, entry_price: float, tf: str) -> float:
        if not bars or len(bars) < self.min_bars.get(tf, 5):
            return 0.0
        score  = self._score_price_action(bars, direction, entry_price)
        score += self._score_volume_profile(bars, direction)
        score += self._score_momentum(bars, direction)
        return min(10.0, score)

    def _score_price_action(self, bars: List[Dict], direction: str, entry_price: float) -> float:
        if len(bars) < 5:
            return 0.0
        score = 0.0
        recent = bars[-10:]
        highs = [b['high']  for b in recent]
        lows  = [b['low']   for b in recent]
        ma10  = np.mean([b['close'] for b in recent])
        if direction == 'BUY':
            if highs[-1] > highs[-3] > highs[-5]: score += 1.5
            if lows[-1]  > lows[-3]  > lows[-5]:  score += 1.5
            if bars[-1]['close'] > ma10:           score += 1.0
        else:
            if highs[-1] < highs[-3] < highs[-5]: score += 1.5
            if lows[-1]  < lows[-3]  < lows[-5]:  score += 1.5
            if bars[-1]['close'] < ma10:           score += 1.0
        return min(4.0, score)

    def _score_volume_profile(self, bars: List[Dict], direction: str) -> float:
        if len(bars) < 5:
            return 0.0
        score   = 0.0
        recent  = bars[-10:]
        volumes = [b['volume'] for b in recent]
        avg_vol = np.mean(volumes)
        cur_vol = bars[-1]['volume']
        if cur_vol > avg_vol * 1.5:
            score += 2.0
        elif cur_vol > avg_vol:
            score += 1.0
        rv = volumes[-3:]
        if np.mean(rv[-2:]) > np.mean(rv[:2]):
            score += 1.0
        return min(3.0, score)

    def _score_momentum(self, bars: List[Dict], direction: str) -> float:
        if len(bars) < 14:
            return 0.0
        score  = 0.0
        closes = [b['close'] for b in bars[-14:]]
        gains, losses = [], []
        for i in range(1, len(closes)):
            chg = closes[i] - closes[i - 1]
            gains.append(chg  if chg > 0 else 0)
            losses.append(-chg if chg < 0 else 0)
        avg_gain = np.mean(gains)  if gains  else 0
        avg_loss = np.mean(losses) if losses else 0
        rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
        if direction == 'BUY':
            score += 1.5 if 40 <= rsi <= 70 else (1.0 if rsi > 50 else 0)
        else:
            score += 1.5 if 30 <= rsi <= 60 else (1.0 if rsi < 50 else 0)
        recent5 = closes[-5:]
        slope   = np.polyfit(range(len(recent5)), recent5, 1)[0]
        if (direction == 'BUY' and slope > 0) or (direction == 'SELL' and slope < 0):
            score += 1.0
        last = bars[-1]
        rng  = last['high'] - last['low']
        if rng > 0 and abs(last['close'] - last['open']) / rng > 0.7:
            score += 0.5
        return min(3.0, score)

    def _detect_divergences(self, scores: Dict[str, float], direction: str) -> List[str]:
        div = []
        if scores['30m'] < 4.0: div.append("30m weak trend")
        if scores['15m'] < 4.0: div.append("15m weak trend")
        if abs(scores['30m'] - scores['5m']) > 4.0: div.append("30m/5m misalignment")
        if abs(scores['15m'] - scores['5m']) > 4.0: div.append("15m/5m misalignment")
        return div

    def _generate_summary(self, overall_score: float, divergences: List[str]) -> str:
        if divergences:
            return f"\u26a0\ufe0f MTF Score: {overall_score:.1f}/10 | Divergences: {', '.join(divergences)}"
        elif overall_score >= 8.0:
            return f"\u2705 Strong MTF alignment ({overall_score:.1f}/10) - All TFs confirm"
        elif overall_score >= 6.0:
            return f"\u2705 Good MTF alignment ({overall_score:.1f}/10) - Signal confirmed"
        else:
            return f"\u274c Weak MTF alignment ({overall_score:.1f}/10) - Signal rejected"

    # ── bar aggregation ──────────────────────────────────────────────────────

    def _aggregate_to_15m(self, bars_1m: List[Dict]) -> List[Dict]:
        if not bars_1m or len(bars_1m) < 15:
            return []
        out = []
        for i in range(0, len(bars_1m), 15):
            chunk = bars_1m[i:i + 15]
            if len(chunk) < 15:
                continue
            out.append({'timestamp': chunk[0]['timestamp'],
                        'open':   chunk[0]['open'],
                        'high':   max(b['high']   for b in chunk),
                        'low':    min(b['low']    for b in chunk),
                        'close':  chunk[-1]['close'],
                        'volume': sum(b['volume'] for b in chunk)})
        return out

    def _aggregate_to_30m(self, bars_1m: List[Dict]) -> List[Dict]:
        if not bars_1m or len(bars_1m) < 30:
            return []
        out = []
        for i in range(0, len(bars_1m), 30):
            chunk = bars_1m[i:i + 30]
            if len(chunk) < 30:
                continue
            out.append({'timestamp': chunk[0]['timestamp'],
                        'open':   chunk[0]['open'],
                        'high':   max(b['high']   for b in chunk),
                        'low':    min(b['low']    for b in chunk),
                        'close':  chunk[-1]['close'],
                        'volume': sum(b['volume'] for b in chunk)})
        return out


# ── module-level accessor (lazy singleton) ───────────────────────────────────
_mtf_trend_validator: Optional[MTFTrendValidator] = None

def get_mtf_trend_validator() -> MTFTrendValidator:
    """Return singleton MTFTrendValidator. Safe to call at import time."""
    global _mtf_trend_validator
    if _mtf_trend_validator is None:
        _mtf_trend_validator = MTFTrendValidator()
    return _mtf_trend_validator


def validate_signal_mtf(ticker: str, direction: str, entry_price: float) -> Dict:
    """Convenience wrapper — validates signal trend alignment across 1m/5m/15m/30m."""
    return get_mtf_trend_validator().validate_signal(ticker, direction, entry_price)


# Keep legacy name so any future scripts that imported the old module still work
MTFValidator = MTFTrendValidator
mtf_validator = get_mtf_trend_validator()
