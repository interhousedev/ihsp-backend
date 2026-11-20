"""ORM model of ai.pipeline_routes (the runtime route of each pipeline)."""

from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import CheckConstraint, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class PipelineRouteRow(TimestampMixin, Base):
    """Where a pipeline's calls go; a null column falls through to the environment."""

    __tablename__ = "pipeline_routes"
    __table_args__ = (
        CheckConstraint(
            "reasoning_effort IS NULL OR "
            "reasoning_effort IN ('none', 'minimal', 'low', 'medium', 'high')",
            name="reasoning_effort",
        ),
        {"schema": "ai"},
    )

    pipeline: Mapped[str] = mapped_column(String(32), primary_key=True)
    # no foreign key: the built-in connectors live in the environment, not the table
    connector_id: Mapped[str | None] = mapped_column(String(48))
    model: Mapped[str | None] = mapped_column(String(255))
    reasoning_effort: Mapped[str | None] = mapped_column(String(16))
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
