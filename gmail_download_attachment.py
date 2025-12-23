from __future__ import print_function
import os
import base64

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# הרשאות: קריאה בלבד למייל
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """
    פונקציה שמכריחה התחברות כל פעם מחדש דרך חלון התחברות של גוגל.
    לא משתמשים בכלל ב-token.json בדמו הזה.
    """
    print("מכין תהליך התחברות ל-Google (OAuth2)...")
    print("עכשיו ייפתח חלון בדפדפן לבחירת משתמש גוגל ואישור הרשאות.\n")

    # credentials.json חייב להיות בתיקייה שבה אתה מריץ את הסקריפט
    flow = InstalledAppFlow.from_client_secrets_file(
        "credentials.json", SCOPES
    )

    # זה פותח דפדפן עם מסך התחברות של גוגל
    creds = flow.run_local_server(port=0, prompt='consent')

    print("ההתחברות הצליחה! בונה אובייקט שירות של Gmail API...\n")
    service = build("gmail", "v1", credentials=creds)
    return service


def list_messages_with_attachments(service, max_results=5):
    """
    מחפש מיילים עם קבצים מצורפים.
    """
    results = service.users().messages().list(
        userId="me",
        q="has:attachment",
        maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    return messages


def download_first_attachment(service, message_id, download_dir="downloads"):
    """
    מוריד את הקובץ המצורף הראשון מהמייל שנבחר.
    """
    msg = service.users().messages().get(userId="me", id=message_id).execute()

    os.makedirs(download_dir, exist_ok=True)

    parts = msg.get("payload", {}).get("parts", [])
    if not parts:
        print("אין חלקים במייל (לא נמצא קובץ מצורף).")
        return

    for part in parts:
        filename = part.get("filename")
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")

        # אם אין שם קובץ – זה כנראה טקסט ולא קובץ מצורף
        if not filename or not attachment_id:
            continue

        attachment = service.users().messages().attachments().get(
            userId="me",
            messageId=message_id,
            id=attachment_id
        ).execute()

        file_data = base64.urlsafe_b64decode(attachment["data"].encode("UTF-8"))

        file_path = os.path.join(download_dir, filename)
        with open(file_path, "wb") as f:
            f.write(file_data)

        print(f"הקובץ נשמר ב: {file_path}")
        print("לצורך הדגמה – הורדנו רק קובץ מצורף אחד מהמייל הזה.")
        return

    print("לא נמצא אף קובץ מצורף להורדה.")


def main():
    print("🚀 דמו: התחברות לג'ימייל באמצעות OAuth2 ושליפת קובץ מצורף\n")

    # 1. מתחברים לג'ימייל דרך גוגל (תמיד יפתח חלון התחברות)
    service = get_gmail_service()

    # 2. מחפשים מיילים עם קבצים מצורפים
    messages = list_messages_with_attachments(service, max_results=5)

    if not messages:
        print("לא נמצאו מיילים עם קבצים מצורפים.")
        return

    print("מיילים עם קבצים מצורפים שנמצאו:\n")
    for i, m in enumerate(messages, start=1):
        msg = service.users().messages().get(userId="me", id=m["id"]).execute()
        snippet = msg.get("snippet", "")
        print(f"{i}. ID={m['id']} | תצוגה קצרה: {snippet[:80]}")

    # 3. מורידים קובץ מצורף מהמייל הראשון לצורך הדגמה
    first_id = messages[0]["id"]
    print(f"\n⬇ מוריד קובץ מצורף מהמייל הראשון (ID={first_id})...\n")
    download_first_attachment(service, first_id)


if __name__ == "__main__":
    main()
