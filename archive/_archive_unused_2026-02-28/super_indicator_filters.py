"""
New Technical Indicator Filters
Add to indicator_filters.py
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from datetime import time

class SuperIndicatorFilters:
    """Extended filters for super indicator combo"""
    
    @staticmethod
    def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
        """
        Calculate SuperTrend indicator
        
        Args:
            df: DataFrame with high, low, close, atr columns
            period: ATR period (default 10)
            multiplier: ATR multiplier (default 3.0)
            
        Returns:
            DataFrame with supertrend and supertrend_direction columns
        """
        hl2 = (df['high'] + df['low']) / 2
        
        # Calculate basic bands
        upper_band = hl2 + (multiplier * df['atr'])
        lower_band = hl2 - (multiplier * df['atr'])
        
        # Initialize
        supertrend = [0.0] * len(df)
        direction = [1] * len(df)  # 1 = uptrend, -1 = downtrend
        
        for i in range(1, len(df)):
            # Update bands
            if df['close'].iloc[i-1] <= upper_band.iloc[i-1]:
                upper_band.iloc[i] = min(upper_band.iloc[i], upper_band.iloc[i-1])
            
            if df['close'].iloc[i-1] >= lower_band.iloc[i-1]:
                lower_band.iloc[i] = max(lower_band.iloc[i], lower_band.iloc[i-1])
            
            # Determine trend
            if df['close'].iloc[i] <= upper_band.iloc[i]:
                direction[i] = -1
                supertrend[i] = upper_band.iloc[i]
            else:
                direction[i] = 1
                supertrend[i] = lower_band.iloc[i]
        
        df['supertrend'] = supertrend
        df['supertrend_direction'] = direction
        return df
    
    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate VWAP (Volume Weighted Average Price)
        Resets daily for intraday data
        
        Args:
            df: DataFrame with high, low, close, volume, datetime columns
            
        Returns:
            DataFrame with vwap column
        """
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['tp_volume'] = df['typical_price'] * df['volume']
        
        # Group by date for daily reset
        if 'datetime' in df.columns:
            df['date'] = pd.to_datetime(df['datetime']).dt.date
            df['vwap'] = df.groupby('date')['tp_volume'].cumsum() / df.groupby('date')['volume'].cumsum()
        else:
            # No date grouping - cumulative VWAP
            df['vwap'] = df['tp_volume'].cumsum() / df['volume'].cumsum()
        
        return df
    
    @staticmethod
    def calculate_ema_200(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate 200-period EMA
        
        Args:
            df: DataFrame with close column
            
        Returns:
            DataFrame with ema_200 column
        """
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        return df
    
    @staticmethod
    def supertrend_alignment(df: pd.DataFrame, signal: Dict) -> bool:
        """
        Filter: Price must align with SuperTrend direction
        
        Bullish: Price > SuperTrend (direction = 1)
        Bearish: Price < SuperTrend (direction = -1)
        """
        if 'supertrend_direction' not in df.columns:
            df = SuperIndicatorFilters.calculate_supertrend(df)
        
        signal_type = signal.get('type', '').upper()
        latest_direction = df['supertrend_direction'].iloc[-1]
        
        if signal_type == 'BREAKOUT':
            return latest_direction == 1  # Uptrend
        elif signal_type == 'BREAKDOWN':
            return latest_direction == -1  # Downtrend
        
        return False
    
    @staticmethod
    def vwap_position(df: pd.DataFrame, signal: Dict) -> bool:
        """
        Filter: Price must be on correct side of VWAP
        
        Bullish: Price > VWAP (institutional buying)
        Bearish: Price < VWAP (institutional selling)
        """
        if 'vwap' not in df.columns:
            df = SuperIndicatorFilters.calculate_vwap(df)
        
        signal_type = signal.get('type', '').upper()
        latest_close = df['close'].iloc[-1]
        latest_vwap = df['vwap'].iloc[-1]
        
        if pd.isna(latest_vwap):
            return False
        
        if signal_type == 'BREAKOUT':
            return latest_close > latest_vwap
        elif signal_type == 'BREAKDOWN':
            return latest_close < latest_vwap
        
        return False
    
    @staticmethod
    def ema_200_alignment(df: pd.DataFrame, signal: Dict) -> bool:
        """
        Filter: Price must align with 200 EMA (major trend)
        
        Bullish: Price > 200 EMA
        Bearish: Price < 200 EMA
        """
        if len(df) < 200:
            return False  # Not enough data
        
        if 'ema_200' not in df.columns:
            df = SuperIndicatorFilters.calculate_ema_200(df)
        
        signal_type = signal.get('type', '').upper()
        latest_close = df['close'].iloc[-1]
        latest_ema = df['ema_200'].iloc[-1]
        
        if pd.isna(latest_ema):
            return False
        
        if signal_type == 'BREAKOUT':
            return latest_close > latest_ema
        elif signal_type == 'BREAKDOWN':
            return latest_close < latest_ema
        
        return False
    
    @staticmethod
    def time_filter(df: pd.DataFrame, signal: Dict) -> bool:
        """
        Filter: Signal must occur during prime trading hours
        
        Best times:
        - 9:30-10:30 AM: Market open (high volume)
        - 10:30 AM-3:30 PM: Midday moves
        - 3:30-4:00 PM: Close (high volume)
        
        Avoid: 12:00-1:00 PM (lunch low volume)
        """
        signal_time = signal.get('timestamp')
        if signal_time is None:
            return True  # No time info, allow
        
        if isinstance(signal_time, str):
            signal_time = pd.to_datetime(signal_time)
        
        hour = signal_time.hour
        minute = signal_time.minute
        
        # Market hours: 9:30 AM - 4:00 PM EST
        market_open = time(9, 30)
        lunch_start = time(12, 0)
        lunch_end = time(13, 0)
        market_close = time(16, 0)
        
        signal_time_only = signal_time.time()
        
        # Must be during market hours
        if signal_time_only < market_open or signal_time_only >= market_close:
            return False
        
        # Avoid lunch hour
        if lunch_start <= signal_time_only < lunch_end:
            return False
        
        return True

# Register new filters
SUPER_FILTERS = {
    'supertrend_alignment': SuperIndicatorFilters.supertrend_alignment,
    'vwap_position': SuperIndicatorFilters.vwap_position,
    'ema_200_alignment': SuperIndicatorFilters.ema_200_alignment,
    'time_filter': SuperIndicatorFilters.time_filter,
}
