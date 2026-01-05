from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attachments.db"
DOWNLOADS_DIR = BASE_DIR / "downloads"

app = FastAPI(title="Bills API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # פיתוח בלבד
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(f"DB not found at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_dicts(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


@app.get("/")
def root():
    return {
        "status": "ok",
        "db_path": str(DB_PATH),
        "downloads_dir": str(DOWNLOADS_DIR),
        "docs": "/docs",
    }


@app.get("/bills")
def get_bills(
        category: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
):
    sql = """
        SELECT
            id, category, subject, sender, msg_date, snippet,
            filename, saved_path, mime_type,
            amount_value, amount_currency, due_date_iso,
            created_at
        FROM attachments
        WHERE 1=1
    """
    params = []

    if category:
        sql += " AND category = ?"
        params.append(category)

    if q:
        sql += " AND (subject LIKE ? OR sender LIKE ? OR filename LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])

    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return {"count": len(rows), "items": rows_to_dicts(rows)}


@app.get("/summary")
def get_summary():
    with get_conn() as conn:
        total_row = conn.execute(
            "SELECT COALESCE(SUM(amount_value), 0) AS total FROM attachments WHERE amount_value IS NOT NULL"
        ).fetchone()

        by_cat = conn.execute(
            """
            SELECT category, COALESCE(SUM(amount_value), 0) AS total
            FROM attachments
            WHERE amount_value IS NOT NULL
            GROUP BY category
            ORDER BY total DESC
            """
        ).fetchall()

    return {
        "total": float(total_row["total"] or 0),
        "by_category": [{"category": r["category"], "total": float(r["total"] or 0)} for r in by_cat],
    }


@app.get("/upcoming")
def get_upcoming(days: int = Query(7, ge=1, le=365)):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id, category, subject, sender,
                amount_value, amount_currency,
                due_date_iso, saved_path
            FROM attachments
            WHERE due_date_iso IS NOT NULL
              AND date(due_date_iso) <= date('now', ?)
              AND date(due_date_iso) >= date('now')
            ORDER BY date(due_date_iso) ASC
            """,
            (f"+{days} day",),
        ).fetchall()

    return {"days": days, "count": len(rows), "items": rows_to_dicts(rows)}


@app.get("/files/{relative_path:path}")
def get_file(relative_path: str):
    relative_path = relative_path.replace("\\", "/")
    requested = (DOWNLOADS_DIR / relative_path).resolve()
    downloads_resolved = DOWNLOADS_DIR.resolve()

    if downloads_resolved not in requested.parents and requested != downloads_resolved:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(requested),
        filename=requested.name,
        media_type="application/pdf",
    )
