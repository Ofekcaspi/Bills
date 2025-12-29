from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import base64
from email import message_from_bytes

creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/gmail.readonly"])
service = build('gmail', 'v1', credentials=creds)

results = service.users().messages().list(userId='me', q='has:attachment').execute()
messages = results.get('messages', [])

for msg in messages:
    msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()

class mailRetrieving:
    def __init__(self):

    def connect(self):


