"""ORM models of notebook sharing: grants, links and attached source sets."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column


class NotebookShareRow(Base):
    """A person's access to a notebook; a revoked row keeps them out of the link."""

    __tablename__ = "notebook_shares"
    __table_args__ = (
        CheckConstraint("via IN ('direct', 'link')", name="via"),
        Index("ix_notebook_shares_user_id", "user_id"),
        {"schema": "notebooks"},
    )

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    via: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotebookShareLinkRow(Base):
    """The notebook's one active link; only the hash of the token is stored."""

    __tablename__ = "notebook_share_links"
    __table_args__ = {"schema": "notebooks"}

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotebookLinkedSetRow(Base):
    """A notebook attached to another one as a live set of sources."""

    __tablename__ = "notebook_linked_sets"
    __table_args__ = (
        CheckConstraint("notebook_id <> linked_notebook_id", name="not_self"),
        Index("ix_notebook_linked_sets_linked_notebook_id", "linked_notebook_id"),
        {"schema": "notebooks"},
    )

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE"), primary_key=True
    )
    linked_notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
