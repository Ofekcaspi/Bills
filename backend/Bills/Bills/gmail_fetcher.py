from __future__ import annotations

import base64
import email.utils
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from .categorizer import classify_category
from .pdf_analysis import analyze_pdf, analyze_text


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


def _decode_gmail_body_data(data: str) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_email_body_text(payload: dict) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part):
        if not part:
            return
        yield part
        for child in (part.get("parts") or []):
            yield from walk(child)

    for part in walk(payload):
        mime = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = body.get("data")
        if not data:
            continue

        decoded = _decode_gmail_body_data(data).strip()
        if not decoded:
            continue

        if mime.startswith("text/plain"):
            plain_parts.append(decoded)
        elif mime.startswith("text/html"):
            html_parts.append(decoded)

    if plain_parts:
        return "\n".join(plain_parts).strip()

    if html_parts:
        html_text = "\n".join(html_parts)
        return BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True)

    return ""


def fetch_invoice_attachments(
        *,
        creds: Credentials,
        downloads_dir: Path,
        query: str,
        max_results: int = 20,
        time_window: Optional[str] = None,
) -> List[dict]:
    downloads_dir.mkdir(parents=True, exist_ok=True)
    service = build("gmail", "v1", credentials=creds)

    q = query if not time_window else f"{query} newer_than:{time_window}"

    resp = service.users().messages().list(
        userId="me",
        q=q,
        maxResults=max_results
    ).execute()

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
        email_body_text = _extract_email_body_text(payload)
        body_analysis = analyze_text(
            email_body_text,
            source_label=f"email body {msg_id}",
        )

        found_pdf = False  # ✅ track whether we recorded any PDF attachment

        for part in walk(payload):
            filename = part.get("filename") or ""
            body = part.get("body") or {}
            att_id = body.get("attachmentId")

            mime = part.get("mimeType") or ""
            is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")

            if not is_pdf or not att_id:
                continue

            found_pdf = True

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
            analysis = analyze_pdf(out_path)
            amount_value = analysis.get("amount_value")
            amount_currency = analysis.get("amount_currency")
            due_date_iso = analysis.get("due_date_iso")

            if amount_value is None:
                amount_value = body_analysis.get("amount_value")
            if not amount_currency:
                amount_currency = body_analysis.get("amount_currency")
            if not due_date_iso:
                due_date_iso = body_analysis.get("due_date_iso")


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
                    "amount_value": amount_value,
                    "amount_currency": amount_currency,
                    "due_date_iso": due_date_iso,
                }
            )

        if not found_pdf:
            # 📩 No PDF attachments found — still record the email
            category = classify_category(subject, sender, None)
            results.append(
                {
                    "message_id": msg_id,
                    "attachment_id": None,
                    "subject": subject,
                    "sender": sender,
                    "msg_date": msg_date,
                    "filename": None,
                    "saved_path": None,
                    "category": category,
                    "amount_value": body_analysis.get("amount_value"),
                    "amount_currency": body_analysis.get("amount_currency"),
                    "due_date_iso": body_analysis.get("due_date_iso"),
                }
            )

    return results
