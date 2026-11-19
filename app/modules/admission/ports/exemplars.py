"""Port: the exemplar essays a review compares a draft with."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.exemplars import Exemplar, ExemplarMatch


class ExemplarSource(Protocol):
    """Finds the published exemplars closest to a draft."""

    async def closest(
        self,
        *,
        kind: str,
        prompt: str,
        body: str,
        institution_id: UUID | None,
        k: int = 3,
    ) -> tuple[ExemplarMatch, ...]:
        """Published only, best first; an empty library gives `()`.

        `kind` is the essay kind (personal_statement, supplemental, other):
        supplemental matches supplement and why_us exemplars, other matches
        any kind. The same kind ranks first, the same institution higher.
        """
        ...


class ExemplarRepository(Protocol):
    """Storage of the exemplar library."""

    async def add(self, item: Exemplar) -> None:
        """Store a new exemplar."""
        ...

    async def institution_exists(self, institution_id: UUID) -> bool:
        """Whether the catalog has the institution."""
        ...

    async def get(self, exemplar_id: UUID) -> Exemplar | None:
        """One exemplar of any status, or None."""
        ...

    async def search(
        self,
        *,
        status: str | None,
        kind: str | None,
        institution_id: UUID | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Exemplar], int]:
        """A page, newest first, and the total of the filter."""
        ...

    async def published(self) -> list[Exemplar]:
        """Every published exemplar (the corpus of a review)."""
        ...

    async def find_by_source(self, source_url: str, title: str) -> UUID | None:
        """The id of the exemplar with this link and title, if any."""
        ...

    async def update(self, item: Exemplar, *, expected_lock: int) -> bool:
        """Write the exemplar and bump its lock; False when the lock is stale."""
        ...

    async def delete(self, exemplar_id: UUID) -> bool:
        """Remove the exemplar; False when it does not exist."""
        ...
