"""In-memory documents, deadlines and transcript repositories for the unit tests."""

import dataclasses
import datetime as dt
from collections.abc import Collection, Sequence
from typing import Any
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
from app.modules.admission.domain.errors import AdmissionConflictError
from app.settings import LimitsSettings
from app.shared.actor import Role
from app.shared.contracts.files import FilePurpose, FileRef, FileScope, SignedDownload
from app.shared.contracts.identity import UserRef
from app.shared.ids import new_id
from app.shared.limits import StaticLimits
from tests.admission.unit.fakes import NOW, FakeStore, FakeUow


class DocState:
    """Rows of the documents, deadline and transcript tables."""

    def __init__(self) -> None:
        """Start empty."""
        self.docs: dict[UUID, DocumentRecord] = {}
        self.versions: list[DocumentVersionRecord] = []
        self.attachments: list[AttachmentRecord] = []
        self.items: dict[UUID, ChecklistItem] = {}
        self.deadlines: dict[UUID, Deadline] = {}
        self.milestones: dict[UUID, Milestone] = {}
        self.milestone_owner: dict[UUID, UUID] = {}
        self.prefs: dict[UUID, ReminderPrefs] = {}
        self.reminders: dict[str, ReminderRecord] = {}
        self.transcripts: dict[UUID, Transcript] = {}
        self.officers: dict[UUID, OfficerSettings] = {}
        self.notifications: list[Any] = []
        self.pending_keys: set[str] = set()
        self.institution_names: dict[UUID, str] = {}


def _lock(row: Any, expected: int) -> None:
    if row.lock_version != expected:
        raise AdmissionConflictError()


class FakeDocuments:
    """DocumentRepository over DocState."""

    def __init__(self, d: DocState) -> None:
        """Bind the state."""
        self.d = d

    async def add(self, doc: DocumentRecord) -> DocumentRecord:
        self.d.docs[doc.id] = doc
        return doc

    async def get(self, document_id: UUID) -> DocumentRecord | None:
        return self.d.docs.get(document_id)

    async def for_students(
        self, student_ids: Collection[UUID] | None, *, review_status: str | None = None
    ) -> list[DocumentRecord]:
        return [
            x
            for x in self.d.docs.values()
            if (student_ids is None or x.student_id in student_ids)
            and (review_status is None or x.review_status == review_status)
        ]

    async def save(self, doc: DocumentRecord, *, expected_lock: int) -> DocumentRecord:
        _lock(doc, expected_lock)
        doc.lock_version += 1
        self.d.docs[doc.id] = doc
        return doc

    async def add_version(
        self, version: DocumentVersionRecord
    ) -> DocumentVersionRecord:
        self.d.versions.append(version)
        return version

    async def version(
        self, document_id: UUID, version: int
    ) -> DocumentVersionRecord | None:
        return next(
            (
                v
                for v in self.d.versions
                if v.document_id == document_id and v.version == version
            ),
            None,
        )

    async def versions(self, document_id: UUID) -> list[DocumentVersionRecord]:
        rows = [v for v in self.d.versions if v.document_id == document_id]
        return sorted(rows, key=lambda v: -v.version)

    async def attachments(
        self, document_ids: Collection[UUID]
    ) -> list[AttachmentRecord]:
        return [
            a
            for a in self.d.attachments
            if a.document_id in document_ids and a.status != "detached"
        ]

    async def attachment(
        self, document_id: UUID, list_entry_id: UUID
    ) -> AttachmentRecord | None:
        return next(
            (
                a
                for a in self.d.attachments
                if a.document_id == document_id
                and a.list_entry_id == list_entry_id
                and a.status != "detached"
            ),
            None,
        )

    async def add_attachment(self, row: AttachmentRecord) -> AttachmentRecord:
        self.d.attachments.append(row)
        return row

    async def save_attachment(self, row: AttachmentRecord) -> None:
        return None

    async def supersede_attachments(self, document_id: UUID, keep_version: int) -> int:
        n = 0
        for a in self.d.attachments:
            if (
                a.document_id == document_id
                and a.status == "attached"
                and a.document_version < keep_version
            ):
                a.status = "superseded"
                n += 1
        return n


class FakeChecklist:
    """ChecklistRepository over DocState."""

    def __init__(self, d: DocState) -> None:
        """Bind the state."""
        self.d = d

    async def for_student(self, student_id: UUID) -> list[ChecklistItem]:
        return [i for i in self.d.items.values() if i.student_id == student_id]

    async def get(self, item_id: UUID) -> ChecklistItem | None:
        return self.d.items.get(item_id)

    async def save(self, item: ChecklistItem, *, expected_lock: int) -> ChecklistItem:
        _lock(item, expected_lock)
        item.lock_version += 1
        return item

    async def ensure(self, items: Sequence[ChecklistItem]) -> None:
        have = {
            (i.student_id, i.list_entry_id, i.template_key)
            for i in self.d.items.values()
        }
        for i in items:
            if (i.student_id, i.list_entry_id, i.template_key) not in have:
                self.d.items[i.id] = i


class FakeDeadlines:
    """DeadlineRepository over DocState."""

    def __init__(self, d: DocState) -> None:
        """Bind the state."""
        self.d = d

    async def get(self, deadline_id: UUID) -> Deadline | None:
        return self.d.deadlines.get(deadline_id)

    async def current(
        self, *, institution_id: UUID | None = None, cycle: int | None = None
    ) -> list[Deadline]:
        return [
            x
            for x in self.d.deadlines.values()
            if x.superseded_by is None
            and (institution_id is None or x.institution_id == institution_id)
            and (cycle is None or x.cycle == cycle)
        ]

    async def add(self, deadline: Deadline) -> Deadline:
        self.d.deadlines[deadline.id] = deadline
        return deadline

    async def supersede(self, deadline_id: UUID, by: UUID) -> None:
        self.d.deadlines[deadline_id].superseded_by = by

    async def milestones_of_entries(
        self, entry_ids: Collection[UUID]
    ) -> list[Milestone]:
        return [m for m in self.d.milestones.values() if m.list_entry_id in entry_ids]

    async def milestones_of_deadline(self, deadline_id: UUID) -> list[DueMilestone]:
        out = []
        for m in self.d.milestones.values():
            if m.deadline_id == deadline_id:
                out.append(
                    DueMilestone(
                        dataclasses.replace(m),
                        self.d.milestone_owner[m.id],
                        self.d.deadlines[deadline_id].institution_id,
                    )
                )
        return out

    async def save_milestone(self, milestone: Milestone) -> None:
        self.d.milestones[milestone.id] = milestone

    async def due_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[DueMilestone]:
        out = []
        for m in self.d.milestones.values():
            if m.due_utc and start <= m.due_utc <= end:
                inst = (
                    self.d.deadlines[m.deadline_id].institution_id
                    if m.deadline_id
                    else new_id()
                )
                out.append(DueMilestone(m, self.d.milestone_owner[m.id], inst))
        return out

    async def prefs(self, student_id: UUID) -> ReminderPrefs | None:
        return self.d.prefs.get(student_id)

    async def save_prefs(
        self, prefs: ReminderPrefs, expected_lock: int | None
    ) -> ReminderPrefs:
        self.d.prefs[prefs.student_id] = prefs
        return prefs

    async def add_reminder(self, reminder: ReminderRecord) -> bool:
        if reminder.dedupe_key in self.d.reminders:
            return False
        self.d.reminders[reminder.dedupe_key] = reminder
        return True

    async def supersede_reminders(self, milestone_ids: Sequence[UUID]) -> list[str]:
        keys = []
        for key, r in self.d.reminders.items():
            if r.milestone_id in milestone_ids and r.sent_at is None:
                keys.append(key)
        return keys

    async def institution_names(self, ids: Collection[UUID]) -> dict[UUID, str]:
        return {i: self.d.institution_names.get(i, "Uni") for i in ids}


class FakeTranscripts:
    """TranscriptRepository over DocState."""

    def __init__(self, d: DocState) -> None:
        """Bind the state."""
        self.d = d

    async def add(self, request: Transcript) -> Transcript:
        if await self.open_of(request.student_id):
            raise AdmissionConflictError()
        request.requested_at = NOW
        self.d.transcripts[request.id] = request
        return request

    async def get(self, request_id: UUID) -> Transcript | None:
        return self.d.transcripts.get(request_id)

    async def open_of(self, student_id: UUID) -> Transcript | None:
        return next(
            (
                t
                for t in self.d.transcripts.values()
                if t.student_id == student_id and t.status == "requested"
            ),
            None,
        )

    async def of_student(self, student_id: UUID) -> list[Transcript]:
        return [t for t in self.d.transcripts.values() if t.student_id == student_id]

    async def listing(
        self, student_ids: Collection[UUID] | None, status: str | None
    ) -> list[Transcript]:
        return [
            t
            for t in self.d.transcripts.values()
            if (student_ids is None or t.student_id in student_ids)
            and (status is None or t.status == status)
        ]

    async def save(self, request: Transcript, *, expected_lock: int) -> Transcript:
        _lock(request, expected_lock)
        request.lock_version += 1
        return request

    async def officer_settings(self, user_id: UUID) -> OfficerSettings | None:
        return self.d.officers.get(user_id)

    async def save_officer_settings(
        self, settings: OfficerSettings, expected_lock: int | None
    ) -> OfficerSettings:
        self.d.officers[settings.user_id] = settings
        return settings


class DocUow(FakeUow):
    """FakeUow with the documents slice and a notification sink."""

    def __init__(self, s: FakeStore, d: DocState) -> None:
        """Bind both states."""
        super().__init__(s)
        self.documents = FakeDocuments(d)
        self.checklist = FakeChecklist(d)
        self.deadlines = FakeDeadlines(d)
        self.transcripts = FakeTranscripts(d)
        self.notify = lambda *drafts: d.notifications.extend(drafts)
        self._d = d

    async def cancel_notification(self, dedupe_key: str) -> bool:
        if dedupe_key in self._d.pending_keys:
            self._d.pending_keys.discard(dedupe_key)
            return True
        return False


class FakeFiles:
    """FilesApi stand-in that stores nothing."""

    def __init__(self) -> None:
        """Start with no files."""
        self.stored: list[dict[str, Any]] = []
        self.ttls: list[int] = []

    async def store_bytes(self, **kw: Any) -> FileRef:
        self.stored.append(kw)
        return FileRef(
            new_id(),
            kw["owner_id"],
            FileScope.STUDENT,
            FilePurpose.ADMISSION_DOCUMENT,
            kw["name"],
            "application/pdf",
            len(kw["data"]),
            "ready",
            None,
            kw.get("confidential", False),
        )

    async def issue_signed_download(
        self, file_id: UUID, ttl_seconds: int = 300
    ) -> SignedDownload:
        self.ttls.append(ttl_seconds)
        return SignedDownload(f"https://f/{file_id}", NOW)


class FakeIdentity:
    """Identity directory with a few users and role holders."""

    def __init__(
        self, users: dict[UUID, UserRef], by_role: dict[Role, list[UUID]]
    ) -> None:
        """Keep the data."""
        self.users, self.by_role = users, by_role

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        return {u: self.users[u] for u in user_ids if u in self.users}

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        out: list[UUID] = []
        for r in roles:
            out.extend(self.by_role.get(r, []))
        return out


def user_ref(user_id: UUID, first: str = "Ali", last: str = "Valiev") -> UserRef:
    """Return a minimal active user."""
    return UserRef(
        id=user_id,
        login=None,
        first_name=first,
        last_name=last,
        middle_name=None,
        roles=frozenset(),
        status="active",  # type: ignore[arg-type]
        locale="ru",
        emis_status=None,
    )


class DocKit:
    """Services over one store."""

    def __init__(self, consent: bool = True) -> None:
        """Wire everything."""
        from app.modules.admission.application.deadlines import DeadlineService
        from app.modules.admission.application.documents import DocumentService
        from app.modules.admission.application.runtime_settings import (
            RuntimeSettingsService,
        )
        from app.modules.admission.application.transcripts import TranscriptService
        from tests.admission.unit.test_access_policy import (
            GROUP,
            OTHER,
            STAFF,
            STUDENT,
            World,
        )

        self.w = World(consent)
        self.d = DocState()
        self.student, self.other, self.staff = STUDENT, OTHER, STAFF
        self.group = GROUP
        self.officer = new_id()
        self.files = FakeFiles()
        self.identity = FakeIdentity(
            {
                STUDENT: user_ref(STUDENT),
                self.officer: user_ref(self.officer, "Ol", "O"),
            },
            {Role.TRANSCRIPT_OFFICER: [self.officer], Role.COUNSELOR: [STAFF]},
        )
        uow = lambda: DocUow(self.w.store, self.d)  # noqa: E731
        clock = self.w.policy._clock  # type: ignore[attr-defined]
        self.clock = clock
        self.runtime = RuntimeSettingsService(uow)
        self.docs = DocumentService(
            uow,  # type: ignore[arg-type]
            self.w.policy,
            clock,
            self.files,
            self.identity,
            StaticLimits(LimitsSettings()),
        )
        self.deadlines = DeadlineService(uow, self.w.policy, clock)
        self.transcripts = TranscriptService(
            uow,
            self.w.policy,
            self.runtime,
            clock,
            self.w.membership,
            self.files,  # type: ignore[arg-type]
            self.identity,  # type: ignore[arg-type]
        )
