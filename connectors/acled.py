import requests
from datetime import datetime, timedelta
from config import ACLED_EMAIL, ACLED_PASSWORD

_AUTH_URL = "https://acleddata.com/oauth/token"
_DATA_URL = "https://acleddata.com/api/acled/read"

_FIELDS = (
    "event_id_cnty|event_date|event_type|sub_event_type"
    "|country|admin1|admin2|location|latitude|longitude|notes|fatalities"
)

# In-memory token cache — avoids re-authenticating on every call within a session
_token_cache: dict = {"access_token": None, "expires_at": datetime.min}


def _get_access_token() -> str | None:
    """Obtain a Bearer token via ACLED OAuth2 (email + password)."""
    if not ACLED_EMAIL or not ACLED_PASSWORD:
        print("[acled] ACLED_EMAIL / ACLED_PASSWORD not set — skipping.")
        return None

    # Return cached token if still valid (with 60s buffer)
    if _token_cache["access_token"] and datetime.utcnow() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    try:
        resp = requests.post(
            _AUTH_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "username":   ACLED_EMAIL,
                "password":   ACLED_PASSWORD,
                "grant_type": "password",
                "client_id":  "acled",
                "scope":      "authenticated",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _token_cache["access_token"] = data["access_token"]
        # access_token is valid 24h; cache for 23h to be safe
        _token_cache["expires_at"] = datetime.utcnow() + timedelta(hours=23)
        return _token_cache["access_token"]
    except Exception as e:
        print(f"[acled] Auth error: {e}")
        return None


def fetch_events(days_back: int = 7, limit: int = 50) -> list[dict]:
    """Fetch recent conflict/security events from ACLED.

    Free access for humanitarian orgs — register at https://acleddata.com/register/
    """
    token = _get_access_token()
    if not token:
        return []

    end_date   = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params = {
        "event_date":       f"{start_date}|{end_date}",
        "event_date_where": "BETWEEN",
        "limit":            limit,
        "fields":           _FIELDS,
    }
    try:
        resp = requests.get(
            _DATA_URL,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        events = []
        for ev in data.get("data", []):
            events.append({
                "source_type": "acled",
                "source_id":   ev.get("event_id_cnty", ""),
                "url":         None,
                "timestamp":   ev.get("event_date", datetime.utcnow().strftime("%Y-%m-%d")),
                "raw_text": (
                    f"{ev.get('event_type', '')} ({ev.get('sub_event_type', '')}) "
                    f"in {ev.get('location', '')}, {ev.get('admin1', '')}, {ev.get('country', '')}. "
                    f"Fatalities: {ev.get('fatalities', 0)}. {ev.get('notes', '')}"
                ),
                "location_hint": {
                    "name":    ev.get("location", ""),
                    "admin1":  ev.get("admin1", ""),
                    "country": ev.get("country", ""),
                    "lat":     ev.get("latitude"),
                    "lon":     ev.get("longitude"),
                },
            })
        return events
    except Exception as e:
        print(f"[acled] Data fetch error: {e}")
        return []
