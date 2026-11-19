"""Ports: documents, checklist, deadlines, reminders and transcript requests."""

import datetime as dt
from collections.abc import Collection, Sequence
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.documents import (
    AttachmentRecord,
    ChecklistItem,
    Deadline,
    DocumentRecord,
    DocumentVersionRecord,
    DueMilestone,
    Milestone,
    OfficerSettings,
    ReminderPrefs,
    ReminderRecord,
    Transcript,
)
from app.modules.admission.domain.institution_brand import InstitutionBrand


class DocumentRepository(Protocol):
    """Documents, their versions and their attachments to list entries."""

    async def add(self, doc: DocumentRecord) -> DocumentRecord:
        """Insert a document (version 0 until the first version is added)."""
        ...

    async def get(self, document_id: UUID) -> DocumentRecord | None:
        """Return the document."""
        ...

    async def for_students(
        self,
        student_ids: Collection[UUID] | None,
        *,
        review_status: str | None = None,
    ) -> list[DocumentRecord]:
        """List documents of the students (None: all), newest first."""
        ...

    async def save(self, doc: DocumentRecord, *, expected_lock: int) -> DocumentRecord:
        """Update; a stale lock raises a conflict."""
        ...

    async def add_version(
        self, version: DocumentVersionRecord
    ) -> DocumentVersionRecord:
        """Insert a version."""
        ...

    async def version(
        self, document_id: UUID, version: int
    ) -> DocumentVersionRecord | None:
        """Return one version."""
        ...

    async def versions(self, document_id: UUID) -> list[DocumentVersionRecord]:
        """Return the versions, newest first."""
        ...

    async def attachments(
        self, document_ids: Collection[UUID]
    ) -> list[AttachmentRecord]:
        """Return the live (attached or superseded) attachments of the documents."""
        ...

    async def attachment(
        self, document_id: UUID, list_entry_id: UUID
    ) -> AttachmentRecord | None:
        """Return the live attachment of a document to a list entry."""
        ...

    async def add_attachment(self, row: AttachmentRecord) -> AttachmentRecord:
        """Insert an attachment."""
        ...

    async def save_attachment(self, row: AttachmentRecord) -> None:
        """Update the status and version of an attachment."""
        ...

    async def supersede_attachments(self, document_id: UUID, keep_version: int) -> int:
        """Mark attached rows of older versions superseded; return how many."""
        ...


class ChecklistRepository(Protocol):
    """Checklist items."""

    async def for_student(self, student_id: UUID) -> list[ChecklistItem]:
        """Return the student's items."""
        ...

    async def get(self, item_id: UUID) -> ChecklistItem | None:
        """Return one item."""
        ...

    async def save(self, item: ChecklistItem, *, expected_lock: int) -> ChecklistItem:
        """Update; a stale lock raises a conflict."""
        ...

    async def ensure(self, items: Sequence[ChecklistItem]) -> None:
        """Insert the rows not there yet, keyed by (student, entry, template)."""
        ...


class DeadlineRepository(Protocol):
    """Deadlines, milestones and reminders."""

    async def get(self, deadline_id: UUID) -> Deadline | None:
        """Return one deadline version."""
        ...

    async def current(
        self, *, institution_id: UUID | None = None, cycle: int | None = None
    ) -> list[Deadline]:
        """Return the live (not superseded) deadlines."""
        ...

    async def add(self, deadline: Deadline) -> Deadline:
        """Insert a deadline version."""
        ...

    async def supersede(self, deadline_id: UUID, by: UUID) -> None:
        """Mark a version as replaced."""
        ...

    async def milestones_of_entries(
        self, entry_ids: Collection[UUID]
    ) -> list[Milestone]:
        """Return the milestones of the list entries."""
        ...

    async def milestones_of_deadline(self, deadline_id: UUID) -> list[DueMilestone]:
        """Return the milestones that follow a deadline, with their student."""
        ...

    async def save_milestone(self, milestone: Milestone) -> None:
        """Update the due time, deadline link and flag."""
        ...

    async def due_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[DueMilestone]:
        """Return milestones of live list entries due in [start, end]."""
        ...

    async def prefs(self, student_id: UUID) -> ReminderPrefs | None:
        """Return the reminder preferences."""
        ...

    async def save_prefs(
        self, prefs: ReminderPrefs, expected_lock: int | None
    ) -> ReminderPrefs:
        """Insert (expected None) or update; a stale lock raises a conflict."""
        ...

    async def add_reminder(self, reminder: ReminderRecord) -> bool:
        """Insert; False when the dedupe key already exists."""
        ...

    async def supersede_reminders(self, milestone_ids: Sequence[UUID]) -> list[str]:
        """Mark unsent reminders of the milestones superseded; return their keys."""
        ...

    async def institution_names(self, ids: Collection[UUID]) -> dict[UUID, str]:
        """Return institution names by id."""
        ...

    async def institution_brands(
        self, ids: Collection[UUID]
    ) -> dict[UUID, InstitutionBrand]:
        """Return institution names and logos by id."""
        ...


class TranscriptRepository(Protocol):
    """Transcript requests and the officers' own settings."""

    async def add(self, request: Transcript) -> Transcript:
        """Insert; a second open request raises a conflict."""
        ...

    async def get(self, request_id: UUID) -> Transcript | None:
        """Return one request."""
        ...

    async def open_of(self, student_id: UUID) -> Transcript | None:
        """Return the student's open (requested) request."""
        ...

    async def of_student(self, student_id: UUID) -> list[Transcript]:
        """Return the student's requests, newest first."""
        ...

    async def listing(
        self, student_ids: Collection[UUID] | None, status: str | None
    ) -> list[Transcript]:
        """List requests of the students (None: all) by status, oldest first."""
        ...

    async def save(self, request: Transcript, *, expected_lock: int) -> Transcript:
        """Update; a stale lock raises a conflict."""
        ...

    async def officer_settings(self, user_id: UUID) -> OfficerSettings | None:
        """Return the officer's settings."""
        ...

    async def save_officer_settings(
        self, settings: OfficerSettings, expected_lock: int | None
    ) -> OfficerSettings:
        """Insert (expected None) or update."""
        ...
