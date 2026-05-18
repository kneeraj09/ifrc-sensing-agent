"""Generate a plain-language ethical decision brief via Claude."""
import json
import anthropic
from config import ANTHROPIC_API_KEY, EXTRACTION_MODEL
from allocation.newsvendor import SCENARIOS

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_decision_brief(
    scenario_name: str,
    allocations: list[dict],
    metrics: dict,
    available_stock: float,
    unit: str,
    commodity: str,
    coordinator_overrides: dict | None = None,
) -> str:
    sc = SCENARIOS.get(scenario_name, {})
    alloc_lines = []
    for r in sorted(allocations, key=lambda x: -x["allocated"]):
        override = (coordinator_overrides or {}).get(r["location"])
        qty = override if override is not None else r["allocated"]
        flag = " [COORDINATOR OVERRIDE]" if override is not None else ""
        alloc_lines.append(
            f"  {r['location']} ({r['risk_level']}): {qty} {unit} "
            f"— {r['coverage_pct']}% of estimated need, "
            f"{r['shortfall_prob']*100:.0f}% shortfall probability{flag}"
        )

    prompt = f"""You are drafting an allocation decision brief for a humanitarian logistics coordinator.

ALLOCATION SCENARIO: {sc.get('label', scenario_name)}
Ethical stance: {sc.get('description', '')}
Critical ratio: {sc.get('critical_ratio', 0.85)} (higher = more conservative, fewer shortfalls)

COMMODITY: {commodity}
TOTAL AVAILABLE: {available_stock} {unit}
TOTAL ALLOCATED: {metrics.get('total_allocated', 0)} {unit}

ALLOCATIONS:
{chr(10).join(alloc_lines)}

METRICS:
- Equity score: {metrics.get('equity_score', 0)}/100 (higher = more equal coverage)
- Average coverage: {metrics.get('avg_coverage_pct', 0)}%
- Locations at risk (<80% coverage): {metrics.get('locations_at_risk', 0)}

Write a decision brief in 3 short paragraphs:
1. SITUATION: What is being allocated, to whom, and under what scenario
2. ETHICAL RATIONALE: What tradeoffs this scenario makes explicit — who benefits most, who is most at risk of shortfall, and why this allocation reflects (or deviates from) the impartiality principle
3. RESIDUAL RISK: What could go wrong, what assumptions are being made, and what the coordinator should monitor

Be direct. Flag any locations where the shortfall probability exceeds 30%. Note any coordinator overrides and their implications.
End with one sentence the coordinator can use to justify this decision to stakeholders."""

    try:
        response = _client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"[Brief generation failed: {e}]"
