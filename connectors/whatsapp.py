from store.db import get_pending_whatsapp_messages, mark_whatsapp_processed


def fetch_messages(limit: int = 100) -> list[dict]:
    """Return buffered WhatsApp messages that arrived via the Twilio webhook.

    Messages are stored by the /webhook/whatsapp Flask endpoint and marked
    processed here so they are not ingested twice.
    """
    messages = get_pending_whatsapp_messages(limit)
    if not messages:
        return []

    articles = []
    for msg in messages:
        body = (msg.get("body") or "").strip()
        if not body:
            continue
        articles.append({
            "source_type":   "whatsapp",
            "source_id":     f"wa_{msg['id']}",
            "_inbox_id":     msg["id"],   # used by main.py to ack after extraction
            "url":           "",
            "timestamp":     msg["received_at"],
            "raw_text":      f"WhatsApp from {msg.get('from_number', 'unknown')}:\n{body}",
            "location_hint": {},
        })

    # NOTE: do NOT mark processed here — main.py acks each message individually
    # after extraction succeeds, so a mid-cycle crash won't silently discard messages.
    return articles
