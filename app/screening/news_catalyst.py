"""
News Catalyst Detector - EODHD News Integration

Detects major news catalysts using EODHD News API:
  - Earnings announcements
  - Analyst upgrades/downgrades
  - M&A activity
  - FDA approvals
  - Macro events

Integration: Used by premarket_scanner_v2 to boost watchlist scoring
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import requests
from utils import config


class NewsCatalyst:
    """Container for news catalyst data."""
    
    def __init__(self,
                 ticker: str,
                 catalyst_type: str,
                 headline: str,
                 sentiment: str,
                 weight: int,
                 timestamp: datetime):
        self.ticker = ticker
        self.catalyst_type = catalyst_type
        self.headline = headline
        self.sentiment = sentiment  # 'bullish', 'bearish', 'neutral'
        self.weight = weight  # +10 to +25 points
        self.timestamp = timestamp
    
    def to_dict(self) -> Dict:
        return {
            'ticker': self.ticker,
            'type': self.catalyst_type,
            'headline': self.headline,
            'sentiment': self.sentiment,
            'weight': self.weight,
            'timestamp': self.timestamp.isoformat()
        }


class NewsCatalystDetector:
    """Detects news catalysts for pre-market scanning."""
    
    # Catalyst keywords
    EARNINGS_KEYWORDS = ['earnings', 'reports q', 'quarterly results', 'eps']
    UPGRADE_KEYWORDS = ['upgrade', 'raised to', 'initiates coverage', 'price target']
    DOWNGRADE_KEYWORDS = ['downgrade', 'cut to', 'lowers rating', 'reduces target']
    MERGER_KEYWORDS = ['merger', 'acquisition', 'takeover', 'buyout', 'deal']
    FDA_KEYWORDS = ['fda', 'approval', 'clinical trial', 'drug']
    MACRO_KEYWORDS = ['fed', 'inflation', 'employment', 'gdp', 'recession']
    
    def __init__(self):
        self.cache = {}  # ticker -> NewsCatalyst
        self.cache_ttl = timedelta(minutes=30)
    
    def detect_catalyst(self, ticker: str, force_refresh: bool = False) -> Optional[NewsCatalyst]:
        """
        Detect news catalyst for a ticker.
        
        Args:
            ticker: Stock ticker
            force_refresh: Skip cache and fetch fresh data
        
        Returns:
            NewsCatalyst object or None if no major catalyst
        """
        # Check cache
        if not force_refresh and ticker in self.cache:
            cached = self.cache[ticker]
            if cached is None:
                return None
            age = datetime.now() - cached.timestamp
            if age < self.cache_ttl:
                return cached
        
        # Fetch news from EODHD
        news_items = self._fetch_news(ticker)
        if not news_items:
            print(f"[NEWS] {ticker}: No news items returned from API")
            self.cache[ticker] = None
            return None
        
        print(f"[NEWS] {ticker}: Fetched {len(news_items)} news items")
        
        # Analyze news for catalysts
        catalyst = self._analyze_news(ticker, news_items)
        
        # Cache result (even if None)
        self.cache[ticker] = catalyst
        
        if catalyst:
            print(f"[NEWS] {ticker}: Catalyst found - {catalyst.catalyst_type} (weight={catalyst.weight})")
        else:
            print(f"[NEWS] {ticker}: No catalyst found")
        
        return catalyst
    
    def _fetch_news(self, ticker: str, limit: int = 10) -> List[Dict]:
        """
        Fetch recent news from EODHD News API.
        
        Returns last 24 hours of news for the ticker.
        """
        try:
            # EODHD News API: https://eodhd.com/financial-apis/stock-market-financial-news-api/
            url = f"https://eodhd.com/api/news"
            params = {
                'api_token': config.EODHD_API_KEY,
                's': f"{ticker}.US",
                'limit': limit,
                'from': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
                'to': datetime.now().strftime('%Y-%m-%d')
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                print(f"[NEWS] {ticker}: API returned HTTP {response.status_code}")
                return []
            
            news_data = response.json()
            return news_data if isinstance(news_data, list) else []
        
        except Exception as e:
            print(f"[NEWS] Error fetching news for {ticker}: {e}")
            return []
    
    def _is_ticker_specific(self, ticker: str, title: str, content: str) -> bool:
        """
        Check if news item is actually about the ticker.
        Prevents false positives from general market news.
        
        Args:
            ticker: Stock ticker
            title: News headline
            content: News content
        
        Returns:
            True if news is ticker-specific
        """
        combined = (title + ' ' + content).lower()
        ticker_lower = ticker.lower()
        
        # Check if ticker appears in the text
        # Also check common variations (e.g., "Tesla" for TSLA)
        if ticker_lower in combined:
            return True
        
        # TODO: Add company name mapping (TSLA -> Tesla, AAPL -> Apple, etc.)
        # For now, just require ticker to be present
        return False
    
    def _analyze_news(self, ticker: str, news_items: List[Dict]) -> Optional[NewsCatalyst]:
        """
        Analyze news items to detect major catalysts.
        
        Returns the highest-weight catalyst found.
        """
        catalysts = []
        ticker_specific_count = 0
        
        for item in news_items:
            title = item.get('title', '')
            content = item.get('content', '')
            
            # CRITICAL: Only analyze ticker-specific news
            if not self._is_ticker_specific(ticker, title, content):
                continue
            
            ticker_specific_count += 1
            
            title_lower = title.lower()
            content_lower = content.lower()
            combined = title_lower + ' ' + content_lower
            
            # Check for earnings
            if any(kw in combined for kw in self.EARNINGS_KEYWORDS):
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='earnings',
                    headline=title,
                    sentiment=self._detect_sentiment(combined),
                    weight=25,  # Highest weight
                    timestamp=datetime.now()
                ))
            
            # Check for upgrades
            elif any(kw in combined for kw in self.UPGRADE_KEYWORDS):
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='upgrade',
                    headline=title,
                    sentiment='bullish',
                    weight=20,
                    timestamp=datetime.now()
                ))
            
            # Check for downgrades
            elif any(kw in combined for kw in self.DOWNGRADE_KEYWORDS):
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='downgrade',
                    headline=title,
                    sentiment='bearish',
                    weight=15,
                    timestamp=datetime.now()
                ))
            
            # Check for M&A
            elif any(kw in combined for kw in self.MERGER_KEYWORDS):
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='merger',
                    headline=title,
                    sentiment='bullish',
                    weight=25,
                    timestamp=datetime.now()
                ))
            
            # Check for FDA
            elif any(kw in combined for kw in self.FDA_KEYWORDS):
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='fda',
                    headline=title,
                    sentiment=self._detect_sentiment(combined),
                    weight=22,
                    timestamp=datetime.now()
                ))
        
        print(f"[NEWS] {ticker}: {ticker_specific_count} ticker-specific news items, {len(catalysts)} catalysts detected")
        
        # Return highest-weight catalyst
        if catalysts:
            return max(catalysts, key=lambda c: c.weight)
        
        return None
    
    def _detect_sentiment(self, text: str) -> str:
        """
        Simple sentiment detection based on keywords.
        """
        bullish_words = ['beat', 'exceed', 'raise', 'growth', 'strong', 'approve', 'success']
        bearish_words = ['miss', 'below', 'cut', 'weak', 'decline', 'reject', 'fail']
        
        bullish_count = sum(1 for word in bullish_words if word in text)
        bearish_count = sum(1 for word in bearish_words if word in text)
        
        if bullish_count > bearish_count:
            return 'bullish'
        elif bearish_count > bullish_count:
            return 'bearish'
        else:
            return 'neutral'


# Global detector instance
_news_detector = NewsCatalystDetector()


def detect_catalyst(ticker: str, force_refresh: bool = False) -> Optional[NewsCatalyst]:
    """
    Public API: Detect news catalyst for a ticker.
    
    Args:
        ticker: Stock ticker
        force_refresh: Skip cache and fetch fresh data
    
    Returns:
        NewsCatalyst object or None
    """
    return _news_detector.detect_catalyst(ticker, force_refresh)
