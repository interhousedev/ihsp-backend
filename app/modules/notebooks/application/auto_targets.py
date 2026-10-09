"""What an auto notebook is about, and which lessons feed it (NB-AUTO)."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.domain.errors import FeatureDisabledError
from app.modules.notebooks.domain.limits import NOTEBOOK_TITLE_MAX_CHARS
from app.modules.notebooks.ports.term_calendar import TermCalendar
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ClassworkQueries, LessonRef, ScheduleQueries

SUBJECT_EMOJI = "📚"
LESSON_EMOJI = "📖"
TITLE_SEPARATOR = " · "


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
        self, user_id: UUID, origin: NotebookOrigin, target_id: UUID
    ) -> AutoTarget | None:
        """Return the target of a new notebook.

        None when the student has no such subject or lesson.

        Raises:
            FeatureDisabledError: The academic contracts are not wired.
        """
        if origin is NotebookOrigin.SUBJECT_AUTO:
            return await self._subject(user_id, target_id)
        return await self._lesson(user_id, target_id)

    async def lessons_of(self, notebook: Notebook) -> list[LessonRef]:
        """The lessons feeding a notebook now (empty when the student lost access)."""
        if notebook.origin is NotebookOrigin.SUBJECT_AUTO and notebook.subject_id:
            window = await self._term_window()
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
        if not lessons:
            return None
        student = await self.schedule.get_student(user_id)
        group = f"{student.group_id}:{student.subgroup or 0}" if student else "none"
        return AutoTarget(
            origin=NotebookOrigin.SUBJECT_AUTO,
            subject_id=subject_id,
            lesson_id=None,
            title=lessons[0].subject_name[:NOTEBOOK_TITLE_MAX_CHARS],
            emoji=SUBJECT_EMOJI,
            lessons=lessons,
            space_key=f"subject:{subject_id}:{start or 'open'}:{group}",
        )

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
