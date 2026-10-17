"""AI task catalog: resolver fallbacks, overrides, environment, deprecated aliases."""

from typing import Any

from app.settings import Settings
from app.settings_ai import DEFAULT_MODEL, AiSettings, AiTaskSettings
from app.settings_loader import SettingsError, load_settings
from app.shared.ai_tasks import (
    COMPACT_MODEL,
    LIGHT_NOTEBOOK_TASKS,
    NOTEBOOK_TASKS,
    SMART_BUDGET_WEIGHT,
    SMART_MODEL,
    TASK_SPECS,
    AiTask,
    ModelProfile,
)

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

STUDIO = [task for task in AiTask if task.value.startswith("studio_")]


def tasks(**overrides: AiTaskSettings) -> AiSettings:
    """AI settings with task overrides, keyed by task value."""
    return AiSettings(tasks={AiTask(key): value for key, value in overrides.items()})


def test_every_task_has_a_spec_and_resolves_to_a_profile() -> None:
    """The catalog and the specs never drift apart."""
    assert set(TASK_SPECS) == set(AiTask)
    ai = AiSettings()

    profiles = [ai.profile(task) for task in AiTask]

    assert all(isinstance(profile, ModelProfile) for profile in profiles)
    assert [profile.task for profile in profiles] == list(AiTask)


def test_the_catalog_lists_the_places_that_call_a_model() -> None:
    """The names the environment variables use."""
    names = {task.value for task in AiTask}

    assert {
        "student_chat",
        "student_chat_smart",
        "admin_chat",
        "chat_summary",
        "context_compact",
        "notebook_chat",
        "source_guide",
        "notebook_summary",
        "source_labels",
        "studio_report",
        "studio_mind_map",
        "studio_flashcards",
        "studio_quiz",
        "studio_data_table",
        "studio_slides",
        "studio_slides_revise",
        "studio_infographic",
        "lms_authoring",
        "web_search",
        "discover",
        "subject_translate",
        "embedding",
        "retrieval_plan",
        "query_decompose",
        "studio_faithfulness",
        "web_material_triage",
        "media_describe",
    } == names


def test_every_task_falls_back_to_the_default_model() -> None:
    """Nothing set: one default model, temperature 0.2, weight 1, no fallbacks."""
    ai = AiSettings()

    for task in AiTask:
        if TASK_SPECS[task].model is not None:  # smart tier, search, Studio
            continue
        profile = ai.profile(task)
        assert profile.model == DEFAULT_MODEL
        assert profile.temperature == 0.2
        assert profile.budget_weight == 1
        assert profile.fallbacks == ()
        assert profile.max_output_tokens is None
        assert profile.reasoning_effort == (TASK_SPECS[task].reasoning_effort or "none")


def test_web_search_has_no_model_and_discover_uses_the_default_one() -> None:
    """Exa runs the chat search (no model call); Discover's plan and ranking use the
    default model, which takes no provider that trains on the data."""
    ai = AiSettings()

    assert TASK_SPECS[AiTask.WEB_SEARCH].model is None
    profile = ai.profile(AiTask.DISCOVER)
    assert profile.model == DEFAULT_MODEL
    assert profile.provider() == {"data_collection": "deny"}
    assert profile.budget_weight == 1


def test_a_discover_override_beats_the_default_model() -> None:
    """AI__TASKS__DISCOVER__MODEL wins over the default model."""
    ai = tasks(discover=AiTaskSettings(model="x/search"))

    assert ai.profile(AiTask.DISCOVER).model == "x/search"


def test_the_default_changes_every_task_without_its_own_value() -> None:
    """AI__DEFAULT__* is what the tasks inherit."""
    ai = AiSettings(
        default={  # type: ignore[arg-type]
            "model": "x/default",
            "temperature": 0.9,
            "max_output_tokens": 999,
            "reasoning_effort": "low",
            "fallbacks": ["x/fallback"],
            "budget_weight": 3,
        }
    )

    for task in (AiTask.STUDENT_CHAT, AiTask.ADMIN_CHAT, AiTask.LMS_AUTHORING):
        profile = ai.profile(task)
        assert (profile.model, profile.temperature) == ("x/default", 0.9)
        assert profile.max_output_tokens == 999
        assert profile.reasoning_effort == "low"
        assert profile.fallbacks == ("x/fallback",)
        assert profile.budget_weight == 3


def test_a_task_override_beats_the_default_and_leaves_other_tasks_alone() -> None:
    """AI__TASKS__<TASK>__* wins for its task only."""
    ai = tasks(
        studio_quiz=AiTaskSettings(
            model="x/quiz",
            temperature=0.7,
            max_output_tokens=1234,
            reasoning_effort="high",
            fallbacks=("x/one", "x/two"),
            budget_weight=2,
            provider_order=("anthropic",),
        )
    )

    quiz = ai.profile(AiTask.STUDIO_QUIZ)
    other = ai.profile(AiTask.ADMIN_CHAT)

    assert (quiz.model, quiz.temperature, quiz.max_output_tokens) == (
        "x/quiz",
        0.7,
        1234,
    )
    assert quiz.reasoning_effort == "high"
    assert quiz.fallbacks == ("x/one", "x/two")
    assert quiz.budget_weight == 2
    assert quiz.provider_order == ("anthropic",)
    assert other.model == DEFAULT_MODEL and other.temperature == 0.2


def test_a_task_override_can_set_one_field_and_inherit_the_rest() -> None:
    """An empty override field falls through to the default."""
    ai = AiSettings(
        default={"model": "x/default", "temperature": 0.5},  # type: ignore[arg-type]
        tasks={AiTask.ADMIN_CHAT: AiTaskSettings(temperature=0.1)},
    )

    profile = ai.profile(AiTask.ADMIN_CHAT)

    assert (profile.model, profile.temperature) == ("x/default", 0.1)


def test_the_default_model_is_haiku_55_and_chats_do_not_reason() -> None:
    """Claude 5.5 reasons inside the answer budget by default: chats switch it off."""
    ai = AiSettings()

    for task in (
        AiTask.STUDENT_CHAT,
        AiTask.ADMIN_CHAT,
        AiTask.CHAT_SUMMARY,
        AiTask.LMS_AUTHORING,
    ):
        profile = ai.profile(task)
        assert profile.model == "anthropic/claude-haiku-5.5" == DEFAULT_MODEL
        assert profile.reasoning_effort == "none"


def test_the_smart_tier_ships_with_gemini_at_low_effort_and_weight_eight() -> None:
    """The built-in value of the task beats the default, an override beats both."""
    ai = AiSettings(default={"model": "x/default"})  # type: ignore[arg-type]

    smart = ai.profile(AiTask.STUDENT_CHAT_SMART)
    fast = ai.profile(AiTask.STUDENT_CHAT)

    assert smart.model == SMART_MODEL == "google/gemini-3.8-flash"
    assert smart.budget_weight == SMART_BUDGET_WEIGHT == 8
    assert smart.reasoning_effort == "low"
    assert fast.reasoning_effort == "none"
    assert fast.model == "x/default" and fast.budget_weight == 1
    changed = tasks(
        student_chat_smart=AiTaskSettings(model="x/smart", budget_weight=2)
    ).profile(AiTask.STUDENT_CHAT_SMART)
    assert (changed.model, changed.budget_weight) == ("x/smart", 2)


def test_notebook_tasks_refuse_data_collection_unless_a_task_allows_it() -> None:
    """Student documents go only to providers that do not keep or train on them."""
    ai = tasks(studio_quiz=AiTaskSettings(data_collection="allow"))

    for task in NOTEBOOK_TASKS - {AiTask.STUDIO_QUIZ}:
        assert ai.profile(task).provider() == {"data_collection": "deny"}
    assert ai.profile(AiTask.STUDIO_QUIZ).provider() == {"data_collection": "allow"}
    assert ai.profile(AiTask.STUDENT_CHAT).provider() is None


def test_the_provider_object_carries_order_and_call_specific_keys() -> None:
    """OpenRouter `provider`: data_collection, order and what the caller adds."""
    profile = tasks(
        notebook_chat=AiTaskSettings(provider_order=("anthropic", "google-vertex"))
    ).profile(AiTask.NOTEBOOK_CHAT)

    assert profile.provider(require_parameters=True) == {
        "require_parameters": True,
        "data_collection": "deny",
        "order": ["anthropic", "google-vertex"],
    }


def test_the_output_limit_replaces_the_call_sites_own_size_only_when_set() -> None:
    """`output_tokens(default)` is the setting or the caller's default."""
    plain = AiSettings().profile(AiTask.NOTEBOOK_CHAT)
    capped = tasks(notebook_chat=AiTaskSettings(max_output_tokens=300)).profile(
        AiTask.NOTEBOOK_CHAT
    )

    assert plain.output_tokens(4096) == 4096
    assert capped.output_tokens(4096) == 300


def test_the_profile_gives_the_gateway_its_tuning() -> None:
    """Temperature, reasoning effort and fallbacks travel as `LlmTuning`."""
    profile = tasks(
        admin_chat=AiTaskSettings(reasoning_effort="medium", fallbacks=("x/b",))
    ).profile(AiTask.ADMIN_CHAT)

    tuning = profile.tuning

    assert tuning.temperature == 0.2
    assert tuning.reasoning_effort == "medium"
    assert tuning.fallbacks == ("x/b",)


@pytest.mark.parametrize(
    "field, value",
    [
        ("temperature", 3),
        ("temperature", -1),
        ("max_output_tokens", 0),
        ("budget_weight", 0),
        ("reasoning_effort", "extreme"),
        ("data_collection", "maybe"),
        ("model", ""),
    ],
)
def test_bad_override_values_are_refused(field: str, value: Any) -> None:
    """The range and choices are checked when the settings load."""
    with pytest.raises(ValidationError):
        AiTaskSettings(**{field: value})


# - - - environment - - -


def test_the_environment_sets_the_default_and_the_task_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IHSP_AI__DEFAULT__* and IHSP_AI__TASKS__<TASK>__*, lists comma separated."""
    monkeypatch.setenv("IHSP_AI__DEFAULT__MODEL", "x/default")
    monkeypatch.setenv("IHSP_AI__DEFAULT__TEMPERATURE", "0.3")
    monkeypatch.setenv("IHSP_AI__TASKS__STUDIO_QUIZ__MODEL", "x/quiz")
    monkeypatch.setenv("IHSP_AI__TASKS__STUDIO_QUIZ__FALLBACKS", "x/a, x/b")
    monkeypatch.setenv("IHSP_AI__TASKS__STUDIO_SLIDES__MAX_OUTPUT_TOKENS", "16000")
    monkeypatch.setenv("IHSP_AI__TASKS__STUDENT_CHAT_SMART__BUDGET_WEIGHT", "2")

    settings = Settings()

    quiz = settings.ai_profile(AiTask.STUDIO_QUIZ)
    assert (quiz.model, quiz.temperature) == ("x/quiz", 0.3)
    assert quiz.fallbacks == ("x/a", "x/b")
    assert settings.ai_profile(AiTask.STUDIO_SLIDES).max_output_tokens == 16000
    assert settings.ai_profile(AiTask.ADMIN_CHAT).model == "x/default"
    assert settings.ai_profile(AiTask.STUDENT_CHAT_SMART).budget_weight == 2


def test_empty_task_variables_mean_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose passes `IHSP_AI__TASKS__X__MODEL=` when .env.prod leaves it out."""
    monkeypatch.setenv("IHSP_AI__TASKS__STUDENT_CHAT__MODEL", "")
    monkeypatch.setenv("IHSP_AI__DEFAULT__MAX_OUTPUT_TOKENS", "")

    settings = Settings()

    assert settings.ai.tasks == {}
    assert settings.ai_profile(AiTask.STUDENT_CHAT).model == DEFAULT_MODEL
    assert settings.ai.default.max_output_tokens is None


def test_a_misspelled_task_stops_the_start_and_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error lists the variable, not a pydantic path."""
    monkeypatch.setenv("IHSP_AI__TASKS__STUDIO_QUIZZ__MODEL", "x/y")
    monkeypatch.setenv("IHSP_AI__TASKS__STUDIO_QUIZ__TEMPERATURE", "hot")

    with pytest.raises(SettingsError) as caught:
        load_settings()

    message = str(caught.value)
    assert "IHSP_AI__TASKS__STUDIO_QUIZZ" in message
    assert "IHSP_AI__TASKS__STUDIO_QUIZ__TEMPERATURE" in message
    assert "(2)" in message


# - - - deprecated aliases - - -


def deprecated(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Settings built with old variables; their warnings are not asserted here."""
    for name, value in env.items():
        monkeypatch.setenv(f"IHSP_{name}", value)
    with capture_logs():
        return Settings()


def test_the_old_model_variables_map_onto_the_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPENROUTER__MODEL_STUDENT, _STUDENT_SMART, _ADMIN keep working."""
    settings = deprecated(
        monkeypatch,
        OPENROUTER__MODEL_STUDENT="old/student",
        OPENROUTER__MODEL_STUDENT_SMART="old/smart",
        OPENROUTER__MODEL_ADMIN="old/admin",
    )

    assert settings.ai_profile(AiTask.STUDENT_CHAT).model == "old/student"
    assert settings.ai_profile(AiTask.STUDENT_CHAT_SMART).model == "old/smart"
    assert settings.ai_profile(AiTask.ADMIN_CHAT).model == "old/admin"
    assert settings.ai_profile(AiTask.CHAT_SUMMARY).model == DEFAULT_MODEL


def test_the_old_notebook_model_covers_chat_and_studio_and_light_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MODEL_NOTEBOOK alone: every notebook task, the light ones included."""
    settings = deprecated(monkeypatch, OPENROUTER__MODEL_NOTEBOOK="old/notebook")

    for task in NOTEBOOK_TASKS:
        assert settings.ai_profile(task).model == "old/notebook"
    assert settings.ai_profile(AiTask.STUDENT_CHAT).model == DEFAULT_MODEL


def test_the_old_light_model_covers_guides_and_summaries_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MODEL_NOTEBOOK_LIGHT: source guide and notebook summary."""
    settings = deprecated(
        monkeypatch,
        OPENROUTER__MODEL_NOTEBOOK="old/notebook",
        OPENROUTER__MODEL_NOTEBOOK_LIGHT="old/light",
    )

    assert settings.ai_profile(AiTask.SOURCE_GUIDE).model == "old/light"
    assert settings.ai_profile(AiTask.NOTEBOOK_SUMMARY).model == "old/light"
    assert settings.ai_profile(AiTask.SOURCE_LABELS).model == "old/light"
    assert settings.ai_profile(AiTask.NOTEBOOK_CHAT).model == "old/notebook"
    assert settings.ai_profile(AiTask.STUDIO_QUIZ).model == "old/notebook"


def test_the_old_data_collection_and_smart_weight_map_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTEBOOK_DATA_COLLECTION -> notebook tasks; LIMITS__AI_SMART_WEIGHT -> smart."""
    settings = deprecated(
        monkeypatch,
        OPENROUTER__NOTEBOOK_DATA_COLLECTION="allow",
        LIMITS__AI_SMART_WEIGHT="2",
    )

    assert settings.ai_profile(AiTask.NOTEBOOK_CHAT).data_collection == "allow"
    assert settings.ai_profile(AiTask.STUDIO_SLIDES).data_collection == "allow"
    assert settings.ai_profile(AiTask.STUDENT_CHAT).data_collection is None
    assert settings.ai_profile(AiTask.STUDENT_CHAT_SMART).budget_weight == 2


def test_the_smart_weight_alias_still_refuses_zero() -> None:
    """The old LIMITS__AI_SMART_WEIGHT keeps its `>= 1` rule."""
    with pytest.raises(ValidationError):
        Settings(limits={"ai_smart_weight": 0})  # type: ignore[arg-type]


def test_a_new_variable_beats_its_deprecated_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both are set, AI__TASKS__... wins and the other tasks still get the old."""
    settings = deprecated(
        monkeypatch,
        OPENROUTER__MODEL_NOTEBOOK="old/notebook",
        AI__TASKS__STUDIO_QUIZ__MODEL="new/quiz",
    )

    assert settings.ai_profile(AiTask.STUDIO_QUIZ).model == "new/quiz"
    assert settings.ai_profile(AiTask.STUDIO_REPORT).model == "old/notebook"


def test_each_deprecated_variable_in_use_is_logged_as_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The log names the old variable and what replaces it."""
    monkeypatch.setenv("IHSP_OPENROUTER__MODEL_ADMIN", "old/admin")
    monkeypatch.setenv("IHSP_LIMITS__AI_SMART_WEIGHT", "3")

    with capture_logs() as logs:
        Settings()

    warnings = [log for log in logs if log["event"] == "settings.deprecated_variable"]
    assert {log["variable"] for log in warnings} == {
        "IHSP_OPENROUTER__MODEL_ADMIN",
        "IHSP_LIMITS__AI_SMART_WEIGHT",
    }
    assert all(log["log_level"] == "warning" for log in warnings)
    assert "IHSP_AI__TASKS__ADMIN_CHAT__MODEL" in {log["use"] for log in warnings}


def test_no_warning_without_deprecated_variables() -> None:
    """A clean environment logs nothing about deprecation."""
    with capture_logs() as logs:
        Settings()

    assert [log for log in logs if "deprecated" in log["event"]] == []


def test_auto_labels_is_a_light_private_notebook_task() -> None:
    """Auto labels (G12): a light notebook task, no provider that trains on it."""
    profile = AiSettings().profile(AiTask.SOURCE_LABELS)

    assert AiTask.SOURCE_LABELS in LIGHT_NOTEBOOK_TASKS
    assert AiTask.SOURCE_LABELS in NOTEBOOK_TASKS
    assert profile.provider() == {"data_collection": "deny"}
    assert profile.budget_weight == 1


def test_context_compaction_runs_on_the_cheapest_model_privately() -> None:
    """AI-EFF-2: CONTEXT_COMPACT ships with the cheap model, no reasoning, deny."""
    profile = AiSettings().profile(AiTask.CONTEXT_COMPACT)

    assert profile.model == COMPACT_MODEL
    assert profile.reasoning_effort == "none"
    assert profile.data_collection == "deny"
