"""
News Sentiment Filter for War Machine
Uses EODHD News API to analyze recent news sentiment and filter/boost signals

EODHD API Endpoint: https://eodhd.com/api/news
Documentation: https://eodhd.com/financial-apis/stock-market-financial-news-api

Integration:
- Filter signals with major negative news
- Boost confidence for positive catalysts
- Cache news for 15 minutes (news changes frequently)
"""

import requests
import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import config


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

NEWS_CACHE_TTL = 900  # 15 minutes (news is time-sensitive)
MAX_NEWS_AGE_HOURS = 24  # Only consider news from last 24 hours

# Sentiment keywords (simple approach - can be enhanced with NLP later)
NEGATIVE_KEYWORDS = [
    'lawsuit', 'investigation', 'fraud', 'scandal', 'bankruptcy', 'downgrade',
    'miss', 'disappoints', 'plunges', 'plummets', 'crashes', 'slumps',
    'warning', 'probe', 'allegations', 'suspend', 'halt', 'delisting',
    'layoffs', 'cuts', 'closes', 'shutters', 'fails', 'losses'
]

POSITIVE_KEYWORDS = [
    'upgrade', 'beats', 'exceeds', 'surges', 'soars', 'jumps', 'rallies',
    'partnership', 'deal', 'contract', 'approval', 'breakthrough', 'innovation',
    'buyback', 'dividend', 'expansion', 'growth', 'record', 'strong',
    'acquisition', 'merger', 'breakthrough', 'wins', 'awarded'
]


# ══════════════════════════════════════════════════════════════════════════════
# CACHING
# ══════════════════════════════════════════════════════════════════════════════

_news_cache: Dict[str, Dict] = {}  # ticker -> {data, timestamp}


def _is_cache_valid(ticker: str) -> bool:
    """Check if cached news is still valid"""
    if ticker not in _news_cache:
        return False
    return (time.time() - _news_cache[ticker]['timestamp']) < NEWS_CACHE_TTL


# ══════════════════════════════════════════════════════════════════════════════
# EODHD NEWS API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_recent_news(ticker: str, limit: int = 10) -> Optional[list]:
    """
    Fetch recent news for ticker from EODHD

    Args:
        ticker: Stock ticker symbol
        limit: Max number of articles to fetch

    Returns:
        List of news articles or None if error
    """
    try:
        url = "https://eodhd.com/api/news"
        params = {
            'api_token': config.EODHD_API_KEY,
            's': f'{ticker}.US',
            'limit': limit,
            'fmt': 'json'
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        articles = response.json()

        # Filter to last 24 hours only
        cutoff = datetime.now() - timedelta(hours=MAX_NEWS_AGE_HOURS)
        recent_articles = []

        for article in articles:
            pub_date = datetime.fromisoformat(article.get('date', '').replace('Z', '+00:00'))
            if pub_date >= cutoff:
                recent_articles.append(article)

        return recent_articles

    except Exception as e:
        print(f"[NEWS] Error fetching news for {ticker}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SENTIMENT ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_sentiment(articles: list) -> Dict:
    """
    Simple keyword-based sentiment analysis

    Returns:
        {
            'score': float (-1.0 to 1.0),
            'positive_count': int,
            'negative_count': int,
            'neutral_count': int,
            'major_negative': bool,
            'major_positive': bool
        }
    """
    if not articles:
        return {
            'score': 0.0,
            'positive_count': 0,
            'negative_count': 0,
            'neutral_count': 0,
            'major_negative': False,
            'major_positive': False
        }

    positive_count = 0
    negative_count = 0
    neutral_count = 0

    for article in articles:
        title = article.get('title', '').lower()
        content = article.get('content', '').lower()
        text = f"{title} {content}"

        # Count keyword matches
        pos_matches = sum(1 for word in POSITIVE_KEYWORDS if word in text)
        neg_matches = sum(1 for word in NEGATIVE_KEYWORDS if word in text)

        if neg_matches > pos_matches:
            negative_count += 1
        elif pos_matches > neg_matches:
            positive_count += 1
        else:
            neutral_count += 1

    total = len(articles)

    # Calculate sentiment score (-1.0 to 1.0)
    if total > 0:
        score = (positive_count - negative_count) / total
    else:
        score = 0.0

    # Major events: >50% of articles skewed one way
    major_negative = (negative_count / total) > 0.5 if total > 0 else False
    major_positive = (positive_count / total) > 0.5 if total > 0 else False

    return {
        'score': score,
        'positive_count': positive_count,
        'negative_count': negative_count,
        'neutral_count': neutral_count,
        'major_negative': major_negative,
        'major_positive': major_positive,
        'total_articles': total
    }


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FILTER FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def check_news_sentiment(ticker: str) -> Tuple[bool, float, str]:
    """
    Check news sentiment and return filter decision + confidence multiplier

    Args:
        ticker: Stock ticker

    Returns:
        (should_proceed, confidence_multiplier, reason)

    Examples:
        (True, 1.1, "Positive news catalyst")  # Boost 10%
        (True, 1.0, "Neutral/no news")         # No change
        (True, 0.9, "Mild negative news")      # Penalize 10%
        (False, 0.0, "Major negative news")    # Filter out
    """
    # Check cache first
    if _is_cache_valid(ticker):
        cached = _news_cache[ticker]['data']
        return cached['should_proceed'], cached['multiplier'], cached['reason']

    # Fetch fresh news
    articles = fetch_recent_news(ticker)

    # If no news or API error, proceed with neutral stance
    if not articles:
        result = {
            'should_proceed': True,
            'multiplier': 1.0,
            'reason': 'No recent news available'
        }
        _news_cache[ticker] = {'data': result, 'timestamp': time.time()}
        return result['should_proceed'], result['multiplier'], result['reason']

    # Analyze sentiment
    sentiment = analyze_sentiment(articles)

    # Decision logic
    if sentiment['major_negative']:
        # Filter signals during major negative news events
        result = {
            'should_proceed': False,
            'multiplier': 0.0,
            'reason': f"Major negative news ({sentiment['negative_count']}/{sentiment['total_articles']} articles)"
        }

    elif sentiment['major_positive']:
        # Boost confidence for positive catalysts
        result = {
            'should_proceed': True,
            'multiplier': 1.10,  # 10% boost
            'reason': f"Positive news catalyst ({sentiment['positive_count']}/{sentiment['total_articles']} articles)"
        }

    elif sentiment['score'] < -0.3:
        # Mild negative news - penalize but don't filter
        result = {
            'should_proceed': True,
            'multiplier': 0.90,  # 10% penalty
            'reason': f"Mildly negative news (score: {sentiment['score']:.2f})"
        }

    elif sentiment['score'] > 0.3:
        # Mild positive news - small boost
        result = {
            'should_proceed': True,
            'multiplier': 1.05,  # 5% boost
            'reason': f"Mildly positive news (score: {sentiment['score']:.2f})"
        }

    else:
        # Neutral news or no strong signal
        result = {
            'should_proceed': True,
            'multiplier': 1.0,
            'reason': f"Neutral news sentiment (score: {sentiment['score']:.2f})"
        }

    # Cache result
    _news_cache[ticker] = {'data': result, 'timestamp': time.time()}

    return result['should_proceed'], result['multiplier'], result['reason']


# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def get_news_summary(ticker: str) -> Dict:
    """Get full news summary with sentiment details"""
    articles = fetch_recent_news(ticker)

    if not articles:
        return {'error': 'No news available'}

    sentiment = analyze_sentiment(articles)
    should_proceed, multiplier, reason = check_news_sentiment(ticker)

    return {
        'ticker': ticker,
        'articles_count': len(articles),
        'sentiment': sentiment,
        'filter_decision': {
            'should_proceed': should_proceed,
            'confidence_multiplier': multiplier,
            'reason': reason
        }
    }


def clear_news_cache():
    """Clear all cached news data"""
    _news_cache.clear()
    print("[NEWS] Cache cleared")


# ══════════════════════════════════════════════════════════════════════════════
# TESTING
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test with sample tickers
    test_tickers = ["AAPL", "TSLA", "NVDA"]

    print("\n=== NEWS FILTER TEST ===\n")

    for ticker in test_tickers:
        print(f"\n--- {ticker} ---")
        should_proceed, multiplier, reason = check_news_sentiment(ticker)
        print(f"Should Proceed: {should_proceed}")
        print(f"Confidence Mult: {multiplier:.2f}x")
        print(f"Reason: {reason}")

        # Get full summary
        summary = get_news_summary(ticker)
        if 'sentiment' in summary:
            sent = summary['sentiment']
            print(f"Articles: {sent['total_articles']} | "
                  f"Pos: {sent['positive_count']} | "
                  f"Neg: {sent['negative_count']} | "
                  f"Score: {sent['score']:.2f}")