from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlmodel import Session, select
from sqlalchemy import func, text

from db import make_engine, create_db_and_tables, get_session

# ✅ add this import (your class that pulls from Gmail)
from mailRetrieving import *

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attachments.db"
DOWNLOADS_DIR = BASE_DIR / "downloads"

engine = make_engine(DB_PATH)

app = FastAPI(title="Bills API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    create_db_and_tables(engine)


def session_dep() -> Session:
    yield from get_session(engine)


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
        session: Session = Depends(session_dep),
):
    stmt = select(Bill)

    if category:
        stmt = stmt.where(Bill.category == category)

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (Bill.subject.like(like)) |
            (Bill.sender.like(like)) |
            (Bill.filename.like(like))
        )

    stmt = stmt.order_by(Bill.id.desc()).offset(offset).limit(limit)
    items = session.exec(stmt).all()
    return {"count": len(items), "items": items}


# ✅ Only keep these if Bill has amount_value, amount_currency, due_date_iso
@app.get("/summary")
def get_summary(session: Session = Depends(session_dep)):
    total = session.exec(
        select(func.coalesce(func.sum(Bill.amount_value), 0))
        .where(Bill.amount_value.is_not(None))
    ).one()

    by_cat_rows = session.exec(
        select(
            Bill.category,
            func.coalesce(func.sum(Bill.amount_value), 0).label("total"),
        )
        .where(Bill.amount_value.is_not(None))
        .group_by(Bill.category)
        .order_by(text("total DESC"))
    ).all()

    return {
        "total": float(total or 0),
        "by_category": [{"category": r[0], "total": float(r[1] or 0)} for r in by_cat_rows],
    }


@app.get("/upcoming")
def get_upcoming(
        days: int = Query(7, ge=1, le=365),
        session: Session = Depends(session_dep),
):
    sql = text(
        """
        SELECT
            id, category, subject, sender,
            amount_value, amount_currency,
            due_date_iso, saved_path
        FROM bills
        WHERE due_date_iso IS NOT NULL
          AND date(due_date_iso) <= date('now', :plus_days)
          AND date(due_date_iso) >= date('now')
        ORDER BY date(due_date_iso) ASC
        """
    )

    rows = session.exec(sql, {"plus_days": f"+{days} day"}).all()

    items = []
    for r in rows:
        try:
            items.append(dict(r._mapping))
        except Exception:
            items.append({
                "id": r[0], "category": r[1], "subject": r[2], "sender": r[3],
                "amount_value": r[4], "amount_currency": r[5],
                "due_date_iso": r[6], "saved_path": r[7],
            })

    return {"days": days, "count": len(items), "items": items}


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


# ===========================
# ✅ MAIN: connect to Gmail and pull bills into DB (no server required)
# Run: python api.py --pull
# or:  python -m backend.api --pull   (depends on your package layout)
# ===========================
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bills API utility")
    parser.add_argument("--pull", action="store_true", help="Pull bills from Gmail into DB")
    parser.add_argument("--time-window", default="6m", help="Gmail time window, e.g. 6m, 30d")
    parser.add_argument("--token", default=str(BASE_DIR / "token.json"), help="Path to token.json")
    parser.add_argument("--creds", default=str(BASE_DIR / "credentials.json"), help="Path to credentials.json")
    parser.add_argument("--only-media", action="store_true", default=True,
                        help="Only download pdf/png/jpg/jpeg (default: True)")
    parser.add_argument("--user", default="me", help="Gmail userId (default: me)")

    args = parser.parse_args()

    # Ensure folders + DB/tables exist
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    create_db_and_tables(engine)

    if args.pull:
        # Open a real DB session (no FastAPI server)
        with Session(engine) as session:
            mr = MailRetrieving(session=session, downloads_dir=DOWNLOADS_DIR)
            mr.connect(token_path=args.token, credentials_path=args.creds)

            result = mr.pull_bills_to_db(
                time_window=args.time_window,
                user_id=args.user,
                only_pdf_and_images=args.only_media,
            )

            print("\n✅ Pull completed:")
            for k, v in result.items():
                print(f"{k}: {v}")


if __name__ == "__main__":
    main()
