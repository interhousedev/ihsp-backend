"""Ports: repositories of the admission foundation (access, courses, settings)."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from app.modules.admission.domain.access import Assignment, Entitlement
from app.modules.admission.domain.courses import Course

AuditActorKind = Literal["user", "guest", "system"]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One row of `admission.audit_events` (§4.6)."""

    action: str
    actor_id: UUID | None
    student_id: UUID | None
    actor_kind: AuditActorKind = "user"
    object_type: str | None = None
    object_id: UUID | None = None
    staff_role_id: UUID | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OptIns:
    """The mentoring switches of one profile."""

    mentee_opt_in: bool = False
    mentor_opt_in: bool = False


class AccessRepository(Protocol):
    """Entitlements, staff assignments, help grants and the audit log."""

    async def entitlement(self, user_id: UUID) -> Entitlement | None:
        """Return the stored entitlement row, revoked or not."""
        ...

    async def assignments_for(self, user_id: UUID) -> tuple[Assignment, ...]:
        """Return the user's unrevoked assignments with their roles."""
        ...

    async def helper_of(self, user_id: UUID, now: dt.datetime) -> frozenset[UUID]:
        """Return the students whose live help requests the user was given."""
        ...

    async def opt_ins(self, user_ids: Sequence[UUID]) -> dict[UUID, OptIns]:
        """Return the mentoring switches of the users that have a profile."""
        ...

    def audit(self, event: AuditEvent) -> None:
        """Queue an audit event in the open transaction."""
        ...


class CourseRepository(Protocol):
    """Stored course rows of student profiles."""

    async def list_for(self, student_id: UUID) -> list[Course]:
        """Return the student's stored rows."""
        ...

    async def get(self, course_id: UUID) -> Course | None:
        """Return one row."""
        ...

    async def find(
        self, student_id: UUID, source: str, source_ref: str
    ) -> Course | None:
        """Return the stored row of a source course."""
        ...

    async def add(self, course: Course) -> Course:
        """Insert a row; returns it with id and creation time."""
        ...

    async def set_included(self, course_id: UUID, included: bool) -> Course:
        """Change the `included` flag of a stored row."""
        ...


class RuntimeSettingsRepository(Protocol):
    """Admin-edited values of `admission.runtime_settings`."""

    async def load(self) -> dict[str, Any]:
        """Return every stored key and value."""
        ...
