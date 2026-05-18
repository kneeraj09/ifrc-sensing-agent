"""
Humanitarian Sensing Agent — CLI entry point.

Usage:
    python main.py ingest [--sources bbc gdelt reliefweb acled gdacs fewsnet hdx email whatsapp telegram] [--dry-run]
    python main.py beliefs
    python main.py report
    python main.py run          # full cycle: ingest all sources → beliefs → report
"""

import argparse
import json

from store.db import (init_db, upsert_signal, upsert_belief_state, get_recent_signals,
                      get_belief_states, source_already_processed, clear_belief_states,
                      upsert_logistics_request, get_pending_requests, upsert_demand_cluster,
                      upsert_proposal, clear_demand_clusters, demand_source_already_processed,
                      mark_demand_source_processed, get_unprocessed_demand_messages,
                      mark_whatsapp_processed)
from connectors import bbc_rss, gdelt, reliefweb, acled, gdacs, fewsnet, hdx, telegram_ch, email_imap, whatsapp
from extraction.agent import extract_signals
from belief.aggregator import compute_belief_states
from demand.extractor import extract_requests
from demand.clustering import cluster_and_propose

ALL_SOURCES = ["bbc", "gdelt", "reliefweb", "acled", "gdacs", "fewsnet", "hdx", "email", "whatsapp"]
# Telegram excluded from default run — add "telegram" to --sources to enable
# Email: skips cleanly if EMAIL_IMAP_HOST not set in .env
# WhatsApp: skips cleanly if inbox is empty (messages arrive via /webhook/whatsapp)

_FETCH_MAP = {
    "bbc":       ("articles",  bbc_rss.fetch_articles),
    "gdelt":     ("articles",  gdelt.fetch_articles),
    "reliefweb": ("reports",   reliefweb.fetch_reports),
    "acled":     ("events",    acled.fetch_events),
    "gdacs":     ("alerts",    gdacs.fetch_alerts),
    "fewsnet":   ("alerts",    fewsnet.fetch_alerts),
    "hdx":       ("datasets",  hdx.fetch_datasets),
    "telegram":  ("messages",  telegram_ch.fetch_messages),
    "email":     ("reports",   email_imap.fetch_reports),
    "whatsapp":  ("messages",  whatsapp.fetch_messages),
}


def cmd_ingest(sources: list[str], dry_run: bool = False) -> list:
    print(f"[sensing] Ingesting from: {', '.join(sources)}")
    articles = []

    for source in sources:
        if source not in _FETCH_MAP:
            print(f"  [warning] Unknown source '{source}' — skipping.")
            continue
        label, fetch_fn = _FETCH_MAP[source]
        items = fetch_fn() if source != "email" else email_imap.fetch_reports(mark_read=not dry_run)
        print(f"  [{source:<10}] {len(items):>3} {label}")
        articles.extend(items)

    print(f"\n[sensing] Extracting signals from {len(articles)} items...")
    all_signals = []
    skipped = 0
    for i, article in enumerate(articles, 1):
        src_id = article.get("source_id", "")
        if not dry_run and src_id and source_already_processed(article.get("source_type", ""), src_id):
            skipped += 1
            continue
        try:
            signals = extract_signals(article)
        except Exception as e:
            print(f"  [{i:>3}/{len(articles)}] {article.get('source_type','?'):>10}  ERROR: {e}")
            continue
        for sig in signals:
            if not dry_run:
                upsert_signal(sig)
            all_signals.append(sig)
        if signals:
            print(f"  [{i:>3}/{len(articles)}] {article['source_type']:>10}  +{len(signals)} signal(s)")
        # Ack WhatsApp messages after extraction (success or empty) — not on exception
        if not dry_run and article.get("source_type") == "whatsapp" and article.get("_inbox_id"):
            mark_whatsapp_processed([article["_inbox_id"]])

    print(f"\n[sensing] Stored {len(all_signals)} signal(s) total. ({skipped} article(s) already processed — skipped)")
    return all_signals


def cmd_beliefs() -> list:
    signals = get_recent_signals(hours=72)
    print(f"[beliefs] Computing over {len(signals)} signal(s) from the last 72h...")
    clear_belief_states()
    beliefs = compute_belief_states(signals)
    for bs in beliefs:
        upsert_belief_state(bs)
    alerts = [bs for bs in beliefs if bs.alert]
    if alerts:
        print(f"\n{'='*60}")
        print(f"  {len(alerts)} ALERT(S)")
        print(f"{'='*60}")
        for bs in alerts:
            print(f"  {bs.alert}")
    print(f"\n[beliefs] Updated {len(beliefs)} belief state(s).")
    return beliefs


def cmd_report():
    beliefs = get_belief_states()
    print(json.dumps(beliefs, indent=2, default=str))


def cmd_demand_extract() -> int:
    messages = get_unprocessed_demand_messages()
    print(f"[demand] Checking {len(messages)} message(s) for logistics requests...")
    total = 0
    for msg in messages:
        try:
            requests = extract_requests(msg)
        except Exception as e:
            print(f"  [demand-extract] skipping {msg['source_id']} — will retry next cycle ({e})")
            continue
        for req in requests:
            upsert_logistics_request(req)
            total += 1
            print(f"  + request: {req.commodity} {req.origin} → {req.destination} ({req.requesting_org or '?'})")
        mark_demand_source_processed(msg["source_type"], msg["source_id"])
    print(f"[demand] Extracted {total} logistics request(s).")
    return total


def cmd_demand_cluster():
    pending = get_pending_requests()
    print(f"[demand] Clustering {len(pending)} pending request(s)...")
    clear_demand_clusters()
    clusters, proposals = cluster_and_propose(pending)
    for c in clusters:
        upsert_demand_cluster(c)
    for p in proposals:
        upsert_proposal(p)
    print(f"[demand] {len(clusters)} cluster(s), {len(proposals)} proposal(s) generated.")


def cmd_demand_run():
    cmd_demand_extract()
    cmd_demand_cluster()


def main():
    parser = argparse.ArgumentParser(
        description="Humanitarian Sensing Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Fetch and extract signals from sources")
    p_ingest.add_argument(
        "--sources", nargs="+", default=ALL_SOURCES,
        choices=ALL_SOURCES, metavar="SOURCE",
        help=f"Sources to ingest (default: all). Choices: {ALL_SOURCES}",
    )
    p_ingest.add_argument(
        "--dry-run", action="store_true",
        help="Extract and print signals without writing to the database",
    )

    sub.add_parser("beliefs",        help="Recompute belief states from stored signals")
    sub.add_parser("report",         help="Print current belief states as JSON")
    sub.add_parser("run",            help="Full cycle: ingest all sources → beliefs → report")
    sub.add_parser("demand-extract", help="Extract logistics requests from email/WhatsApp messages")
    sub.add_parser("demand-cluster", help="Cluster pending requests and generate proposals")
    sub.add_parser("demand-run",     help="Full demand cycle: extract → cluster → propose")

    args = parser.parse_args()
    init_db()

    if args.command == "ingest":
        cmd_ingest(args.sources, dry_run=args.dry_run)
    elif args.command == "beliefs":
        cmd_beliefs()
    elif args.command == "report":
        cmd_report()
    elif args.command == "run":
        cmd_ingest(ALL_SOURCES)
        cmd_beliefs()
        cmd_report()
    elif args.command == "demand-extract":
        cmd_demand_extract()
    elif args.command == "demand-cluster":
        cmd_demand_cluster()
    elif args.command == "demand-run":
        cmd_demand_run()


if __name__ == "__main__":
    main()
