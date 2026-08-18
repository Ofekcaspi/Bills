## Bills - Automated Invoice & Receipt Tracker

Tracking invoices and receipts from email is a routine but tedious part of managing a household or small business. **Bills** automates this process by connecting to Gmail via OAuth 2.0, scanning emails over a selected date range, and identifying invoices and receipts.

Each document goes through:

* **Classification** — ML-based document type detection.
* **Data extraction** — extracts amount, currency, and due date from Hebrew and English text.
* **Categorization** — assigns expenses to categories such as electricity, water, and property tax.

Results are stored in a database and presented through a web interface with invoice/receipt lists, dashboards, expense analytics, reports, and a chatbot.

### Google OAuth Setup

The `credentials.json` file is **not included in the repository** for security reasons.

To connect a Gmail account, obtain the project's `credentials.json` OAuth configuration file from the project team and place it in:

```text
backend/Bills/credentials.json
```

The Google OAuth application is currently in **Testing mode**, so only accounts added to the Google Cloud **Test Users** list can authorize the application. If your Google account has not been added, contact the project team before attempting to connect Gmail.

> You do not need to provide your Gmail password or personal Google credentials. You authenticate through Google's OAuth flow using your own Google account.

## Project Structure

```text
backend/Bills/          Django + DRF API
frontend/bills/         React (Vite) UI
```

## Prerequisites

* Python 3.12+
* Node 18+
* A Google account added to the application's OAuth Test Users list

## Installing the Backend

```bash
cd backend/Bills
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

The server must run on `127.0.0.1:8000`, as the Gmail OAuth redirect URI is configured for this address.

Optionally, set `OPENAI_API_KEY` in your environment for the chatbot feature. The rest of the application works without it.

## Installing the Frontend

```bash
cd frontend/bills
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` by default.
