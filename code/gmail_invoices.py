import os
import re
import base64
import hashlib
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import pdfplumber

# OCR deps
import pytesseract
from pdf2image import convert_from_path

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# =========================
# DB (SQLite) - Dedup + Metadata + Amount/DueDate
# =========================
class AttachmentDB:
    def __init__(self, db_path: str = "attachments.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._init_tables()

    def _init_tables(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE,

                message_id TEXT,
                attachment_id TEXT,
                thread_id TEXT,

                subject TEXT,
                sender TEXT,
                msg_date TEXT,
                snippet TEXT,

                filename TEXT,
                category TEXT,
                mime_type TEXT,
                saved_path TEXT,

                extracted_text_len INTEGER,

                amount_value REAL,
                amount_currency TEXT,
                amount_source TEXT,

                due_date_iso TEXT,
                due_date_source TEXT,

                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_message_id ON attachments(message_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_category ON attachments(category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_due_date ON attachments(due_date_iso)")
        self.conn.commit()

    def exists_hash(self, file_hash: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM attachments WHERE file_hash = ? LIMIT 1", (file_hash,))
        return cur.fetchone() is not None

    def insert(
            self,
            *,
            file_hash: str,
            message_id: str,
            attachment_id: str,
            thread_id: str,
            subject: str,
            sender: str,
            msg_date: str,
            snippet: str,
            filename: str,
            category: str,
            mime_type: str,
            saved_path: str,
            extracted_text_len: int,
            amount_value: Optional[float],
            amount_currency: Optional[str],
            amount_source: Optional[str],
            due_date_iso: Optional[str],
            due_date_source: Optional[str],
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO attachments
            (file_hash, message_id, attachment_id, thread_id, subject, sender, msg_date, snippet,
             filename, category, mime_type, saved_path, extracted_text_len,
             amount_value, amount_currency, amount_source,
             due_date_iso, due_date_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_hash, message_id, attachment_id, thread_id,
                subject, sender, msg_date, snippet,
                filename, category, mime_type, saved_path, extracted_text_len,
                amount_value, amount_currency, amount_source,
                due_date_iso, due_date_source
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# =========================
# Gmail Downloader + Extract + Classify + Parse Amount/DueDate
# =========================
class GmailInvoiceDownloader:
    def __init__(
            self,
            credentials_path: str,
            download_root: str = "downloads",
            tesseract_cmd: Optional[str] = None,  # ב-Windows: r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    ):
        self.credentials_path = credentials_path
        self.download_root = Path(download_root)
        self.service = None

        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def connect(self) -> None:
        print("מכין תהליך התחברות ל-Google (OAuth2)...")
        print("עכשיו ייפתח חלון בדפדפן לבחירת משתמש גוגל ואישור הרשאות.\n")

        flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")

        print("ההתחברות הצליחה! בונה אובייקט שירות של Gmail API...\n")
        self.service = build("gmail", "v1", credentials=creds)

    # ---------- Helpers ----------
    @staticmethod
    def _sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _safe_filename(name: str) -> str:
        name = (name or "").strip()
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
    def _collect_attachment_parts(payload: Dict) -> List[Tuple[str, str, str]]:
        found: List[Tuple[str, str, str]] = []
        if not payload:
            return found

        parts = payload.get("parts", []) or []
        for part in parts:
            filename = part.get("filename") or ""
            mime_type = part.get("mimeType") or ""
            body = part.get("body", {}) or {}
            attachment_id = body.get("attachmentId")

            if filename and attachment_id:
                found.append((filename, attachment_id, mime_type))

            if part.get("parts"):
                found.extend(GmailInvoiceDownloader._collect_attachment_parts(part))

        return found

    # ---------- Text extraction ----------
    @staticmethod
    def extract_text_from_pdf(
            pdf_path: Path,
            *,
            ocr_lang: str = "heb+eng",
            ocr_max_pages: int = 10,
            digital_min_chars: int = 200,
            dpi: int = 250,
    ) -> str:
        text = ""

        # A) Digital
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                chunks = []
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    if t:
                        chunks.append(t)
                text = "\n".join(chunks).strip()
        except Exception:
            text = ""

        if len(text) >= digital_min_chars:
            return text

        # B) OCR fallback
        try:
            images = convert_from_path(str(pdf_path), dpi=dpi, first_page=1, last_page=ocr_max_pages)
            ocr_chunks = []
            for img in images:
                ocr_chunks.append(pytesseract.image_to_string(img, lang=ocr_lang))
            ocr_text = "\n".join(ocr_chunks).strip()
            if ocr_text:
                return (text + "\n" + ocr_text).strip() if text else ocr_text
        except Exception:
            pass

        return text

    # ---------- Classification ----------
    @staticmethod
    def classify(subject: str, sender: str, snippet: str, extracted_text: str) -> str:
        s = f"{subject} {sender} {snippet} {extracted_text}".lower()

        if any(k in s for k in ["חברת חשמל", "iec", "electricity", "electric", "תעריף חשמל"]):
            return "חשמל"
        if any(k in s for k in ["תאגיד מים", "מים", "water"]):
            return "מים"
        if any(k in s for k in ["ארנונה", "עירייה", "עירית", "עיריית", "municipality"]):
            return "ארנונה"
        if any(k in s for k in ["אמישראגז", "פזגז", "סופרגז", "גז", "gas"]):
            return "גז"
        if any(k in s for k in ["ביטוח", "insurance", "policy", "פוליסה", "פרמיה"]):
            return "ביטוח"
        if any(k in s for k in ["סלקום", "פרטנר", "פלאפון", "הוט", "yes", "בזק", "internet", "mobile", "סיבים"]):
            return "תקשורת"
        if any(k in s for k in ["ישראכרט", "max", "כאל", "visa", "mastercard", "פירוט עסקות", "דוח חיובים"]):
            return "אשראי/בנק"
        if any(k in s for k in ["subscription", "מנוי", "membership", "renewal", "חיוב חודשי"]):
            return "מנויים"
        if any(k in s for k in ["חשבונית", "קבלה", "invoice", "receipt", "tax invoice"]):
            return "חשבוניות-כללי"

        return "אחר"

    # ---------- Amount & Due date extraction ----------
    @staticmethod
    def _normalize_number(num_str: str) -> Optional[float]:
        """
        תומך ב:
        1,234.56
        1.234,56
        1234.56
        1234,56
        1 234,56
        """
        if not num_str:
            return None
        s = num_str.strip().replace(" ", "")

        # אם יש גם '.' וגם ',' נחליט מי דסימל לפי המופע האחרון
        if "." in s and "," in s:
            if s.rfind(",") > s.rfind("."):
                # 1.234,56 -> אלפים '.' דסימל ','
                s = s.replace(".", "").replace(",", ".")
            else:
                # 1,234.56 -> אלפים ',' דסימל '.'
                s = s.replace(",", "")
        else:
            # רק ',' -> נניח שזה דסימלי אם יש 1-2 ספרות אחרי
            if "," in s:
                parts = s.split(",")
                if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
                    s = s.replace(",", ".")
                else:
                    s = s.replace(",", "")
            # רק '.' -> נשאיר כרגיל (או נסיר אלפים אם יש יותר מנקודה אחת)
            if s.count(".") > 1:
                s = s.replace(".", "")

        try:
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def extract_amount_and_currency(text: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
        """
        מחזיר: (amount_value, currency, source_label)
        source_label מסביר מאיזה "סימן" חילצנו (לצורך Debug/הסבר).
        """
        if not text:
            return None, None, None

        t = " ".join(text.split())  # normalize spaces

        # מיפוי מטבע
        currency_patterns = [
            ("ILS", r"(₪|ש\"?ח|שח|nis\b|ils\b)"),
            ("USD", r"(\$|usd\b)"),
            ("EUR", r"(€|eur\b)"),
        ]

        # תבניות "סכום לתשלום" בעברית/אנגלית
        label_patterns = [
            ("amount_due", r"(סכום\s*לתשלום|לתשלום|סה\"?כ\s*לתשלום|total\s*due|amount\s*due|balance\s*due)"),
            ("total", r"(סה\"?כ|סך\s*הכל|total)"),
        ]

        # מספר כסף: 1,234.56 / 1.234,56 / 1234.56 / 1234,56
        money_number = r"(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})|\d+(?:[.,]\d{1,2})?)"

        candidates: List[Tuple[float, str, str]] = []

        # 1) קודם נחפש ליד תוויות (עד ~40 תווים אחרי)
        for label_name, lp in label_patterns:
            for m in re.finditer(lp, t, flags=re.IGNORECASE):
                window = t[m.end(): m.end() + 60]
                nm = re.search(money_number, window)
                if nm:
                    val = GmailInvoiceDownloader._normalize_number(nm.group(1))
                    if val is not None:
                        currency = None
                        # חפש מטבע בסביבה הקרובה (לפני/אחרי)
                        near = t[max(0, m.start() - 20): m.end() + 60]
                        for ccode, cp in currency_patterns:
                            if re.search(cp, near, flags=re.IGNORECASE):
                                currency = ccode
                                break
                        candidates.append((val, currency or "ILS", f"label:{label_name}"))

        # 2) אם לא מצאנו — fallback: “המספר הכי גדול” עם סימן מטבע באיזור
        if not candidates:
            for nm in re.finditer(money_number, t):
                val = GmailInvoiceDownloader._normalize_number(nm.group(1))
                if val is None:
                    continue
                near = t[max(0, nm.start() - 10): nm.end() + 10]
                currency = None
                for ccode, cp in currency_patterns:
                    if re.search(cp, near, flags=re.IGNORECASE):
                        currency = ccode
                        break
                # ניקח רק אם נראה שזה כסף (מטבע או גודל סביר)
                if currency or val > 10:
                    candidates.append((val, currency or "ILS", "fallback:max-number"))

        if not candidates:
            return None, None, None

        # ניקח את המועמד עם הערך הגבוה ביותר (ברוב החשבוניות ה-total הוא הגבוה)
        best = max(candidates, key=lambda x: x[0])
        return best[0], best[1], best[2]

    @staticmethod
    def extract_due_date_iso(text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        מחזיר (YYYY-MM-DD, source_label).
        תומך ב:
        - "לתשלום עד 31/01/2026"
        - "תאריך יעד: 31-01-2026"
        - "due date 2026-01-31"
        """
        if not text:
            return None, None

        t = " ".join(text.split()).lower()

        # מילות מפתח שמרמזות על תאריך יעד
        due_labels = [
            ("due", r"(לתשלום\s*עד|עד\s*תאריך|מועד\s*תשלום|תאריך\s*יעד|תשלום\s*עד|due\s*date|pay\s*by|payment\s*due)"),
        ]

        # פורמטים:
        # dd/mm/yyyy או dd-mm-yyyy
        dmy = r"(\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b)"
        # yyyy-mm-dd או yyyy/mm/dd
        ymd = r"(\b\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}\b)"

        def to_iso(date_str: str) -> Optional[str]:
            ds = date_str.strip()
            # ymd
            m = re.match(r"^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$", ds)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
                return None

            # dmy
            m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})$", ds)
            if m:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if y < 100:
                    y += 2000
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            return None

        # 1) נחפש תאריך ליד "תשלום עד"/"due date"
        for label_name, lp in due_labels:
            for m in re.finditer(lp, t):
                window = t[m.end(): m.end() + 80]
                dm = re.search(ymd, window) or re.search(dmy, window)
                if dm:
                    iso = to_iso(dm.group(1))
                    if iso:
                        return iso, f"label:{label_name}"

        # 2) fallback: אם יש ymd anywhere (בדרך כלל ברור יותר)
        all_ymd = re.findall(ymd, t)
        for ds in all_ymd:
            iso = to_iso(ds)
            if iso:
                return iso, "fallback:ymd"

        # 3) fallback: לקחת dmy האחרון (לפעמים יש כמה תאריכים; האחרון הוא יעד)
        all_dmy = re.findall(dmy, t)
        for ds in reversed(all_dmy):
            iso = to_iso(ds)
            if iso:
                return iso, "fallback:dmy-last"

        return None, None

    # ---------- Download ----------
    def _download_attachments_for_message(
            self,
            *,
            db: AttachmentDB,
            message_id: str,
            thread_id: str,
            subject: str,
            sender: str,
            msg_date: str,
            snippet: str,
            category_hint: str,
    ) -> List[Path]:
        msg = self.service.users().messages().get(userId="me", id=message_id).execute()
        attachments = self._collect_attachment_parts(msg.get("payload", {}))
        if not attachments:
            return []

        saved_paths: List[Path] = []

        for filename, attachment_id, mime_type in attachments:
            att = self.service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=attachment_id
            ).execute()

            file_bytes = base64.urlsafe_b64decode(att["data"].encode("UTF-8"))
            file_hash = self._sha256_bytes(file_bytes)

            if db.exists_hash(file_hash):
                print(f"⏭️ דילוג כפילות: {filename}")
                continue

            safe_name = self._safe_filename(filename)
            unique_suffix = hashlib.sha256((message_id + attachment_id).encode()).hexdigest()[:10]
            name, ext = os.path.splitext(safe_name)
            out_name = f"{name}_{unique_suffix}{ext}" if ext else f"{name}_{unique_suffix}"

            temp_dir = self.download_root / category_hint
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / out_name

            with open(out_path, "wb") as f:
                f.write(file_bytes)

            # חילוץ טקסט + סיווג משופר
            extracted_text = ""
            if ext.lower() == ".pdf":
                extracted_text = self.extract_text_from_pdf(
                    out_path,
                    ocr_lang="heb+eng",
                    ocr_max_pages=2,       # תוכל להעלות ל-5 אם צריך
                    digital_min_chars=200,
                    dpi=250,
                )

            final_category = self.classify(subject, sender, snippet, extracted_text)

            # חילוץ סכום ותאריך יעד מהטקסט
            amount_value, amount_currency, amount_source = self.extract_amount_and_currency(extracted_text)
            due_date_iso, due_date_source = self.extract_due_date_iso(extracted_text)

            # להעביר לתיקיית הקטגוריה הסופית
            if final_category != category_hint:
                final_dir = self.download_root / final_category
                final_dir.mkdir(parents=True, exist_ok=True)
                final_path = final_dir / out_name
                try:
                    out_path.replace(final_path)
                    out_path = final_path
                except Exception:
                    pass

            # רושמים ל-DB
            db.insert(
                file_hash=file_hash,
                message_id=message_id,
                attachment_id=attachment_id,
                thread_id=thread_id,
                subject=subject,
                sender=sender,
                msg_date=msg_date,
                snippet=snippet,
                filename=safe_name,
                category=final_category,
                mime_type=mime_type,
                saved_path=str(out_path),
                extracted_text_len=len(extracted_text),
                amount_value=amount_value,
                amount_currency=amount_currency,
                amount_source=amount_source,
                due_date_iso=due_date_iso,
                due_date_source=due_date_source,
            )

            print(
                f"✅ נשמר: {out_path} | "
                f"amount={amount_value} {amount_currency} ({amount_source}) | "
                f"due={due_date_iso} ({due_date_source})"
            )

            saved_paths.append(out_path)

        return saved_paths

    # ---------- Main flow ----------
    def download_from_query(
            self,
            *,
            db: AttachmentDB,
            query: str,
            max_per_page: int = 100,
            limit_messages: Optional[int] = None,
    ) -> None:
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
                pageToken=page_token,
            ).execute()

            msgs = resp.get("messages", []) or []

            for m in msgs:
                if limit_messages is not None and total_msgs >= limit_messages:
                    print(f"⛔ הגעת להגבלת הודעות: {limit_messages}")
                    print(f"✅ סה\"כ הודעות: {total_msgs} | סה\"כ קבצים: {total_files}")
                    return

                message_id = m["id"]
                msg_full = self.service.users().messages().get(userId="me", id=message_id).execute()

                headers = self._get_headers_map(msg_full)
                subject = headers.get("subject", "")
                sender = headers.get("from", "")
                msg_date = headers.get("date", "")
                snippet = msg_full.get("snippet", "")
                thread_id = msg_full.get("threadId", "")

                category_hint = self.classify(subject, sender, snippet, extracted_text="")

                paths = self._download_attachments_for_message(
                    db=db,
                    message_id=message_id,
                    thread_id=thread_id,
                    subject=subject,
                    sender=sender,
                    msg_date=msg_date,
                    snippet=snippet,
                    category_hint=category_hint,
                )

                total_msgs += 1
                total_files += len(paths)

                if not paths:
                    print(f"📩 {total_msgs}. {subject[:60]} | הורדו: 0 (ייתכן inline/מבנה לא סטנדרטי)")

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        print(f"\n✅ סיום. סה\"כ הודעות: {total_msgs} | סה\"כ קבצים שהורדו: {total_files}")
        print(f"📁 downloads: {self.download_root.resolve()}")
        print(f"🗄️ DB: {db.db_path.resolve()}")


def main():
    # אם אתה ב-Windows וזה לא מוצא Tesseract, תגדיר כאן:
    # tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    tesseract_path = None

    downloader = GmailInvoiceDownloader(
        credentials_path="../backend/credentials.json",  # עדכן נתיב אם צריך
        download_root="downloads",
        tesseract_cmd=tesseract_path,
    )
    downloader.connect()

    db = AttachmentDB("attachments.db")

    query = (
        'has:attachment newer_than:365d '
        '(subject:חשבונית OR subject:קבלה OR subject:invoice OR subject:receipt OR "Tax Invoice" OR "Receipt")'
    )

    downloader.download_from_query(
        db=db,
        query=query,
        max_per_page=100,
        limit_messages=None,  # אפשר לשים 200 לבדיקה
    )

    db.close()


if __name__ == "__main__":
    main()
