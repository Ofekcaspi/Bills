from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from backend.Bills.Bills.gmailConnect import GmailAuthService
from backend.Bills.Bills.models import BillDocument
from backend.Bills.Bills.gmail_fetcher import fetch_invoice_attachments


# =====================================================
# Helpers
# =====================================================
def _auth_service() -> GmailAuthService:
    return GmailAuthService(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH,
        redirect_uri=settings.GMAIL_REDIRECT_URI,
    )


# =====================================================
# OAuth – Gmail connect
# =====================================================
@api_view(["GET"])
def gmail_connect(request):
    """
    GET /connect-email/

    - אם יש token תקין → מחזיר JSON
    - אם אין token → redirect ל-Google OAuth
    - callback עם ?code=&state= → שומר token ומחזיר redirect / JSON
    """
    auth = _auth_service()

    code = request.GET.get("code")
    state = request.GET.get("state")

    # כבר מחובר
    if not code:
        creds = auth.ensure_valid_creds()
        if creds:
            return Response(
                {"ok": True, "status": "already_connected"},
                status=status.HTTP_200_OK,
            )

        # התחלת OAuth
        auth_url, new_state = auth.start_oauth()
        request.session["gmail_oauth_state"] = new_state
        return redirect(auth_url)

    # OAuth callback
    saved_state = request.session.get("gmail_oauth_state")
    if not saved_state or saved_state != state:
        return Response(
            {"ok": False, "error": "Invalid OAuth state"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    auth.finish_oauth(state=saved_state, code=code)
    request.session.pop("gmail_oauth_state", None)

    return Response(
        {"ok": True, "status": "connected"},
        status=status.HTTP_200_OK,
    )


# =====================================================
# POST /sync/ – סנכרון Gmail → downloads/ + DB
# =====================================================
@api_view(["POST"])
def sync_gmail(request):
    """
    POST /sync/

    מסנכרן מיילים עם attachments (PDF)
    שומר קבצים בתיקיית downloads/
    ושומר מטא־דאטה ב-DB
    """
    auth = _auth_service()
    creds = auth.ensure_valid_creds()
    if not creds:
        return Response(
            {"ok": False, "error": "not_connected"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    query = request.data.get("query") or (
        'has:attachment (filename:pdf OR "invoice" OR "receipt" OR "חשבונית" OR "קבלה")'
    )
    max_results = int(request.data.get("max_results") or 20)

    rows = fetch_invoice_attachments(
        creds=creds,
        downloads_dir=settings.BILLS_DOWNLOADS_DIR,
        query=query,
        max_results=max_results,
    )

    created = 0
    for r in rows:
        _, is_created = BillDocument.objects.get_or_create(
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

    return Response(
        {
            "ok": True,
            "fetched": len(rows),
            "created": created,
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
    qs = BillDocument.objects.order_by("-id")[:1000]
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
    now = datetime.now(timezone.utc)
    limit = now + timedelta(days=days)

    items = []
    for b in BillDocument.objects.all():
        if not b.due_date_iso:
            continue
        try:
            d = datetime.fromisoformat(b.due_date_iso)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
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

    return FileResponse(
        open(target, "rb"),
        content_type="application/pdf",
    )
