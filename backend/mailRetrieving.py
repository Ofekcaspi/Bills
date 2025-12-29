from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from email import message_from_bytes
import base64
import os
import re


class MailRetrieving:
    def __init__(self):
        self.service = None
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]

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

    def _safe_filename(self, name: str) -> str:
        name = (name or "").strip()
        name = re.sub(r"[\\/:*?\"<>|]+", "_", name)  # Windows-safe
        return name[:180] if len(name) > 180 else name

    def _iter_parts(self, payload: dict):
        """Iterate recursively over all MIME parts."""
        stack = [payload]
        while stack:
            node = stack.pop()
            parts = node.get("parts", []) or []
            for p in parts:
                yield p
                if p.get("parts"):
                    stack.append(p)

    def _list_all_message_ids(self, query: str, user_id="me"):
        """Pagination: returns ALL message ids matching query."""
        if self.service is None:
            raise RuntimeError("Call connect() first")

        ids = []
        page_token = None

        while True:
            res = self.service.users().messages().list(
                userId=user_id,
                q=query,
                maxResults=500,
                pageToken=page_token
            ).execute()

            msgs = res.get("messages", []) or []
            ids.extend([m["id"] for m in msgs])

            page_token = res.get("nextPageToken")
            if not page_token:
                break

        return ids

    def build_receipts_query(self, time_window=None):
        base_query = (
            f'has:attachment '
            f'(subject:חשבונית OR subject:קבלה OR subject:invoice OR subject:receipt OR '
            f'"  OR החשבון  חשבונית מס" OR "Tax Invoice" OR "Receipt")'
        )
        if time_window:
            base_query = f"{base_query} newer_than:{time_window}"
        return base_query

    def download_all_receipt_attachments(
            self,
            time_window="6m",
            out_dir="downloads_invoices",
            user_id="me",
            only_pdf_and_images=True
    ):
        """
        מוריד את כל המצורפים מכל מיילי החשבוניות בחלון הזמן הנתון.
        מחזיר סיכום: (emails_found, emails_with_files, files_downloaded, out_dir)
        """
        if self.service is None:
            raise RuntimeError("Call connect() first")

        query = self.build_receipts_query(time_window=time_window)
        message_ids = self._list_all_message_ids(query=query, user_id=user_id)

        os.makedirs(out_dir, exist_ok=True)

        emails_with_files = 0
        files_downloaded = 0

        for idx, mid in enumerate(message_ids, start=1):
            # Fetch full message to access attachment metadata (parts + attachmentId)
            msg = self.service.users().messages().get(
                userId=user_id,
                id=mid,
                format="full"
            ).execute()

            payload = msg.get("payload", {}) or {}
            found_any_in_email = False

            for part in self._iter_parts(payload):
                filename = part.get("filename") or ""
                body = part.get("body", {}) or {}
                attachment_id = body.get("attachmentId")

                if not filename or not attachment_id:
                    continue

                filename_lower = filename.lower()
                if only_pdf_and_images:
                    if not filename_lower.endswith((".pdf", ".png", ".jpg", ".jpeg")):
                        continue

                # Download attachment bytes
                att = self.service.users().messages().attachments().get(
                    userId=user_id,
                    messageId=mid,
                    id=attachment_id
                ).execute()

                data = att.get("data")
                if not data:
                    continue

                file_bytes = base64.urlsafe_b64decode(data.encode("utf-8"))

                # Save under a folder per message_id
                msg_dir = os.path.join(out_dir, mid)
                os.makedirs(msg_dir, exist_ok=True)

                out_path = os.path.join(msg_dir, self._safe_filename(filename))
                with open(out_path, "wb") as f:
                    f.write(file_bytes)

                found_any_in_email = True
                files_downloaded += 1

            if found_any_in_email:
                emails_with_files += 1

            # progress every 25
            if idx % 25 == 0:
                print(f"Progress: {idx}/{len(message_ids)} | files downloaded: {files_downloaded}")

        return len(message_ids), emails_with_files, files_downloaded, os.path.abspath(out_dir)

    # optional: keep your previous raw-email fetch
    def get_emails(self, query=None, time_window=None, max_results=10, user_id="me"):
        if self.service is None:
            raise RuntimeError("Call connect() first")

        if query is None:
            query = self.build_receipts_query(time_window=time_window)
        elif time_window:
            query = f"{query} newer_than:{time_window}"

        res = self.service.users().messages().list(
            userId=user_id,
            q=query,
            maxResults=max_results
        ).execute()

        msgs = res.get("messages", []) or []
        emails = []

        for m in msgs:
            data = self.service.users().messages().get(
                userId=user_id,
                id=m["id"],
                format="raw"
            ).execute()

            raw = data.get("raw")
            if not raw:
                continue

            decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
            emails.append(message_from_bytes(decoded))

        return emails


def main():
    mr = MailRetrieving()
    mr.connect(token_path="token.json", credentials_path="credentials.json")

    TIME_WINDOW = "6m"  # last 6 months
    OUT_DIR = "invoices_last_6_months"

    print(f"Downloading all receipt attachments for last {TIME_WINDOW}...")
    emails_found, emails_with_files, files_downloaded, folder = mr.download_all_receipt_attachments(
        time_window=TIME_WINDOW,
        out_dir=OUT_DIR,
        only_pdf_and_images=True
    )

    print("\n=== SUMMARY ===")
    print(f"Emails matched query   : {emails_found}")
    print(f"Emails with files      : {emails_with_files}")
    print(f"Files downloaded       : {files_downloaded}")
    print(f"Saved to folder        : {folder}")


if __name__ == "__main__":
    main()
