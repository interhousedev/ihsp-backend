"""In-memory file repository and unit of work."""

import copy
from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft

_COUNTED = {FileStatus.PENDING, FileStatus.PROCESSING, FileStatus.READY}


def _study_file(file: StoredFile) -> bool:
    """Library files are left out of owner lists, search and clean-up."""
    return file.scope != FileScope.LIBRARY


class FileStore:
    """The 'database': rows and indexed texts shared by every transaction."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, StoredFile] = {}
        self.texts: dict[UUID, str] = {}


class InMemoryFileRepository:
    """FileRepository over a working copy of the store."""

    def __init__(self, store: FileStore) -> None:
        """Work on the given (copied) store."""
        self.store = store
        self.locked: list[UUID] = []

    async def lock_owner(self, owner_id: UUID) -> None:
        """Remember the lock request."""
        self.locked.append(owner_id)

    async def used_bytes(
        self, owner_id: UUID, scope: FileScope, term_id: UUID | None
    ) -> int:
        """Sum counted bytes like the SQL repository."""
        return sum(
            f.byte_size
            for f in self.store.rows.values()
            if f.owner_id == owner_id
            and f.scope == scope
            and f.status in _COUNTED
            and (scope != FileScope.STUDENT or f.term_id == term_id)
        )

    async def add(self, file: StoredFile) -> None:
        """Insert a row."""
        self.store.rows[file.id] = copy.deepcopy(file)

    async def save(self, file: StoredFile) -> None:
        """Replace a row."""
        self.store.rows[file.id] = copy.deepcopy(file)

    async def get(self, file_id: UUID) -> StoredFile | None:
        """Return a copy of the row."""
        row = self.store.rows.get(file_id)
        return None if row is None else copy.deepcopy(row)

    async def get_many(self, file_ids: Sequence[UUID]) -> list[StoredFile]:
        """Return copies of existing rows."""
        return [
            copy.deepcopy(self.store.rows[i]) for i in file_ids if i in self.store.rows
        ]

    async def list_for_owner(
        self,
        owner_id: UUID,
        *,
        purpose: FilePurpose | None,
        after: tuple[datetime, UUID] | None,
        limit: int,
        name_query: str | None = None,
        content_types: Sequence[str] | None = None,
        oldest_first: bool = False,
        offset: int = 0,
    ) -> list[StoredFile]:
        """Newest first; pending and deleted are hidden."""
        rows = [
            f
            for f in self.store.rows.values()
            if f.owner_id == owner_id
            and _study_file(f)
            and f.status not in {FileStatus.PENDING, FileStatus.DELETED}
            and (purpose is None or f.purpose == purpose)
            and (not name_query or name_query.lower() in f.name.lower())
            and (content_types is None or f.content_type in content_types)
        ]
        rows.sort(key=lambda f: (f.created_at, f.id), reverse=not oldest_first)
        if after is not None:
            rows = [f for f in rows if (f.created_at, f.id) < after]
        return [copy.deepcopy(f) for f in rows[offset : offset + limit]]

    async def list_ready(self, owner_id: UUID, limit: int) -> list[StoredFile]:
        """Ready files of the owner, newest first."""
        rows = [
            f
            for f in self.store.rows.values()
            if f.owner_id == owner_id
            and _study_file(f)
            and f.status == FileStatus.READY
        ]
        rows.sort(key=lambda f: (f.created_at, f.id), reverse=True)
        return [copy.deepcopy(f) for f in rows[:limit]]

    async def list_for_owner_all(self, owner_id: UUID, limit: int) -> list[StoredFile]:
        """Every non-deleted file of the owner."""
        rows = [
            f
            for f in self.store.rows.values()
            if f.owner_id == owner_id
            and _study_file(f)
            and f.status != FileStatus.DELETED
        ]
        return [copy.deepcopy(f) for f in rows[:limit]]

    async def set_text(self, file_id: UUID, text_bytes: int, content: str) -> None:
        """Index the text."""
        row = copy.deepcopy(self.store.rows[file_id])
        row.text_bytes = text_bytes
        self.store.rows[file_id] = row
        self.store.texts[file_id] = content

    async def search(self, owner_id: UUID, query: str, limit: int) -> list[StoredFile]:
        """All words of the query must appear (case-insensitive)."""
        words = query.lower().split()
        found = [
            f
            for f in self.store.rows.values()
            if f.owner_id == owner_id
            and _study_file(f)
            and f.status == FileStatus.READY
            and f.id in self.store.texts
            and all(w in self.store.texts[f.id].lower() for w in words)
        ]
        return [copy.deepcopy(f) for f in found[:limit]]

    async def headline(self, document: str, query: str) -> str:
        """A fragment around the first query word, the word in ``**``."""
        word = query.lower().split()[0]
        at = document.lower().find(word)
        if at < 0:
            return ""
        start = max(0, at - 20)
        return (
            document[start:at]
            + "**"
            + document[at : at + len(word)]
            + "**"
            + document[at + len(word) : at + 40]
        )

    async def student_term_ids(self) -> list[UUID]:
        """Terms with live student files."""
        return sorted(
            {
                f.term_id
                for f in self.store.rows.values()
                if f.scope == FileScope.STUDENT
                and f.term_id is not None
                and f.status != FileStatus.DELETED
            }
        )

    async def list_expired(
        self, *, expired_term_ids: Sequence[UUID], now: datetime, limit: int
    ) -> list[StoredFile]:
        """Files of expired terms or past their own expires_at."""
        rows = [
            f
            for f in self.store.rows.values()
            if f.status != FileStatus.DELETED
            and _study_file(f)
            and (
                (f.expires_at is not None and f.expires_at < now)
                or (f.scope == FileScope.STUDENT and f.term_id in expired_term_ids)
            )
        ]
        return [copy.deepcopy(f) for f in rows[:limit]]

    async def term_owner_counts(self, term_id: UUID) -> list[tuple[UUID, int]]:
        """Owners of live student files in the term."""
        counts: dict[UUID, int] = {}
        for f in self.store.rows.values():
            if (
                f.scope == FileScope.STUDENT
                and f.term_id == term_id
                and f.status in {FileStatus.PROCESSING, FileStatus.READY}
            ):
                counts[f.owner_id] = counts.get(f.owner_id, 0) + 1
        return sorted(counts.items())

    async def list_stale_uploads(
        self, older_than: datetime, limit: int
    ) -> list[StoredFile]:
        """Old pending and rejected rows."""
        rows = [
            f
            for f in self.store.rows.values()
            if (f.status == FileStatus.PENDING and f.created_at < older_than)
            or (f.status == FileStatus.REJECTED and f.updated_at < older_than)
        ]
        return [copy.deepcopy(f) for f in rows[:limit]]

    async def list_stale_processing(
        self, older_than: datetime, limit: int
    ) -> list[StoredFile]:
        """Rows in processing for too long."""
        rows = [
            f
            for f in self.store.rows.values()
            if f.status == FileStatus.PROCESSING and f.updated_at < older_than
        ]
        return [copy.deepcopy(f) for f in rows[:limit]]

    async def mark_deleted(self, file_ids: Sequence[UUID], now: datetime) -> None:
        """Soft-delete rows and drop their index."""
        for file_id in file_ids:
            row = copy.deepcopy(self.store.rows[file_id])
            row.mark_deleted(now)
            self.store.rows[file_id] = row
            self.store.texts.pop(file_id, None)

    async def delete_rows(self, file_ids: Sequence[UUID]) -> None:
        """Remove rows."""
        for file_id in file_ids:
            self.store.rows.pop(file_id, None)
            self.store.texts.pop(file_id, None)


class FakeFilesUnitOfWork:
    """A transaction over a copy of the store; commit writes the copy back."""

    def __init__(self, store: FileStore, log: "UowLog") -> None:
        """Remember the shared store and the commit log."""
        self._store = store
        self._log = log
        self._notifications: list[NotificationDraft] = []
        self._after_commit: list[AfterCommit] = []
        self.files: InMemoryFileRepository

    async def __aenter__(self) -> Self:
        """Start from a copy of the store."""
        work = FileStore()
        work.rows = dict(self._store.rows)  # entities are copied when written
        work.texts = dict(self._store.texts)
        self.files = InMemoryFileRepository(work)
        self._notifications, self._after_commit = [], []
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Discard uncommitted changes."""

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications."""
        self._notifications.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Audit events are not used by this module."""

    def after_commit(self, hook: AfterCommit) -> None:
        """Queue a hook."""
        self._after_commit.append(hook)

    async def commit(self) -> None:
        """Publish the working copy, record notifications and run hooks."""
        self._store.rows = self.files.store.rows
        self._store.texts = self.files.store.texts
        self._log.notifications.extend(self._notifications)
        self._log.commits += 1
        self._log.locked.extend(self.files.locked)
        hooks, self._after_commit = self._after_commit, []
        for hook in hooks:
            await hook()


class UowLog:
    """What committed transactions did, for assertions."""

    def __init__(self) -> None:
        """Start empty."""
        self.notifications: list[NotificationDraft] = []
        self.commits = 0
        self.locked: list[UUID] = []


class FakeFilesDatabase:
    """The shared store, its log and the unit-of-work factory."""

    def __init__(self) -> None:
        """Start with an empty store."""
        self.store = FileStore()
        self.log = UowLog()

    def uow(self) -> FakeFilesUnitOfWork:
        """Return a new transaction (the UowFactory)."""
        return FakeFilesUnitOfWork(self.store, self.log)

    def row(self, file_id: UUID) -> StoredFile:
        """Return the committed row (test helper)."""
        return self.store.rows[file_id]

    def all_rows(self) -> list[Any]:
        """Return every committed row (test helper)."""
        return list(self.store.rows.values())
