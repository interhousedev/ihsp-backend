"""Pause-and-predict checks and recap cards from a video transcript (LMS_VIDEO_CHECKS).

Nothing is saved: the editor shows the suggestions, the author edits them and saves
the step draft as usual (interactive video interactions, a flash card block).
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.domain.authoring.errors import StepNotFoundError
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.domain.learning.lesson_ai import (
    CHECKS_MAX_TOKENS,
    CHECKS_SCHEMA_NAME,
    CHECKS_SYSTEM,
    INTERVAL_SEC,
    CheckSuggestion,
    VideoChecksDraft,
    checks_message,
    clean_checks,
    parse_transcript,
    video_parts,
)
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.modules.lms.ports.lesson_ai import LessonModel
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.limits import LimitsProvider
from app.shared.rate_limit import RateLimiter


@dataclass(frozen=True, slots=True)
class VideoChecksSuggestion:
    """Checks at their pause times and recap cards (front, back)."""

    checks: list[CheckSuggestion]
    cards: list[tuple[str, str]]


class SuggestVideoChecks:
    """Suggest checks for a video block of a step the actor may edit."""

    def __init__(
        self,
        uow_factory: Callable[[], AuthoringUnitOfWork],
        model: LessonModel,
        limits: LimitsProvider,
        limiter: RateLimiter,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.model = model
        self.limits = limits
        self.limiter = limiter

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        step_id: UUID,
        *,
        transcript: str,
        duration_sec: float | None,
        language: str,
        title: str,
    ) -> VideoChecksSuggestion:
        """Return the suggestions; an empty transcript is a validation error."""
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            if step.course_id != course_id:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            (await access_to(uow, actor, course_id)).require(EDIT)
        parts = video_parts(
            parse_transcript(transcript, duration_sec), duration_sec, INTERVAL_SEC
        )
        if not parts:
            raise ValidationFailedError(params={"field": "transcript"})
        limits = await self.limits.for_actor(actor)
        await self.limiter.hit(
            f"lms_video_checks:{actor.user_id}",
            limit=limits.values.lms_ai_chat_per_minute,
            window_seconds=60,
        )
        data = await self.model.complete_json(
            task="lms_video_checks",
            system=CHECKS_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": checks_message(
                        title=title, language=language, parts=parts
                    ),
                }
            ],
            schema_name=CHECKS_SCHEMA_NAME,
            schema=to_strict_schema(VideoChecksDraft),
            max_tokens=CHECKS_MAX_TOKENS,
        )
        checks, cards = clean_checks(VideoChecksDraft.model_validate(data), parts)
        return VideoChecksSuggestion(checks, cards)
