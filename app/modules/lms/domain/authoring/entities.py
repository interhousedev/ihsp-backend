"""Authoring entities; repositories map them to and from ORM rows."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.domain.authoring.enums import (
    CourseStatus,
    RevisionKind,
    StepVia,
    Visibility,
)


@dataclass(slots=True)
class Course:
    """A course with its draft working copy and a pointer to the live version."""

    id: UUID
    slug: str
    title: str
    description: str
    visibility: Visibility
    status: CourseStatus
    created_by: UUID
    draft_meta: dict[str, Any]
    draft_outline: dict[str, Any]
    outline_hash: str
    cover_file_id: UUID | None = None
    invite_code: str | None = None
    draft_updated_by: UUID | None = None
    draft_updated_at: datetime | None = None
    lock_version: int = 0
    draft_seq: int = 0
    live_outline_hash: str | None = None
    live_version_id: UUID | None = None


@dataclass(slots=True)
class StaffMember:
    """A user on the staff of a course."""

    course_id: UUID
    user_id: UUID
    role: str
    permissions: list[str]
    show_on_page: bool
    position: int
    added_by: UUID


@dataclass(slots=True)
class CourseStep:
    """Stable identity of a step plus its working copy."""

    id: UUID
    course_id: UUID
    draft: dict[str, Any]
    draft_hash: str
    created_via: StepVia
    draft_updated_via: StepVia
    draft_updated_by: UUID | None = None
    draft_updated_at: datetime | None = None
    file_ids: list[UUID] = field(default_factory=list)
    lock_version: int = 0
    live_revision_id: UUID | None = None
    live_hash: str | None = None

    @property
    def title(self) -> str:
        """Title of the step in the draft."""
        return str(self.draft.get("title", ""))


@dataclass(slots=True)
class StepRevision:
    """An immutable frozen state of a step."""

    id: UUID
    step_id: UUID
    content: dict[str, Any]
    content_hash: str
    kind: RevisionKind
    created_by: UUID
    created_at: datetime
    file_ids: list[UUID] = field(default_factory=list)
    label: str | None = None
    published_at: datetime | None = None


@dataclass(slots=True)
class CourseVersion:
    """An immutable manifest of a published course."""

    id: UUID
    course_id: UUID
    number: int
    meta: dict[str, Any]
    outline: dict[str, Any]
    changes: dict[str, Any]
    published_by: UUID
    created_at: datetime
    note: str | None = None
