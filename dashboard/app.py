import json
import sqlite3
import sys
import os
import subprocess
import threading
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import anthropic
from flask import Flask, render_template, request, abort, redirect, jsonify
from config import DB_PATH, ANTHROPIC_API_KEY, EXTRACTION_MODEL, TWILIO_AUTH_TOKEN
from store.db import (store_whatsapp_message, upsert_logistics_request,
                      get_all_requests, get_all_clusters, get_all_proposals,
                      update_proposal_status, update_request_status,
                      upsert_stock_position, get_stock_positions,
                      upsert_allocation_run, get_allocation_runs, get_latest_allocation_run)
from models import LogisticsRequest, StockPosition, AllocationRun
from utils.regions import classify

try:
    from twilio.request_validator import RequestValidator as _TwilioValidator
    _TWILIO_AVAILABLE = True
except ImportError:
    _TWILIO_AVAILABLE = False

app = Flask(__name__)
_anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_RISK_ORDER   = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}
_BRIEFING_CACHE_PATH = os.path.join(os.path.dirname(__file__), ".briefing_cache.json")
_BRIEFING_TTL_MINUTES = 30

ALL_REGIONS = ["Africa", "Asia", "Middle East", "Latin America", "Europe", "North America", "Oceania", "Global"]


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _get_beliefs_with_signals():
    conn = _get_db()
    beliefs = [dict(r) for r in conn.execute(
        "SELECT * FROM belief_states ORDER BY last_updated DESC"
    ).fetchall()]
    for b in beliefs:
        b["supporting_signal_ids"] = json.loads(b["supporting_signal_ids"] or "[]")
        b["risk_order"] = _RISK_ORDER.get(b["risk_level"], 4)
        b["region"]     = classify(b.get("country"))
        if b["supporting_signal_ids"]:
            placeholders = ",".join("?" * len(b["supporting_signal_ids"]))
            b["signals"] = [dict(r) for r in conn.execute(
                f"SELECT * FROM signals WHERE id IN ({placeholders}) ORDER BY timestamp DESC",
                b["supporting_signal_ids"],
            ).fetchall()]
        else:
            b["signals"] = []
    beliefs.sort(key=lambda x: x["risk_order"])
    conn.close()
    return beliefs


def _get_stats():
    conn = _get_db()
    stats = {
        "total_signals":  conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0],
        "total_beliefs":  conn.execute("SELECT COUNT(*) FROM belief_states").fetchone()[0],
        "alerts":         conn.execute(
            "SELECT COUNT(*) FROM belief_states WHERE risk_level IN ('critical','high')"
        ).fetchone()[0],
        "last_ingested":  conn.execute("SELECT MAX(created_at) FROM signals").fetchone()[0],
    }
    conn.close()
    return stats


def _group_by_region(beliefs: list[dict]) -> dict:
    """Group beliefs by region, preserving risk-level sort within each group."""
    groups = defaultdict(list)
    for b in beliefs:
        groups[b["region"]].append(b)
    # Only return regions that have data, in a consistent order
    return {r: groups[r] for r in ALL_REGIONS if groups[r]}


def _priority_groups(beliefs: list[dict]) -> dict:
    return {
        "action":  [b for b in beliefs if b["risk_level"] in ("critical", "high")],
        "monitor": [b for b in beliefs if b["risk_level"] == "medium"],
        "watch":   [b for b in beliefs if b["risk_level"] in ("low", "unknown")],
    }


def _group_beliefs_by_location(beliefs: list[dict]) -> list[dict]:
    """Merge per-commodity belief states into one entry per location."""
    seen = {}
    ordered = []
    for b in beliefs:  # already sorted by risk_order
        key = (b["location"], b.get("country") or "")
        if key not in seen:
            group = {
                "location":          b["location"],
                "country":           b.get("country"),
                "region":            b.get("region"),
                "risk_level":        b["risk_level"],
                "risk_order":        b["risk_order"],
                "alert":             b.get("alert"),
                "time_window":       b.get("time_window"),
                "commodity_beliefs": [],
                "all_signals":       [],
            }
            seen[key] = group
            ordered.append(group)
        g = seen[key]
        if b["risk_order"] < g["risk_order"]:
            g["risk_order"] = b["risk_order"]
            g["risk_level"] = b["risk_level"]
            if b.get("alert"):
                g["alert"] = b["alert"]
        g["commodity_beliefs"].append(b)
        g["all_signals"].extend(b.get("signals", []))
    for g in ordered:
        seen_ids = set()
        deduped = []
        for s in g["all_signals"]:
            if s["id"] not in seen_ids:
                seen_ids.add(s["id"])
                deduped.append(s)
        g["all_signals"] = deduped
    return ordered


def _load_briefing_cache():
    try:
        with open(_BRIEFING_CACHE_PATH) as f:
            cache = json.load(f)
        age = (datetime.utcnow() - datetime.fromisoformat(cache["generated_at"])).seconds / 60
        if age < _BRIEFING_TTL_MINUTES and "regions" in cache:
            return cache
    except Exception:
        pass
    return None


def _save_briefing_cache(briefing: dict):
    try:
        with open(_BRIEFING_CACHE_PATH, "w") as f:
            json.dump(briefing, f)
    except Exception:
        pass


def generate_scqa_briefing(beliefs: list[dict], region_groups: dict = None) -> dict:
    cached = _load_briefing_cache()
    if cached:
        return cached

    if not beliefs:
        return {
            "situation": "No humanitarian signals detected in the current monitoring window.",
            "complication": "Insufficient data to assess the situation.",
            "question": "Should ingestion sources be expanded or the monitoring window widened?",
            "answer": "Run ingestion across all sources before drawing conclusions.",
            "recommendations": [],
            "regions": {},
            "generated_at": datetime.utcnow().isoformat(),
        }

    summary_lines = []
    for b in beliefs[:20]:
        summary_lines.append(
            f"- {b['location']} ({b.get('country','?')}, {b.get('region','?')}): "
            f"{b['commodity']} — risk={b['risk_level']}, "
            f"signals={len(b['signals'])}, alert={b.get('alert') or 'none'}"
        )

    region_lines = []
    for region, rbeliefs in (region_groups or {}).items():
        top_risk = min(
            (b["risk_level"] for b in rbeliefs),
            key=lambda r: _RISK_ORDER.get(r, 4),
            default="unknown",
        )
        commodities = list({b["commodity"] for b in rbeliefs})[:4]
        region_lines.append(
            f"- {region}: {len(rbeliefs)} locations, top risk={top_risk}, commodities={', '.join(commodities)}"
        )

    prompt = f"""You are a senior humanitarian logistics analyst briefing a global operations director.
Using the Minto Pyramid (SCQA), write a concise executive briefing from these belief states:

{chr(10).join(summary_lines)}

Regional breakdown:
{chr(10).join(region_lines) if region_lines else "No regional data available."}

Return a JSON object with exactly these keys:
- situation: 1–2 sentences on the current observed state (factual, no recommendations)
- complication: 1–2 sentences on what is concerning or has changed
- question: the single key decision this forces
- answer: the headline recommendation in one sentence
- recommendations: array of 3–5 specific, prioritised action strings (imperative, brief)
- regions: object where each key is a region name from the breakdown above, value has:
    - headline: one factual sentence on the main concern in that region
    - risk: highest risk level (critical/high/medium/low/unknown)
    - action: one short imperative action for operations staff covering that region

Be direct. Write for a decision-maker who has 90 seconds."""

    try:
        response = _anthropic.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Extract JSON from anywhere in the response
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found in response")
        briefing = json.loads(text[start:end])
        briefing.setdefault("regions", {})
        briefing["generated_at"] = datetime.utcnow().isoformat()
        _save_briefing_cache(briefing)
        return briefing
    except Exception as e:
        print(f"[dashboard] SCQA error: {e}")
        return {
            "situation": "Briefing generation failed.", "complication": str(e),
            "question": "", "answer": "", "recommendations": [],
            "regions": {},
            "generated_at": datetime.utcnow().isoformat(),
        }



_run_state = {"status": "idle", "log": []}
_run_lock  = threading.Lock()
_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


_RUN_TIMEOUT_SECONDS = 900  # 15 min max per full cycle


def _run_background():
    with _run_lock:
        _run_state.update({"status": "running", "log": []})
    lines = []
    try:
        proc = subprocess.Popen(
            [sys.executable, "main.py", "run"],
            cwd=_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            stdout, _ = proc.communicate(timeout=_RUN_TIMEOUT_SECONDS)
            lines = [l.rstrip() for l in stdout.splitlines()]
            status = "done" if proc.returncode == 0 else "error"
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
            lines = [l.rstrip() for l in stdout.splitlines()]
            lines.append(f"[timeout] Cycle killed after {_RUN_TIMEOUT_SECONDS}s")
            status = "error"
    except Exception as e:
        lines.append(f"ERROR: {e}")
        status = "error"
    with _run_lock:
        _run_state["status"] = status
        _run_state["log"]    = lines[-60:]


@app.route("/run", methods=["POST"])
def run_cycle():
    with _run_lock:
        if _run_state["status"] == "running":
            return jsonify({"status": "already_running"}), 409
    threading.Thread(target=_run_background, daemon=True).start()
    return jsonify({"status": "started"}), 202


@app.route("/run/status")
def run_status():
    with _run_lock:
        return jsonify(_run_state.copy())


@app.route("/run/reset", methods=["POST"])
def run_reset():
    with _run_lock:
        _run_state.update({"status": "idle", "log": ["[reset] State cleared manually."]})
    return jsonify({"status": "idle"})


@app.route("/cheatsheet")
def cheatsheet():
    return render_template("cheatsheet.html")


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    if TWILIO_AUTH_TOKEN:
        if not _TWILIO_AVAILABLE:
            print("[webhook] twilio package not installed — skipping signature validation")
        else:
            validator = _TwilioValidator(TWILIO_AUTH_TOKEN)
            # Reconstruct the public URL using forwarded headers (required when behind ngrok/proxy)
            proto = request.headers.get("X-Forwarded-Proto", request.scheme)
            host  = request.headers.get("X-Forwarded-Host", request.host)
            url   = f"{proto}://{host}{request.path}"
            sig   = request.headers.get("X-Twilio-Signature", "")
            if not validator.validate(url, request.form, sig):
                abort(403)

    from_number = request.form.get("From", "")
    body        = request.form.get("Body", "").strip()
    num_media   = int(request.form.get("NumMedia", 0))
    media_urls  = [request.form.get(f"MediaUrl{i}") for i in range(num_media) if request.form.get(f"MediaUrl{i}")]

    if body or media_urls:
        store_whatsapp_message(from_number, body, media_urls)
        print(f"[webhook] WhatsApp message stored from {from_number} ({len(body)} chars, {len(media_urls)} media)")

    return ('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', 200, {"Content-Type": "text/xml"})


@app.route("/")
def index():
    beliefs        = _get_beliefs_with_signals()
    stats          = _get_stats()
    region_groups   = _group_by_region(beliefs)
    briefing        = generate_scqa_briefing(beliefs, region_groups)
    active_regions  = list(region_groups.keys())

    location_beliefs       = _group_beliefs_by_location(beliefs)
    priority_groups        = _priority_groups(location_beliefs)
    region_priority_groups = {
        region: _priority_groups(_group_beliefs_by_location(grp))
        for region, grp in region_groups.items()
    }

    return render_template(
        "index.html",
        beliefs=beliefs,
        stats=stats,
        briefing=briefing,
        region_groups=region_groups,
        priority_groups=priority_groups,
        region_priority_groups=region_priority_groups,
        active_regions=active_regions,
    )


@app.route("/demand")
def demand():
    requests  = get_all_requests()
    clusters  = get_all_clusters()
    proposals = get_all_proposals()

    # Attach request details to each cluster
    req_by_id = {r["id"]: r for r in requests}
    for c in clusters:
        c["requests"] = [req_by_id[rid] for rid in c["request_ids"] if rid in req_by_id]

    # Attach cluster + requests to each proposal
    cluster_by_id = {c["id"]: c for c in clusters}
    for p in proposals:
        p["cluster"] = cluster_by_id.get(p["cluster_id"], {})

    stats = {
        "total_requests":   len(requests),
        "pending_requests": sum(1 for r in requests if r["status"] == "pending"),
        "pending_proposals": sum(1 for p in proposals if p["status"] == "pending"),
        "accepted":          sum(1 for p in proposals if p["status"] == "accepted"),
    }
    return render_template("demand.html", requests=requests, clusters=clusters,
                           proposals=proposals, stats=stats)


@app.route("/demand/debug")
def demand_debug():
    """Diagnostic: show raw whatsapp_inbox and demand pipeline state."""
    conn = _get_db()
    inbox = [dict(r) for r in conn.execute(
        "SELECT id, from_number, substr(body,1,100) as body, received_at, processed "
        "FROM whatsapp_inbox ORDER BY received_at DESC LIMIT 20"
    ).fetchall()]
    processed = [dict(r) for r in conn.execute(
        "SELECT * FROM demand_processed_sources ORDER BY processed_at DESC LIMIT 20"
    ).fetchall()]
    pending = [dict(r) for r in conn.execute(
        """SELECT 'wa_'||w.id as source_id, substr(w.body,1,100) as body, w.received_at,
                  w.processed as sensing_processed
           FROM whatsapp_inbox w
           WHERE NOT EXISTS (
               SELECT 1 FROM demand_processed_sources d
               WHERE d.source_type='whatsapp' AND d.source_id='wa_'||w.id
           ) ORDER BY w.received_at DESC"""
    ).fetchall()]
    conn.close()
    return jsonify({
        "whatsapp_inbox_count": len(inbox),
        "whatsapp_inbox": inbox,
        "demand_processed_sources": processed,
        "pending_for_demand_cycle": pending,
    })


@app.route("/demand/request", methods=["POST"])
def add_manual_request():
    req = LogisticsRequest(
        source="manual",
        requesting_org=request.form.get("requesting_org") or None,
        origin=request.form.get("origin", "").strip(),
        destination=request.form.get("destination", "").strip(),
        commodity=request.form.get("commodity", "").strip(),
        quantity=float(request.form["quantity"]) if request.form.get("quantity") else None,
        unit=request.form.get("unit") or None,
        deadline=request.form.get("deadline") or None,
        urgency=request.form.get("urgency", "unknown"),
        notes=request.form.get("notes") or None,
        confidence=1.0,
    )
    upsert_logistics_request(req)
    return redirect("/demand")


@app.route("/demand/proposal/<proposal_id>", methods=["POST"])
def review_proposal(proposal_id):
    status = request.form.get("status", "pending")
    notes  = request.form.get("notes", "")
    update_proposal_status(proposal_id, status, notes)
    return redirect("/demand")


@app.route("/demand/request/<request_id>/cancel", methods=["POST"])
def cancel_request(request_id):
    update_request_status(request_id, "cancelled")
    return redirect("/demand")


_demand_run_state = {"status": "idle", "log": []}
_demand_run_lock  = threading.Lock()


def _run_demand_background():
    with _demand_run_lock:
        _demand_run_state.update({"status": "running", "log": []})
    lines = []
    try:
        proc = subprocess.Popen(
            [sys.executable, "main.py", "demand-run"],
            cwd=_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            stdout, _ = proc.communicate(timeout=300)
            lines = [l.rstrip() for l in stdout.splitlines()]
            status = "done" if proc.returncode == 0 else "error"
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
            lines = [l.rstrip() for l in stdout.splitlines()]
            lines.append("[timeout] Demand cycle killed after 300s")
            status = "error"
    except Exception as e:
        lines.append(f"ERROR: {e}")
        status = "error"
    with _demand_run_lock:
        _demand_run_state["status"] = status
        _demand_run_state["log"]    = lines[-60:]


@app.route("/demand/run", methods=["POST"])
def run_demand_cycle():
    with _demand_run_lock:
        if _demand_run_state["status"] == "running":
            return jsonify({"status": "already_running"}), 409
    threading.Thread(target=_run_demand_background, daemon=True).start()
    return jsonify({"status": "started"}), 202


@app.route("/demand/run/status")
def demand_run_status():
    with _demand_run_lock:
        return jsonify(_demand_run_state.copy())


# ── Allocation agent ────────────────────────────────────────────────────────

@app.route("/allocation")
def allocation():
    from allocation.newsvendor import SCENARIOS
    stock     = get_stock_positions()
    runs      = get_allocation_runs()
    latest    = runs[0] if runs else None
    beliefs   = _get_beliefs_with_signals()
    return render_template("allocation.html", stock=stock, runs=runs,
                           latest=latest, beliefs=beliefs, scenarios=SCENARIOS)


@app.route("/allocation/stock", methods=["POST"])
def add_stock():
    pos = StockPosition(
        commodity=request.form.get("commodity", "").strip(),
        depot_location=request.form.get("depot_location", "").strip(),
        quantity=float(request.form.get("quantity", 0)),
        unit=request.form.get("unit", "").strip(),
        as_of=request.form.get("as_of") or None,
    )
    upsert_stock_position(pos)
    return redirect("/allocation")


@app.route("/allocation/run", methods=["POST"])
def run_allocation():
    import json as _json
    from allocation.newsvendor import run_all_scenarios
    from allocation.metrics import scenario_summary

    commodity = request.form.get("commodity", "").strip()
    unit      = request.form.get("unit", "units").strip()
    try:
        available_stock = float(request.form.get("available_stock", 0))
    except ValueError:
        available_stock = 0

    beliefs = _get_beliefs_with_signals()
    locations = []
    for b in beliefs:
        if commodity and b.get("commodity", "").lower() != commodity.lower():
            continue
        locations.append({
            "location":     b["location"],
            "commodity":    b.get("commodity", "general"),
            "risk_level":   b.get("risk_level", "unknown"),
            "demand_p10":   b.get("demand_p10") or 0.3,
            "demand_p50":   b.get("demand_p50") or 0.5,
            "demand_p90":   b.get("demand_p90") or 0.8,
            "reference_qty": available_stock / max(len(beliefs), 1),
        })

    if not locations:
        return redirect("/allocation")

    all_results = run_all_scenarios(locations, available_stock)
    metrics     = scenario_summary(all_results)

    run = AllocationRun(
        commodity=commodity or "all",
        unit=unit,
        available_stock=available_stock,
        scenario_results=_json.dumps(all_results),
        scenario_metrics=_json.dumps(metrics),
    )
    upsert_allocation_run(run)
    return redirect(f"/allocation?run_id={run.id}")


@app.route("/allocation/select", methods=["POST"])
def select_scenario():
    import json as _json
    run_id   = request.form.get("run_id")
    scenario = request.form.get("scenario")
    runs     = get_allocation_runs()
    run_data = next((r for r in runs if r["id"] == run_id), None)
    if not run_data:
        return redirect("/allocation")

    overrides = {}
    for key, val in request.form.items():
        if key.startswith("override_") and val.strip():
            loc = key[len("override_"):]
            try:
                overrides[loc] = float(val)
            except ValueError:
                pass

    from allocation.briefing import generate_decision_brief
    from allocation.metrics import compute_metrics
    results  = run_data["scenario_results"].get(scenario, [])
    metrics  = run_data["scenario_metrics"].get(scenario, {})

    # Apply overrides to results for brief generation
    brief = generate_decision_brief(
        scenario_name=scenario,
        allocations=results,
        metrics=metrics,
        available_stock=run_data["available_stock"],
        unit=run_data["unit"],
        commodity=run_data["commodity"],
        coordinator_overrides=overrides if overrides else None,
    )

    run = AllocationRun(
        id=run_id,
        commodity=run_data["commodity"],
        unit=run_data["unit"],
        available_stock=run_data["available_stock"],
        scenario_results=_json.dumps(run_data["scenario_results"]),
        scenario_metrics=_json.dumps(run_data["scenario_metrics"]),
        selected_scenario=scenario,
        coordinator_overrides=_json.dumps(overrides) if overrides else None,
        decision_brief=brief,
        status="draft",
        created_at=run_data["created_at"],
    )
    upsert_allocation_run(run)
    return redirect(f"/allocation?run_id={run_id}")


@app.route("/allocation/ratify", methods=["POST"])
def ratify_allocation():
    import json as _json
    from datetime import datetime as _dt
    run_id   = request.form.get("run_id")
    rationale = request.form.get("rationale", "")
    runs     = get_allocation_runs()
    run_data = next((r for r in runs if r["id"] == run_id), None)
    if not run_data:
        return redirect("/allocation")

    run = AllocationRun(
        id=run_id,
        commodity=run_data["commodity"],
        unit=run_data["unit"],
        available_stock=run_data["available_stock"],
        scenario_results=_json.dumps(run_data["scenario_results"]),
        scenario_metrics=_json.dumps(run_data["scenario_metrics"]),
        selected_scenario=run_data.get("selected_scenario"),
        coordinator_overrides=_json.dumps(run_data.get("coordinator_overrides") or {}),
        decision_brief=run_data.get("decision_brief"),
        status="ratified",
        created_at=run_data["created_at"],
        ratified_at=_dt.utcnow().isoformat(),
        rationale=rationale,
    )
    upsert_allocation_run(run)
    return redirect("/allocation")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=False, host="0.0.0.0", port=port)
