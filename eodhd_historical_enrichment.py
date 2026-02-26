"""Enrich signals with EODHD historical data for ML features."""

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

try:
    from data_manager import MarketDataManager
    EODHD_AVAILABLE = True
except ImportError:
    EODHD_AVAILABLE = False
    print("[ENRICHMENT] ⚠️ EODHD client not available")


class SignalEnricher:
    """Enriches closed signals with historical market data."""
    
    def __init__(self):
        if not EODHD_AVAILABLE:
            raise Exception("EODHD client required for enrichment")
        
        self.data_manager = MarketDataManager()
    
    def fetch_post_breakout_bars(self, ticker: str, breakout_time: datetime, num_bars: int = 3) -> Optional[pd.DataFrame]:
        """Fetch bars immediately after breakout."""
        try:
            # Get 5-minute bars for the day
            bars = self.data_manager.get_intraday_bars(
                ticker,
                start_date=breakout_time.date(),
                end_date=breakout_time.date(),
                interval='5m'
            )
            
            if bars is None or len(bars) == 0:
                return None
            
            # Find bars after breakout
            bars['time'] = pd.to_datetime(bars['timestamp'])
            after_breakout = bars[bars['time'] >= breakout_time]
            
            return after_breakout.head(num_bars)
            
        except Exception as e:
            print(f"[ANALYSIS] Error fetching post-breakout bars: {e}")
            return None
    
    def calculate_confirmation_features(self, signal: Dict, bars: pd.DataFrame) -> Dict:
        """Calculate confirmation features from post-breakout bars."""
        if bars is None or len(bars) == 0:
            return {}
        
        entry_price = signal['entry_price']
        direction = signal['direction']
        
        features = {}
        
        # Hold rate: % of bars that closed above entry (for bulls)
        if direction == 'BULL':
            bars_above = (bars['close'] > entry_price).sum()
        else:
            bars_above = (bars['close'] < entry_price).sum()
        
        features['breakout_hold_rate'] = (bars_above / len(bars)) * 100
        features['bars_above_entry'] = int(bars_above)
        
        # Volume analysis
        features['breakout_volume_ratio'] = bars.iloc[0]['volume'] / bars['volume'].mean()
        features['avg_volume_3bar'] = bars['volume'].mean()
        
        # Price action
        features['post_breakout_high'] = bars['high'].max()
        features['post_breakout_low'] = bars['low'].min()
        
        if direction == 'BULL':
            features['immediate_rejection'] = bars.iloc[0]['close'] < entry_price
        else:
            features['immediate_rejection'] = bars.iloc[0]['close'] > entry_price
        
        return features
    
    def enrich_signal(self, signal: Dict) -> Dict:
        """Enrich a single signal with historical data."""
        breakout_time = datetime.fromisoformat(signal['generated_at'])
        
        # Fetch post-breakout bars
        bars = self.fetch_post_breakout_bars(signal['ticker'], breakout_time, num_bars=3)
        
        if bars is not None and len(bars) > 0:
            features = self.calculate_confirmation_features(signal, bars)
            signal.update(features)
        
        return signal
    
    def enrich_signal_list(self, signals: List[Dict]) -> List[Dict]:
        """Enrich multiple signals."""
        enriched = []
        
        for i, signal in enumerate(signals):
            if (i + 1) % 10 == 0:
                print(f"  Enriched {i + 1}/{len(signals)} signals...")
            
            enriched_signal = self.enrich_signal(signal)
            enriched.append(enriched_signal)
        
        return enriched
    
    def build_ml_features_dataframe(self, enriched_signals: List[Dict]) -> pd.DataFrame:
        """Build ML-ready feature matrix."""
        df = pd.DataFrame(enriched_signals)
        
        # Target variable: 1 for win, 0 for loss
        df['target'] = (df['outcome'] == 'win').astype(int)
        
        # Select feature columns
        feature_cols = [
            'ticker', 'direction', 'grade', 'confidence',
            'breakout_hold_rate', 'bars_above_entry',
            'breakout_volume_ratio', 'immediate_rejection',
            'return_pct', 'hold_time_minutes', 'target'
        ]
        
        available_cols = [c for c in feature_cols if c in df.columns]
        return df[available_cols]
