"""Port: legal documents and acceptances."""

from collections.abc import Collection, Sequence
from typing import Protocol
from uuid import UUID

from app.modules.legal.domain.models import Acceptance, DocKey, LegalDocument


class LegalRepository(Protocol):
    """Documents of every kind and scope and the acceptances of users."""

    async def lock_kind(self, kind: str, app_scope: str) -> None:
        """Serialize writers of one kind and scope until the transaction ends."""
        ...

    async def list_documents(self) -> list[LegalDocument]:
        """Every version, by scope, kind, then newest version first."""
        ...

    async def list_current(
        self, app_scopes: Collection[str] | None = None
    ) -> list[LegalDocument]:
        """The newest published version of each (kind, scope) that has one.

        ``app_scopes`` limits the result to those scopes; None means all.
        """
        ...

    async def get_current(self, kind: str, app_scope: str) -> LegalDocument | None:
        """The newest published version of the kind in the scope."""
        ...

    async def get_draft(self, kind: str, app_scope: str) -> LegalDocument | None:
        """The draft of the kind in the scope, if any."""
        ...

    async def next_version(self, kind: str, app_scope: str) -> int:
        """The number after the newest version of the kind in the scope."""
        ...

    async def add(self, document: LegalDocument) -> None:
        """Insert a document."""
        ...

    async def save(self, document: LegalDocument) -> None:
        """Write the editable fields and the publication of a document."""
        ...

    async def accepted_versions(self, user_id: UUID) -> dict[DocKey, set[int]]:
        """Versions the user accepted, by (kind, scope)."""
        ...

    async def add_acceptances(self, acceptances: Sequence[Acceptance]) -> None:
        """Insert acceptances; one the user already gave is skipped."""
        ...

    async def count_acceptances(self, current: dict[DocKey, int]) -> dict[DocKey, int]:
        """Distinct users that accepted the given version, by (kind, scope)."""
        ...
