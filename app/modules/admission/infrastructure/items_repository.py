"""SQL repository of items, metrics, interview rounds and item reviews."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.items import Item, ItemKind
from app.modules.admission.infrastructure.orm.profile import (
    ItemInterviewRow,
    ItemMetricRow,
    ItemRow,
    ProfileWordsRow,
    ReviewFeedbackRow,
    ReviewRow,
)
from app.modules.admission.ports.items import (
    FeedbackKind,
    Horizon,
    InterviewRound,
    Metric,
    ProfileWordsRef,
    Provenance,
    ReviewStatus,
    SafetyFlag,
    StoredReview,
)
from app.shared.ids import new_id

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _item(row: ItemRow) -> Item:
    return Item(
        id=row.id,
        student_id=row.student_id,
        kind=cast(ItemKind, row.kind),
        title=row.position,
        organization=row.org,
        description=row.description,
        category=row.category,
        grades=tuple(row.grade_levels or ()),
        hours_per_week=row.hours_week,
        weeks_per_year=row.weeks_year,
        position=row.sort_order,
        created_at=row.created_at,
        lock_version=row.lock_version,
    )


def _metric(row: ItemMetricRow) -> Metric:
    return Metric(
        id=row.id,
        item_id=row.item_id,
        label=row.label,
        value=row.value,
        unit=row.unit,
        horizon=cast(Horizon, row.horizon),
        as_of=row.as_of,
        target_date=row.target_date,
        provenance=cast(Provenance, row.provenance),
    )


def _round(row: ItemInterviewRow) -> InterviewRound:
    return InterviewRound(
        id=row.id,
        item_id=row.item_id,
        round=row.round,
        questions=dict(row.questions or {}),
        answers=dict(row.answers or {}),
        created_at=row.created_at,
    )


def _review(row: ReviewRow) -> StoredReview:
    return StoredReview(
        id=row.id,
        student_id=row.student_id,
        target_kind=row.target_kind,
        target_id=row.target_id,
        input_hash=row.input_hash,
        task=row.task,
        model=row.model,
        prompt_version=row.prompt_version,
        rubric_version=row.rubric_version,
        schema_version=row.schema_version,
        words_version=row.words_version,
        grades=dict(row.grades or {}),
        overall=row.overall,
        payload=dict(row.payload or {}),
        safety_flag=cast(SafetyFlag, row.safety_flag),
        status=cast(ReviewStatus, row.status),
        created_at=row.created_at,
    )


class SqlItemRepository:
    """Stored items and everything hanging off them."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def list_for(self, student_id: UUID) -> list[Item]:
        """Return the student's items in display order."""
        rows = await self._s.scalars(
            select(ItemRow)
            .where(ItemRow.student_id == student_id)
            .order_by(ItemRow.kind, ItemRow.sort_order, ItemRow.created_at)
        )
        return [_item(r) for r in rows]

    async def get(self, item_id: UUID) -> Item | None:
        """Return one item."""
        row = await self._s.get(ItemRow, item_id)
        return _item(row) if row else None

    async def add(self, item: Item) -> Item:
        """Insert an item."""
        row = ItemRow(
            id=item.id or new_id(),
            student_id=item.student_id,
            kind=item.kind,
            position=item.title,
            org=item.organization,
            description=item.description,
            category=item.category,
            grade_levels=list(item.grades),
            hours_week=item.hours_per_week,
            weeks_year=item.weeks_per_year,
            sort_order=item.position,
            lock_version=0,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _item(row)

    async def update(self, item: Item) -> Item:
        """Store the fields and bump the lock version (compare-and-set)."""
        row = await self._s.get(ItemRow, item.id)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != item.lock_version:
            raise AdmissionConflictError()
        row.position = item.title
        row.org = item.organization
        row.description = item.description
        row.category = item.category
        row.grade_levels = list(item.grades)
        row.hours_week = item.hours_per_week
        row.weeks_year = item.weeks_per_year
        row.lock_version = item.lock_version + 1
        await self._s.flush()
        await self._s.refresh(row)
        return _item(row)

    async def delete(self, item_id: UUID) -> None:
        """Delete the item; metrics, interviews and proofs cascade."""
        await self._s.execute(
            delete(ReviewRow).where(
                ReviewRow.target_kind == "item", ReviewRow.target_id == item_id
            )
        )
        await self._s.execute(delete(ItemRow).where(ItemRow.id == item_id))

    async def set_order(self, ordered: Sequence[UUID]) -> None:
        """Set the sort order of the given items to their list position."""
        for index, item_id in enumerate(ordered):
            await self._s.execute(
                update(ItemRow).where(ItemRow.id == item_id).values(sort_order=index)
            )

    async def metrics_for(self, item_ids: Sequence[UUID]) -> dict[UUID, list[Metric]]:
        """Return the metrics of the items."""
        out: dict[UUID, list[Metric]] = {i: [] for i in item_ids}
        if not item_ids:
            return out
        rows = await self._s.scalars(
            select(ItemMetricRow)
            .where(ItemMetricRow.item_id.in_(list(item_ids)))
            .order_by(ItemMetricRow.id)
        )
        for r in rows:
            out[r.item_id].append(_metric(r))
        return out

    async def replace_metrics(self, item_id: UUID, metrics: Sequence[Metric]) -> None:
        """Replace the metrics of an item."""
        await self._s.execute(
            delete(ItemMetricRow).where(ItemMetricRow.item_id == item_id)
        )
        for m in metrics:
            self._s.add(
                ItemMetricRow(
                    id=m.id,
                    item_id=item_id,
                    label=m.label,
                    value=m.value,
                    unit=m.unit,
                    horizon=m.horizon,
                    as_of=m.as_of,
                    target_date=m.target_date,
                    provenance=m.provenance,
                )
            )
        await self._s.flush()

    async def interviews(self, item_id: UUID) -> list[InterviewRound]:
        """Return the interview rounds of an item, oldest first."""
        rows = await self._s.scalars(
            select(ItemInterviewRow)
            .where(ItemInterviewRow.item_id == item_id)
            .order_by(ItemInterviewRow.round)
        )
        return [_round(r) for r in rows]

    async def add_interview(self, round_: InterviewRound) -> InterviewRound:
        """Insert an interview round."""
        row = ItemInterviewRow(
            id=round_.id,
            item_id=round_.item_id,
            round=round_.round,
            questions=round_.questions,
            answers=round_.answers,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _round(row)

    async def update_round(
        self,
        round_id: UUID,
        *,
        questions: dict[str, Any] | None = None,
        answers: dict[str, Any] | None = None,
    ) -> None:
        """Update the questions and/or answers of a round."""
        values: dict[str, Any] = {}
        if questions is not None:
            values["questions"] = questions
        if answers is not None:
            values["answers"] = answers
        if values:
            await self._s.execute(
                update(ItemInterviewRow)
                .where(ItemInterviewRow.id == round_id)
                .values(**values)
            )

    async def clear_interviews(self, item_id: UUID) -> None:
        """Delete the interview rounds of an item."""
        await self._s.execute(
            delete(ItemInterviewRow).where(ItemInterviewRow.item_id == item_id)
        )

    async def words(self, student_id: UUID) -> ProfileWordsRef | None:
        """Return the student's words, or None if none are set."""
        row = await self._s.get(ProfileWordsRow, student_id)
        if row is None or not row.words:
            return None
        return ProfileWordsRef(words=tuple(row.words), version=row.version)

    async def find_review(
        self, target_kind: str, target_id: UUID, input_hash: str
    ) -> StoredReview | None:
        """Return the review stored for the same input."""
        row = await self._s.scalar(
            select(ReviewRow).where(
                ReviewRow.target_kind == target_kind,
                ReviewRow.target_id == target_id,
                ReviewRow.input_hash == input_hash,
            )
        )
        return _review(row) if row else None

    async def latest_review(
        self, target_kind: str, target_id: UUID
    ) -> StoredReview | None:
        """Return the newest ready review of a target."""
        row = await self._s.scalar(
            select(ReviewRow)
            .where(
                ReviewRow.target_kind == target_kind,
                ReviewRow.target_id == target_id,
                ReviewRow.status == "ready",
            )
            .order_by(ReviewRow.created_at.desc(), ReviewRow.id.desc())
            .limit(1)
        )
        return _review(row) if row else None

    async def get_review(self, review_id: UUID) -> StoredReview | None:
        """Return one review."""
        row = await self._s.get(ReviewRow, review_id)
        return _review(row) if row else None

    async def add_review(self, review: StoredReview) -> StoredReview:
        """Insert a review."""
        row = ReviewRow(
            id=review.id,
            student_id=review.student_id,
            target_kind=review.target_kind,
            target_id=review.target_id,
            input_hash=review.input_hash,
            task=review.task,
            model=review.model,
            prompt_version=review.prompt_version,
            rubric_version=review.rubric_version,
            schema_version=review.schema_version,
            words_version=review.words_version,
            grades=review.grades,
            overall=review.overall,
            payload=review.payload,
            safety_flag=review.safety_flag,
            status=review.status,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _review(row)

    async def count_reviews(
        self, student_id: UUID, task: str, since: datetime, *, target_id: UUID | None
    ) -> int:
        """Count reviews of a task since a time, optionally of one target."""
        query = select(func.count(ReviewRow.id)).where(
            ReviewRow.student_id == student_id,
            ReviewRow.task == task,
            ReviewRow.created_at >= since,
        )
        if target_id is not None:
            query = query.where(ReviewRow.target_id == target_id)
        return int(await self._s.scalar(query) or 0)

    async def add_feedback(
        self, review_id: UUID, student_id: UUID, kind: FeedbackKind, note: str | None
    ) -> None:
        """Store the student's feedback on a review."""
        self._s.add(
            ReviewFeedbackRow(
                id=new_id(),
                review_id=review_id,
                student_id=student_id,
                kind=kind,
                note=note,
            )
        )
        await self._s.flush()
