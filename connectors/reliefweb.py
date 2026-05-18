import requests
from datetime import datetime, timezone, timedelta
from config import RELIEFWEB_APP_NAME

_API_BASE = "https://api.reliefweb.int/v1"
_FIELDS = ["title", "body", "country", "source", "disaster", "date", "format", "url"]


def _parse_date(date_str: str) -> str:
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _fetch_endpoint(endpoint: str, limit: int, days_back: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "appname": RELIEFWEB_APP_NAME,
        "limit": limit,
        "sort": ["date.created:desc"],
        "fields": {"include": _FIELDS},
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "date.created", "value": {"from": since}},
            ],
        },
    }
    try:
        resp = requests.post(f"{_API_BASE}/{endpoint}", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        print(f"[reliefweb] Error fetching /{endpoint}: {e}")
        return []


def fetch_reports(limit: int = 30, days_back: int = 3) -> list[dict]:
    """Fetch recent reports and disasters from the ReliefWeb API v2."""
    articles = []

    for endpoint in ("reports", "disasters"):
        items = _fetch_endpoint(endpoint, limit, days_back)
        for item in items:
            f = item.get("fields", {})
            title   = f.get("title", "")
            body    = f.get("body", "") or ""
            url     = f.get("url", "") or item.get("href", "")
            date    = _parse_date(f.get("date", {}).get("created", "") if isinstance(f.get("date"), dict) else "")

            # Build location hint from country field
            countries = f.get("country", [])
            country_names = [c.get("name", "") for c in countries if isinstance(c, dict)]

            # Combine title + body for richer extraction (truncate body to 1500 chars)
            raw_text = f"{title}.\n\n{body[:1500]}".strip() if body else title

            source_names = [s.get("name", "") for s in f.get("source", []) if isinstance(s, dict)]

            articles.append({
                "source_type":   "reliefweb",
                "source_id":     str(item.get("id", url)),
                "url":           url,
                "timestamp":     date,
                "raw_text":      raw_text,
                "location_hint": {"country": country_names[0]} if country_names else {},
            })

        print(f"[reliefweb] /{endpoint}: {len(items)} item(s)")

    return articles
