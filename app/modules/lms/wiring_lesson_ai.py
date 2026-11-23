"""Wiring of the lesson AI: the step tutor and video check suggestions."""

from dataclasses import dataclass

from app.modules.lms.application.authoring.suggest_video_checks import (
    SuggestVideoChecks,
)
from app.modules.lms.application.learning.ask_tutor import AskTutor
from app.modules.lms.infrastructure.authoring.uow import SqlAuthoringUnitOfWork
from app.modules.lms.infrastructure.tutor_history import RedisTutorHistory
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.modules.lms.ports.lesson_ai import LessonModel
from app.modules.lms.wiring_learning import LearningServices
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class LessonAiServices:
    """`container.lms_lesson_ai`: built only in processes with the AI module."""

    ask_tutor: AskTutor
    suggest_video_checks: SuggestVideoChecks


def build_lesson_ai(
    deps: ModuleDeps, *, learning: LearningServices, model: LessonModel
) -> LessonAiServices:
    """Build the use cases; learning access reuses the source reader's gate."""

    def authoring_uow() -> AuthoringUnitOfWork:
        return SqlAuthoringUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    limits = deps.effective_limits
    reader = learning.source_reader
    return LessonAiServices(
        ask_tutor=AskTutor(
            reader.uow_factory,
            reader.gate,
            model,
            RedisTutorHistory(deps.redis),
            limits,
            deps.rate_limiter,
            deps.clock,
        ),
        suggest_video_checks=SuggestVideoChecks(
            authoring_uow, model, limits, deps.rate_limiter
        ),
    )
