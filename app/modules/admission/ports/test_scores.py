"""Port: the test catalog and the students' test and certificate entries."""

from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.modules.admission.domain.test_scores import ScoreEntry, ScoreTest
from app.modules.admission.ports.documents import DocumentRepository
from app.modules.admission.ports.repositories import AccessRepository


class ScoreRepository(Protocol):
    """Rows of the tests & certificates slice."""

    async def catalog(self, *, include_inactive: bool) -> list[ScoreTest]:
        """Tests ordered by position and key."""
        ...

    async def get_test(self, test_id: UUID) -> ScoreTest | None:
        """One test, active or not."""
        ...

    async def key_taken(self, key: str, *, except_id: UUID | None) -> bool:
        """Return whether another test already uses the key."""
        ...

    async def save_test(self, test: ScoreTest) -> ScoreTest:
        """Insert or update a test."""
        ...

    async def delete_test(self, test_id: UUID) -> None:
        """Delete a test that has no entries."""
        ...

    async def test_in_use(self, test_id: UUID) -> bool:
        """Return whether any student entry refers to the test."""
        ...

    async def entries(self, student_id: UUID) -> list[ScoreEntry]:
        """A student's entries, newest first."""
        ...

    async def get_entry(self, entry_id: UUID) -> ScoreEntry | None:
        """One entry."""
        ...

    async def save_entry(self, entry: ScoreEntry) -> ScoreEntry:
        """Insert or update an entry."""
        ...

    async def delete_entry(self, entry_id: UUID) -> None:
        """Remove an entry."""
        ...


class ScoreUnitOfWork(Protocol):
    """The part of the admission unit of work this slice uses."""

    @property
    def test_scores(self) -> ScoreRepository:
        """Catalog and entries."""
        ...

    @property
    def documents(self) -> DocumentRepository:
        """Uploaded certificate documents."""
        ...

    @property
    def access(self) -> AccessRepository:
        """The audit log."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...
