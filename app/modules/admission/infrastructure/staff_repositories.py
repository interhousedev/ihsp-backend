"""SQL repositories of staff, comments and privacy."""

import datetime as dt
import json
from collections.abc import Sequence
from typing import Any, Final, cast
from uuid import UUID

from app.modules.admission.domain.access import (
    Assignment,
    GrantedVia,
    ScopeKind,
    StaffRole,
)
from app.modules.admission.domain.consultations import ACTIVE
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    EssayKeyUnavailableError,
    EssayVaultUnavailableError,
)
from app.modules.admission.domain.staff import (
    AuditRecord,
    CaseloadRow,
    Comment,
    SavedView,
)
from app.modules.admission.infrastructure.orm.access import (
    AuditEventRow,
    StaffAssignmentRow,
    StaffRoleRow,
    StaffSavedViewRow,
)
from app.modules.admission.infrastructure.orm.applications import (
    ChecklistItemRow,
    DocumentRow,
    DocumentVersionRow,
)
from app.modules.admission.infrastructure.orm.calendar import (
    CalendarFeedRow,
    CalendarReminderRow,
)
from app.modules.admission.infrastructure.orm.catalog import CatalogProposalRow
from app.modules.admission.infrastructure.orm.consultations import ConsultationRow
from app.modules.admission.infrastructure.orm.exemplars import ExemplarRow
from app.modules.admission.infrastructure.orm.kb import KbArticleRow
from app.modules.admission.infrastructure.orm.opp_social import (
    OppCommentReportRow,
    OppCommentRow,
)
from app.modules.admission.infrastructure.orm.opportunities import (
    OpportunityRow,
    OpportunitySubmissionRow,
)
from app.modules.admission.infrastructure.orm.profile import (
    CommentRow,
    ItemRow,
    ProfileRow,
    ProofRow,
)
from app.modules.admission.infrastructure.orm.sealed import SEALED_COLUMNS, SEALED_JSON
from app.modules.admission.infrastructure.repositories import _role
from app.modules.admission.ports.essay_crypto import EssayCipher
from app.shared.db.base import Base
from app.shared.ids import new_id

import structlog
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

DONE_ITEMS = ("done", "n_a")
SECRET_COLUMNS = frozenset({"token_hash", "token_prefix", "session_hash", "ip_hash"})
"""Columns that never leave the server in an export."""
EXPORT_FILTERS: dict[str, tuple[str, Any]] = {
    "comments": ("visibility", "student_and_staff"),
    "documents": ("visibility", "student"),
}
"""Tables exported only for the rows the student may see."""


def _assignment(a: StaffAssignmentRow, role: StaffRole) -> Assignment:
    return Assignment(
        id=a.id,
        user_id=a.user_id,
        role=role,
        scope_kind=cast(ScopeKind, a.scope_kind),
        scope_ref=a.scope_ref,
        starts_at=a.starts_at,
        expires_at=a.expires_at,
        granted_by=a.granted_by,
        granted_via=cast(GrantedVia, a.granted_via),
        parent_assignment_id=a.parent_assignment_id,
        revoked_at=a.revoked_at,
    )


def _view(r: StaffSavedViewRow) -> SavedView:
    return SavedView(
        id=r.id,
        user_id=r.user_id,
        name=r.name,
        filters=dict(r.filters or {}),
        sort=r.sort,
        is_default=r.is_default,
        lock_version=r.lock_version,
    )


def _comment(r: CommentRow) -> Comment:
    return Comment(
        id=r.id,
        student_id=r.student_id,
        target_kind=r.target_kind,
        target_id=r.target_id,
        author_id=r.author_id,
        body=r.body,
        visibility=r.visibility,
        created_at=r.created_at,
        anchor=r.anchor,
    )


class SqlStaffRepository:
    """Assignments, saved views and the caseload query."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def role(self, role_id: UUID) -> StaffRole | None:
        """Return a sub-role or None."""
        row = await self._s.get(StaffRoleRow, role_id)
        return _role(row) if row else None

    async def roles(self) -> list[StaffRole]:
        """Return the live (not archived) sub-roles, builtin first."""
        rows = await self._s.scalars(
            select(StaffRoleRow)
            .where(StaffRoleRow.archived_at.is_(None))
            .order_by(StaffRoleRow.kind, StaffRoleRow.name)
        )
        return [_role(r) for r in rows]

    async def assignment(self, assignment_id: UUID) -> Assignment | None:
        """Return an assignment or None."""
        row = await self._s.get(StaffAssignmentRow, assignment_id)
        if row is None:
            return None
        role = await self.role(row.staff_role_id)
        return _assignment(row, role) if role else None

    async def live_assignments(self, kind: str, scope_kind: str) -> list[Assignment]:
        """Return unrevoked root assignments of a role kind and scope kind."""
        rows = (
            await self._s.scalars(
                select(StaffAssignmentRow)
                .join(StaffRoleRow, StaffRoleRow.id == StaffAssignmentRow.staff_role_id)
                .where(
                    StaffRoleRow.kind == kind,
                    StaffAssignmentRow.scope_kind == scope_kind,
                    StaffAssignmentRow.revoked_at.is_(None),
                    StaffAssignmentRow.parent_assignment_id.is_(None),
                )
                .order_by(StaffAssignmentRow.starts_at)
            )
        ).all()
        out: list[Assignment] = []
        for row in rows:
            role = await self.role(row.staff_role_id)
            if role is not None:
                out.append(_assignment(row, role))
        return out

    async def add_assignment(self, assignment: Assignment) -> Assignment:
        """Store a new assignment; a live duplicate is returned unchanged."""
        live = await self._s.scalar(
            select(StaffAssignmentRow).where(
                StaffAssignmentRow.user_id == assignment.user_id,
                StaffAssignmentRow.staff_role_id == assignment.role.id,
                StaffAssignmentRow.scope_kind == assignment.scope_kind,
                StaffAssignmentRow.scope_ref.is_not_distinct_from(assignment.scope_ref),
                StaffAssignmentRow.revoked_at.is_(None),
            )
        )
        if live is not None:
            return _assignment(live, assignment.role)
        row = StaffAssignmentRow(
            id=new_id(),
            user_id=assignment.user_id,
            staff_role_id=assignment.role.id,
            scope_kind=assignment.scope_kind,
            scope_ref=assignment.scope_ref,
            starts_at=assignment.starts_at,
            expires_at=assignment.expires_at,
            granted_by=assignment.granted_by,
            granted_via=assignment.granted_via,
            parent_assignment_id=assignment.parent_assignment_id,
        )
        self._s.add(row)
        await self._s.flush()
        return _assignment(row, assignment.role)

    async def revoke_assignment(
        self, assignment_id: UUID, now: dt.datetime, reason: str
    ) -> list[Assignment]:
        """Revoke the assignment and its delegated descendants."""
        done: list[Assignment] = []
        queue = [assignment_id]
        while queue:
            current = queue.pop()
            row = await self._s.get(StaffAssignmentRow, current)
            if row is None or row.revoked_at is not None:
                continue
            row.revoked_at = now
            row.revoked_reason = reason
            role = await self.role(row.staff_role_id)
            if role is not None:
                done.append(_assignment(row, role))
            children = await self._s.scalars(
                select(StaffAssignmentRow.id).where(
                    StaffAssignmentRow.parent_assignment_id == current,
                    StaffAssignmentRow.revoked_at.is_(None),
                )
            )
            queue.extend(children)
        await self._s.flush()
        return done

    async def caseload(
        self, student_ids: Sequence[UUID] | None, now: dt.datetime
    ) -> list[CaseloadRow]:
        """Return a row per student with a profile."""
        open_item = ChecklistItemRow.status.not_in(DONE_ITEMS)
        items = (
            select(
                ChecklistItemRow.student_id.label("sid"),
                func.min(ChecklistItemRow.due_utc).filter(open_item).label("next_due"),
                func.count()
                .filter(and_(open_item, ChecklistItemRow.due_utc < now))
                .label("overdue"),
            )
            .group_by(ChecklistItemRow.student_id)
            .subquery()
        )
        helps = (
            select(
                ConsultationRow.student_id.label("sid"),
                func.count().label("open_help"),
            )
            .where(ConsultationRow.status.in_(ACTIVE))
            .group_by(ConsultationRow.student_id)
            .subquery()
        )
        stmt = (
            select(
                ProfileRow.student_id,
                ProfileRow.stage,
                items.c.next_due,
                func.coalesce(items.c.overdue, 0),
                func.coalesce(helps.c.open_help, 0),
            )
            .outerjoin(items, items.c.sid == ProfileRow.student_id)
            .outerjoin(helps, helps.c.sid == ProfileRow.student_id)
            .order_by(items.c.next_due.asc().nulls_last(), ProfileRow.student_id)
        )
        if student_ids is not None:
            stmt = stmt.where(ProfileRow.student_id.in_(list(student_ids)))
        rows = await self._s.execute(stmt)
        return [CaseloadRow(*r) for r in rows.tuples()]

    async def saved_views(self, user_id: UUID) -> list[SavedView]:
        """Return the user's saved views."""
        rows = await self._s.scalars(
            select(StaffSavedViewRow)
            .where(StaffSavedViewRow.user_id == user_id)
            .order_by(StaffSavedViewRow.created_at)
        )
        return [_view(r) for r in rows]

    async def add_saved_view(self, view: SavedView) -> SavedView:
        """Store a saved view."""
        row = StaffSavedViewRow(
            id=new_id(),
            user_id=view.user_id,
            name=view.name,
            scope_kind="all",
            filters=view.filters,
            sort=view.sort,
            is_default=view.is_default,
        )
        self._s.add(row)
        await self._s.flush()
        return _view(row)

    async def update_saved_view(self, view: SavedView) -> SavedView:
        """Replace the view's fields; a stale lock_version raises a conflict."""
        row = await self._s.get(StaffSavedViewRow, view.id)
        if row is None or row.user_id != view.user_id:
            raise AdmissionConflictError()
        if row.lock_version != view.lock_version:
            raise AdmissionConflictError()
        row.name, row.filters = view.name, view.filters
        row.sort, row.is_default = view.sort, view.is_default
        row.lock_version += 1
        await self._s.flush()
        return _view(row)

    async def delete_saved_view(self, view_id: UUID, user_id: UUID) -> bool:
        """Delete the user's view."""
        res = await self._s.execute(
            delete(StaffSavedViewRow).where(
                StaffSavedViewRow.id == view_id, StaffSavedViewRow.user_id == user_id
            )
        )
        return bool(cast(Any, res).rowcount)


class SqlCommentRepository:
    """Comments on a student's objects."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def add(self, comment: Comment) -> Comment:
        """Store a comment."""
        row = CommentRow(
            id=new_id(),
            student_id=comment.student_id,
            target_kind=comment.target_kind,
            target_id=comment.target_id,
            anchor=comment.anchor,
            author_id=comment.author_id,
            body=comment.body,
            visibility=comment.visibility,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _comment(row)

    async def get(self, comment_id: UUID) -> Comment | None:
        """Return a live comment or None."""
        row = await self._s.get(CommentRow, comment_id)
        return _comment(row) if row and row.deleted_at is None else None

    async def for_target(
        self, student_id: UUID, target_kind: str, target_id: UUID
    ) -> list[Comment]:
        """Return the live comments of a target, oldest first."""
        rows = await self._s.scalars(
            select(CommentRow)
            .where(
                CommentRow.student_id == student_id,
                CommentRow.target_kind == target_kind,
                CommentRow.target_id == target_id,
                CommentRow.deleted_at.is_(None),
            )
            .order_by(CommentRow.created_at)
        )
        return [_comment(r) for r in rows]

    async def inbox(self, student_id: UUID, limit: int) -> list[Comment]:
        """Return the student-visible comments written by others."""
        rows = await self._s.scalars(
            select(CommentRow)
            .where(
                CommentRow.student_id == student_id,
                CommentRow.author_id != student_id,
                CommentRow.visibility == "student_and_staff",
                CommentRow.deleted_at.is_(None),
            )
            .order_by(CommentRow.created_at.desc())
            .limit(limit)
        )
        return [_comment(r) for r in rows]

    async def delete(self, comment_id: UUID, now: dt.datetime) -> None:
        """Soft-delete a comment."""
        await self._s.execute(
            update(CommentRow).where(CommentRow.id == comment_id).values(deleted_at=now)
        )


def _student_tables() -> list[Any]:
    """Admission tables with a student_id column, parents before children."""
    return [
        t
        for t in Base.metadata.sorted_tables
        if t.schema == "admission"
        and "student_id" in t.c
        and t.name != AuditEventRow.__tablename__
    ]


_USER_KEYED: Final[tuple[tuple[Any, str], ...]] = (
    (CalendarFeedRow.__table__, "user_id"),
    (CalendarReminderRow.__table__, "user_id"),
    (CatalogProposalRow.__table__, "proposed_by"),
    (OpportunitySubmissionRow.__table__, "submitted_by"),
    (OppCommentReportRow.__table__, "reporter_id"),
    (OppCommentRow.__table__, "author_id"),
)
"""Tables keyed by user rather than student; their rows are deleted."""

_USER_NULLED: Final[tuple[tuple[Any, str], ...]] = (
    (ExemplarRow.__table__, "created_by"),
    (ExemplarRow.__table__, "updated_by"),
    (KbArticleRow.__table__, "author_id"),
    (OpportunityRow.__table__, "created_by"),
)
"""Shared content that outlives its author; the reference is cleared."""


class SqlPrivacyRepository:
    """Export, erasure and audit view, generic over the student tables."""

    def __init__(self, session: AsyncSession, cipher: EssayCipher) -> None:
        """Keep the open session and the cipher of the sealed essay columns."""
        self._s = session
        self._cipher = cipher

    async def export(self, student_id: UUID) -> dict[str, list[dict[str, Any]]]:
        """Return the student's rows per table, without staff-only data."""
        out: dict[str, list[dict[str, Any]]] = {}
        for table in _student_tables():
            cond = [table.c.student_id == student_id]
            if table.name == "comments":
                cond.append(table.c.deleted_at.is_(None))
            if table.name in EXPORT_FILTERS:
                col, value = EXPORT_FILTERS[table.name]
                cond.append(table.c[col] == value)
            cols = [c for c in table.c if c.name not in SECRET_COLUMNS]
            rows = await self._s.execute(select(*cols).where(*cond))
            data = [dict(r._mapping) for r in rows]
            if table.name in SEALED_COLUMNS:
                data = [await self._opened(table.name, d) for d in data]
            if data:
                out[table.name] = data
        return out

    async def _opened(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        """Replace the sealed blobs of a row with their plaintext (None if lost)."""
        failed = 0
        for col in SEALED_COLUMNS[table] & row.keys():
            blob = row[col]
            if blob is None:
                continue
            try:
                text = await self._cipher.open(
                    row["student_id"], row["id"], col, bytes(blob)
                )
            except (ValueError, EssayKeyUnavailableError, EssayVaultUnavailableError):
                failed += 1
                row[col] = None
                continue
            row[col] = json.loads(text) if (table, col) in SEALED_JSON else text
        if failed:
            log.warning("essay_export_unreadable", table=table, columns=failed)
        return row

    async def erase(self, student_id: UUID) -> dict[str, int]:
        """Delete the student's rows, children first."""
        counts: dict[str, int] = {}
        for table in reversed(_student_tables()):
            res = await self._s.execute(
                delete(table).where(table.c.student_id == student_id)
            )
            n = cast(Any, res).rowcount or 0
            if n:
                counts[table.name] = n
        for table, col in _USER_KEYED:
            res = await self._s.execute(delete(table).where(table.c[col] == student_id))
            n = cast(Any, res).rowcount or 0
            if n:
                counts[table.name] = n
        for table, col in _USER_NULLED:
            res = await self._s.execute(
                update(table).where(table.c[col] == student_id).values({col: None})
            )
            n = cast(Any, res).rowcount or 0
            if n:
                counts[table.name] = n
        return counts

    async def stored_file_ids(self, student_id: UUID) -> list[UUID]:
        """Return the file ids of document versions and proofs."""
        docs = select(DocumentVersionRow.file_id).where(
            DocumentVersionRow.document_id.in_(
                select(DocumentRow.id).where(DocumentRow.student_id == student_id)
            )
        )
        proofs = select(ProofRow.file_id).where(
            ProofRow.file_id.is_not(None),
            ProofRow.item_id.in_(
                select(ItemRow.id).where(ItemRow.student_id == student_id)
            ),
        )
        rows = await self._s.scalars(docs.union(proofs))
        return list(rows)

    async def audit(self, student_id: UUID, limit: int) -> list[AuditRecord]:
        """Return who accessed the student's data, newest first."""
        rows = await self._s.execute(
            select(
                AuditEventRow.at,
                AuditEventRow.actor_kind,
                AuditEventRow.action,
                AuditEventRow.object_type,
                AuditEventRow.object_id,
                AuditEventRow.staff_role_id,
            )
            .where(AuditEventRow.student_id == student_id)
            .order_by(AuditEventRow.at.desc())
            .limit(limit)
        )
        return [AuditRecord(*r) for r in rows.tuples()]
