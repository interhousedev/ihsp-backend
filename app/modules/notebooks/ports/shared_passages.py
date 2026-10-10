"""Port: ranked passages of the shared documents, before the access check."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.shared.contracts.embeddings import QueryVector


@dataclass(frozen=True, slots=True)
class SharedCandidate:
    """A passage as one source holds it; `owner_id` owns that source's notebook."""

    passage_id: UUID
    source_id: UUID
    notebook_id: UUID
    owner_id: UUID
    kind: str
    ref: dict[str, Any]
    source_title: str
    text: str


class SharedPassageReader(Protocol):
    """Hybrid (words and meaning) ranking over passages of possibly shared texts."""

    async def search(
        self, user_id: UUID, query: str, query_vector: QueryVector | None, limit: int
    ) -> list[SharedCandidate]:
        """Candidates best first (RRF of text and cosine rankings).

        Only a pre-filter: sources of the user's own notebooks, and library and
        lesson sources of anyone's. Whether the user may read the latter is decided
        by the caller (`SharedPassageSearch`), never here.
        """
        ...
