"""
Derive routing plans from ratified allocation runs (Agent 3 output).

For each ratified run the planner:
  1. Identifies the origin node (depot_location from stock_positions, mapped to
     the nearest route_node via haversine, or matched by name).
  2. Reads the selected scenario results to extract destination locations +
     allocated quantities.
  3. Calls connectors.openrouteservice (with haversine fallback) for distance
     and travel-time estimates between every origin–destination pair.
  4. Stores a routing_plan row per (origin, destination) pair.

Multi-stop / convoy clustering (Phase 2 placeholder): when multiple
destinations share the same origin and their total quantity fits a single
truck, they can be merged into one multi-stop plan.  This version generates
one plan per destination and marks the field `planner_notes` with convoy hints.
"""

import json
import uuid
from datetime import datetime

from store.db import (
    get_ratified_allocation_runs, get_route_nodes,
    upsert_routing_plan, get_routing_plans,
)
from routing.graph import RouteGraph
from connectors import openrouteservice as ors


# Maximum km from a depot name to its matched node before we give up matching
_MAX_DEPOT_MATCH_KM = 300


def _name_match(depot: str, nodes: list[dict]) -> dict | None:
    """Try to match a depot name string to a route node by substring."""
    depot_l = depot.strip().lower()
    for n in nodes:
        if depot_l in n["name"].lower() or n["name"].lower() in depot_l:
            return n
        if depot_l in (n.get("country") or "").lower():
            return n
    return None


def _nearest_node(lat: float, lon: float, nodes: list[dict]) -> dict | None:
    import math
    def hav(a, b, c, d):
        R = 6371.0
        p1, p2 = math.radians(a), math.radians(c)
        dp, dl = math.radians(c - a), math.radians(d - b)
        x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))
    best, best_d = None, float("inf")
    for n in nodes:
        if n.get("lat") is None:
            continue
        d = hav(lat, lon, n["lat"], n["lon"])
        if d < best_d:
            best_d, best = d, n
    return best if best_d <= _MAX_DEPOT_MATCH_KM else None


def _resolve_origin(depot_location: str, nodes: list[dict]) -> dict | None:
    """Map a depot_location string to a route_node."""
    # Try name match first
    node = _name_match(depot_location, nodes)
    if node:
        return node
    # If depot_location is "Name, Country" style, try splitting
    parts = [p.strip() for p in depot_location.split(",")]
    for part in parts:
        node = _name_match(part, nodes)
        if node:
            return node
    return None


def plan_from_allocation(run_id: str | None = None) -> list[dict]:
    """
    Build routing plans from one or all ratified allocation runs.

    Parameters
    ----------
    run_id : str, optional
        Specific allocation run ID.  If None, processes the most-recent
        ratified run that does not yet have routing plans.

    Returns
    -------
    list of plan dicts as stored in the DB.
    """
    runs  = get_ratified_allocation_runs()
    nodes = get_route_nodes()

    if not runs:
        print("[planner] No ratified allocation runs found.")
        return []

    # Filter to a specific run or find the first unplanned one
    if run_id:
        runs = [r for r in runs if r["id"] == run_id]
    else:
        existing_ids = {p["allocation_run_id"] for p in get_routing_plans()}
        runs = [r for r in runs if r["id"] not in existing_ids][:1]

    if not runs:
        print("[planner] No unplanned ratified runs to process.")
        return []

    # Build the route graph (loads segments + auto-edges)
    graph = RouteGraph()
    graph.load_from_db(auto_edges=True)

    created_plans: list[dict] = []

    for run in runs:
        print(f"[planner] Planning routes for run {run['id'][:8]}… "
              f"({run['commodity']} {run['available_stock']} {run['unit']})")

        # ── Identify origin node ─────────────────────────────────────────────
        # Priority order:
        #   1. Stock position whose commodity matches (exact)
        #   2. Any stock position when commodity is "all" or no exact match
        #   3. First valid (non-blank, non-<UNKNOWN>) location in scenario_results
        from store.db import get_stock_positions
        stock = get_stock_positions()
        commodity = run["commodity"]

        _BAD_LOCS = {"", "<unknown>", "unknown", "none", "n/a"}

        depot_str = ""
        # Pass 1: exact commodity match
        for sp in stock:
            if sp["commodity"].lower() == commodity.lower():
                depot_str = sp.get("depot_location", "").strip()
                break
        # Pass 2: any stock position (catches commodity="all" or mismatched labels)
        if not depot_str or depot_str.lower() in _BAD_LOCS:
            for sp in stock:
                candidate = sp.get("depot_location", "").strip()
                if candidate and candidate.lower() not in _BAD_LOCS:
                    depot_str = candidate
                    print(f"  [planner] No exact commodity match — using depot '{depot_str}' from stock position")
                    break
        # Pass 3: first valid location from scenario results
        if not depot_str or depot_str.lower() in _BAD_LOCS:
            for sc, results in run["scenario_results"].items():
                for r in results:
                    loc = (r.get("location") or "").strip()
                    if loc and loc.lower() not in _BAD_LOCS:
                        depot_str = loc
                        print(f"  [planner] No stock positions found — using first result location '{depot_str}' as origin")
                        break
                if depot_str:
                    break

        if not depot_str or depot_str.lower() in _BAD_LOCS:
            print(f"  [planner] Could not determine origin depot for run {run['id'][:8]}.")
            print(f"  [planner] Tip: add a stock position with a depot_location that matches a route node name.")
            continue

        origin_node = _resolve_origin(depot_str, nodes)
        if not origin_node:
            print(f"  [planner] Could not match '{depot_str}' to any route node — skipping run.")
            print(f"  [planner] Available nodes: {', '.join(n['name'] for n in nodes[:10])}…")
            print(f"  [planner] Tip: the depot_location in your stock position should contain a city name")
            print(f"             that matches one of the 46 seeded waypoints (e.g. 'Nairobi', 'Kampala').")
            continue
        print(f"  [planner] Origin: {origin_node['name']} ({origin_node['id']})")

        # ── Extract destinations ─────────────────────────────────────────────
        scenario_name  = run.get("selected_scenario") or "balanced"
        allocations    = run["scenario_results"].get(scenario_name, [])
        if not allocations:
            # Fall back to any non-empty scenario
            for sc, res in run["scenario_results"].items():
                if res:
                    allocations    = res
                    scenario_name  = sc
                    break

        if not allocations:
            print(f"  [planner] No scenario results in run {run['id'][:8]} — skipping.")
            continue

        # ── One plan per destination ─────────────────────────────────────────
        for alloc in allocations:
            dest_str = (alloc.get("location") or "").strip()
            qty      = alloc.get("allocated_qty", alloc.get("quantity"))

            # Skip blank / unknown destinations
            if not dest_str or dest_str.lower() in _BAD_LOCS:
                continue

            dest_node = _resolve_origin(dest_str, nodes)
            if not dest_node:
                print(f"    [planner] No node match for destination '{dest_str}' — skipping.")
                continue

            if dest_node["id"] == origin_node["id"]:
                print(f"    [planner] Origin == destination ({dest_str}) — skipping.")
                continue

            # ── Route finding ────────────────────────────────────────────────
            route_result = graph.best_path(origin_node["id"], dest_node["id"])

            # Try ORS for real road distance if key is configured
            ors_result = ors.route_between_nodes(origin_node, dest_node)

            total_km  = ors_result.get("distance_km") or (route_result["total_km"] if route_result else None)
            est_hours = ors_result.get("duration_h")  or (route_result["est_hours"]  if route_result else None)

            route_json = {}
            composite  = None
            if route_result:
                composite  = route_result["composite_score"]
                route_json = {
                    "path":             route_result["path"],
                    "path_labels":      [graph.node_label(n) for n in route_result["path"]],
                    "total_km":         total_km,
                    "est_hours":        est_hours,
                    "composite_score":  composite,
                    "min_safety":       route_result["min_safety"],
                    "prod_reliability": route_result["prod_reliability"],
                    "ors_used":         bool(ors_result.get("distance_km")),
                }

            plan = {
                "id":                str(uuid.uuid4()),
                "allocation_run_id": run["id"],
                "origin_node":       origin_node["id"],
                "destination_nodes": [dest_node["id"]],
                "commodity":         commodity,
                "quantity":          qty,
                "unit":              run["unit"],
                "plan_status":       "proposed",
                "route_json":        route_json,
                "total_km":          total_km,
                "est_hours":         est_hours,
                "composite_score":   composite,
                "planner_notes":     (
                    f"Auto-planned from allocation run {run['id'][:8]}. "
                    f"Scenario: {scenario_name}. "
                    f"Destination: {dest_str}."
                ),
                "created_at":        datetime.utcnow().isoformat(),
                "approved_at":       None,
                "approved_by":       None,
            }

            upsert_routing_plan(plan)
            created_plans.append(plan)
            km_str  = f"{total_km:.0f} km"   if total_km  else "dist unknown"
            hrs_str = f"{est_hours:.1f}h"    if est_hours else "time unknown"
            print(f"    [planner] Plan → {dest_node['name']}: {km_str}, {hrs_str}, "
                  f"score={composite:.3f}" if composite else f"    [planner] Plan → {dest_node['name']}: {km_str}, {hrs_str}")

    print(f"[planner] Created {len(created_plans)} routing plan(s).")
    return created_plans
