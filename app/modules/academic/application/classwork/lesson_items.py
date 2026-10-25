"""Builds the ``LessonItem`` and ``SubjectRef`` JSON of lessons."""

from collections.abc import Sequence
from typing import Any

from app.modules.academic.application.classwork.people import PeopleDirectory, Person
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.lesson_item import lesson_item


def subject_ref(lesson: Lesson, locale: str) -> dict[str, Any]:
    """Return the ``SubjectRef`` JSON of the lesson's subject."""
    name = lesson.subject_name(locale)
    return {
        "id": str(lesson.subject_id),
        "name": name,
        "short_name": lesson.subject_short or name,
    }


def audience_items(lesson: Lesson) -> list[dict[str, Any]]:
    """Return the ``AudienceItem`` JSON list of the lesson."""
    items = []
    for key in lesson.audience:
        group_id, subgroup = audience_keys.parse(key)
        items.append(
            {
                "group_id": str(group_id),
                "group_name": lesson.groups.get(group_id, ""),
                "subgroup": subgroup,
            }
        )
    return items


class LessonItemBuilder:
    """Turns lessons into ``LessonItem`` dicts with teachers resolved."""

    def __init__(self, people: PeopleDirectory) -> None:
        """Store the people directory."""
        self.people = people

    @staticmethod
    def item(lesson: Lesson, teacher: Person | None, locale: str) -> dict[str, Any]:
        """Build one ``LessonItem``."""
        return lesson_item(
            lesson.to_ref(locale),
            teacher=None if teacher is None else teacher.to_json(),
            subject_short=lesson.subject_short,
            audience=audience_items(lesson),
            attendance_submitted=lesson.submitted,
            has_homework=lesson.has_homework,
            is_overridden=lesson.is_overridden,
            changes=lesson.changes,
        )

    async def build_many(
        self, lessons: Sequence[Lesson], locale: str
    ) -> list[dict[str, Any]]:
        """Build items for many lessons with one identity lookup."""
        teachers = await self.people.people(
            lesson.teacher_id for lesson in lessons if lesson.teacher_id is not None
        )
        return [
            self.item(
                lesson,
                None if lesson.teacher_id is None else teachers.get(lesson.teacher_id),
                locale,
            )
            for lesson in lessons
        ]

    async def build(self, lesson: Lesson, locale: str) -> dict[str, Any]:
        """Build one item with its teacher resolved."""
        return (await self.build_many([lesson], locale))[0]
