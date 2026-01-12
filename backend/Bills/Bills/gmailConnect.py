from __future__ import annotations

from pathlib import Path
from typing import Optional, List

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request


class GmailAuthService:
    def __init__(
            self,
            *,
            credentials_path: Path,
            token_path: Path,
            redirect_uri: str,
            scopes: Optional[List[str]] = None,
    ):
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.redirect_uri = redirect_uri
        self.scopes = scopes or ["https://www.googleapis.com/auth/gmail.readonly"]

    def load_creds(self) -> Optional[Credentials]:
        if self.token_path.exists():
            return Credentials.from_authorized_user_file(str(self.token_path), self.scopes)
        return None

    def save_creds(self, creds: Credentials) -> None:
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    def ensure_valid_creds(self) -> Optional[Credentials]:
        """
        Return valid credentials if possible, else None.
        """
        creds = self.load_creds()
        if not creds:
            return None

        if creds.valid:
            return creds

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.save_creds(creds)
            return creds

        return None

    def build_flow(self, state: Optional[str] = None) -> Flow:
        flow = Flow.from_client_secrets_file(
            str(self.credentials_path),
            scopes=self.scopes,
            state=state,
        )
        flow.redirect_uri = self.redirect_uri
        return flow

    def start_oauth(self) -> tuple[str, str]:
        """
        Start OAuth flow.
        Returns (authorization_url, state).
        """
        flow = self.build_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url, state

    def finish_oauth(self, *, state: str, code: str) -> Credentials:
        """
        Finish OAuth flow and persist token.json.
        """
        flow = self.build_flow(state=state)
        flow.fetch_token(code=code)
        creds = flow.credentials
        self.save_creds(creds)
        return creds
