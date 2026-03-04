"""
Sector Rotation Detector - Hot Sector Identification

Detects sector rotation by analyzing sector ETF momentum:
  - Compares 5-day vs 1-day sector performance
  - Identifies top 2 hot sectors daily
  - Boosts watchlist scoring for tickers in hot sectors

Integration: Used by premarket_scanner_v2 to elevate sector plays
"""
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import requests
from utils import config


class SectorRotationDetector:
    """Detects hot sectors via sector ETF momentum analysis."""
    
    # Sector ETFs (SPDR Select Sector ETFs)
    SECTOR_ETFS = {
        'XLK': 'Technology',
        'XLF': 'Financials',
        'XLE': 'Energy',
        'XLV': 'Healthcare',
        'XLY': 'Consumer Discretionary',
        'XLP': 'Consumer Staples',
        'XLI': 'Industrials',
        'XLB': 'Materials',
        'XLRE': 'Real Estate',
        'XLU': 'Utilities',
        'XLC': 'Communication Services'
    }
    
    # Sector to stock mapping (major stocks per sector)
    SECTOR_STOCKS = {
        'Technology': ['AAPL', 'MSFT', 'NVDA', 'AMD', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'ORCL'],
        'Financials': ['JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'SCHW', 'AXP', 'USB'],
        'Energy': ['XOM', 'CVX', 'COP', 'SLB', 'EOG', 'MPC', 'PSX', 'VLO', 'OXY', 'HAL'],
        'Healthcare': ['UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'TMO', 'ABT', 'DHR', 'PFE', 'AMGN'],
        'Consumer Discretionary': ['AMZN', 'TSLA', 'HD', 'MCD', 'NKE', 'SBUX', 'LOW', 'TJX', 'BKNG', 'CMG'],
        'Consumer Staples': ['PG', 'KO', 'PEP', 'WMT', 'COST', 'PM', 'MO', 'MDLZ', 'CL', 'KMB'],
        'Industrials': ['BA', 'HON', 'UNP', 'RTX', 'CAT', 'GE', 'MMM', 'DE', 'LMT', 'UPS'],
        'Materials': ['LIN', 'APD', 'SHW', 'FCX', 'NEM', 'ECL', 'DD', 'NUE', 'DOW', 'PPG'],
        'Real Estate': ['AMT', 'PLD', 'CCI', 'EQIX', 'PSA', 'SPG', 'O', 'WELL', 'DLR', 'AVB'],
        'Utilities': ['NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC', 'SRE', 'XEL', 'ED', 'PEG'],
        'Communication Services': ['GOOGL', 'META', 'DIS', 'NFLX', 'T', 'CMCSA', 'VZ', 'TMUS', 'PARA', 'WBD']
    }
    
    def __init__(self):
        self.hot_sectors = []  # List of (sector_name, momentum_pct)
        self.last_update = None
        self.update_interval = timedelta(hours=1)  # Refresh hourly
    
    def get_hot_sectors(self, force_refresh: bool = False) -> List[Tuple[str, float]]:
        """
        Get top 2 hot sectors based on relative strength.
        
        Returns:
            List of (sector_name, momentum_pct) tuples, sorted by strength
        """
        # Check if refresh needed
        if force_refresh or not self.last_update or \
           (datetime.now() - self.last_update) >= self.update_interval:
            self._update_hot_sectors()
        
        return self.hot_sectors[:2]  # Top 2 sectors
    
    def is_hot_sector(self, ticker: str) -> Tuple[bool, Optional[str]]:
        """
        Check if ticker belongs to a hot sector.
        
        Args:
            ticker: Stock ticker
        
        Returns:
            (is_hot: bool, sector_name: Optional[str])
        """
        hot_sector_names = [sector for sector, _ in self.get_hot_sectors()]
        
        for sector_name, stocks in self.SECTOR_STOCKS.items():
            if ticker in stocks and sector_name in hot_sector_names:
                return True, sector_name
        
        return False, None
    
    def _update_hot_sectors(self):
        """
        Update hot sectors by analyzing sector ETF momentum.
        
        Compares 5-day performance vs 1-day performance to identify
        sectors with accelerating momentum.
        """
        sector_momentum = []
        
        for etf, sector_name in self.SECTOR_ETFS.items():
            try:
                # Fetch 5-day price data
                data_5d = self._fetch_price_data(etf, days=5)
                data_1d = self._fetch_price_data(etf, days=1)
                
                if not data_5d or not data_1d:
                    continue
                
                # Calculate momentum
                pct_5d = data_5d.get('change_pct', 0)
                pct_1d = data_1d.get('change_pct', 0)
                
                # Relative strength: 1-day performance vs 5-day average
                # Higher score = sector is accelerating
                if pct_5d != 0:
                    relative_strength = (pct_1d / (pct_5d / 5)) * 100
                else:
                    relative_strength = pct_1d * 100
                
                sector_momentum.append((sector_name, pct_1d, relative_strength))
            
            except Exception as e:
                print(f"[SECTOR] Error analyzing {etf} ({sector_name}): {e}")
                continue
        
        # Sort by relative strength (descending)
        sector_momentum.sort(key=lambda x: x[2], reverse=True)
        
        # Store top sectors with their 1-day momentum
        self.hot_sectors = [(name, pct_1d) for name, pct_1d, _ in sector_momentum]
        self.last_update = datetime.now()
        
        # Log results
        if len(self.hot_sectors) >= 2:
            top1, top2 = self.hot_sectors[0], self.hot_sectors[1]
            print(f"[SECTOR] Hot sectors: {top1[0]} ({top1[1]:+.1f}%), {top2[0]} ({top2[1]:+.1f}%)")
    
    def _fetch_price_data(self, ticker: str, days: int = 1) -> Optional[Dict]:
        """
        Fetch price data for a ticker.
        
        Args:
            ticker: ETF ticker
            days: Number of days to look back (1 or 5)
        
        Returns:
            Dict with 'change_pct' or None
        """
        try:
            # Use EODHD real-time API for latest price
            url = f"https://eodhd.com/api/real-time/{ticker}.US"
            params = {
                'api_token': config.EODHD_API_KEY,
                'fmt': 'json'
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                return None
            
            data = response.json()
            current_price = data.get('close', 0)
            prev_close = data.get('previousClose', 0)
            
            if prev_close == 0:
                return None
            
            # For 1-day: use change from previous close
            if days == 1:
                change_pct = ((current_price - prev_close) / prev_close) * 100
                return {'change_pct': change_pct}
            
            # For 5-day: fetch historical data
            else:
                hist_url = f"https://eodhd.com/api/eod/{ticker}.US"
                hist_params = {
                    'api_token': config.EODHD_API_KEY,
                    'fmt': 'json',
                    'from': (datetime.now() - timedelta(days=days+2)).strftime('%Y-%m-%d'),
                    'to': datetime.now().strftime('%Y-%m-%d')
                }
                
                hist_response = requests.get(hist_url, params=hist_params, timeout=10)
                if hist_response.status_code != 200:
                    return None
                
                hist_data = hist_response.json()
                if len(hist_data) < 2:
                    return None
                
                start_price = hist_data[0]['close']
                end_price = hist_data[-1]['close']
                
                change_pct = ((end_price - start_price) / start_price) * 100
                return {'change_pct': change_pct}
        
        except Exception as e:
            print(f"[SECTOR] Error fetching price data for {ticker}: {e}")
            return None


# Global detector instance
_sector_detector = SectorRotationDetector()


def get_hot_sectors(force_refresh: bool = False) -> List[Tuple[str, float]]:
    """
    Public API: Get top 2 hot sectors.
    
    Returns:
        List of (sector_name, momentum_pct) tuples
    """
    return _sector_detector.get_hot_sectors(force_refresh)


def is_hot_sector_stock(ticker: str) -> Tuple[bool, Optional[str]]:
    """
    Public API: Check if ticker is in a hot sector.
    
    Args:
        ticker: Stock ticker
    
    Returns:
        (is_hot: bool, sector_name: Optional[str])
    """
    return _sector_detector.is_hot_sector(ticker)
