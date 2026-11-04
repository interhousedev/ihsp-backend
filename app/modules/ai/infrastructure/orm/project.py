"""ORM models of ai.projects and ai.project_files."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class Project(IdMixin, TimestampMixin, Base):
    """A named group of student chats with its own files and instructions."""

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_owner_id", "owner_id"),
        {"schema": "ai"},
    )

    owner_id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(120))
    instructions: Mapped[str] = mapped_column(Text, server_default=text("''"))


class ProjectFile(TimestampMixin, Base):
    """A file of the student attached to a project (the file lives in `files`)."""

    __tablename__ = "project_files"
    __table_args__ = (
        Index("ix_project_files_file_id", "file_id"),
        {"schema": "ai"},
    )

    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ai.projects.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
