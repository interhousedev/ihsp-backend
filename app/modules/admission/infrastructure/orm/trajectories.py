"""Educational trajectories and the progress students mark on their nodes."""

from typing import Any
from uuid import UUID

from app.modules.admission.domain.trajectories import NODE_STATUSES
from app.modules.admission.infrastructure.orm._common import (
    SCHEMA,
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import Boolean, ForeignKey, Index, String, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["TrajectoryProgressRow", "TrajectoryRow"]


class TrajectoryRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A roadmap of one study field; stages, nodes and edges are one JSON graph."""

    __tablename__ = "trajectories"
    __table_args__ = (S,)

    slug: Mapped[str] = mapped_column(String(80), unique=True)
    field: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    description: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    published: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    stages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    edges: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )


class TrajectoryProgressRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A student's status of one node."""

    __tablename__ = "trajectory_progress"
    __table_args__ = (
        Index(
            "uq_trajectory_progress_student_node",
            "student_id",
            "trajectory_id",
            "node_id",
            unique=True,
        ),
        check_in("status", NODE_STATUSES),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    trajectory_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.trajectories.id", ondelete="CASCADE")
    )
    node_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12))
