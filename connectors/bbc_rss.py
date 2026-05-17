import feedparser
from datetime import datetime
from config import BBC_FEEDS


def fetch_articles(max_per_feed: int = 20) -> list[dict]:
    """Fetch recent articles from all configured BBC RSS feeds."""
    articles = []
    for feed_url in BBC_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_per_feed]:
                articles.append({
                    "source_type": "bbc",
                    "source_id": entry.get("id") or entry.get("link", ""),
                    "url": entry.get("link", ""),
                    "timestamp": _parse_timestamp(entry),
                    "raw_text": f"{entry.get('title', '')}. {entry.get('summary', '')}",
                })
        except Exception as e:
            print(f"[bbc_rss] Error fetching {feed_url}: {e}")
    return articles


def _parse_timestamp(entry) -> str:
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6]).isoformat()
    return datetime.utcnow().isoformat()
