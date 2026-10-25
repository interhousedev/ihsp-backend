"""Use case: AI feedback on a free response of an exercise (the student asks for it).

A cheap model (AI task EXERCISE_FEEDBACK) assesses the answer against the question's
rubric. The call is charged to the notebook budget and refused when notebook AI is
revoked (scope ``notebooks``), like every Studio call.
"""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact, load_notebook
from app.modules.notebooks.application.artifact_engine import require_ready
from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.exercise.answers import word_count
from app.modules.notebooks.domain.exercise.feedback import (
    ANSWER_MAX_CHARS,
    ANSWER_MIN_WORDS,
    MAX_TOKENS,
    SCHEMA_NAME,
    SYSTEM,
    clean_feedback,
    feedback_message,
    feedback_schema,
)
from app.modules.notebooks.domain.language import resolve_language
from app.modules.notebooks.domain.tokens import estimate_cost
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError

from pydantic import ValidationError


def _invalid(detail: str) -> InvalidOptionsError:
    return InvalidOptionsError(params={"details": [detail]}, support_details=detail)


def find_essay(content: dict[str, Any], question_id: str) -> tuple[dict[str, Any], str]:
    """The free response question and its stimulus, or `InvalidOptionsError`."""
    for section in content.get("sections") or []:
        for question in section.get("questions") or []:
            if question.get("id") == question_id:
                if question.get("type") != "free_response":
                    raise _invalid("question_id: not a free response question")
                return question, str(section.get("stimulus") or "")
    raise _invalid("question_id: no such question")


class ExerciseFeedback:
    """Assesses one essay or free response against its rubric."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        llm: NotebookLlm,
        budget: NotebookBudget,
        locale: LocaleResolver,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.llm = llm
        self.budget = budget
        self.locale = locale

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        *,
        question_id: str,
        answer: str,
    ) -> dict[str, Any]:
        """Return ``{overall, estimated_band, criteria, strengths, improvements}``.

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            InvalidOptionsError: Not an exercise, not a free response, or the answer
                is too short or too long.
            ArtifactNotReadyError: The output is not ready.
            AiAccessRevokedError: Notebook AI is revoked for the student.
            LimitReachedError: The weighted-token budget is used up.
        """
        text = answer.strip()
        if word_count(text) < ANSWER_MIN_WORDS:
            raise _invalid(f"answer: at least {ANSWER_MIN_WORDS} words")
        if len(text) > ANSWER_MAX_CHARS:
            raise _invalid(f"answer: at most {ANSWER_MAX_CHARS} characters")
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id, write=False)
            artifact = await load_artifact(
                uow, actor.user_id, notebook_id, artifact_id, write=False
            )
        content = require_ready(artifact, ArtifactKind.EXERCISE)
        question, stimulus = find_essay(content, question_id)
        requested = (artifact.options or {}).get("language")
        language = resolve_language(
            requested, await self.locale.locale_of(actor.user_id)
        )
        message = feedback_message(
            exam=str(content.get("exam") or "generic"),
            question=question,
            stimulus=stimulus,
            answer=text,
            language=language,
        )
        max_tokens = self.llm.max_tokens(AiTask.EXERCISE_FEEDBACK, MAX_TOKENS)
        pool = self.budget.pool(notebook.is_course_workspace)
        await pool.require(
            actor.user_id, estimate_cost(len(SYSTEM) + len(message), max_tokens)
        )
        done = await self.llm.json(
            task=AiTask.EXERCISE_FEEDBACK,
            system=SYSTEM,
            messages=[{"role": "user", "content": message}],
            schema_name=SCHEMA_NAME,
            schema=feedback_schema(),
            max_tokens=max_tokens,
        )
        await pool.add(actor.user_id, done.usage.weighted)
        try:
            return clean_feedback(done.data)
        except ValidationError as exc:
            raise AiInvalidOutputError(support_details="exercise feedback") from exc
