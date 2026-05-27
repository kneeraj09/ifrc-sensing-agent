"""
Three-layer reliability and safety scorer for route segments.

Reliability prior
─────────────────
  Layer 1 — ACLED conflict density near segment midpoint   (weight 0.40)
  Layer 2 — GDACS hazard baseline for the countries        (weight 0.30)
  Layer 3 — Manual coordinator override                    (weight 0.30, default 0.85)

Safety score
────────────
  Derived from ACLED event severity and fatality counts near the segment.
  Range: 0.0 (completely unsafe) → 1.0 (no known risk).

Both scores are bounded to [0.05, 0.99] so no segment is ever perfectly
scored or entirely discarded by the algorithm.
"""

import math
from datetime import datetime, timezone


# ── Defaults ────────────────────────────────────────────────────────────────

_DEFAULT_RELIABILITY = 0.85
_DEFAULT_SAFETY      = 0.85
_ACLED_WEIGHT        = 0.40
_GDACS_WEIGHT        = 0.30
_MANUAL_WEIGHT       = 0.30

# km radius for ACLED event lookup around segment midpoint
_ACLED_RADIUS_KM = 150
# Days back to consider ACLED events "current"
_ACLED_LOOKBACK_DAYS = 90
# How quickly ACLED events decay — events older than this contribute half weight
_ACLED_HALFLIFE_DAYS = 30


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _clamp(v: float, lo: float = 0.05, hi: float = 0.99) -> float:
    return max(lo, min(hi, v))


def _days_ago(iso_str: str) -> float:
    """Return how many days ago the ISO timestamp was."""
    try:
        ts = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 86400
    except Exception:
        return 999.0


def score_segment(
    from_node: dict,
    to_node: dict,
    acled_events: list[dict],
    gdacs_profiles: list[dict],
    manual_reliability: float | None = None,
    manual_safety: float | None = None,
) -> dict:
    """
    Compute reliability and safety scores for a segment between two nodes.

    Parameters
    ----------
    from_node, to_node : dict  with 'lat', 'lon', 'iso3' keys
    acled_events       : list of ACLED signal dicts (from store.db.get_recent_signals)
    gdacs_profiles     : list of hazard profile dicts (from risk.baseline.compute_hazard_profiles)
    manual_reliability : 0–1 override from coordinator (None → use default 0.85)
    manual_safety      : 0–1 override from coordinator (None → use ACLED-derived)

    Returns
    -------
    dict with keys: reliability, safety, acled_score, gdacs_score, manual_score
    """
    mid_lat = (from_node.get("lat", 0) + to_node.get("lat", 0)) / 2
    mid_lon = (from_node.get("lon", 0) + to_node.get("lon", 0)) / 2
    iso3_set = {from_node.get("iso3", ""), to_node.get("iso3", "")} - {""}

    # ── Layer 1: ACLED conflict density ─────────────────────────────────────
    acled_score  = _DEFAULT_RELIABILITY
    raw_safety   = _DEFAULT_SAFETY
    if acled_events:
        nearby_events = []
        for ev in acled_events:
            elat = ev.get("lat") or 0.0
            elon = ev.get("lon") or 0.0
            if elat == 0.0 and elon == 0.0:
                continue
            dist_km = _haversine_km(mid_lat, mid_lon, elat, elon)
            if dist_km <= _ACLED_RADIUS_KM:
                age_days = _days_ago(ev.get("timestamp", ""))
                if age_days <= _ACLED_LOOKBACK_DAYS:
                    decay = 0.5 ** (age_days / _ACLED_HALFLIFE_DAYS)
                    nearby_events.append({
                        "dist_km": dist_km,
                        "decay": decay,
                        "urgency": ev.get("urgency", "low"),
                        "signal_type": ev.get("signal_type", ""),
                    })

        if nearby_events:
            # Weighted conflict density 0→1 (1 = many/recent events nearby)
            density = 0.0
            for ev in nearby_events:
                urgency_w = {"immediate": 1.0, "24h": 0.8, "72h": 0.5, "low": 0.2}.get(
                    ev["urgency"], 0.3
                )
                is_conflict = 1.0 if ev["signal_type"] in ("conflict", "access", "risk") else 0.4
                density += urgency_w * is_conflict * ev["decay"] * (
                    1.0 - ev["dist_km"] / _ACLED_RADIUS_KM
                )

            # Normalise: density≥5 → acled_score≈0.2
            norm = min(density / 5.0, 1.0)
            acled_score = _clamp(1.0 - 0.75 * norm)
            raw_safety  = _clamp(1.0 - 0.85 * norm)

    # ── Layer 2: GDACS hazard baseline ──────────────────────────────────────
    gdacs_score = _DEFAULT_RELIABILITY
    if gdacs_profiles and iso3_set:
        tier_penalty = {"critical": 0.45, "high": 0.30, "medium": 0.15, "low": 0.05}
        worst = 0.0
        for p in gdacs_profiles:
            if p.get("iso3") in iso3_set:
                worst = max(worst, tier_penalty.get(p.get("risk_tier", "low"), 0.05))
        gdacs_score = _clamp(_DEFAULT_RELIABILITY - worst)

    # ── Layer 3: Manual coordinator input ───────────────────────────────────
    man_rel = manual_reliability if manual_reliability is not None else _DEFAULT_RELIABILITY

    # ── Weighted composite ───────────────────────────────────────────────────
    reliability = _clamp(
        _ACLED_WEIGHT * acled_score +
        _GDACS_WEIGHT * gdacs_score +
        _MANUAL_WEIGHT * man_rel
    )

    safety = _clamp(
        manual_safety if manual_safety is not None else raw_safety
    )

    return {
        "reliability":  reliability,
        "safety":       safety,
        "acled_score":  acled_score,
        "gdacs_score":  gdacs_score,
        "manual_score": man_rel,
    }


def rescore_all_segments(acled_events: list[dict], gdacs_profiles: list[dict]):
    """
    Recompute scores for every segment in the DB and persist results.
    Called during the sensing cycle (routing.monitor).
    """
    from store.db import get_route_segments, get_route_nodes, update_segment_scores

    nodes   = {n["id"]: n for n in get_route_nodes()}
    for seg in get_route_segments():
        fn = nodes.get(seg["from_node"])
        tn = nodes.get(seg["to_node"])
        if not fn or not tn:
            continue
        scores = score_segment(fn, tn, acled_events, gdacs_profiles)
        update_segment_scores(seg["id"], scores["reliability"], scores["safety"])
