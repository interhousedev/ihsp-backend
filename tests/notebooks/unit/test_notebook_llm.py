"""NB-8, NB-20: notebooks ask for AI tasks; the settings choose model and options."""

from typing import Any

from app.modules.notebooks.application.artifact_tasks import (
    ARTIFACT_TASKS,
    task_for_kind,
)
from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.artifacts.registry import supported_kinds
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.settings import Settings
from app.settings_ai import AiSettings, AiTaskSettings
from app.shared.ai_tasks import NOTEBOOK_TASKS, AiTask
from app.shared.contracts.ai import LlmTuning
from tests.fakes.notebooks.llm import ScriptedLlm

import pytest

SCHEMA: dict[str, Any] = {"type": "object"}
MESSAGES = [{"role": "user", "content": "hi"}]


def llm_with(
    settings: Settings, **tasks: AiTaskSettings
) -> tuple[NotebookLlm, ScriptedLlm]:
    """A notebook LLM over a scripted gateway; keys are task values."""
    ai = AiSettings(tasks={AiTask(key): value for key, value in tasks.items()})
    gateway = ScriptedLlm()
    return NotebookLlm(gateway, settings.model_copy(update={"ai": ai})), gateway


def test_every_supported_kind_has_a_studio_task() -> None:
    """A new Studio kind must be added to the catalog before it can be generated."""
    assert supported_kinds() == set(ARTIFACT_TASKS)
    for kind in supported_kinds():
        # Course plans and lesson drafts run on the LMS authoring task.
        if kind.is_course_kind:
            assert task_for_kind(kind) is AiTask.LMS_AUTHORING
            continue
        assert task_for_kind(kind) in NOTEBOOK_TASKS
        assert task_for_kind(kind).value.startswith("studio_")


def test_the_audio_overview_has_no_task() -> None:
    """It is reserved and never generated."""
    with pytest.raises(InvalidOptionsError):
        task_for_kind(ArtifactKind.AUDIO_OVERVIEW)


async def test_json_calls_use_the_model_and_options_of_their_task(
    settings: Settings,
) -> None:
    """Quiz and slides can run on different models with different tuning."""
    llm, gateway = llm_with(
        settings,
        studio_quiz=AiTaskSettings(model="x/quiz", temperature=0.4),
        studio_slides=AiTaskSettings(model="x/slides", fallbacks=("x/backup",)),
    )

    gateway.queue_json({"ok": True})
    gateway.queue_json({"ok": True})
    for task in (AiTask.STUDIO_QUIZ, AiTask.STUDIO_SLIDES):
        done = await llm.json(
            task=task,
            system="s",
            messages=MESSAGES,
            schema_name="n",
            schema=SCHEMA,
            max_tokens=100,
        )
        assert done.model == gateway.json_requests[-1]["model"]

    quiz, slides = gateway.json_requests
    assert (quiz["model"], slides["model"]) == ("x/quiz", "x/slides")
    assert quiz["tuning"] == LlmTuning(temperature=0.4)
    assert slides["tuning"] == LlmTuning(temperature=0.2, fallbacks=("x/backup",))
    for request in (quiz, slides):
        assert request["provider"] == {
            "require_parameters": True,
            "data_collection": "deny",
        }


async def test_chat_calls_use_the_chat_task_by_default(settings: Settings) -> None:
    """text() and stream() are NOTEBOOK_CHAT unless a task is passed."""
    llm, gateway = llm_with(
        settings,
        notebook_chat=AiTaskSettings(model="x/chat", reasoning_effort="low"),
    )

    await llm.text(system="s", messages=MESSAGES, max_tokens=50)
    _ = [
        item async for item in llm.stream(system="s", messages=MESSAGES, max_tokens=50)
    ]

    sent = [*gateway.text_requests, *gateway.stream_requests]
    assert [request["model"] for request in sent] == ["x/chat", "x/chat"]
    assert all(request["provider"] == {"data_collection": "deny"} for request in sent)
    assert all(request["tuning"].reasoning_effort == "low" for request in sent)
    assert llm.model() == "x/chat"


def test_the_output_limit_of_a_task_replaces_the_call_sites_size(
    settings: Settings,
) -> None:
    """Without the setting the planned size stays."""
    llm, _ = llm_with(settings, studio_report=AiTaskSettings(max_output_tokens=900))

    assert llm.max_tokens(AiTask.STUDIO_REPORT, 6000) == 900
    assert llm.max_tokens(AiTask.STUDIO_QUIZ, 6000) == 6000


def test_only_anthropic_models_get_the_cache_mark(settings: Settings) -> None:
    """The context message follows the model of the task it is built for."""
    llm, _ = llm_with(settings, studio_mind_map=AiTaskSettings(model="x/other"))

    cached = llm.context_message("<sources/>", AiTask.STUDIO_QUIZ)
    plain = llm.context_message("<sources/>", AiTask.STUDIO_MIND_MAP)

    assert cached["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert plain["content"] == "<sources/>"
