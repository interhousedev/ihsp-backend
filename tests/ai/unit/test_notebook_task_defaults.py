"""The built-in profile of the notebook tasks: Haiku 5.5 with reasoning off."""

from app.settings_ai import AiDefaults, AiSettings, AiTaskSettings
from app.shared.ai_tasks import NOTEBOOK_MODEL, AiTask

import pytest

STRUCTURED = [
    AiTask.SOURCE_GUIDE,
    AiTask.NOTEBOOK_SUMMARY,
    AiTask.SOURCE_LABELS,
    AiTask.STUDIO_REPORT,
    AiTask.STUDIO_MIND_MAP,
    AiTask.STUDIO_FLASHCARDS,
    AiTask.STUDIO_QUIZ,
    AiTask.STUDIO_DATA_TABLE,
    AiTask.STUDIO_SLIDES,
    AiTask.STUDIO_SLIDES_REVISE,
    AiTask.STUDIO_INFOGRAPHIC,
]


@pytest.mark.parametrize("task", STRUCTURED)
def test_structured_notebook_tasks_ship_with_the_notebook_model(task: AiTask) -> None:
    """Studio, guides, summaries and labels: Haiku 5.5, private, no reasoning."""
    profile = AiSettings().profile(task)

    assert profile.model == NOTEBOOK_MODEL == "anthropic/claude-haiku-5.5"
    assert profile.reasoning_effort == "none"
    assert profile.data_collection == "deny"


def test_notebook_chat_keeps_the_default_model_without_reasoning() -> None:
    """The chat was not part of the Studio bench: the default model, reasoning off."""
    profile = AiSettings().profile(AiTask.NOTEBOOK_CHAT)

    assert profile.model == AiDefaults().model
    assert profile.reasoning_effort == "none"


def test_settings_override_the_built_in_reasoning_and_model() -> None:
    """`AI__TASKS__STUDIO_QUIZ__*` beats the task's built-in values."""
    settings = AiSettings(
        tasks={
            AiTask.STUDIO_QUIZ: AiTaskSettings(model="x/quiz", reasoning_effort="low")
        }
    )

    profile = settings.profile(AiTask.STUDIO_QUIZ)

    assert profile.model == "x/quiz" and profile.reasoning_effort == "low"
    assert settings.profile(AiTask.STUDIO_FLASHCARDS).reasoning_effort == "none"


def test_the_default_reasoning_applies_only_to_tasks_without_their_own() -> None:
    """`AI__DEFAULT__REASONING_EFFORT` does not switch notebook reasoning back on."""
    settings = AiSettings(default=AiDefaults(reasoning_effort="high"))

    assert settings.profile(AiTask.STUDENT_CHAT).reasoning_effort == "high"
    assert settings.profile(AiTask.STUDIO_QUIZ).reasoning_effort == "none"
