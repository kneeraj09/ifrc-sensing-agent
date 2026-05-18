"""
Multi-location newsvendor allocation engine.

For each location the optimal allocation is:
    Q* = μ + σ · Φ⁻¹(critical_ratio)

where μ and σ are estimated from the P10/P50/P90 belief state demand indices
scaled by a reference quantity (either from a logistics request or coordinator input),
and Φ⁻¹ is the inverse normal CDF.

The critical_ratio encodes the ethical stance: high ratio = avoid shortfalls (humanitarian
priority); low ratio = lean allocation (efficiency priority).
"""
from scipy.stats import norm

SCENARIOS: dict[str, dict] = {
    "speed": {
        "label":          "Speed Priority",
        "description":    "Lean allocation — faster deployment, accepts more shortfall risk",
        "critical_ratio": 0.70,
        "risk_adjustment": False,
    },
    "balanced": {
        "label":          "Balanced",
        "description":    "Default IFRC approach — balances speed, equity, and coverage",
        "critical_ratio": 0.85,
        "risk_adjustment": False,
    },
    "equity": {
        "label":          "Equity Focus",
        "description":    "Prioritises equal coverage across all locations",
        "critical_ratio": 0.90,
        "risk_adjustment": False,
    },
    "critical_first": {
        "label":          "Critical Locations First",
        "description":    "Higher allocation to high-risk locations; lower to stable ones",
        "critical_ratio": 0.85,
        "risk_adjustment": True,
    },
    "conservative": {
        "label":          "Conservative",
        "description":    "Minimise shortfall probability everywhere",
        "critical_ratio": 0.95,
        "risk_adjustment": False,
    },
}

_RISK_CR_DELTA = {
    "critical": +0.08,
    "high":     +0.04,
    "medium":    0.00,
    "low":      -0.04,
    "unknown":  -0.02,
}


def _effective_cr(base: float, risk: str, apply: bool) -> float:
    delta = _RISK_CR_DELTA.get(risk, 0) if apply else 0
    return min(max(base + delta, 0.50), 0.9999)


def run_newsvendor(locations: list[dict], available_stock: float, scenario_name: str) -> list[dict]:
    """
    Allocate available_stock across locations under a named scenario.

    Each location dict must contain:
        location, commodity, risk_level,
        demand_p10, demand_p50, demand_p90  (0-1 indices from belief state)
        reference_qty   (actual units — MT, pallets, etc. — for scaling)

    Returns list of result dicts sorted by coverage_ratio ascending.
    """
    sc = SCENARIOS[scenario_name]
    base_cr = sc["critical_ratio"]
    risk_adj = sc["risk_adjustment"]
    n = len(locations)
    if n == 0 or available_stock <= 0:
        return []

    prepped = []
    for loc in locations:
        ref = loc.get("reference_qty") or available_stock / n
        p50 = loc.get("demand_p50") or 0.5
        p10 = loc.get("demand_p10") or p50 * 0.6
        p90 = loc.get("demand_p90") or p50 * 1.6

        # Scale index → quantity
        mu    = p50 * ref
        sigma = max((p90 - p10) / 2.56 * ref, mu * 0.10)
        floor = max(p10 * ref, 0)

        cr = _effective_cr(base_cr, loc.get("risk_level", "unknown"), risk_adj)
        q_star = max(mu + sigma * norm.ppf(cr), floor)

        prepped.append({**loc, "mu": mu, "sigma": sigma, "floor": floor,
                        "cr": cr, "q_star": q_star})

    # Stock constraint: floors first, then residuals proportionally
    total_q   = sum(p["q_star"] for p in prepped)
    total_fl  = sum(p["floor"]  for p in prepped)
    results   = []

    for p in prepped:
        if total_q <= available_stock:
            allocated = p["q_star"]
        elif total_fl >= available_stock:
            allocated = p["floor"] * (available_stock / max(total_fl, 1e-9))
        else:
            residual_pool   = available_stock - total_fl
            total_residuals = sum(max(x["q_star"] - x["floor"], 0) for x in prepped)
            weight = max(p["q_star"] - p["floor"], 0) / max(total_residuals, 1e-9)
            allocated = p["floor"] + residual_pool * weight

        allocated = max(allocated, 0)
        cov = allocated / max(p["mu"], 1e-9)
        sf  = float(1 - norm.cdf(allocated, loc=p["mu"], scale=max(p["sigma"], 1e-9)))

        results.append({
            "location":       p["location"],
            "commodity":      p["commodity"],
            "risk_level":     p.get("risk_level", "unknown"),
            "reference_qty":  round(p.get("reference_qty", 0), 2),
            "mean_demand":    round(p["mu"], 2),
            "allocated":      round(allocated, 2),
            "coverage_ratio": round(min(cov, 2.0), 3),
            "coverage_pct":   round(min(cov * 100, 200), 1),
            "shortfall_prob": round(sf, 4),
            "critical_ratio": round(p["cr"], 4),
            "at_risk":        cov < 0.80,
        })

    return sorted(results, key=lambda x: x["coverage_ratio"])


def run_all_scenarios(locations: list[dict], available_stock: float) -> dict[str, list[dict]]:
    return {name: run_newsvendor(locations, available_stock, name) for name in SCENARIOS}
