"""Use case: set the topic from the staff portal and return the lesson page."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.set_topic import SetTopic
from app.modules.academic.application.classwork.staff_lesson import StaffLesson
from app.shared.actor import Actor


class StaffSetTopic:
    """Save the topic, then show the lesson as the teacher sees it."""

    def __init__(self, set_topic: SetTopic, staff_lesson: StaffLesson) -> None:
        """Initialize the use case."""
        self.set_topic = set_topic
        self.staff_lesson = staff_lesson

    async def execute(
        self, lesson_id: UUID, actor: Actor, topic: str
    ) -> dict[str, Any]:
        """Return the ``StaffLesson`` JSON after the change."""
        await self.set_topic.execute(lesson_id, actor, topic)
        return await self.staff_lesson.execute(lesson_id, actor)
