"""
Mission execution monitor — runs during the sensing cycle.

Two checks on every cycle
──────────────────────────
  1. Overdue check-ins
     Flags any active mission that has had no check-in for more than
     MISSION_CHECKIN_ALERT_HOURS (default 6h from config.py).

  2. Route disruption detection
     Looks at new signals from Agent 1 (conflict / access / infrastructure)
     and cross-references them with segments on active mission routes.
     Creates route_disruption records and logs alerts.
"""

import math
from datetime import datetime, timezone

from config import MISSION_CHECKIN_ALERT_HOURS
from store.db import (
    get_active_missions, get_routing_plans, get_route_segments, get_route_nodes,
    upsert_route_disruption, get_route_disruptions,
)


def _hours_since(iso_str: str | None) -> float:
    """Return how many hours have elapsed since an ISO timestamp."""
    if not iso_str:
        return float("inf")
    try:
        ts = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 3600
    except Exception:
        return float("inf")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _active_route_segment_ids(missions: list[dict], plans: dict) -> dict[str, list[str]]:
    """
    Return a mapping of {segment_id: [mission_ids]} for all segments
    that appear in the routes of in-transit missions.
    """
    seg_to_missions: dict[str, list[str]] = {}
    for m in missions:
        if m["mission_status"] not in ("in_transit", "preparing", "delayed"):
            continue
        plan = plans.get(m["routing_plan_id"])
        if not plan:
            continue
        route = plan.get("route_json", {})
        for edge in route.get("edges", []):
            sid = edge.get("segment_id", "")
            if sid and not sid.startswith("auto_"):
                seg_to_missions.setdefault(sid, []).append(m["id"])
    return seg_to_missions


# ── Public API ───────────────────────────────────────────────────────────────

def check_active_missions(recent_signals: list[dict] = None) -> list[str]:
    """
    Run all monitoring checks and return a list of alert strings.

    Parameters
    ----------
    recent_signals : list of signal dicts from get_recent_signals()
                     Used for disruption detection; pass [] to skip.

    Returns
    -------
    list of human-readable alert strings (empty if nothing to flag).
    """
    alerts: list[str] = []

    missions = get_active_missions()
    if not missions:
        return alerts

    all_plans  = get_routing_plans()
    plans_by_id = {p["id"]: p for p in all_plans}

    # ── 1. Overdue check-ins ─────────────────────────────────────────────────
    for m in missions:
        if m["mission_status"] not in ("in_transit", "delayed"):
            continue
        hrs = _hours_since(m.get("last_checkin_at") or m.get("departure_time"))
        if hrs >= MISSION_CHECKIN_ALERT_HOURS:
            alert = (
                f"[OVERDUE CHECK-IN] Mission {m['id'][:8]} "
                f"({m.get('last_position') or 'position unknown'}) — "
                f"no update for {hrs:.1f}h (threshold {MISSION_CHECKIN_ALERT_HOURS}h)"
            )
            alerts.append(alert)

    # ── 2. Disruptions from Agent 1 signals ─────────────────────────────────
    if recent_signals:
        seg_to_missions = _active_route_segment_ids(missions, plans_by_id)
        if seg_to_missions:
            segments = {s["id"]: s for s in get_route_segments()}
            nodes    = {n["id"]: n for n in get_route_nodes()}
            existing_disruptions = {d["segment_id"] for d in get_route_disruptions(active_only=True)}

            conflict_signals = [
                s for s in recent_signals
                if s.get("signal_type") in ("conflict", "access", "risk", "infrastructure")
                and s.get("lat") and s.get("lon")
            ]

            for sid, mission_ids in seg_to_missions.items():
                if sid in existing_disruptions:
                    continue   # already logged
                seg = segments.get(sid)
                if not seg:
                    continue
                fn = nodes.get(seg["from_node"])
                tn = nodes.get(seg["to_node"])
                if not fn or not tn:
                    continue
                mid_lat = (fn["lat"] + tn["lat"]) / 2
                mid_lon = (fn["lon"] + tn["lon"]) / 2

                for sig in conflict_signals:
                    dist = _haversine_km(mid_lat, mid_lon, sig["lat"], sig["lon"])
                    if dist <= 200:  # 200 km proximity
                        stype    = sig.get("signal_type", "conflict")
                        urgency  = sig.get("urgency", "unknown")
                        severity = {"immediate": "critical", "24h": "high",
                                    "72h": "medium"}.get(urgency, "low")

                        disruption = {
                            "segment_id":      sid,
                            "disruption_type": stype,
                            "severity":        severity,
                            "description":     (
                                f"Signal from {sig.get('source_type','?')} within "
                                f"{dist:.0f} km of segment "
                                f"{fn['name']} → {tn['name']}. "
                                f"Urgency: {urgency}. "
                                f"Confidence: {sig.get('confidence', 0):.2f}."
                            ),
                            "reported_at":     sig.get("timestamp", datetime.utcnow().isoformat()),
                            "source":          f"agent1_{sig.get('source_type','signal')}",
                            "active":          1,
                        }
                        upsert_route_disruption(disruption)

                        alert = (
                            f"[ROUTE DISRUPTION] {fn['name']} → {tn['name']}: "
                            f"{stype} signal ({severity}) detected {dist:.0f} km away. "
                            f"Affects mission(s): {', '.join(m[:8] for m in mission_ids)}"
                        )
                        alerts.append(alert)
                        break   # one disruption record per segment per cycle

    return alerts


def run_monitor(recent_signals: list[dict] = None) -> int:
    """
    Convenience entry point called from main.py `route-monitor`.

    Returns the number of alerts raised.
    """
    alerts = check_active_missions(recent_signals or [])
    if alerts:
        print(f"\n{'='*60}")
        print(f"  ROUTING MONITOR — {len(alerts)} ALERT(S)")
        print(f"{'='*60}")
        for a in alerts:
            print(f"  {a}")
    else:
        missions = get_active_missions()
        active = [m for m in missions if m["mission_status"] in ("in_transit", "delayed")]
        print(f"[route-monitor] {len(active)} active mission(s). No alerts.")
    return len(alerts)
