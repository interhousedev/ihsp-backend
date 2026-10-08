"""TeacherViews: a teacher's pages for the admin view."""

import datetime as dt
from uuid import UUID

from app.bootstrap.adapters.composition.actors import admin_actor, teacher_actor
from app.bootstrap.adapters.composition.json_shape import json_object, json_objects
from app.interfaces.http.v1.composition.ports import JsonObject
from app.modules.academic.application.classwork.missing_attendance import (
    MissingAttendance,
)
from app.modules.academic.application.schedule.get_staff_timetable import (
    GetStaffTimetable,
)
from app.modules.academic.application.schedule.list_curated_groups import (
    ListCuratedGroups,
)


class TeacherViewsAdapter:
    """Composition <- academic: timetable, missing attendance, curated groups."""

    def __init__(
        self,
        get_staff_timetable: GetStaffTimetable,
        missing_attendance: MissingAttendance,
        list_curated_groups: ListCuratedGroups,
    ) -> None:
        """Keep the three use cases."""
        self._timetable = get_staff_timetable
        self._missing_attendance = missing_attendance
        self._curated_groups = list_curated_groups

    async def timetable(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        """Return the `LessonItem` list the teacher teaches between two dates."""
        lessons = await self._timetable.execute(teacher_actor(teacher_id), start, end)
        return [json_object(lesson) for lesson in lessons]

    async def missing_attendance(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        """Return the teacher's finished lessons without attendance (`LessonItem`).

        The classwork use case reports all teachers and demands the admin role (its
        caller, the admin profile endpoint, was already authorized): it runs as an
        admin acting on the teacher's behalf, and the teacher's row is picked out.
        """
        rows = await self._missing_attendance.execute(
            admin_actor(teacher_id), start, end
        )
        wanted = str(teacher_id)
        for row in rows:
            if row["teacher"]["id"] == wanted:
                return json_objects(row["lessons"])
        return []

    async def curated_groups(self, teacher_id: UUID) -> list[JsonObject]:
        """Return the `GroupItem` list of the groups the teacher curates."""
        groups = await self._curated_groups.execute(teacher_actor(teacher_id))
        return json_objects(groups)
