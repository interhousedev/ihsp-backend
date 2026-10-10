"""ORM model of id.users."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class User(IdMixin, TimestampMixin, Base):
    """A person: student, teacher, administrator (README -> Models -> User)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("login", name="uq_users_login"),
        UniqueConstraint(
            "activation_token_hash", name="uq_users_activation_token_hash"
        ),
        UniqueConstraint("emis_student_id", name="uq_users_emis_student_id"),
        UniqueConstraint("emis_teacher_id", name="uq_users_emis_teacher_id"),
        UniqueConstraint("emis_vault_ref", name="uq_users_emis_vault_ref"),
        Index("ix_users_roles", "roles", postgresql_using="gin"),
        Index(
            "ix_users_recovery_email_lower",
            text("lower(recovery_email)"),
            unique=True,
        ),
        {"schema": "id"},
    )

    login: Mapped[str | None] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(Text)
    # True while the password was set by an administrator and is not changed yet.
    password_change_required: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )
    first_name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[str] = mapped_column(String(255))
    middle_name: Mapped[str | None] = mapped_column(String(255))
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    recovery_email: Mapped[str | None] = mapped_column(String(320))
    recovery_email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    otp_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    otp_via_email: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(
        Enum(
            "unregistered",
            "pending_activation",
            "active",
            "blocked",
            "deactivated",
            "deleted",
            name="status",
            native_enum=False,
            create_constraint=True,
        )
    )
    auth_epoch: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    activation_token_hash: Mapped[str | None] = mapped_column(String(64))
    activation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    activation_purpose: Mapped[str | None] = mapped_column(
        Enum(
            "activate",
            "reset_password",
            name="activation_purpose",
            native_enum=False,
            create_constraint=True,
        )
    )
    emis_student_id: Mapped[int | None] = mapped_column(Integer)
    emis_teacher_id: Mapped[int | None] = mapped_column(Integer)
    emis_vault_ref: Mapped[UUID | None] = mapped_column(Uuid)
    emis_status: Mapped[str | None] = mapped_column(
        Enum(
            "active",
            "needs_reauth",
            name="emis_status",
            native_enum=False,
            create_constraint=True,
        )
    )
    mail_suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    otp_reset_effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    otp_reset_request_id: Mapped[UUID | None] = mapped_column(Uuid)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
