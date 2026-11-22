"""Project-idea runs of a student and the curated helpers."""

from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import Boolean, Index, String, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ProjectIdeaRunRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One generation: the brief the student typed and the projects the model gave."""

    __tablename__ = "project_idea_runs"
    __table_args__ = (
        check_in("locale", ("uz", "ru", "en")),
        Index("ix_project_idea_runs_student_created", "student_id", "created_at"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    locale: Mapped[str] = mapped_column(String(2))
    brief: Mapped[dict[str, Any]] = mapped_column(JSONB)
    projects: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    model: Mapped[str] = mapped_column(String(120))
    search_used: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))


class ProjectHelperRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A person or an organization curated by staff."""

    __tablename__ = "project_helpers"
    __table_args__ = (check_in("kind", ("person", "organization")), S)

    kind: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    help_types: Mapped[list[str]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    expertise_areas: Mapped[list[str]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    contacts: Mapped[dict[str, str | None]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, index=True, server_default=sql_text("true")
    )
    created_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
