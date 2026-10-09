"""ORM models of notebooks.source_labels, source_label_links and source_label_runs."""

from datetime import datetime
from uuid import UUID

from app.modules.notebooks.domain.labels import LabelOrigin, LabelRunStatus
from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column


class SourceLabel(IdMixin, Base):
    """A topic label of a notebook (made by the model or by the student)."""

    __tablename__ = "source_labels"
    __table_args__ = (
        Index(
            "uq_source_labels_notebook_id_lower_name",
            "notebook_id",
            text("lower(name)"),
            unique=True,
        ),
        Index("ix_source_labels_notebook_id_position", "notebook_id", "position"),
        {"schema": "notebooks"},
    )

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(40))
    emoji: Mapped[str] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(str_enum(LabelOrigin, "origin"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SourceLabelLink(Base):
    """A label on a source; `origin` tells whether the model or the student set it."""

    __tablename__ = "source_label_links"
    __table_args__ = (
        Index("ix_source_label_links_label_id", "label_id"),
        {"schema": "notebooks"},
    )

    source_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("notebooks.sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    label_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("notebooks.source_labels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    origin: Mapped[str] = mapped_column(str_enum(LabelOrigin, "origin"))


class SourceLabelRun(Base):
    """The state of the automatic labeling of a notebook (one row at most)."""

    __tablename__ = "source_label_runs"
    __table_args__ = ({"schema": "notebooks"},)

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("notebooks.notebooks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(
        str_enum(LabelRunStatus, "status"), server_default=text("'idle'")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(40))
    started_by: Mapped[UUID | None] = mapped_column(Uuid)
