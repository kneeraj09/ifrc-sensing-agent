"""
GDACS Historical Event Connector.

Fetches multi-year disaster event records from the GDACS REST API
(not the RSS feed) and filters them to target regions. Used to build
a historical hazard baseline for the allocation agent.

API docs: https://www.gdacs.org/Documents/2025/GDACS_API_quickstart_v2.pdf
Endpoint: https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH
"""
import requests
from datetime import datetime, timezone
from utils.regions import classify

_API_BASE = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
_TIMEOUT  = 60
_ALL_TYPES = "EQ;FL;TC;WF;DR;VO"

# Alert level → numeric severity weight (used in severity index)
_SEVERITY_WEIGHT = {"red": 3.0, "orange": 2.0, "green": 1.0}


def _fetch_year(year: int, target_regions: list[str]) -> list[dict]:
    """Fetch all events for one calendar year and filter to target regions."""
    params = {
        "eventlist":   _ALL_TYPES,
        "fromdate":    f"{year}-01-01",
        "todate":      f"{year}-12-31",
        "alertlevel":  "red;orange;green",
        "format":      "json",
    }
    try:
        resp = requests.get(_API_BASE, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except Exception as e:
        print(f"  [gdacs_hist] {year}: fetch error — {e}")
        return []

    events = []
    for f in features:
        props = f.get("properties", {})

        # Primary affected country
        affected      = props.get("affectedcountries") or []
        primary_country = ""
        primary_iso3    = ""
        if affected and isinstance(affected, list):
            first = affected[0] if isinstance(affected[0], dict) else {}
            primary_country = first.get("countryname", "")
            primary_iso3    = first.get("iso3", "")
        if not primary_country:
            primary_country = props.get("country", "")

        region = classify(primary_country)
        if region not in target_regions:
            continue

        coords = f.get("geometry", {}).get("coordinates") or [None, None]
        event_type = props.get("eventtype", "")
        event_id   = props.get("eventid", "")
        episode_id = props.get("episodeid", "")

        events.append({
            "id":          f"{event_type}_{event_id}_{episode_id}",
            "event_type":  event_type,
            "event_name":  (props.get("eventname") or props.get("name") or "").strip(),
            "country":     primary_country,
            "iso3":        primary_iso3,
            "region":      region,
            "alert_level": (props.get("alertlevel") or "").lower(),
            "alert_score": float(props.get("alertscore") or 0),
            "from_date":   (props.get("fromdate") or "")[:10],
            "to_date":     (props.get("todate")   or "")[:10],
            "lat":         coords[1] if len(coords) > 1 else None,
            "lon":         coords[0] if len(coords) > 0 else None,
            "glide":       (props.get("glide") or "").strip(),
            "event_url":   (props.get("url") or "").strip(),
        })
    return events


def fetch_historical(
    years_back:     int       = 5,
    target_regions: list[str] = None,
) -> list[dict]:
    """Fetch historical GDACS events for the specified regions.

    Args:
        years_back:      How many full calendar years to fetch (default 5).
        target_regions:  List of region names matching utils.regions.classify()
                         output. Defaults to ["Africa"] — the highest-priority
                         region for IFRC operations.

    Returns:
        List of event dicts ready for upsert_gdacs_event().
    """
    if target_regions is None:
        target_regions = ["Africa"]

    current_year = datetime.now(timezone.utc).year
    all_events   = []

    for year in range(current_year - years_back, current_year + 1):
        events = _fetch_year(year, target_regions)
        all_events.extend(events)
        print(f"  [gdacs_hist] {year}: {len(events):>3} event(s) in {', '.join(target_regions)}")

    return all_events
