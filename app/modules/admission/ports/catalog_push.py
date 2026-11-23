"""Port: write pushed institutions into the catalog."""

from typing import Any, Protocol

from app.modules.admission.domain.catalog_push import PushResult


class InstitutionPushWriter(Protocol):
    """Validates and upserts institutions in the seed shape, keyed by slug."""

    async def upsert(self, items: list[dict[str, Any]]) -> list[PushResult]:
        """One result per item, in order; a bad item never stops the others."""
        ...
