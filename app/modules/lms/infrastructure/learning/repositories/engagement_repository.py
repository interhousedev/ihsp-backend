"""SQLAlchemy repository of the engagement tables (XP, review, quests)."""

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.lms.domain.engagement.fsrs import FsrsState
from app.modules.lms.infrastructure.orm.course_step import CourseStep
from app.modules.lms.infrastructure.orm.engagement import (
    ClassQuest,
    CourseEngagementSettings,
    EngagementProfile,
    ReviewItem,
    XpEvent,
)
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.infrastructure.orm.step_state import StepState
from app.modules.lms.infrastructure.orm.test_attempt import TestAttempt
from app.modules.lms.ports.learning.engagement import (
    QuestRecord,
    StoredReviewItem,
    SubmittedAttempt,
    XpRecord,
)
from app.shared.ids import new_id

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _item(row: ReviewItem) -> StoredReviewItem:
    return StoredReviewItem(
        id=row.id,
        user_id=row.user_id,
        course_id=row.course_id,
        step_id=row.step_id,
        revision_id=row.revision_id,
        block_id=row.block_id,
        question_id=row.question_id,
        state=FsrsState(
            stability=row.stability,
            difficulty=row.difficulty,
            due_at=row.due_at,
            last_review_at=row.last_review_at,
            reps=row.reps,
            lapses=row.lapses,
        ),
    )


def _quest(row: ClassQuest) -> QuestRecord:
    return QuestRecord(
        id=row.id,
        course_id=row.course_id,
        title=row.title,
        goal_kind=row.goal_kind,
        target=row.target,
        class_target=row.class_target,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
    )


class SqlEngagementRepository:
    """Engagement reads and writes inside the learning transaction."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    # - - - profile - - -

    async def profile(self, user_id: UUID) -> tuple[int, datetime | None]:
        """Return the weekly goal (default 5) and the XP sync watermark."""
        row = await self.session.get(EngagementProfile, user_id)
        return (row.weekly_goal_days, row.synced_at) if row else (5, None)

    async def mark_synced(self, user_id: UUID, at: datetime) -> None:
        """Store the XP sync watermark."""
        stmt = insert(EngagementProfile).values(user_id=user_id, synced_at=at)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[EngagementProfile.user_id], set_={"synced_at": at}
            )
        )

    # - - - sync sources - - -

    async def attempts_since(
        self, user_id: UUID, since: datetime | None
    ) -> list[SubmittedAttempt]:
        """Return the user's submitted non-preview attempts after `since`."""
        query = select(TestAttempt).where(
            TestAttempt.user_id == user_id,
            TestAttempt.is_preview.is_(False),
            TestAttempt.submitted_at.is_not(None),
        )
        if since is not None:
            query = query.where(TestAttempt.submitted_at > since)
        rows = await self.session.scalars(query.order_by(TestAttempt.submitted_at))
        return [
            SubmittedAttempt(
                id=r.id,
                step_id=r.step_id,
                revision_id=r.revision_id,
                block_id=r.block_id,
                variant=dict(r.variant or {}),
                answers=dict(r.answers or {}),
                score=(
                    Decimal(r.override_score)
                    if r.override_score is not None
                    else None if r.score is None else Decimal(r.score)
                ),
                max_score=Decimal(r.max_score),
                submitted_at=r.submitted_at,  # type: ignore[arg-type]
            )
            for r in rows
        ]

    async def completions_since(
        self, user_id: UUID, since: datetime | None
    ) -> list[tuple[UUID, datetime]]:
        """Return (step_id, completed_at) of steps completed after `since`."""
        query = select(StepState.step_id, StepState.completed_at).where(
            StepState.user_id == user_id, StepState.completed_at.is_not(None)
        )
        if since is not None:
            query = query.where(StepState.completed_at > since)
        return [(s, c) for s, c in await self.session.execute(query)]

    async def scores_before(
        self, user_id: UUID, step_id: UUID, block_id: str, before: datetime
    ) -> list[tuple[Decimal | None, Decimal]]:
        """Return (score, max_score) of earlier submitted non-preview attempts."""
        rows = await self.session.execute(
            select(
                func.coalesce(TestAttempt.override_score, TestAttempt.score),
                TestAttempt.max_score,
            ).where(
                TestAttempt.user_id == user_id,
                TestAttempt.step_id == step_id,
                TestAttempt.block_id == block_id,
                TestAttempt.is_preview.is_(False),
                TestAttempt.submitted_at < before,
            )
        )
        return [
            (None if s is None else Decimal(s), Decimal(m)) for s, m in rows.tuples()
        ]

    async def course_of_steps(self, step_ids: Sequence[UUID]) -> dict[UUID, UUID]:
        """Return the course id of each step."""
        if not step_ids:
            return {}
        rows = await self.session.execute(
            select(CourseStep.id, CourseStep.course_id).where(
                CourseStep.id.in_(step_ids)
            )
        )
        return dict(rows.tuples().all())

    # - - - XP ledger - - -

    async def add_xp(
        self,
        user_id: UUID,
        course_id: UUID | None,
        source: str,
        ref: str,
        xp: int,
        earned_on: date,
    ) -> bool:
        """Record an award once per (user, source, ref); True when new."""
        result = await self.session.execute(
            insert(XpEvent)
            .values(
                id=new_id(),
                user_id=user_id,
                course_id=course_id,
                source=source,
                ref=ref,
                xp=xp,
                earned_on=earned_on,
            )
            .on_conflict_do_nothing(constraint="uq_xp_events_user_source_ref")
            .returning(XpEvent.id)
        )
        return result.scalar() is not None

    async def xp_total(self, user_id: UUID) -> int:
        """Return the user's total XP."""
        total = await self.session.scalar(
            select(func.coalesce(func.sum(XpEvent.xp), 0)).where(
                XpEvent.user_id == user_id
            )
        )
        return int(total or 0)

    async def active_days(self, user_id: UUID, since: date) -> list[date]:
        """Return the days with any XP from `since`."""
        rows = await self.session.scalars(
            select(distinct(XpEvent.earned_on)).where(
                XpEvent.user_id == user_id, XpEvent.earned_on >= since
            )
        )
        return list(rows)

    async def recent_xp(self, user_id: UUID, limit: int) -> list[XpRecord]:
        """Return the newest XP awards."""
        rows = await self.session.scalars(
            select(XpEvent)
            .where(XpEvent.user_id == user_id)
            .order_by(XpEvent.created_at.desc(), XpEvent.id.desc())
            .limit(limit)
        )
        return [XpRecord(r.source, r.ref, r.xp, r.created_at) for r in rows]

    async def reviews_on(self, user_id: UUID, day: date) -> int:
        """Return how many review answers earned XP on a day."""
        count = await self.session.scalar(
            select(func.count()).where(
                XpEvent.user_id == user_id,
                XpEvent.source == "review",
                XpEvent.earned_on == day,
            )
        )
        return int(count or 0)

    async def xp_on(self, user_id: UUID, day: date, source: str) -> int:
        """Return the XP of one source earned on a day."""
        total = await self.session.scalar(
            select(func.coalesce(func.sum(XpEvent.xp), 0)).where(
                XpEvent.user_id == user_id,
                XpEvent.source == source,
                XpEvent.earned_on == day,
            )
        )
        return int(total or 0)

    async def course_progress(
        self, course_id: UUID, kind: str, start: date, end: date
    ) -> dict[UUID, int]:
        """Return each enrolled learner's progress on a quest metric."""
        where: tuple[Any, ...] = (
            XpEvent.course_id == course_id,
            XpEvent.earned_on >= start,
            XpEvent.earned_on <= end,
        )
        if kind == "xp":
            measure: Any = func.sum(XpEvent.xp)
        elif kind == "steps":
            measure = func.count()
            where = (*where, XpEvent.source == "step")
        else:
            measure = func.count(distinct(XpEvent.earned_on))
            where = (*where, XpEvent.source == "review")
        rows = await self.session.execute(
            select(XpEvent.user_id, measure)
            .join(
                Enrollment,
                (Enrollment.user_id == XpEvent.user_id)
                & (Enrollment.course_id == course_id),
            )
            .where(*where)
            .group_by(XpEvent.user_id)
        )
        return {u: int(v or 0) for u, v in rows}

    # - - - review items - - -

    async def add_review_item(
        self,
        *,
        user_id: UUID,
        course_id: UUID,
        step_id: UUID,
        revision_id: UUID,
        block_id: str,
        question_id: str,
        state: FsrsState,
    ) -> None:
        """Queue a missed question unless it is already queued."""
        await self.session.execute(
            insert(ReviewItem)
            .values(
                id=new_id(),
                user_id=user_id,
                course_id=course_id,
                step_id=step_id,
                revision_id=revision_id,
                block_id=block_id,
                question_id=question_id,
                stability=state.stability,
                difficulty=state.difficulty,
                due_at=state.due_at,
            )
            .on_conflict_do_nothing(constraint="uq_review_items_user_question")
        )

    async def due_items(
        self, user_id: UUID, now: datetime, limit: int, step_ids: Sequence[UUID]
    ) -> list[StoredReviewItem]:
        """Return the user's due questions in the given steps, oldest due first."""
        if not step_ids:
            return []
        rows = await self.session.scalars(
            select(ReviewItem)
            .where(
                ReviewItem.user_id == user_id,
                ReviewItem.due_at <= now,
                ReviewItem.step_id.in_(step_ids),
            )
            .order_by(ReviewItem.due_at)
            .limit(limit)
        )
        return [_item(r) for r in rows]

    async def due_count(
        self, user_id: UUID, now: datetime, step_ids: Sequence[UUID]
    ) -> int:
        """Return how many questions in the given steps are due."""
        if not step_ids:
            return 0
        count = await self.session.scalar(
            select(func.count()).where(
                ReviewItem.user_id == user_id,
                ReviewItem.due_at <= now,
                ReviewItem.step_id.in_(step_ids),
            )
        )
        return int(count or 0)

    async def due_counts(self, now: datetime) -> dict[UUID, int]:
        """Return the number of due questions per user (for nudges)."""
        rows = await self.session.execute(
            select(ReviewItem.user_id, func.count())
            .where(ReviewItem.due_at <= now)
            .group_by(ReviewItem.user_id)
        )
        return {u: int(n) for u, n in rows}

    async def get_item(self, item_id: UUID) -> StoredReviewItem | None:
        """Return a review item."""
        row = await self.session.get(ReviewItem, item_id, populate_existing=True)
        return _item(row) if row else None

    async def save_item(self, item_id: UUID, state: FsrsState) -> None:
        """Store the new FSRS state."""
        row = await self.session.get(ReviewItem, item_id)
        if row is None:
            return
        row.stability = state.stability
        row.difficulty = state.difficulty
        row.due_at = state.due_at
        row.last_review_at = state.last_review_at
        row.reps = state.reps
        row.lapses = state.lapses

    # - - - settings - - -

    async def unlock_threshold(self, course_id: UUID) -> int | None:
        """Return the mastery unlock threshold of a course."""
        row = await self.session.get(CourseEngagementSettings, course_id)
        return row.unlock_threshold_pct if row else None

    async def set_unlock_threshold(self, course_id: UUID, pct: int | None) -> None:
        """Store the mastery unlock threshold."""
        stmt = insert(CourseEngagementSettings).values(
            course_id=course_id, unlock_threshold_pct=pct
        )
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[CourseEngagementSettings.course_id],
                set_={"unlock_threshold_pct": pct, "updated_at": func.now()},
            )
        )

    # - - - quests - - -

    async def quests_of(
        self, course_ids: Sequence[UUID], active_on: date | None = None
    ) -> list[QuestRecord]:
        """Return the quests of courses, optionally only those running on a day."""
        if not course_ids:
            return []
        query = select(ClassQuest).where(ClassQuest.course_id.in_(course_ids))
        if active_on is not None:
            query = query.where(
                ClassQuest.starts_on <= active_on, ClassQuest.ends_on >= active_on
            )
        rows = await self.session.scalars(
            query.order_by(ClassQuest.ends_on, ClassQuest.id)
        )
        return [_quest(r) for r in rows]

    async def quests_of_all_active(self, day: date) -> list[QuestRecord]:
        """Return every quest running on a day (for nudges)."""
        rows = await self.session.scalars(
            select(ClassQuest).where(
                ClassQuest.starts_on <= day, ClassQuest.ends_on >= day
            )
        )
        return [_quest(r) for r in rows]

    async def get_quest(self, quest_id: UUID) -> QuestRecord | None:
        """Return a quest."""
        row = await self.session.get(ClassQuest, quest_id, populate_existing=True)
        return _quest(row) if row else None

    async def save_quest(self, quest: QuestRecord, created_by: UUID) -> None:
        """Insert or update a quest."""
        values = {
            "title": quest.title,
            "goal_kind": quest.goal_kind,
            "target": quest.target,
            "class_target": quest.class_target,
            "starts_on": quest.starts_on,
            "ends_on": quest.ends_on,
        }
        stmt = insert(ClassQuest).values(
            id=quest.id, course_id=quest.course_id, created_by=created_by, **values
        )
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[ClassQuest.id],
                set_={**values, "updated_at": func.now()},
            )
        )

    async def delete_quest(self, quest_id: UUID) -> None:
        """Delete a quest."""
        await self.session.execute(delete(ClassQuest).where(ClassQuest.id == quest_id))

    async def learners_with_recent_xp(self, since: date) -> list[UUID]:
        """Return the users with any XP since a day (nudge candidates)."""
        rows = await self.session.scalars(
            select(distinct(XpEvent.user_id)).where(XpEvent.earned_on >= since)
        )
        return list(rows)
