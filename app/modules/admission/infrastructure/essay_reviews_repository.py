"""SQL adapter of `EssayReviewRepository`; the result JSON is sealed per student."""

import json
from typing import cast
from uuid import UUID

from app.modules.admission.domain.essay_reviews import ReviewKind, StoredReview
from app.modules.admission.infrastructure.essay_unreadable import (
    readable,
    readable_one,
)
from app.modules.admission.infrastructure.orm.essay_reviews import EssayReviewRow
from app.modules.admission.infrastructure.orm.sealed import to_json
from app.modules.admission.ports.essay_crypto import EssayCipher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select


def _where(
    essay_id: UUID, kind: ReviewKind, institution_id: UUID | None
) -> Select[tuple[EssayReviewRow]]:
    q = select(EssayReviewRow).where(
        EssayReviewRow.essay_id == essay_id, EssayReviewRow.kind == kind
    )
    if institution_id is None:
        return q.where(EssayReviewRow.institution_id.is_(None))
    return q.where(EssayReviewRow.institution_id == institution_id)


class SqlEssayReviewRepository:
    """Stored reviews in `admission.essay_reviews`."""

    def __init__(self, session: AsyncSession, cipher: EssayCipher) -> None:
        """Keep the session and the cipher that seals `result`."""
        self._s = session
        self._cipher = cipher

    async def _view(self, row: EssayReviewRow) -> StoredReview:
        text = await self._cipher.open(row.student_id, row.id, "result", row.result)
        return StoredReview(
            id=row.id,
            essay_id=row.essay_id,
            student_id=row.student_id,
            kind=cast(ReviewKind, row.kind),
            institution_id=row.institution_id,
            input_digest=row.input_digest,
            payload=json.loads(text),
            model=row.model,
            prompt_ref=row.prompt_ref,
            created_at=row.created_at,
        )

    async def latest(
        self, essay_id: UUID, kind: ReviewKind, institution_id: UUID | None
    ) -> StoredReview | None:
        """The newest stored review of the kind, or None."""
        q = _where(essay_id, kind, institution_id)
        q = q.order_by(EssayReviewRow.created_at.desc(), EssayReviewRow.id.desc())
        row = (await self._s.scalars(q.limit(1))).first()
        return await readable_one(row, self._view, "essay_review")

    async def find(
        self,
        essay_id: UUID,
        kind: ReviewKind,
        institution_id: UUID | None,
        input_digest: str,
    ) -> StoredReview | None:
        """The stored review for exactly this input, or None."""
        q = _where(essay_id, kind, institution_id).where(
            EssayReviewRow.input_digest == input_digest
        )
        row = (await self._s.scalars(q)).first()
        return await readable_one(row, self._view, "essay_review")

    async def save(self, review: StoredReview) -> None:
        """Store a review; an existing one for the same input is resealed in place."""
        q = _where(review.essay_id, review.kind, review.institution_id).where(
            EssayReviewRow.input_digest == review.input_digest
        )
        row = (await self._s.scalars(q)).first()
        if row is None:
            row = EssayReviewRow(
                id=review.id,
                essay_id=review.essay_id,
                student_id=review.student_id,
                kind=review.kind,
                institution_id=review.institution_id,
                input_digest=review.input_digest,
            )
            self._s.add(row)
        row.result = await self._cipher.seal(
            row.student_id, row.id, "result", to_json(review.payload)
        )
        row.model = review.model
        row.prompt_ref = review.prompt_ref
        row.created_at = review.created_at
        await self._s.flush()

    async def list_for_essay(self, essay_id: UUID) -> list[StoredReview]:
        """Every stored review of the essay, newest first."""
        q = (
            select(EssayReviewRow)
            .where(EssayReviewRow.essay_id == essay_id)
            .order_by(EssayReviewRow.created_at.desc(), EssayReviewRow.id.desc())
        )
        return await readable(await self._s.scalars(q), self._view, "essay_review")
