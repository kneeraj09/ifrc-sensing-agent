from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid


class Location(BaseModel):
    name: str
    admin1: Optional[str] = None
    admin2: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class Signal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str           # bbc | gdelt | reliefweb | acled | whatsapp | email | sitrep
    source_id: str
    timestamp: str
    location: Optional[Location] = None
    commodity: Optional[str] = None   # food | water | shelter | medical | nfis | logistics | none
    signal_type: str           # demand | capacity | access | risk | conflict | infrastructure
    quantity: Optional[float] = None
    unit: Optional[str] = None
    urgency: str = "unknown"   # immediate | 24h | 72h | low | unknown
    confidence: float = 0.5
    raw_text: str
    url: Optional[str] = None
    extractor_model: str = ""


class BeliefState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    location: str
    country: Optional[str] = None
    commodity: str
    time_window: str = "next_72h"
    demand_p10: Optional[float] = None
    demand_p50: Optional[float] = None
    demand_p90: Optional[float] = None
    risk_level: str = "unknown"        # low | medium | high | critical
    supporting_signal_ids: list[str] = Field(default_factory=list)
    last_updated: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    human_override: Optional[dict] = None
    alert: Optional[str] = None
