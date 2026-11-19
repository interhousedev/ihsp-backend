"""Port: stored essay reviews (coach checks, base and university reviews)."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.essay_reviews import ReviewKind, StoredReview


class EssayReviewRepository(Protocol):
    """Port: sealed review results keyed by essay, kind, university and input."""

    async def latest(
        self, essay_id: UUID, kind: ReviewKind, institution_id: UUID | None
    ) -> StoredReview | None:
        """The newest stored review of the kind, or None."""
        ...

    async def find(
        self,
        essay_id: UUID,
        kind: ReviewKind,
        institution_id: UUID | None,
        input_digest: str,
    ) -> StoredReview | None:
        """The stored review for exactly this input, or None."""
        ...

    async def save(self, review: StoredReview) -> None:
        """Store a review; an existing one for the same input is replaced."""
        ...

    async def list_for_essay(self, essay_id: UUID) -> list[StoredReview]:
        """Every stored review of the essay, newest first."""
        ...
