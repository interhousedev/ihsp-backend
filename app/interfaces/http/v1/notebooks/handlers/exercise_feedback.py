"""POST /v1/notebooks/{id}/artifacts/{aid}/exercise-feedback."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import (
    ExerciseFeedbackBody,
    ExerciseFeedbackResponse,
)


async def exercise_feedback(
    notebook_id: UUID,
    artifact_id: UUID,
    body: ExerciseFeedbackBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> ExerciseFeedbackResponse:
    """AI feedback on an essay of an exercise against its rubric (charged)."""
    feedback = await notebooks.exercise_feedback.execute(
        actor,
        notebook_id,
        artifact_id,
        question_id=body.question_id,
        answer=body.answer,
    )
    return ExerciseFeedbackResponse.model_validate(feedback)
