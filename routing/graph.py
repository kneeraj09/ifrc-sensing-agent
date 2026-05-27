"""
Weighted directed route graph with composite-score path finding.

Composite score (higher = better)
───────────────────────────────────
  score = w_safety × min_safety + w_rel × prod_reliability − w_time × norm_time

Where:
  min_safety     = minimum safety score along the path (bottleneck)
  prod_reliability = product of reliability scores (independent probabilities)
  norm_time      = total_hours / MAX_HOURS (normalised, cap at 1.0)
  MAX_HOURS      = 120h (5 days)

Weights default to config.py values: 0.50 / 0.30 / 0.20
"""

import heapq
import math
from typing import Optional

from config import ROUTE_W_SAFETY, ROUTE_W_RELIABILITY, ROUTE_W_TIME

_MAX_HOURS = 120.0   # normalisation cap


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class RouteGraph:
    """
    Directed graph over humanitarian waypoints.

    Nodes are loaded from route_nodes; edges from route_segments.
    If a segment is missing, a synthetic "open road" edge is added between any
    two nodes within AUTO_EDGE_KM using haversine × 1.4 at 50 km/h with
    default reliability/safety priors.
    """

    AUTO_EDGE_KM         = 1200   # max km to auto-generate an edge (African corridors)
    AUTO_CONV_SPEED_KMH  = 50.0   # humanitarian convoy speed estimate
    AUTO_ROAD_FACTOR     = 1.4    # straight-line → road distance multiplier
    AUTO_RELIABILITY     = 0.75
    AUTO_SAFETY          = 0.75

    def __init__(self):
        self.nodes: dict[str, dict]        = {}   # id → node dict
        self.edges: dict[str, list[dict]]  = {}   # from_id → [edge dicts]

    # ── Build ────────────────────────────────────────────────────────────────

    def load_from_db(self, auto_edges: bool = True):
        """Load nodes and segments from the database."""
        from store.db import get_route_nodes, get_route_segments

        self.nodes = {n["id"]: n for n in get_route_nodes()}
        self.edges = {nid: [] for nid in self.nodes}

        for seg in get_route_segments():
            fn, tn = seg["from_node"], seg["to_node"]
            if fn not in self.nodes or tn not in self.nodes:
                continue
            self.edges.setdefault(fn, []).append({
                "to":          tn,
                "distance_km": seg["distance_km"] or self._straight_dist(fn, tn),
                "est_hours":   seg["est_hours"]   or self._road_hours(fn, tn),
                "reliability": seg["reliability_score"] or self.AUTO_RELIABILITY,
                "safety":      seg["safety_score"]      or self.AUTO_SAFETY,
                "segment_id":  seg["id"],
            })

        if auto_edges:
            self._add_auto_edges()

    def _straight_dist(self, a: str, b: str) -> float:
        na, nb = self.nodes[a], self.nodes[b]
        return _haversine_km(na["lat"], na["lon"], nb["lat"], nb["lon"])

    def _road_hours(self, a: str, b: str) -> float:
        return (self._straight_dist(a, b) * self.AUTO_ROAD_FACTOR) / self.AUTO_CONV_SPEED_KMH

    def _add_auto_edges(self):
        """Add synthetic edges for nearby node pairs with no existing segment."""
        existing = set()
        for fn, edges in self.edges.items():
            for e in edges:
                existing.add((fn, e["to"]))

        node_list = list(self.nodes.values())
        for i, na in enumerate(node_list):
            for nb in node_list[i + 1:]:
                dist = _haversine_km(na["lat"], na["lon"], nb["lat"], nb["lon"])
                if dist > self.AUTO_EDGE_KM:
                    continue
                hours = (dist * self.AUTO_ROAD_FACTOR) / self.AUTO_CONV_SPEED_KMH
                for src, dst in [(na["id"], nb["id"]), (nb["id"], na["id"])]:
                    if (src, dst) not in existing:
                        self.edges.setdefault(src, []).append({
                            "to":          dst,
                            "distance_km": dist * self.AUTO_ROAD_FACTOR,
                            "est_hours":   hours,
                            "reliability": self.AUTO_RELIABILITY,
                            "safety":      self.AUTO_SAFETY,
                            "segment_id":  f"auto_{src}_{dst}",
                        })
                        existing.add((src, dst))

    # ── Path finding ─────────────────────────────────────────────────────────

    def best_path(self, origin: str, destination: str) -> Optional[dict]:
        """
        Find the path from origin → destination that maximises the composite score.

        We negate the score to use Python's min-heap as a max-heap.

        Returns
        -------
        dict with keys:
            path          — list of node IDs (includes origin and destination)
            total_km      — road distance
            est_hours     — estimated travel hours
            composite_score
            min_safety    — bottleneck safety
            prod_reliability
            edges         — list of edge dicts along the path
        or None if no path exists.
        """
        if origin not in self.nodes or destination not in self.nodes:
            return None
        if origin == destination:
            return {
                "path": [origin], "total_km": 0.0, "est_hours": 0.0,
                "composite_score": 1.0, "min_safety": 1.0,
                "prod_reliability": 1.0, "edges": [],
            }

        # State: (-score, node_id, path, total_km, total_hours, min_safety, prod_rel, edges)
        initial = (-0.0, origin, [origin], 0.0, 0.0, 1.0, 1.0, [])
        heap    = [initial]
        visited: dict[str, float] = {}   # node → best neg_score seen

        while heap:
            neg_score, node, path, km, hrs, min_saf, prod_rel, edges = heapq.heappop(heap)

            if node in visited and visited[node] <= neg_score:
                continue
            visited[node] = neg_score

            if node == destination:
                norm_time = min(hrs / _MAX_HOURS, 1.0)
                composite  = (
                    ROUTE_W_SAFETY      * min_saf +
                    ROUTE_W_RELIABILITY * prod_rel -
                    ROUTE_W_TIME        * norm_time
                )
                return {
                    "path":             path,
                    "total_km":         round(km, 1),
                    "est_hours":        round(hrs, 2),
                    "composite_score":  round(composite, 4),
                    "min_safety":       round(min_saf, 4),
                    "prod_reliability": round(prod_rel, 4),
                    "edges":            edges,
                }

            for edge in self.edges.get(node, []):
                nxt   = edge["to"]
                new_km   = km  + edge["distance_km"]
                new_hrs  = hrs + edge["est_hours"]
                new_saf  = min(min_saf, edge["safety"])
                new_rel  = prod_rel * edge["reliability"]

                norm_time  = min(new_hrs / _MAX_HOURS, 1.0)
                new_score  = (
                    ROUTE_W_SAFETY      * new_saf +
                    ROUTE_W_RELIABILITY * new_rel -
                    ROUTE_W_TIME        * norm_time
                )
                neg_new  = -new_score

                if nxt not in visited or visited[nxt] > neg_new:
                    heapq.heappush(heap, (
                        neg_new, nxt, path + [nxt], new_km, new_hrs,
                        new_saf, new_rel, edges + [edge],
                    ))

        return None   # no path found

    # ── Utilities ────────────────────────────────────────────────────────────

    def node_label(self, node_id: str) -> str:
        n = self.nodes.get(node_id, {})
        return f"{n.get('name', node_id)} ({n.get('country', '?')})"

    def nearest_node(self, lat: float, lon: float) -> Optional[str]:
        """Return the ID of the node closest to (lat, lon)."""
        best_id, best_d = None, float("inf")
        for nid, n in self.nodes.items():
            d = _haversine_km(lat, lon, n["lat"], n["lon"])
            if d < best_d:
                best_d, best_id = d, nid
        return best_id
