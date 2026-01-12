from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from django.db import transaction

from .models import Attachment, Bill


@dataclass(frozen=True)
class GmailFetchConfig:
    download_root: Path
    only_pdf_and_images: bool = True
    ocr_lang: str = "heb+eng"
    ocr_max_pages: int = 2
    digital_min_chars: int = 200
    dpi: int = 250
    tesseract_cmd: Optional[str] = None
    create_bill_mirror: bool = True  # create Bill rows too (optional)


class GmailInvoiceService:
    """
    Django-integrated Gmail fetcher:
    - Requires already-established OAuth token (Credentials) -> builds Gmail API service.
    - Downloads attachments -> classifies -> extracts amount/due date -> saves with Django ORM.
    """

    def __init__(self, *, creds: Credentials, config: GmailFetchConfig):
        self.config = config
        self.download_root = Path(config.download_root)
        self.download_root.mkdir(parents=True, exist_ok=True)

        if config.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = config.tesseract_cmd

        # Gmail API client from existing creds (NO browser / NO local_server)
        self.service = build("gmail", "v1", credentials=creds)

    # -------------------------
    # Query builder
    # -------------------------
    @staticmethod
    def build_default_query(time_window: str = "365d") -> str:
        return (
            f'has:attachment newer_than:{time_window} '
            '(subject:חשבונית OR subject:קבלה OR subject:invoice OR subject:receipt OR "Tax Invoice" OR "Receipt")'
        )

    # -------------------------
    # Helpers
    # -------------------------
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
        hmap: Dict[str, str] = {}
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
                found.extend(GmailInvoiceService._collect_attachment_parts(part))

        return found

    # -------------------------
    # Text extraction (PDF + OCR fallback)
    # -------------------------
    @staticmethod
    def extract_text_from_pdf(
            pdf_path: Path,
            *,
            ocr_lang: str,
            ocr_max_pages: int,
            digital_min_chars: int,
            dpi: int,
    ) -> str:
        text = ""

        # A) Digital text
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
            images = convert_from_path(
                str(pdf_path),
                dpi=dpi,
                first_page=1,
                last_page=ocr_max_pages,
            )
            ocr_chunks = []
            for img in images:
                ocr_chunks.append(pytesseract.image_to_string(img, lang=ocr_lang))
            ocr_text = "\n".join(ocr_chunks).strip()
            if ocr_text:
                return (text + "\n" + ocr_text).strip() if text else ocr_text
        except Exception:
            pass

        return text

    # -------------------------
    # Classification
    # -------------------------
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
        if any(k in s for k in ["ישראכרט", "max", "כאל", "visa", "mastercard", "פירוט עסקות", "דוח חיובים", "דוח חיובים"]):
            return "אשראי/בנק"
        if any(k in s for k in ["subscription", "מנוי", "membership", "renewal", "חיוב חודשי"]):
            return "מנויים"
        if any(k in s for k in ["חשבונית", "קבלה", "invoice", "receipt", "tax invoice"]):
            return "חשבוניות-כללי"

        return "אחר"

    # -------------------------
    # Amount parsing
    # -------------------------
    @staticmethod
    def _normalize_number(num_str: str) -> Optional[float]:
        if not num_str:
            return None
        s = num_str.strip().replace(" ", "")

        if "." in s and "," in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        else:
            if "," in s:
                parts = s.split(",")
                if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
                    s = s.replace(",", ".")
                else:
                    s = s.replace(",", "")
            if s.count(".") > 1:
                s = s.replace(".", "")

        try:
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def extract_amount_and_currency(text: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
        if not text:
            return None, None, None

        t = " ".join(text.split())

        currency_patterns = [
            ("ILS", r"(₪|ש\"?ח|שח|nis\b|ils\b)"),
            ("USD", r"(\$|usd\b)"),
            ("EUR", r"(€|eur\b)"),
        ]

        label_patterns = [
            ("amount_due", r"(סכום\s*לתשלום|לתשלום|סה\"?כ\s*לתשלום|total\s*due|amount\s*due|balance\s*due)"),
            ("total", r"(סה\"?כ|סך\s*הכל|total)"),
        ]

        money_number = r"(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})|\d+(?:[.,]\d{1,2})?)"
        candidates: List[Tuple[float, str, str]] = []

        for label_name, lp in label_patterns:
            for m in re.finditer(lp, t, flags=re.IGNORECASE):
                window = t[m.end(): m.end() + 60]
                nm = re.search(money_number, window)
                if nm:
                    val = GmailInvoiceService._normalize_number(nm.group(1))
                    if val is not None:
                        currency = None
                        near = t[max(0, m.start() - 20): m.end() + 60]
                        for ccode, cp in currency_patterns:
                            if re.search(cp, near, flags=re.IGNORECASE):
                                currency = ccode
                                break
                        candidates.append((val, currency or "ILS", f"label:{label_name}"))

        if not candidates:
            for nm in re.finditer(money_number, t):
                val = GmailInvoiceService._normalize_number(nm.group(1))
                if val is None:
                    continue
                near = t[max(0, nm.start() - 10): nm.end() + 10]
                currency = None
                for ccode, cp in currency_patterns:
                    if re.search(cp, near, flags=re.IGNORECASE):
                        currency = ccode
                        break
                if currency or val > 10:
                    candidates.append((val, currency or "ILS", "fallback:max-number"))

        if not candidates:
            return None, None, None

        best = max(candidates, key=lambda x: x[0])
        return best[0], best[1], best[2]

    # -------------------------
    # Due date parsing
    # -------------------------
    @staticmethod
    def extract_due_date_iso(text: str) -> Tuple[Optional[str], Optional[str]]:
        if not text:
            return None, None

        t = " ".join(text.split()).lower()

        due_labels = [
            ("due", r"(לתשלום\s*עד|עד\s*תאריך|מועד\s*תשלום|תאריך\s*יעד|תשלום\s*עד|due\s*date|pay\s*by|payment\s*due)"),
        ]

        dmy = r"(\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b)"
        ymd = r"(\b\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}\b)"

        def to_iso(date_str: str) -> Optional[str]:
            ds = date_str.strip()
            m = re.match(r"^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$", ds)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
                return None

            m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})$", ds)
            if m:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if y < 100:
                    y += 2000
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            return None

        for label_name, lp in due_labels:
            for m in re.finditer(lp, t):
                window = t[m.end(): m.end() + 80]
                dm = re.search(ymd, window) or re.search(dmy, window)
                if dm:
                    iso = to_iso(dm.group(1))
                    if iso:
                        return iso, f"label:{label_name}"

        all_ymd = re.findall(ymd, t)
        for ds in all_ymd:
            iso = to_iso(ds)
            if iso:
                return iso, "fallback:ymd"

        all_dmy = re.findall(dmy, t)
        for ds in reversed(all_dmy):
            iso = to_iso(ds)
            if iso:
                return iso, "fallback:dmy-last"

        return None, None

    # -------------------------
    # ORM utilities
    # -------------------------
    @staticmethod
    def _exists_hash(file_hash: str) -> bool:
        return Attachment.objects.filter(file_hash=file_hash).exists()

    @staticmethod
    def _upsert_attachment(
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
    ) -> Attachment:
        """
        Uses update_or_create to be idempotent and safe for re-runs.
        Unique key is file_hash (matches your model unique constraint).
        """
        obj, _created = Attachment.objects.update_or_create(
            file_hash=file_hash,
            defaults=dict(
                message_id=message_id,
                attachment_id=attachment_id,
                thread_id=thread_id,
                subject=subject,
                sender=sender,
                msg_date=msg_date,
                snippet=snippet,
                filename=filename,
                category=category,
                mime_type=mime_type,
                saved_path=saved_path,
                extracted_text_len=extracted_text_len,
                amount_value=amount_value,
                amount_currency=amount_currency,
                amount_source=amount_source,
                due_date_iso=due_date_iso,
                due_date_source=due_date_source,
            ),
        )
        return obj

    @staticmethod
    def _create_bill_mirror_if_enabled(*, enabled: bool, att: Attachment) -> None:
        if not enabled:
            return

        # Your Bill model is thinner; we mirror what fits.
        Bill.objects.create(
            category=att.category,
            subject=att.subject,
            sender=att.sender,
            filename=att.filename,
            amount_value=att.amount_value,
            amount_currency=att.amount_currency,
            due_date_iso=att.due_date_iso,
            saved_path=att.saved_path,  # should be relative
        )

    # -------------------------
    # Core download/save flow (used by views)
    # -------------------------
    def run_query(
            self,
            *,
            query: str,
            user_id: str = "me",
            max_per_page: int = 100,
            limit_messages: Optional[int] = None,
    ) -> dict:
        """
        Main entrypoint for a future get_emails view.
        Returns stats dict.
        """
        page_token = None
        total_msgs = 0
        total_files_saved = 0
        total_rows_upserted = 0
        total_skipped_duplicates = 0

        while True:
            resp = self.service.users().messages().list(
                userId=user_id,
                q=query,
                maxResults=max_per_page,
                pageToken=page_token,
            ).execute()

            msgs = resp.get("messages", []) or []

            for m in msgs:
                if limit_messages is not None and total_msgs >= limit_messages:
                    return {
                        "emails_processed": total_msgs,
                        "files_saved": total_files_saved,
                        "rows_upserted": total_rows_upserted,
                        "skipped_duplicates": total_skipped_duplicates,
                        "stopped_reason": "limit_messages",
                    }

                message_id = m["id"]
                msg_full = self.service.users().messages().get(userId=user_id, id=message_id).execute()

                headers = self._get_headers_map(msg_full)
                subject = headers.get("subject", "")
                sender = headers.get("from", "")
                msg_date = headers.get("date", "")
                snippet = msg_full.get("snippet", "")
                thread_id = msg_full.get("threadId", "") or ""

                category_hint = self.classify(subject, sender, snippet, extracted_text="")

                saved_count, upsert_count, skipped_count = self._process_message_attachments(
                    message_id=message_id,
                    thread_id=thread_id,
                    subject=subject,
                    sender=sender,
                    msg_date=msg_date,
                    snippet=snippet,
                    category_hint=category_hint,
                    user_id=user_id,
                )

                total_msgs += 1
                total_files_saved += saved_count
                total_rows_upserted += upsert_count
                total_skipped_duplicates += skipped_count

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return {
            "emails_processed": total_msgs,
            "files_saved": total_files_saved,
            "rows_upserted": total_rows_upserted,
            "skipped_duplicates": total_skipped_duplicates,
            "stopped_reason": None,
        }

    def _process_message_attachments(
            self,
            *,
            message_id: str,
            thread_id: str,
            subject: str,
            sender: str,
            msg_date: str,
            snippet: str,
            category_hint: str,
            user_id: str,
    ) -> tuple[int, int, int]:
        """
        Returns: (files_saved, rows_upserted, skipped_duplicates)
        """
        msg = self.service.users().messages().get(userId=user_id, id=message_id).execute()
        attachments = self._collect_attachment_parts(msg.get("payload", {}))
        if not attachments:
            return 0, 0, 0

        files_saved = 0
        rows_upserted = 0
        skipped_duplicates = 0

        for filename, attachment_id, mime_type in attachments:
            if not filename or not attachment_id:
                continue

            filename_lower = filename.lower()
            if self.config.only_pdf_and_images and not filename_lower.endswith((".pdf", ".png", ".jpg", ".jpeg")):
                continue

            att = self.service.users().messages().attachments().get(
                userId=user_id, messageId=message_id, id=attachment_id
            ).execute()

            data = att.get("data")
            if not data:
                continue

            file_bytes = base64.urlsafe_b64decode(data.encode("UTF-8"))
            file_hash = self._sha256_bytes(file_bytes)

            # Dedup by hash (fast + reliable)
            if self._exists_hash(file_hash):
                skipped_duplicates += 1
                continue

            safe_name = self._safe_filename(filename)
            unique_suffix = hashlib.sha256((message_id + attachment_id).encode()).hexdigest()[:10]
            name, ext = os.path.splitext(safe_name)
            out_name = f"{name}_{unique_suffix}{ext}" if ext else f"{name}_{unique_suffix}"

            # Save first into hint category folder
            temp_dir = self.download_root / category_hint
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / out_name
            out_path.write_bytes(file_bytes)

            extracted_text = ""
            if ext.lower() == ".pdf":
                extracted_text = self.extract_text_from_pdf(
                    out_path,
                    ocr_lang=self.config.ocr_lang,
                    ocr_max_pages=self.config.ocr_max_pages,
                    digital_min_chars=self.config.digital_min_chars,
                    dpi=self.config.dpi,
                )

            final_category = self.classify(subject, sender, snippet, extracted_text)

            amount_value, amount_currency, amount_source = self.extract_amount_and_currency(extracted_text)
            due_date_iso, due_date_source = self.extract_due_date_iso(extracted_text)

            # Move to final category directory if changed
            if final_category != category_hint:
                final_dir = self.download_root / final_category
                final_dir.mkdir(parents=True, exist_ok=True)
                final_path = final_dir / out_name
                try:
                    out_path.replace(final_path)
                    out_path = final_path
                except Exception:
                    pass

            # Store saved_path as RELATIVE under download_root (fits your models)
            rel_saved_path = out_path.relative_to(self.download_root).as_posix()

            # Save DB row (atomic per attachment)
            with transaction.atomic():
                row = self._upsert_attachment(
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
                    saved_path=rel_saved_path,
                    extracted_text_len=len(extracted_text),
                    amount_value=amount_value,
                    amount_currency=amount_currency,
                    amount_source=amount_source,
                    due_date_iso=due_date_iso,
                    due_date_source=due_date_source,
                )
                self._create_bill_mirror_if_enabled(enabled=self.config.create_bill_mirror, att=row)

            files_saved += 1
            rows_upserted += 1

        return files_saved, rows_upserted, skipped_duplicates
