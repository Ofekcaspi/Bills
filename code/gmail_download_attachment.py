import os
import re
import base64
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailInvoiceDownloader:
    def __init__(self, credentials_path: str, download_root: str = "downloads"):
        self.credentials_path = credentials_path
        self.download_root = Path(download_root)
        self.service = None

    # -----------------------------
    # Connect
    # -----------------------------
    def connect(self) -> None:
        print("מכין תהליך התחברות ל-Google (OAuth2)...")
        print("עכשיו ייפתח חלון בדפדפן לבחירת משתמש גוגל ואישור הרשאות.\n")

        flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")

        print("ההתחברות הצליחה! בונה אובייקט שירות של Gmail API...\n")
        self.service = build("gmail", "v1", credentials=creds)

    # -----------------------------
    # Gmail helpers
    # -----------------------------
    @staticmethod
    def _safe_filename(name: str) -> str:
        # משאיר אותיות/ספרות/נקודות/קווים/רווחים, ממיר השאר ל "_"
        name = name.strip()
        name = re.sub(r"[^\w\-. ()\[\]]+", "_", name)
        return name or "attachment"

    @staticmethod
    def _get_headers_map(message: Dict) -> Dict[str, str]:
        headers = message.get("payload", {}).get("headers", []) or []
        hmap = {}
        for h in headers:
            n = (h.get("name") or "").lower()
            v = h.get("value") or ""
            if n:
                hmap[n] = v
        return hmap

    @staticmethod
    def _collect_attachment_parts(payload: Dict) -> List[Tuple[str, str]]:
        """
        מחזיר רשימה של (filename, attachmentId) כולל מבנים מקוננים (multipart).
        """
        found = []
        if not payload:
            return found

        parts = payload.get("parts", []) or []
        for part in parts:
            filename = part.get("filename") or ""
            body = part.get("body", {}) or {}
            attachment_id = body.get("attachmentId")

            if filename and attachment_id:
                found.append((filename, attachment_id))

            # recurse nested parts
            if part.get("parts"):
                found.extend(GmailInvoiceDownloader._collect_attachment_parts(part))

        return found

    # -----------------------------
    # Classification (initial rules)
    # -----------------------------
    @staticmethod
    def classify(subject: str, sender: str, snippet: str) -> str:
        """
        סיווג ראשוני לפי טקסט קצר: subject + from + snippet
        """
        s = f"{subject} {sender} {snippet}".lower()

        # חשמל
        if any(k in s for k in ["חברת חשמל", "electric", "electricity", "iec", "חח\"י", "חח״י"]):
            return "חשמל"

        # מים
        if any(k in s for k in ["מים", "תאגיד מים", "water", "mei", "מי "]):
            return "מים"

        # ארנונה / עירייה
        if any(k in s for k in ["ארנונה", "עירייה", "municipality", "עירית", "עיריית"]):
            return "ארנונה"

        # גז
        if any(k in s for k in ["גז", "gas", "אמישראגז", "פזגז", "סופרגז"]):
            return "גז"

        # ביטוח
        if any(k in s for k in ["ביטוח", "insurance", "policy", "פוליסה"]):
            return "ביטוח"

        # תקשורת: אינטרנט/סלולר/טלוויזיה
        if any(k in s for k in ["סלקום", "פרטנר", "פלאפון", "הוט", "yes", "בזק", "internet", "mobile", "cellular"]):
            return "תקשורת"

        # מנויים
        if any(k in s for k in ["subscription", "מנוי", "membership", "renewal", "חיוב חודשי"]):
            return "מנויים"

        # כללי: חשבונית/קבלה
        if any(k in s for k in ["חשבונית", "קבלה", "invoice", "receipt", "tax invoice"]):
            return "חשבוניות-כללי"

        return "אחר"

    # -----------------------------
    # Downloading
    # -----------------------------
    def _download_all_attachments_from_message(self, message_id: str, category: str) -> List[Path]:
        """
        מוריד את כל הקבצים המצורפים ממייל אחד לתיקיית הקטגוריה.
        """
        msg = self.service.users().messages().get(userId="me", id=message_id).execute()

        out_dir = self.download_root / category
        out_dir.mkdir(parents=True, exist_ok=True)

        attachments = self._collect_attachment_parts(msg.get("payload", {}))
        if not attachments:
            return []

        saved_paths: List[Path] = []
        for filename, attachment_id in attachments:
            att = self.service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=attachment_id
            ).execute()

            file_bytes = base64.urlsafe_b64decode(att["data"].encode("UTF-8"))

            safe_name = self._safe_filename(filename)
            unique_suffix = hashlib.sha256((message_id + attachment_id).encode()).hexdigest()[:10]
            name, ext = os.path.splitext(safe_name)
            out_name = f"{name}_{unique_suffix}{ext}" if ext else f"{name}_{unique_suffix}"
            out_path = out_dir / out_name

            with open(out_path, "wb") as f:
                f.write(file_bytes)

            saved_paths.append(out_path)

        return saved_paths

    # -----------------------------
    # Main flow with pagination
    # -----------------------------
    def download_from_query(self, query: str, max_per_page: int = 100, limit_messages: Optional[int] = None) -> None:
        """
        משלב Pagination + הורדת כל attachments + סיווג ראשוני.
        limit_messages: אם תרצה להגביל (למשל 200) – אחרת None יוריד הכל לפי query.
        """
        if not self.service:
            raise RuntimeError("Service not connected. Call connect() first.")

        print(f"🔎 Query: {query}")
        page_token = None
        total_msgs = 0
        total_files = 0

        while True:
            resp = self.service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_per_page,
                pageToken=page_token
            ).execute()

            msgs = resp.get("messages", []) or []
            if not msgs and not page_token:
                break

            for m in msgs:
                if limit_messages is not None and total_msgs >= limit_messages:
                    print(f"⛔ הגעת להגבלת הודעות: {limit_messages}")
                    print(f"✅ סה\"כ הודעות שטופלו: {total_msgs}, סה\"כ קבצים שהורדו: {total_files}")
                    return

                message_id = m["id"]
                msg_full = self.service.users().messages().get(userId="me", id=message_id).execute()

                headers = self._get_headers_map(msg_full)
                subject = headers.get("subject", "")
                sender = headers.get("from", "")
                snippet = msg_full.get("snippet", "")

                category = self.classify(subject, sender, snippet)

                paths = self._download_all_attachments_from_message(message_id, category)
                total_msgs += 1
                total_files += len(paths)

                if paths:
                    print(f"📩 {total_msgs}. {category} | {subject[:60]} | files: {len(paths)}")
                else:
                    # יש מיילים עם has:attachment אבל לפעמים אין filename/attachmentId רגיל
                    print(f"📩 {total_msgs}. {category} | {subject[:60]} | files: 0 (ייתכן inline/מבנה לא סטנדרטי)")

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        print(f"\n✅ סיום. סה\"כ הודעות שטופלו: {total_msgs}, סה\"כ קבצים שהורדו: {total_files}")
        print(f"📁 נשמרו בתיקייה: {self.download_root.resolve()}")


def main():
    downloader = GmailInvoiceDownloader(
        credentials_path="../old be/credentials.json",
        download_root="downloads"
    )
    downloader.connect()

    # דוגמה ל-query חכם יותר (מומלץ):
    query = (
        'has:attachment newer_than:365d '
        '(subject:חשבונית OR subject:קבלה OR subject:invoice OR subject:receipt OR "Tax Invoice" OR "Receipt")'
    )

    downloader.download_from_query(query=query, max_per_page=100, limit_messages=None)


if __name__ == "__main__":
    main()
