"""In-memory unit of work, account control and sources of the privacy module."""

import copy
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime, timedelta
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from app.modules.privacy.domain.models import (
    ErasureRequest,
    ErasureStatus,
    ExportJob,
    ExportStatus,
)
from app.modules.privacy.ports.gateways import OwnedFile
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.contracts.privacy import AccountInfo
from app.shared.notifications import AuditDraft, NotificationDraft

OPEN = (ErasureStatus.PENDING_REVIEW, ErasureStatus.APPROVED)


class FakePrivacyStore:
    """The "database": requests, exports and what was committed."""

    def __init__(self) -> None:
        """Start empty."""
        self.requests: list[ErasureRequest] = []
        self.exports: list[ExportJob] = []
        self.audits: list[AuditDraft] = []
        self.notifications: list[NotificationDraft] = []
        self.commits = 0


class FakeErasureRepository:
    """Erasure requests of a store."""

    def __init__(self, store: FakePrivacyStore) -> None:
        """Bind to the store."""
        self.store = store

    async def add(self, request: ErasureRequest) -> None:
        """Insert."""
        self.store.requests.append(copy.deepcopy(request))

    async def get(self, request_id: UUID) -> ErasureRequest | None:
        """Return a copy or None."""
        for r in self.store.requests:
            if r.id == request_id:
                return copy.deepcopy(r)
        return None

    async def get_open(self, user_id: UUID) -> ErasureRequest | None:
        """The newest open request of the user."""
        found = [
            r for r in self.store.requests if r.user_id == user_id and r.status in OPEN
        ]
        found.sort(key=lambda r: r.requested_at, reverse=True)
        return copy.deepcopy(found[0]) if found else None

    async def list(
        self, status: ErasureStatus | None, *, limit: int, offset: int
    ) -> Sequence[ErasureRequest]:
        """Newest first."""
        rows = [r for r in self.store.requests if status in (None, r.status)]
        rows.sort(key=lambda r: r.requested_at, reverse=True)
        return [copy.deepcopy(r) for r in rows[offset : offset + limit]]

    async def save(self, request: ErasureRequest) -> None:
        """Replace by id."""
        for i, r in enumerate(self.store.requests):
            if r.id == request.id:
                self.store.requests[i] = copy.deepcopy(request)


class FakeExportRepository:
    """Exports of a store."""

    def __init__(self, store: FakePrivacyStore) -> None:
        """Bind to the store."""
        self.store = store

    async def add(self, job: ExportJob) -> None:
        """Insert."""
        self.store.exports.append(copy.deepcopy(job))

    async def get(self, export_id: UUID) -> ExportJob | None:
        """Return a copy or None."""
        for j in self.store.exports:
            if j.id == export_id:
                return copy.deepcopy(j)
        return None

    async def latest_of(self, user_id: UUID) -> ExportJob | None:
        """Newest export that did not fail."""
        rows = [
            j
            for j in self.store.exports
            if j.user_id == user_id and j.status is not ExportStatus.FAILED
        ]
        rows.sort(key=lambda j: j.created_at, reverse=True)
        return copy.deepcopy(rows[0]) if rows else None

    async def list_of(self, user_id: UUID, *, limit: int) -> Sequence[ExportJob]:
        """Newest first."""
        rows = [j for j in self.store.exports if j.user_id == user_id]
        rows.sort(key=lambda j: j.created_at, reverse=True)
        return [copy.deepcopy(j) for j in rows[:limit]]

    async def expired(self, now: datetime, *, limit: int) -> Sequence[ExportJob]:
        """Stored archives past their expiry."""
        rows = [
            j
            for j in self.store.exports
            if j.storage_key and j.expires_at is not None and j.expires_at <= now
        ]
        return [copy.deepcopy(j) for j in rows[:limit]]

    async def save(self, job: ExportJob) -> None:
        """Replace by id."""
        for i, j in enumerate(self.store.exports):
            if j.id == job.id:
                self.store.exports[i] = copy.deepcopy(job)


class FakePrivacyUnitOfWork:
    """Notices and audits land at commit; hooks run after it."""

    def __init__(self, store: FakePrivacyStore) -> None:
        """Bind to the store."""
        self.store = store
        self.erasure = FakeErasureRepository(store)
        self.exports = FakeExportRepository(store)
        self._notes: list[NotificationDraft] = []
        self._audits: list[AuditDraft] = []
        self._hooks: list[Callable[[], Awaitable[None]]] = []

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications."""
        self._notes.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audits."""
        self._audits.extend(drafts)

    def after_commit(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Queue a hook."""
        self._hooks.append(hook)

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Drop what was not committed."""
        self._notes, self._audits, self._hooks = [], [], []

    async def commit(self) -> None:
        """Publish notices and audits, then run the hooks."""
        self.store.notifications.extend(self._notes)
        self.store.audits.extend(self._audits)
        self.store.commits += 1
        hooks, self._hooks, self._notes, self._audits = self._hooks, [], [], []
        for hook in hooks:
            await hook()


def fake_uow_factory(store: FakePrivacyStore) -> Callable[[], FakePrivacyUnitOfWork]:
    """A factory of units of work over the store."""
    return lambda: FakePrivacyUnitOfWork(store)


class FakeAccountControl:
    """Records what privacy asked identity to do."""

    def __init__(self, today: date) -> None:
        """Remember the day the window starts."""
        self.today = today
        self.started: list[tuple[UUID, UUID]] = []
        self.notices: list[tuple[UUID, str, dict[str, Any]]] = []
        self.accounts: dict[UUID, AccountInfo] = {}

    def add_account(self, user_id: UUID, name: str = "Ann") -> None:
        """Make ``describe`` know the user."""
        self.accounts[user_id] = AccountInfo(
            user_id, name, "ann", frozenset({Role.STUDENT}), UserStatus.ACTIVE
        )

    async def start_deletion(
        self, user_id: UUID, *, approved_by: UUID, ip: str | None
    ) -> date:
        """Record and return the purge date."""
        self.started.append((user_id, approved_by))
        return self.today + timedelta(days=30)

    async def send_notice(
        self, user_id: UUID, text_key: str, params: dict[str, Any]
    ) -> None:
        """Record the notice."""
        self.notices.append((user_id, text_key, params))

    async def describe(self, user_ids: Sequence[UUID]) -> dict[UUID, AccountInfo]:
        """Known accounts among the ids."""
        return {u: self.accounts[u] for u in user_ids if u in self.accounts}


class FakeOwnedFiles:
    """Files by owner."""

    def __init__(self) -> None:
        """Start empty."""
        self.files: dict[UUID, list[OwnedFile]] = {}

    async def list_of(self, user_id: UUID) -> Sequence[OwnedFile]:
        """The user's files."""
        return self.files.get(user_id, [])


class FakePersonalData:
    """A source with fixed rows; ``erase`` clears them."""

    def __init__(self, rows: dict[UUID, dict[str, list[dict[str, Any]]]]) -> None:
        """Rows by user, then table."""
        self.rows = rows
        self.erased: list[UUID] = []
        self.fail = False

    def tables(self) -> Sequence[Any]:
        """Not used by the use cases."""
        return []

    async def export(self, user_id: UUID) -> dict[str, list[dict[str, Any]]]:
        """The user's rows."""
        if self.fail:
            raise RuntimeError("boom")
        return self.rows.get(user_id, {})

    async def erase(self, user_id: UUID) -> int:
        """Drop the rows."""
        self.erased.append(user_id)
        return sum(len(v) for v in self.rows.pop(user_id, {}).values())
