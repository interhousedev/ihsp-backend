"""ORM model of ai.ai_requests: the registry of AI requests published by the code."""

from datetime import datetime
from typing import Any

from app.shared.db.base import Base

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class AiRequestRow(Base):
    """One registered request; `retired` once the code no longer declares it."""

    __tablename__ = "ai_requests"
    __table_args__ = {"schema": "ai"}

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_app: Mapped[str] = mapped_column(String(32))
    task: Mapped[str] = mapped_column(String(64))
    template_id: Mapped[str] = mapped_column(String(128))
    args_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'")
    )
    tools: Mapped[list[Any]] = mapped_column(JSONB, server_default=sql_text("'[]'"))
    summary: Mapped[str] = mapped_column(Text, server_default=sql_text("''"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retired: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    code_version: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_text("now()")
    )
