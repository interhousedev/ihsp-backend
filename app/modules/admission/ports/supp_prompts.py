"""Port: supplemental essay prompts per institution and cycle."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.supp_prompts import SuppPrompt


class SuppPromptRepository(Protocol):
    """Read and replace the prompts of an institution."""

    async def institution_exists(self, institution_id: UUID) -> bool:
        """Whether the catalog has the institution."""
        ...

    async def by_cycle(self, institution_id: UUID) -> dict[str, list[SuppPrompt]]:
        """Every cycle of the institution with its prompts in position order."""
        ...

    async def replace(
        self, institution_id: UUID, cycle: str, prompts: list[SuppPrompt]
    ) -> None:
        """Drop the prompts of the cycle and store the given ones."""
        ...
