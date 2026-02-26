"""
EODHD Historical Data Enrichment

Fetches comprehensive EODHD data for each historical signal:
  - Intraday bars (5m, 1m) around signal time
  - Technical indicators (RSI, ADX, MACD, BB)
  - Volume profile data
  - Options flow (if available)
  - Market regime (VIX, SPY trend)

Builds features for ML-based confirmation system.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
from zoneinfo import ZoneInfo

try:
    from eodhd_client import eodhd_client
    EODHD_AVAILABLE = True
except ImportError:
    EODHD_AVAILABLE = False
    print("[ENRICHMENT] ⚠️ EODHD client not available")

ET = ZoneInfo("America/New_York")


class SignalEnricher:
    """Enrich historical signals with EODHD data for analysis."""
    
    def __init__(self):
        """Initialize enricher."""
        if not EODHD_AVAILABLE:
            raise ImportError("EODHD client required for enrichment")
        
        self.cache = {}  # Cache EODHD responses
        print("[ENRICHMENT] ✅ Signal enricher initialized")
    
    def get_bars_around_signal(self, ticker: str, signal_time: datetime, 
                               bars_before: int = 12, bars_after: int = 5,
                               interval: str = '5m') -> Optional[pd.DataFrame]:
        """
        Fetch intraday bars around signal generation time.
        
        Args:
            ticker: Stock ticker
            signal_time: Time signal was generated
            bars_before: Bars before signal (for context)
            bars_after: Bars after signal (for confirmation analysis)
            interval: Bar interval ('5m' or '1m')
        
        Returns:
            DataFrame with OHLCV data
        """
        try:
            # EODHD intraday data
            date_str = signal_time.strftime('%Y-%m-%d')
            
            bars = eodhd_client.get_intraday_data(
                ticker=ticker,
                interval=interval,
                from_date=date_str,
                to_date=date_str
            )
            
            if not bars:
                return None
            
            df = pd.DataFrame(bars)
            df['datetime'] = pd.to_datetime(df['datetime'])
            
            # Filter to bars around signal time
            df_sorted = df.sort_values('datetime')
            signal_idx = df_sorted[df_sorted['datetime'] <= signal_time].index[-1]
            
            start_idx = max(0, signal_idx - bars_before)
            end_idx = min(len(df_sorted), signal_idx + bars_after + 1)
            
            return df_sorted.iloc[start_idx:end_idx].copy()
        
        except Exception as e:
            print(f"[ENRICHMENT] Error fetching bars: {e}")
            return None
    
    def calculate_breakout_characteristics(self, bars_df: pd.DataFrame, 
                                          entry_price: float,
                                          bars_before_signal: int = 12) -> Dict:
        """
        Calculate characteristics of breakout from bar data.
        
        Args:
            bars_df: DataFrame with OHLCV data
            entry_price: Breakout entry price
            bars_before_signal: Number of bars before signal for analysis
        
        Returns:
            Dict with breakout features
        """
        if len(bars_df) < bars_before_signal + 2:
            return {}
        
        # Split into before/after signal
        signal_idx = bars_before_signal
        before_bars = bars_df.iloc[:signal_idx]
        after_bars = bars_df.iloc[signal_idx:]
        
        features = {}
        
        # Pre-breakout characteristics
        features['consolidation_range'] = (before_bars['high'].max() - before_bars['low'].min()) / entry_price * 100
        features['avg_volume_pre'] = before_bars['volume'].mean()
        features['volume_trend_pre'] = np.polyfit(range(len(before_bars)), before_bars['volume'], 1)[0]
        
        # Breakout bar characteristics
        if len(after_bars) > 0:
            breakout_bar = after_bars.iloc[0]
            features['breakout_volume'] = breakout_bar['volume']
            features['breakout_volume_ratio'] = breakout_bar['volume'] / features['avg_volume_pre']
            features['breakout_candle_size'] = (breakout_bar['close'] - breakout_bar['open']) / breakout_bar['open'] * 100
            features['breakout_body_pct'] = abs(breakout_bar['close'] - breakout_bar['open']) / (breakout_bar['high'] - breakout_bar['low']) * 100
        
        # Post-breakout confirmation (next 5 bars)
        if len(after_bars) >= 2:
            post_bars = after_bars.iloc[1:min(6, len(after_bars))]
            
            # How many bars held above entry?
            features['bars_above_entry'] = sum(post_bars['close'] > entry_price)
            features['bars_below_entry'] = sum(post_bars['close'] < entry_price)
            features['hold_rate'] = features['bars_above_entry'] / len(post_bars) * 100
            
            # Volume sustainability
            features['avg_volume_post'] = post_bars['volume'].mean()
            features['volume_decay_rate'] = (features['avg_volume_pre'] - features['avg_volume_post']) / features['avg_volume_pre'] * 100
            
            # Price momentum
            features['max_gain_post'] = (post_bars['high'].max() - entry_price) / entry_price * 100
            features['max_loss_post'] = (entry_price - post_bars['low'].min()) / entry_price * 100
            features['close_change_post'] = (post_bars.iloc[-1]['close'] - entry_price) / entry_price * 100
        
        return features
    
    def get_technical_indicators(self, ticker: str, signal_date: str) -> Dict:
        """
        Fetch EODHD technical indicators at time of signal.
        
        Args:
            ticker: Stock ticker
            signal_date: Date of signal (YYYY-MM-DD)
        
        Returns:
            Dict with indicator values
        """
        indicators = {}
        
        try:
            # Calculate date range (need historical data for indicators)
            end_date = datetime.strptime(signal_date, '%Y-%m-%d')
            start_date = end_date - timedelta(days=30)  # 30 days of history
            
            # RSI (14 period)
            rsi_data = eodhd_client.get_technical_indicator(
                ticker=ticker,
                function='rsi',
                period=14,
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=signal_date
            )
            if rsi_data and len(rsi_data) > 0:
                indicators['rsi'] = rsi_data[-1].get('rsi', None)
            
            # ADX (trend strength)
            adx_data = eodhd_client.get_technical_indicator(
                ticker=ticker,
                function='adx',
                period=14,
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=signal_date
            )
            if adx_data and len(adx_data) > 0:
                indicators['adx'] = adx_data[-1].get('adx', None)
                indicators['plus_di'] = adx_data[-1].get('plus_di', None)
                indicators['minus_di'] = adx_data[-1].get('minus_di', None)
            
            # MACD
            macd_data = eodhd_client.get_technical_indicator(
                ticker=ticker,
                function='macd',
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=signal_date
            )
            if macd_data and len(macd_data) > 0:
                indicators['macd'] = macd_data[-1].get('macd', None)
                indicators['macd_signal'] = macd_data[-1].get('signal', None)
                indicators['macd_hist'] = macd_data[-1].get('histogram', None)
            
            # Bollinger Bands
            bb_data = eodhd_client.get_technical_indicator(
                ticker=ticker,
                function='bbands',
                period=20,
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=signal_date
            )
            if bb_data and len(bb_data) > 0:
                indicators['bb_upper'] = bb_data[-1].get('upper', None)
                indicators['bb_middle'] = bb_data[-1].get('middle', None)
                indicators['bb_lower'] = bb_data[-1].get('lower', None)
                
                # Calculate BB position
                if all(k in indicators for k in ['bb_upper', 'bb_lower']):
                    bb_range = indicators['bb_upper'] - indicators['bb_lower']
                    if bb_range > 0:
                        # Where is price in BB range? (0 = lower, 1 = upper)
                        price = bb_data[-1].get('close', indicators['bb_middle'])
                        indicators['bb_position'] = (price - indicators['bb_lower']) / bb_range
        
        except Exception as e:
            print(f"[ENRICHMENT] Error fetching indicators: {e}")
        
        return indicators
    
    def get_market_context(self, signal_time: datetime) -> Dict:
        """
        Get market regime context at time of signal.
        
        Args:
            signal_time: Time of signal generation
        
        Returns:
            Dict with market context features
        """
        context = {}
        
        try:
            date_str = signal_time.strftime('%Y-%m-%d')
            
            # VIX (volatility)
            vix_data = eodhd_client.get_eod_data(
                ticker='VIX.INDX',
                from_date=date_str,
                to_date=date_str
            )
            if vix_data and len(vix_data) > 0:
                context['vix'] = vix_data[0].get('close', None)
            
            # SPY (market direction)
            spy_data = eodhd_client.get_eod_data(
                ticker='SPY',
                from_date=date_str,
                to_date=date_str
            )
            if spy_data and len(spy_data) > 0:
                context['spy_close'] = spy_data[0].get('close', None)
                context['spy_change'] = spy_data[0].get('change_p', None)
        
        except Exception as e:
            print(f"[ENRICHMENT] Error fetching market context: {e}")
        
        return context
    
    def enrich_signal(self, signal_data: Dict) -> Dict:
        """
        Enrich single signal with EODHD data.
        
        Args:
            signal_data: Dict with signal details from database
        
        Returns:
            Enriched signal dict with additional features
        """
        enriched = signal_data.copy()
        
        ticker = signal_data['ticker']
        signal_time = datetime.fromisoformat(signal_data['generated_at'])
        entry_price = signal_data['entry_price']
        
        print(f"[ENRICHMENT] Enriching {ticker} signal from {signal_time}...")
        
        # 1. Get bars around signal
        bars_df = self.get_bars_around_signal(
            ticker=ticker,
            signal_time=signal_time,
            bars_before=12,
            bars_after=5,
            interval='5m'
        )
        
        if bars_df is not None:
            # 2. Calculate breakout characteristics
            breakout_features = self.calculate_breakout_characteristics(
                bars_df=bars_df,
                entry_price=entry_price,
                bars_before_signal=12
            )
            enriched['breakout_features'] = breakout_features
        
        # 3. Get technical indicators
        signal_date = signal_time.strftime('%Y-%m-%d')
        indicators = self.get_technical_indicators(ticker, signal_date)
        enriched['indicators'] = indicators
        
        # 4. Get market context
        market_context = self.get_market_context(signal_time)
        enriched['market_context'] = market_context
        
        return enriched
    
    def enrich_signal_list(self, signals: List[Dict]) -> List[Dict]:
        """
        Enrich multiple signals with EODHD data.
        
        Args:
            signals: List of signal dicts from database
        
        Returns:
            List of enriched signals
        """
        enriched_signals = []
        
        for i, signal in enumerate(signals, 1):
            print(f"[ENRICHMENT] Processing signal {i}/{len(signals)}...")
            try:
                enriched = self.enrich_signal(signal)
                enriched_signals.append(enriched)
            except Exception as e:
                print(f"[ENRICHMENT] Error enriching signal: {e}")
                # Add signal without enrichment
                enriched_signals.append(signal)
        
        return enriched_signals
    
    def build_ml_features_dataframe(self, enriched_signals: List[Dict]) -> pd.DataFrame:
        """
        Build ML-ready feature matrix from enriched signals.
        
        Args:
            enriched_signals: List of enriched signal dicts
        
        Returns:
            DataFrame with features and target (win/loss)
        """
        features_list = []
        
        for signal in enriched_signals:
            try:
                features = {
                    'signal_id': signal.get('signal_id'),
                    'ticker': signal.get('ticker'),
                    'grade': signal.get('grade'),
                    'confidence': signal.get('confidence'),
                    'outcome': signal.get('outcome'),
                    'return_pct': signal.get('return_pct'),
                    'hold_time_minutes': signal.get('hold_time_minutes')
                }
                
                # Add breakout features
                if 'breakout_features' in signal:
                    for k, v in signal['breakout_features'].items():
                        features[f'breakout_{k}'] = v
                
                # Add technical indicators
                if 'indicators' in signal:
                    for k, v in signal['indicators'].items():
                        features[f'ind_{k}'] = v
                
                # Add market context
                if 'market_context' in signal:
                    for k, v in signal['market_context'].items():
                        features[f'market_{k}'] = v
                
                features_list.append(features)
            
            except Exception as e:
                print(f"[ENRICHMENT] Error building features: {e}")
                continue
        
        df = pd.DataFrame(features_list)
        
        # Convert outcome to binary target
        df['target'] = (df['outcome'] == 'win').astype(int)
        
        return df


# ========================================
# MAIN EXECUTION
# ========================================
if __name__ == "__main__":
    print("\n" + "="*80)
    print("EODHD HISTORICAL ENRICHMENT")
    print("Fetching comprehensive market data for signal analysis")
    print("="*80 + "\n")
    
    if not EODHD_AVAILABLE:
        print("❌ EODHD client not available - cannot run enrichment")
        exit(1)
    
    # Example: Enrich recent signals
    enricher = SignalEnricher()
    
    print("✅ Ready to enrich signal data")
    print("\nUsage:")
    print("  from eodhd_historical_enrichment import SignalEnricher")
    print("  enricher = SignalEnricher()")
    print("  enriched = enricher.enrich_signal(signal_dict)")
    print("")
