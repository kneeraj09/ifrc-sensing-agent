import anthropic
import hashlib
from datetime import datetime
from models import Signal, Location
from config import EXTRACTION_MODEL, ANTHROPIC_API_KEY


def _signal_id(source_type, source_id, location_name, commodity, signal_type):
    key = f"{source_type}|{source_id}|{location_name or ''}|{commodity or ''}|{signal_type}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_SYSTEM_PROMPT = """\
You are a humanitarian logistics intelligence analyst.
Extract signals from field messages and news articles that indicate:
  - Unmet needs in disaster-affected populations (demand signals)
  - Available relief capacity: vehicles, warehouses, staff, pre-positioned stock
  - Access constraints: road closures, checkpoints, security incidents, border delays
  - Risk events: conflict, extreme weather, displacement, infrastructure damage

Rules:
  - Extract only what is explicitly stated or strongly implied — do not hallibate.
  - If no relevant humanitarian signal is present, call record_signals with an empty array.
  - confidence = your certainty about the extraction (0.0–1.0), not the urgency of the situation.
  - urgency = how soon the need must be addressed based on the text.
  - One signal per distinct location/commodity/signal_type combination.\
"""

# Tool schema forces structured output rather than free-text JSON
_TOOLS = [
    {
        "name": "record_signals",
        "description": "Record all humanitarian logistics signals extracted from the source text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "signals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "location_name": {
                                "type": "string",
                                "description": "Most specific location mentioned (city, district, camp name).",
                            },
                            "country": {"type": "string"},
                            "admin1": {"type": "string", "description": "State, province, or region."},
                            "commodity": {
                                "type": "string",
                                "enum": ["food", "water", "shelter", "medical", "nfis", "logistics", "none"],
                            },
                            "signal_type": {
                                "type": "string",
                                "enum": ["demand", "capacity", "access", "risk", "conflict", "infrastructure"],
                            },
                            "quantity": {
                                "type": "number",
                                "description": "Numeric quantity if explicitly mentioned.",
                            },
                            "unit": {
                                "type": "string",
                                "description": "Unit of measurement (e.g. MT, households, trucks).",
                            },
                            "urgency": {
                                "type": "string",
                                "enum": ["immediate", "24h", "72h", "low", "unknown"],
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Extraction confidence 0.0–1.0.",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "summary": {
                                "type": "string",
                                "description": "One sentence describing this signal.",
                            },
                        },
                        "required": [
                            "location_name", "signal_type", "urgency", "confidence", "summary"
                        ],
                    },
                }
            },
            "required": ["signals"],
        },
    }
]


def extract_signals(article: dict) -> list[Signal]:
    """Extract structured humanitarian signals from a raw article or message."""
    raw_text = article.get("raw_text", "").strip()
    if not raw_text:
        return []

    try:
        response = _client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            tool_choice={"type": "any"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Source type: {article.get('source_type', 'unknown')}\n\n"
                        f"{raw_text}"
                    ),
                }
            ],
        )
    except Exception as e:
        print(f"[extraction] Claude API error: {e}")
        return []

    signals = []
    for block in response.content:
        if block.type != "tool_use" or block.name != "record_signals":
            continue
        location_hint = article.get("location_hint", {})
        for s in block.input.get("signals", []):
            location = Location(
                name=s.get("location_name") or location_hint.get("name", "unknown"),
                admin1=s.get("admin1") or location_hint.get("admin1"),
                country=s.get("country") or location_hint.get("country"),
                lat=location_hint.get("lat"),
                lon=location_hint.get("lon"),
            )
            src_type  = article.get("source_type", "unknown")
            src_id    = article.get("source_id", "")
            commodity = s.get("commodity")
            sig_type  = s["signal_type"]
            signals.append(
                Signal(
                    id=_signal_id(src_type, src_id, location.name, commodity, sig_type),
                    source_type=src_type,
                    source_id=src_id,
                    timestamp=article.get("timestamp", datetime.utcnow().isoformat()),
                    url=article.get("url"),
                    location=location,
                    commodity=commodity,
                    signal_type=sig_type,
                    quantity=s.get("quantity"),
                    unit=s.get("unit"),
                    urgency=s["urgency"],
                    confidence=s["confidence"],
                    raw_text=s.get("summary", ""),
                    extractor_model=EXTRACTION_MODEL,
                )
            )
    return signals
