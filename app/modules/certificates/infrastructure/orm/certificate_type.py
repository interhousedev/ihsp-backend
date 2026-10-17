"""ORM model of certificates.types."""

from typing import Any

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import Boolean, Float, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class CertificateTypeRow(IdMixin, TimestampMixin, Base):
    """A certificate type; names and levels are jsonb."""

    __tablename__ = "types"
    __table_args__ = {"schema": "certificates"}

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[dict[str, Any]] = mapped_column(JSONB)
    levels: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    asks_level: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    asks_score: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    score_min: Mapped[float | None] = mapped_column(Float)
    score_max: Mapped[float | None] = mapped_column(Float)
    asks_percent: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    asks_subject: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    asks_year: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    builtin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
