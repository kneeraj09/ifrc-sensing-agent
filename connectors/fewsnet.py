import socket
import feedparser
from datetime import datetime

# FEWS NET public RSS — no credentials required
# Note: fdw.fews.net (data warehouse API) is frequently unreachable externally;
# the RSS feed is the reliable public-facing endpoint.
_FEEDS = [
    "https://fews.net/latest-updates/rss",
    "https://fews.net/feed/",
]


def fetch_alerts(limit: int = 30) -> list[dict]:
    """Fetch food security alerts from FEWS NET RSS feeds.

    Tries each feed URL in order and returns the first that yields results.
    If both are unreachable, skips cleanly — FEWS NET content is also
    partially captured via ReliefWeb and HDX connectors.
    """
    for feed_url in _FEEDS:
        try:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(20)
            try:
                feed = feedparser.parse(feed_url)
            finally:
                socket.setdefaulttimeout(old_timeout)
            if not feed.entries:
                continue
            articles = []
            for entry in feed.entries[:limit]:
                articles.append({
                    "source_type":   "fewsnet",
                    "source_id":     entry.get("id") or entry.get("link", ""),
                    "url":           entry.get("link", ""),
                    "timestamp":     _parse_timestamp(entry),
                    "raw_text":      f"{entry.get('title', '')}. {entry.get('summary', '')}",
                    "location_hint": {},
                })
            if articles:
                return articles
        except Exception as e:
            print(f"[fewsnet] {feed_url} — {e}")

    print("[fewsnet] No feeds reachable — skipping. FEWS NET content is partially covered via ReliefWeb/HDX.")
    return []


def _parse_timestamp(entry) -> str:
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6]).isoformat()
    return datetime.utcnow().isoformat()
