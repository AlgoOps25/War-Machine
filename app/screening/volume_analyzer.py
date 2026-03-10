"""
Real-Time Volume Top/Bottom Detector
Tracks live volume patterns bar-by-bar to predict exhaustion and reversal points.

Key Patterns:
  1. Bottom Volume: Volume dries up (20-30% of avg) + price compression → reversal
  2. Peak Volume: Volume spike (200%+ of avg) + price extension → exhaustion/top
  3. Volume Divergence: Price makes new high/low but volume declines → reversal warning

Use Case:
  - Intraday: Detect when a breakout is running out of gas (exit signals)
  - Reversals: Catch the exact bar where accumulation/distribution begins
"""
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import statistics
from app.data.db_connection import get_connection, ph


class VolumeState:
    """Track volume state for a single ticker."""

    def __init__(self, ticker: str, lookback_bars: int = 20):
        self.ticker = ticker
        self.lookback_bars = lookback_bars
        self.volume_history: List[int] = []
        self.price_history: List[float] = []
        self.timestamp_history: List[datetime] = []

        self.avg_volume: float = 0
        self.current_volume: int = 0
        self.volume_ratio: float = 0

        self.is_bottom_volume = False
        self.is_peak_volume = False
        self.consecutive_low_vol_bars = 0
        self.consecutive_high_vol_bars = 0

        self.price_direction = "neutral"
        self.volume_trend = "neutral"

    def update(self, price: float, volume: int, timestamp: datetime):
        self.price_history.append(price)
        self.volume_history.append(volume)
        self.timestamp_history.append(timestamp)

        if len(self.volume_history) > self.lookback_bars:
            self.price_history.pop(0)
            self.volume_history.pop(0)
            self.timestamp_history.pop(0)

        self.current_volume = volume

        if len(self.volume_history) >= 5:
            self.avg_volume = statistics.mean(self.volume_history[-5:])
            self.volume_ratio = volume / self.avg_volume if self.avg_volume > 0 else 0
            self._detect_bottom_volume()
            self._detect_peak_volume()
            self._detect_divergence()
        else:
            self.avg_volume = 0
            self.volume_ratio = 0

    def _detect_bottom_volume(self):
        BOTTOM_THRESHOLD = 0.30
        if self.volume_ratio < BOTTOM_THRESHOLD:
            self.consecutive_low_vol_bars += 1
            self.is_bottom_volume = self.consecutive_low_vol_bars >= 2
        else:
            self.consecutive_low_vol_bars = 0
            self.is_bottom_volume = False

    def _detect_peak_volume(self):
        PEAK_THRESHOLD = 2.0
        if self.volume_ratio > PEAK_THRESHOLD:
            self.consecutive_high_vol_bars += 1
            self.is_peak_volume = self.consecutive_high_vol_bars >= 1
        else:
            self.consecutive_high_vol_bars = 0
            self.is_peak_volume = False

    def _detect_divergence(self):
        if len(self.price_history) < 10 or len(self.volume_history) < 10:
            return

        recent_prices = self.price_history[-5:]
        older_prices = self.price_history[-10:-5]
        recent_avg = statistics.mean(recent_prices)
        older_avg = statistics.mean(older_prices)

        if recent_avg > older_avg * 1.005:
            self.price_direction = "bull"
        elif recent_avg < older_avg * 0.995:
            self.price_direction = "bear"
        else:
            self.price_direction = "neutral"

        recent_vol = self.volume_history[-5:]
        older_vol = self.volume_history[-10:-5]
        recent_vol_avg = statistics.mean(recent_vol)
        older_vol_avg = statistics.mean(older_vol)

        if recent_vol_avg > older_vol_avg * 1.2:
            self.volume_trend = "rising"
        elif recent_vol_avg < older_vol_avg * 0.8:
            self.volume_trend = "falling"
        else:
            self.volume_trend = "neutral"

    def get_signal(self) -> Optional[Dict]:
        if self.price_direction == "bull" and self.volume_trend == "falling":
            return {
                'type': 'bearish_divergence',
                'ticker': self.ticker,
                'confidence': 75,
                'reason': 'Price making highs but volume declining',
                'action': 'exit_long_or_short',
                'timestamp': datetime.now().isoformat()
            }
        if self.price_direction == "bear" and self.volume_trend == "falling":
            return {
                'type': 'bullish_divergence',
                'ticker': self.ticker,
                'confidence': 70,
                'reason': 'Price declining but selling pressure exhausted',
                'action': 'reversal_long',
                'timestamp': datetime.now().isoformat()
            }
        if self.is_peak_volume and self.price_direction == "bull":
            return {
                'type': 'volume_climax_top',
                'ticker': self.ticker,
                'confidence': 80,
                'reason': f'Volume spike {self.volume_ratio:.1f}x avg on uptrend',
                'action': 'exit_long',
                'timestamp': datetime.now().isoformat()
            }
        if self.is_peak_volume and self.price_direction == "bear":
            return {
                'type': 'volume_climax_bottom',
                'ticker': self.ticker,
                'confidence': 75,
                'reason': f'Volume spike {self.volume_ratio:.1f}x avg on downtrend',
                'action': 'reversal_long',
                'timestamp': datetime.now().isoformat()
            }
        if self.is_bottom_volume:
            return {
                'type': 'volume_compression',
                'ticker': self.ticker,
                'confidence': 60,
                'reason': f'Volume dried up to {self.volume_ratio:.1%} of avg',
                'action': 'watch_for_breakout',
                'timestamp': datetime.now().isoformat()
            }
        return None

    def get_state_summary(self) -> Dict:
        return {
            'ticker': self.ticker,
            'current_volume': self.current_volume,
            'avg_volume': round(self.avg_volume, 0),
            'volume_ratio': round(self.volume_ratio, 2),
            'is_bottom_volume': self.is_bottom_volume,
            'is_peak_volume': self.is_peak_volume,
            'price_direction': self.price_direction,
            'volume_trend': self.volume_trend,
            'bars_tracked': len(self.volume_history)
        }


class VolumeAnalyzer:
    """Multi-ticker volume analyzer for real-time monitoring."""

    def __init__(self):
        self.tracked_tickers: Dict[str, VolumeState] = {}

    def track_ticker(self, ticker: str, lookback_bars: int = 20):
        if ticker not in self.tracked_tickers:
            self.tracked_tickers[ticker] = VolumeState(ticker, lookback_bars)
            print(f"[VOL] Tracking {ticker} (lookback={lookback_bars} bars)")

    def stop_tracking(self, ticker: str):
        if ticker in self.tracked_tickers:
            del self.tracked_tickers[ticker]
            print(f"[VOL] Stopped tracking {ticker}")

    def update_bar(self, ticker: str, price: float, volume: int, timestamp: datetime = None):
        if timestamp is None:
            timestamp = datetime.now()
        if ticker not in self.tracked_tickers:
            self.track_ticker(ticker)
        self.tracked_tickers[ticker].update(price, volume, timestamp)

    def get_active_signals(self) -> List[Dict]:
        signals = []
        for ticker, state in self.tracked_tickers.items():
            signal = state.get_signal()
            if signal:
                signals.append(signal)
        return signals

    def get_all_states(self) -> List[Dict]:
        return [state.get_state_summary() for state in self.tracked_tickers.values()]

    def get_ticker_state(self, ticker: str) -> Optional[Dict]:
        if ticker in self.tracked_tickers:
            return self.tracked_tickers[ticker].get_state_summary()
        return None

    def load_historical_bars(self, ticker: str, lookback_minutes: int = 60):
        """Load historical bars from database to initialize volume state."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                query = f"""
                    SELECT close, volume, datetime
                    FROM intraday_bars
                    WHERE ticker = {ph()}
                    ORDER BY datetime DESC
                    LIMIT {ph()}
                """
                cursor.execute(query, (ticker, lookback_minutes))
                rows = cursor.fetchall()

            if not rows:
                return

            if ticker not in self.tracked_tickers:
                self.track_ticker(ticker)

            for row in reversed(rows):
                if isinstance(row, dict):
                    close_price = row['close']
                    volume = row['volume']
                    ts = row['datetime']
                else:
                    close_price = row[0]
                    volume = row[1]
                    ts = row[2]

                if isinstance(ts, str):
                    timestamp = datetime.fromisoformat(ts)
                else:
                    timestamp = ts

                self.update_bar(ticker, close_price, volume, timestamp)

            print(f"[VOL] Loaded {len(rows)} historical bars for {ticker}")

        except Exception as e:
            print(f"[VOL] Error loading historical bars for {ticker}: {e}")

    def print_summary(self, top_n: int = 10):
        states = self.get_all_states()
        states.sort(key=lambda x: abs(x['volume_ratio'] - 1.0), reverse=True)

        print("\n" + "="*80)
        print(f"VOLUME ANALYZER - {datetime.now().strftime('%H:%M:%S')}")
        print("="*80)
        print(f"{'Ticker':<8}{'Vol Ratio':<12}{'Avg Vol':<12}{'Price Dir':<12}{'Vol Trend':<12}{'Signal'}")
        print("-"*80)

        for state in states[:top_n]:
            signal_flag = ""
            if state['is_peak_volume']:
                signal_flag = "⚠️  PEAK"
            elif state['is_bottom_volume']:
                signal_flag = "📉 BOTTOM"

            print(
                f"{state['ticker']:<8}"
                f"{state['volume_ratio']:<12.2f}"
                f"{int(state['avg_volume']):<12,}"
                f"{state['price_direction']:<12}"
                f"{state['volume_trend']:<12}"
                f"{signal_flag}"
            )

        print("="*80 + "\n")


def calculate_volume_profile(prices: List[float], volumes: List[int], num_bins: int = 10) -> Dict:
    """
    Calculate Volume Profile (volume distribution by price level).
    Used to identify high-volume nodes (support/resistance).
    """
    if not prices or not volumes or len(prices) != len(volumes):
        return {'poc': 0, 'vah': 0, 'val': 0, 'profile': []}

    min_price = min(prices)
    max_price = max(prices)
    bin_size = (max_price - min_price) / num_bins if max_price > min_price else 1

    volume_by_bin: Dict[int, int] = {}
    for price, volume in zip(prices, volumes):
        bin_idx = int((price - min_price) / bin_size) if bin_size > 0 else 0
        bin_idx = min(bin_idx, num_bins - 1)
        volume_by_bin[bin_idx] = volume_by_bin.get(bin_idx, 0) + volume

    poc_bin = max(volume_by_bin, key=volume_by_bin.get)
    poc_price = min_price + (poc_bin + 0.5) * bin_size

    total_volume = sum(volumes)
    target_volume = total_volume * 0.70
    sorted_bins = sorted(volume_by_bin.items(), key=lambda x: x[1], reverse=True)

    value_area_bins = []
    accumulated_vol = 0
    for bin_idx, vol in sorted_bins:
        value_area_bins.append(bin_idx)
        accumulated_vol += vol
        if accumulated_vol >= target_volume:
            break

    vah_bin = max(value_area_bins)
    val_bin = min(value_area_bins)
    vah_price = min_price + (vah_bin + 1) * bin_size
    val_price = min_price + val_bin * bin_size

    profile = [(min_price + (i + 0.5) * bin_size, volume_by_bin.get(i, 0)) for i in range(num_bins)]
    profile.sort(key=lambda x: x[1], reverse=True)

    return {
        'poc': round(poc_price, 2),
        'vah': round(vah_price, 2),
        'val': round(val_price, 2),
        'profile': profile[:5]
    }


if __name__ == "__main__":
    analyzer = VolumeAnalyzer()
    test_ticker = "SPY"
    analyzer.track_ticker(test_ticker)
    for i in range(10):
        analyzer.update_bar(test_ticker, 450 + i * 0.5, 1000000)
    analyzer.update_bar(test_ticker, 455, 200000)
    analyzer.update_bar(test_ticker, 455.5, 180000)
    analyzer.update_bar(test_ticker, 456, 3000000)
    analyzer.print_summary()
    signals = analyzer.get_active_signals()
    if signals:
        print("\n🚨 ACTIVE SIGNALS:")
        for sig in signals:
            print(f"  {sig['type']}: {sig['ticker']} - {sig['reason']} (conf: {sig['confidence']}%)")
