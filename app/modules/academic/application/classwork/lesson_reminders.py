"""Use case: lesson reminders, run every minute (UF-SYS-06, UF-BOT-07, UF-BOT-08)."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ReaderUnitOfWork,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.shared.clock import Clock
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import UserPreferences
from app.shared.contracts.links import LinksApi
from app.shared.notifications import NotificationDraft, NotificationType

LOOKAHEAD = dt.timedelta(minutes=30)
TICK = dt.timedelta(minutes=1)
PROMPT_BEFORE_END = dt.timedelta(minutes=5)


class LessonReminders:
    """Queue resource messages before lessons and attendance prompts before their end.

    The outbox's unique keys make a second run in the same minute harmless.
    """

    def __init__(
        self,
        uow_factory: Callable[[], ReaderUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        schedule: ScheduleQueries,
        links: LinksApi,
        rooms_url: str,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.schedule = schedule
        self.links = links
        self.rooms_url = rooms_url.rstrip("/")

    async def execute(self) -> dict[str, int]:
        """Queue the reminders due now; return how many of each were queued."""
        now = self.clock.now()
        preferences: dict[UUID, UserPreferences] = {}
        async with self.uow_factory() as uow:
            starting = await uow.lesson_reader.starting_between(now, now + LOOKAHEAD)
            ending = await uow.lesson_reader.ending_between(
                now - TICK + PROMPT_BEFORE_END, now + PROMPT_BEFORE_END
            )
            resources: list[NotificationDraft] = []
            for lesson in starting:
                resources += await self._resources(lesson, now, preferences)
            prompts: list[NotificationDraft] = []
            for lesson in ending:
                prompts += await self._prompt(lesson, preferences)
            drafts = [*resources, *prompts]
            if drafts:
                uow.notify(*drafts)
                await uow.commit()
        return {"resources": len(resources), "prompts": len(prompts)}

    async def _prefs(
        self, user_id: UUID, cache: dict[UUID, UserPreferences]
    ) -> UserPreferences:
        if user_id not in cache:
            cache[user_id] = await self.people.preferences(user_id)
        return cache[user_id]

    async def _resources(
        self, lesson: Lesson, now: dt.datetime, cache: dict[UUID, UserPreferences]
    ) -> list[NotificationDraft]:
        recipients = list(await self.schedule.head_student_ids(lesson.id))
        if lesson.teacher_id is not None:
            recipients.insert(0, lesson.teacher_id)
        drafts: list[NotificationDraft] = []
        has_resources: bool | None = None
        for user_id in dict.fromkeys(recipients):
            prefs = await self._prefs(user_id, cache)
            fire_at = lesson.starts_at - dt.timedelta(
                minutes=prefs.lessons_links_lead_min
            )
            if not now - TICK < fire_at <= now:
                continue
            if has_resources is None:
                has_resources = bool(await self.links.lesson_resources(lesson.id))
            if not has_resources:
                return []
            drafts.append(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.LESSON_RESOURCES,
                    payload=self._resources_payload(lesson, str(prefs.locale)),
                    dedupe_key=f"res:{lesson.id}:{user_id}",
                )
            )
        return drafts

    def _resources_payload(self, lesson: Lesson, locale: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "lesson_id": str(lesson.id),
            "group_names": list(lesson.group_names),
            "subject_name": lesson.subject_name(locale),
            "period": lesson.period,
        }
        if lesson.room_name:
            payload["room_name"] = lesson.room_name
        if lesson.room_slug and lesson.room_pin:
            payload["room_url"] = (
                f"{self.rooms_url}/{lesson.room_slug}?pin={lesson.room_pin}"
            )
            payload["room_pin"] = lesson.room_pin
        return payload

    async def _prompt(
        self, lesson: Lesson, cache: dict[UUID, UserPreferences]
    ) -> list[NotificationDraft]:
        teacher_id = lesson.teacher_id
        if teacher_id is None:
            return []
        if not (await self._prefs(teacher_id, cache)).lessons_prompt_enabled:
            return []
        return [
            NotificationDraft(
                user_id=teacher_id,
                type=NotificationType.LESSON_PROMPT,
                payload={
                    "lesson_id": str(lesson.id),
                    "teacher_id": str(teacher_id),
                    "ends_at": lesson.ends_at.isoformat(),
                },
                dedupe_key=(
                    f"prompt:{lesson.id}:{teacher_id}:{lesson.ends_at.isoformat()}"
                ),
            )
        ]
