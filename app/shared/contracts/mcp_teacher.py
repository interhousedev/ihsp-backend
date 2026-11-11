"""What the teacher MCP tools need (implemented by the academic module).

Every method takes the user as an `Actor` from the guard, never from tool arguments.
A lesson, group or control the teacher does not teach or curate raises the same
domain error as the web API (forbidden or not found). Results are JSON-able.
"""

from datetime import date
from typing import Any, Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor

GroupAttendanceView = Literal["student", "subject", "day", "lesson"]


class McpTeacherTools(Protocol):
    """Today, timetable, journal, homework, temporary marks and assessments."""

    async def today(self, actor: Actor) -> dict[str, Any]:
        """The current or next lesson, today's lessons and the missed attendance."""
        ...

    async def timetable(self, actor: Actor, start: date, end: date) -> list[Any]:
        """The lessons the teacher teaches in a closed range."""
        ...

    async def lesson(self, actor: Actor, lesson_id: UUID) -> dict[str, Any]:
        """One lesson as its teacher (or the curator) sees it: roster, homework."""
        ...

    async def homework_submissions(
        self, actor: Actor, lesson_id: UUID
    ) -> dict[str, Any]:
        """Who handed in the homework of a lesson, with download links."""
        ...

    async def my_groups(self, actor: Actor) -> dict[str, Any]:
        """`{"curated": GroupItem[], "teaching": {subject, audience_key, label}[]}`."""
        ...

    async def group_roster(self, actor: Actor, group_id: UUID) -> dict[str, Any]:
        """A curated group with its students."""
        ...

    async def journal(
        self,
        actor: Actor,
        subject_id: UUID,
        audience_key: str,
        term_id: UUID | None,
    ) -> dict[str, Any]:
        """Students by lessons of a journal the teacher teaches."""
        ...

    async def group_attendance(
        self,
        actor: Actor,
        group_id: UUID,
        view: GroupAttendanceView,
        start: date | None,
        end: date | None,
    ) -> dict[str, Any]:
        """The attendance report of a curated group."""
        ...

    async def missing_attendance(
        self, actor: Actor, start: date, end: date
    ) -> list[Any]:
        """The teacher's own finished lessons without a submitted attendance list."""
        ...

    async def set_homework(
        self, actor: Actor, lesson_id: UUID, text: str, due_date: date | None
    ) -> dict[str, Any]:
        """Set the homework of a lesson the actor teaches; return the lesson."""
        ...

    async def clear_homework(self, actor: Actor, lesson_id: UUID) -> dict[str, Any]:
        """Remove the homework of a lesson the actor teaches; return the lesson."""
        ...

    async def temporary_marks(
        self, actor: Actor, lesson_id: UUID | None
    ) -> list[dict[str, Any]]:
        """Temporary marks of one lesson, or the pending ones of all own lessons."""
        ...

    async def set_temporary_mark(
        self,
        actor: Actor,
        lesson_id: UUID,
        student_id: UUID,
        value: int,
        comment: str | None,
    ) -> dict[str, Any]:
        """Create or replace a student's temporary mark for a lesson."""
        ...

    async def delete_temporary_mark(
        self, actor: Actor, lesson_id: UUID, student_id: UUID
    ) -> None:
        """Delete a student's temporary mark for a lesson."""
        ...

    async def student_record(
        self, actor: Actor, group_id: UUID, semester: int | None
    ) -> dict[str, Any]:
        """Semester grades and attendance per student of a curated group."""
        ...

    async def list_assessments(
        self,
        actor: Actor,
        *,
        start: date | None,
        end: date | None,
        subject_id: UUID | None,
        group_id: UUID | None,
        kind: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        """The controls (ПК, ИК, tests) of the teacher's subjects and groups."""
        ...

    async def create_assessment(
        self,
        actor: Actor,
        *,
        subject_id: UUID,
        group_ids: list[UUID],
        kind: str,
        day: date,
        title: str,
        room: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        """Plan a control for whole groups; a teacher must teach the subject there."""
        ...

    async def update_assessment(
        self,
        actor: Actor,
        assessment_id: UUID,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply the given fields (`title`, `date`, `room`, `note`, `status`)."""
        ...

    async def unfinished_work_report(
        self, actor: Actor, start: date, end: date
    ) -> dict[str, Any]:
        """Absent or excused students without a work-off, per own lesson."""
        ...
