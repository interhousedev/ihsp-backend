"""Ports: staff assignments and views, comments, privacy export and erase."""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from app.modules.admission.domain.access import Assignment, StaffRole
from app.modules.admission.domain.staff import (
    AuditRecord,
    CaseloadRow,
    Comment,
    SavedView,
    StaffUser,
)


class StaffDirectory(Protocol):
    """Who a user is, for assignments (identity data, read-only)."""

    async def staff_user(self, user_id: UUID) -> StaffUser | None:
        """Return the user's roles and state, or None."""
        ...


class StaffRepository(Protocol):
    """Assignments, saved views and the caseload query."""

    async def role(self, role_id: UUID) -> StaffRole | None:
        """Return a sub-role or None."""
        ...

    async def roles(self) -> list[StaffRole]:
        """Return the live (not archived) sub-roles."""
        ...

    async def assignment(self, assignment_id: UUID) -> Assignment | None:
        """Return an assignment, revoked ones included, or None."""
        ...

    async def live_assignments(self, kind: str, scope_kind: str) -> list[Assignment]:
        """Return unrevoked root assignments of a role kind and scope kind."""
        ...

    async def add_assignment(self, assignment: Assignment) -> Assignment:
        """Store a new assignment; a live duplicate is returned unchanged."""
        ...

    async def revoke_assignment(
        self, assignment_id: UUID, now: dt.datetime, reason: str
    ) -> list[Assignment]:
        """Revoke the assignment and its delegated children; return all revoked."""
        ...

    async def caseload(
        self, student_ids: Sequence[UUID] | None, now: dt.datetime
    ) -> list[CaseloadRow]:
        """Return a row per student with a profile; None means every student."""
        ...

    async def saved_views(self, user_id: UUID) -> list[SavedView]:
        """Return the user's saved views."""
        ...

    async def add_saved_view(self, view: SavedView) -> SavedView:
        """Store a saved view."""
        ...

    async def update_saved_view(self, view: SavedView) -> SavedView:
        """Replace name, filters, sort and default flag (lock_version checked)."""
        ...

    async def delete_saved_view(self, view_id: UUID, user_id: UUID) -> bool:
        """Delete the user's view; False if it is not theirs."""
        ...


class CommentRepository(Protocol):
    """Comments on a student's objects."""

    async def add(self, comment: Comment) -> Comment:
        """Store a comment."""
        ...

    async def get(self, comment_id: UUID) -> Comment | None:
        """Return a live comment or None."""
        ...

    async def for_target(
        self, student_id: UUID, target_kind: str, target_id: UUID
    ) -> list[Comment]:
        """Return the live comments of a target, oldest first (all visibilities)."""
        ...

    async def inbox(self, student_id: UUID, limit: int) -> list[Comment]:
        """Return the student-visible comments by others, newest first."""
        ...

    async def delete(self, comment_id: UUID, now: dt.datetime) -> None:
        """Soft-delete a comment."""
        ...


class PrivacyRepository(Protocol):
    """Export, erasure and the audit view of one student's data."""

    async def export(self, student_id: UUID) -> dict[str, list[dict[str, Any]]]:
        """Return the student's rows per table, without staff-only data."""
        ...

    async def erase(self, student_id: UUID) -> dict[str, int]:
        """Delete the student's rows (not the audit log); return counts per table."""
        ...

    async def stored_file_ids(self, student_id: UUID) -> list[UUID]:
        """Return the ids of every stored file the student's rows point to."""
        ...

    async def audit(self, student_id: UUID, limit: int) -> list[AuditRecord]:
        """Return who accessed the student's data, newest first."""
        ...

    async def revoke_sharing(self, student_id: UUID, now: dt.datetime) -> None:
        """Revoke guest links and unassign helpers."""
        ...
