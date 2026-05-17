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
    ids = []
    for msg in messages:
        body = (msg.get("body") or "").strip()
        if not body:
            continue
        ids.append(msg["id"])
        articles.append({
            "source_type":   "whatsapp",
            "source_id":     f"wa_{msg['id']}",
            "url":           "",
            "timestamp":     msg["received_at"],
            "raw_text":      f"WhatsApp from {msg.get('from_number', 'unknown')}:\n{body}",
            "location_hint": {},
        })

    if ids:
        mark_whatsapp_processed(ids)

    return articles
