from sqlmodel import Session, select
from models import Attachment
from backend.db import make_engine, create_db_and_tables
from api import BASE_DIR

def test_attachment_insert_uses_db_py(tmp_path):
    db_file = tmp_path / "attachments.db"
    engine = make_engine(db_file)

    create_db_and_tables(engine)
    assert db_file.exists()

    with Session(engine) as session:
        a = Attachment(
            category="invoice",
            subject="Test",
            sender="a@b.com",
            filename="x.pdf",
            saved_path="mid/x.pdf",
            mime_type="application/pdf",
            amount_value=10.5,
            amount_currency="ILS",
            due_date_iso="2026-01-10",
        )
        session.add(a)
        session.commit()
        session.refresh(a)
        assert a.id is not None

    with Session(engine) as session:
        row = session.exec(select(Attachment).where(Attachment.filename == "x.pdf")).first()
        assert row is not None
        assert row.amount_value == 10.5
test_attachment_insert_uses_db_py(BASE_DIR)