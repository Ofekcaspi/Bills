from __future__ import annotations

import csv as std_csv
import io as std_io
import re as std_re
import zipfile as std_zipfile
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone as django_timezone
from json import dumps as json_dumps
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.db import connection, transaction
from .chat_service import (
    ChatServiceError,
    ensure_session_key,
    get_or_create_conversation,
    handle_chat_message,
)
from .gmailConnect import GmailAuthService
from .models import BillDocument, GmailAccount, Bill, Receipt
from .gmail_fetcher import fetch_invoice_attachments


# =====================================================
# Helpers
# =====================================================
def _auth_service() -> GmailAuthService:
    return GmailAuthService(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        tokens_dir=settings.GMAIL_TOKENS_DIR,
        redirect_uri=settings.GMAIL_REDIRECT_URI,
    )


@api_view(["POST"])
def chat_with_openai(request):
    try:
        session_key = ensure_session_key(request)
        if not session_key:
            raise ChatServiceError("Failed to initialize session for chat", status_code=500)

        conversation = get_or_create_conversation(session_key)
        previous_response_id_raw = request.data.get("previous_response_id")
        previous_response_id = (
            str(previous_response_id_raw).strip()
            if isinstance(previous_response_id_raw, str)
            else ""
        )

        payload = handle_chat_message(
            conversation=conversation,
            message=str(request.data.get("message") or ""),
            previous_response_id=previous_response_id,
        )
        return Response(payload, status=status.HTTP_200_OK)
    except ChatServiceError as exc:
        return Response(
            {"ok": False, "error": str(exc)},
            status=exc.status_code,
        )


# =====================================================
# OAuth – Gmail connect
# =====================================================
@api_view(["GET"])
def gmail_connect(request):
    auth = _auth_service()

    code = request.GET.get("code")
    state = request.GET.get("state")

    if code:
        saved_state = request.session.get("gmail_oauth_state")

        if not saved_state or saved_state != state:
            return Response(
                {"ok": False, "error": "Invalid OAuth state"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        gmail_account = auth.finish_oauth(
            state=saved_state,
            code=code,
        )

        request.session.pop("gmail_oauth_state", None)
        request.session["gmail_account_id"] = gmail_account.id

        return Response(
            {
                "ok": True,
                "status": "connected",
                "gmail_account_id": gmail_account.id,
                "google_email": gmail_account.google_email,
            },
            status=status.HTTP_200_OK,
        )

    gmail_account_id = request.session.get("gmail_account_id")

    if gmail_account_id:
        try:
            gmail_account = GmailAccount.objects.get(
                id=gmail_account_id,
                is_active=True,
            )

            creds = auth.ensure_valid_creds(gmail_account)

            if creds:
                return Response(
                    {
                        "ok": True,
                        "status": "already_connected",
                        "gmail_account_id": gmail_account.id,
                        "google_email": gmail_account.google_email,
                    },
                    status=status.HTTP_200_OK,
                )

        except GmailAccount.DoesNotExist:
            request.session.pop("gmail_account_id", None)

    auth_url, new_state = auth.start_oauth()
    request.session["gmail_oauth_state"] = new_state

    return redirect(auth_url)
# =====================================================
# POST /sync/ – סנכרון Gmail → downloads/ + DB
# =====================================================
def window_to_dates(time_window: str | None):
    days_map = {
        "7d": 7,
        "14d": 14,
        "30d": 30,
        "90d": 90,
        "180d": 180,
        "365d": 365,
    }

    days = days_map.get(time_window or "365d", 365)
    now = django_timezone.now()
    return now - timedelta(days=days), now
@api_view(["PATCH"])
def update_bill_status(request):
    bill_id = request.data.get("bill_id")

    try:
        document = BillDocument.objects.get(id=bill_id)
    except BillDocument.DoesNotExist:
        return Response(
            {"error": "Bill document not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    new_status = (request.data.get("status") or "").lower().strip()

    if new_status not in ["bill", "receipt"]:
        return Response(
            {"error": "status must be either 'bill' or 'receipt'"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if new_status == "receipt":
        document.document_type = BillDocument.DocumentType.RECEIPT
        document.save(update_fields=["document_type"])

        receipt, _ = Receipt.objects.get_or_create(
            id=document.id,
            defaults={
                "paid_at": request.data.get("paid_at") or django_timezone.now().date(),
                "payment_method": request.data.get("payment_method"),
            },
        )

        receipt.paid_at = request.data.get("paid_at") or receipt.paid_at or django_timezone.now().date()
        receipt.payment_method = request.data.get("payment_method", receipt.payment_method)
        receipt.save()

        document = receipt

    else:
        document.document_type = BillDocument.DocumentType.BILL
        document.save(update_fields=["document_type"])

        bill, _ = Bill.objects.get_or_create(id=document.id)

        if request.data.get("due_date") or request.data.get("due_date_iso"):
            bill.due_date = request.data.get("due_date") or request.data.get("due_date_iso")
            bill.save()

        document = bill

    return Response(
        {
            "message": "Document status updated successfully",
            "id": document.id,
            "pk": document.pk,
            "document": document.to_dict(),
        },
        status=status.HTTP_200_OK,
    )

def calculate_fetch_ranges(gmail_account: GmailAccount, requested_from, requested_until):
    if not gmail_account.synced_from or not gmail_account.synced_until:
        return [(requested_from, requested_until)]

    fetch_ranges = []

    existing_from = gmail_account.synced_from
    existing_until = gmail_account.synced_until

    # Need older missing data
    if requested_from < existing_from:
        fetch_ranges.append((requested_from, existing_from))

    # Need newer missing data
    if requested_until > existing_until:
        fetch_ranges.append((existing_until, requested_until))

    return fetch_ranges

@api_view(["POST"])
def sync_gmail(request):
    auth = _auth_service()

    gmail_account_id = request.session.get("gmail_account_id")
    active_accounts = list(
        GmailAccount.objects.filter(is_active=True).order_by("-updated_at")
    )

    if not active_accounts:
        return Response(
            {"ok": False, "error": "not_connected"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    selected_account = None

    # Keep the session-preferred account first (if still active), then fallback to others.
    candidates = []
    if gmail_account_id:
        preferred = next((acc for acc in active_accounts if acc.id == gmail_account_id), None)
        if preferred is not None:
            candidates.append(preferred)

    for acc in active_accounts:
        if not any(existing.id == acc.id for existing in candidates):
            candidates.append(acc)

    for candidate in candidates:
        creds = auth.ensure_valid_creds(candidate)
        if creds:
            selected_account = candidate
            break

    if not selected_account:
        return Response(
            {"ok": False, "error": "not_connected"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    request.session["gmail_account_id"] = selected_account.id
    request.session.modified = True
    gmail_account = selected_account

    time_window = request.data.get("time_window") or "365d"

    query = request.data.get("query") or (
        '(invoice OR receipt OR "חשבונית" OR "קבלה" OR "Order" OR "הזמנה" OR "חשבונית מס" OR "Tax Invoice")'
        'NOT subject:(פרסומת)'
    )

    max_results = int(request.data.get("max_results") or 20)

    requested_from, requested_until = window_to_dates(time_window)

    fetch_ranges = calculate_fetch_ranges(
        gmail_account=gmail_account,
        requested_from=requested_from,
        requested_until=requested_until,
    )

    if not fetch_ranges:
        gmail_account.last_synced_at = django_timezone.now()
        gmail_account.last_sync_window = time_window
        gmail_account.last_sync_count = 0
        gmail_account.save(update_fields=[
            "last_synced_at",
            "last_sync_window",
            "last_sync_count",
            "updated_at",
        ])

        return Response(
            {
                "ok": True,
                "status": "already_synced",
                "gmail_account": gmail_account.google_email,
                "requested_from": requested_from.isoformat(),
                "requested_until": requested_until.isoformat(),
                "synced_from": gmail_account.synced_from.isoformat() if gmail_account.synced_from else None,
                "synced_until": gmail_account.synced_until.isoformat() if gmail_account.synced_until else None,
                "fetched": 0,
                "created": 0,
                "updated": 0,
                "saved_objects": [],
            },
            status=status.HTTP_200_OK,
        )

    rows = []

    for fetch_from, fetch_until in fetch_ranges:
        batch_rows = fetch_invoice_attachments(
            creds=creds,
            downloads_dir=settings.BILLS_DOWNLOADS_DIR,
            query=query,
            my_email=gmail_account.google_email,
            max_results=max_results,
            start_date=fetch_from,
            end_date=fetch_until,
        )
        rows.extend(batch_rows)

    created = 0
    updated = 0
    saved_objects = []

    for r in rows:
        document_type = (r.get("document_type") or "").lower().strip()

        if document_type == BillDocument.DocumentType.BILL:
            model_class = Bill
        elif document_type == BillDocument.DocumentType.RECEIPT:
            model_class = Receipt
        else:
            continue

        defaults = {
            "document_type": document_type,
            "subject": r.get("subject"),
            "sender": r.get("sender"),
            "msg_date": r.get("msg_date"),
            "filename": r.get("filename"),
            "saved_path": r.get("saved_path"),
            "vendor": r.get("vendor") or r.get("sender"),
            "category": r.get("category"),
            "amount_value": r.get("amount_value"),
            "amount_currency": r.get("amount_currency"),
            "document_date": r.get("document_date"),
        }

        if document_type == BillDocument.DocumentType.BILL:
            defaults["due_date"] = r.get("due_date") or r.get("due_date_iso")

        if document_type == BillDocument.DocumentType.RECEIPT:
            defaults["paid_at"] = r.get("paid_at")
            defaults["payment_method"] = r.get("payment_method")

        obj, is_created = model_class.objects.get_or_create(
            gmail_account=gmail_account,
            message_id=r["message_id"],
            attachment_id=r.get("attachment_id"),
            defaults=defaults,
        )

        if is_created:
            created += 1
        else:
            changed = False
            update_fields = []

            for field, value in defaults.items():
                if value is not None and not getattr(obj, field, None):
                    setattr(obj, field, value)
                    changed = True
                    update_fields.append(field)

            if changed:
                obj.save(update_fields=update_fields)
                updated += 1

        saved_objects.append({
            "id": obj.id,
            "pk": obj.pk,
            "document_type": document_type,
            "message_id": obj.message_id,
            "attachment_id": obj.attachment_id,
        })

    gmail_account.synced_from = (
        min(gmail_account.synced_from, requested_from)
        if gmail_account.synced_from
        else requested_from
    )

    gmail_account.synced_until = (
        max(gmail_account.synced_until, requested_until)
        if gmail_account.synced_until
        else requested_until
    )

    gmail_account.last_synced_at = django_timezone.now()
    gmail_account.last_sync_window = time_window
    gmail_account.last_sync_count = len(rows)

    gmail_account.save(update_fields=[
        "synced_from",
        "synced_until",
        "last_synced_at",
        "last_sync_window",
        "last_sync_count",
        "updated_at",
    ])

    return Response(
        {
            "ok": True,
            "gmail_account": gmail_account.google_email,
            "requested_from": requested_from.isoformat(),
            "requested_until": requested_until.isoformat(),
            "synced_from": gmail_account.synced_from.isoformat(),
            "synced_until": gmail_account.synced_until.isoformat(),
            "fetch_ranges": [
                {
                    "from": start.isoformat(),
                    "until": end.isoformat(),
                }
                for start, end in fetch_ranges
            ],
            "fetched": len(rows),
            "created": created,
            "updated": updated,
            "saved_objects": saved_objects,
        },
        status=status.HTTP_200_OK,
    )
# =====================================================
# GET /bills/ – רשימת חשבוניות
# =====================================================
@api_view(["GET"])
def bills_list(request):
    """
    GET /bills/
    מחזיר רשימת חשבוניות בפורמט שהפרונט מצפה
    """
    qs = BillDocument.objects.order_by("-msg_date", "-id")[:1000]
    items = [b.to_dict() for b in qs]
    return Response({"items": items}, status=status.HTTP_200_OK)


# =====================================================
# GET /summary/ – סיכום סכומים
# =====================================================
@api_view(["GET"])
def bills_summary(request):
    """
    GET /summary/
    """
    total = 0.0
    for b in BillDocument.objects.all():
        if b.amount_value is not None:
            total += float(b.amount_value)

    return Response({"total": total}, status=status.HTTP_200_OK)


# =====================================================
# GET /upcoming/ – תשלומים קרובים
# =====================================================
@api_view(["GET"])
def bills_upcoming(request):
    """
    GET /upcoming/?days=14
    """
    try:
        days = int(request.GET.get("days") or 14)
    except (TypeError, ValueError):
        days = 14
    days = max(0, min(days, 3650))

    now = datetime.now(dt_timezone.utc)
    limit = now + timedelta(days=days)

    items = []
    for b in Bill.objects.all():
        due_value = b.due_date
        if not due_value:
            continue

        try:
            if isinstance(due_value, datetime):
                due_dt = due_value
            elif isinstance(due_value, str):
                due_dt = datetime.fromisoformat(due_value)
            else:
                # DateField returns a date object (most common path)
                due_dt = datetime.combine(due_value, datetime.min.time())

            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=dt_timezone.utc)

            if now <= due_dt <= limit:
                items.append(b.to_dict())
        except Exception:
            continue

    return Response(
        {"count": len(items), "items": items},
        status=status.HTTP_200_OK,
    )


# =====================================================
# GET /files/<path> – הגשת קבצים מ-downloads/
# =====================================================
@api_view(["GET"])
def serve_file(request, path: str):
    """
    GET /files/<path>
    מגיש קבצים מתוך downloads/ בלבד (מוגן path traversal)
    """
    base = Path(settings.BILLS_DOWNLOADS_DIR).resolve()
    target = (base / path).resolve()

    if not str(target).startswith(str(base)) or not target.exists():
        raise Http404("File not found")

    content_type = "application/pdf"
    if target.suffix.lower() == ".txt":
        content_type = "text/plain; charset=utf-8"

    return FileResponse(
        open(target, "rb"),
        content_type=content_type,
    )
@api_view(["DELETE"])
def clean_db(request):
    sql_path = Path(__file__).resolve().parent / "clean_db_script.sql"

    if not sql_path.exists():
        return Response(
            {"error": f"SQL script not found at {sql_path}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if connection.vendor != "sqlite":
        return Response(
            {"error": f"clean_db is intended for SQLite, but current DB vendor is '{connection.vendor}'"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        sql = sql_path.read_text(encoding="utf-8")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.executescript(sql)

            # reset gmail sync tracking
            GmailAccount.objects.all().update(
                synced_from=None,
                synced_until=None,
                last_synced_at=None,
                last_sync_window=None,
                last_sync_count=0,
            )

        return Response(
            {
                "message": "SQLite database cleaned successfully",
                "gmail_accounts_reset": True,
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
def _resolve_saved_file_path(saved_path: str | None) -> Path | None:
    if not saved_path:
        return None

    base = Path(settings.BILLS_DOWNLOADS_DIR).resolve()
    raw_value = str(saved_path).strip()
    if not raw_value:
        return None

    normalized = raw_value.replace("\\", "/")
    candidate_paths = []

    raw_path = Path(raw_value)
    if raw_path.is_absolute():
        candidate_paths.append(raw_path)

    relative = normalized
    if relative.startswith("./"):
        relative = relative[2:]
    if relative.startswith("downloads/"):
        relative = relative[len("downloads/"):]
    candidate_paths.append(base / relative)

    for candidate in candidate_paths:
        try:
            resolved = candidate.resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue

        try:
            resolved.relative_to(base)
        except ValueError:
            continue

        if resolved.is_file():
            return resolved

    return None


def _safe_archive_filename(value: str | None, fallback: str) -> str:
    raw = (value or "").strip()
    if raw:
        raw = raw.replace("\\", "/").split("/")[-1]
    else:
        raw = fallback

    safe = std_re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", raw).strip().strip(".")
    return safe or fallback


@api_view(["POST"])
def export_receipts_report(request):
    raw_ids = request.data.get("document_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return Response(
            {"error": "document_ids must be a non-empty list"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    document_ids = []
    for raw_id in raw_ids:
        try:
            document_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    if not document_ids:
        return Response(
            {"error": "No valid document IDs were provided"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    documents = list(
        BillDocument.objects.filter(id__in=document_ids).order_by("-msg_date", "-id")
    )
    if not documents:
        return Response(
            {"error": "No documents found for the selected IDs"},
            status=status.HTTP_404_NOT_FOUND,
        )

    report_stream = std_io.StringIO()
    report_writer = std_csv.writer(report_stream)
    report_writer.writerow(
        [
            "id",
            "subject",
            "sender",
            "category",
            "document_type",
            "amount_value",
            "amount_currency",
            "msg_date",
            "saved_path",
            "filename",
        ]
    )

    archive_buffer = std_io.BytesIO()
    used_filenames = {}
    exported_count = 0
    missing_files = []

    with std_zipfile.ZipFile(
        archive_buffer,
        "w",
        compression=std_zipfile.ZIP_DEFLATED,
    ) as report_zip:
        for document in documents:
            report_writer.writerow(
                [
                    document.id,
                    document.subject or "",
                    document.sender or "",
                    document.category or "",
                    document.document_type or "",
                    document.amount_value if document.amount_value is not None else "",
                    document.amount_currency or "",
                    document.msg_date.isoformat() if document.msg_date else "",
                    document.saved_path or "",
                    document.filename or "",
                ]
            )

            resolved_file = _resolve_saved_file_path(document.saved_path)
            if not resolved_file:
                missing_files.append(
                    {
                        "id": document.id,
                        "filename": document.filename,
                        "saved_path": document.saved_path,
                    }
                )
                continue

            fallback_name = f"receipt_{document.id}{resolved_file.suffix or '.pdf'}"
            base_name = _safe_archive_filename(document.filename or resolved_file.name, fallback_name)

            next_index = used_filenames.get(base_name, 0) + 1
            used_filenames[base_name] = next_index
            if next_index > 1:
                stem = Path(base_name).stem
                suffix = Path(base_name).suffix
                archive_name = f"receipts/{stem}_{next_index}{suffix}"
            else:
                archive_name = f"receipts/{base_name}"

            report_zip.write(resolved_file, arcname=archive_name)
            exported_count += 1

        report_zip.writestr("report_summary.csv", report_stream.getvalue().encode("utf-8-sig"))
        if missing_files:
            report_zip.writestr(
                "missing_files.json",
                json_dumps(missing_files, ensure_ascii=False, indent=2).encode("utf-8"),
            )

    if exported_count == 0:
        return Response(
            {"error": "No receipt files found for the selected documents"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    archive_buffer.seek(0)
    timestamp = django_timezone.now().strftime("%Y%m%d_%H%M%S")
    response = FileResponse(
        archive_buffer,
        as_attachment=True,
        filename=f"receipts_report_{timestamp}.zip",
        content_type="application/zip",
    )
    response["X-Report-Documents"] = str(len(documents))
    response["X-Report-Exported-Files"] = str(exported_count)
    response["X-Report-Missing-Files"] = str(len(missing_files))
    return response
