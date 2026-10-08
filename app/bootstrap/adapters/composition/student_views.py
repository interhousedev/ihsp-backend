"""StudentViews: a student's own pages, run as that student (read-only)."""

import datetime as dt
from uuid import UUID

from app.bootstrap.adapters.composition.actors import student_actor
from app.bootstrap.adapters.composition.json_shape import json_object
from app.interfaces.http.v1.composition.ports import JsonObject
from app.modules.academic.application.classwork.student_attendance import (
    StudentAttendance,
)
from app.modules.academic.application.marks.get_semester_grades import (
    GetSemesterGrades,
)
from app.modules.academic.application.schedule.get_student_timetable import (
    GetStudentTimetable,
)
from app.modules.academic.application.schedule.student_profile import (
    GetStudentProfile,
)


class StudentViewsAdapter:
    """Composition <- academic: profile, timetable, grades and attendance."""

    def __init__(
        self,
        get_student_profile: GetStudentProfile,
        get_student_timetable: GetStudentTimetable,
        get_semester_grades: GetSemesterGrades,
        student_attendance: StudentAttendance,
    ) -> None:
        """Keep the four use cases."""
        self._profile = get_student_profile
        self._timetable = get_student_timetable
        self._grades = get_semester_grades
        self._attendance = student_attendance

    async def profile(self, user_id: UUID) -> JsonObject:
        """Return `StudentProfile` (the group nested as `{id, name}`)."""
        data = json_object(await self._profile.execute(student_actor(user_id)))
        group = {"id": data.pop("group_id"), "name": data.pop("group_name")}
        return {**data, "group": group}

    async def timetable(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[JsonObject]:
        """Return the student's `LessonItem` list between two dates."""
        lessons = await self._timetable.execute(student_actor(user_id), start, end)
        return [json_object(lesson) for lesson in lessons]

    async def grades(self, user_id: UUID) -> JsonObject:
        """Return `SemesterGrades` of the current semester."""
        return json_object(await self._grades.execute(student_actor(user_id), None))

    async def attendance(self, user_id: UUID) -> JsonObject:
        """Return `StudentAttendance` for the current term (keys `from` and `to`)."""
        report = await self._attendance.execute(student_actor(user_id), None, None)
        return json_object(report)
