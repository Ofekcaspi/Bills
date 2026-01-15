from __future__ import annotations

import base64
import email.utils
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from .categorizer import classify_category


def _parse_rfc2822_date(s: str) -> Optional[datetime]:
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _safe_filename(name: str) -> str:
    bad = ["..", "/", "\\", ":", "*", "?", '"', "<", ">", "|"]
    out = name or ""
    for b in bad:
        out = out.replace(b, "_")
    out = out.strip()
    return out or "file.pdf"


def fetch_invoice_attachments(
        *,
        creds: Credentials,
        downloads_dir: Path,
        query: str,
        max_results: int = 20,
) -> List[dict]:
    """
    מחפש מיילים לפי query ומוריד attachments (PDF) לתיקיית downloads_dir.
    מחזיר רשימת dict עם מטא-דאטה לקליטה ל-DB.
    """
    downloads_dir.mkdir(parents=True, exist_ok=True)

    service = build("gmail", "v1", credentials=creds)

    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    msgs = resp.get("messages", []) or []
    results: List[dict] = []

    def walk(p):
        if not p:
            return
        yield p
        for ch in (p.get("parts") or []):
            yield from walk(ch)

    for m in msgs:
        msg_id = m["id"]
        full = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

        headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
        subject = headers.get("subject")
        sender = headers.get("from")
        date_raw = headers.get("date")
        msg_date = _parse_rfc2822_date(date_raw) if date_raw else None

        payload = full.get("payload", {})

        for part in walk(payload):
            filename = part.get("filename") or ""
            body = part.get("body") or {}
            att_id = body.get("attachmentId")

            mime = part.get("mimeType") or ""
            is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")

            if not is_pdf or not att_id:
                continue

            att = service.users().messages().attachments().get(
                userId="me",
                messageId=msg_id,
                id=att_id,
            ).execute()

            data = att.get("data")
            if not data:
                continue

            file_bytes = base64.urlsafe_b64decode(data.encode("utf-8"))
            safe = _safe_filename(filename or f"{msg_id}.pdf")
            out_path = downloads_dir / safe

            if out_path.exists():
                stem = out_path.stem
                suf = out_path.suffix
                i = 2
                while True:
                    cand = downloads_dir / f"{stem}_{i}{suf}"
                    if not cand.exists():
                        out_path = cand
                        break
                    i += 1


            out_path.write_bytes(file_bytes)


            category = classify_category(subject, sender, out_path.name)

            results.append(
                {
                    "message_id": msg_id,
                    "attachment_id": att_id,
                    "subject": subject,
                    "sender": sender,
                    "msg_date": msg_date,
                    "filename": out_path.name,
                    "saved_path": f"downloads/{out_path.name}",
                    "category": category,
                    "amount_value": None,
                    "amount_currency": None,
                    "due_date_iso": None,
                }
            )

    return results
