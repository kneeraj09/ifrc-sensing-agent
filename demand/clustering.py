import json
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
import anthropic
from models import DemandCluster, ConsolidationProposal
from config import ANTHROPIC_API_KEY, EXTRACTION_MODEL

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_COMMODITY_MAP = {
    ("food", "nutrition", "ration", "grain", "cereal", "meal", "rice", "flour"): "food",
    ("water", "wash", "sanitation", "hygiene"):                                   "water",
    ("medical", "medicine", "health", "drug", "pharmaceutical"):                  "medical",
    ("shelter", "nfi", "non-food", "blanket", "tarp", "kit"):                    "shelter",
    ("logistics", "transport", "vehicle", "fuel"):                                "logistics",
}


def _commodity_class(commodity: str) -> str:
    c = commodity.lower()
    for keywords, cls in _COMMODITY_MAP.items():
        if any(k in c for k in keywords):
            return cls
    return c.strip()


def _cluster_id(corridor: str, commodity: str) -> str:
    key = f"{corridor}|{commodity}|{datetime.now(timezone.utc).date()}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _proposal_id(cluster_id: str) -> str:
    return hashlib.sha256(f"prop|{cluster_id}".encode()).hexdigest()[:24]


def _generate_proposal(cluster: DemandCluster, requests: list[dict]) -> ConsolidationProposal:
    """Call Claude to generate a plain-language consolidation proposal for a cluster."""
    req_lines = []
    for r in requests:
        qty = f"{r['quantity']} {r['unit']}" if r.get("quantity") else "quantity TBC"
        org = r.get("requesting_org") or "unknown org"
        deadline = r.get("deadline") or "no fixed deadline"
        req_lines.append(f"- {org}: {r['commodity']} from {r['origin']} to {r['destination']}, {qty}, by {deadline} ({r['urgency']})")

    prompt = f"""You are a humanitarian logistics coordinator reviewing consolidation opportunities.

These requests could potentially be consolidated:
{chr(10).join(req_lines)}

Write a consolidation proposal for a field coordinator. Return JSON with:
- proposal_text: 2-3 sentences describing what to consolidate and how (plain language, actionable)
- rationale: 1 sentence explaining why this makes sense (shared corridor, timing, etc.)
- estimated_saving: brief string like "saves ~1 truck trip" or "reduces 2-day overlap"
- suggested_timing: when to coordinate (e.g. "align pickups for Wednesday")
- suggested_actions: array of 2-4 short imperative action strings for the coordinator

Be direct and practical. Flag any risks or constraints that need checking."""

    try:
        response = _client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        start, end = text.find("{"), text.rfind("}") + 1
        data = json.loads(text[start:end]) if start != -1 else {}
    except Exception as e:
        print(f"  [demand-cluster] Proposal generation error: {e}")
        data = {}

    return ConsolidationProposal(
        id=_proposal_id(cluster.id),
        cluster_id=cluster.id,
        proposal_text=data.get("proposal_text", f"Consolidate {len(requests)} requests on {cluster.corridor} corridor."),
        rationale=data.get("rationale", "Shared destination and compatible commodities."),
        estimated_saving=data.get("estimated_saving"),
        suggested_timing=data.get("suggested_timing"),
        suggested_actions=data.get("suggested_actions", []),
    )


def cluster_and_propose(requests: list[dict]) -> tuple[list[DemandCluster], list[ConsolidationProposal]]:
    """Group compatible requests into clusters and generate consolidation proposals."""
    if not requests:
        return [], []

    # Group by (commodity_class, destination)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in requests:
        key = (_commodity_class(r["commodity"]), r["destination"].strip().lower())
        groups[key].append(r)

    clusters, proposals = [], []

    for (commodity_cls, destination), group in groups.items():
        if len(group) < 2:
            continue  # No consolidation opportunity for singletons

        corridor_origins = sorted({r["origin"] for r in group})
        corridor = f"{' / '.join(corridor_origins[:3])} → {group[0]['destination']}"

        # Sum quantities where unit is consistent
        units = {r.get("unit") for r in group if r.get("unit")}
        total_qty = None
        common_unit = None
        if len(units) == 1:
            common_unit = list(units)[0]
            qtys = [r["quantity"] for r in group if r.get("quantity")]
            total_qty = sum(qtys) if qtys else None

        cluster = DemandCluster(
            id=_cluster_id(corridor, commodity_cls),
            request_ids=[r["id"] for r in group],
            corridor=corridor,
            commodity=commodity_cls,
            total_quantity=total_qty,
            unit=common_unit,
            time_window=f"{len(group)} requests",
        )
        clusters.append(cluster)

        proposal = _generate_proposal(cluster, group)
        proposals.append(proposal)
        print(f"  [demand-cluster] {corridor} — {commodity_cls} ({len(group)} requests)")

    return clusters, proposals
