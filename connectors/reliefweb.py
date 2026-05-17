import feedparser
from datetime import datetime

# ReliefWeb public RSS feeds — no API key or registration required
_FEEDS = [
    "https://reliefweb.int/updates/rss.xml",           # all updates
    "https://reliefweb.int/disasters/rss.xml",          # active disasters
]


def fetch_reports(max_per_feed: int = 25) -> list[dict]:
    """Fetch recent humanitarian updates from ReliefWeb RSS feeds."""
    articles = []
    for feed_url in _FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_per_feed]:
                summary = entry.get("summary", "")
                articles.append({
                    "source_type": "reliefweb",
                    "source_id": entry.get("id") or entry.get("link", ""),
                    "url": entry.get("link", ""),
                    "timestamp": _parse_timestamp(entry),
                    "raw_text": f"{entry.get('title', '')}. {summary}",
                })
        except Exception as e:
            print(f"[reliefweb] Error fetching {feed_url}: {e}")
    return articles


def _parse_timestamp(entry) -> str:
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6]).isoformat()
    return datetime.utcnow().isoformat()
