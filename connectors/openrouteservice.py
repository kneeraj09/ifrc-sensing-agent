"""
OpenRouteService (ORS) connector — free, OSM-based routing API.

Africa coverage is excellent.  Register for a free key at:
    https://openrouteservice.org/dev/#/signup

Free tier: 2,000 requests/day, 40 requests/minute.

Fallback
────────
If ORS_API_KEY is empty or the request fails, we fall back to:
    distance = haversine(origin, destination) × ROAD_FACTOR (1.4)
    duration = distance / CONVOY_SPEED_KMH (50)

This gives ~±30% accuracy — acceptable for planning; do not use for SLA
commitments.
"""

import math
import time
import urllib.request
import urllib.error
import json

from config import ORS_API_KEY

_ORS_BASE    = "https://api.openrouteservice.org/v2/directions/driving-hgv"
_ROAD_FACTOR = 1.4    # straight-line → road distance multiplier
_CONV_KMH    = 50.0   # humanitarian convoy speed (km/h)
_LAST_CALL   = 0.0    # module-level rate-limit guard
_MIN_GAP_SEC = 1.5    # minimum seconds between ORS calls


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _haversine_fallback(origin: dict, destination: dict) -> dict:
    """Return a fallback estimate using haversine × road factor."""
    dist = _haversine_km(
        origin["lat"], origin["lon"],
        destination["lat"], destination["lon"],
    ) * _ROAD_FACTOR
    duration = dist / _CONV_KMH
    return {
        "distance_km": round(dist, 1),
        "duration_h":  round(duration, 2),
        "source":      "haversine_fallback",
    }


def route_between_nodes(origin: dict, destination: dict) -> dict:
    """
    Get road distance and travel time between two node dicts.

    Each node dict must have 'lat' and 'lon' keys.

    Returns
    -------
    dict with:
        distance_km  — road distance in kilometres
        duration_h   — travel time in hours
        source       — "ors" | "haversine_fallback"
    """
    global _LAST_CALL

    if not ORS_API_KEY:
        return _haversine_fallback(origin, destination)

    # Respect rate limit
    gap = time.time() - _LAST_CALL
    if gap < _MIN_GAP_SEC:
        time.sleep(_MIN_GAP_SEC - gap)
    _LAST_CALL = time.time()

    coords = [
        [origin["lon"],      origin["lat"]],
        [destination["lon"], destination["lat"]],
    ]
    payload = json.dumps({
        "coordinates": coords,
        "units":       "km",
        "geometry":    False,
    }).encode()

    req = urllib.request.Request(
        _ORS_BASE,
        data=payload,
        headers={
            "Authorization": ORS_API_KEY,
            "Content-Type":  "application/json; charset=utf-8",
            "Accept":        "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        summary  = data["routes"][0]["summary"]
        dist_km  = summary["distance"]          # already in km (units=km)
        dur_sec  = summary["duration"]          # seconds
        dur_h    = dur_sec / 3600
        # Scale to convoy speed (ORS default is ~80 km/h for HGV)
        ors_kph  = dist_km / max(dur_h, 0.01)
        if ors_kph > _CONV_KMH:
            dur_h = dist_km / _CONV_KMH        # apply convoy speed cap
        return {
            "distance_km": round(dist_km, 1),
            "duration_h":  round(dur_h, 2),
            "source":      "ors",
        }
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        print(f"[ors] Routing API error ({origin.get('name','?')} → "
              f"{destination.get('name','?')}): {e} — using fallback")
        return _haversine_fallback(origin, destination)


def route_multi_stop(nodes: list[dict]) -> dict:
    """
    Get road distance and travel time for a multi-stop itinerary.

    Parameters
    ----------
    nodes : list of node dicts (in order: origin, stop1, stop2, …, final)

    Returns
    -------
    dict with:
        total_distance_km
        total_duration_h
        legs              — list of per-leg dicts {distance_km, duration_h, source}
        source            — "ors" | "haversine_fallback"
    """
    if len(nodes) < 2:
        return {"total_distance_km": 0.0, "total_duration_h": 0.0, "legs": [], "source": "none"}

    legs = []
    for i in range(len(nodes) - 1):
        leg = route_between_nodes(nodes[i], nodes[i + 1])
        legs.append(leg)

    return {
        "total_distance_km": round(sum(l["distance_km"] for l in legs), 1),
        "total_duration_h":  round(sum(l["duration_h"]  for l in legs), 2),
        "legs":              legs,
        "source":            "ors" if any(l["source"] == "ors" for l in legs)
                             else "haversine_fallback",
    }
