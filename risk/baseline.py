"""
Hazard Baseline Computer.

Aggregates raw GDACS historical event records (from the gdacs_events DB table)
into per-country hazard profiles. Profiles are computed on-demand from stored
events — no separate persistence needed at our scale.

Output schema (per country):
    {
        "country":       str,
        "iso3":          str,
        "region":        str,
        "total_events":  int,
        "events_per_year": float,
        "severity_index":  float,   # sum of alert-level weights (red=3, orange=2, green=1)
        "dominant_type": str,       # e.g. "FL" (flood)
        "peak_month":    str|None,  # e.g. "Mar"
        "by_type":       {type_code: count},
        "by_alert":      {alert_level: count},
    }
"""

from collections import Counter, defaultdict

# Matches _SEVERITY_WEIGHT in connectors/gdacs_historical.py
_SEVERITY_WEIGHT = {"red": 3.0, "orange": 2.0, "green": 1.0}

_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

_TYPE_LABELS = {
    "EQ": "Earthquake",
    "FL": "Flood",
    "TC": "Cyclone",
    "WF": "Wildfire",
    "DR": "Drought",
    "VO": "Volcano",
}


def type_label(code: str) -> str:
    """Return human-readable label for a GDACS event-type code."""
    return _TYPE_LABELS.get(code.upper(), code)


def compute_hazard_profiles(
    events: list[dict],
    years_back: int = 5,
) -> list[dict]:
    """Compute per-country hazard profiles from a flat list of GDACS events.

    Args:
        events:      List of event dicts as returned by get_gdacs_events().
        years_back:  Denominator for events_per_year (default 5).

    Returns:
        List of profile dicts, sorted by severity_index descending.
    """
    raw: dict[str, dict] = defaultdict(lambda: {
        "country":      "Unknown",
        "iso3":         "",
        "region":       "",
        "total_events": 0,
        "severity_sum": 0.0,
        "by_type":      Counter(),
        "by_alert":     Counter(),
        "month_counter": Counter(),
    })

    for ev in events:
        country = (ev.get("country") or "Unknown").strip()
        if not country:
            country = "Unknown"

        p = raw[country]
        p["country"] = country
        p["iso3"]   = ev.get("iso3")    or p["iso3"]
        p["region"] = ev.get("region")  or p["region"]
        p["total_events"] += 1

        ev_type     = (ev.get("event_type") or "").upper()
        alert_level = (ev.get("alert_level") or "").lower()

        p["by_type"][ev_type]     += 1
        p["by_alert"][alert_level] += 1
        p["severity_sum"] += _SEVERITY_WEIGHT.get(alert_level, 0.0)

        from_date = ev.get("from_date") or ""
        if len(from_date) >= 7:
            try:
                month = int(from_date[5:7])
                if 1 <= month <= 12:
                    p["month_counter"][month] += 1
            except ValueError:
                pass

    profiles = []
    for country, p in raw.items():
        peak_candidates = p["month_counter"].most_common(1)
        peak_month = _MONTH_NAMES[peak_candidates[0][0] - 1] if peak_candidates else None

        dominant_candidates = p["by_type"].most_common(1)
        dominant_type = dominant_candidates[0][0] if dominant_candidates else ""

        profiles.append({
            "country":        country,
            "iso3":           p["iso3"],
            "region":         p["region"],
            "total_events":   p["total_events"],
            "events_per_year": round(p["total_events"] / max(years_back, 1), 1),
            "severity_index": round(p["severity_sum"], 1),
            "dominant_type":  dominant_type,
            "dominant_label": type_label(dominant_type),
            "peak_month":     peak_month,
            "by_type":        dict(p["by_type"]),
            "by_alert":       dict(p["by_alert"]),
        })

    profiles.sort(key=lambda x: x["severity_index"], reverse=True)
    return profiles


def risk_tier(severity_index: float) -> str:
    """Map severity index to a display tier label."""
    if severity_index >= 25:
        return "critical"
    if severity_index >= 12:
        return "high"
    if severity_index >= 5:
        return "medium"
    return "low"
