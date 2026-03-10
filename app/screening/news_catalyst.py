"""
News Catalyst Detector - EODHD News Integration

Detects major news catalysts using EODHD News API:
  - Earnings announcements (actual event, not generic mentions)
  - Analyst upgrades/downgrades
  - M&A activity
  - FDA approvals
  - Macro events

Integration: Used by premarket_scanner to boost watchlist scoring

PHASE 1.18 (MAR 10, 2026) - Tightened earnings detection:
  - Removed bare 'earnings' keyword — appears in too much generic commentary
    (earnings growth, earnings estimate, earnings multiple, etc.)
  - Now requires event-specific phrases that confirm an actual earnings
    announcement occurred: 'reported earnings', 'beat estimates',
    'misses estimates', 'quarterly results', 'Q1/Q2/Q3/Q4 results',
    'eps beat', 'eps miss', 'reports q[1-4]'
  - Added RECENCY_HOURS window (default 48h) — news older than this is
    ignored to avoid stale catalysts from prior quarters
  - Matched keyword is now logged for easier debugging
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import re
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
        self.weight = weight        # +10 to +25 points
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

    # How far back to look for relevant news (hours)
    RECENCY_HOURS = 48

    # ---- EARNINGS ----
    # Requires event-specific language, NOT bare 'earnings'.
    # Each entry is a substring that unambiguously signals an actual event.
    EARNINGS_KEYWORDS = [
        'reported earnings',
        'reports earnings',
        'quarterly results',
        'quarterly earnings',
        'beat estimates',
        'beats estimates',
        'misses estimates',
        'missed estimates',
        'eps beat',
        'eps miss',
        'earnings beat',
        'earnings miss',
        'earnings surprise',
        'reports q1', 'reports q2', 'reports q3', 'reports q4',
        'reported q1', 'reported q2', 'reported q3', 'reported q4',
        'q1 results', 'q2 results', 'q3 results', 'q4 results',
        'q1 earnings', 'q2 earnings', 'q3 earnings', 'q4 earnings',
    ]

    # ---- ANALYST ----
    UPGRADE_KEYWORDS = [
        'upgraded to',
        'raises price target',
        'raised price target',
        'initiates coverage',
        'initiates with buy',
        'initiates with overweight',
        'price target raised',
        'price target increased',
    ]
    DOWNGRADE_KEYWORDS = [
        'downgraded to',
        'lowers price target',
        'lowered price target',
        'price target cut',
        'price target lowered',
        'cut to sell',
        'cut to underperform',
        'cut to underweight',
    ]

    # ---- M&A ----
    MERGER_KEYWORDS = [
        'agrees to acquire',
        'to be acquired',
        'merger agreement',
        'acquisition agreement',
        'takeover bid',
        'buyout offer',
        'going private',
    ]

    # ---- FDA ----
    FDA_KEYWORDS = [
        'fda approves',
        'fda approved',
        'fda grants',
        'fda accepts',
        'fda rejects',
        'fda rejection',
        'clinical trial results',
        'phase 3 results',
        'phase 2 results',
        'breakthrough therapy',
        'complete response letter',
    ]

    # ---- MACRO ----
    MACRO_KEYWORDS = [
        'federal reserve',
        'rate decision',
        'rate cut',
        'rate hike',
        'cpi report',
        'jobs report',
        'nonfarm payroll',
    ]
    
    def __init__(self):
        self.cache = {}  # ticker -> (NewsCatalyst | None, fetched_at)
        self.cache_ttl = timedelta(minutes=30)
    
    def detect_catalyst(self, ticker: str, force_refresh: bool = False) -> Optional[NewsCatalyst]:
        """
        Detect news catalyst for a ticker.

        Returns NewsCatalyst or None.
        """
        # Check cache
        if not force_refresh and ticker in self.cache:
            cached_result, fetched_at = self.cache[ticker]
            if (datetime.now() - fetched_at) < self.cache_ttl:
                return cached_result
        
        news_items = self._fetch_news(ticker)
        if not news_items:
            print(f"[NEWS] {ticker}: No news items returned from API")
            self.cache[ticker] = (None, datetime.now())
            return None
        
        print(f"[NEWS] {ticker}: Fetched {len(news_items)} news items")
        catalyst = self._analyze_news(ticker, news_items)
        self.cache[ticker] = (catalyst, datetime.now())
        
        if catalyst:
            print(f"[NEWS] {ticker}: Catalyst found - {catalyst.catalyst_type} (weight={catalyst.weight})")
        else:
            print(f"[NEWS] {ticker}: No catalyst found")
        
        return catalyst
    
    def _fetch_news(self, ticker: str, limit: int = 10) -> List[Dict]:
        """Fetch recent news from EODHD News API (last RECENCY_HOURS)."""
        try:
            url = "https://eodhd.com/api/news"
            since = datetime.now() - timedelta(hours=self.RECENCY_HOURS)
            params = {
                'api_token': config.EODHD_API_KEY,
                's': f"{ticker}.US",
                'limit': limit,
                'from': since.strftime('%Y-%m-%d'),
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
        """Check if the news item is actually about this ticker."""
        combined = (title + ' ' + content).lower()
        ticker_lower = ticker.lower()
        if ticker_lower in combined:
            return True
        return False

    def _is_recent(self, item: Dict) -> bool:
        """
        Return True if the news item's publish date is within RECENCY_HOURS.
        Accepts ISO-8601 strings or Unix timestamps in the 'date' field.
        Falls back to True when the field is missing (don't discard).
        """
        raw = item.get('date') or item.get('published_at') or item.get('datetime')
        if not raw:
            return True
        try:
            if isinstance(raw, (int, float)):
                pub = datetime.utcfromtimestamp(raw)
            else:
                # Strip trailing Z or timezone offset for fromisoformat compat
                raw_clean = re.sub(r'Z$', '', str(raw))
                raw_clean = re.sub(r'[+-]\d{2}:\d{2}$', '', raw_clean).strip()
                pub = datetime.fromisoformat(raw_clean)
            cutoff = datetime.utcnow() - timedelta(hours=self.RECENCY_HOURS)
            return pub >= cutoff
        except Exception:
            return True  # parse failure -> don't discard
    
    def _analyze_news(self, ticker: str, news_items: List[Dict]) -> Optional[NewsCatalyst]:
        """Analyze news items to detect major catalysts."""
        catalysts = []
        ticker_specific_count = 0
        
        for item in news_items:
            title = item.get('title', '')
            content = item.get('content', item.get('summary', ''))

            if not self._is_ticker_specific(ticker, title, content):
                continue
            if not self._is_recent(item):
                continue

            ticker_specific_count += 1
            title_lower = title.lower()
            content_lower = content.lower()
            combined = title_lower + ' ' + content_lower

            matched_kw = None

            # --- Earnings (tight match required) ---
            for kw in self.EARNINGS_KEYWORDS:
                if kw in combined:
                    matched_kw = kw
                    break
            if matched_kw:
                print(f"[NEWS] {ticker}: earnings match on '{matched_kw}'")
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='earnings',
                    headline=title,
                    sentiment=self._detect_sentiment(combined),
                    weight=25,
                    timestamp=datetime.now()
                ))
                continue

            # --- Upgrade ---
            for kw in self.UPGRADE_KEYWORDS:
                if kw in combined:
                    matched_kw = kw
                    break
            if matched_kw:
                print(f"[NEWS] {ticker}: upgrade match on '{matched_kw}'")
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='upgrade',
                    headline=title,
                    sentiment='bullish',
                    weight=20,
                    timestamp=datetime.now()
                ))
                continue

            matched_kw = None

            # --- Downgrade ---
            for kw in self.DOWNGRADE_KEYWORDS:
                if kw in combined:
                    matched_kw = kw
                    break
            if matched_kw:
                print(f"[NEWS] {ticker}: downgrade match on '{matched_kw}'")
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='downgrade',
                    headline=title,
                    sentiment='bearish',
                    weight=15,
                    timestamp=datetime.now()
                ))
                continue

            matched_kw = None

            # --- M&A ---
            for kw in self.MERGER_KEYWORDS:
                if kw in combined:
                    matched_kw = kw
                    break
            if matched_kw:
                print(f"[NEWS] {ticker}: merger match on '{matched_kw}'")
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='merger',
                    headline=title,
                    sentiment='bullish',
                    weight=25,
                    timestamp=datetime.now()
                ))
                continue

            matched_kw = None

            # --- FDA ---
            for kw in self.FDA_KEYWORDS:
                if kw in combined:
                    matched_kw = kw
                    break
            if matched_kw:
                print(f"[NEWS] {ticker}: fda match on '{matched_kw}'")
                catalysts.append(NewsCatalyst(
                    ticker=ticker,
                    catalyst_type='fda',
                    headline=title,
                    sentiment=self._detect_sentiment(combined),
                    weight=22,
                    timestamp=datetime.now()
                ))
                continue
        
        print(f"[NEWS] {ticker}: {ticker_specific_count} ticker-specific news items, {len(catalysts)} catalysts detected")
        
        if catalysts:
            return max(catalysts, key=lambda c: c.weight)
        return None
    
    def _detect_sentiment(self, text: str) -> str:
        bullish_words = ['beat', 'exceed', 'raise', 'growth', 'strong', 'approve', 'success', 'surge', 'jump']
        bearish_words = ['miss', 'below', 'cut', 'weak', 'decline', 'reject', 'fail', 'drop', 'plunge']
        bullish_count = sum(1 for word in bullish_words if word in text)
        bearish_count = sum(1 for word in bearish_words if word in text)
        if bullish_count > bearish_count:
            return 'bullish'
        elif bearish_count > bullish_count:
            return 'bearish'
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
