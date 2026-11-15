"""SQLAlchemy repository of lms.access_rules."""

from collections.abc import Iterable
from uuid import UUID

from app.modules.lms.domain.access_rules import AccessRule, Audience, WhenDenied
from app.modules.lms.infrastructure.orm.access_rule import AccessRule as AccessRuleRow
from app.modules.lms.infrastructure.orm.course import Course
from app.modules.lms.infrastructure.orm.course_staff import CourseStaff

from sqlalchemy import delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _to_rule(row: AccessRuleRow) -> AccessRule:
    """Map the ORM row to the domain rule."""
    return AccessRule(
        audience=Audience(row.audience),
        when_denied=WhenDenied(row.when_denied),
        group_ids=tuple(UUID(str(value)) for value in row.group_ids),
        user_ids=tuple(UUID(str(value)) for value in row.user_ids),
    )


class SqlAccessRuleRepository:
    """Audience rules of the lms schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def for_course(self, course_id: UUID) -> dict[UUID, AccessRule]:
        """Return the course rule (under the course id) and every step rule."""
        rows = await self.session.scalars(
            select(AccessRuleRow).where(AccessRuleRow.course_id == course_id)
        )
        return {row.target_id: _to_rule(row) for row in rows}

    async def for_courses(
        self, course_ids: Iterable[UUID]
    ) -> dict[UUID, dict[UUID, AccessRule]]:
        """Return the course and step rules of each given course that has any."""
        ids = list(course_ids)
        if not ids:
            return {}
        rows = await self.session.scalars(
            select(AccessRuleRow).where(AccessRuleRow.course_id.in_(ids))
        )
        result: dict[UUID, dict[UUID, AccessRule]] = {}
        for row in rows:
            result.setdefault(row.course_id, {})[row.target_id] = _to_rule(row)
        return result

    async def delete_targets(self, course_id: UUID, target_ids: Iterable[UUID]) -> None:
        """Remove the rules of the given steps (or the course) of a course."""
        ids = list(target_ids)
        if ids:
            await self.session.execute(
                delete(AccessRuleRow).where(
                    AccessRuleRow.course_id == course_id,
                    AccessRuleRow.target_id.in_(ids),
                )
            )

    async def save(
        self, course_id: UUID, target_id: UUID, rule: AccessRule, updated_by: UUID
    ) -> None:
        """Store the rule; the public default removes the row."""
        if rule.is_open_to_all:
            await self.delete_targets(course_id, [target_id])
            return
        values = {
            "audience": rule.audience.value,
            "when_denied": rule.when_denied.value,
            "group_ids": [str(value) for value in rule.group_ids],
            "user_ids": [str(value) for value in rule.user_ids],
            "updated_by": updated_by,
        }
        statement = insert(AccessRuleRow).values(
            target_id=target_id, course_id=course_id, **values
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[AccessRuleRow.target_id],
                set_={**values, "updated_at": func.now()},
                where=AccessRuleRow.course_id == course_id,
            )
        )

    async def lead(self, course_id: UUID) -> UUID | None:
        """Return the course lead: the first staff manager, else the founder."""
        manager = await self.session.scalar(
            select(CourseStaff.user_id)
            .where(
                CourseStaff.course_id == course_id,
                literal("manage_staff") == CourseStaff.permissions.any_(),
            )
            .order_by(CourseStaff.position, CourseStaff.created_at)
            .limit(1)
        )
        if manager is not None:
            return manager
        founder: UUID | None = await self.session.scalar(
            select(Course.created_by).where(Course.id == course_id)
        )
        return founder
