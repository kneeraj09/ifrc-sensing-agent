"""Equity and efficiency metrics for allocation scenario comparison."""


def gini_coefficient(values: list[float]) -> float:
    """Gini coefficient of coverage ratios. 0 = perfect equity, 1 = total inequality."""
    n = len(values)
    if n == 0 or sum(values) == 0:
        return 0.0
    s = sorted(values)
    total = sum(s)
    cumsum = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(s))
    return cumsum / (n * total)


def compute_metrics(results: list[dict]) -> dict:
    if not results:
        return {"equity_score": 0, "avg_coverage_pct": 0,
                "locations_at_risk": 0, "total_allocated": 0}
    coverages = [r["coverage_ratio"] for r in results]
    return {
        "equity_score":      round((1 - gini_coefficient(coverages)) * 100, 1),
        "avg_coverage_pct":  round(sum(coverages) / len(coverages) * 100, 1),
        "locations_at_risk": sum(1 for r in results if r["at_risk"]),
        "total_allocated":   round(sum(r["allocated"] for r in results), 2),
    }


def scenario_summary(all_results: dict[str, list[dict]]) -> dict[str, dict]:
    return {name: compute_metrics(results) for name, results in all_results.items()}
