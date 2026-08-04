from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone as django_timezone
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
from .gmail_fetcher import GmailInvoiceFetcher
from .file_naming import safe_filename, dedupe_filename


DEFAULT_SYNC_QUERY = (
    '(invoice OR receipt OR "חשבונית" OR "קבלה" OR "Order" OR "הזמנה" OR "חשבונית מס" OR "Tax Invoice" OR "שובר" OR "קבלת תשלום",OR "אישור תשלום")'
    'NOT subject:(פרסומת)'
)


# =====================================================
# Helpers
# =====================================================
def _auth_service() -> GmailAuthService:
    return GmailAuthService(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        tokens_dir=settings.GMAIL_TOKENS_DIR,
        redirect_uri=settings.GMAIL_REDIRECT_URI,
    )


def _error_response(message: str, status_code: int) -> Response:
    return Response({"error": message}, status=status_code)


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
        return _error_response("Bill document not found", status.HTTP_404_NOT_FOUND)

    new_status = (request.data.get("status") or "").lower().strip()

    if new_status not in ["bill", "receipt"]:
        return _error_response("status must be either 'bill' or 'receipt'", status.HTTP_400_BAD_REQUEST)

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


def _select_gmail_account(request, auth: GmailAuthService):
    """
    Picks the session's preferred Gmail account if it's still active and has
    valid creds, otherwise falls back to the next active account that does.
    Returns (gmail_account, creds) or (None, None) if nothing usable is found.
    """
    preferred_id = request.session.get("gmail_account_id")
    active_accounts = list(
        GmailAccount.objects.filter(is_active=True).order_by("-updated_at")
    )

    # Try the session-preferred account first, keep the rest in their original order.
    candidates = sorted(active_accounts, key=lambda acc: acc.id != preferred_id)

    for candidate in candidates:
        creds = auth.ensure_valid_creds(candidate)
        if creds:
            return candidate, creds

    return None, None


def _persist_fetched_rows(rows: list[dict], gmail_account: GmailAccount):
    """Upserts fetched bill/receipt rows into the DB. Returns (created, updated, saved_objects)."""
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

    return created, updated, saved_objects


@api_view(["POST"])
def sync_gmail(request):
    auth = _auth_service()

    gmail_account, creds = _select_gmail_account(request, auth)
    if not gmail_account:
        return Response(
            {"ok": False, "error": "not_connected"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    request.session["gmail_account_id"] = gmail_account.id
    request.session.modified = True

    time_window = request.data.get("time_window") or "365d"
    query = request.data.get("query") or DEFAULT_SYNC_QUERY
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

    fetcher = GmailInvoiceFetcher(creds)
    rows = []

    for fetch_from, fetch_until in fetch_ranges:
        rows.extend(fetcher.fetch(
            downloads_dir=settings.BILLS_DOWNLOADS_DIR,
            query=query,
            my_email=gmail_account.google_email,
            max_results=max_results,
            start_date=fetch_from,
            end_date=fetch_until,
        ))

    created, updated, saved_objects = _persist_fetched_rows(rows, gmail_account)

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
    for b in BillDocument.objects.filter(
            document_type=BillDocument.DocumentType.BILL
    ):
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
        return _error_response(f"SQL script not found at {sql_path}", status.HTTP_500_INTERNAL_SERVER_ERROR)

    if connection.vendor != "sqlite":
        return _error_response(
            f"clean_db is intended for SQLite, but current DB vendor is '{connection.vendor}'",
            status.HTTP_400_BAD_REQUEST,
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
        return _error_response(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)


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


def _write_receipts_archive(documents: list[BillDocument]):
    """Builds the CSV summary + zip of receipt files for export_receipts_report. Returns (buffer, exported_count, missing_files)."""
    report_stream = io.StringIO()
    report_writer = csv.writer(report_stream)
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

    archive_buffer = io.BytesIO()
    used_filenames = {}
    exported_count = 0
    missing_files = []

    with zipfile.ZipFile(
        archive_buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
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
            base_name = safe_filename(document.filename or resolved_file.name, fallback_name)
            archive_name = f"receipts/{dedupe_filename(base_name, used_filenames)}"

            report_zip.write(resolved_file, arcname=archive_name)
            exported_count += 1

        report_zip.writestr("report_summary.csv", report_stream.getvalue().encode("utf-8-sig"))
        if missing_files:
            report_zip.writestr(
                "missing_files.json",
                json.dumps(missing_files, ensure_ascii=False, indent=2).encode("utf-8"),
            )

    return archive_buffer, exported_count, missing_files


@api_view(["POST"])
def export_receipts_report(request):
    raw_ids = request.data.get("document_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return _error_response("document_ids must be a non-empty list", status.HTTP_400_BAD_REQUEST)

    document_ids = []
    for raw_id in raw_ids:
        try:
            document_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    if not document_ids:
        return _error_response("No valid document IDs were provided", status.HTTP_400_BAD_REQUEST)

    documents = list(
        BillDocument.objects.filter(id__in=document_ids).order_by("-msg_date", "-id")
    )
    if not documents:
        return _error_response("No documents found for the selected IDs", status.HTTP_404_NOT_FOUND)

    archive_buffer, exported_count, missing_files = _write_receipts_archive(documents)

    if exported_count == 0:
        return _error_response("No receipt files found for the selected documents", status.HTTP_400_BAD_REQUEST)

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
