from __future__ import annotations

from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class Bill(SQLModel, table=True):
    __tablename__ = "bills"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Gmail identifiers
    message_id: str = Field(index=True)
    attachment_id: str

    # Email metadata
    subject: Optional[str] = None
    sender: Optional[str] = None
    msg_date: Optional[str] = None

    # File metadata
    filename: str
    mime_type: Optional[str] = None
    saved_path: str  # relative to downloads dir

    # Simple classification
    category: str = Field(default="unknown", index=True)

    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
