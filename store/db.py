import sqlite3
import json
from datetime import datetime
from models import Signal, BeliefState
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


def get_belief_states() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM belief_states ORDER BY last_updated DESC"
        ).fetchall()
    return [dict(r) for r in rows]
