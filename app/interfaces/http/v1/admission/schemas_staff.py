"""Request and response models of the staff, comment and privacy routes."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.admission.application.privacy import ConsentState
from app.modules.admission.application.staff import CaseloadItem
from app.modules.admission.domain.access import Assignment
from app.modules.admission.domain.staff import AuditRecord, Comment, SavedView
from app.modules.admission.ports.consent import PurposeGrant

from pydantic import BaseModel, Field


class CaseloadItemOut(BaseModel):
    """One student on the staff member's list."""

    student_id: UUID
    student_name: str | None
    group_id: UUID | None
    group_name: str | None
    stage: str | None
    next_due: datetime | None
    overdue: int
    open_help: int
    limited: bool

    @classmethod
    def of(cls, item: CaseloadItem) -> "CaseloadItemOut":
        """Map a caseload item."""
        r = item.row
        return cls(
            student_id=r.student_id,
            student_name=item.student_name,
            group_id=item.group_id,
            group_name=r.group_name,
            stage=r.stage,
            next_due=r.next_due,
            overdue=r.overdue,
            open_help=r.open_help,
            limited=item.limited,
        )


class CaseloadOut(BaseModel):
    """The caseload."""

    items: list[CaseloadItemOut]


class AssignmentIn(BaseModel):
    """Delegate a sub-role over one student or a class."""

    user_id: UUID
    staff_role_id: UUID
    scope_kind: Literal["student", "cohort"]
    scope_ref: UUID
    expires_at: datetime | None = None


class AssignmentOut(BaseModel):
    """A stored assignment."""

    id: UUID
    user_id: UUID
    staff_role_id: UUID
    scope_kind: str
    scope_ref: UUID | None
    starts_at: datetime
    expires_at: datetime | None
    granted_by: UUID | None
    parent_assignment_id: UUID | None

    @classmethod
    def of(cls, a: Assignment) -> "AssignmentOut":
        """Map an assignment."""
        return cls(
            id=a.id,
            user_id=a.user_id,
            staff_role_id=a.role.id,
            scope_kind=a.scope_kind,
            scope_ref=a.scope_ref,
            starts_at=a.starts_at,
            expires_at=a.expires_at,
            granted_by=a.granted_by,
            parent_assignment_id=a.parent_assignment_id,
        )


class SavedViewIn(BaseModel):
    """A saved caseload filter."""

    name: str = Field(max_length=60)
    filters: dict[str, Any] = Field(default_factory=dict)
    sort: str | None = None
    is_default: bool = False


class SavedViewPatch(SavedViewIn):
    """Replace a view; `lock_version` guards against stale edits."""

    lock_version: int


class SavedViewOut(BaseModel):
    """A saved view."""

    id: UUID
    name: str
    filters: dict[str, Any]
    sort: str | None
    is_default: bool
    lock_version: int

    @classmethod
    def of(cls, v: SavedView) -> "SavedViewOut":
        """Map a saved view."""
        return cls(
            id=v.id,
            name=v.name,
            filters=v.filters,
            sort=v.sort,
            is_default=v.is_default,
            lock_version=v.lock_version,
        )


class SavedViewListOut(BaseModel):
    """The caller's saved views."""

    items: list[SavedViewOut]


class CommentIn(BaseModel):
    """A new comment."""

    student_id: UUID
    target_kind: Literal[
        "profile", "help_request", "item", "list_entry", "essay", "words"
    ]
    target_id: UUID
    body: str
    visibility: Literal["staff_only", "student_and_staff"] = "student_and_staff"
    anchor: dict[str, Any] | None = None


class CommentOut(BaseModel):
    """A comment."""

    id: UUID
    student_id: UUID
    target_kind: str
    target_id: UUID
    author_id: UUID
    body: str
    visibility: str
    created_at: datetime
    anchor: dict[str, Any] | None

    @classmethod
    def of(cls, c: Comment) -> "CommentOut":
        """Map a comment."""
        return cls(
            id=c.id,
            student_id=c.student_id,
            target_kind=c.target_kind,
            target_id=c.target_id,
            author_id=c.author_id,
            body=c.body,
            visibility=c.visibility,
            created_at=c.created_at,
            anchor=c.anchor,
        )


class CommentListOut(BaseModel):
    """Comments."""

    items: list[CommentOut]


class ConsentIn(BaseModel):
    """Purposes to grant."""

    purposes: list[str] = Field(min_length=1)


class PurposeGrantOut(BaseModel):
    """One purpose answer."""

    purpose: str
    method: str
    given_at: datetime
    withdrawn_at: datetime | None
    active: bool

    @classmethod
    def of(cls, g: PurposeGrant) -> "PurposeGrantOut":
        """Map a grant."""
        return cls(
            purpose=g.purpose,
            method=g.method,
            given_at=g.given_at,
            withdrawn_at=g.withdrawn_at,
            active=g.active,
        )


class ConsentOut(BaseModel):
    """The caller's purpose consents."""

    grants: list[PurposeGrantOut]
    non_ai_mode: bool

    @classmethod
    def of(cls, s: ConsentState) -> "ConsentOut":
        """Map the consent state."""
        return cls(
            grants=[PurposeGrantOut.of(g) for g in s.grants],
            non_ai_mode=s.non_ai_mode,
        )


class PurposeOut(BaseModel):
    """A consent purpose with its texts per locale."""

    id: str
    title: dict[str, str]
    text: dict[str, str]


class PurposeListOut(BaseModel):
    """The consent purposes the app asks for."""

    items: list[PurposeOut]


class AuditRecordOut(BaseModel):
    """One access to the caller's data."""

    at: datetime
    actor_kind: str
    action: str
    object_type: str | None
    object_id: UUID | None
    staff_role_id: UUID | None

    @classmethod
    def of(cls, a: AuditRecord) -> "AuditRecordOut":
        """Map an audit record."""
        return cls(
            at=a.at,
            actor_kind=a.actor_kind,
            action=a.action,
            object_type=a.object_type,
            object_id=a.object_id,
            staff_role_id=a.staff_role_id,
        )


class AuditOut(BaseModel):
    """Who looked at the caller's data."""

    items: list[AuditRecordOut]


class DataExportOut(BaseModel):
    """The caller's admission data."""

    generated_at: datetime
    tables: dict[str, list[dict[str, Any]]]
    access_log: list[AuditRecordOut]


class ErasedOut(BaseModel):
    """Rows deleted per table."""

    deleted: dict[str, int]
