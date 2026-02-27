"""
Market Filters Module
Real filter implementations for War Machine trading signals
Connects to market_memory.db and applies actual filtering logic
"""

import sqlite3
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from config import WarMachineConfig


class MarketFilters:
    """Market filtering system for War Machine"""

    def __init__(self, db_path: str = "market_memory.db"):
        self.config = WarMachineConfig()
        self.db_path = db_path

    def _get_latest_data(self, symbol: str, days: int = 30) -> Optional[pd.DataFrame]:
        """Get latest market data for a symbol from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            query = """
                SELECT date, open, high, low, close, volume
                FROM daily_bars
                WHERE symbol = ?
                AND date >= ?
                ORDER BY date DESC
                LIMIT ?
            """

            df = pd.read_sql_query(query, conn, params=(symbol, cutoff_date, days))
            conn.close()

            if df.empty:
                return None

            df['date'] = pd.to_datetime(df['date'])
            return df.sort_values('date')

        except Exception as e:
            return None

    def run_filter_combination(self, symbol: str, filter_names: List[str], filter_params: Dict) -> Dict:
        """Run multiple filters on a symbol"""
        individual_results = {}

        for filter_name in filter_names:
            params = filter_params.get(filter_name, {})
            passed = self.apply_filter(symbol, filter_name, params)
            individual_results[filter_name] = passed

        all_passed = all(individual_results.values()) if individual_results else True

        results = {
            'symbol': symbol,
            'filters_run': filter_names,
            'all_filters_passed': all_passed,
            'individual_results': individual_results
        }

        return results

    def apply_filter(self, symbol: str, filter_name: str, filter_params: Dict) -> bool:
        """Apply a single filter to a symbol"""
        df = self._get_latest_data(symbol, days=30)

        if df is None or df.empty:
            return False

        filter_method = getattr(self, f'_filter_{filter_name}', None)

        if filter_method is None:
            return True

        try:
            return filter_method(df, filter_params)
        except Exception as e:
            return False

    # ========================================
    # PRICE & VOLUME FILTERS
    # ========================================

    def _filter_price_range(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by price range"""
        min_price = params.get('min_price', 5.0)
        max_price = params.get('max_price', 500.0)
        latest_price = df['close'].iloc[-1]
        return min_price <= latest_price <= max_price

    def _filter_volume_surge(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by volume surge vs average"""
        min_surge = params.get('min_surge', 2.0)
        lookback = params.get('lookback', 20)

        if len(df) < lookback + 1:
            return False

        latest_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].iloc[-lookback-1:-1].mean()

        if avg_volume == 0:
            return False

        surge_ratio = latest_volume / avg_volume
        return surge_ratio >= min_surge

    def _filter_gap_size(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by gap size"""
        min_gap = params.get('min_gap', 2.0)
        max_gap = params.get('max_gap', 20.0)

        if len(df) < 2:
            return False

        prev_close = df['close'].iloc[-2]
        current_open = df['open'].iloc[-1]
        gap_pct = ((current_open - prev_close) / prev_close) * 100
        gap_abs = abs(gap_pct)

        return min_gap <= gap_abs <= max_gap

    def _filter_atr_threshold(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by ATR (Average True Range)"""
        min_atr = params.get('min_atr', 0.5)
        period = params.get('period', 14)

        if len(df) < period + 1:
            return False

        high = df['high']
        low = df['low']
        close_prev = df['close'].shift(1)

        tr1 = high - low
        tr2 = abs(high - close_prev)
        tr3 = abs(low - close_prev)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]

        latest_price = df['close'].iloc[-1]
        atr_pct = (atr / latest_price) * 100

        return atr_pct >= min_atr

    # ========================================
    # TECHNICAL INDICATOR FILTERS
    # ========================================

    def _filter_rsi_threshold(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by RSI"""
        min_rsi = params.get('min_rsi', 30)
        max_rsi = params.get('max_rsi', 70)
        period = params.get('period', 14)

        if len(df) < period + 1:
            return False

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        latest_rsi = rsi.iloc[-1]

        if pd.isna(latest_rsi):
            return False

        return min_rsi <= latest_rsi <= max_rsi

    def _filter_trend_alignment(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by moving average alignment"""
        fast_period = params.get('fast_period', 10)
        slow_period = params.get('slow_period', 50)

        if len(df) < slow_period:
            return False

        fast_ma = df['close'].rolling(window=fast_period).mean().iloc[-1]
        slow_ma = df['close'].rolling(window=slow_period).mean().iloc[-1]
        latest_price = df['close'].iloc[-1]

        return latest_price > fast_ma > slow_ma

    def _filter_bollinger_position(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by Bollinger Band position"""
        period = params.get('period', 20)
        std_dev = params.get('std_dev', 2.0)
        min_position = params.get('min_position', 0.0)
        max_position = params.get('max_position', 1.0)

        if len(df) < period:
            return False

        sma = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()

        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)

        latest_price = df['close'].iloc[-1]
        latest_upper = upper_band.iloc[-1]
        latest_lower = lower_band.iloc[-1]

        if latest_upper == latest_lower:
            return False

        position = (latest_price - latest_lower) / (latest_upper - latest_lower)
        return min_position <= position <= max_position

    def _filter_macd_signal(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by MACD signal"""
        fast = params.get('fast', 12)
        slow = params.get('slow', 26)
        signal = params.get('signal', 9)

        if len(df) < slow + signal:
            return False

        ema_fast = df['close'].ewm(span=fast).mean()
        ema_slow = df['close'].ewm(span=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()

        return macd_line.iloc[-1] > signal_line.iloc[-1]

    # ========================================
    # MARKET CONDITION FILTERS
    # ========================================

    def _filter_time_of_day(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by time of day (always passes for EOD data)"""
        return True

    def _filter_vix_level(self, df: pd.DataFrame, params: Dict) -> bool:
        """Filter by VIX level"""
        min_vix = params.get('min_vix', 0)
        max_vix = params.get('max_vix', 100)

        vix_df = self._get_latest_data('^VIX', days=5)

        if vix_df is None or vix_df.empty:
            return True

        latest_vix = vix_df['close'].iloc[-1]
        return min_vix <= latest_vix <= max_vix


# ========================================
# MODULE-LEVEL FUNCTION (NOT IN CLASS!)
# ========================================

def get_available_filters():
    """Get list of all available filters"""
    return [
        'price_range',
        'volume_surge',
        'gap_size',
        'atr_threshold',
        'rsi_threshold',
        'trend_alignment',
        'bollinger_position',
        'macd_signal',
        'time_of_day',
        'vix_level',
    ]
