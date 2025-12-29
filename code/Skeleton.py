from __future__ import print_function
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ההרשאות שאנחנו מבקשים
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service():
    creds = None

    # אם כבר יש token.json – נטען משם
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # אם אין או שהוא פג תוקף – נעשה OAuth מחדש
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # רענון אוטומטי של ה-token
            creds.refresh(Request())
        else:
            # פעם ראשונה: יפתח דפדפן לבקשת הרשאה
            flow = InstalledAppFlow.from_client_secrets_file(
                '../backend/credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # נשמור token לשימושים הבאים
        with open('../backend/token.json', 'w') as token:
            token.write(creds.to_json())

    # יצירת אובייקט service ל-Gmail
    service = build('gmail', 'v1', credentials=creds)
    return service

if __name__ == '__main__':
    service = get_gmail_service()
    # בדיקה קטנה: הדפסת 5 מיילים אחרונים
    results = service.users().messages().list(userId='me', maxResults=5).execute()
    messages = results.get('messages', [])
    print(f"Found {len(messages)} messages")
