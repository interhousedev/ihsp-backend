"""ORM of the country facts a student weighs when choosing a country."""

from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base

from sqlalchemy import String, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

COUNTRY_FACT_STATUSES = ("draft", "verified")


class CountryFactsRow(CreatedMixin, UpdatedMixin, Base):
    """Facts of one country; `verified` rows are never overwritten by the seed."""

    __tablename__ = "country_facts"
    __table_args__ = (check_in("status", COUNTRY_FACT_STATUSES), S)

    country: Mapped[str] = mapped_column(String(2), primary_key=True)
    as_of: Mapped[str] = mapped_column(String(7))
    facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(8), server_default=sql_text("'draft'"))
    verified_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    """The staff member who last saved the row; None while it is still the seed."""
