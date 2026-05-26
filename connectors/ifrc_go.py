"""
IFRC GO connector — fetches emergency events and field reports.

Public REST API: https://goadmin.ifrc.org/api/v2/
No credentials required for public read access.
Optional: set IFRC_GO_TOKEN in .env for authenticated access to richer data.
"""
import requests
from datetime import datetime, timezone, timedelta
from config import IFRC_GO_TOKEN

_API_BASE = "https://goadmin.ifrc.org/api/v2"
_TIMEOUT  = 30


def _headers() -> dict:
    if IFRC_GO_TOKEN:
        return {"Authorization": f"Token {IFRC_GO_TOKEN}"}
    return {}


def _parse_date(date_str: str | None) -> str:
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _primary_country(item: dict) -> str:
    """Extract the primary country name from an event or field-report item."""
    for key in ("countries_details", "countries"):
        countries = item.get(key) or []
        if countries and isinstance(countries, list):
            c = countries[0]
            if isinstance(c, dict):
                return c.get("name", "") or c.get("iso", "")
    return ""


def _primary_iso3(item: dict) -> str:
    """Extract the primary ISO3 country code from an event or field-report item."""
    for key in ("countries_details", "countries"):
        countries = item.get(key) or []
        if countries and isinstance(countries, list):
            c = countries[0]
            if isinstance(c, dict):
                return c.get("iso3", "") or c.get("iso", "")
    return ""


def _fetch(endpoint: str, params: dict) -> list[dict]:
    try:
        resp = requests.get(
            f"{_API_BASE}/{endpoint}/",
            params=params,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        print(f"[ifrc_go] Error fetching /{endpoint}: {e}")
        return []


# ── Emergency events ──────────────────────────────────────────────────────────

def _fetch_events(limit: int, days_back: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = _fetch("event", {
        "limit":                    limit,
        "ordering":                 "-disaster_start_date",
        "disaster_start_date__gte": since,
        "format":                   "json",
    })
    articles = []
    for item in items:
        name     = item.get("name", "")
        summary  = (item.get("summary") or "")[:1500]
        dtype    = item.get("dtype") or {}
        dtype_nm = dtype.get("name", "") if isinstance(dtype, dict) else ""
        country  = _primary_country(item)
        severity = item.get("ifrc_severity_level_display", "")

        nums = " ".join(filter(None, [
            f"Affected: {item['num_affected']}."  if item.get("num_affected") else "",
            f"Dead: {item['num_dead']}."           if item.get("num_dead")      else "",
            f"Displaced: {item['num_displaced']}." if item.get("num_displaced") else "",
        ]))

        raw = (
            f"IFRC GO Emergency: {name}. "
            f"Disaster type: {dtype_nm}. Country: {country}. "
            f"IFRC severity: {severity}. {nums} {summary}"
        ).strip()

        articles.append({
            "source_type":   "ifrc_go",
            "source_id":     f"event_{item['id']}",
            "url":           f"https://go.ifrc.org/emergencies/{item['id']}",
            "timestamp":     _parse_date(item.get("disaster_start_date") or item.get("created_at")),
            "raw_text":      raw,
            "location_hint": {"country": country},
        })
    print(f"[ifrc_go]  /event: {len(articles)} item(s)")
    return articles


# ── Field reports ─────────────────────────────────────────────────────────────

def _fetch_field_reports(limit: int, days_back: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = _fetch("field-report", {
        "limit":           limit,
        "ordering":        "-created_at",
        "created_at__gte": since,
        "format":          "json",
    })
    articles = []
    for item in items:
        title    = item.get("title", "")
        summary  = (item.get("summary") or "")
        desc     = (item.get("description") or "")
        dtype    = item.get("dtype_details") or {}
        dtype_nm = dtype.get("name", "") if isinstance(dtype, dict) else ""
        country  = _primary_country(item)

        nums = " ".join(filter(None, [
            f"Affected: {item['num_affected']}."   if item.get("num_affected")   else "",
            f"Displaced: {item['num_displaced']}." if item.get("num_displaced")  else "",
            f"Injured: {item['num_injured']}."     if item.get("num_injured")    else "",
            f"Dead: {item['num_dead']}."            if item.get("num_dead")       else "",
        ]))

        # Flatten actions taken
        action_names = []
        for block in (item.get("actions_taken") or []):
            if isinstance(block, dict):
                for ad in (block.get("actions_details") or []):
                    if isinstance(ad, dict) and ad.get("name"):
                        action_names.append(ad["name"])

        narrative = (desc or summary)[:1500]
        actions_str = f"Actions: {'; '.join(action_names[:6])}. " if action_names else ""

        raw = (
            f"IFRC GO Field Report: {title}. "
            f"Disaster type: {dtype_nm}. Country: {country}. "
            f"{nums} {actions_str}{narrative}"
        ).strip()

        articles.append({
            "source_type":   "ifrc_go",
            "source_id":     f"fr_{item['id']}",
            "url":           f"https://go.ifrc.org/reports/{item['id']}",
            "timestamp":     _parse_date(item.get("report_date") or item.get("created_at")),
            "raw_text":      raw,
            "location_hint": {"country": country},
        })
    print(f"[ifrc_go]  /field-report: {len(articles)} item(s)")
    return articles


# ── Baseline fetch (multi-year, for GLIDE linkage) ───────────────────────────

# IFRC GO appeal type codes
_APPEAL_TYPE = {1: "DREF", 2: "EA", 3: "EAP"}


def fetch_events_baseline(years_back: int = 2, page_size: int = 100) -> list[dict]:
    """Fetch IFRC GO emergency events for the baseline cross-reference.

    Fetches multiple pages going back ``years_back`` calendar years and extracts
    the GLIDE number, disaster type, country, and appeal type so records can be
    linked against GDACS historical events.

    Returns:
        List of dicts with keys: id, go_id, name, glide, disaster_type,
        iso3, country, start_date, num_affected, appeal_type, go_url.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=years_back * 365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_items: list[dict] = []
    offset = 0
    while True:
        items = _fetch("event", {
            "limit":                    page_size,
            "offset":                   offset,
            "ordering":                 "-disaster_start_date",
            "disaster_start_date__gte": since,
            "format":                   "json",
        })
        if not items:
            break
        all_items.extend(items)
        if len(items) < page_size:
            break
        offset += page_size
        if offset >= 2000:          # safety cap — ~20 pages
            break

    events = []
    for item in all_items:
        dtype    = item.get("dtype") or {}
        dtype_nm = dtype.get("name", "") if isinstance(dtype, dict) else ""
        country  = _primary_country(item)
        iso3     = _primary_iso3(item)
        glide    = (item.get("glide") or "").strip()

        # Pick the highest-priority appeal type (EA > EAP > DREF)
        appeal_type = ""
        for appeal in (item.get("appeals") or []):
            if isinstance(appeal, dict):
                code = _APPEAL_TYPE.get(appeal.get("atype"), "")
                if code == "EA":
                    appeal_type = "EA"
                    break
                if code in ("EAP", "DREF") and not appeal_type:
                    appeal_type = code

        events.append({
            "id":           f"event_{item['id']}",
            "go_id":        item.get("id"),
            "name":         (item.get("name") or "").strip(),
            "glide":        glide,
            "disaster_type": dtype_nm,
            "iso3":         iso3,
            "country":      country,
            "start_date":   (item.get("disaster_start_date") or "")[:10],
            "num_affected": item.get("num_affected"),
            "appeal_type":  appeal_type,
            "go_url":       f"https://go.ifrc.org/emergencies/{item['id']}",
        })

    print(f"[ifrc_go]  baseline: {len(events)} emergency event(s) ({years_back}yr lookback)")
    return events


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_reports(limit: int = 50, days_back: int = 7) -> list[dict]:
    """Fetch recent IFRC GO emergency events and field reports.

    Args:
        limit:     Max items per endpoint (default 50).
        days_back: How many days back to look (default 7 — GO updates less
                   frequently than news sources so a wider window is appropriate).
    """
    return _fetch_events(limit, days_back) + _fetch_field_reports(limit, days_back)
