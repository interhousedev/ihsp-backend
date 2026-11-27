"""Ports of the lesson AI: the model call and the tutor conversation store."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

LessonTask = Literal["lms_tutor", "lms_video_checks", "lms_badge_draft"]


class LessonModel(Protocol):
    """One structured model call of a lesson AI task (usage ledger, prompt slots)."""

    async def complete_json(
        self,
        *,
        task: LessonTask,
        system: str,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Return the parsed document; raises the AI errors of the gateway."""
        ...


@dataclass(frozen=True, slots=True)
class TutorMessage:
    """A stored message of a tutor conversation."""

    role: Literal["student", "tutor"]
    text: str
    created_at: datetime


class TutorHistory(Protocol):
    """The tutor conversation of one student in one step."""

    async def read(self, user_id: UUID, step_id: UUID) -> list[TutorMessage]:
        """Return the messages, oldest first."""
        ...

    async def append(
        self, user_id: UUID, step_id: UUID, messages: list[TutorMessage]
    ) -> None:
        """Add messages at the end (older ones beyond the cap are dropped)."""
        ...
