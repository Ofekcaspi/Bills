from sqlmodel import SQLModel, create_engine, Session
from typing import Generator
from pathlib import Path

def make_engine(db_path: Path):
    return create_engine(
        f"sqlite:///{db_path.resolve()}",
        echo=False,
        connect_args={"check_same_thread": False},
    )

def create_db_and_tables(engine) -> None:
    SQLModel.metadata.create_all(engine)

def get_session(engine) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
