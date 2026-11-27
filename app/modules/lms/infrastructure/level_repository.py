"""SQLAlchemy stores of level schemes, high-water marks and XP totals."""

from typing import Any
from uuid import UUID

from app.modules.lms.domain.engagement.levels import (
    DEFAULT_SCHEME,
    Curve,
    LevelScheme,
    LevelTier,
)
from app.modules.lms.infrastructure.orm.engagement import XpEvent
from app.modules.lms.infrastructure.orm.level import LevelMark
from app.modules.lms.infrastructure.orm.level import LevelScheme as SchemeRow

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _curve_json(curve: Curve) -> dict[str, Any]:
    if curve.kind == "quadratic":
        return {"kind": "quadratic", "base": curve.base}
    return {"kind": "table", "steps": list(curve.steps)}


def _curve(data: dict[str, Any]) -> Curve:
    if data["kind"] == "quadratic":
        return Curve.quadratic(int(data["base"]))
    return Curve.table([int(n) for n in data["steps"]])


def _tiers_json(tiers: list[LevelTier]) -> list[dict[str, Any]]:
    return [
        {
            "level_from": t.level_from,
            "title": t.title,
            "icon": t.icon,
            "color": t.color,
            "reward_badge_id": (
                None if t.reward_badge_id is None else str(t.reward_badge_id)
            ),
        }
        for t in tiers
    ]


def _tiers(data: list[dict[str, Any]]) -> list[LevelTier]:
    return [
        LevelTier(
            level_from=int(t["level_from"]),
            title=t["title"],
            icon=t["icon"],
            color=t["color"],
            reward_badge_id=(
                UUID(t["reward_badge_id"]) if t.get("reward_badge_id") else None
            ),
        )
        for t in data
    ]


def _scheme(row: SchemeRow) -> LevelScheme:
    return LevelScheme(
        id=row.id,
        scope="course" if row.scope == "course" else "platform",
        course_id=row.course_id,
        name=row.name,
        curve=_curve(row.curve),
        tiers=_tiers(row.tiers),
        active=row.active,
    )


class SqlLevelSchemes:
    """Level schemes of the lms schema."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind to the session factory."""
        self.sessionmaker = sessionmaker

    async def add(self, scheme: LevelScheme) -> None:
        """Store a new scheme."""
        async with self.sessionmaker() as db:
            db.add(
                SchemeRow(
                    id=scheme.id,
                    scope=scheme.scope,
                    course_id=scheme.course_id,
                    name=scheme.name,
                    curve=_curve_json(scheme.curve),
                    tiers=_tiers_json(scheme.tiers),
                    active=False,
                )
            )
            await db.commit()

    async def get(self, id: UUID) -> LevelScheme | None:
        """Return a scheme."""
        async with self.sessionmaker() as db:
            row = await db.get(SchemeRow, id)
            return None if row is None else _scheme(row)

    async def update(self, scheme: LevelScheme) -> None:
        """Replace the name, curve and tiers of a stored scheme."""
        async with self.sessionmaker() as db:
            await db.execute(
                update(SchemeRow)
                .where(SchemeRow.id == scheme.id)
                .values(
                    name=scheme.name,
                    curve=_curve_json(scheme.curve),
                    tiers=_tiers_json(scheme.tiers),
                )
            )
            await db.commit()

    async def list(self) -> list[LevelScheme]:
        """Return every scheme, newest first."""
        async with self.sessionmaker() as db:
            rows = await db.scalars(
                select(SchemeRow).order_by(SchemeRow.created_at.desc())
            )
            return [_scheme(r) for r in rows]

    async def active_platform(self) -> LevelScheme:
        """Return the active platform scheme or the default."""
        async with self.sessionmaker() as db:
            row = await db.scalar(
                select(SchemeRow).where(
                    SchemeRow.scope == "platform", SchemeRow.active.is_(True)
                )
            )
            return DEFAULT_SCHEME if row is None else _scheme(row)

    async def for_course(self, course_id: UUID) -> LevelScheme | None:
        """Return the active scheme of a course."""
        async with self.sessionmaker() as db:
            row = await db.scalar(
                select(SchemeRow).where(
                    SchemeRow.course_id == course_id, SchemeRow.active.is_(True)
                )
            )
            return None if row is None else _scheme(row)

    async def deactivate_platform(self) -> None:
        """Deactivate the platform schemes."""
        async with self.sessionmaker() as db:
            await db.execute(
                update(SchemeRow)
                .where(SchemeRow.scope == "platform")
                .values(active=False)
            )
            await db.commit()

    async def activate(self, id: UUID) -> None:
        """Activate a scheme; a course scheme replaces the course's live one."""
        async with self.sessionmaker() as db:
            row = await db.get(SchemeRow, id)
            if row is None:
                raise LookupError(str(id))
            if row.course_id is not None:
                await db.execute(
                    update(SchemeRow)
                    .where(SchemeRow.course_id == row.course_id, SchemeRow.id != id)
                    .values(active=False)
                )
            row.active = True
            await db.commit()


class SqlProfileLevels:
    """High-water marks per learner on the platform and in each course."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind to the session factory."""
        self.sessionmaker = sessionmaker

    async def highest_level(self, user_id: UUID, course_id: UUID | None) -> int:
        """Return the mark (1 when none)."""
        async with self.sessionmaker() as db:
            found = await db.scalar(
                select(LevelMark.level).where(
                    LevelMark.user_id == user_id,
                    (
                        LevelMark.course_id.is_(None)
                        if course_id is None
                        else LevelMark.course_id == course_id
                    ),
                )
            )
            return int(found or 1)

    async def set_highest(
        self, user_id: UUID, course_id: UUID | None, level: int
    ) -> None:
        """Raise the mark; it never goes down."""
        async with self.sessionmaker() as db:
            statement = insert(LevelMark).values(
                user_id=user_id, course_id=course_id, level=level
            )
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=(
                        [LevelMark.user_id]
                        if course_id is None
                        else [LevelMark.user_id, LevelMark.course_id]
                    ),
                    index_where=(
                        statement.excluded.course_id.is_(None)
                        if course_id is None
                        else statement.excluded.course_id.is_not(None)
                    ),
                    set_={"level": func.greatest(LevelMark.level, level)},
                )
            )
            await db.commit()


class SqlXpTotals:
    """The total XP of every learner."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Bind to the session factory."""
        self.sessionmaker = sessionmaker

    async def all_totals(self) -> list[int]:
        """Return one total per learner."""
        async with self.sessionmaker() as db:
            rows = await db.scalars(
                select(func.sum(XpEvent.xp)).group_by(XpEvent.user_id)
            )
            return [int(n or 0) for n in rows]

    async def user_total(self, user_id: UUID, course_id: UUID | None) -> int:
        """Return the learner's XP on the platform or in one course."""
        condition = [XpEvent.user_id == user_id]
        if course_id is not None:
            condition.append(XpEvent.course_id == course_id)
        async with self.sessionmaker() as db:
            total = await db.scalar(
                select(func.coalesce(func.sum(XpEvent.xp), 0)).where(*condition)
            )
            return int(total or 0)
