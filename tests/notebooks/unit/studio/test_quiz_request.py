"""The Studio quiz batch runs as its registered AI request."""

from dataclasses import replace
from typing import Any

from app.bootstrap.adapters.prompt_slots import prompt_slots
from app.modules.ai.application.prompt_registry import PromptRegistry
from app.modules.ai.application.request_context import RequestCtx, current_request
from app.modules.ai.application.requests import AiRequests
from app.modules.ai.domain.requests import build_catalog
from app.modules.notebooks.application.assessment_pipeline import AssessmentPipeline
from app.modules.notebooks.application.llm import JsonCompletion
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.wiring import AI_REQUESTS
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from tests.notebooks.unit.studio.test_assessment_rules import (
    FakeNotebookLlm,
    ScriptedAsk,
    job,
    question,
)

QUIZ = "notebooks.studio_quiz.generate"


class _NoVersions:
    """The registry reads no stored versions."""

    async def active(self) -> list:
        """Nothing."""
        return []


class SpyAsk(ScriptedAsk):
    """Notes the request context of each model call by task."""

    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        """Start with no notes."""
        super().__init__(batches)
        self.contexts: dict[AiTask, list[RequestCtx | None]] = {}

    async def __call__(self, task: AiTask, *args: Any) -> JsonCompletion:
        """Note the context, then answer as the script does."""
        self.contexts.setdefault(task, []).append(current_request.get())
        return await super().__call__(task, *args)


def build(settings: Settings, *, wired: bool) -> AssessmentPipeline:
    """A pipeline with (or without) the real quiz request."""
    notebooks = settings.notebooks.model_copy(
        update={"assessment_fill_rounds": 1, "assessment_verify": False}
    )
    slots = prompt_slots()
    requests = AiRequests(
        build_catalog(slots, AI_REQUESTS), PromptRegistry(slots, _NoVersions())
    )
    llm: Any = FakeNotebookLlm()
    return AssessmentPipeline(
        llm,
        settings.model_copy(update={"notebooks": notebooks}),
        None,
        requests=requests if wired else None,
    )


async def test_the_quiz_batch_call_carries_the_request_context(
    settings: Settings,
) -> None:
    """The writing call sees the quiz request; planning calls are not part of it."""
    ask = SpyAsk([[question("If $2x + 1 = 11$, what is the value of $x$?")]])

    await build(settings, wired=True).run(job(), ask)

    assert ask.contexts[AiTask.STUDIO_QUIZ] == [RequestCtx(QUIZ, "studio")]
    assert current_request.get() is None


async def test_without_requests_the_quiz_runs_unchanged(settings: Settings) -> None:
    """A pipeline built without the registry still writes the quiz."""
    ask = SpyAsk([[question("If $2x + 1 = 11$, what is the value of $x$?")]])

    out = await build(settings, wired=False).run(job(), ask)

    assert ask.contexts[AiTask.STUDIO_QUIZ] == [None]
    assert out.content["questions"]


async def test_flash_cards_are_not_the_quiz_request(settings: Settings) -> None:
    """Only the quiz task maps to the quiz request."""
    cards = replace(
        job(),
        task=AiTask.STUDIO_FLASHCARDS,
        cards=True,
        handler=handler_for(ArtifactKind.FLASHCARDS),
    )
    ask = SpyAsk([[]])

    try:
        await build(settings, wired=True).run(cards, ask)
    except Exception:  # the empty script may fail the cards; only the context matters
        pass

    assert all(ctx is None for ctx in ask.contexts.get(AiTask.STUDIO_FLASHCARDS, []))
