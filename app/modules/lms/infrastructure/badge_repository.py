"""SQLAlchemy repository of course badges, awards and the learner facts."""

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.lms.domain.badges import (
    BadgeDesign,
    BadgeIcon,
    BadgeRule,
    BadgeShape,
    LearnerFacts,
    dump_rule,
    parse_rule,
)
from app.modules.lms.infrastructure.orm.badge import Badge, BadgeAward, BadgeSettings
from app.modules.lms.infrastructure.orm.engagement import XpEvent
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.infrastructure.orm.step_state import StepState
from app.modules.lms.infrastructure.orm.test_attempt import TestAttempt
from app.modules.lms.ports.badge_repository import StoredAward, StoredBadge
from app.shared.ids import new_id

from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _stored(row: Badge) -> StoredBadge:
    return StoredBadge(
        id=row.id,
        course_id=row.course_id,
        design=BadgeDesign(
            name=dict(row.name),
            description=dict(row.description or {}),
            icon=BadgeIcon(row.icon),
            color=row.color,
            shape=BadgeShape(row.shape),
            image_file_id=row.image_file_id,
        ),
        rule=parse_rule(row.rule),
        enabled=row.enabled,
        position=row.position,
        created_at=row.created_at,
    )


def _design_values(design: BadgeDesign) -> dict[str, Any]:
    return {
        "name": design.name,
        "description": design.description,
        "icon": design.icon.value,
        "color": design.color,
        "shape": design.shape.value,
        "image_file_id": design.image_file_id,
    }


def _award(row: BadgeAward) -> StoredAward:
    return StoredAward(
        id=row.id,
        badge_id=row.badge_id,
        user_id=row.user_id,
        course_id=row.course_id,
        awarded_at=row.awarded_at,
        seen_at=row.seen_at,
    )


def _pct(score: Decimal | None, top: Decimal) -> float | None:
    if score is None:
        return None
    return 100.0 if top <= 0 else float(score * 100 / top)


class SqlBadgeRepository:
    """Badge reads and writes inside the learning transaction."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    # - - - badges - - -

    async def for_course(self, course_id: UUID) -> list[StoredBadge]:
        """Return the badges of a course in display order."""
        return await self.for_courses([course_id])

    async def for_courses(self, course_ids: Sequence[UUID]) -> list[StoredBadge]:
        """Return the badges of several courses in display order."""
        if not course_ids:
            return []
        rows = await self.session.scalars(
            select(Badge)
            .where(Badge.course_id.in_(course_ids))
            .order_by(Badge.position, Badge.created_at, Badge.id)
        )
        return [_stored(r) for r in rows]

    async def get(self, badge_id: UUID) -> StoredBadge | None:
        """Return one badge."""
        row = await self.session.get(Badge, badge_id)
        return _stored(row) if row else None

    async def count(self, course_id: UUID) -> int:
        """Return how many badges a course has."""
        total = await self.session.scalar(
            select(func.count()).where(Badge.course_id == course_id)
        )
        return int(total or 0)

    async def add(
        self,
        course_id: UUID,
        design: BadgeDesign,
        rule: BadgeRule,
        enabled: bool,
        created_by: UUID,
    ) -> UUID:
        """Store a new badge at the end of the list."""
        badge_id = new_id()
        position = await self.session.scalar(
            select(func.coalesce(func.max(Badge.position) + 1, 0)).where(
                Badge.course_id == course_id
            )
        )
        self.session.add(
            Badge(
                id=badge_id,
                course_id=course_id,
                rule=dump_rule(rule),
                enabled=enabled,
                position=int(position or 0),
                created_by=created_by,
                **_design_values(design),
            )
        )
        await self.session.flush()
        return badge_id

    async def update(
        self, badge_id: UUID, design: BadgeDesign, rule: BadgeRule, enabled: bool
    ) -> None:
        """Replace the design, rule and switch of a badge."""
        await self.session.execute(
            update(Badge)
            .where(Badge.id == badge_id)
            .values(rule=dump_rule(rule), enabled=enabled, **_design_values(design))
        )

    async def delete(self, badge_id: UUID) -> None:
        """Remove a badge and its awards (cascade)."""
        await self.session.execute(delete(Badge).where(Badge.id == badge_id))

    async def show_locked(self, course_id: UUID) -> bool:
        """Return whether learners see badges they have not earned (default on)."""
        row = await self.session.get(BadgeSettings, course_id)
        return True if row is None else row.show_locked

    async def set_show_locked(self, course_id: UUID, value: bool) -> None:
        """Store whether learners see badges they have not earned."""
        stmt = insert(BadgeSettings).values(course_id=course_id, show_locked=value)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[BadgeSettings.course_id],
                set_={"show_locked": value, "updated_at": func.now()},
            )
        )

    # - - - awards - - -

    async def award_counts(self, course_id: UUID) -> dict[UUID, int]:
        """Return how many learners earned each badge of a course."""
        rows = await self.session.execute(
            select(BadgeAward.badge_id, func.count())
            .where(BadgeAward.course_id == course_id)
            .group_by(BadgeAward.badge_id)
        )
        return {b: int(n) for b, n in rows}

    async def awards_of(self, user_id: UUID) -> list[StoredAward]:
        """Return every badge a learner earned, newest first."""
        rows = await self.session.scalars(
            select(BadgeAward)
            .where(BadgeAward.user_id == user_id)
            .order_by(BadgeAward.awarded_at.desc(), BadgeAward.id)
        )
        return [_award(r) for r in rows]

    async def get_award(self, award_id: UUID) -> StoredAward | None:
        """Return one award."""
        row = await self.session.get(BadgeAward, award_id)
        return _award(row) if row else None

    async def award(
        self, badge_id: UUID, user_id: UUID, course_id: UUID, at: datetime
    ) -> bool:
        """Store an award once; return False when it already existed."""
        result = await self.session.execute(
            insert(BadgeAward)
            .values(
                id=new_id(),
                badge_id=badge_id,
                user_id=user_id,
                course_id=course_id,
                awarded_at=at,
            )
            .on_conflict_do_nothing(constraint="uq_badge_awards_badge_user")
            .returning(BadgeAward.id)
        )
        return result.scalar() is not None

    async def mark_seen(self, award_id: UUID, now: datetime) -> None:
        """Record that the learner saw the celebration of an award (first time)."""
        await self.session.execute(
            update(BadgeAward)
            .where(BadgeAward.id == award_id, BadgeAward.seen_at.is_(None))
            .values(seen_at=now)
        )

    # - - - facts - - -

    async def facts(
        self,
        user_id: UUID,
        course_id: UUID,
        sections: Sequence[tuple[str, Sequence[UUID]]],
        completed_at: datetime | None,
        today: date,
    ) -> LearnerFacts | None:
        """Return the learner facts of an enrolled learner, else None."""
        enrolled_at = await self.session.scalar(
            select(Enrollment.created_at).where(
                Enrollment.course_id == course_id, Enrollment.user_id == user_id
            )
        )
        if enrolled_at is None:
            return None
        step_ids = [s for _, ids in sections for s in ids]
        states = list(
            await self.session.scalars(
                select(StepState).where(
                    StepState.user_id == user_id, StepState.step_id.in_(step_ids)
                )
            )
        )
        scores, passed = await self._attempts(user_id, step_ids)
        return LearnerFacts(
            enrolled_at=enrolled_at,
            course_completed_at=completed_at,
            sections=sections,
            completed_steps={
                s.step_id: s.completed_at for s in states if s.completed_at
            },
            step_scores=scores,
            passed_tests=passed,
            exam_scores=_exam_scores(states),
            active_days=await self._active_days(user_id),
            today=today,
            reviews_per_day=await self._reviews(user_id, course_id),
        )

    async def _attempts(
        self, user_id: UUID, step_ids: Sequence[UUID]
    ) -> tuple[dict[UUID, float], list[tuple[UUID, datetime, float]]]:
        rows = await self.session.scalars(
            select(TestAttempt).where(
                TestAttempt.user_id == user_id,
                TestAttempt.step_id.in_(step_ids),
                TestAttempt.is_preview.is_(False),
                TestAttempt.submitted_at.is_not(None),
            )
        )
        best: dict[UUID, float] = {}
        passed: list[tuple[UUID, datetime, float]] = []
        for row in rows:
            raw = row.override_score if row.override_score is not None else row.score
            pct = _pct(None if raw is None else Decimal(raw), Decimal(row.max_score))
            if pct is None or row.submitted_at is None:
                continue
            best[row.step_id] = max(pct, best.get(row.step_id, pct))
            if row.passed:
                passed.append((row.step_id, row.submitted_at, pct))
        return best, passed

    async def _active_days(self, user_id: UUID) -> list[date]:
        rows = await self.session.scalars(
            select(distinct(XpEvent.earned_on)).where(XpEvent.user_id == user_id)
        )
        return list(rows)

    async def _reviews(self, user_id: UUID, course_id: UUID) -> dict[date, int]:
        rows = await self.session.execute(
            select(XpEvent.earned_on, func.count())
            .where(
                XpEvent.user_id == user_id,
                XpEvent.course_id == course_id,
                XpEvent.source == "review",
            )
            .group_by(XpEvent.earned_on)
        )
        return {d: int(n) for d, n in rows}


def _exam_scores(states: Sequence[StepState]) -> list[tuple[UUID, datetime, float]]:
    """Return the finished exam results kept in the step state cards."""
    out: list[tuple[UUID, datetime, float]] = []
    for state in states:
        for card in (state.cards or {}).values():
            if isinstance(card, dict) and card.get("kind") == "exam":
                pct = card.get("pct")
                if isinstance(pct, int | float):
                    out.append((state.step_id, state.updated_at, float(pct)))
    return out
