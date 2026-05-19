from __future__ import annotations

import base64
import email.utils
import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone,timedelta

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from .categorizer import classify_category
from .pdf_analysis import analyze_pdf, analyze_text
from .BillClassifier import get_bill_receipt_general_classifier



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


def _make_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suf = path.suffix
    i = 2
    while True:
        cand = path.parent / f"{stem}_{i}{suf}"
        if not cand.exists():
            return cand
        i += 1


def _extract_part_charset(part: dict) -> Optional[str]:
    for header in (part.get("headers") or []):
        if (header.get("name") or "").lower() != "content-type":
            continue
        value = header.get("value") or ""
        match = re.search(r"charset\s*=\s*['\"]?([^\s;\"']+)", value, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _decode_gmail_body_data(data: str, *, charset: Optional[str] = None) -> str:
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data.encode("utf-8"))
    except Exception:
        return ""

    charsets = [charset, "utf-8", "windows-1255", "iso-8859-8", "latin-1"]
    seen: set[str] = set()
    for cs in charsets:
        if not cs:
            continue
        normalized = cs.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return raw.decode(normalized)
        except Exception:
            continue

    return raw.decode("utf-8", errors="replace")


def _extract_email_body_text(service, msg_id: str, payload: dict) -> str:
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
        if not data and body.get("attachmentId") and (
            mime.startswith("text/plain") or mime.startswith("text/html")
        ):
            try:
                att = service.users().messages().attachments().get(
                    userId="me",
                    messageId=msg_id,
                    id=body["attachmentId"],
                ).execute()
                data = att.get("data")
            except Exception:
                data = None
        if not data:
            continue

        decoded = _decode_gmail_body_data(data, charset=_extract_part_charset(part)).strip()
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
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
) -> List[dict]:
    downloads_dir.mkdir(parents=True, exist_ok=True)
    service = build("gmail", "v1", credentials=creds)
    bill_classifier = get_bill_receipt_general_classifier()

    q = query

    if start_date and end_date:
        after = start_date.strftime("%Y/%m/%d")
        before = (end_date + timedelta(days=1)).strftime("%Y/%m/%d")
        q = f"{q} after:{after} before:{before}"
    elif time_window:
        q = f"{q} newer_than:{time_window}"
    page_size = max(1, min(int(max_results or 20), 500))
    msgs: List[dict] = []
    page_token: Optional[str] = None

    while True:
        list_kwargs = {
            "userId": "me",
            "q": q,
            "maxResults": page_size,
        }
        if page_token:
            list_kwargs["pageToken"] = page_token

        resp = service.users().messages().list(**list_kwargs).execute()
        msgs.extend(resp.get("messages", []) or [])

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

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
        email_body_text = _extract_email_body_text(service, msg_id, payload)

        body_analysis = analyze_text(
            email_body_text,
            source_label=f"email body {msg_id}",
        )

        pdf_parts = []

        for part in walk(payload):
            filename = part.get("filename") or ""
            body = part.get("body") or {}
            att_id = body.get("attachmentId")
            mime = part.get("mimeType") or ""

            is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")

            if is_pdf and att_id:
                pdf_parts.append((part, filename, att_id, mime))

        has_bill_document_pdf = False

        # Case 1: email has PDF(s)
        if pdf_parts:
            for part, filename, att_id, mime in pdf_parts:
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
                out_path = _make_unique_path(downloads_dir / safe)
                out_path.write_bytes(file_bytes)

                prediction, _ = bill_classifier.classify_file(out_path,subject=subject)
                if prediction not in ["bill","receipt"]:
                    continue
                document_type = prediction.lower().strip()

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

                if amount_value is None:
                    continue

                category = classify_category(subject, sender, out_path.name)

                results.append(
                    {
                        "document_type": document_type,
                        "message_id": msg_id,
                        "attachment_id": att_id,
                        "subject": subject,
                        "sender": sender,
                        "msg_date": msg_date,
                        "filename": out_path.name,
                        "saved_path": f"downloads/{out_path.name}",
                        "vendor": sender,
                        "category": category,
                        "amount_value": amount_value,
                        "amount_currency": amount_currency,
                        "due_date_iso": due_date_iso,
                    }
                )

                has_bill_document_pdf = True

            # If at least one PDF is financial with amount,
            # keep PDF path as source of truth.
            if has_bill_document_pdf:
                continue

        # Case 2: no PDFs -> fallback to body text
        prediction, _ = bill_classifier.classify_text(email_body_text or "")
        if prediction not in ["bill","receipt"]:
            continue
        document_type = prediction.lower().strip()

        print("pred:", document_type)

        if body_analysis.get("amount_value") is None:
            continue

        safe = _safe_filename(f"{msg_id}_body.txt")
        out_path = _make_unique_path(downloads_dir / safe)

        out_path.write_text(
            email_body_text or "",
            encoding="utf-8",
            )

        category = classify_category(subject, sender, out_path.name)

        results.append(
            {
                "document_type": document_type,
                "message_id": msg_id,
                "attachment_id": None,
                "subject": subject,
                "sender": sender,
                "msg_date": msg_date,
                "filename": out_path.name,
                "saved_path": f"downloads/{out_path.name}",
                "vendor": sender,
                "category": category,
                "amount_value": body_analysis.get("amount_value"),
                "amount_currency": body_analysis.get("amount_currency"),
                "due_date_iso": body_analysis.get("due_date_iso"),
            }
        )
    return results
def _user_replied_to_thread(service, thread_id, my_email):
    thread = service.users().threads().get(
        userId="me",
        id=thread_id,
        format="metadata",
        metadataHeaders=["From"],
    ).execute()

    my_email = my_email.lower()

    for msg in thread.get("messages", []):
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }

        sender = (headers.get("from") or "").lower()

        if my_email in sender:
            return True

    return False
def fetch_invoice_attachments(
        *,
        creds: Credentials,
        downloads_dir: Path,
        query: str,
        my_email: str,
        max_results: int = 20,
        time_window: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
) -> List[dict]:
    downloads_dir.mkdir(parents=True, exist_ok=True)
    service = build("gmail", "v1", credentials=creds)
    bill_classifier = get_bill_receipt_general_classifier()

    q = query

    if start_date and end_date:
        after = start_date.strftime("%Y/%m/%d")
        before = (end_date + timedelta(days=1)).strftime("%Y/%m/%d")
        q = f"{q} after:{after} before:{before}"
    elif time_window:
        q = f"{q} newer_than:{time_window}"
    page_size = max(1, min(int(max_results or 20), 500))
    msgs: List[dict] = []
    page_token: Optional[str] = None

    while True:
        list_kwargs = {
            "userId": "me",
            "q": q,
            "maxResults": page_size,
        }
        if page_token:
            list_kwargs["pageToken"] = page_token

        resp = service.users().messages().list(**list_kwargs).execute()
        msgs.extend(resp.get("messages", []) or [])

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

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
        if _user_replied_to_thread(service, full["threadId"], my_email):
            continue
        headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
        subject = headers.get("subject")
        sender = headers.get("from")
        date_raw = headers.get("date")
        msg_date = _parse_rfc2822_date(date_raw) if date_raw else None

        payload = full.get("payload", {})
        email_body_text = _extract_email_body_text(service, msg_id, payload)
        body_analysis = analyze_text(
            email_body_text,
            source_label=f"email body {msg_id}",
        )

        pdf_parts = []

        for part in walk(payload):
            filename = part.get("filename") or ""
            body = part.get("body") or {}
            att_id = body.get("attachmentId")
            mime = part.get("mimeType") or ""

            is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")

            if is_pdf and att_id:
                pdf_parts.append((part, filename, att_id, mime))

        has_bill_document_pdf = False

        # Case 1: email has PDF(s)
        if pdf_parts:
            for part, filename, att_id, mime in pdf_parts:
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
                out_path = _make_unique_path(downloads_dir / safe)
                out_path.write_bytes(file_bytes)

                prediction, _ = bill_classifier.classify_file(out_path,subject=subject)
                if prediction not in ["bill","receipt"]:
                    continue
                document_type = prediction.lower().strip()

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

                if amount_value is None:
                    continue

                category = classify_category(subject, sender, out_path.name)

                results.append(
                    {
                        "document_type": document_type,
                        "message_id": msg_id,
                        "attachment_id": att_id,
                        "subject": subject,
                        "sender": sender,
                        "msg_date": msg_date,
                        "filename": out_path.name,
                        "saved_path": f"downloads/{out_path.name}",
                        "vendor": sender,
                        "category": category,
                        "amount_value": amount_value,
                        "amount_currency": amount_currency,
                        "due_date_iso": due_date_iso,
                    }
                )

                has_bill_document_pdf = True

            # If at least one PDF is financial with amount,
            # keep PDF path as source of truth.
            if has_bill_document_pdf:
                continue

        # Case 2: no PDFs -> fallback to body text
        prediction, _ = bill_classifier.classify_text(email_body_text or "",subject=subject)
        if prediction not in ["bill","receipt"]:
            continue
        document_type = prediction.lower().strip()

        print("pred:", document_type)

        if body_analysis.get("amount_value") is None:
            continue

        safe = _safe_filename(f"{msg_id}_body.txt")
        out_path = _make_unique_path(downloads_dir / safe)

        out_path.write_text(
            email_body_text or "",
            encoding="utf-8",
            )

        category = classify_category(subject, sender, out_path.name)

        results.append(
            {
                "document_type": document_type,
                "message_id": msg_id,
                "attachment_id": None,
                "subject": subject,
                "sender": sender,
                "msg_date": msg_date,
                "filename": out_path.name,
                "saved_path": f"downloads/{out_path.name}",
                "vendor": sender,
                "category": category,
                "amount_value": body_analysis.get("amount_value"),
                "amount_currency": body_analysis.get("amount_currency"),
                "due_date_iso": body_analysis.get("due_date_iso"),
            }
        )
    return results

