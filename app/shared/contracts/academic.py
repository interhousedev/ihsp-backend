"""Academic contracts (providers: schedule, classwork and marks parts)."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor
from app.shared.contracts.emis import EmisSubject
from app.shared.lesson_kind import LessonKind, TopicSource


@dataclass(frozen=True, slots=True)
class StudentRef:
    """A student and the group they belong to."""

    user_id: UUID
    group_id: UUID
    group_name: str
    subgroup: int | None
    status: Literal["active", "left"]
    synced_at: dt.datetime | None
    # True when the group has no timetable in the current term: kick
    # `academic.sync_group_timetable` (after the student's account is committed).
    needs_timetable: bool = False
    # True when the group has no stored EMIS curriculum: kick
    # `academic.sync_group_curriculum`.
    needs_curriculum: bool = False


@dataclass(frozen=True, slots=True)
class LessonRef:
    """A lesson as other modules see it."""

    id: UUID
    date: dt.date
    period: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    subject_name: str
    teacher_id: UUID | None
    room_id: UUID | None
    room_slug: str | None
    room_name: str | None
    audience: tuple[str, ...]
    group_names: tuple[str, ...]
    status: Literal["scheduled", "cancelled"]
    topic: str | None
    homework_text: str | None
    homework_due_date: dt.date | None
    kind: LessonKind = "other"
    topic_source: TopicSource | None = None


@dataclass(frozen=True, slots=True)
class RoomRef:
    """A room with its public page."""

    id: UUID
    slug: str
    name: str
    pin: str
    status: Literal["active", "archived"]


@dataclass(frozen=True, slots=True)
class SubjectSummary:
    """A student's standing in one subject."""

    subject_id: UUID
    name: str
    teacher_names: tuple[str, ...]
    semester_mark: float | None
    emis_rating: int | None
    absences: int
    lessons_with_attendance: int
    gpa_with_temporary: float | None = None


@dataclass(frozen=True, slots=True)
class MarkRef:
    """One mark."""

    subject_id: UUID
    subject_name: str
    semester: int
    type: str
    value: int
    date: dt.date
    lesson_id: UUID | None


class ScheduleQueries(Protocol):
    """Read access to the schedule (provider: B3)."""

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        """Return the student record or None."""
        ...

    async def get_lesson(self, lesson_id: UUID) -> LessonRef | None:
        """Return the lesson or None."""
        ...

    async def subject_emis_id(self, subject_id: UUID) -> int | None:
        """The EMIS id of a subject; None when the subject has none (or is gone)."""
        ...

    async def subject_title(self, subject_id: UUID) -> str | None:
        """The subject's display name; None when there is no such subject."""
        ...

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return the student's lessons between two dates."""
        ...

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return the teacher's lessons between two dates."""
        ...

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the student attends the lesson."""
        ...

    async def emis_control_lessons(
        self, group_ids: Sequence[UUID], start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return scheduled lessons EMIS calls a midterm or a final (``kind``), by date.

        EMIS exam weeks are reliable, unlike its topics and files. Each lesson has its
        id, subject, date and audience.
        """
        ...

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the user teaches the lesson."""
        ...

    async def head_student_ids(self, lesson_id: UUID) -> list[UUID]:
        """Return group heads of the lesson's audience."""
        ...

    async def room_by_slug(self, slug: str) -> RoomRef | None:
        """Return the room with this slug."""
        ...

    async def room_day(self, room_id: UUID, day: dt.date) -> list[LessonRef]:
        """Return the lessons held in the room on a day."""
        ...

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int] = ()
    ) -> list[UUID]:
        """Return user ids of the groups' active students."""
        ...

    async def search_lessons(
        self, user_id: UUID, query: str, limit: int
    ) -> list[LessonRef]:
        """Search the user's lessons by subject, topic or homework."""
        ...

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return the groups the teacher curates."""
        ...

    async def projected_lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return generated lessons plus lessons projected from timetable entries.

        Projected ids are uuid5(entry_id, date).
        """
        ...


@dataclass(frozen=True, slots=True)
class LessonGroupRef:
    """One (lesson, group) pair: a lesson for several groups yields one per group."""

    lesson_id: UUID
    date: dt.date
    subject_id: UUID
    teacher_id: UUID | None
    group_id: UUID
    group_name: str


class LessonGroupIndex(Protocol):
    """Lessons of a subject by group (provider: schedule)."""

    async def lesson_groups(
        self,
        *,
        subject_id: UUID | None = None,
        lesson_ids: Sequence[UUID] | None = None,
        teacher_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> list[LessonGroupRef]:
        """Return (lesson, group) pairs matching every given filter.

        At least one of ``subject_id`` and ``lesson_ids`` must be given.
        """
        ...


class GroupDirectory(Protocol):
    """Existence check of student groups (provider: schedule)."""

    async def existing_group_ids(self, ids: Sequence[UUID]) -> set[UUID]:
        """Return the subset of ``ids`` that are groups."""
        ...


class ClassworkQueries(Protocol):
    """Read access to homework and attendance (provider: B4)."""

    async def subject_lessons(
        self,
        user_id: UUID,
        subject_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[LessonRef]:
        """Return the student's lessons of one subject."""
        ...

    async def homework(
        self,
        user_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
        done: bool | None,
    ) -> list[dict[str, Any]]:
        """Return items {"lesson": LessonRef, "done_at", "note"}."""
        ...

    async def absences(
        self, user_id: UUID, start: dt.date | None, end: dt.date | None
    ) -> list[dict[str, Any]]:
        """Return items {"lesson": LessonRef, "excused": bool}."""
        ...

    async def missing_attendance(
        self, teacher_id: UUID | None, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return finished lessons without submitted attendance."""
        ...

    async def work_off_templates(self, teacher_id: UUID) -> list[dict[str, Any]]:
        """Return the teacher's templates as {"id", "text", "is_default"}."""
        ...

    async def my_work_offs(self, student_id: UUID, locale: str) -> list[dict[str, Any]]:
        """Return the student's open work-offs.

        Keys: id, lesson_id, date, period, subject_name, teacher_name, text,
        status, due_date, done_at, created_at.
        """
        ...

    async def teacher_open_work_offs(
        self, teacher_id: UUID, locale: str
    ) -> list[dict[str, Any]]:
        """Return the teacher's open work-offs.

        Keys: id, student_name, group_name, lesson_id, date, subject_name, text.
        """
        ...


class MarksQueries(Protocol):
    """Read access to marks and results (provider: B5)."""

    async def subjects_summary(
        self, user_id: UUID, semester: int | None
    ) -> list[SubjectSummary]:
        """Return the student's standing per subject."""
        ...

    async def marks(
        self,
        user_id: UUID,
        subject_id: UUID | None,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[MarkRef]:
        """Return marks, optionally filtered."""
        ...

    async def results(self, user_id: UUID, semester: int | None) -> dict[str, Any]:
        """Return {"semester", "gpa", "subjects": [...]}.

        Each subject has subject_id, name, lesson_avg, midterm_avg, final_avg,
        semester_mark, emis_rating and marks_count.
        """
        ...

    async def new_marks_since(
        self, user_id: UUID, since: dt.datetime | None, limit: int = 20
    ) -> list[MarkRef]:
        """Return marks added after a moment."""
        ...

    async def gpa_for_users(
        self, user_ids: Sequence[UUID], semester: int | None
    ) -> dict[UUID, float | None]:
        """Return the GPA of each user."""
        ...


class ClassworkCommands(Protocol):
    """Classwork actions for the bot (provider: B4)."""

    async def prompt_state(self, lesson_id: UUID, teacher_id: UUID) -> dict[str, Any]:
        """Return the lesson prompt state.

        Keys: lesson (LessonRef), roster (items with position, user_id, name,
        group_name, subgroup_unset, absent), attendance_submitted,
        attendance_version, homework_text, expired.
        """
        ...

    async def toggle_draft_absent(
        self, lesson_id: UUID, teacher_id: UUID, position: int
    ) -> dict[str, Any]:
        """Toggle one student in the draft and return the prompt state."""
        ...

    async def submit_attendance(
        self,
        lesson_id: UUID,
        actor: Actor,
        *,
        absent: Sequence[UUID] | None,
        from_draft: bool,
        base_version: int,
        source: Literal["bot", "staff", "admin"],
        work_off_mode: str = "per_student",
        common_work_off: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save attendance and return the prompt state.

        ``work_off_mode`` is per_student, none or common; ``common_work_off`` is
        {"template_id", "text", "due_date"} and gives every absent student a task.
        """
        ...

    async def set_homework(
        self, lesson_id: UUID, actor: Actor, text: str, due_date: dt.date | None
    ) -> LessonRef:
        """Set the lesson's homework."""
        ...

    async def clear_homework(self, lesson_id: UUID, actor: Actor) -> None:
        """Remove the lesson's homework."""
        ...

    async def set_topic(self, lesson_id: UUID, actor: Actor, topic: str) -> LessonRef:
        """Set the lesson's topic."""
        ...

    async def set_homework_done(
        self, lesson_id: UUID, actor: Actor, done: bool
    ) -> None:
        """Mark the student's homework as done or not done."""
        ...

    async def set_work_off_status(
        self, work_off_id: UUID, actor: Actor, status: str
    ) -> dict[str, Any]:
        """Mark a work-off assigned or done; return its WorkOffResponse dict."""
        ...


class AcademicEnrollment(Protocol):
    """Enrollment actions (provider: B3; consumers: B2 and B5)."""

    async def ensure_student(
        self,
        *,
        user_id: UUID,
        group_emis_id: int,
        group_name: str,
        current_semester: int | None,
        curriculum_id: int | None,
    ) -> StudentRef:
        """Create or update the student's group membership."""
        ...

    async def find_imported_student(
        self,
        *,
        emis_student_id: int | None,
        first_name: str,
        last_name: str,
        group_name: str,
    ) -> UUID | None:
        """Find an unregistered student created by an import."""
        ...

    async def sync_subjects(
        self, *, group_id: UUID, subjects: Sequence[EmisSubject]
    ) -> None:
        """Create or update the subjects of a group."""
        ...

    async def mark_left(self, user_id: UUID, *, reason: str) -> None:
        """Mark the student as having left."""
        ...

    async def group_names(self, group_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Return the names of the active groups among ``group_ids``."""
        ...

    async def enqueue_student_sync(self, user_id: UUID) -> None:
        """Record the initial sync as pending; it is retried until it succeeds."""
        ...
