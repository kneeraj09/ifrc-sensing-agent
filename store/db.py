import sqlite3
import json
from datetime import datetime
from models import Signal, BeliefState, LogisticsRequest, DemandCluster, ConsolidationProposal
from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS whatsapp_inbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_number TEXT,
    body        TEXT,
    media_urls  TEXT,
    received_at TEXT,
    processed   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS signals (
    id              TEXT PRIMARY KEY,
    source_type     TEXT,
    source_id       TEXT,
    timestamp       TEXT,
    location_name   TEXT,
    country         TEXT,
    admin1          TEXT,
    lat             REAL,
    lon             REAL,
    commodity       TEXT,
    signal_type     TEXT,
    quantity        REAL,
    unit            TEXT,
    urgency         TEXT,
    confidence      REAL,
    raw_text        TEXT,
    url             TEXT,
    extractor_model TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS logistics_requests (
    id                TEXT PRIMARY KEY,
    source            TEXT,
    source_message_id TEXT,
    requesting_org    TEXT,
    origin            TEXT,
    destination       TEXT,
    commodity         TEXT,
    quantity          REAL,
    unit              TEXT,
    deadline          TEXT,
    urgency           TEXT,
    notes             TEXT,
    status            TEXT DEFAULT 'pending',
    confidence        REAL,
    raw_text          TEXT,
    created_at        TEXT
);

CREATE TABLE IF NOT EXISTS demand_clusters (
    id                  TEXT PRIMARY KEY,
    request_ids         TEXT,
    corridor            TEXT,
    commodity           TEXT,
    time_window         TEXT,
    total_quantity      REAL,
    unit                TEXT,
    compatibility_notes TEXT,
    status              TEXT DEFAULT 'proposed',
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS consolidation_proposals (
    id                TEXT PRIMARY KEY,
    cluster_id        TEXT,
    proposal_text     TEXT,
    rationale         TEXT,
    estimated_saving  TEXT,
    suggested_timing  TEXT,
    suggested_actions TEXT,
    coordinator_notes TEXT,
    status            TEXT DEFAULT 'pending',
    created_at        TEXT,
    reviewed_at       TEXT
);

CREATE TABLE IF NOT EXISTS demand_processed_sources (
    source_type  TEXT,
    source_id    TEXT,
    processed_at TEXT,
    PRIMARY KEY (source_type, source_id)
);

CREATE TABLE IF NOT EXISTS belief_states (
    id                    TEXT PRIMARY KEY,
    location              TEXT,
    country               TEXT,
    commodity             TEXT,
    time_window           TEXT,
    demand_p10            REAL,
    demand_p50            REAL,
    demand_p90            REAL,
    risk_level            TEXT,
    supporting_signal_ids TEXT,   -- JSON array
    alert                 TEXT,
    human_override        TEXT,   -- JSON object
    last_updated          TEXT
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def upsert_signal(signal: Signal):
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO signals VALUES (
                :id, :source_type, :source_id, :timestamp,
                :location_name, :country, :admin1, :lat, :lon,
                :commodity, :signal_type, :quantity, :unit,
                :urgency, :confidence, :raw_text, :url, :extractor_model, :created_at
            )
            """,
            {
                "id":              signal.id,
                "source_type":     signal.source_type,
                "source_id":       signal.source_id,
                "timestamp":       signal.timestamp,
                "location_name":   signal.location.name if signal.location else "",
                "country":         signal.location.country if signal.location else None,
                "admin1":          signal.location.admin1 if signal.location else None,
                "lat":             signal.location.lat if signal.location else None,
                "lon":             signal.location.lon if signal.location else None,
                "commodity":       signal.commodity,
                "signal_type":     signal.signal_type,
                "quantity":        signal.quantity,
                "unit":            signal.unit,
                "urgency":         signal.urgency,
                "confidence":      signal.confidence,
                "raw_text":        signal.raw_text,
                "url":             signal.url,
                "extractor_model": signal.extractor_model,
                "created_at":      datetime.utcnow().isoformat(),
            },
        )


def get_recent_signals(hours: int = 72) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE datetime(timestamp) >= datetime('now', ?)
            ORDER BY timestamp DESC
            """,
            (f"-{hours} hours",),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_belief_state(bs: BeliefState):
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO belief_states VALUES (
                :id, :location, :country, :commodity, :time_window,
                :demand_p10, :demand_p50, :demand_p90, :risk_level,
                :supporting_signal_ids, :alert, :human_override, :last_updated
            )
            """,
            {
                "id":                    bs.id,
                "location":              bs.location,
                "country":               bs.country,
                "commodity":             bs.commodity,
                "time_window":           bs.time_window,
                "demand_p10":            bs.demand_p10,
                "demand_p50":            bs.demand_p50,
                "demand_p90":            bs.demand_p90,
                "risk_level":            bs.risk_level,
                "supporting_signal_ids": json.dumps(bs.supporting_signal_ids),
                "alert":                 bs.alert,
                "human_override":        json.dumps(bs.human_override) if bs.human_override else None,
                "last_updated":          bs.last_updated,
            },
        )


def source_already_processed(source_type: str, source_id: str) -> bool:
    with _conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE source_type=? AND source_id=?",
            (source_type, source_id),
        ).fetchone()[0]
    return count > 0


def clear_belief_states():
    with _conn() as conn:
        conn.execute("DELETE FROM belief_states")


def store_whatsapp_message(from_number: str, body: str, media_urls: list):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO whatsapp_inbox (from_number, body, media_urls, received_at) VALUES (?, ?, ?, ?)",
            (from_number, body, json.dumps(media_urls), datetime.utcnow().isoformat()),
        )


def get_pending_whatsapp_messages(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM whatsapp_inbox WHERE processed = 0 ORDER BY received_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_whatsapp_processed(ids: list[int]):
    with _conn() as conn:
        conn.executemany(
            "UPDATE whatsapp_inbox SET processed = 1 WHERE id = ?",
            [(i,) for i in ids],
        )


def upsert_logistics_request(req: LogisticsRequest):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO logistics_requests VALUES
               (:id,:source,:source_message_id,:requesting_org,:origin,:destination,
                :commodity,:quantity,:unit,:deadline,:urgency,:notes,:status,
                :confidence,:raw_text,:created_at)""",
            {
                "id": req.id, "source": req.source,
                "source_message_id": req.source_message_id,
                "requesting_org": req.requesting_org,
                "origin": req.origin, "destination": req.destination,
                "commodity": req.commodity, "quantity": req.quantity,
                "unit": req.unit, "deadline": req.deadline,
                "urgency": req.urgency, "notes": req.notes,
                "status": req.status, "confidence": req.confidence,
                "raw_text": req.raw_text, "created_at": req.created_at,
            },
        )


def get_all_requests() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM logistics_requests ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_requests() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM logistics_requests WHERE status='pending' ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_request_status(request_id: str, status: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE logistics_requests SET status=? WHERE id=?", (status, request_id)
        )


def upsert_demand_cluster(cluster: DemandCluster):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO demand_clusters VALUES
               (:id,:request_ids,:corridor,:commodity,:time_window,
                :total_quantity,:unit,:compatibility_notes,:status,:created_at)""",
            {
                "id": cluster.id,
                "request_ids": json.dumps(cluster.request_ids),
                "corridor": cluster.corridor, "commodity": cluster.commodity,
                "time_window": cluster.time_window,
                "total_quantity": cluster.total_quantity, "unit": cluster.unit,
                "compatibility_notes": cluster.compatibility_notes,
                "status": cluster.status, "created_at": cluster.created_at,
            },
        )


def get_all_clusters() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM demand_clusters ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["request_ids"] = json.loads(d["request_ids"] or "[]")
        result.append(d)
    return result


def clear_demand_clusters():
    with _conn() as conn:
        conn.execute("DELETE FROM demand_clusters")
        conn.execute("DELETE FROM consolidation_proposals WHERE status='pending'")


def upsert_proposal(proposal: ConsolidationProposal):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO consolidation_proposals VALUES
               (:id,:cluster_id,:proposal_text,:rationale,:estimated_saving,
                :suggested_timing,:suggested_actions,:coordinator_notes,
                :status,:created_at,:reviewed_at)""",
            {
                "id": proposal.id, "cluster_id": proposal.cluster_id,
                "proposal_text": proposal.proposal_text,
                "rationale": proposal.rationale,
                "estimated_saving": proposal.estimated_saving,
                "suggested_timing": proposal.suggested_timing,
                "suggested_actions": json.dumps(proposal.suggested_actions),
                "coordinator_notes": proposal.coordinator_notes,
                "status": proposal.status, "created_at": proposal.created_at,
                "reviewed_at": proposal.reviewed_at,
            },
        )


def get_all_proposals() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM consolidation_proposals ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["suggested_actions"] = json.loads(d["suggested_actions"] or "[]")
        result.append(d)
    return result


def update_proposal_status(proposal_id: str, status: str, notes: str = ""):
    with _conn() as conn:
        conn.execute(
            """UPDATE consolidation_proposals
               SET status=?, coordinator_notes=?, reviewed_at=?
               WHERE id=?""",
            (status, notes, datetime.utcnow().isoformat(), proposal_id),
        )


def demand_source_already_processed(source_type: str, source_id: str) -> bool:
    with _conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM demand_processed_sources WHERE source_type=? AND source_id=?",
            (source_type, source_id),
        ).fetchone()[0]
    return count > 0


def mark_demand_source_processed(source_type: str, source_id: str):
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO demand_processed_sources VALUES (?,?,?)",
            (source_type, source_id, datetime.utcnow().isoformat()),
        )


def get_unprocessed_demand_messages() -> list[dict]:
    """Return distinct email/WhatsApp messages not yet checked for logistics requests."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT s.source_type, s.source_id, s.raw_text, s.timestamp
               FROM signals s
               WHERE s.source_type IN ('email','whatsapp')
               AND NOT EXISTS (
                   SELECT 1 FROM demand_processed_sources d
                   WHERE d.source_type=s.source_type AND d.source_id=s.source_id
               )
               ORDER BY s.timestamp DESC""",
        ).fetchall()
    return [dict(r) for r in rows]


def get_belief_states() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM belief_states ORDER BY last_updated DESC"
        ).fetchall()
    return [dict(r) for r in rows]
