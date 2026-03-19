"""
News Catalyst Detector - EODHD News Integration

Detects major news catalysts using EODHD News API:
  - Earnings announcements (actual event, not generic mentions)
  - Analyst upgrades/downgrades
  - M&A activity
  - FDA approvals
  - Macro events

Integration: Used by premarket_scanner to boost watchlist scoring

PHASE 1.18 (MAR 10, 2026):
  - Tightened earnings keywords (event-specific phrases only)
  - Added RECENCY_HOURS window (48h) to skip stale catalysts
  - Matched keyword logged for debugging
  - notify_news_catalyst(): posts rich Discord embed to dedicated
    news channel (DISCORD_NEWS_WEBHOOK_URL) whenever a catalyst fires
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import re
import requests
from utils import config


# Catalyst type -> emoji for Discord embed
_CATALYST_EMOJI = {
    'earnings':  '📊',
    'upgrade':   '⬆️',
    'downgrade': '⬇️',
    'merger':    '🤝',
    'fda':       '💊',
    'macro':     '🌐',
}

# Sentiment -> color (Discord embed sidebar color, decimal)
_SENTIMENT_COLOR = {
    'bullish': 0x2ECC71,   # green
    'bearish': 0xE74C3C,   # red
    'neutral': 0x95A5A6,   # grey
}


class NewsCatalyst:
    """Container for news catalyst data."""
    
    def __init__(self,
                 ticker: str,
                 catalyst_type: str,
                 headline: str,
                 sentiment: str,
                 weight: int,
                 timestamp: datetime,
                 matched_kw: str = ''):
        self.ticker = ticker
        self.catalyst_type = catalyst_type
        self.headline = headline
        self.sentiment = sentiment  # 'bullish', 'bearish', 'neutral'
        self.weight = weight        # +10 to +25 points
        self.timestamp = timestamp
        self.matched_kw = matched_kw  # keyword that triggered the match
    
    def to_dict(self) -> Dict:
        return {
            'ticker': self.ticker,
            'type': self.catalyst_type,
            'headline': self.headline,
            'sentiment': self.sentiment,
            'weight': self.weight,
            'matched_kw': self.matched_kw,
            'timestamp': self.timestamp.isoformat()
        }


def notify_news_catalyst(catalyst: 'NewsCatalyst') -> None:
    """
    Post a Discord embed to the dedicated news channel when a catalyst fires.

    Uses DISCORD_NEWS_WEBHOOK_URL from config.  Fails silently if the webhook
    is not configured or the request errors — never blocks the scan loop.
    """
    webhook_url = getattr(config, 'DISCORD_NEWS_WEBHOOK_URL', '')
    if not webhook_url:
        return

    emoji = _CATALYST_EMOJI.get(catalyst.catalyst_type, '📰')
    color = _SENTIMENT_COLOR.get(catalyst.sentiment, 0x95A5A6)
    sentiment_label = catalyst.sentiment.upper()

    # Truncate headline to Discord field limit
    headline = catalyst.headline[:250] + '…' if len(catalyst.headline) > 250 else catalyst.headline

    embed = {
        'title': f'{emoji}  {catalyst.ticker}  —  {catalyst.catalyst_type.upper()} CATALYST',
        'description': headline,
        'color': color,
        'fields': [
            {'name': 'Sentiment',    'value': sentiment_label,          'inline': True},
            {'name': 'Score Weight', 'value': f'+{catalyst.weight} pts', 'inline': True},
            {'name': 'Matched On',   'value': f'`{catalyst.matched_kw}`','inline': True},
        ],
        'footer': {
            'text': f'War Machine  •  News Catalyst  •  {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}'
        }
    }

    try:
        resp = requests.post(
            webhook_url,
            json={'embeds': [embed]},
            timeout=10
        )
        if resp.status_code not in (200, 204):
            print(f'[NEWS-DISCORD] Webhook error {resp.status_code} for {catalyst.ticker}')
    except Exception as e:
        print(f'[NEWS-DISCORD] Failed to send alert for {catalyst.ticker}: {e}')


class NewsCatalystDetector:
    """Detects news catalysts for pre-market scanning."""

    # How far back to look for relevant news (hours)
    RECENCY_HOURS = 48

    # ---- EARNINGS ----
    # Requires event-specific language, NOT bare 'earnings'.
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
        Fires a Discord notification automatically when a catalyst is found.
        """
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
            # Fire Discord alert to news channel
            notify_news_catalyst(catalyst)
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
        combined = (title + ' ' + content).lower()
        return ticker.lower() in combined

    def _is_recent(self, item: Dict) -> bool:
        raw = item.get('date') or item.get('published_at') or item.get('datetime')
        if not raw:
            return True
        try:
            if isinstance(raw, (int, float)):
                pub = datetime.utcfromtimestamp(raw)
            else:
                raw_clean = re.sub(r'Z$', '', str(raw))
                raw_clean = re.sub(r'[+-]\d{2}:\d{2}$', '', raw_clean).strip()
                pub = datetime.fromisoformat(raw_clean)
            cutoff = datetime.utcnow() - timedelta(hours=self.RECENCY_HOURS)
            return pub >= cutoff
        except Exception:
            return True
    
    def _analyze_news(self, ticker: str, news_items: List[Dict]) -> Optional[NewsCatalyst]:
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
            combined = (title + ' ' + content).lower()
            matched_kw = None

            # --- Earnings ---
            for kw in self.EARNINGS_KEYWORDS:
                if kw in combined:
                    matched_kw = kw
                    break
            if matched_kw:
                print(f"[NEWS] {ticker}: earnings match on '{matched_kw}'")
                catalysts.append(NewsCatalyst(
                    ticker=ticker, catalyst_type='earnings',
                    headline=title,
                    sentiment=self._detect_sentiment(combined),
                    weight=25, timestamp=datetime.now(), matched_kw=matched_kw
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
                    ticker=ticker, catalyst_type='upgrade',
                    headline=title, sentiment='bullish',
                    weight=20, timestamp=datetime.now(), matched_kw=matched_kw
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
                    ticker=ticker, catalyst_type='downgrade',
                    headline=title, sentiment='bearish',
                    weight=15, timestamp=datetime.now(), matched_kw=matched_kw
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
                    ticker=ticker, catalyst_type='merger',
                    headline=title, sentiment='bullish',
                    weight=25, timestamp=datetime.now(), matched_kw=matched_kw
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
                    ticker=ticker, catalyst_type='fda',
                    headline=title,
                    sentiment=self._detect_sentiment(combined),
                    weight=22, timestamp=datetime.now(), matched_kw=matched_kw
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
    Automatically sends Discord alert to news channel when catalyst is found.
    """
    return _news_detector.detect_catalyst(ticker, force_refresh)
