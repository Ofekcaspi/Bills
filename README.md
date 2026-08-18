# Bills

Connects to a Gmail inbox, finds bill/receipt emails, extracts the amount owed and due date, and shows them in a dashboard — with a chat assistant for asking questions about your spending.

- `backend/Bills/` — Django + DRF API
- `frontend/bills/` — React (Vite) UI

## Project structure

```
backend/Bills/
  manage.py
  requirements.txt
  credentials.json        (gitignored — Google OAuth client config, not included in the repo)
  db.sqlite3               (gitignored — local SQLite database)
  Bills/
    settings.py             Django settings, Gmail/OpenAI config
    urls.py                  API routes
    views.py                  The API endpoints: connect Gmail, sync, list bills, export reports, serve files
    models.py                  DB tables: Gmail accounts, bills/receipts, chat history
    gmailConnect.py              Gmail OAuth: sign-in flow + token storage
    gmail_fetcher.py              Searches Gmail and pulls out matching bill/receipt emails
    BillClassifier.py              ML classifier: is this document a bill, a receipt, or neither
    categorizer.py                  Rule-based category tagging (electricity, water, etc.)
    pdf_analysis.py                  Reads a PDF/email and extracts the amount owed + due date
    hebrew_text.py                    Fixes Hebrew text that PDFs/emails hand back reversed
    text_cleaning.py                   Strips invisible characters that break text matching
    file_naming.py                      Safe, collision-free file naming helpers
    chat_service.py                      Talks to OpenAI for the insights chat
    migrations/                           Django DB migrations

frontend/bills/
  package.json
  src/
    App.jsx                 Root component
    pages/                   One file per screen: Home, Bills, Analysis, Reports
    constants/                Shared constants: API URL, filter options, thresholds
    hooks/useAnimatedNumber.js  Animates KPI numbers counting up/down
    services/dashboardApi.js     All calls to the backend API
    utils/billUtils.js            Formatting/parsing helpers shared across pages
    styles/App.css
```

## Prerequisites

- Python 3.12+
- Node 18+
- A Google account you're comfortable connecting (read-only Gmail access)

## Installing the backend

```bash
cd backend/Bills
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

The server must run on `127.0.0.1:8000` specifically — the Gmail OAuth redirect URI is hardcoded to that host/port in `Bills/settings.py`.

Optional: set `OPENAI_API_KEY` in your environment for the chat feature to work — everything else (sync, dashboard, reports) works without it.

## Installing the frontend

```bash
cd frontend/bills
npm install
npm run dev
```

Runs at `http://localhost:5173` by default, which the backend already allows via CORS.
