"""In-memory excuses: repository, transaction, directory, tokens and a world."""

import dataclasses
import datetime as dt
from collections.abc import Sequence
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from app.modules.academic.application.excuses.access import ExcuseAccess
from app.modules.academic.application.excuses.cancel_excuse import CancelExcuse
from app.modules.academic.application.excuses.coverage import ExcuseCoverageQuery
from app.modules.academic.application.excuses.create_exclusion import (
    CreateExcuseExclusion,
)
from app.modules.academic.application.excuses.create_request import (
    CreateExcuseRequest,
)
from app.modules.academic.application.excuses.decide_by_token import (
    DecideExcuseByToken,
)
from app.modules.academic.application.excuses.decide_excuse import DecideExcuse
from app.modules.academic.application.excuses.end_excuse import (
    EndExcuse,
    RevokeExcuse,
)
from app.modules.academic.application.excuses.excuse_status import ExcuseStatusQuery
from app.modules.academic.application.excuses.notices import ExcuseNotices
from app.modules.academic.application.excuses.ports import (
    DecisionGrant,
    Person,
    StudentContext,
)
from app.modules.academic.application.excuses.post_message import PostExcuseMessage
from app.modules.academic.application.excuses.queries import (
    GetExcuse,
    ListExcuses,
    ListExcuseTemplates,
)
from app.modules.academic.application.excuses.views import ExcusePresenter
from app.modules.academic.application.excuses.work_offs import ExcuseWorkOffs
from app.modules.academic.domain.classwork.work_off import (
    ResolvedWorkOff,
    WorkOff,
)
from app.modules.academic.domain.excuses.excuse import (
    Excuse,
    ExcuseMessage,
    ExcuseStatus,
    ExcuseTemplate,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft
from tests.fakes.clock import FixedClock


class FakeExcuseRepository:
    """Excuses held in dicts."""

    def __init__(self, templates: list[ExcuseTemplate]) -> None:
        """Start with the templates."""
        self.rows: dict[UUID, Excuse] = {}
        self.thread: list[ExcuseMessage] = []
        self._templates = templates

    async def add(self, excuse: Excuse) -> None:
        """Insert."""
        self.rows[excuse.id] = dataclasses.replace(excuse)

    async def get(self, excuse_id: UUID) -> Excuse | None:
        """Return a copy."""
        row = self.rows.get(excuse_id)
        return None if row is None else dataclasses.replace(row)

    async def save(self, excuse: Excuse) -> None:
        """Overwrite."""
        self.rows[excuse.id] = dataclasses.replace(excuse)

    async def search(
        self,
        *,
        student_ids: Sequence[UUID] | None,
        status: ExcuseStatus | None,
        offset: int,
        limit: int,
    ) -> list[Excuse]:
        """Newest first."""
        found = [
            e
            for e in self.rows.values()
            if (student_ids is None or e.student_id in student_ids)
            and (status is None or e.status == status)
        ]
        found.sort(key=lambda e: e.created_at, reverse=True)
        return found[offset : offset + limit]

    async def covering(self, student_ids: Sequence[UUID], day: dt.date) -> list[Excuse]:
        """Approved excuses active on the day."""
        return [
            e
            for e in self.rows.values()
            if e.student_id in student_ids and e.is_active_on(day)
        ]

    async def add_message(self, message: ExcuseMessage) -> None:
        """Append."""
        self.thread.append(message)

    async def messages(self, excuse_id: UUID) -> list[ExcuseMessage]:
        """The thread."""
        return [m for m in self.thread if m.excuse_id == excuse_id]

    async def templates(self, *, active_only: bool) -> list[ExcuseTemplate]:
        """Templates."""
        return [t for t in self._templates if t.active or not active_only]


class FakeWorkOffs:
    """The two work-off methods excuses use."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: list[WorkOff] = []

    async def for_lessons(self, lesson_ids: Sequence[UUID]) -> list[WorkOff]:
        """Work-offs of the lessons."""
        return [w for w in self.rows if w.lesson_id in lesson_ids]

    async def upsert(
        self,
        *,
        lesson_id: UUID,
        student_id: UUID,
        assigned_by: UUID,
        resolved: ResolvedWorkOff,
        at: dt.datetime,
    ) -> WorkOff:
        """Create the work-off."""
        row = WorkOff(
            id=new_id(),
            lesson_id=lesson_id,
            student_id=student_id,
            assigned_by=assigned_by,
            template_id=resolved.template_id,
            text=resolved.text,
            status="assigned",  # type: ignore[arg-type]
            due_date=resolved.due_date,
            done_at=None,
            created_at=at,
            updated_at=at,
        )
        self.rows.append(row)
        return row


class FakeExcuseUow:
    """A transaction that records drafts and commits."""

    def __init__(self, world: "ExcuseWorld") -> None:
        """Bind to the world."""
        self.world = world
        self.excuses = world.repo
        self.work_offs: Any = world.work_off_rows
        self._drafts: list[NotificationDraft] = []

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue."""
        self._drafts.extend(drafts)

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to roll back."""

    async def commit(self) -> None:
        """Publish the drafts."""
        self.world.notifications.extend(self._drafts)
        self._drafts = []


class FakeDirectory:
    """Students, curators and people."""

    def __init__(self) -> None:
        """Start empty."""
        self.contexts: dict[UUID, StudentContext] = {}
        self.persons: dict[UUID, Person] = {}
        self.admins: list[UUID] = []

    async def student_context(self, student_id: UUID) -> StudentContext | None:
        """The context."""
        return self.contexts.get(student_id)

    async def curated_student_ids(self, curator_id: UUID) -> list[UUID]:
        """Students whose curator is the user."""
        return [s for s, c in self.contexts.items() if c.curator_id == curator_id]

    async def people(self, user_ids: Sequence[UUID]) -> dict[UUID, Person]:
        """Known people."""
        return {u: self.persons[u] for u in user_ids if u in self.persons}

    async def admin_ids(self) -> list[UUID]:
        """Administrators."""
        return list(self.admins)


class FakeTokens:
    """Single-use tokens in a dict."""

    def __init__(self) -> None:
        """Start empty."""
        self.live: dict[str, DecisionGrant] = {}

    async def issue(self, excuse_id: UUID, user_id: UUID) -> tuple[str, str]:
        """Two new tokens."""
        approve, reject = f"a-{new_id()}", f"r-{new_id()}"
        self.live[approve] = DecisionGrant(excuse_id, user_id, True)
        self.live[reject] = DecisionGrant(excuse_id, user_id, False)
        return approve, reject

    async def consume(self, token: str, user_id: UUID) -> DecisionGrant | None:
        """Use once, only for its user."""
        grant = self.live.get(token)
        if grant is None or grant.user_id != user_id:
            return None
        del self.live[token]
        return grant

    async def revoke(self, excuse_id: UUID) -> None:
        """Forget the excuse's tokens."""
        self.live = {k: g for k, g in self.live.items() if g.excuse_id != excuse_id}


class FakeFiles:
    """Files by id; ``download_url`` is a fixed pattern."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, FileRef] = {}

    def add(
        self,
        owner_id: UUID,
        *,
        content_type: str = "application/pdf",
        status: str = "ready",
    ) -> UUID:
        """Register a file."""
        ref = FileRef(
            id=new_id(),
            owner_id=owner_id,
            scope=FileScope.STUDENT,
            purpose=FilePurpose.FEEDBACK,
            name="doc.pdf",
            content_type=content_type,
            byte_size=10,
            status=status,
            text_bytes=None,
        )
        self.rows[ref.id] = ref
        return ref.id

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Known files."""
        return {i: self.rows[i] for i in file_ids if i in self.rows}

    async def download_url(self, file_id: UUID, *, ttl_seconds: int) -> str:
        """A fake URL."""
        return f"https://files.test/{file_id}"


class FakeSchedule:
    """Lessons by student."""

    def __init__(self) -> None:
        """Start empty."""
        self.lessons: list[Any] = []

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[Any]:
        """Lessons in the window."""
        return [x for x in self.lessons if start <= x.date <= end]


class ExcuseWorld:
    """Everything wired over fakes: a curator, a student, an admin, templates."""

    def __init__(self) -> None:
        """Build the world."""
        self.clock = FixedClock()
        self.illness = ExcuseTemplate(new_id(), "illness", "Illness", True, True, 1)
        self.family = ExcuseTemplate(new_id(), "family", "Family", False, True, 2)
        self.repo = FakeExcuseRepository([self.illness, self.family])
        self.work_off_rows = FakeWorkOffs()
        self.notifications: list[NotificationDraft] = []
        self.directory = FakeDirectory()
        self.tokens = FakeTokens()
        self.files = FakeFiles()
        self.schedule = FakeSchedule()
        self.group_id = new_id()
        self.curator = self._user("Curator", Role.TEACHER)
        self.other_curator = self._user("Other", Role.TEACHER)
        self.admin = self._user("Admin", Role.ADMIN)
        self.student = self._user("Student", Role.STUDENT)
        self.stranger = self._user("Stranger", Role.STUDENT)
        self.directory.contexts[self.student.user_id] = StudentContext(
            self.student.user_id, self.group_id, self.curator.user_id
        )
        self.directory.contexts[self.stranger.user_id] = StudentContext(
            self.stranger.user_id, new_id(), self.other_curator.user_id
        )
        self.directory.admins = [self.admin.user_id]
        self.access = ExcuseAccess(self.directory)
        self.notices = ExcuseNotices(directory=self.directory, tokens=self.tokens)
        self.presenter = ExcusePresenter(
            files=self.files, directory=self.directory  # type: ignore[arg-type]
        )
        self.work_offs = ExcuseWorkOffs(
            schedule=self.schedule,  # type: ignore[arg-type]
            text_for=lambda locale: f"work off ({locale})",
            clock=self.clock,
        )
        common: dict[str, Any] = {"uow_factory": self.uow, "clock": self.clock}
        self.request = CreateExcuseRequest(
            **common,
            directory=self.directory,
            files=self.files,  # type: ignore[arg-type]
            notices=self.notices,
            presenter=self.presenter,
        )
        self.exclusion = CreateExcuseExclusion(
            **common,
            directory=self.directory,
            access=self.access,
            notices=self.notices,
            work_offs=self.work_offs,
            presenter=self.presenter,
        )
        self.decide = DecideExcuse(
            **common,
            directory=self.directory,
            access=self.access,
            notices=self.notices,
            work_offs=self.work_offs,
            tokens=self.tokens,
            presenter=self.presenter,
        )
        self.by_token = DecideExcuseByToken(tokens=self.tokens, decide=self.decide)
        self.cancel = CancelExcuse(
            **common, access=self.access, tokens=self.tokens, presenter=self.presenter
        )
        self.end = EndExcuse(**common, access=self.access, presenter=self.presenter)
        self.revoke = RevokeExcuse(
            **common,
            access=self.access,
            notices=self.notices,
            presenter=self.presenter,
        )
        self.post = PostExcuseMessage(
            **common,
            directory=self.directory,
            access=self.access,
            files=self.files,  # type: ignore[arg-type]
            notices=self.notices,
            presenter=self.presenter,
        )
        self.list = ListExcuses(
            uow_factory=self.uow, directory=self.directory, presenter=self.presenter
        )
        self.get = GetExcuse(
            uow_factory=self.uow, access=self.access, presenter=self.presenter
        )
        self.templates = ListExcuseTemplates(uow_factory=self.uow)
        self.coverage = ExcuseCoverageQuery(uow_factory=self.uow)
        self.status = ExcuseStatusQuery(
            uow_factory=self.uow,
            directory=self.directory,
            schedule=self.schedule,  # type: ignore[arg-type]
        )

    def uow(self) -> FakeExcuseUow:
        """Open a transaction."""
        return FakeExcuseUow(self)

    def _user(self, name: str, role: Role) -> Actor:
        actor = Actor(user_id=new_id(), roles=frozenset({role}))
        self.directory.persons[actor.user_id] = Person(actor.user_id, name, "ru")
        return actor
