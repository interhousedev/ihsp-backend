"""ORM model of notebooks.presentation_plans (PLAN)."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.presentation_plan import PlanStatus
from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import ARRAY, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class PresentationPlan(IdMixin, TimestampMixin, Base):
    """A slide outline the owner confirms before the deck is generated."""

    __tablename__ = "presentation_plans"
    __table_args__ = (
        Index("ix_presentation_plans_notebook_id_owner_id", "notebook_id", "owner_id"),
        {"schema": "notebooks"},
    )

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE")
    )
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(255))
    # [{"title": str, "bullets": [str]}], in slide order
    slides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        str_enum(PlanStatus, "status"), server_default=text("'draft'")
    )
    prompt: Mapped[str | None] = mapped_column(Text)
    source_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'")
    )
    format: Mapped[str] = mapped_column(String(16), server_default=text("'presenter'"))
    artifact_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("notebooks.artifacts.id", ondelete="SET NULL")
    )
