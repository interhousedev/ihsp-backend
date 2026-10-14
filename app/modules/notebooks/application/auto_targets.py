"""What an auto notebook is about, and which lessons feed it (NB-AUTO)."""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.domain.errors import (
    FeatureDisabledError,
    SubjectNotFoundError,
)
from app.modules.notebooks.domain.limits import NOTEBOOK_TITLE_MAX_CHARS
from app.modules.notebooks.ports.term_calendar import TermCalendar
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ClassworkQueries, LessonRef, ScheduleQueries

SUBJECT_EMOJI = "📚"
LESSON_EMOJI = "📖"
TITLE_SEPARATOR = " · "
NO_TERM_DAYS = 180  # the window around today when the calendar has no term


@dataclass(frozen=True, slots=True)
class SubjectSlot:
    """A subject (and, for a teacher, a group) the user can have a notebook for."""

    subject_id: UUID
    subject_name: str
    group_id: UUID | None
    group_name: str | None


def _group_of(key: str) -> UUID:
    """The group of an audience key ("<group>" or "<group>:<subgroup>")."""
    return UUID(key.partition(":")[0])


def _group_name(key: str, label: str) -> str:
    """The group's name from the readable audience label ("2TN1/2" -> "2TN1")."""
    return label if ":" not in key else label.rsplit("/", 1)[0]


def teacher_title(subject_name: str, group_name: str) -> str:
    """Title of a teacher's subject notebook ("Algebra · 2TN2"), cut to the limit."""
    suffix = f"{TITLE_SEPARATOR}{group_name}"
    return subject_name[: max(NOTEBOOK_TITLE_MAX_CHARS - len(suffix), 1)] + suffix


@dataclass(frozen=True, slots=True)
class AutoTarget:
    """A subject or lesson the student can open an auto notebook for."""

    origin: NotebookOrigin
    subject_id: UUID
    lesson_id: UUID | None
    title: str
    emoji: str
    lessons: list[LessonRef]
    space_key: str
    group_id: UUID | None = None  # a teacher's notebook: the group it is for


def lesson_title(subject_name: str, day: date) -> str:
    """Title of a lesson notebook ("Biology · 12.10.2026"), cut to the limit."""
    suffix = f"{TITLE_SEPARATOR}{day:%d.%m.%Y}"
    return subject_name[: NOTEBOOK_TITLE_MAX_CHARS - len(suffix)] + suffix


class AutoTargets:
    """Finds the lessons of a subject in this term, or one lesson, for a student.

    Only lessons the student attends count, so every material found through them is
    one the student may see. Without the academic contracts the feature is off.
    """

    def __init__(
        self,
        *,
        schedule: ScheduleQueries,
        classwork: ClassworkQueries | None,
        terms: TermCalendar | None,
        clock: Clock,
    ) -> None:
        """Store the collaborators (`classwork` and `terms` may be missing)."""
        self.schedule = schedule
        self.classwork = classwork
        self.terms = terms
        self.clock = clock

    async def resolve(
        self,
        user_id: UUID,
        origin: NotebookOrigin,
        target_id: UUID,
        group_id: UUID | None = None,
    ) -> AutoTarget | None:
        """Return the target of a new notebook.

        None when the student has no such lesson, or the teacher does not teach the
        subject to the group (`group_id` is given for teachers only). A student's
        subject needs no lessons yet, only to be known to the school.

        Raises:
            SubjectNotFoundError: A student's subject the school does not know.
            FeatureDisabledError: The academic contracts are not wired.
        """
        if origin is NotebookOrigin.SUBJECT_AUTO:
            if group_id is not None:
                return await self._teacher_subject(user_id, target_id, group_id)
            return await self._subject(user_id, target_id)
        return await self._lesson(user_id, target_id)

    async def student_slots(self, user_id: UUID) -> list[SubjectSlot]:
        """The subjects of the student's lessons this term, by name."""
        if await self.schedule.get_student(user_id) is None:
            return []
        start, end = await self._slot_window()
        lessons = await self.schedule.lessons_for_student(user_id, start, end)
        names = {x.subject_id: x.subject_name for x in lessons}
        return sorted(
            (SubjectSlot(sid, name, None, None) for sid, name in names.items()),
            key=lambda slot: slot.subject_name.casefold(),
        )

    async def teacher_slots(self, user_id: UUID) -> list[SubjectSlot]:
        """The subject and group pairs the teacher teaches this term."""
        start, end = await self._slot_window()
        lessons = await self.schedule.lessons_for_teacher(user_id, start, end)
        found: dict[tuple[UUID, UUID], SubjectSlot] = {}
        for lesson in lessons:
            for key, label in zip(lesson.audience, lesson.group_names, strict=False):
                group_id = _group_of(key)
                found.setdefault(
                    (lesson.subject_id, group_id),
                    SubjectSlot(
                        lesson.subject_id,
                        lesson.subject_name,
                        group_id,
                        _group_name(key, label),
                    ),
                )
        return sorted(
            found.values(),
            key=lambda x: (x.subject_name.casefold(), (x.group_name or "").casefold()),
        )

    async def _slot_window(self) -> tuple[date, date]:
        """This term, or half a year around today when there is no calendar."""
        today = local_today(self.clock)
        window = (
            await self.terms.current_term_dates(today)
            if self.terms is not None
            else None
        )
        return window or (
            today - timedelta(days=NO_TERM_DAYS),
            today + timedelta(days=NO_TERM_DAYS),
        )

    async def emis_subject_id(self, subject_id: UUID) -> int | None:
        """The EMIS id of a subject; the default materials are kept under it."""
        return await self.schedule.subject_emis_id(subject_id)

    async def lessons_of(self, notebook: Notebook) -> list[LessonRef]:
        """The lessons feeding a notebook now (empty when the student lost access)."""
        if notebook.origin is NotebookOrigin.SUBJECT_AUTO and notebook.subject_id:
            window = await self._term_window()
            if notebook.group_id is not None:
                return await self._teacher_lessons(
                    notebook.owner_id, notebook.subject_id, notebook.group_id, window
                )
            return await self._term_lessons(
                notebook.owner_id, notebook.subject_id, window
            )
        if notebook.origin is NotebookOrigin.LESSON_AUTO and notebook.lesson_id:
            lesson = await self._attended(notebook.owner_id, notebook.lesson_id)
            return [] if lesson is None else [lesson]
        return []

    async def _subject(self, user_id: UUID, subject_id: UUID) -> AutoTarget | None:
        start, end = await self._term_window()
        lessons = await self._term_lessons(user_id, subject_id, (start, end))
        # No lessons yet (a fresh student before the timetable syncs): the notebook
        # is made empty; only the student's own lessons ever feed it.
        name = (
            lessons[0].subject_name
            if lessons
            else await self.schedule.subject_title(subject_id)
        )
        if name is None:
            raise SubjectNotFoundError()
        student = await self.schedule.get_student(user_id)
        group = f"{student.group_id}:{student.subgroup or 0}" if student else "none"
        return AutoTarget(
            origin=NotebookOrigin.SUBJECT_AUTO,
            subject_id=subject_id,
            lesson_id=None,
            title=name[:NOTEBOOK_TITLE_MAX_CHARS],
            emoji=SUBJECT_EMOJI,
            lessons=lessons,
            space_key=f"subject:{subject_id}:{start or 'open'}:{group}",
        )

    async def _teacher_subject(
        self, user_id: UUID, subject_id: UUID, group_id: UUID
    ) -> AutoTarget | None:
        window = await self._term_window()
        lessons = await self._teacher_lessons(user_id, subject_id, group_id, window)
        if not lessons:
            return None
        names = {
            _group_of(key): _group_name(key, label)
            for lesson in lessons
            for key, label in zip(lesson.audience, lesson.group_names, strict=False)
        }
        title = teacher_title(
            lessons[0].subject_name, names.get(group_id, str(group_id))
        )
        return AutoTarget(
            origin=NotebookOrigin.SUBJECT_AUTO,
            subject_id=subject_id,
            lesson_id=None,
            title=title,
            emoji=SUBJECT_EMOJI,
            lessons=lessons,
            space_key=f"subject:{subject_id}:{window[0] or 'open'}:g{group_id}",
            group_id=group_id,
        )

    async def _teacher_lessons(
        self,
        user_id: UUID,
        subject_id: UUID,
        group_id: UUID,
        window: tuple[date | None, date | None],
    ) -> list[LessonRef]:
        """The teacher's lessons of the subject for the group in the window."""
        today = local_today(self.clock)
        start = window[0] or today - timedelta(days=NO_TERM_DAYS)
        end = window[1] or today + timedelta(days=NO_TERM_DAYS)
        lessons = await self.schedule.lessons_for_teacher(user_id, start, end)
        return [
            lesson
            for lesson in lessons
            if lesson.subject_id == subject_id
            and any(_group_of(key) == group_id for key in lesson.audience)
        ]

    async def _lesson(self, user_id: UUID, lesson_id: UUID) -> AutoTarget | None:
        self._require()
        lesson = await self._attended(user_id, lesson_id)
        if lesson is None:
            return None
        return AutoTarget(
            origin=NotebookOrigin.LESSON_AUTO,
            subject_id=lesson.subject_id,
            lesson_id=lesson.id,
            title=lesson_title(lesson.subject_name, lesson.date),
            emoji=LESSON_EMOJI,
            lessons=[lesson],
            space_key=f"lesson:{lesson.id}",
        )

    async def _attended(self, user_id: UUID, lesson_id: UUID) -> LessonRef | None:
        """The lesson, if the student is in its audience."""
        if not await self.schedule.is_in_audience(user_id, lesson_id):
            return None
        return await self.schedule.get_lesson(lesson_id)

    async def _term_window(self) -> tuple[date | None, date | None]:
        """First and last day of this term; open-ended when the calendar is empty."""
        _classwork, terms = self._require()
        term = await terms.current_term_dates(local_today(self.clock))
        return term if term is not None else (None, None)

    async def _term_lessons(
        self, user_id: UUID, subject_id: UUID, window: tuple[date | None, date | None]
    ) -> list[LessonRef]:
        classwork, _terms = self._require()
        return await classwork.subject_lessons(user_id, subject_id, *window)

    def _require(self) -> tuple[ClassworkQueries, TermCalendar]:
        if self.classwork is None or self.terms is None:
            raise FeatureDisabledError(params={"feature": "auto-notebooks"})
        return self.classwork, self.terms
