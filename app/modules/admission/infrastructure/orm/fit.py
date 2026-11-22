"""ORM of the fit preferences and the professions plan (ikigai)."""

from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
)
from app.shared.db.base import Base

from sqlalchemy import Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["FitPreferencesRow", "ProfessionPlanRow"]


class FitPreferencesRow(CreatedMixin, UpdatedMixin, Base):
    """One student's 1..10 ratings of what matters in a university."""

    __tablename__ = "fit_preferences"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    ratings: Mapped[dict[str, int]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )


class ProfessionPlanRow(CreatedMixin, UpdatedMixin, Base):
    """One student's ranked ISCO professions and ikigai chips."""

    __tablename__ = "profession_plans"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    chosen: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    ikigai: Mapped[dict[str, list[str]]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    custom: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
