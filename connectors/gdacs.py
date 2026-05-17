import feedparser
from datetime import datetime

_RSS_URL = "https://www.gdacs.org/xml/rss.xml"

# GDACS alert level → urgency mapping
_ALERT_URGENCY = {"Red": "immediate", "Orange": "24h", "Green": "low"}


def fetch_alerts(max_items: int = 50) -> list[dict]:
    """Fetch global disaster alerts from GDACS RSS.

    GDACS aggregates data from NOAA, USGS, ECMWF, and regional met agencies
    into a single scored alert feed covering earthquakes, floods, cyclones,
    volcanoes, wildfires, and droughts. No credentials required.
    """
    try:
        feed = feedparser.parse(_RSS_URL)
        alerts = []
        for entry in feed.entries[:max_items]:
            alert_level = entry.get("gdacs_alertlevel", "")
            event_type  = entry.get("gdacs_eventtype", "")
            country     = entry.get("gdacs_country", "")
            severity    = entry.get("gdacs_severity", {})
            population  = entry.get("gdacs_population", {})

            raw = (
                f"{entry.get('title', '')}. "
                f"Event type: {event_type}. Alert level: {alert_level}. "
                f"Country: {country}. "
                f"Severity: {getattr(severity, 'value', '')}. "
                f"Affected population: {getattr(population, 'value', '')}. "
                f"{entry.get('summary', '')}"
            )

            alerts.append({
                "source_type":   "gdacs",
                "source_id":     entry.get("id") or entry.get("link", ""),
                "url":           entry.get("link", ""),
                "timestamp":     _parse_timestamp(entry),
                "raw_text":      raw,
                "location_hint": {"name": country, "country": country},
            })
        return alerts
    except Exception as e:
        print(f"[gdacs] Error: {e}")
        return []


def _parse_timestamp(entry) -> str:
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6]).isoformat()
    return datetime.utcnow().isoformat()
