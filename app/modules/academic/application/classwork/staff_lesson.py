"""Use case: a lesson page for staff (STF-4, UF-STF-06)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.attendance_sheet import (
    AttendanceSheetBuilder,
)
from app.modules.academic.application.classwork.lesson_items import LessonItemBuilder
from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.application.classwork.resource_items import (
    staff_resource_items,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.classwork.errors import NotLessonTeacherError
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.links import LinksApi


class StaffLesson:
    """The lesson's teacher and Administration see everything.

    A curator of a group in the audience sees the lesson read-only, limited to
    the students of their own groups, so they can open absences they excuse.
    """

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        lesson_items: LessonItemBuilder,
        roster_loader: RosterLoader,
        sheets: AttendanceSheetBuilder,
        schedule: ScheduleQueries,
        links: LinksApi,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.lesson_items = lesson_items
        self.roster_loader = roster_loader
        self.sheets = sheets
        self.schedule = schedule
        self.links = links

    async def execute(self, lesson_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the ``StaffLesson`` JSON."""
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            visible: set[UUID] | None = None
            if not (actor.has(Role.ADMIN) or lesson.is_taught_by(actor.user_id)):
                curated = set(await self.schedule.curated_group_ids(actor.user_id))
                visible = curated & audience_keys.group_ids(lesson.audience)
                if not visible:
                    raise NotLessonTeacherError(params={"lesson_id": str(lesson_id)})
            roster = await self.roster_loader.load(uow, lesson)
        sheet = await self.sheets.build(
            lesson, roster, actor, local_today(self.clock), visible_groups=visible
        )
        refs = await self.links.lesson_resources(lesson_id, include_hidden=True)
        return {
            "lesson": await self.lesson_items.build(lesson, locale),
            "materials": await staff_resource_items(
                [ref for ref in refs if ref.role == "material"], self.people
            ),
            "attachments": await staff_resource_items(
                [ref for ref in refs if ref.role == "attachment"], self.people
            ),
            "homework": (
                {
                    "text": lesson.homework_text,
                    "due_date": (
                        lesson.homework_due_date.isoformat()
                        if lesson.homework_due_date
                        else None
                    ),
                    "due_auto": lesson.homework_due_auto,
                }
                if lesson.has_homework
                else None
            ),
            "attendance": sheet,
        }
