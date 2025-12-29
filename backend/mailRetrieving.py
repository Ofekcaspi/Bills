from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from email import message_from_bytes
import base64
import os



class MailRetrieving:
    def __init__(self):
        self.service = None
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]

    def connect(self, token_path):
        creds = Credentials.from_authorized_user_file(token_path, self.scopes)
        self.service = build("gmail", "v1", credentials=creds)

    def get_emails(self, query = (
            f'has:attachment '
            f'(subject:חשבונית OR subject:קבלה OR subject:invoice OR subject:receipt OR '
            f'"חשבונית מס" OR "Tax Invoice" OR "Receipt")'
    ), time_window=None, max_results=10, user_id="me"):
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



def main():
    print("=== Manual test: MailRetrieving ===")

    TOKEN_PATH = os.path.join(os.getcwd(),"token.json")   # must exist
    TIME_WINDOW = "6m"          # last 6 months
    MAX_RESULTS = 100           # increase if needed

    mr = MailRetrieving()

    print("[1] Connecting to Gmail...")
    mr.connect(TOKEN_PATH)
    print("    ✓ Connected")

    print(f"[2] Fetching emails from last {TIME_WINDOW}...")
    emails = mr.get_emails(time_window=TIME_WINDOW, max_results=MAX_RESULTS)

    print(f"    ✓ Fetched {len(emails)} emails")

    print("[3] Checking attachments...")
    with_attachments = 0

    for i, email_msg in enumerate(emails, start=1):
        subject = email_msg.get("Subject", "<no subject>")
        has_file = mr.has_pdf_or_image(email_msg)

        if has_file:
            with_attachments += 1

        print(
            f"    {i:02d}. "
            f"{'[PDF/IMG]' if has_file else '[NO FILE]'} "
            f"{subject}"
        )

    print("\n=== TEST SUMMARY ===")
    print(f"Total emails fetched      : {len(emails)}")
    print(f"Emails with PDF/Image     : {with_attachments}")

    if with_attachments > 0:
        print("✓ TEST PASSED: receipts detected")
    else:
        print("✗ TEST FAILED: no receipts detected")


if __name__ == "__main__":
    main()

