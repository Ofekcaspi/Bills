from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Optional, List, Dict

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from sqlmodel import Session, select

from models import Bill


class MailRetrieving:
    def __init__(self, session: Session, downloads_dir: Path):
        self.service = None
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        self.session = session
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def connect(self, token_path="token.json", credentials_path="credentials.json"):
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
        name = re.sub(r"[\\/:*?\"<>|]+", "_", name)  # Windows-safe
        return name[:180] if len(name) > 180 else name

    def _iter_parts(self, payload: dict):
        stack = [payload]
        while stack:
            node = stack.pop()
            parts = node.get("parts", []) or []
            for p in parts:
                yield p
                if p.get("parts"):
                    stack.append(p)

    def _list_all_message_ids(self, query: str, user_id="me") -> List[str]:
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

    def _headers_map(self, payload: dict) -> Dict[str, str]:
        headers = payload.get("headers", []) or []
        return {h.get("name", "").lower(): h.get("value", "") for h in headers if h.get("name")}

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

    def _bill_exists(self, message_id: str, filename: str) -> bool:
        stmt = select(Bill.id).where(Bill.message_id == message_id, Bill.filename == filename)
        return self.session.exec(stmt).first() is not None

    # ---------- main ----------
    def pull_bills_to_db(
            self,
            time_window: str = "6m",
            user_id: str = "me",
            only_pdf_and_images: bool = True,
    ) -> dict:
        """
        For every matching email attachment:
        1) download file into downloads/<message_id>/<filename>
        2) insert a Bill row into bills table (one row per file)
        """
        if self.service is None:
            raise RuntimeError("Call connect() first")

        query = self.build_receipts_query(time_window=time_window)
        message_ids = self._list_all_message_ids(query=query, user_id=user_id)

        emails_with_files = 0
        files_saved = 0
        rows_inserted = 0

        for idx, mid in enumerate(message_ids, start=1):
            msg = self.service.users().messages().get(
                userId=user_id, id=mid, format="full"
            ).execute()

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

                filename_lower = filename.lower()
                if only_pdf_and_images and not filename_lower.endswith((".pdf", ".png", ".jpg", ".jpeg")):
                    continue

                safe_name = self._safe_filename(filename)

                # Dedup: same email + same filename
                if self._bill_exists(mid, safe_name):
                    continue

                att = self.service.users().messages().attachments().get(
                    userId=user_id, messageId=mid, id=attachment_id
                ).execute()

                data = att.get("data")
                if not data:
                    continue

                file_bytes = base64.urlsafe_b64decode(data.encode("utf-8"))

                # Save file under downloads/<message_id>/<filename>
                msg_dir = self.downloads_dir / mid
                msg_dir.mkdir(parents=True, exist_ok=True)

                out_path = msg_dir / safe_name
                out_path.write_bytes(file_bytes)

                # saved_path should be relative to downloads/ for /files/{relative_path}
                saved_path = out_path.relative_to(self.downloads_dir).as_posix()

                # Insert Bill row
                bill = Bill(
                    message_id=mid,
                    attachment_id=attachment_id,
                    subject=subject,
                    sender=sender,
                    msg_date=msg_date,
                    filename=safe_name,
                    mime_type=mime_type,
                    saved_path=saved_path,
                    category=category,
                )
                self.session.add(bill)

                found_any_in_email = True
                files_saved += 1
                rows_inserted += 1

            if found_any_in_email:
                emails_with_files += 1

            # commit every email (simple + safe)
            self.session.commit()

            if idx % 25 == 0:
                print(f"Progress: {idx}/{len(message_ids)} | rows inserted: {rows_inserted} | files saved: {files_saved}")

        return {
            "emails_matched": len(message_ids),
            "emails_with_files": emails_with_files,
            "files_saved": files_saved,
            "rows_inserted": rows_inserted,
            "downloads_dir": str(self.downloads_dir.resolve()),
        }
