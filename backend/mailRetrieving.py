from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from email import message_from_bytes
import base64


class MailRetrieving:
    def __init__(self):
        self.service = None
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]

    def connect(self, token_path):
        creds = Credentials.from_authorized_user_file(token_path, self.scopes)
        self.service = build("gmail", "v1", credentials=creds)

    def get_emails(self, query, time_window=None, max_results=10, user_id="me"):
        """
        time_window examples:
          - "5m"  -> last 5 months
          - "30d" -> last 30 days
          - "1y"  -> last 1 year
        """
        if self.service is None:
            raise RuntimeError("Call connect(token_path) first")

        if time_window:
            query = f"{query} newer_than:{time_window}"

        res = self.service.users().messages().list(
            userId=user_id,
            q=query,
            maxResults=max_results
        ).execute()

        msgs = res.get("messages", []) or []
        emails = []

        for m in msgs:
            data = self.service.users().messages().get(
                userId=user_id,
                id=m["id"],
                format="raw"
            ).execute()

            raw = data.get("raw")
            if not raw:
                continue

            decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
            emails.append(message_from_bytes(decoded))

        return emails

    def has_pdf_or_image(self, email_msg):
        for part in email_msg.walk():
            if part.get_filename():
                ct = part.get_content_type()
                if ct == "application/pdf" or ct.startswith("image/"):
                    return True
        return False
