import requests
from datetime import datetime

_API_BASE = "https://data.humdata.org/api/3/action"

# Search terms covering Flash Appeals and humanitarian situation reports
_SEARCH_TERMS = [
    "flash appeal",
    "humanitarian needs overview",
    "emergency response plan",
    "situation report",
]

_RESULTS_PER_TERM = 10


def fetch_datasets(limit: int = 40) -> list[dict]:
    """Fetch recent humanitarian datasets from HDX (OCHA Humanitarian Data Exchange).

    Uses the public CKAN API — no credentials required.
    Searches for Flash Appeals, HNOs, ERPs, and sitreps published recently.
    """
    articles = []
    per_term = max(1, limit // len(_SEARCH_TERMS))

    for term in _SEARCH_TERMS:
        try:
            resp = requests.get(
                f"{_API_BASE}/package_search",
                params={
                    "q":    term,
                    "sort": "metadata_modified desc",
                    "rows": per_term,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("result", {}).get("results", [])

            for pkg in results:
                countries = [g.get("display_name", "") for g in pkg.get("groups", [])]
                tags      = [t.get("display_name", "") for t in pkg.get("tags", [])]
                notes     = (pkg.get("notes") or "")[:600]

                raw = (
                    f"{pkg.get('title', '')}. "
                    f"Countries: {', '.join(countries)}. "
                    f"Tags: {', '.join(tags[:8])}. "
                    f"{notes}"
                )
                articles.append({
                    "source_type":   "hdx",
                    "source_id":     pkg.get("id", ""),
                    "url":           f"https://data.humdata.org/dataset/{pkg.get('name', '')}",
                    "timestamp":     pkg.get("metadata_modified", datetime.utcnow().isoformat()),
                    "raw_text":      raw,
                    "countries":     countries,
                    "location_hint": {"country": countries[0]} if countries else {},
                })
        except Exception as e:
            print(f"[hdx] Error for '{term}': {e}")

    return articles
