from __future__ import annotations

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
from .gmailConnect import GmailAuthService
from  .models import BillDocument,GmailAccount
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

    days = days_map.get(time_window or "30d", 30)
    now = django_timezone.now()
    return now - timedelta(days=days), now


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

    gmail_account = None

    if gmail_account_id:
        gmail_account = GmailAccount.objects.filter(
            id=gmail_account_id,
            is_active=True,
        ).first()

    if not gmail_account:
        gmail_account = GmailAccount.objects.filter(
            is_active=True,
        ).order_by("-updated_at").first()

    if not gmail_account:
        return Response(
            {"ok": False, "error": "not_connected"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    request.session["gmail_account_id"] = gmail_account.id
    request.session.modified = True

    creds = auth.ensure_valid_creds(gmail_account)

    if not creds:
        return Response(
            {"ok": False, "error": "not_connected"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    time_window = request.data.get("time_window") or "30d"

    query = request.data.get("query") or (
        '(invoice OR receipt OR "חשבונית" OR "קבלה" OR "Order" OR "הזמנה" OR "חשבונית מס" OR "Tax Invoice")'
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
            },
            status=status.HTTP_200_OK,
        )

    rows = []

    for fetch_from, fetch_until in fetch_ranges:
        batch_rows = fetch_invoice_attachments(
            creds=creds,
            downloads_dir=settings.BILLS_DOWNLOADS_DIR,
            query=query,
            max_results=max_results,
            start_date=fetch_from,
            end_date=fetch_until,
        )
        rows.extend(batch_rows)

    created = 0
    updated = 0

    for r in rows:
        print(r["subject"])

        obj, is_created = BillDocument.objects.get_or_create(
            message_id=r["message_id"],
            defaults={
                "attachment_id": r["attachment_id"],
                "subject": r["subject"],
                "sender": r["sender"],
                "msg_date": r["msg_date"],
                "filename": r["filename"],
                "saved_path": r["saved_path"],
                "category": r["category"],
                "amount_value": r["amount_value"],
                "amount_currency": r["amount_currency"],
                "due_date_iso": r["due_date_iso"],
            },
        )

        if is_created:
            created += 1
        else:
            changed = False
            update_fields = []

            if not obj.category and r.get("category"):
                obj.category = r["category"]
                changed = True
                update_fields.append("category")

            if not obj.saved_path and r.get("saved_path"):
                obj.saved_path = r["saved_path"]
                changed = True
                update_fields.append("saved_path")

            if obj.amount_value is None and r.get("amount_value") is not None:
                obj.amount_value = r["amount_value"]
                changed = True
                update_fields.append("amount_value")

            if not obj.amount_currency and r.get("amount_currency"):
                obj.amount_currency = r["amount_currency"]
                changed = True
                update_fields.append("amount_currency")

            if not obj.due_date_iso and r.get("due_date_iso"):
                obj.due_date_iso = r["due_date_iso"]
                changed = True
                update_fields.append("due_date_iso")

            if changed:
                obj.save(update_fields=update_fields)
                updated += 1

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
    days = int(request.GET.get("days") or 14)
    now = datetime.now(dt_timezone.utc)
    limit = now + timedelta(days=days)

    items = []
    for b in BillDocument.objects.all():
        if not b.due_date_iso:
            continue
        try:
            d = datetime.fromisoformat(b.due_date_iso)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt_timezone.utc)
            if now <= d <= limit:
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

    # Ensure we're actually using SQLite
    if connection.vendor != "sqlite":
        return Response(
            {"error": f"clean_db is intended for SQLite, but current DB vendor is '{connection.vendor}'"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        sql = sql_path.read_text(encoding="utf-8")

        with transaction.atomic():
            with connection.cursor() as cursor:
                # SQLite supports multiple statements via executescript
                cursor.executescript(sql)

        return Response(
            {"message": "SQLite database cleaned successfully"},
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
