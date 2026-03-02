"""
War Machine Filter Configuration System - Phase 3
Centralized configuration for all market filters

Features:
- Enable/disable individual filters
- Parameter tuning for each filter
- Preset configurations (conservative, balanced, aggressive)
- Filter weighting system
- Easy-to-modify filter combinations
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import json
from pathlib import Path
import os
from datetime import time as dtime


# ========================================
# API KEYS & CREDENTIALS
# ========================================

# EODHD API Key (required for data_manager, signal_generator, etc.)
EODHD_API_KEY = "695cf9738b6fc2.79743285"  # Replace with your actual key

# Account Configuration
ACCOUNT_SIZE = 5000  # Your trading account size in USD

# Risk Management
MAX_SECTOR_EXPOSURE_PCT = 30.0  # Maximum exposure to any single sector (%)
MAX_POSITION_SIZE_PCT = 5.0     # Maximum % of account per position
MAX_DAILY_LOSS_PCT = 2.0        # Stop trading if daily loss exceeds this %
MAX_INTRADAY_DRAWDOWN_PCT = 5.0 # Max drawdown from intraday high water mark
MAX_OPEN_POSITIONS = 5          # Maximum concurrent positions
MAX_CONTRACTS = 10              # Maximum contracts per position
MIN_RISK_REWARD_RATIO = 1.5     # Minimum R:R for new positions

# Position Sizing Tiers (% of account risk per trade)
# These are BASE values before performance/VIX multipliers
POSITION_RISK = {
    "A+_high_confidence": 0.04,  # 4% risk for A+ grade + 85%+ confidence
    "A_high_confidence":  0.03,  # 3% risk for A/A+ grade + 75%+ confidence
    "standard":           0.02,  # 2% risk for 65%+ confidence
    "conservative":       0.01,  # 1% risk for lower confidence (<65%)
}

# Database Configuration (optional - uses SQLite if not set)
DATABASE_URL = None  # Set to PostgreSQL URL if using Railway/Heroku
# Database configuration
DB_PATH = os.getenv('DB_PATH', '/app/data/war_machine.db')
DBPATH = DB_PATH  # Alias used by WatchlistFunnel / VolumeAnalyzer

# ========================================
# MARKET HOURS (datetime.time objects for proper comparisons)
# ========================================

# FIX: Must be datetime.time objects, NOT strings.
# scanner.py and data_manager.py compare these with datetime.time values.
MARKET_OPEN  = dtime(9, 30)   # 9:30 AM ET
MARKET_CLOSE = dtime(16, 0)   # 4:00 PM ET
PRE_MARKET_START = dtime(4, 0)   # 4:00 AM ET (extended hours open)
AFTER_HOURS_END  = dtime(20, 0)  # 8:00 PM ET (extended hours close)

# ========================================
# WEBSOCKET FEED
# ========================================

ENABLE_WEBSOCKET_FEED = True  # Enable EODHD WebSocket real-time feed

# ========================================
# DISCORD ALERTS
# ========================================

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471917294891307100/onHzBfoozy0UK91wBi-7w0lC3NzF_eiiW2sUAuWLZogpWfMAk5Azfr7DcFyaGeKDM_Sa"

# ========================================
# FILTER CONFIGURATION DATACLASS
# ========================================

@dataclass
class FilterConfig:
    """Configuration for a single filter"""
    enabled: bool = True
    weight: float = 1.0  # Weight in combined scoring (0.0 to 2.0)
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


# ========================================
# MAIN CONFIGURATION CLASS
# ========================================

class WarMachineConfig:
    """
    Centralized configuration for War Machine trading system
    
    Usage:
        config = WarMachineConfig()
        config.load_preset('aggressive')
        enabled_filters = config.get_enabled_filters()
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration
        
        Args:
            config_file: Optional JSON file to load config from
        """
        self.config_file = config_file
        
        # Initialize default configurations
        self._init_baseline_config()
        self._init_technical_config()
        self._init_volume_config()
        self._init_options_config()
        self._init_fundamental_config()
        self._init_market_context_config()
        self._init_time_config()
        
        # Load from file if provided
        if config_file and Path(config_file).exists():
            self.load_from_file(config_file)
    
    # ========================================
    # BASELINE SCANNER CONFIG (V2 OPTIMIZED)
    # ========================================
    
    def _init_baseline_config(self):
        """Baseline scanner parameters (V2 optimized)"""
        self.baseline = {
            'volume_multiplier': 2.0,
            'atr_multiplier': 4.0,
            'risk_reward_ratio': 2.5,
            'lookback_periods': 16,
            'trading_window': {
                'start': '09:30',
                'end': '10:00'
            },
            'min_price': 5.0,
            'max_price': 500.0,
            'timeframe': '1min'  # 1min beats 5min in testing
        }
    
    # ========================================
    # TECHNICAL INDICATORS CONFIG
    # ========================================
    
    def _init_technical_config(self):
        """Technical indicator filter configurations"""
        self.technical_filters = {
            'rsi': FilterConfig(
                enabled=False,  # Baseline won in testing
                weight=1.0,
                params={
                    'period': 14,
                    'oversold': 30.0,
                    'overbought': 70.0,
                    'lookback_days': 90
                },
                description="RSI momentum filter - detects overbought/oversold"
            ),
            
            'macd': FilterConfig(
                enabled=False,
                weight=1.2,
                params={
                    'lookback_days': 90
                },
                description="MACD trend filter - detects bullish/bearish crossovers"
            ),
            
            'bollinger_bands': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'period': 20,
                    'std_dev': 2,
                    'lookback_days': 90
                },
                description="Bollinger Bands - detects volatility and price position"
            ),
            
            'stochastic': FilterConfig(
                enabled=False,
                weight=0.9,
                params={
                    'fast_k': 14,
                    'slow_k': 3,
                    'slow_d': 3,
                    'lookback_days': 90
                },
                description="Stochastic oscillator - momentum and crossovers"
            ),
            
            'adx': FilterConfig(
                enabled=False,
                weight=1.3,
                params={
                    'period': 14,
                    'min_trend_strength': 25.0,
                    'lookback_days': 90
                },
                description="ADX trend strength - filters for strong trends"
            ),
            
            'atr': FilterConfig(
                enabled=False,
                weight=1.1,
                params={
                    'period': 14,
                    'min_atr_percentile': 50.0,
                    'lookback_days': 252
                },
                description="ATR volatility - ensures sufficient price movement"
            ),
            
            'ema': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'fast_period': 9,
                    'slow_period': 21,
                    'lookback_days': 90
                },
                description="EMA crossover - trend following"
            ),
            
            'sma': FilterConfig(
                enabled=False,
                weight=0.9,
                params={
                    'period': 50,
                    'lookback_days': 90
                },
                description="SMA support/resistance - price vs moving average"
            ),
            
            'obv': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'lookback_days': 90
                },
                description="On Balance Volume - volume-price relationship"
            ),
            
            'cci': FilterConfig(
                enabled=False,
                weight=0.8,
                params={
                    'period': 20,
                    'lookback_days': 90
                },
                description="Commodity Channel Index - cyclical trends"
            ),
            
            'roc': FilterConfig(
                enabled=False,
                weight=0.9,
                params={
                    'period': 12,
                    'lookback_days': 90
                },
                description="Rate of Change - momentum measurement"
            ),
            
            'willr': FilterConfig(
                enabled=False,
                weight=0.8,
                params={
                    'period': 14,
                    'lookback_days': 90
                },
                description="Williams %R - momentum oscillator"
            )
        }
    
    # ========================================
    # VOLUME & MOMENTUM CONFIG
    # ========================================
    
    def _init_volume_config(self):
        """Volume and momentum filter configurations"""
        self.volume_filters = {
            'volume_surge': FilterConfig(
                enabled=False,
                weight=1.5,
                params={
                    'min_volume_ratio': 1.5,
                    'avg_period': 20,
                    'lookback_days': 90
                },
                description="Volume surge - detects unusual volume spikes"
            ),
            
            'price_momentum': FilterConfig(
                enabled=False,
                weight=1.3,
                params={
                    'period': 10,
                    'min_momentum_pct': 2.0,
                    'lookback_days': 90
                },
                description="Price momentum - recent price movement strength"
            ),
            
            'gap_size': FilterConfig(
                enabled=False,
                weight=1.4,
                params={
                    'min_gap_pct': 2.0,
                    'max_gap_pct': 10.0
                },
                description="Gap size filter - optimal gap range"
            ),
            
            'relative_volume': FilterConfig(
                enabled=False,
                weight=1.2,
                params={
                    'min_rvol': 2.0,
                    'lookback_periods': 20
                },
                description="Relative volume - volume vs historical average"
            ),
            
            'volume_price_trend': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'lookback_days': 30
                },
                description="Volume Price Trend - accumulation/distribution"
            )
        }
    
    # ========================================
    # OPTIONS FLOW CONFIG
    # ========================================
    
    def _init_options_config(self):
        """Options flow filter configurations"""
        self.options_filters = {
            'options_iv_rank': FilterConfig(
                enabled=False,
                weight=1.2,
                params={
                    'min_iv_rank': 30.0,
                    'max_iv_rank': 80.0,
                    'lookback_days': 252
                },
                description="IV Rank - implied volatility percentile"
            ),
            
            'put_call_ratio': FilterConfig(
                enabled=False,
                weight=1.1,
                params={
                    'min_ratio': 0.5,
                    'max_ratio': 2.0
                },
                description="Put/Call ratio - options sentiment"
            ),
            
            'options_volume': FilterConfig(
                enabled=False,
                weight=1.3,
                params={
                    'min_volume_ratio': 2.0
                },
                description="Options volume surge - unusual options activity"
            ),
            
            'unusual_whales': FilterConfig(
                enabled=False,
                weight=1.5,
                params={
                    'min_premium': 50000,
                    'lookback_hours': 24
                },
                description="Unusual options flow - large premium trades"
            ),
            
            'iv_percentile': FilterConfig(
                enabled=False,
                weight=1.1,
                params={
                    'min_percentile': 40.0,
                    'lookback_days': 252
                },
                description="IV Percentile - current IV vs historical"
            ),
            
            'option_spreads': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'max_bid_ask_pct': 10.0
                },
                description="Options spreads - liquidity check"
            )
        }
    
    # ========================================
    # FUNDAMENTAL CONFIG
    # ========================================
    
    def _init_fundamental_config(self):
        """Fundamental filter configurations"""
        self.fundamental_filters = {
            'market_cap': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'min_market_cap': 1e9,  # $1B
                    'max_market_cap': None
                },
                description="Market cap filter - company size"
            ),
            
            'liquidity': FilterConfig(
                enabled=False,
                weight=1.4,
                params={
                    'min_avg_dollar_volume': 10e6,  # $10M
                    'avg_period': 20
                },
                description="Liquidity filter - average dollar volume"
            ),
            
            'sector': FilterConfig(
                enabled=False,
                weight=0.8,
                params={
                    'allowed_sectors': [],  # Empty = all sectors
                    'excluded_sectors': []
                },
                description="Sector filter - industry selection"
            ),
            
            'pe_ratio': FilterConfig(
                enabled=False,
                weight=0.7,
                params={
                    'min_pe': 0,
                    'max_pe': 50
                },
                description="P/E ratio - valuation filter"
            ),
            
            'float_size': FilterConfig(
                enabled=False,
                weight=1.2,
                params={
                    'min_float': 10e6,  # 10M shares
                    'max_float': 500e6  # 500M shares
                },
                description="Float size - shares available for trading"
            ),
            
            'short_interest': FilterConfig(
                enabled=False,
                weight=1.1,
                params={
                    'min_short_pct': 10.0,
                    'max_short_pct': 40.0
                },
                description="Short interest - potential squeeze candidates"
            )
        }
    
    # ========================================
    # MARKET CONTEXT CONFIG
    # ========================================
    
    def _init_market_context_config(self):
        """Market context filter configurations"""
        self.market_context_filters = {
            'spy_correlation': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'max_correlation': 0.8,
                    'lookback_days': 60
                },
                description="SPY correlation - stock-specific vs market-wide"
            ),
            
            'vix_level': FilterConfig(
                enabled=False,
                weight=1.2,
                params={
                    'min_vix': 15.0,
                    'max_vix': 30.0
                },
                description="VIX level - market volatility context"
            ),
            
            'sector_strength': FilterConfig(
                enabled=False,
                weight=1.1,
                params={
                    'min_sector_momentum': 1.0,
                    'lookback_days': 10
                },
                description="Sector strength - relative sector performance"
            ),
            
            'market_breadth': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'min_advance_decline': 0.6
                },
                description="Market breadth - advance/decline ratio"
            ),
            
            'premarket_volume': FilterConfig(
                enabled=False,
                weight=1.3,
                params={
                    'min_pm_volume_ratio': 0.3
                },
                description="Premarket volume - early interest indicator"
            )
        }
    
    # ========================================
    # TIME-BASED CONFIG
    # ========================================
    
    def _init_time_config(self):
        """Time-based filter configurations"""
        self.time_filters = {
            'day_of_week': FilterConfig(
                enabled=False,
                weight=0.8,
                params={
                    'allowed_days': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
                },
                description="Day of week - trading calendar filter"
            ),
            
            'time_of_day': FilterConfig(
                enabled=False,
                weight=1.0,
                params={
                    'start_time': '09:30',
                    'end_time': '10:00'
                },
                description="Time of day - intraday window filter"
            ),
            
            'avoid_fomc': FilterConfig(
                enabled=False,
                weight=1.5,
                params={
                    'check_calendar': True
                },
                description="FOMC days - avoid high-impact events"
            ),
            
            'earnings_date': FilterConfig(
                enabled=False,
                weight=1.2,
                params={
                    'days_before': 0,
                    'days_after': 1
                },
                description="Earnings proximity - avoid or target earnings"
            ),
            
            'expiration_week': FilterConfig(
                enabled=False,
                weight=0.9,
                params={
                    'avoid_opex': True
                },
                description="Options expiration week - volatility consideration"
            )
        }
    
    # ========================================
    # PRESET CONFIGURATIONS
    # ========================================
    
    def load_preset(self, preset_name: str):
        """
        Load a preset configuration
        
        Available presets:
        - baseline: No filters (V2 optimized baseline only)
        - conservative: Strong filters, high quality setups only
        - balanced: Moderate filtering
        - aggressive: Light filtering, more opportunities
        - volume_focused: Heavy emphasis on volume/liquidity
        - technical_focused: Heavy emphasis on technical indicators
        - options_focused: Options flow and Greeks
        """
        if preset_name == 'baseline':
            self._load_baseline_preset()
        elif preset_name == 'conservative':
            self._load_conservative_preset()
        elif preset_name == 'balanced':
            self._load_balanced_preset()
        elif preset_name == 'aggressive':
            self._load_aggressive_preset()
        elif preset_name == 'volume_focused':
            self._load_volume_focused_preset()
        elif preset_name == 'technical_focused':
            self._load_technical_focused_preset()
        elif preset_name == 'options_focused':
            self._load_options_focused_preset()
        else:
            raise ValueError(f"Unknown preset: {preset_name}")
    
    def _load_baseline_preset(self):
        """Baseline: No filters, just V2 optimized scanner"""
        # Disable all filters
        self._disable_all_filters()
    
    def _load_conservative_preset(self):
        """Conservative: High-quality setups only"""
        self._disable_all_filters()
        
        # Enable key filters with strict parameters
        self.volume_filters['volume_surge'].enabled = True
        self.volume_filters['volume_surge'].params['min_volume_ratio'] = 2.0
        
        self.fundamental_filters['liquidity'].enabled = True
        self.fundamental_filters['liquidity'].params['min_avg_dollar_volume'] = 20e6
        
        self.market_context_filters['vix_level'].enabled = True
        self.market_context_filters['vix_level'].params = {'min_vix': 16.0, 'max_vix': 28.0}
        
        self.technical_filters['adx'].enabled = True
        self.technical_filters['adx'].params['min_trend_strength'] = 30.0
    
    def _load_balanced_preset(self):
        """Balanced: Moderate filtering"""
        self._disable_all_filters()
        
        # Enable moderate filters
        self.volume_filters['volume_surge'].enabled = True
        self.volume_filters['gap_size'].enabled = True
        
        self.fundamental_filters['liquidity'].enabled = True
        
        self.technical_filters['rsi'].enabled = True
        self.technical_filters['macd'].enabled = True
        
        self.market_context_filters['vix_level'].enabled = True
    
    def _load_aggressive_preset(self):
        """Aggressive: Light filtering, more opportunities"""
        self._disable_all_filters()
        
        # Enable only basic filters
        self.volume_filters['volume_surge'].enabled = True
        self.volume_filters['volume_surge'].params['min_volume_ratio'] = 1.3
        
        self.fundamental_filters['liquidity'].enabled = True
        self.fundamental_filters['liquidity'].params['min_avg_dollar_volume'] = 5e6
    
    def _load_volume_focused_preset(self):
        """Volume-focused: Emphasis on volume and liquidity"""
        self._disable_all_filters()
        
        # Enable all volume filters
        self.volume_filters['volume_surge'].enabled = True
        self.volume_filters['volume_surge'].weight = 2.0
        
        self.volume_filters['price_momentum'].enabled = True
        self.volume_filters['price_momentum'].weight = 1.5
        
        self.volume_filters['relative_volume'].enabled = True
        
        self.fundamental_filters['liquidity'].enabled = True
        self.fundamental_filters['liquidity'].weight = 1.8
        
        self.market_context_filters['premarket_volume'].enabled = True
    
    def _load_technical_focused_preset(self):
        """Technical-focused: Multiple technical indicators"""
        self._disable_all_filters()
        
        # Enable technical indicators
        self.technical_filters['rsi'].enabled = True
        self.technical_filters['macd'].enabled = True
        self.technical_filters['bollinger_bands'].enabled = True
        self.technical_filters['adx'].enabled = True
        self.technical_filters['atr'].enabled = True
        
        # Basic liquidity filter
        self.fundamental_filters['liquidity'].enabled = True
    
    def _load_options_focused_preset(self):
        """Options-focused: Options flow and Greeks"""
        self._disable_all_filters()
        
        # Enable options filters
        self.options_filters['options_iv_rank'].enabled = True
        self.options_filters['put_call_ratio'].enabled = True
        self.options_filters['options_volume'].enabled = True
        self.options_filters['unusual_whales'].enabled = True
        
        # Supporting filters
        self.volume_filters['volume_surge'].enabled = True
        self.fundamental_filters['liquidity'].enabled = True
        self.market_context_filters['vix_level'].enabled = True
    
    def _disable_all_filters(self):
        """Disable all filters"""
        for filter_dict in [
            self.technical_filters,
            self.volume_filters,
            self.options_filters,
            self.fundamental_filters,
            self.market_context_filters,
            self.time_filters
        ]:
            for filter_config in filter_dict.values():
                filter_config.enabled = False
    
    # ========================================
    # UTILITY METHODS
    # ========================================
    
    def get_enabled_filters(self) -> Dict[str, FilterConfig]:
        """Get all enabled filters with their configurations"""
        enabled = {}
        
        for category in [
            self.technical_filters,
            self.volume_filters,
            self.options_filters,
            self.fundamental_filters,
            self.market_context_filters,
            self.time_filters
        ]:
            for name, config in category.items():
                if config.enabled:
                    enabled[name] = config
        
        return enabled
    
    def get_filter_names(self) -> List[str]:
        """Get list of enabled filter names"""
        return list(self.get_enabled_filters().keys())
    
    def get_filter_params(self) -> Dict[str, Dict]:
        """Get parameters for all enabled filters"""
        enabled = self.get_enabled_filters()
        return {name: config.params for name, config in enabled.items()}
    
    def get_filter_weights(self) -> Dict[str, float]:
        """Get weights for all enabled filters"""
        enabled = self.get_enabled_filters()
        return {name: config.weight for name, config in enabled.items()}
    
    def enable_filter(self, filter_name: str):
        """Enable a specific filter"""
        filter_config = self._find_filter(filter_name)
        if filter_config:
            filter_config.enabled = True
        else:
            raise ValueError(f"Filter not found: {filter_name}")
    
    def disable_filter(self, filter_name: str):
        """Disable a specific filter"""
        filter_config = self._find_filter(filter_name)
        if filter_config:
            filter_config.enabled = False
        else:
            raise ValueError(f"Filter not found: {filter_name}")
    
    def update_filter_params(self, filter_name: str, params: Dict):
        """Update parameters for a specific filter"""
        filter_config = self._find_filter(filter_name)
        if filter_config:
            filter_config.params.update(params)
        else:
            raise ValueError(f"Filter not found: {filter_name}")
    
    def _find_filter(self, filter_name: str) -> Optional[FilterConfig]:
        """Find a filter by name across all categories"""
        for category in [
            self.technical_filters,
            self.volume_filters,
            self.options_filters,
            self.fundamental_filters,
            self.market_context_filters,
            self.time_filters
        ]:
            if filter_name in category:
                return category[filter_name]
        return None
    
    def get_all_filters(self) -> Dict[str, FilterConfig]:
        """Get all filters (enabled and disabled)"""
        all_filters = {}
        
        for category in [
            self.technical_filters,
            self.volume_filters,
            self.options_filters,
            self.fundamental_filters,
            self.market_context_filters,
            self.time_filters
        ]:
            all_filters.update(category)
        
        return all_filters
    
    def print_config_summary(self):
        """Print configuration summary"""
        print("="*70)
        print("WAR MACHINE FILTER CONFIGURATION")
        print("="*70)
        
        print("\nBASELINE SCANNER:")
        for key, value in self.baseline.items():
            print(f"  {key}: {value}")
        
        enabled = self.get_enabled_filters()
        print(f"\nENABLED FILTERS: {len(enabled)}")
        
        if enabled:
            for name, config in enabled.items():
                print(f"\n  {name.upper()}")
                print(f"    Weight: {config.weight}")
                print(f"    Description: {config.description}")
                print(f"    Params: {config.params}")
        else:
            print("  None (Baseline mode)")
        
        print("\n" + "="*70)
    
    # ========================================
    # SAVE/LOAD CONFIGURATION
    # ========================================
    
    def save_to_file(self, filename: str):
        """Save configuration to JSON file"""
        config_data = {
            'baseline': self.baseline,
            'technical_filters': self._serialize_filters(self.technical_filters),
            'volume_filters': self._serialize_filters(self.volume_filters),
            'options_filters': self._serialize_filters(self.options_filters),
            'fundamental_filters': self._serialize_filters(self.fundamental_filters),
            'market_context_filters': self._serialize_filters(self.market_context_filters),
            'time_filters': self._serialize_filters(self.time_filters)
        }
        
        with open(filename, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        print(f"Configuration saved to {filename}")
    
    def load_from_file(self, filename: str):
        """Load configuration from JSON file"""
        with open(filename, 'r') as f:
            config_data = json.load(f)
        
        self.baseline = config_data.get('baseline', self.baseline)
        
        # Load filters
        self._deserialize_filters(config_data.get('technical_filters', {}), self.technical_filters)
        self._deserialize_filters(config_data.get('volume_filters', {}), self.volume_filters)
        self._deserialize_filters(config_data.get('options_filters', {}), self.options_filters)
        self._deserialize_filters(config_data.get('fundamental_filters', {}), self.fundamental_filters)
        self._deserialize_filters(config_data.get('market_context_filters', {}), self.market_context_filters)
        self._deserialize_filters(config_data.get('time_filters', {}), self.time_filters)
        
        print(f"Configuration loaded from {filename}")
    
    def _serialize_filters(self, filters: Dict[str, FilterConfig]) -> Dict:
        """Convert FilterConfig objects to dict for JSON serialization"""
        return {
            name: {
                'enabled': config.enabled,
                'weight': config.weight,
                'params': config.params,
                'description': config.description
            }
            for name, config in filters.items()
        }
    
    def _deserialize_filters(self, data: Dict, target: Dict[str, FilterConfig]):
        """Load FilterConfig objects from dict"""
        for name, config_dict in data.items():
            if name in target:
                target[name].enabled = config_dict.get('enabled', False)
                target[name].weight = config_dict.get('weight', 1.0)
                target[name].params = config_dict.get('params', {})
                target[name].description = config_dict.get('description', '')


# ========================================
# EXAMPLE USAGE
# ========================================

if __name__ == "__main__":
    # Create default config
    config = WarMachineConfig()
    
    # Test baseline (no filters)
    print("\n" + "="*70)
    print("BASELINE CONFIGURATION")
    print("="*70)
    config.load_preset('baseline')
    config.print_config_summary()
    
    # Test balanced preset
    print("\n" + "="*70)
    print("BALANCED CONFIGURATION")
    print("="*70)
    config.load_preset('balanced')
    config.print_config_summary()
    
    # Test conservative preset
    print("\n" + "="*70)
    print("CONSERVATIVE CONFIGURATION")
    print("="*70)
    config.load_preset('conservative')
    config.print_config_summary()
    
    # Custom configuration
    print("\n" + "="*70)
    print("CUSTOM CONFIGURATION")
    print("="*70)
    config.load_preset('baseline')
    config.enable_filter('rsi')
    config.enable_filter('volume_surge')
    config.update_filter_params('rsi', {'period': 10})
    config.print_config_summary()
    
    # Save configuration
    config.save_to_file('war_machine_config.json')
    
    # Show usage for scanner integration
    print("\n" + "="*70)
    print("USAGE IN SCANNER")
    print("="*70)
    print("enabled_filters = config.get_filter_names()")
    print("filter_params = config.get_filter_params()")
    print("filter_weights = config.get_filter_weights()")
    print("\nEnabled filters:", config.get_filter_names())
