import imaplib
import email as email_lib
from email.header import decode_header as _decode_header
from email.utils import parsedate_to_datetime
import re
from datetime import datetime, timezone
from config import EMAIL_IMAP_HOST, EMAIL_IMAP_PORT, EMAIL_USER, EMAIL_PASSWORD, EMAIL_FOLDER


def _decode_str(value: str) -> str:
    if not value:
        return ""
    parts = []
    for chunk, charset in _decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return " ".join(parts)


def _get_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                payload = part.get_payload(decode=True)
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html" and part.get_content_disposition() != "attachment":
                payload = part.get_payload(decode=True)
                html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                return re.sub(r"<[^>]+>", " ", html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                return re.sub(r"<[^>]+>", " ", text)
            return text
    return ""


def _parse_date(date_str: str) -> str:
    try:
        return parsedate_to_datetime(date_str).astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().isoformat()


def fetch_reports(limit: int = 30, mark_read: bool = False) -> list[dict]:
    """Fetch unread emails from the configured IMAP mailbox and mark them as read."""
    if not EMAIL_IMAP_HOST:
        print("[email] EMAIL_IMAP_HOST not configured — skipping.")
        return []

    try:
        mail = imaplib.IMAP4_SSL(EMAIL_IMAP_HOST, EMAIL_IMAP_PORT)
        mail.login(EMAIL_USER, EMAIL_PASSWORD)
        status, counts = mail.select(EMAIL_FOLDER)
        if status != "OK":
            print(f"[email] Folder '{EMAIL_FOLDER}' not found. Status: {status}")
            mail.logout()
            return []

        _, all_data = mail.search(None, "ALL")
        uids = all_data[0].split() if all_data[0] else []
        print(f"[email] Folder '{EMAIL_FOLDER}': {len(uids)} message(s) found")
        if not uids:
            mail.logout()
            return []

        uids = uids[-limit:]  # most recent first up to limit

        articles = []
        for uid in uids:
            _, raw = mail.fetch(uid, "(RFC822)")
            msg = email_lib.message_from_bytes(raw[0][1])

            subject    = _decode_str(msg.get("Subject", ""))
            sender     = _decode_str(msg.get("From", ""))
            message_id = msg.get("Message-ID", uid.decode()).strip()
            body       = _get_body(msg).strip()
            if not body:
                continue

            articles.append({
                "source_type":   "email",
                "source_id":     message_id,
                "url":           "",
                "timestamp":     _parse_date(msg.get("Date", "")),
                "raw_text":      f"From: {sender}\nSubject: {subject}\n\n{body}",
                "location_hint": {},
            })

        if mark_read:
            for uid in uids:
                mail.store(uid, "+FLAGS", "\\Seen")

        mail.logout()
        return articles

    except Exception as e:
        print(f"[email] Error: {e}")
        return []
