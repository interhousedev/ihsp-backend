"""ORM model of certificates.types."""

from typing import Any

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import Boolean, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class CertificateTypeRow(IdMixin, TimestampMixin, Base):
    """A certificate type; names and custom fields are jsonb."""

    __tablename__ = "types"
    __table_args__ = {"schema": "certificates"}

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[dict[str, Any]] = mapped_column(JSONB)
    builtin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    custom_fields: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'")
    )
