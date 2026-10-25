"""Which AI task generates each kind of Studio output."""

from typing import Final

from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.shared.ai_tasks import AiTask

ARTIFACT_TASKS: Final[dict[ArtifactKind, AiTask]] = {
    ArtifactKind.REPORT: AiTask.STUDIO_REPORT,
    ArtifactKind.MIND_MAP: AiTask.STUDIO_MIND_MAP,
    ArtifactKind.FLASHCARDS: AiTask.STUDIO_FLASHCARDS,
    ArtifactKind.QUIZ: AiTask.STUDIO_QUIZ,
    ArtifactKind.DATA_TABLE: AiTask.STUDIO_DATA_TABLE,
    ArtifactKind.SLIDES: AiTask.STUDIO_SLIDES,
    ArtifactKind.INFOGRAPHIC: AiTask.STUDIO_INFOGRAPHIC,
    ArtifactKind.EXERCISE: AiTask.STUDIO_EXERCISE,
    ArtifactKind.COURSE_PLAN: AiTask.LMS_AUTHORING,
    ArtifactKind.LESSON_DRAFT: AiTask.LMS_AUTHORING,
}


def task_for_kind(kind: ArtifactKind) -> AiTask:
    """The task that writes a kind of output (audio overview is never generated)."""
    task = ARTIFACT_TASKS.get(kind)
    if task is None:
        raise InvalidOptionsError(
            params={"kind": kind.value}, support_details="unsupported kind"
        )
    return task
