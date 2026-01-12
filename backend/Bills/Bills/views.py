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
