"""SQL repositories of documents, checklist, deadlines and transcript requests."""

import datetime as dt
from collections.abc import Collection, Sequence
from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.catalog_display import resolve_logo_fit
from app.modules.admission.domain.documents import (
    LIVE_ENTRY_STATUSES,
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
from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.institution_brand import InstitutionBrand
from app.modules.admission.infrastructure.orm.access import OfficerSettingsRow
from app.modules.admission.infrastructure.orm.applications import (
    ChecklistItemRow,
    DeadlineRow,
    DocumentAttachmentRow,
    DocumentRow,
    DocumentVersionRow,
    ListEntryRow,
    MilestoneRow,
    ReminderPrefsRow,
    ReminderRow,
    TranscriptRequestRow,
)
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.shared.ids import new_id

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _doc(row: DocumentRow) -> DocumentRecord:
    return DocumentRecord(
        id=row.id,
        student_id=row.student_id,
        kind=cast(Any, row.kind),
        visibility=cast(Any, row.visibility),
        uploaded_by=row.uploaded_by,
        owner_kind=cast(Any, row.owner_kind),
        current_version=row.current_version,
        review_status=cast(Any, row.review_status),
        reject_reason_code=row.reject_reason_code,
        reject_note=row.reject_note,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        lock_version=row.lock_version,
    )


def _version(row: DocumentVersionRow) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        document_id=row.document_id,
        version=row.version,
        file_id=row.file_id,
        scan_status=cast(Any, row.scan_status),
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
    )


def _attachment(row: DocumentAttachmentRow) -> AttachmentRecord:
    return AttachmentRecord(
        id=row.id,
        document_id=row.document_id,
        document_version=row.document_version,
        list_entry_id=row.list_entry_id,
        attached_by=row.attached_by,
        status=cast(Any, row.status),
        attached_at=row.attached_at,
    )


def _item(row: ChecklistItemRow) -> ChecklistItem:
    return ChecklistItem(
        id=row.id,
        student_id=row.student_id,
        template_key=row.template_key,
        title_key=row.title_key,
        list_entry_id=row.list_entry_id,
        owner=row.owner,
        status=cast(Any, row.status),
        due_utc=row.due_utc,
        document_id=row.document_id,
        source_url=row.source_url,
        important=row.important,
        urgent_override=row.urgent_override,
        rule_version=row.rule_version,
        lock_version=row.lock_version,
    )


def _deadline(row: DeadlineRow) -> Deadline:
    return Deadline(
        id=row.id,
        institution_id=row.institution_id,
        cycle=row.cycle,
        round=row.round,
        program_id=row.program_id,
        precision=cast(Any, row.precision),
        source_text=row.source_text,
        source_tz=row.source_tz,
        local_date=row.local_date,
        cutoff_time=row.cutoff_time,
        instant_utc=row.instant_utc,
        binding=row.binding,
        applies_to=row.applies_to,
        status=cast(Any, row.status),
        source_id=row.source_id,
        version=row.version,
        superseded_by=row.superseded_by,
    )


def _milestone(row: MilestoneRow) -> Milestone:
    return Milestone(
        id=row.id,
        list_entry_id=row.list_entry_id,
        kind=row.kind,
        due_utc=row.due_utc,
        deadline_id=row.deadline_id,
        deadline_version=row.deadline_version,
        predicted=row.predicted,
    )


def _prefs(row: ReminderPrefsRow) -> ReminderPrefs:
    return ReminderPrefs(
        student_id=row.student_id,
        offsets_days=tuple(row.offsets_days),
        channels=tuple(row.channels),
        quiet_from=row.quiet_from,
        quiet_to=row.quiet_to,
        lock_version=row.lock_version,
    )


def _transcript(row: TranscriptRequestRow) -> Transcript:
    return Transcript(
        id=row.id,
        student_id=row.student_id,
        destination_note=row.destination_note or "",
        status=cast(Any, row.status),
        requested_at=row.requested_at,
        ready_at=row.ready_at,
        ready_by=row.ready_by,
        undo_until=row.undo_until,
        pickup_location_snapshot=row.pickup_location_snapshot,
        cancelled_by=row.cancelled_by,
        cancelled_at=row.cancelled_at,
        last_reminded_at=row.last_reminded_at,
        document_id=row.document_id,
        lock_version=row.lock_version,
    )


class SqlDocumentRepository:
    """Documents, versions and attachments."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the open session."""
        self._s = session

    async def add(self, doc: DocumentRecord) -> DocumentRecord:
        """Insert a document."""
        row = DocumentRow(
            id=doc.id,
            student_id=doc.student_id,
            kind=doc.kind,
            current_version=doc.current_version,
            visibility=doc.visibility,
            owner_kind=doc.owner_kind,
            uploaded_by=doc.uploaded_by,
            review_status=doc.review_status,
            lock_version=0,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _doc(row)

    async def get(self, document_id: UUID) -> DocumentRecord | None:
        """Return the document."""
        row = await self._s.get(DocumentRow, document_id)
        return _doc(row) if row else None

    async def for_students(
        self,
        student_ids: Collection[UUID] | None,
        *,
        review_status: str | None = None,
    ) -> list[DocumentRecord]:
        """List documents of the students (None: all), newest first."""
        stmt = select(DocumentRow).order_by(DocumentRow.created_at.desc())
        if student_ids is not None:
            stmt = stmt.where(DocumentRow.student_id.in_(list(student_ids)))
        if review_status:
            stmt = stmt.where(DocumentRow.review_status == review_status)
        return [_doc(r) for r in (await self._s.scalars(stmt)).all()]

    async def save(self, doc: DocumentRecord, *, expected_lock: int) -> DocumentRecord:
        """Update; a stale lock raises a conflict."""
        row = await self._s.get(DocumentRow, doc.id, with_for_update=True)
        if row is None or row.lock_version != expected_lock:
            raise AdmissionConflictError()
        row.current_version = doc.current_version
        row.review_status = doc.review_status
        row.reject_reason_code = doc.reject_reason_code
        row.reject_note = doc.reject_note
        row.reviewed_by = doc.reviewed_by
        row.reviewed_at = doc.reviewed_at
        row.lock_version = expected_lock + 1
        await self._s.flush()
        return _doc(row)

    async def add_version(
        self, version: DocumentVersionRecord
    ) -> DocumentVersionRecord:
        """Insert a version."""
        row = DocumentVersionRow(
            id=new_id(),
            document_id=version.document_id,
            version=version.version,
            file_id=version.file_id,
            scan_status=version.scan_status,
            uploaded_by=version.uploaded_by,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _version(row)

    async def version(
        self, document_id: UUID, version: int
    ) -> DocumentVersionRecord | None:
        """Return one version."""
        row = await self._s.scalar(
            select(DocumentVersionRow).where(
                DocumentVersionRow.document_id == document_id,
                DocumentVersionRow.version == version,
            )
        )
        return _version(row) if row else None

    async def versions(self, document_id: UUID) -> list[DocumentVersionRecord]:
        """Return the versions, newest first."""
        rows = await self._s.scalars(
            select(DocumentVersionRow)
            .where(DocumentVersionRow.document_id == document_id)
            .order_by(DocumentVersionRow.version.desc())
        )
        return [_version(r) for r in rows.all()]

    async def attachments(
        self, document_ids: Collection[UUID]
    ) -> list[AttachmentRecord]:
        """Return the live attachments of the documents."""
        if not document_ids:
            return []
        rows = await self._s.scalars(
            select(DocumentAttachmentRow).where(
                DocumentAttachmentRow.document_id.in_(list(document_ids)),
                DocumentAttachmentRow.status != "detached",
            )
        )
        return [_attachment(r) for r in rows.all()]

    async def attachment(
        self, document_id: UUID, list_entry_id: UUID
    ) -> AttachmentRecord | None:
        """Return the live attachment of a document to a list entry."""
        row = await self._s.scalar(
            select(DocumentAttachmentRow)
            .where(
                DocumentAttachmentRow.document_id == document_id,
                DocumentAttachmentRow.list_entry_id == list_entry_id,
                DocumentAttachmentRow.status != "detached",
            )
            .order_by(DocumentAttachmentRow.attached_at.desc())
            .limit(1)
        )
        return _attachment(row) if row else None

    async def add_attachment(self, row: AttachmentRecord) -> AttachmentRecord:
        """Insert an attachment."""
        orm = DocumentAttachmentRow(
            id=row.id,
            document_id=row.document_id,
            document_version=row.document_version,
            list_entry_id=row.list_entry_id,
            status=row.status,
            attached_by=row.attached_by,
        )
        self._s.add(orm)
        await self._s.flush()
        await self._s.refresh(orm)
        return _attachment(orm)

    async def save_attachment(self, row: AttachmentRecord) -> None:
        """Update the status and version of an attachment."""
        await self._s.execute(
            update(DocumentAttachmentRow)
            .where(DocumentAttachmentRow.id == row.id)
            .values(status=row.status, document_version=row.document_version)
        )

    async def supersede_attachments(self, document_id: UUID, keep_version: int) -> int:
        """Mark attached rows of older versions superseded; return how many."""
        result = await self._s.execute(
            update(DocumentAttachmentRow)
            .where(
                DocumentAttachmentRow.document_id == document_id,
                DocumentAttachmentRow.status == "attached",
                DocumentAttachmentRow.document_version < keep_version,
            )
            .values(status="superseded")
        )
        return int(getattr(result, "rowcount", 0) or 0)


class SqlChecklistRepository:
    """Checklist items."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the open session."""
        self._s = session

    async def for_student(self, student_id: UUID) -> list[ChecklistItem]:
        """Return the student's items."""
        rows = await self._s.scalars(
            select(ChecklistItemRow)
            .where(ChecklistItemRow.student_id == student_id)
            .order_by(ChecklistItemRow.due_utc.asc().nulls_last(), ChecklistItemRow.id)
        )
        return [_item(r) for r in rows.all()]

    async def get(self, item_id: UUID) -> ChecklistItem | None:
        """Return one item."""
        row = await self._s.get(ChecklistItemRow, item_id)
        return _item(row) if row else None

    async def save(self, item: ChecklistItem, *, expected_lock: int) -> ChecklistItem:
        """Update; a stale lock raises a conflict."""
        row = await self._s.get(ChecklistItemRow, item.id, with_for_update=True)
        if row is None or row.lock_version != expected_lock:
            raise AdmissionConflictError()
        row.status = item.status
        row.due_utc = item.due_utc
        row.document_id = item.document_id
        row.source_url = item.source_url
        row.important = item.important
        row.urgent_override = item.urgent_override
        row.lock_version = expected_lock + 1
        await self._s.flush()
        return _item(row)

    async def ensure(self, items: Sequence[ChecklistItem]) -> None:
        """Insert missing rows; a concurrent duplicate is ignored by the index."""
        if not items:
            return
        await self._s.execute(
            pg_insert(ChecklistItemRow)
            .values(
                [
                    {
                        "id": i.id,
                        "student_id": i.student_id,
                        "list_entry_id": i.list_entry_id,
                        "template_key": i.template_key,
                        "title_key": i.title_key,
                        "owner": i.owner,
                        "status": i.status,
                        "due_utc": i.due_utc,
                        "rule_version": i.rule_version,
                        "lock_version": 0,
                    }
                    for i in items
                ]
            )
            .on_conflict_do_nothing()
        )


class SqlDeadlineRepository:
    """Deadlines, milestones, reminder preferences and reminders."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the open session."""
        self._s = session

    async def get(self, deadline_id: UUID) -> Deadline | None:
        """Return one deadline version."""
        row = await self._s.get(DeadlineRow, deadline_id)
        return _deadline(row) if row else None

    async def current(
        self, *, institution_id: UUID | None = None, cycle: int | None = None
    ) -> list[Deadline]:
        """Return the live deadlines."""
        stmt = select(DeadlineRow).where(DeadlineRow.superseded_by.is_(None))
        if institution_id:
            stmt = stmt.where(DeadlineRow.institution_id == institution_id)
        if cycle:
            stmt = stmt.where(DeadlineRow.cycle == cycle)
        stmt = stmt.order_by(DeadlineRow.institution_id, DeadlineRow.round)
        return [_deadline(r) for r in (await self._s.scalars(stmt)).all()]

    async def add(self, deadline: Deadline) -> Deadline:
        """Insert a deadline version."""
        row = DeadlineRow(
            id=deadline.id,
            institution_id=deadline.institution_id,
            program_id=deadline.program_id,
            cycle=deadline.cycle,
            round=deadline.round,
            precision=deadline.precision,
            source_text=deadline.source_text,
            source_tz=deadline.source_tz,
            local_date=deadline.local_date,
            cutoff_time=deadline.cutoff_time,
            instant_utc=deadline.instant_utc,
            binding=deadline.binding,
            applies_to=deadline.applies_to,
            status=deadline.status,
            source_id=deadline.source_id,
            version=deadline.version,
        )
        self._s.add(row)
        await self._s.flush()
        return _deadline(row)

    async def supersede(self, deadline_id: UUID, by: UUID) -> None:
        """Mark a version as replaced."""
        await self._s.execute(
            update(DeadlineRow)
            .where(DeadlineRow.id == deadline_id)
            .values(superseded_by=by)
        )

    async def milestones_of_entries(
        self, entry_ids: Collection[UUID]
    ) -> list[Milestone]:
        """Return the milestones of the list entries."""
        if not entry_ids:
            return []
        rows = await self._s.scalars(
            select(MilestoneRow)
            .where(MilestoneRow.list_entry_id.in_(list(entry_ids)))
            .order_by(MilestoneRow.due_utc.asc().nulls_last())
        )
        return [_milestone(r) for r in rows.all()]

    async def _due(self, *conditions: Any) -> list[DueMilestone]:
        rows = await self._s.execute(
            select(MilestoneRow, ListEntryRow.student_id, ListEntryRow.institution_id)
            .join(ListEntryRow, ListEntryRow.id == MilestoneRow.list_entry_id)
            .where(*conditions)
        )
        return [DueMilestone(_milestone(m), s, i) for m, s, i in rows.all()]

    async def milestones_of_deadline(self, deadline_id: UUID) -> list[DueMilestone]:
        """Return the milestones that follow a deadline, with their student."""
        return await self._due(MilestoneRow.deadline_id == deadline_id)

    async def save_milestone(self, milestone: Milestone) -> None:
        """Update the due time, deadline link and flag."""
        await self._s.execute(
            update(MilestoneRow)
            .where(MilestoneRow.id == milestone.id)
            .values(
                due_utc=milestone.due_utc,
                deadline_id=milestone.deadline_id,
                deadline_version=milestone.deadline_version,
                predicted=milestone.predicted,
            )
        )

    async def due_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[DueMilestone]:
        """Return milestones of live list entries due in [start, end]."""
        return await self._due(
            MilestoneRow.due_utc >= start,
            MilestoneRow.due_utc <= end,
            MilestoneRow.predicted.is_(False),
            ListEntryRow.status.in_(sorted(LIVE_ENTRY_STATUSES)),
        )

    async def prefs(self, student_id: UUID) -> ReminderPrefs | None:
        """Return the reminder preferences."""
        row = await self._s.get(ReminderPrefsRow, student_id)
        return _prefs(row) if row else None

    async def save_prefs(
        self, prefs: ReminderPrefs, expected_lock: int | None
    ) -> ReminderPrefs:
        """Insert (expected None) or update; a stale lock raises a conflict."""
        if expected_lock is None:
            row = ReminderPrefsRow(
                student_id=prefs.student_id,
                offsets_days=list(prefs.offsets_days),
                channels=list(prefs.channels),
                quiet_from=prefs.quiet_from,
                quiet_to=prefs.quiet_to,
                lock_version=0,
            )
            self._s.add(row)
        else:
            found = await self._s.get(
                ReminderPrefsRow, prefs.student_id, with_for_update=True
            )
            if found is None or found.lock_version != expected_lock:
                raise AdmissionConflictError()
            row = found
            row.offsets_days = list(prefs.offsets_days)
            row.channels = list(prefs.channels)
            row.quiet_from = prefs.quiet_from
            row.quiet_to = prefs.quiet_to
            row.lock_version = expected_lock + 1
        await self._s.flush()
        return _prefs(row)

    async def add_reminder(self, reminder: ReminderRecord) -> bool:
        """Insert; False when the dedupe key already exists."""
        stmt = (
            pg_insert(ReminderRow)
            .values(
                id=reminder.id,
                student_id=reminder.student_id,
                milestone_id=reminder.milestone_id,
                schedule_version=reminder.schedule_version,
                offset_days=reminder.offset_days,
                dedupe_key=reminder.dedupe_key,
                scheduled_at=reminder.scheduled_at,
            )
            .on_conflict_do_nothing(index_elements=[ReminderRow.dedupe_key])
            .returning(ReminderRow.id)
        )
        return (await self._s.scalar(stmt)) is not None

    async def supersede_reminders(self, milestone_ids: Sequence[UUID]) -> list[str]:
        """Mark unsent reminders of the milestones superseded; return their keys."""
        if not milestone_ids:
            return []
        rows = await self._s.scalars(
            update(ReminderRow)
            .where(
                ReminderRow.milestone_id.in_(list(milestone_ids)),
                ReminderRow.sent_at.is_(None),
                ReminderRow.superseded_at.is_(None),
            )
            .values(superseded_at=dt.datetime.now(dt.UTC))
            .returning(ReminderRow.dedupe_key)
        )
        return list(rows.all())

    async def institution_names(self, ids: Collection[UUID]) -> dict[UUID, str]:
        """Return institution names by id."""
        if not ids:
            return {}
        rows = await self._s.execute(
            select(InstitutionRow.id, InstitutionRow.name).where(
                InstitutionRow.id.in_(list(ids))
            )
        )
        return dict(rows.tuples().all())

    async def institution_brands(
        self, ids: Collection[UUID]
    ) -> dict[UUID, InstitutionBrand]:
        """Return institution names and logos by id."""
        if not ids:
            return {}
        rows = await self._s.execute(
            select(
                InstitutionRow.id,
                InstitutionRow.name,
                InstitutionRow.logo_url,
                InstitutionRow.logo_fit,
                InstitutionRow.logo_aspect,
                InstitutionRow.logo_zoom,
            ).where(InstitutionRow.id.in_(list(ids)))
        )
        return {
            i: InstitutionBrand(
                name=name,
                logo_url=url,
                logo_fit=resolve_logo_fit(fit, aspect),
                logo_zoom=zoom,
            )
            for i, name, url, fit, aspect, zoom in rows.tuples().all()
        }


class SqlTranscriptRepository:
    """Transcript requests and officer settings."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the open session."""
        self._s = session

    async def add(self, request: Transcript) -> Transcript:
        """Insert; a second open request raises a conflict."""
        row = TranscriptRequestRow(
            id=request.id,
            student_id=request.student_id,
            destination_note=request.destination_note,
            status="requested",
            lock_version=0,
        )
        try:
            async with self._s.begin_nested():
                self._s.add(row)
                await self._s.flush()
        except IntegrityError as exc:
            raise AdmissionConflictError() from exc
        await self._s.refresh(row)
        return _transcript(row)

    async def get(self, request_id: UUID) -> Transcript | None:
        """Return one request."""
        row = await self._s.get(TranscriptRequestRow, request_id)
        return _transcript(row) if row else None

    async def open_of(self, student_id: UUID) -> Transcript | None:
        """Return the student's open request."""
        row = await self._s.scalar(
            select(TranscriptRequestRow).where(
                TranscriptRequestRow.student_id == student_id,
                TranscriptRequestRow.status == "requested",
            )
        )
        return _transcript(row) if row else None

    async def of_student(self, student_id: UUID) -> list[Transcript]:
        """Return the student's requests, newest first."""
        rows = await self._s.scalars(
            select(TranscriptRequestRow)
            .where(TranscriptRequestRow.student_id == student_id)
            .order_by(TranscriptRequestRow.requested_at.desc())
        )
        return [_transcript(r) for r in rows.all()]

    async def listing(
        self, student_ids: Collection[UUID] | None, status: str | None
    ) -> list[Transcript]:
        """List requests of the students (None: all) by status, oldest first."""
        stmt = select(TranscriptRequestRow).order_by(TranscriptRequestRow.requested_at)
        if student_ids is not None:
            stmt = stmt.where(TranscriptRequestRow.student_id.in_(list(student_ids)))
        if status:
            stmt = stmt.where(TranscriptRequestRow.status == status)
        return [_transcript(r) for r in (await self._s.scalars(stmt)).all()]

    async def save(self, request: Transcript, *, expected_lock: int) -> Transcript:
        """Update; a stale lock raises a conflict."""
        row = await self._s.get(TranscriptRequestRow, request.id, with_for_update=True)
        if row is None or row.lock_version != expected_lock:
            raise AdmissionConflictError()
        row.status = request.status
        row.ready_at = request.ready_at
        row.ready_by = request.ready_by
        row.undo_until = request.undo_until
        row.pickup_location_snapshot = request.pickup_location_snapshot
        row.cancelled_by = request.cancelled_by
        row.cancelled_at = request.cancelled_at
        row.last_reminded_at = request.last_reminded_at
        row.document_id = request.document_id
        row.lock_version = expected_lock + 1
        try:
            async with self._s.begin_nested():
                await self._s.flush()
        except IntegrityError as exc:  # undo into an already open request
            raise AdmissionConflictError() from exc
        return _transcript(row)

    async def officer_settings(self, user_id: UUID) -> OfficerSettings | None:
        """Return the officer's settings."""
        row = await self._s.get(OfficerSettingsRow, user_id)
        if row is None:
            return None
        return OfficerSettings(row.user_id, dict(row.pickup_location), row.lock_version)

    async def save_officer_settings(
        self, settings: OfficerSettings, expected_lock: int | None
    ) -> OfficerSettings:
        """Insert (expected None) or update."""
        found = await self._s.get(
            OfficerSettingsRow, settings.user_id, with_for_update=True
        )
        if found is None:
            found = OfficerSettingsRow(
                user_id=settings.user_id,
                pickup_location=dict(settings.pickup_location),
                lock_version=0,
            )
            self._s.add(found)
        else:
            if expected_lock is not None and found.lock_version != expected_lock:
                raise AdmissionConflictError()
            found.pickup_location = dict(settings.pickup_location)
            found.lock_version += 1
        await self._s.flush()
        return OfficerSettings(
            found.user_id, dict(found.pickup_location), found.lock_version
        )
