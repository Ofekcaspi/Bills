from __future__ import annotations

import base64
import email.utils
import logging
import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from .categorizer import classify_category
from .pdf_analysis import analyze_pdf, analyze_text
from .BillClassifier import get_bill_receipt_general_classifier
from .file_naming import safe_filename, make_unique_path

logger = logging.getLogger(__name__)


def _parse_rfc2822_date(s: str) -> Optional[datetime]:
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _headers_dict(headers: list[dict]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in headers}


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


def _iter_mime_parts(payload: dict):
    """Yields a MIME part and all of its nested sub-parts, depth-first."""
    if not payload:
        return
    yield payload
    for child in (payload.get("parts") or []):
        yield from _iter_mime_parts(child)


def _extract_email_body_text(service, msg_id: str, payload: dict) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in _iter_mime_parts(payload):
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


def _build_result_row(
        *,
        document_type: str,
        message_id: str,
        attachment_id: Optional[str],
        subject: Optional[str],
        sender: Optional[str],
        msg_date: Optional[datetime],
        out_path: Path,
        category: Optional[str],
        amount_value,
        amount_currency,
        due_date_iso,
) -> dict:
    return {
        "document_type": document_type,
        "message_id": message_id,
        "attachment_id": attachment_id,
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


class GmailInvoiceFetcher:
    """Searches a Gmail account for invoice/receipt emails and saves the matching bills/receipts to disk."""

    def __init__(self, creds: Credentials):
        self.service = build("gmail", "v1", credentials=creds)
        self.bill_classifier = get_bill_receipt_general_classifier()

    def fetch(
            self,
            *,
            downloads_dir: Path,
            query: str,
            my_email: str,
            max_results: int = 20,
            time_window: Optional[str] = None,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None,
    ) -> List[dict]:
        downloads_dir.mkdir(parents=True, exist_ok=True)

        message_ids = self._search_message_ids(
            query=query,
            max_results=max_results,
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
        )

        results: List[dict] = []
        for message_id in message_ids:
            results.extend(self._process_message(message_id, my_email, downloads_dir))

        return results

    # ---- message discovery ----

    def _search_message_ids(
            self,
            *,
            query: str,
            max_results: int,
            time_window: Optional[str],
            start_date: Optional[datetime],
            end_date: Optional[datetime],
    ) -> List[str]:
        q = self._build_search_query(query, time_window, start_date, end_date)
        page_size = max(1, min(int(max_results or 20), 500))

        message_ids: List[str] = []
        page_token: Optional[str] = None

        while True:
            list_kwargs = {"userId": "me", "q": q, "maxResults": page_size}
            if page_token:
                list_kwargs["pageToken"] = page_token

            resp = self.service.users().messages().list(**list_kwargs).execute()
            message_ids.extend(m["id"] for m in (resp.get("messages", []) or []))

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return message_ids

    @staticmethod
    def _build_search_query(
            query: str,
            time_window: Optional[str],
            start_date: Optional[datetime],
            end_date: Optional[datetime],
    ) -> str:
        if start_date and end_date:
            after = start_date.strftime("%Y/%m/%d")
            before = (end_date + timedelta(days=1)).strftime("%Y/%m/%d")
            return f"{query} after:{after} before:{before}"

        if time_window:
            return f"{query} newer_than:{time_window}"

        return query

    # ---- per-message processing ----

    def _load_full_message(self, message_id: str) -> dict:
        return self.service.users().messages().get(userId="me", id=message_id, format="full").execute()

    def _user_has_replied(self, thread_id: str, my_email: str) -> bool:
        thread = self.service.users().threads().get(
            userId="me",
            id=thread_id,
            format="metadata",
            metadataHeaders=["From"],
        ).execute()

        my_email = my_email.lower()

        for msg in thread.get("messages", []):
            headers = _headers_dict(msg.get("payload", {}).get("headers", []))
            sender = (headers.get("from") or "").lower()
            if my_email in sender:
                return True

        return False

    def _process_message(self, message_id: str, my_email: str, downloads_dir: Path) -> List[dict]:
        full = self._load_full_message(message_id)

        if self._user_has_replied(full["threadId"], my_email):
            return []

        headers = _headers_dict(full.get("payload", {}).get("headers", []))
        subject = headers.get("subject")
        sender = headers.get("from")
        date_raw = headers.get("date")
        msg_date = _parse_rfc2822_date(date_raw) if date_raw else None

        payload = full.get("payload", {})
        email_body_text = _extract_email_body_text(self.service, message_id, payload)
        body_analysis = analyze_text(email_body_text, source_label=f"email body {message_id}")

        pdf_results = self._process_pdf_attachments(
            message_id=message_id,
            payload=payload,
            subject=subject,
            sender=sender,
            msg_date=msg_date,
            body_analysis=body_analysis,
            downloads_dir=downloads_dir,
        )

        # If at least one PDF attachment produced a financial document, that's the
        # source of truth for this message — don't also fall back to the body text.
        if pdf_results:
            return pdf_results

        body_result = self._process_body_fallback(
            message_id=message_id,
            subject=subject,
            sender=sender,
            msg_date=msg_date,
            email_body_text=email_body_text,
            body_analysis=body_analysis,
            downloads_dir=downloads_dir,
        )
        return [body_result] if body_result else []

    # ---- PDF attachment path ----

    @staticmethod
    def _find_pdf_parts(payload: dict) -> List[tuple]:
        pdf_parts = []

        for part in _iter_mime_parts(payload):
            filename = part.get("filename") or ""
            body = part.get("body") or {}
            att_id = body.get("attachmentId")
            mime = part.get("mimeType") or ""

            is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")
            if is_pdf and att_id:
                pdf_parts.append((filename, att_id))

        return pdf_parts

    def _process_pdf_attachments(
            self,
            *,
            message_id: str,
            payload: dict,
            subject: Optional[str],
            sender: Optional[str],
            msg_date: Optional[datetime],
            body_analysis: dict,
            downloads_dir: Path,
    ) -> List[dict]:
        results = []

        for filename, att_id in self._find_pdf_parts(payload):
            result = self._process_pdf_attachment(
                message_id=message_id,
                att_id=att_id,
                filename=filename,
                subject=subject,
                sender=sender,
                msg_date=msg_date,
                body_analysis=body_analysis,
                downloads_dir=downloads_dir,
            )
            if result:
                results.append(result)

        return results

    def _process_pdf_attachment(
            self,
            *,
            message_id: str,
            att_id: str,
            filename: str,
            subject: Optional[str],
            sender: Optional[str],
            msg_date: Optional[datetime],
            body_analysis: dict,
            downloads_dir: Path,
    ) -> Optional[dict]:
        att = self.service.users().messages().attachments().get(
            userId="me",
            messageId=message_id,
            id=att_id,
        ).execute()

        data = att.get("data")
        if not data:
            return None

        file_bytes = base64.urlsafe_b64decode(data.encode("utf-8"))
        safe = safe_filename(filename or f"{message_id}.pdf", fallback="file.pdf")
        out_path = make_unique_path(downloads_dir / safe)
        out_path.write_bytes(file_bytes)

        prediction, _ = self.bill_classifier.classify_file(out_path, subject=subject)
        if prediction not in ("bill", "receipt"):
            return None
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
            return None

        category = classify_category(subject, sender, out_path.name)

        return _build_result_row(
            document_type=document_type,
            message_id=message_id,
            attachment_id=att_id,
            subject=subject,
            sender=sender,
            msg_date=msg_date,
            out_path=out_path,
            category=category,
            amount_value=amount_value,
            amount_currency=amount_currency,
            due_date_iso=due_date_iso,
        )

    # ---- body-text fallback path (no usable PDF attachment) ----

    def _process_body_fallback(
            self,
            *,
            message_id: str,
            subject: Optional[str],
            sender: Optional[str],
            msg_date: Optional[datetime],
            email_body_text: str,
            body_analysis: dict,
            downloads_dir: Path,
    ) -> Optional[dict]:
        prediction, _ = self.bill_classifier.classify_text(email_body_text or "", subject=subject)
        if prediction not in ("bill", "receipt"):
            return None
        document_type = prediction.lower().strip()

        logger.debug("body fallback prediction: %s", document_type)

        if body_analysis.get("amount_value") is None:
            return None

        safe = safe_filename(f"{message_id}_body.txt", fallback="file.pdf")
        out_path = make_unique_path(downloads_dir / safe)
        out_path.write_text(email_body_text or "", encoding="utf-8")

        category = classify_category(subject, sender, out_path.name)

        return _build_result_row(
            document_type=document_type,
            message_id=message_id,
            attachment_id=None,
            subject=subject,
            sender=sender,
            msg_date=msg_date,
            out_path=out_path,
            category=category,
            amount_value=body_analysis.get("amount_value"),
            amount_currency=body_analysis.get("amount_currency"),
            due_date_iso=body_analysis.get("due_date_iso"),
        )
