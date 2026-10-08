"""A unit of work over the in-memory store with rollback, outbox and hooks."""

from collections.abc import Callable
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft
from tests.fakes.academic.schedule.repositories import (
    FakeGroupRepository,
    FakeLessonRepository,
    FakeRoomRepository,
    FakeStudentRepository,
    FakeSubjectRepository,
    FakeTermRepository,
    FakeTimetableEntryRepository,
)
from tests.fakes.academic.schedule.store import ScheduleStore


class FakeScheduleUnitOfWork:
    """Implements ScheduleUnitOfWork; uncommitted changes are rolled back on exit."""

    def __init__(self, store: ScheduleStore) -> None:
        """Bind to the store."""
        self.store = store
        self.terms = FakeTermRepository(store)
        self.groups = FakeGroupRepository(store)
        self.students = FakeStudentRepository(store)
        self.subjects = FakeSubjectRepository(store)
        self.rooms = FakeRoomRepository(store)
        self.entries = FakeTimetableEntryRepository(store)
        self.lessons = FakeLessonRepository(store)
        self.committed = False
        self._snapshot: dict[str, Any] | None = None
        self._notifications: list[NotificationDraft] = []
        self._audits: list[AuditDraft] = []
        self._hooks: list[AfterCommit] = []

    async def __aenter__(self) -> Self:
        """Start a transaction."""
        self._snapshot = self.store.snapshot()
        self._notifications, self._audits, self._hooks = [], [], []
        self.committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back everything that was not committed."""
        if self._snapshot is not None:
            self.store.restore(self._snapshot)
        self._snapshot = None

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications."""
        self._notifications.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        self._audits.extend(drafts)

    def after_commit(self, hook: AfterCommit) -> None:
        """Queue a hook for after the commit."""
        self._hooks.append(hook)

    async def commit(self) -> None:
        """Keep the changes, publish outbox and audit, run the hooks."""
        self.store.notifications.extend(self._notifications)
        self.store.audits.extend(self._audits)
        self._snapshot = None
        self.committed = True
        hooks, self._hooks = self._hooks, []
        self._notifications, self._audits = [], []
        for hook in hooks:
            await hook()

    async def lock_term(self, term_id: UUID) -> None:
        """Record the lock (there is no concurrency in tests)."""
        self.store.locks.append(term_id)


def uow_factory_for(store: ScheduleStore) -> Callable[[], FakeScheduleUnitOfWork]:
    """Return a factory that builds a new unit of work on the store each call."""

    def factory() -> FakeScheduleUnitOfWork:
        return FakeScheduleUnitOfWork(store)

    return factory
