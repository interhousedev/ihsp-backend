"""AI requests: the registered call specs, the catalogue build and the prompt diffs."""

from typing import Any

from app.modules.ai.domain.prompt_registry import PromptSlot
from app.modules.ai.domain.requests import (
    AiRequestDuplicateError,
    AiRequestSpec,
    build_catalog,
    estimate_tokens,
    unified_diff,
)
from app.shared.ai_tasks import AiTask

import pytest

QUIZ = PromptSlot("studio_quiz", "main", "The quiz writer", "Write a quiz.")
GREET = PromptSlot("chat", "greet", "Greeting", "Hi {name}.", template=True)


def spec(request_id: str = "notebooks.studio_quiz.main", **kw: Any) -> AiRequestSpec:
    fields = {
        "id": request_id,
        "owner_app": "notebooks",
        "task": AiTask.STUDIO_QUIZ,
        "template": QUIZ,
        "args_schema": {"type": "object", "properties": {}},
        "tools": (),
        "summary": "Quiz",
    }
    fields.update(kw)
    return AiRequestSpec(**fields)


def test_spec_derives_pipeline_and_template_id() -> None:
    declared = spec()
    assert declared.template_id == "studio_quiz/main"
    assert declared.pipeline == "studio"


def test_spec_rejects_a_malformed_id() -> None:
    with pytest.raises(ValueError):
        spec("Notebooks Quiz")


def test_catalog_adds_one_auto_spec_per_uncovered_slot() -> None:
    catalog = build_catalog([QUIZ, GREET], [spec()])
    assert [s.id for s in catalog] == ["notebooks.studio_quiz.main", "ai.chat.greet"]
    assert catalog[1].template == GREET
    assert catalog[1].task == "chat"


def test_catalog_rejects_duplicate_request_ids() -> None:
    with pytest.raises(AiRequestDuplicateError):
        build_catalog([], [spec(), spec()])


def test_estimate_tokens_is_a_quarter_of_the_characters_rounded_up() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_unified_diff_labels_both_sides_and_shows_changes() -> None:
    diff = unified_diff("one\ntwo\n", "one\nthree\n", "v1", "v2")
    assert "--- v1" in diff
    assert "+++ v2" in diff
    assert "-two" in diff
    assert "+three" in diff


def test_unified_diff_of_identical_texts_is_empty() -> None:
    assert unified_diff("same\n", "same\n", "a", "b") == ""
