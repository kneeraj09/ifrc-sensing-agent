import requests
from datetime import datetime
from config import GDELT_QUERY, GDELT_MAX_RECORDS

_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


def fetch_articles() -> list[dict]:
    """Fetch recent humanitarian/disaster articles via GDELT DOC API v2."""
    params = {
        "query": GDELT_QUERY,
        "mode": "artlist",
        "maxrecords": GDELT_MAX_RECORDS,
        "format": "json",
        "sort": "datedesc",
    }
    try:
        resp = requests.get(_DOC_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        articles = []
        for art in data.get("articles", []):
            articles.append({
                "source_type": "gdelt",
                "source_id": art.get("url", ""),
                "url": art.get("url", ""),
                "timestamp": _parse_gdelt_date(art.get("seendate", "")),
                "raw_text": art.get("title", ""),
            })
        return articles
    except Exception as e:
        print(f"[gdelt] Error: {e}")
        return []


def _parse_gdelt_date(date_str: str) -> str:
    # GDELT format: YYYYMMDDTHHMMSSZ
    try:
        return datetime.strptime(date_str, "%Y%m%dT%H%M%SZ").isoformat()
    except Exception:
        return datetime.utcnow().isoformat()
