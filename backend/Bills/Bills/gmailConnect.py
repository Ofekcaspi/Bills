"""Handles connecting a user's Gmail account: sending them to Google to approve
access, and saving/reusing their login token afterward."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, List
from uuid import uuid4
from googleapiclient.discovery import build
from django.contrib.auth import get_user_model

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

from .models import GmailAccount

User = get_user_model()


class GmailAuthService:
    """Walks a user through connecting their Gmail account and keeps their login token usable."""

    def __init__(
            self,
            *,
            credentials_path: Path,
            tokens_dir: Path,
            redirect_uri: str,
            scopes: Optional[List[str]] = None,
    ):
        self.credentials_path = Path(credentials_path)
        self.tokens_dir = Path(tokens_dir)
        self.redirect_uri = redirect_uri
        self.scopes = scopes or [
            "https://www.googleapis.com/auth/gmail.readonly",
        ]

    def build_flow(self, state: Optional[str] = None) -> Flow:
        flow = Flow.from_client_secrets_file(
            str(self.credentials_path),
            scopes=self.scopes,
            state=state,
        )
        flow.redirect_uri = self.redirect_uri
        return flow

    def start_oauth(self) -> tuple[str, str]:
        flow = self.build_flow()

        # Always show the consent screen and ask for offline access, so we get
        # a token we can refresh later instead of one that dies when the tab closes.
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="false",
            prompt="consent",
        )

        return auth_url, state

    def finish_oauth(self, *, state: str, code: str) -> GmailAccount:
        """Takes the code Google sent back, figures out who signed in, and saves their token for later use."""
        flow = self.build_flow(state=state)
        flow.fetch_token(code=code)

        creds = flow.credentials

        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        google_email = profile.get("emailAddress")

        if not google_email:
            raise ValueError("Could not determine Google email from OAuth response")

        user, _ = User.objects.get_or_create(
            username=google_email,
            defaults={
                "email": google_email,
            },
        )

        self.tokens_dir.mkdir(parents=True, exist_ok=True)

        gmail_account, _ = GmailAccount.objects.get_or_create(
            user=user,
            google_email=google_email,
            defaults={
                "token_path": str(self.tokens_dir / f"{uuid4()}.json"),
                "is_active": True,
            },
        )

        token_path = Path(gmail_account.token_path)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

        gmail_account.is_active = True
        gmail_account.save(update_fields=["is_active", "updated_at"])

        return gmail_account

    def load_creds(self, gmail_account: GmailAccount) -> Optional[Credentials]:
        token_path = Path(gmail_account.token_path)

        if not token_path.exists():
            return None

        return Credentials.from_authorized_user_file(
            str(token_path),
            self.scopes,
        )

    def save_creds(self, gmail_account: GmailAccount, creds: Credentials) -> None:
        token_path = Path(gmail_account.token_path)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    def delete_creds(self, gmail_account: GmailAccount) -> None:
        token_path = Path(gmail_account.token_path)

        if token_path.exists():
            token_path.unlink()

        gmail_account.is_active = False
        gmail_account.save(update_fields=["is_active", "updated_at"])

    def ensure_valid_creds(self, gmail_account: GmailAccount) -> Optional[Credentials]:
        """Gets a usable token for this account: reuses it if still valid, refreshes it if expired, or forgets it if that fails."""
        creds = self.load_creds(gmail_account)

        if not creds:
            return None

        if creds.valid:
            return creds

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.save_creds(gmail_account, creds)
                return creds
            except RefreshError:
                self.delete_creds(gmail_account)
                return None

        return None