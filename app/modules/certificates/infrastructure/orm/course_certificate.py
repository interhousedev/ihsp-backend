"""ORM models of course certificates (schema ``certificates``)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

SCHEMA = {"schema": "certificates"}


class CourseCertificateSettingsRow(TimestampMixin, Base):
    """Certificate settings of one course."""

    __tablename__ = "course_settings"
    __table_args__ = SCHEMA

    course_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    passing_pct: Mapped[int] = mapped_column(Integer, server_default=text("60"))
    optional_section_ids: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'")
    )
    tiers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    template_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    partner_ids: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))


class CourseCertificateTemplateRow(IdMixin, TimestampMixin, Base):
    """A certificate design: background and placed fields."""

    __tablename__ = "course_templates"
    __table_args__ = SCHEMA

    course_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(120))
    background_file_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    qr: Mapped[dict[str, Any]] = mapped_column(JSONB)


class CoursePartnerRow(IdMixin, TimestampMixin, Base):
    """An organisation that co-issues the certificates of a course."""

    __tablename__ = "course_partners"
    __table_args__ = SCHEMA

    course_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(160))
    url: Mapped[str | None] = mapped_column(String(500))
    logo_file_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    co_issued: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class IssuedCourseCertificateRow(IdMixin, TimestampMixin, Base):
    """An issued certificate with a snapshot of everything printed on it."""

    __tablename__ = "issued_course_certificates"
    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_issued_course_user"),
        SCHEMA,
    )

    code: Mapped[str] = mapped_column(String(16), unique=True)
    course_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    tier_key: Mapped[str] = mapped_column(String(24))
    tier_label: Mapped[dict[str, str]] = mapped_column(JSONB)
    holder_name: Mapped[str] = mapped_column(String(240))
    course_title: Mapped[str] = mapped_column(String(300))
    partner: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    template: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    score_pct: Mapped[int] = mapped_column(Integer)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
