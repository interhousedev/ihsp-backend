"""Port: stored preference answers and university decisions of a student."""

import datetime as dt
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.modules.admission.domain.matching import PreferenceAnswers
from app.modules.admission.ports.chooser import CatalogRepository, ListRepository


class PreferenceRepository(Protocol):
    """One row of answers per student."""

    async def get(
        self, student_id: UUID
    ) -> tuple[PreferenceAnswers, dt.datetime] | None:
        """The answers and when they were last saved."""
        ...

    async def save(
        self, student_id: UUID, answers: PreferenceAnswers, now: dt.datetime
    ) -> None:
        """Insert or replace the answers."""
        ...


class DecisionRepository(Protocol):
    """A student's swipes on universities."""

    async def decided(self, student_id: UUID) -> dict[UUID, str]:
        """University id → decision."""
        ...

    async def get(self, student_id: UUID, institution_id: UUID) -> str | None:
        """The decision on one university."""
        ...

    async def created_entry(self, student_id: UUID, institution_id: UUID) -> bool:
        """Whether the swipe itself put the university on the list."""
        ...

    async def set(
        self,
        student_id: UUID,
        institution_id: UUID,
        decision: str,
        now: dt.datetime,
        *,
        created_list_entry: bool = False,
    ) -> None:
        """Insert or replace the decision (idempotent)."""
        ...

    async def delete(self, student_id: UUID, institution_id: UUID) -> None:
        """Forget the decision."""
        ...


class MatchUnitOfWork(Protocol):
    """The part of the admission unit of work the matching slice uses."""

    @property
    def preferences(self) -> PreferenceRepository:
        """Stored answers."""
        ...

    @property
    def decisions(self) -> DecisionRepository:
        """Stored decisions."""
        ...

    @property
    def catalog(self) -> CatalogRepository:
        """Institutions."""
        ...

    @property
    def shortlist(self) -> ListRepository:
        """The student's list."""
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
