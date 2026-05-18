import hashlib
import anthropic
from models import LogisticsRequest
from config import ANTHROPIC_API_KEY, EXTRACTION_MODEL

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_TOOL = {
    "name": "extract_logistics_requests",
    "description": (
        "Extract structured logistics requests from humanitarian field communications. "
        "A logistics request is an explicit ask to move goods from one place to another. "
        "Return an empty array if the message is a situation report, news article, or "
        "general update with no logistics request."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requesting_org": {"type": "string", "description": "Organisation making the request"},
                        "origin":         {"type": "string", "description": "Pick-up location"},
                        "destination":    {"type": "string", "description": "Delivery location"},
                        "commodity":      {"type": "string", "description": "food | water | medical | shelter | nfis | logistics | other"},
                        "quantity":       {"type": "number"},
                        "unit":           {"type": "string", "description": "MT, pallets, boxes, litres, etc."},
                        "deadline":       {"type": "string", "description": "ISO date or relative timeframe"},
                        "urgency":        {"type": "string", "enum": ["immediate", "24h", "72h", "low", "unknown"]},
                        "notes":          {"type": "string", "description": "Constraints, special requirements, contact info"},
                        "confidence":     {"type": "number", "description": "0.0–1.0 confidence this is a logistics request"},
                    },
                    "required": ["origin", "destination", "commodity", "urgency", "confidence"],
                },
            }
        },
        "required": ["requests"],
    },
}


def _request_id(source_type: str, source_id: str, destination: str, commodity: str) -> str:
    key = f"{source_type}|{source_id}|{destination}|{commodity}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def extract_requests(message: dict) -> list[LogisticsRequest]:
    """Extract logistics requests from a single message dict (source_type, source_id, raw_text)."""
    raw_text = (message.get("raw_text") or "").strip()
    if not raw_text:
        return []

    try:
        response = _client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=1000,
            system=(
                "You extract logistics coordination requests from humanitarian field communications. "
                "Focus on inter-agency requests: who needs what moved from where to where by when. "
                "Be conservative — only extract explicit logistics requests, not general mentions of need."
            ),
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "extract_logistics_requests"},
            messages=[{"role": "user", "content": raw_text[:3000]}],
        )
    except Exception as e:
        print(f"  [demand-extract] API error: {e}")
        raise  # let caller decide whether to mark processed

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        return []

    results = []
    src_type = message.get("source_type", "")
    src_id   = message.get("source_id", "")

    for r in tool_use.input.get("requests", []):
        if r.get("confidence", 0) < 0.5:
            continue
        req = LogisticsRequest(
            id=_request_id(src_type, src_id, r.get("destination", ""), r.get("commodity", "")),
            source=src_type or "unknown",
            source_message_id=src_id or None,
            requesting_org=r.get("requesting_org"),
            origin=r.get("origin", "unknown"),
            destination=r.get("destination", "unknown"),
            commodity=r.get("commodity", "general"),
            quantity=r.get("quantity"),
            unit=r.get("unit"),
            deadline=r.get("deadline"),
            urgency=r.get("urgency", "unknown"),
            notes=r.get("notes"),
            confidence=r.get("confidence", 0.5),
            raw_text=raw_text[:500],
        )
        results.append(req)

    return results
