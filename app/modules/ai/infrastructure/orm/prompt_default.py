"""ORM model of ai.prompt_defaults: the built-in text last published for each slot."""

from datetime import datetime

from app.shared.db.base import Base

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column


class PromptDefaultRow(Base):
    """The hash, version and text of a slot's built-in as last published at startup."""

    __tablename__ = "prompt_defaults"
    __table_args__ = {"schema": "ai"}

    task: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    hash: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, server_default=sql_text("''"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_text("now()")
    )
