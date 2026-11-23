"""The "Ask about this lesson" tutor of a step (AI task LMS_TUTOR).

The model reads the student's copy of the step (`export_text` without answers) and
the outline titles: it cannot reveal an answer it never sees (LMS-17). Access is
the same as reading the step: enrolled, audience gate open, the course tutor on.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.revision_loading import load_revision
from app.modules.lms.application.learning.step_context import load_live_step
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.learning.errors import NotEnrolledError
from app.modules.lms.domain.learning.lesson_ai import (
    TUTOR_MAX_TOKENS,
    TUTOR_MESSAGE_MAX_CHARS,
    TUTOR_SCHEMA_NAME,
    TutorReply,
    TutorTurn,
    tutor_messages,
    tutor_system,
)
from app.modules.lms.domain.learning.source_text import export_text
from app.modules.lms.domain.learning.tutor_errors import (
    TutorDailyLimitError,
    TutorDisabledError,
)
from app.modules.lms.ports.lesson_ai import LessonModel, TutorHistory, TutorMessage
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.clock import Clock, local_today
from app.shared.limits import LimitsProvider
from app.shared.rate_limit import RateLimiter

DAY_SECONDS = 86_400


@dataclass(frozen=True, slots=True)
class TutorConversation:
    """The conversation and the questions left today (None: no cap)."""

    messages: list[TutorMessage]
    remaining_today: int | None


@dataclass(frozen=True, slots=True)
class _Lesson:
    course_title: str
    outline: list[str]
    step_title: str
    text: str


class AskTutor:
    """Read and continue the tutor conversation of a step."""

    def __init__(
        self,
        uow_factory: UowFactory,
        gate: AudienceGate,
        model: LessonModel,
        history: TutorHistory,
        limits: LimitsProvider,
        limiter: RateLimiter,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.gate = gate
        self.model = model
        self.history = history
        self.limits = limits
        self.limiter = limiter
        self.clock = clock

    async def conversation(self, actor: Actor, step_id: UUID) -> TutorConversation:
        """Return the stored conversation of the step."""
        await self._lesson(actor, step_id)
        messages = await self.history.read(actor.user_id, step_id)
        limit = await self._limit(actor)
        used = await self.limiter.count(self._key(actor)) if limit is not None else 0
        return TutorConversation(messages, _left(limit, used))

    async def ask(
        self, actor: Actor, step_id: UUID, message: str, language: str
    ) -> TutorConversation:
        """Answer the student's message and store both messages."""
        text = message.strip()
        if not text or len(text) > TUTOR_MESSAGE_MAX_CHARS:
            raise ValidationFailedError(params={"field": "message"})
        lesson = await self._lesson(actor, step_id)
        limit = await self._limit(actor)
        used = 0
        if limit is not None:
            try:
                used = await self.limiter.hit(
                    self._key(actor), limit=limit, window_seconds=DAY_SECONDS
                )
            except RateLimitedError as error:
                raise TutorDailyLimitError(params=error.params) from error
        earlier = await self.history.read(actor.user_id, step_id)
        turns = [TutorTurn(m.role, m.text) for m in earlier]
        turns.append(TutorTurn("student", text))
        data = await self.model.complete_json(
            task="lms_tutor",
            system=tutor_system(
                language=language,
                course_title=lesson.course_title,
                outline=lesson.outline,
                step_title=lesson.step_title,
                lesson_text=lesson.text,
            ),
            messages=tutor_messages(turns),
            schema_name=TUTOR_SCHEMA_NAME,
            schema=to_strict_schema(TutorReply),
            max_tokens=TUTOR_MAX_TOKENS,
        )
        reply = TutorReply.model_validate(data).reply.strip()
        now: datetime = self.clock.now()
        added = [TutorMessage("student", text, now), TutorMessage("tutor", reply, now)]
        await self.history.append(actor.user_id, step_id, added)
        return TutorConversation([*earlier, *added], _left(limit, used))

    async def _lesson(self, actor: Actor, step_id: UUID) -> _Lesson:
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            course = context.course
            if await uow.enrollments.get(course.id, actor.user_id) is None:
                raise NotEnrolledError(params={"course_id": str(course.id)})
            if not course.tutor_enabled:
                raise TutorDisabledError(params={"course_id": str(course.id)})
            await self.gate.require_step(uow, actor, course.id, step_id)
            revision = await load_revision(uow, context.live_step.revision_id)
        text, _ = export_text(revision.content)
        outline = [
            step.title
            for section in context.version.manifest.sections
            for step in section.steps
        ]
        return _Lesson(course.title, outline, context.live_step.title, text)

    async def _limit(self, actor: Actor) -> int | None:
        limits = await self.limits.for_actor(actor)
        value: int | None = limits.ai_lms_tutor_per_day_student
        return value

    def _key(self, actor: Actor) -> str:
        return f"lms_tutor:{actor.user_id}:{local_today(self.clock).isoformat()}"


def _left(limit: int | None, used: int) -> int | None:
    return None if limit is None else max(limit - used, 0)
