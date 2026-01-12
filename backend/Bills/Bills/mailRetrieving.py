from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from django.utils import timezone

from .models import Attachment, Bill


class MailRetrieving:
    """
    Gmail -> download attachments -> save Attachment rows (and optionally Bill rows).
    Django ORM version, aligned to your models.py.
    """

    def __init__(self, downloads_dir: Path):
        self.service = None
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    # ---------- auth ----------
    def connect(self, token_path: str = "token.json", credentials_path: str = "credentials.json"):
        creds = None

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, self.scopes)

        if not creds or not creds.valid:
            refreshed = False
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    refreshed = True
                except Exception:
                    refreshed = False

            if not refreshed:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, self.scopes)
                creds = flow.run_local_server(port=0, prompt="consent")

            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)

    # ---------- helpers ----------
    def _safe_filename(self, name: str) -> str:
        name = (name or "").strip()
        name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name[:180] if len(name) > 180 else name

    def _iter_parts(self, payload: dict):
        stack = [payload]
        while stack:
            node = stack.pop()
            for p in (node.get("parts") or []):
                yield p
                if p.get("parts"):
                    stack.append(p)

    def _headers_map(self, payload: dict) -> Dict[str, str]:
        headers = payload.get("headers", []) or []
        return {h.get("name", "").lower(): h.get("value", "") for h in headers if h.get("name")}

    def _list_all_message_ids(self, query: str, user_id: str = "me") -> List[str]:
        if self.service is None:
            raise RuntimeError("Call connect() first")

        ids: List[str] = []
        page_token = None
        while True:
            res = self.service.users().messages().list(
                userId=user_id, q=query, maxResults=500, pageToken=page_token
            ).execute()

            msgs = res.get("messages", []) or []
            ids.extend([m["id"] for m in msgs])

            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return ids

    def build_receipts_query(self, time_window: Optional[str] = None) -> str:
        base_query = (
            'has:attachment '
            '(subject:חשבונית OR subject:קבלה OR subject:invoice OR subject:receipt OR '
            '"Tax Invoice" OR "Receipt")'
        )
        if time_window:
            base_query = f"{base_query} newer_than:{time_window}"
        return base_query

    def _infer_category(self, subject: str) -> str:
        s = (subject or "").lower()
        if "receipt" in s or "קבלה" in s:
            return "receipt"
        if "invoice" in s or "חשבונית" in s or "tax invoice" in s:
            return "invoice"
        return "unknown"

    def _sha256(self, b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    def _dated_rel_path(self, safe_filename: str) -> str:
        # downloads/<YYYY>/<MM>/<filename>
        now = timezone.now()
        return f"{now.year:04d}/{now.month:02d}/{safe_filename}"

    def _download_attachment_bytes(self, user_id: str, message_id: str, attachment_id: str) -> Optional[bytes]:
        att = self.service.users().messages().attachments().get(
            userId=user_id, messageId=message_id, id=attachment_id
        ).execute()
        data = att.get("data")
        if not data:
            return None
        return base64.urlsafe_b64decode(data.encode("utf-8"))

    # ---------- main ----------
    def pull_attachments_to_db(
            self,
            time_window: str = "6m",
            user_id: str = "me",
            only_pdf_and_images: bool = True,
            create_bill_mirror: bool = True,
    ) -> dict:
        """
        For every matching email attachment:
        - download file
        - compute sha256 -> Attachment.file_hash (unique)
        - save file under downloads/<YYYY>/<MM>/<filename>
        - create/update Attachment row
        - optionally create/update Bill row (mirror summary)
        """
        if self.service is None:
            raise RuntimeError("Call connect() first")

        query = self.build_receipts_query(time_window=time_window)
        message_ids = self._list_all_message_ids(query=query, user_id=user_id)

        emails_with_files = 0
        files_saved = 0
        attachments_upserted = 0
        bills_upserted = 0

        for mid in message_ids:
            msg = self.service.users().messages().get(userId=user_id, id=mid, format="full").execute()
            payload = msg.get("payload", {}) or {}
            headers = self._headers_map(payload)

            subject = headers.get("subject", "")
            sender = headers.get("from", "")
            msg_date = headers.get("date", "")
            category = self._infer_category(subject)

            found_any_in_email = False

            for part in self._iter_parts(payload):
                filename = part.get("filename") or ""
                body = part.get("body", {}) or {}
                attachment_id = body.get("attachmentId")
                mime_type = part.get("mimeType") or ""

                if not filename or not attachment_id:
                    continue

                if only_pdf_and_images:
                    fl = filename.lower()
                    if not fl.endswith((".pdf", ".png", ".jpg", ".jpeg")):
                        continue

                safe_name = self._safe_filename(filename)

                file_bytes = self._download_attachment_bytes(user_id=user_id, message_id=mid, attachment_id=attachment_id)
                if not file_bytes:
                    continue

                file_hash = self._sha256(file_bytes)

                # If already exists, skip re-writing file unless no saved_path yet
                existing = Attachment.objects.filter(file_hash=file_hash).first()
                if existing and existing.saved_path:
                    # still useful to update metadata if missing, but keep it minimal
                    Attachment.objects.filter(pk=existing.pk).update(
                        subject=existing.subject or subject,
                        sender=existing.sender or sender,
                        msg_date=existing.msg_date or msg_date,
                        snippet=existing.snippet or (msg.get("snippet") or ""),
                        category=existing.category or category,
                        mime_type=existing.mime_type or mime_type,
                        message_id=existing.message_id or mid,
                        attachment_id=existing.attachment_id or attachment_id,
                        thread_id=existing.thread_id or msg.get("threadId"),
                    )
                    found_any_in_email = True
                    continue

                rel_path = self._dated_rel_path(safe_name)
                out_path = self.downloads_dir / rel_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(file_bytes)
                files_saved += 1

                snippet = msg.get("snippet") or ""

                # Upsert Attachment
                att_obj, created = Attachment.objects.update_or_create(
                    file_hash=file_hash,
                    defaults=dict(
                        message_id=mid,
                        attachment_id=attachment_id,
                        thread_id=msg.get("threadId"),
                        subject=subject,
                        sender=sender,
                        msg_date=msg_date,
                        snippet=snippet,
                        filename=safe_name,
                        category=category,
                        mime_type=mime_type,
                        saved_path=rel_path,   # relative under downloads/
                        extracted_text_len=0,
                        # amount_* and due_date_* stay null until you parse OCR/text
                    ),
                )
                attachments_upserted += 1
                found_any_in_email = True

                # Optional: mirror into Bill
                if create_bill_mirror:
                    bill_obj, _ = Bill.objects.update_or_create(
                        saved_path=rel_path,  # nice natural key in your Bill model
                        defaults=dict(
                            category=category,
                            subject=subject,
                            sender=sender,
                            filename=safe_name,
                            amount_value=att_obj.amount_value,
                            amount_currency=att_obj.amount_currency,
                            due_date_iso=att_obj.due_date_iso,
                        ),
                    )
                    bills_upserted += 1

            if found_any_in_email:
                emails_with_files += 1

        return {
            "emails_matched": len(message_ids),
            "emails_with_files": emails_with_files,
            "files_saved": files_saved,
            "attachments_upserted": attachments_upserted,
            "bills_upserted": bills_upserted,
            "downloads_dir": str(self.downloads_dir.resolve()),
        }
