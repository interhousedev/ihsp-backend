"""McpTeacherTools over the academic module.

Authorization stays in the use cases: a lesson the actor does not teach, a group they
do not curate or a control of a subject they do not teach is refused exactly as on the
web, so the tools add no access of their own.
"""

import datetime as dt
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.modules.academic.application.assessments.inputs import (
    AssessmentInput,
    StaffFilters,
)
from app.modules.academic.domain.assessments.edit import UNSET, AssessmentPatch
from app.shared.actor import Actor
from app.shared.contracts.mcp_teacher import GroupAttendanceView, McpTeacherTools

if TYPE_CHECKING:
    from app.bootstrap.container import Container

# One report reads one sheet per lesson: bound the work of a single call.
REPORT_LESSONS_MAX = 60
_EDITABLE = ("title", "date", "room", "note", "status")


class McpTeacherToolsAdapter:
    """Reads the academic module lazily from the container."""

    def __init__(self, container: "Container") -> None:
        """Keep the container."""
        self._c = container

    async def today(self, actor: Actor) -> dict[str, Any]:
        """Return the staff "today" screen."""
        return await self._c.academic.classwork.staff_today.execute(actor)

    async def timetable(self, actor: Actor, start: dt.date, end: dt.date) -> list[Any]:
        """Return the lessons the actor teaches in the range."""
        items = await self._c.academic.schedule.get_staff_timetable.execute(
            actor, start, end
        )
        return list(items)

    async def lesson(self, actor: Actor, lesson_id: UUID) -> dict[str, Any]:
        """Return one lesson as its teacher sees it."""
        return await self._c.academic.classwork.staff_lesson.execute(lesson_id, actor)

    async def my_groups(self, actor: Actor) -> dict[str, Any]:
        """Return the curated groups and the journals the actor teaches."""
        academic = self._c.academic
        curated = await academic.schedule.list_curated_groups.execute(actor)
        teaching = await academic.classwork.journal_options.execute(actor)
        return {"curated": curated, "teaching": teaching}

    async def group_roster(self, actor: Actor, group_id: UUID) -> dict[str, Any]:
        """Return a curated group with its students."""
        detail = await self._c.academic.schedule.get_group_detail.execute(
            actor, group_id
        )
        students = await self._c.academic.classwork.curator_students.execute(
            actor, group_id
        )
        return {"group": detail, "students": students}

    async def journal(
        self,
        actor: Actor,
        subject_id: UUID,
        audience_key: str,
        term_id: UUID | None,
    ) -> dict[str, Any]:
        """Return a journal of the actor."""
        return await self._c.academic.classwork.get_journal.execute(
            actor, subject_id, audience_key, term_id
        )

    async def group_attendance(
        self,
        actor: Actor,
        group_id: UUID,
        view: GroupAttendanceView,
        start: dt.date | None,
        end: dt.date | None,
    ) -> dict[str, Any]:
        """Return the attendance report of a curated group."""
        return await self._c.academic.classwork.group_attendance.execute(
            actor, group_id, view, start, end
        )

    async def missing_attendance(
        self, actor: Actor, start: dt.date, end: dt.date
    ) -> list[Any]:
        """Return the actor's own lessons without attendance (never other teachers')."""
        queries = self._c.academic.classwork.queries
        return list(await queries.missing_attendance(actor.user_id, start, end))

    async def set_homework(
        self, actor: Actor, lesson_id: UUID, text: str, due_date: dt.date | None
    ) -> dict[str, Any]:
        """Set the homework of a lesson."""
        return await self._c.academic.classwork.staff_set_homework.execute(
            lesson_id, actor, text, due_date
        )

    async def homework_submissions(
        self, actor: Actor, lesson_id: UUID
    ) -> dict[str, Any]:
        """Return the submissions of a lesson the actor teaches."""
        return await self._c.academic.classwork.list_homework_submissions.execute(
            lesson_id, actor
        )

    async def clear_homework(self, actor: Actor, lesson_id: UUID) -> dict[str, Any]:
        """Clear the homework of a lesson."""
        return await self._c.academic.classwork.staff_clear_homework.execute(
            lesson_id, actor
        )

    async def temporary_marks(
        self, actor: Actor, lesson_id: UUID | None
    ) -> list[dict[str, Any]]:
        """Return the temporary marks of a lesson or all the pending ones."""
        classwork = self._c.academic.classwork
        if lesson_id is not None:
            views = await classwork.list_lesson_temporary_marks.execute(
                lesson_id, actor
            )
        else:
            views = await classwork.list_pending_temporary_marks.execute(
                actor, teacher_id=actor.user_id
            )
        return [view.to_json() for view in views]

    async def set_temporary_mark(
        self,
        actor: Actor,
        lesson_id: UUID,
        student_id: UUID,
        value: int,
        comment: str | None,
    ) -> dict[str, Any]:
        """Set a temporary mark."""
        view = await self._c.academic.classwork.set_temporary_mark.execute(
            lesson_id, student_id, actor, value=value, comment=comment
        )
        result: dict[str, Any] = view.to_json()
        return result

    async def delete_temporary_mark(
        self, actor: Actor, lesson_id: UUID, student_id: UUID
    ) -> None:
        """Delete a temporary mark."""
        await self._c.academic.classwork.delete_temporary_mark.execute(
            lesson_id, student_id, actor
        )

    async def student_record(
        self, actor: Actor, group_id: UUID, semester: int | None
    ) -> dict[str, Any]:
        """Return the semester progress of a curated group."""
        return await self._c.academic.marks.get_group_progress.for_staff(
            actor, group_id, semester
        )

    async def list_assessments(
        self,
        actor: Actor,
        *,
        start: dt.date | None,
        end: dt.date | None,
        subject_id: UUID | None,
        group_id: UUID | None,
        kind: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        """Return the controls the actor may see as staff."""
        filters = StaffFilters(
            since=start,
            until=end,
            subject_id=subject_id,
            group_id=group_id,
            kind=kind,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            source=None,
            undated=False,
        )
        return await self._c.academic.assessments.list_staff.execute(actor, filters)

    async def create_assessment(
        self,
        actor: Actor,
        *,
        subject_id: UUID,
        group_ids: list[UUID],
        kind: str,
        day: dt.date,
        title: str,
        room: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        """Plan a control for whole groups."""
        data = AssessmentInput(
            subject_id=subject_id,
            audience=[(group_id, None) for group_id in group_ids],
            kind=kind,  # type: ignore[arg-type]
            date=day,
            title=title,
            starts_at=None,
            room=room,
            note=note,
            lesson_id=None,
            control=None,
        )
        return await self._c.academic.assessments.create.execute(actor, data)

    async def update_assessment(
        self, actor: Actor, assessment_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply the sent fields only."""
        values = {name: changes[name] for name in _EDITABLE if name in changes}
        patch = AssessmentPatch(
            title=values.get("title", UNSET),
            date=values.get("date", UNSET),
            room=values.get("room", UNSET),
            note=values.get("note", UNSET),
            status=values.get("status", UNSET),
        )
        return await self._c.academic.assessments.update.execute(
            actor, assessment_id, patch
        )

    async def unfinished_work_report(
        self, actor: Actor, start: dt.date, end: dt.date
    ) -> dict[str, Any]:
        """List absent or excused students of own lessons who owe a work-off."""
        classwork = self._c.academic.classwork
        lessons = await self._c.academic.schedule.get_staff_timetable.execute(
            actor, start, end
        )
        taught = [item for item in lessons if item.get("status") != "cancelled"]
        rows: list[dict[str, Any]] = []
        for item in taught[:REPORT_LESSONS_MAX]:
            sheet = await classwork.staff_lesson.execute(item["id"], actor)
            attendance = sheet.get("attendance") or {}
            offs = {str(w.get("student_id")) for w in attendance.get("work_offs") or []}
            owing = [
                {
                    "student_id": s.get("user_id"),
                    "first_name": s.get("first_name"),
                    "last_name": s.get("last_name"),
                    "group_name": s.get("group_name"),
                    "excused": bool(s.get("excused")),
                }
                for s in attendance.get("roster") or []
                if (s.get("absent") or s.get("excused"))
                and str(s.get("user_id")) not in offs
            ]
            if owing:
                rows.append(
                    {
                        "lesson_id": item["id"],
                        "date": item.get("date"),
                        "subject": item.get("subject_name") or item.get("subject"),
                        "students": owing,
                    }
                )
        open_work_offs = await classwork.list_teacher_work_offs.execute(actor.user_id)
        return {
            "lessons_checked": min(len(taught), REPORT_LESSONS_MAX),
            "truncated": len(taught) > REPORT_LESSONS_MAX,
            "absent_without_work_off": rows,
            "open_work_offs": open_work_offs,
        }


def build_teacher_tools(container: "Container") -> McpTeacherTools:
    """Create the adapter."""
    return McpTeacherToolsAdapter(container)
