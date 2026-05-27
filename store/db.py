import sqlite3
import json
from datetime import datetime
from models import Signal, BeliefState, LogisticsRequest, DemandCluster, ConsolidationProposal, StockPosition, AllocationRun
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

CREATE TABLE IF NOT EXISTS stock_positions (
    id             TEXT PRIMARY KEY,
    commodity      TEXT,
    depot_location TEXT,
    region         TEXT,
    quantity       REAL,
    unit           TEXT,
    as_of          TEXT,
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS allocation_runs (
    id                    TEXT PRIMARY KEY,
    commodity             TEXT,
    unit                  TEXT,
    available_stock       REAL,
    scenario_results      TEXT,
    scenario_metrics      TEXT,
    selected_scenario     TEXT,
    coordinator_overrides TEXT,
    decision_brief        TEXT,
    status                TEXT DEFAULT 'draft',
    created_at            TEXT,
    ratified_at           TEXT,
    rationale             TEXT
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

CREATE TABLE IF NOT EXISTS gdacs_events (
    id          TEXT PRIMARY KEY,
    event_type  TEXT,
    event_name  TEXT,
    country     TEXT,
    iso3        TEXT,
    region      TEXT,
    alert_level TEXT,
    alert_score REAL,
    from_date   TEXT,
    to_date     TEXT,
    lat         REAL,
    lon         REAL,
    glide       TEXT,
    event_url   TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS ifrc_go_events (
    id            TEXT PRIMARY KEY,   -- "event_{go_id}"
    go_id         INTEGER,
    name          TEXT,
    glide         TEXT,
    disaster_type TEXT,
    iso3          TEXT,
    country       TEXT,
    start_date    TEXT,
    num_affected  INTEGER,
    appeal_type   TEXT,               -- "DREF", "EA", "EAP", or ""
    go_url        TEXT,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS route_nodes (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    lat         REAL,
    lon         REAL,
    node_type   TEXT,    -- hub | port | forward | waypoint
    country     TEXT,
    iso3        TEXT,
    notes       TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS route_segments (
    id                TEXT PRIMARY KEY,
    from_node         TEXT,
    to_node           TEXT,
    distance_km       REAL,
    est_hours         REAL,
    reliability_score REAL,
    safety_score      REAL,
    road_quality      TEXT,
    last_assessed     TEXT,
    notes             TEXT,
    created_at        TEXT
);

CREATE TABLE IF NOT EXISTS routing_plans (
    id                TEXT PRIMARY KEY,
    allocation_run_id TEXT,
    origin_node       TEXT,
    destination_nodes TEXT,    -- JSON array
    commodity         TEXT,
    quantity          REAL,
    unit              TEXT,
    plan_status       TEXT DEFAULT 'proposed',
    route_json        TEXT,    -- JSON full route detail
    total_km          REAL,
    est_hours         REAL,
    composite_score   REAL,
    planner_notes     TEXT,
    created_at        TEXT,
    approved_at       TEXT,
    approved_by       TEXT
);

CREATE TABLE IF NOT EXISTS active_missions (
    id                TEXT PRIMARY KEY,
    routing_plan_id   TEXT,
    allocation_run_id TEXT,
    mission_status    TEXT DEFAULT 'preparing',
    driver_contact    TEXT,
    convoy_size       INTEGER,
    departure_time    TEXT,
    expected_arrival  TEXT,
    last_checkin_at   TEXT,
    last_position     TEXT,
    notes             TEXT,
    created_at        TEXT
);

CREATE TABLE IF NOT EXISTS mission_checkins (
    id            TEXT PRIMARY KEY,
    mission_id    TEXT,
    checkin_time  TEXT,
    position_name TEXT,
    lat           REAL,
    lon           REAL,
    status_note   TEXT,
    source        TEXT,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS route_disruptions (
    id              TEXT PRIMARY KEY,
    segment_id      TEXT,
    disruption_type TEXT,
    severity        TEXT,
    description     TEXT,
    reported_at     TEXT,
    expires_at      TEXT,
    source          TEXT,
    active          INTEGER DEFAULT 1,
    created_at      TEXT
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript(_SCHEMA)
        # stock_positions: add region column if missing
        sp_cols = {row[1] for row in conn.execute("PRAGMA table_info(stock_positions)")}
        if "region" not in sp_cols:
            conn.execute("ALTER TABLE stock_positions ADD COLUMN region TEXT")
        # gdacs_events: add glide + event_url columns if missing (added in v2)
        ge_cols = {row[1] for row in conn.execute("PRAGMA table_info(gdacs_events)")}
        if "glide" not in ge_cols:
            conn.execute("ALTER TABLE gdacs_events ADD COLUMN glide TEXT")
        if "event_url" not in ge_cols:
            conn.execute("ALTER TABLE gdacs_events ADD COLUMN event_url TEXT")
        # routing: create tables via schema (CREATE TABLE IF NOT EXISTS handles this)


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


def upsert_stock_position(pos: StockPosition):
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO stock_positions VALUES (:id,:commodity,:depot_location,:region,:quantity,:unit,:as_of,:created_at)",
            {"id": pos.id, "commodity": pos.commodity, "depot_location": pos.depot_location,
             "region": pos.region, "quantity": pos.quantity, "unit": pos.unit,
             "as_of": pos.as_of, "created_at": pos.created_at},
        )


def get_stock_positions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM stock_positions ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_stock_position(pos_id: str):
    with _conn() as conn:
        conn.execute("DELETE FROM stock_positions WHERE id=?", (pos_id,))


def upsert_allocation_run(run: AllocationRun):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO allocation_runs VALUES
               (:id,:commodity,:unit,:available_stock,:scenario_results,:scenario_metrics,
                :selected_scenario,:coordinator_overrides,:decision_brief,:status,:created_at,
                :ratified_at,:rationale)""",
            {"id": run.id, "commodity": run.commodity, "unit": run.unit,
             "available_stock": run.available_stock,
             "scenario_results": run.scenario_results,
             "scenario_metrics": run.scenario_metrics,
             "selected_scenario": run.selected_scenario,
             "coordinator_overrides": run.coordinator_overrides,
             "decision_brief": run.decision_brief,
             "status": run.status, "created_at": run.created_at,
             "ratified_at": run.ratified_at, "rationale": run.rationale},
        )


def get_allocation_runs() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM allocation_runs ORDER BY created_at DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["scenario_results"] = json.loads(d["scenario_results"] or "{}")
        d["scenario_metrics"] = json.loads(d["scenario_metrics"] or "{}")
        d["coordinator_overrides"] = json.loads(d["coordinator_overrides"] or "{}")
        result.append(d)
    return result


def get_latest_allocation_run() -> dict | None:
    runs = get_allocation_runs()
    return runs[0] if runs else None


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


def bulk_update_request_status(request_ids: list[str], status: str):
    if not request_ids:
        return
    with _conn() as conn:
        conn.executemany(
            "UPDATE logistics_requests SET status=? WHERE id=?",
            [(status, rid) for rid in request_ids],
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
    """Return messages not yet checked for logistics requests.

    Two sources are combined:
    1. WhatsApp inbox (processed=1 means sensing cycle has seen it) — uses original body.
       This catches logistics requests that produced no humanitarian signal.
    2. Email signals — uses signal raw_text (original email body is not separately stored).

    Results are de-duplicated by source_id so the same WhatsApp message is not
    returned twice even if it also produced a signal entry.
    """
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT 'whatsapp'                                       AS source_type,
                   'wa_' || w.id                                    AS source_id,
                   'WhatsApp from ' || w.from_number || ':' || char(10) || w.body
                                                                    AS raw_text,
                   w.received_at                                    AS timestamp
            FROM   whatsapp_inbox w
            WHERE  NOT EXISTS (
                       SELECT 1 FROM demand_processed_sources d
                       WHERE  d.source_type = 'whatsapp'
                       AND    d.source_id   = 'wa_' || w.id
                   )

            UNION

            SELECT DISTINCT s.source_type, s.source_id, s.raw_text, s.timestamp
            FROM   signals s
            WHERE  s.source_type = 'email'
            AND    NOT EXISTS (
                       SELECT 1 FROM demand_processed_sources d
                       WHERE  d.source_type = s.source_type
                       AND    d.source_id   = s.source_id
                   )

            ORDER BY timestamp DESC
            """,
        ).fetchall()
    return [dict(r) for r in rows]


def get_belief_states() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM belief_states ORDER BY last_updated DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── GDACS historical events ──────────────────────────────────────────────────

def upsert_gdacs_event(event: dict):
    """Insert or replace a GDACS historical event record."""
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO gdacs_events VALUES
               (:id,:event_type,:event_name,:country,:iso3,:region,
                :alert_level,:alert_score,:from_date,:to_date,:lat,:lon,
                :glide,:event_url,:created_at)""",
            {
                "id":          event.get("id", ""),
                "event_type":  event.get("event_type", ""),
                "event_name":  event.get("event_name", ""),
                "country":     event.get("country", ""),
                "iso3":        event.get("iso3", ""),
                "region":      event.get("region", ""),
                "alert_level": event.get("alert_level", ""),
                "alert_score": event.get("alert_score", 0.0),
                "from_date":   event.get("from_date", ""),
                "to_date":     event.get("to_date", ""),
                "lat":         event.get("lat"),
                "lon":         event.get("lon"),
                "glide":       event.get("glide", ""),
                "event_url":   event.get("event_url", ""),
                "created_at":  datetime.utcnow().isoformat(),
            },
        )


def get_gdacs_events(region: str = None) -> list[dict]:
    """Return all stored GDACS events, optionally filtered by region."""
    with _conn() as conn:
        if region:
            rows = conn.execute(
                "SELECT * FROM gdacs_events WHERE region=? ORDER BY from_date DESC",
                (region,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM gdacs_events ORDER BY from_date DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_gdacs_event_count() -> int:
    """Return the total number of stored GDACS events."""
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM gdacs_events").fetchone()[0]


# ── IFRC GO baseline events ──────────────────────────────────────────────────

def upsert_ifrc_go_event(event: dict):
    """Insert or replace an IFRC GO emergency event record."""
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO ifrc_go_events VALUES
               (:id,:go_id,:name,:glide,:disaster_type,:iso3,:country,
                :start_date,:num_affected,:appeal_type,:go_url,:created_at)""",
            {
                "id":           event.get("id", ""),
                "go_id":        event.get("go_id"),
                "name":         event.get("name", ""),
                "glide":        event.get("glide", ""),
                "disaster_type": event.get("disaster_type", ""),
                "iso3":         event.get("iso3", ""),
                "country":      event.get("country", ""),
                "start_date":   event.get("start_date", ""),
                "num_affected": event.get("num_affected"),
                "appeal_type":  event.get("appeal_type", ""),
                "go_url":       event.get("go_url", ""),
                "created_at":   datetime.utcnow().isoformat(),
            },
        )


def get_ifrc_go_events(iso3: str = None) -> list[dict]:
    """Return stored IFRC GO events, optionally filtered by ISO3 country code."""
    with _conn() as conn:
        if iso3:
            rows = conn.execute(
                "SELECT * FROM ifrc_go_events WHERE iso3=? ORDER BY start_date DESC",
                (iso3,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ifrc_go_events ORDER BY start_date DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_ifrc_go_event_count() -> int:
    """Return the total number of stored IFRC GO events."""
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM ifrc_go_events").fetchone()[0]


def get_ratified_allocation_runs() -> list[dict]:
    """Return all allocation runs with status='ratified', newest first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM allocation_runs WHERE status='ratified' ORDER BY ratified_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["scenario_results"]      = json.loads(d["scenario_results"] or "{}")
        d["scenario_metrics"]      = json.loads(d["scenario_metrics"] or "{}")
        d["coordinator_overrides"] = json.loads(d["coordinator_overrides"] or "{}")
        result.append(d)
    return result


def get_glide_links() -> dict:
    """Return IFRC GO events indexed by iso3 and by GLIDE number.

    Returns:
        {
            "by_iso3":  {iso3: [event_dicts]},
            "by_glide": {glide: event_dict},  # only non-empty GLIDE values
        }
    """
    from collections import defaultdict
    events = get_ifrc_go_events()
    by_iso3: dict  = defaultdict(list)
    by_glide: dict = {}
    for ev in events:
        if ev.get("iso3"):
            by_iso3[ev["iso3"]].append(ev)
        if ev.get("glide"):
            by_glide[ev["glide"]] = ev      # one GLIDE → one canonical operation
    return {"by_iso3": dict(by_iso3), "by_glide": by_glide}


# ── Routing Agent (Agent 4) ──────────────────────────────────────────────────

def upsert_route_node(node: dict):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO route_nodes
               VALUES (:id,:name,:lat,:lon,:node_type,:country,:iso3,:notes,:created_at)""",
            {
                "id":         node["id"],
                "name":       node.get("name", ""),
                "lat":        node.get("lat"),
                "lon":        node.get("lon"),
                "node_type":  node.get("node_type", "waypoint"),
                "country":    node.get("country", ""),
                "iso3":       node.get("iso3", ""),
                "notes":      node.get("notes", ""),
                "created_at": node.get("created_at", datetime.utcnow().isoformat()),
            },
        )


def get_route_nodes() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM route_nodes ORDER BY name ASC").fetchall()
    return [dict(r) for r in rows]


def upsert_route_segment(seg: dict):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO route_segments
               VALUES (:id,:from_node,:to_node,:distance_km,:est_hours,
                       :reliability_score,:safety_score,:road_quality,
                       :last_assessed,:notes,:created_at)""",
            {
                "id":                seg["id"],
                "from_node":         seg["from_node"],
                "to_node":           seg["to_node"],
                "distance_km":       seg.get("distance_km"),
                "est_hours":         seg.get("est_hours"),
                "reliability_score": seg.get("reliability_score", 0.75),
                "safety_score":      seg.get("safety_score", 0.75),
                "road_quality":      seg.get("road_quality", "mixed"),
                "last_assessed":     seg.get("last_assessed", datetime.utcnow().isoformat()),
                "notes":             seg.get("notes", ""),
                "created_at":        seg.get("created_at", datetime.utcnow().isoformat()),
            },
        )


def get_route_segments() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM route_segments").fetchall()
    return [dict(r) for r in rows]


def update_segment_scores(segment_id: str, reliability: float, safety: float):
    with _conn() as conn:
        conn.execute(
            "UPDATE route_segments SET reliability_score=?, safety_score=?, last_assessed=? WHERE id=?",
            (reliability, safety, datetime.utcnow().isoformat(), segment_id),
        )


def upsert_routing_plan(plan: dict):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO routing_plans
               VALUES (:id,:allocation_run_id,:origin_node,:destination_nodes,
                       :commodity,:quantity,:unit,:plan_status,:route_json,
                       :total_km,:est_hours,:composite_score,:planner_notes,
                       :created_at,:approved_at,:approved_by)""",
            {
                "id":                plan["id"],
                "allocation_run_id": plan.get("allocation_run_id", ""),
                "origin_node":       plan.get("origin_node", ""),
                "destination_nodes": json.dumps(plan.get("destination_nodes", [])),
                "commodity":         plan.get("commodity", ""),
                "quantity":          plan.get("quantity"),
                "unit":              plan.get("unit", ""),
                "plan_status":       plan.get("plan_status", "proposed"),
                "route_json":        json.dumps(plan.get("route_json", {})),
                "total_km":          plan.get("total_km"),
                "est_hours":         plan.get("est_hours"),
                "composite_score":   plan.get("composite_score"),
                "planner_notes":     plan.get("planner_notes", ""),
                "created_at":        plan.get("created_at", datetime.utcnow().isoformat()),
                "approved_at":       plan.get("approved_at"),
                "approved_by":       plan.get("approved_by"),
            },
        )


def get_routing_plans(status: str = None) -> list[dict]:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM routing_plans WHERE plan_status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM routing_plans ORDER BY created_at DESC"
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["destination_nodes"] = json.loads(d["destination_nodes"] or "[]")
        d["route_json"]        = json.loads(d["route_json"] or "{}")
        result.append(d)
    return result


def approve_routing_plan(plan_id: str, approved_by: str = "coordinator"):
    with _conn() as conn:
        conn.execute(
            "UPDATE routing_plans SET plan_status='approved', approved_at=?, approved_by=? WHERE id=?",
            (datetime.utcnow().isoformat(), approved_by, plan_id),
        )


def update_routing_plan_status(plan_id: str, status: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE routing_plans SET plan_status=? WHERE id=?",
            (status, plan_id),
        )


def upsert_active_mission(mission: dict):
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO active_missions
               VALUES (:id,:routing_plan_id,:allocation_run_id,:mission_status,
                       :driver_contact,:convoy_size,:departure_time,:expected_arrival,
                       :last_checkin_at,:last_position,:notes,:created_at)""",
            {
                "id":                mission["id"],
                "routing_plan_id":   mission.get("routing_plan_id", ""),
                "allocation_run_id": mission.get("allocation_run_id", ""),
                "mission_status":    mission.get("mission_status", "preparing"),
                "driver_contact":    mission.get("driver_contact", ""),
                "convoy_size":       mission.get("convoy_size", 1),
                "departure_time":    mission.get("departure_time"),
                "expected_arrival":  mission.get("expected_arrival"),
                "last_checkin_at":   mission.get("last_checkin_at"),
                "last_position":     mission.get("last_position", ""),
                "notes":             mission.get("notes", ""),
                "created_at":        mission.get("created_at", datetime.utcnow().isoformat()),
            },
        )


def get_active_missions(status: str = None) -> list[dict]:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM active_missions WHERE mission_status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM active_missions ORDER BY created_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def update_mission_status(mission_id: str, status: str, notes: str = ""):
    with _conn() as conn:
        conn.execute(
            "UPDATE active_missions SET mission_status=?, notes=? WHERE id=?",
            (status, notes, mission_id),
        )


def add_mission_checkin(checkin: dict):
    import uuid as _uuid
    with _conn() as conn:
        conn.execute(
            """INSERT INTO mission_checkins
               VALUES (:id,:mission_id,:checkin_time,:position_name,:lat,:lon,
                       :status_note,:source,:created_at)""",
            {
                "id":            checkin.get("id", str(_uuid.uuid4())),
                "mission_id":    checkin["mission_id"],
                "checkin_time":  checkin.get("checkin_time", datetime.utcnow().isoformat()),
                "position_name": checkin.get("position_name", ""),
                "lat":           checkin.get("lat"),
                "lon":           checkin.get("lon"),
                "status_note":   checkin.get("status_note", ""),
                "source":        checkin.get("source", "manual"),
                "created_at":    datetime.utcnow().isoformat(),
            },
        )
        # Update the mission's last check-in
        conn.execute(
            "UPDATE active_missions SET last_checkin_at=?, last_position=? WHERE id=?",
            (checkin.get("checkin_time", datetime.utcnow().isoformat()),
             checkin.get("position_name", ""),
             checkin["mission_id"]),
        )


def get_mission_checkins(mission_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM mission_checkins WHERE mission_id=? ORDER BY checkin_time DESC",
            (mission_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_route_disruption(disruption: dict):
    import uuid as _uuid
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO route_disruptions
               VALUES (:id,:segment_id,:disruption_type,:severity,:description,
                       :reported_at,:expires_at,:source,:active,:created_at)""",
            {
                "id":              disruption.get("id", str(_uuid.uuid4())),
                "segment_id":      disruption.get("segment_id", ""),
                "disruption_type": disruption.get("disruption_type", "other"),
                "severity":        disruption.get("severity", "medium"),
                "description":     disruption.get("description", ""),
                "reported_at":     disruption.get("reported_at", datetime.utcnow().isoformat()),
                "expires_at":      disruption.get("expires_at"),
                "source":          disruption.get("source", "manual"),
                "active":          disruption.get("active", 1),
                "created_at":      datetime.utcnow().isoformat(),
            },
        )


def get_route_disruptions(active_only: bool = True) -> list[dict]:
    with _conn() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM route_disruptions WHERE active=1 ORDER BY reported_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM route_disruptions ORDER BY reported_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def resolve_disruption(disruption_id: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE route_disruptions SET active=0 WHERE id=?",
            (disruption_id,),
        )
