import math
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from models import BeliefState
from config import SOURCE_WEIGHTS, SIGNAL_HALFLIFE_HOURS


def _belief_id(location: str, commodity: str) -> str:
    return hashlib.sha256(f"{location}|{commodity}".encode()).hexdigest()[:24]

# Maps urgency text to an ordinal risk level
_URGENCY_TO_RISK = {
    "immediate": "critical",
    "24h":       "high",
    "72h":       "medium",
    "low":       "low",
    "unknown":   "unknown",
}

_RISK_ORDINAL = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}
_ORDINAL_RISK = {v: k for k, v in _RISK_ORDINAL.items()}


def compute_belief_states(signals: list[dict]) -> list[BeliefState]:
    """Aggregate DB signal rows into belief states grouped by (location, commodity)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for s in signals:
        # Group by country when available — keeps dashboard at country level
        loc = s.get("country") or s.get("location_name") or "unknown"
        commodity = s.get("commodity") or "general"
        groups[(loc, commodity)].append(s)

    belief_states = []
    for (location, commodity), group in groups.items():
        demand_signals = [s for s in group if s["signal_type"] == "demand"]
        risk_signals   = [s for s in group if s["signal_type"] in ("risk", "conflict", "access")]

        risk_level = _aggregate_risk(risk_signals + demand_signals)
        alert = _build_alert(location, commodity, risk_level, group)

        # Collect sub-locations for context
        sub_locations = sorted({s.get("location_name") for s in group if s.get("location_name") and s.get("location_name") != location})

        bs = BeliefState(
            id=_belief_id(location, commodity),
            location=location,
            country=location,
            commodity=commodity,
            time_window="next_72h",
            risk_level=risk_level,
            supporting_signal_ids=[s["id"] for s in group],
            alert=alert,
            last_updated=datetime.utcnow().isoformat(),
        )

        if demand_signals:
            score = _weighted_score(demand_signals)
            # Express as a rough demand index (p10/p50/p90) rather than false precision
            bs.demand_p50 = round(score, 3)
            bs.demand_p10 = round(score * 0.6, 3)
            bs.demand_p90 = round(score * 1.6, 3)

        belief_states.append(bs)

    return belief_states


def _recency_weight(timestamp_str: str) -> float:
    """Exponential decay: weight = 0.5 at SIGNAL_HALFLIFE_HOURS, ~0 at 3× halflife."""
    try:
        ts = datetime.fromisoformat(timestamp_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        return 0.1
    age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    return math.exp(-0.693 * age_hours / SIGNAL_HALFLIFE_HOURS)


def _weighted_score(signals: list[dict]) -> float:
    """Weighted average of confidence, scaled by source veracity × recency."""
    weighted_conf = 0.0
    total_weight = 0.0
    for s in signals:
        source_w  = SOURCE_WEIGHTS.get(s.get("source_type", ""), 0.5)
        recency_w = _recency_weight(s.get("timestamp", ""))
        w = source_w * recency_w
        weighted_conf += w * s.get("confidence", 0.5)
        total_weight  += w
    return weighted_conf / total_weight if total_weight > 0 else 0.0


def _aggregate_risk(signals: list[dict]) -> str:
    """Return the highest risk level observed across a set of signals."""
    best = 0
    for s in signals:
        urgency = s.get("urgency", "unknown")
        level = _RISK_ORDINAL.get(_URGENCY_TO_RISK.get(urgency, "unknown"), 0)
        best = max(best, level)
    return _ORDINAL_RISK.get(best, "unknown")


def _build_alert(location: str, commodity: str, risk_level: str, signals: list[dict]) -> str | None:
    if risk_level not in ("critical", "high"):
        return None
    sources = sorted({s.get("source_type", "unknown") for s in signals})
    return (
        f"{risk_level.upper()} — {commodity} concern in {location}. "
        f"{len(signals)} signal(s) from: {', '.join(sources)}."
    )
