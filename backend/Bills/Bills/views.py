from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .gmailConnect import GmailAuthService


def _auth_service() -> GmailAuthService:
    return GmailAuthService(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH,
        redirect_uri=settings.GMAIL_REDIRECT_URI,
    )


@api_view(["GET"])
def gmail_connect(request):
    """
    GET /api/gmail/connect/

    - No token yet → redirect to Google OAuth
    - Returning with ?code=&state= → store token, return JSON
    - Token already valid → return JSON
    """
    auth = _auth_service()

    code = request.GET.get("code")
    state = request.GET.get("state")

    # Already connected
    if not code:
        creds = auth.ensure_valid_creds()
        if creds:
            return Response(
                {"ok": True, "status": "already_connected"},
                status=status.HTTP_200_OK,
            )

        # Start OAuth flow
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

@api_view(["GET"])
def get_emails(request):
    """
    GET /api/gmail/get-emails/

    This should be called AFTER /api/gmail/connect/ completed successfully.

    Behavior:
    - If not connected → 401 with hint to call /connect/
    - If connected → fetch emails+attachments, classify+extract, save via Django ORM
    """
    auth = _auth_service()
    creds = auth.ensure_valid_creds()
    if not creds:
        return Response(
            {"ok": False, "error": "not_connected", "hint": "Call /api/gmail/connect/ first"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Optional query overrides via URL params
    query = request.GET.get("query") or GmailInvoiceService.build_default_query(
        time_window=request.GET.get("window", "365d")
    )

    # Safety/perf knobs (optional)
    max_per_page = int(request.GET.get("max_per_page", "100"))
    limit_messages_raw = request.GET.get("limit_messages")
    limit_messages = int(limit_messages_raw) if limit_messages_raw else None

    service = GmailInvoiceService(
        creds=creds,
        config=GmailFetchConfig(
            download_root=settings.BILLS_DOWNLOADS_DIR,  # you should define this in settings.py
            only_pdf_and_images=True,
            ocr_lang="heb+eng",
            ocr_max_pages=2,
            digital_min_chars=200,
            dpi=250,
            tesseract_cmd=getattr(settings, "TESSERACT_CMD", None),
            create_bill_mirror=True,
        ),
    )

    try:
        stats = service.run_query(
            query=query,
            max_per_page=max_per_page,
            limit_messages=limit_messages,
        )
        return Response({"ok": True, "status": "done", "stats": stats}, status=status.HTTP_200_OK)
    except Exception as e:
        # keep it simple for now; later you can log exception details with logging/Sentry
        return Response(
            {"ok": False, "error": "fetch_failed", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )