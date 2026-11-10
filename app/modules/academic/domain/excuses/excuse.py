"""Excuse: an official reason why a student misses lessons."""

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.modules.academic.domain.excuses.errors import (
    ExcuseInvalidError,
    ExcuseNotApprovedError,
    ExcuseNotPendingError,
)

REASON_MAX = 2000
MESSAGE_MAX = 2000
COMMENT_MAX = 2000


class ExcuseOrigin(StrEnum):
    """Who started the excuse."""

    REQUEST = "request"
    CURATOR = "curator"


class ExcuseStatus(StrEnum):
    """Where the excuse is in its life."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ExcuseTemplate:
    """A ready reason; some need a document."""

    id: UUID
    code: str
    title: dict[str, str]
    requires_document: bool
    active: bool
    sort: int


@dataclass(frozen=True, slots=True)
class ExcuseMessage:
    """One line of the thread between the student, the curator and Administration."""

    id: UUID
    excuse_id: UUID
    author_id: UUID
    body: str
    file_ids: tuple[UUID, ...]
    created_at: dt.datetime


@dataclass(slots=True)
class Excuse:
    """The excuse; both ``lesson_ids`` and ``subject_ids`` empty means whole days."""

    id: UUID
    student_id: UUID
    origin: ExcuseOrigin
    status: ExcuseStatus
    template_id: UUID
    reason: str
    starts_on: dt.date
    ends_on: dt.date | None
    lesson_ids: tuple[UUID, ...]
    subject_ids: tuple[UUID, ...]
    created_by: UUID
    decided_by: UUID | None
    decided_at: dt.datetime | None
    decision_comment: str | None
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    messages: list[ExcuseMessage] = field(default_factory=list)

    def covers(
        self, day: dt.date, lesson_id: UUID | None, subject_id: UUID | None
    ) -> bool:
        """True when this approved excuse excuses the lesson of that day."""
        if self.status != ExcuseStatus.APPROVED or day < self.starts_on:
            return False
        if self.ends_on is not None and day > self.ends_on:
            return False
        if not self.lesson_ids and not self.subject_ids:
            return True
        return (lesson_id is not None and lesson_id in self.lesson_ids) or (
            subject_id is not None and subject_id in self.subject_ids
        )

    def is_active_on(self, day: dt.date) -> bool:
        """True when the day is inside an approved excuse."""
        return (
            self.status == ExcuseStatus.APPROVED
            and self.starts_on <= day
            and (self.ends_on is None or day <= self.ends_on)
        )

    def approve(self, by: UUID, comment: str | None, at: dt.datetime) -> None:
        """Approve a pending excuse."""
        self._decide(ExcuseStatus.APPROVED, by, comment, at)

    def reject(self, by: UUID, comment: str | None, at: dt.datetime) -> None:
        """Reject a pending excuse."""
        self._decide(ExcuseStatus.REJECTED, by, comment, at)

    def cancel(self, at: dt.datetime) -> None:
        """The student withdraws a pending request."""
        if self.status != ExcuseStatus.PENDING:
            raise ExcuseNotPendingError(params={"status": self.status.value})
        self.status = ExcuseStatus.CANCELLED
        self._touch(at)

    def revoke(self, by: UUID, comment: str | None, at: dt.datetime) -> None:
        """The curator takes an approved excuse back."""
        if self.status != ExcuseStatus.APPROVED:
            raise ExcuseNotApprovedError(params={"status": self.status.value})
        self.status = ExcuseStatus.CANCELLED
        self.decided_by, self.decided_at = by, at
        self.decision_comment = _clean(comment, COMMENT_MAX)
        self._touch(at)

    def end(self, ends_on: dt.date, at: dt.datetime) -> None:
        """Close an approved excuse on ``ends_on`` (not before it started)."""
        if self.status != ExcuseStatus.APPROVED:
            raise ExcuseNotApprovedError(params={"status": self.status.value})
        if ends_on < self.starts_on:
            raise ExcuseInvalidError(params={"field": "ends_on"})
        self.ends_on = ends_on
        self._touch(at)

    def _decide(
        self, status: ExcuseStatus, by: UUID, comment: str | None, at: dt.datetime
    ) -> None:
        if self.status != ExcuseStatus.PENDING:
            raise ExcuseNotPendingError(params={"status": self.status.value})
        self.status = status
        self.decided_by, self.decided_at = by, at
        self.decision_comment = _clean(comment, COMMENT_MAX)
        self._touch(at)

    def _touch(self, at: dt.datetime) -> None:
        self.version += 1
        self.updated_at = at


def _clean(text: str | None, limit: int) -> str | None:
    value = (text or "").strip()
    return value[:limit] or None


def clean_text(text: str | None, limit: int, field_name: str) -> str:
    """Trim a required text; empty or too long raises ``ExcuseInvalidError``."""
    value = (text or "").strip()
    if not value or len(value) > limit:
        raise ExcuseInvalidError(params={"field": field_name})
    return value


def check_period(starts_on: dt.date, ends_on: dt.date | None) -> None:
    """The end, when given, is not before the start."""
    if ends_on is not None and ends_on < starts_on:
        raise ExcuseInvalidError(params={"field": "ends_on"})
