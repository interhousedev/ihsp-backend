"""ORM model of id.student_card_qr_tokens."""

from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class StudentCardQrTokenRow(TimestampMixin, Base):
    """The permanent QR token of a student's card; regenerating replaces it."""

    __tablename__ = "student_card_qr_tokens"
    __table_args__ = {"schema": "id"}

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
