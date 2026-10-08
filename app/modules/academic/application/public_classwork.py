"""Public API of classwork: ``ClassworkQueries`` and ``ClassworkCommands``."""

import datetime as dt
from collections.abc import Callable, Sequence
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.application.classwork.clear_homework import ClearHomework
from app.modules.academic.application.classwork.get_prompt_state import GetPromptState
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.set_homework import SetHomework
from app.modules.academic.application.classwork.set_homework_done import (
    SetHomeworkDone,
)
from app.modules.academic.application.classwork.set_topic import SetTopic
from app.modules.academic.application.classwork.student_context import (
    keys_of,
    require_student,
)
from app.modules.academic.application.classwork.submit_from_draft import SubmitFromDraft
from app.modules.academic.application.classwork.toggle_draft_absent import (
    ToggleDraftAbsent,
)
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import LessonRef

DEFAULT_LOCALE = "uz"
WIDE_DAYS = 365


class ClassworkQueriesImpl:
    """Read access for the assistant and other modules (ClassworkQueries)."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
    ) -> None:
        """Initialize the queries."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people

    async def subject_lessons(
        self,
        user_id: UUID,
        subject_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[LessonRef]:
        """Return the student's lessons of one subject."""
        today = local_today(self.clock)
        locale = await self.people.locale(user_id)
        async with self.uow_factory() as uow:
            student = await require_student(uow, user_id)
            lessons = await uow.lesson_reader.audience_lessons(
                keys_of(student),
                start or today - dt.timedelta(days=WIDE_DAYS),
                end or today + dt.timedelta(days=WIDE_DAYS),
                subject_id=subject_id,
            )
        return [lesson.to_ref(locale) for lesson in lessons]

    async def homework(
        self,
        user_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
        done: bool | None,
    ) -> list[dict[str, Any]]:
        """Return items ``{"lesson": LessonRef, "done_at", "note"}``.

        ``start`` and ``end`` bound the due date (the lesson date if none).
        """
        today = local_today(self.clock)
        locale = await self.people.locale(user_id)
        async with self.uow_factory() as uow:
            student = await require_student(uow, user_id)
            records = await uow.lesson_reader.homework_records(
                user_id, keys_of(student), today - dt.timedelta(days=WIDE_DAYS)
            )
        items = []
        for record in records:
            lesson, todo = record.lesson, record.todo
            when = lesson.homework_due_date or lesson.date
            is_done = todo is not None and todo.done_at is not None
            if (start and when < start) or (end and when > end):
                continue
            if done is not None and done != is_done:
                continue
            items.append(
                {
                    "lesson": lesson.to_ref(locale),
                    "done_at": todo.done_at if todo else None,
                    "note": todo.note if todo else None,
                }
            )
        return items

    async def absences(
        self, user_id: UUID, start: dt.date | None, end: dt.date | None
    ) -> list[dict[str, Any]]:
        """Return items ``{"lesson": LessonRef, "excused": bool}``."""
        today = local_today(self.clock)
        locale = await self.people.locale(user_id)
        async with self.uow_factory() as uow:
            missed = await uow.lesson_reader.student_absences(
                user_id, start or today - dt.timedelta(days=WIDE_DAYS), end or today
            )
        return [
            {"lesson": lesson.to_ref(locale), "excused": excused}
            for lesson, excused in missed
        ]

    async def missing_attendance(
        self, teacher_id: UUID | None, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return finished lessons without submitted attendance."""
        async with self.uow_factory() as uow:
            lessons = await uow.lesson_reader.missing_attendance(
                teacher_id, start, end, self.clock.now()
            )
        return [lesson.to_ref(DEFAULT_LOCALE) for lesson in lessons]


class ClassworkCommandsImpl:
    """Actions for the Telegram bot (ClassworkCommands)."""

    def __init__(
        self,
        people: PeopleDirectory,
        get_prompt_state: GetPromptState,
        toggle_draft_absent: ToggleDraftAbsent,
        submit_from_draft: SubmitFromDraft,
        set_homework: SetHomework,
        clear_homework: ClearHomework,
        set_topic: SetTopic,
        set_homework_done: SetHomeworkDone,
    ) -> None:
        """Initialize the commands."""
        self.people = people
        self._prompt_state = get_prompt_state
        self._toggle = toggle_draft_absent
        self._submit = submit_from_draft
        self._set_homework = set_homework
        self._clear_homework = clear_homework
        self._set_topic = set_topic
        self._set_done = set_homework_done

    async def prompt_state(self, lesson_id: UUID, teacher_id: UUID) -> dict[str, Any]:
        """Return the end-of-lesson prompt state."""
        return await self._prompt_state.execute(lesson_id, teacher_id)

    async def toggle_draft_absent(
        self, lesson_id: UUID, teacher_id: UUID, position: int
    ) -> dict[str, Any]:
        """Toggle one student in the draft and return the prompt state."""
        return await self._toggle.execute(lesson_id, teacher_id, position)

    async def submit_attendance(
        self,
        lesson_id: UUID,
        actor: Actor,
        *,
        absent: Sequence[UUID] | None,
        from_draft: bool,
        base_version: int,
        source: Literal["bot", "staff", "admin"],
    ) -> dict[str, Any]:
        """Save attendance and return the prompt state."""
        return await self._submit.execute(
            lesson_id,
            actor,
            absent=absent,
            from_draft=from_draft,
            base_version=base_version,
            source=source,
        )

    async def set_homework(
        self, lesson_id: UUID, actor: Actor, text: str, due_date: dt.date | None
    ) -> LessonRef:
        """Set the lesson's homework."""
        lesson = await self._set_homework.execute(lesson_id, actor, text, due_date)
        return lesson.to_ref(await self.people.locale(actor.user_id))

    async def clear_homework(self, lesson_id: UUID, actor: Actor) -> None:
        """Remove the lesson's homework."""
        await self._clear_homework.execute(lesson_id, actor)

    async def set_topic(self, lesson_id: UUID, actor: Actor, topic: str) -> LessonRef:
        """Set the lesson's topic."""
        lesson = await self._set_topic.execute(lesson_id, actor, topic)
        return lesson.to_ref(await self.people.locale(actor.user_id))

    async def set_homework_done(
        self, lesson_id: UUID, actor: Actor, done: bool
    ) -> None:
        """Mark the student's homework as done or not done."""
        await self._set_done.execute(lesson_id, actor, done)
