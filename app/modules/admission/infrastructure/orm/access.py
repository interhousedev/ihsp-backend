"""Access, entitlement, audit and runtime settings tables (§3.1)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    LockMixin,
    S,
    UpdatedMixin,
    check_in,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column


class EntitlementRow(CreatedMixin, UpdatedMixin, LockMixin, Base):
    """Admission eligibility of one user."""

    __tablename__ = "entitlements"
    __table_args__ = (check_in("kind", ("school_student", "alumni", "staff")), S)

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    cohort_year: Mapped[int | None] = mapped_column(Integer)
    granted_by: Mapped[UUID | None] = mapped_column(Uuid)
    granted_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]


class StaffRoleRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A permission bundle; built-ins are seeded by the migration."""

    __tablename__ = "staff_roles"
    __table_args__ = (
        check_in("kind", ("counselor", "mentor", "transcript_officer")),
        max_len("name", 60),
        S,
    )

    key: Mapped[str | None] = mapped_column(String(40), unique=True)
    kind: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(60))
    name_i18n: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    is_builtin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    archived_at: Mapped[datetime | None]


class StaffAssignmentRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A staff role granted to a user over a scope."""

    __tablename__ = "staff_assignments"
    __table_args__ = (
        check_in("scope_kind", ("all", "cohort", "student")),
        check_in("granted_via", ("admin", "delegation")),
        Index(
            "uq_staff_assignments_live",
            "user_id",
            "staff_role_id",
            "scope_kind",
            "scope_ref",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_staff_assignments_scope", "scope_kind", "scope_ref"),
        S,
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    staff_role_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.staff_roles.id", ondelete="RESTRICT")
    )
    scope_kind: Mapped[str] = mapped_column(String(8))
    scope_ref: Mapped[UUID | None] = mapped_column(Uuid)
    starts_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None]
    granted_by: Mapped[UUID | None] = mapped_column(Uuid)
    granted_via: Mapped[str] = mapped_column(String(12))
    parent_assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.staff_assignments.id", ondelete="CASCADE"), index=True
    )
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(String(40))


class OfficerSettingsRow(CreatedMixin, LockMixin, Base):
    """A transcript officer's pickup location."""

    __tablename__ = "officer_settings"
    __table_args__ = (S,)

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    pickup_location: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class StaffSavedViewRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A staff member's saved student-list filter (max 20 per user)."""

    __tablename__ = "staff_saved_views"
    __table_args__ = (
        check_in("scope_kind", ("all", "cohort", "student")),
        max_len("name", 60),
        S,
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(60))
    scope_kind: Mapped[str] = mapped_column(String(8))
    scope_ref: Mapped[UUID | None] = mapped_column(Uuid)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    sort: Mapped[str | None] = mapped_column(String(40))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class AuditEventRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """Append-only audit trail of reads and changes of student data."""

    __tablename__ = "audit_events"
    __table_args__ = (
        check_in("actor_kind", ("user", "guest", "system")),
        Index("ix_audit_events_student_id_at", "student_id", "at"),
        S,
    )

    at: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_kind: Mapped[str] = mapped_column(String(8))
    action: Mapped[str] = mapped_column(String(60))
    student_id: Mapped[UUID | None] = mapped_column(Uuid)
    object_type: Mapped[str | None] = mapped_column(String(40))
    object_id: Mapped[UUID | None] = mapped_column(Uuid)
    staff_role_id: Mapped[UUID | None] = mapped_column(Uuid)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'")
    )
    ip_hash: Mapped[str | None] = mapped_column(String(64))


class RuntimeSettingRow(CreatedMixin, Base):
    """One admin-editable admission setting (addendum: 30 s cache)."""

    __tablename__ = "runtime_settings"
    __table_args__ = (S,)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
