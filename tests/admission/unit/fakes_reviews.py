"""In-memory fakes for essay reviews: the review repository and an exemplar source."""

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from app.modules.admission.domain.essay_reviews import ReviewKind, StoredReview
from app.modules.admission.domain.exemplars import ExemplarMatch


class MemReviews:
    """Stored reviews in a list; the same input replaces the older row."""

    def __init__(self) -> None:
        self.rows: list[StoredReview] = []

    async def latest(
        self, essay_id: UUID, kind: ReviewKind, institution_id: UUID | None
    ) -> StoredReview | None:
        found = [
            r
            for r in self.rows
            if (r.essay_id, r.kind, r.institution_id)
            == (essay_id, kind, institution_id)
        ]
        return max(found, key=lambda r: r.created_at) if found else None

    async def find(
        self,
        essay_id: UUID,
        kind: ReviewKind,
        institution_id: UUID | None,
        input_digest: str,
    ) -> StoredReview | None:
        key = (essay_id, kind, institution_id, input_digest)
        for r in self.rows:
            if (r.essay_id, r.kind, r.institution_id, r.input_digest) == key:
                return r
        return None

    async def save(self, review: StoredReview) -> None:
        old = await self.find(
            review.essay_id, review.kind, review.institution_id, review.input_digest
        )
        if old is not None:
            self.rows.remove(old)
            review = replace(review, id=old.id)
        self.rows.append(review)

    async def list_for_essay(self, essay_id: UUID) -> list[StoredReview]:
        rows = [r for r in self.rows if r.essay_id == essay_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)


class FixedExemplars:
    """Returns the given matches for every query and records the calls."""

    def __init__(self, matches: Sequence[ExemplarMatch] = ()) -> None:
        self.matches = list(matches)
        self.calls = 0

    async def closest(
        self,
        *,
        kind: str,
        prompt: str,
        body: str,
        institution_id: UUID | None,
        k: int = 3,
    ) -> tuple[ExemplarMatch, ...]:
        self.calls += 1
        return tuple(self.matches[:k])
