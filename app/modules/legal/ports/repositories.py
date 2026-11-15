"""Port: legal documents and acceptances."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.legal.domain.models import Acceptance, LegalDocument


class LegalRepository(Protocol):
    """Documents of every kind and the acceptances of users."""

    async def lock_kind(self, kind: str) -> None:
        """Serialize writers of one kind until the transaction ends."""
        ...

    async def list_documents(self) -> list[LegalDocument]:
        """Every version, by kind then newest version first."""
        ...

    async def list_current(self) -> list[LegalDocument]:
        """The newest published version of each kind that has one."""
        ...

    async def get_current(self, kind: str) -> LegalDocument | None:
        """The newest published version of the kind."""
        ...

    async def get_draft(self, kind: str) -> LegalDocument | None:
        """The draft of the kind, if any."""
        ...

    async def next_version(self, kind: str) -> int:
        """The number after the newest version of the kind (drafts count)."""
        ...

    async def add(self, document: LegalDocument) -> None:
        """Insert a document."""
        ...

    async def save(self, document: LegalDocument) -> None:
        """Write the editable fields and the publication of a document."""
        ...

    async def accepted_versions(self, user_id: UUID) -> dict[str, set[int]]:
        """Versions the user accepted, by kind."""
        ...

    async def add_acceptances(self, acceptances: Sequence[Acceptance]) -> None:
        """Insert acceptances; one the user already gave is skipped."""
        ...

    async def count_acceptances(self, current: dict[str, int]) -> dict[str, int]:
        """Distinct users that accepted the given version, by kind."""
        ...
