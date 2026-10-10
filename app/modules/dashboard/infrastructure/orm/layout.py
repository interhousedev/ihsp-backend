"""ORM model of dashboard.layouts."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import Integer, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class DashboardLayout(TimestampMixin, Base):
    """The widgets of one user; `version` is the optimistic-lock counter."""

    __tablename__ = "layouts"
    __table_args__ = ({"schema": "dashboard"},)

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    widgets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
