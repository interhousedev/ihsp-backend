"""SQL adapters of the badge authoring and backfill ports."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.badge_model import Badge as BadgeModel
from app.modules.lms.domain.badge_model import BadgeScope
from app.modules.lms.domain.badges import BadgeIcon, BadgeShape, LearnerFacts
from app.modules.lms.infrastructure.orm.badge import Badge as BadgeRow
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.infrastructure.orm.level import LevelMark
from app.modules.lms.infrastructure.orm.tutor import TutorSession
from app.shared.clock import to_local
from app.shared.notifications import AuditDraft
from app.shared.tasks import TaskKicker

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TASK_NAME = "lms.backfill_badge"


def _model(r: BadgeRow) -> BadgeModel:
    return BadgeModel(
        id=r.id,
        scope=BadgeScope(r.scope),
        course_id=r.course_id,
        name=dict(r.name),
        description=dict(r.description or {}),
        image=r.image_file_id,
        rule=dict(r.rule),
        template_code=r.template_code,
        template_params=r.template_params,
        enabled=r.enabled,
        version=r.version,
        icon=BadgeIcon(r.icon),
        color=r.color,
        shape=BadgeShape(r.shape),
        updated_at=r.updated_at,
    )


def _fill(r: BadgeRow, b: BadgeModel) -> None:
    r.scope, r.course_id = b.scope.value, b.course_id
    r.name, r.description, r.image_file_id = b.name, b.description, b.image
    r.rule, r.template_code, r.template_params = (
        b.rule,
        b.template_code,
        b.template_params,
    )
    r.enabled, r.version = b.enabled, b.version
    r.icon, r.color, r.shape = b.icon.value, b.color, b.shape.value


class SqlBadgeStore:
    """Badge aggregates (course and platform)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the factory."""
        self.sessionmaker = sessionmaker

    async def add(self, badge: BadgeModel) -> None:
        """Store a new badge."""
        row = BadgeRow(id=badge.id)
        _fill(row, badge)
        async with self.sessionmaker() as s, s.begin():
            s.add(row)

    async def get(self, id: UUID) -> BadgeModel | None:
        """Return one badge."""
        async with self.sessionmaker() as s:
            row = await s.get(BadgeRow, id)
            return _model(row) if row else None

    async def update(self, badge: BadgeModel) -> None:
        """Replace a stored badge."""
        async with self.sessionmaker() as s, s.begin():
            row = await s.get(BadgeRow, badge.id)
            if row is not None:
                _fill(row, badge)

    async def count_for_course(self, course_id: UUID) -> int:
        """Return how many badges a course has."""
        async with self.sessionmaker() as s:
            n = await s.scalar(
                select(func.count())
                .select_from(BadgeRow)
                .where(BadgeRow.course_id == course_id)
            )
            return int(n or 0)

    async def list_platform(self) -> list[BadgeModel]:
        """Return the platform badges."""
        async with self.sessionmaker() as s:
            rows = await s.scalars(
                select(BadgeRow)
                .where(BadgeRow.scope == "platform")
                .order_by(BadgeRow.created_at, BadgeRow.id)
            )
            return [_model(r) for r in rows]

    async def delete(self, id: UUID) -> None:
        """Delete a badge (awards go with it)."""
        async with self.sessionmaker() as s, s.begin():
            row = await s.get(BadgeRow, id)
            if row is not None:
                await s.delete(row)


class SqlEnrolmentFacts:
    """Learner facts of a course's enrolments, paged by offset."""

    def __init__(
        self,
        uow_factory: UowFactory,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        """Store the factories."""
        self.uow_factory = uow_factory
        self.sessionmaker = sessionmaker

    async def total(self, course_id: UUID) -> int:
        """Return the exact enrolment count (one aggregate)."""
        async with self.sessionmaker() as s:
            n = await s.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(Enrollment.course_id == course_id)
            )
            return int(n or 0)

    async def page(
        self, course_id: UUID, cursor: int | None, limit: int
    ) -> tuple[list[tuple[UUID, LearnerFacts]], int | None]:
        """Return up to `limit` learners and the next offset."""
        start = cursor or 0
        out: list[tuple[UUID, LearnerFacts]] = []
        async with self.uow_factory() as uow:
            course = await uow.courses.get(course_id)
            version = (
                await uow.versions.get(course.live_version_id)
                if course is not None and course.live_version_id is not None
                else None
            )
            if version is None:
                return [], None
            sections = [
                (s.id, [st.step_id for st in s.steps])
                for s in version.manifest.sections
            ]
            async with self.sessionmaker() as s:
                rows = (
                    await s.execute(
                        select(Enrollment.user_id, Enrollment.completed_at)
                        .where(Enrollment.course_id == course_id)
                        .order_by(Enrollment.id)
                        .offset(start)
                        .limit(limit + 1)
                    )
                ).all()
            today: date = to_local(datetime.now().astimezone()).date()
            for user_id, completed_at in rows[:limit]:
                facts = await uow.badges.facts(
                    user_id, course_id, sections, completed_at, today
                )
                if facts is not None:
                    out.append((user_id, facts))
        return out, (start + limit if len(rows) > limit else None)


@dataclass(frozen=True, slots=True)
class PlatformFacts:
    """What platform badges read about one learner."""

    level: int
    coach_resolved: int
    courses_completed: int


class SqlPlatformFacts:
    """Platform facts of every learner with an enrolment."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the factory."""
        self.sessionmaker = sessionmaker

    async def page(
        self, cursor: int | None, limit: int
    ) -> tuple[list[tuple[UUID, Any]], int | None]:
        """Return (user, facts) rows and the next offset."""
        start = cursor or 0
        async with self.sessionmaker() as s:
            users = list(
                await s.scalars(
                    select(Enrollment.user_id)
                    .distinct()
                    .order_by(Enrollment.user_id)
                    .offset(start)
                    .limit(limit + 1)
                )
            )
            page = users[:limit]
            levels = dict(
                (
                    await s.execute(
                        select(LevelMark.user_id, LevelMark.level).where(
                            LevelMark.course_id.is_(None), LevelMark.user_id.in_(page)
                        )
                    )
                )
                .tuples()
                .all()
            )
            coach = dict(
                (
                    await s.execute(
                        select(TutorSession.user_id, func.count())
                        .where(
                            TutorSession.outcome == "resolved",
                            TutorSession.user_id.in_(page),
                        )
                        .group_by(TutorSession.user_id)
                    )
                )
                .tuples()
                .all()
            )
            done = dict(
                (
                    await s.execute(
                        select(Enrollment.user_id, func.count())
                        .where(
                            Enrollment.completed_at.is_not(None),
                            Enrollment.user_id.in_(page),
                        )
                        .group_by(Enrollment.user_id)
                    )
                )
                .tuples()
                .all()
            )
        rows = [
            (u, PlatformFacts(levels.get(u, 0), coach.get(u, 0), done.get(u, 0)))
            for u in page
        ]
        return rows, (start + limit if len(users) > limit else None)


class SqlAwardStore:
    """Writes the award and its audit event in one transaction."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the factory."""
        self.uow_factory = uow_factory

    async def award(
        self, badge_id: UUID, user_id: UUID, at: datetime, event: dict[str, Any]
    ) -> bool:
        """Return False and write nothing when the award exists."""
        async with self.uow_factory() as uow:
            course = event.get("course_id")
            made = await uow.badges.award(
                badge_id, user_id, UUID(course) if course else None, at
            )
            if not made:
                return False
            uow.audit(
                AuditDraft(type="lms.badge_awarded", user_id=user_id, metadata=event)
            )
            await uow.commit()
            return True


class TaskBackfillQueue:
    """Queues `lms.backfill_badge` batches."""

    def __init__(self, kicker: TaskKicker | None) -> None:
        """Store the kicker (None in bare tests: nothing is queued)."""
        self.kicker = kicker

    async def enqueue(self, badge_id: UUID, cursor: int | None = None) -> None:
        """Queue the batch starting at `cursor`."""
        if self.kicker is not None:
            await self.kicker.kick(TASK_NAME, badge_id=str(badge_id), cursor=cursor)
