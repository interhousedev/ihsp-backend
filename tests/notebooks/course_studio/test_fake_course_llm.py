"""LMS-AI-STUDIO: the fake model writes believable plans and lessons without a key."""

import re
from typing import Any

from app.modules.ai.infrastructure.fake_course import build_course_document
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.notebooks.application.artifact_tasks import task_for_kind
from app.modules.notebooks.domain.artifacts.handler import ProcessContext
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.prompts.course import (
    course_system_prompt,
    task_with_course,
)
from app.modules.notebooks.domain.sources_block import render_sources_block
from app.shared.ai_tasks import AiTask
from tests.notebooks.unit.domain.pack_support import make_pack

import pytest

CYRILLIC = re.compile(r"[а-яА-Я]")


def messages_for(
    kind: ArtifactKind, options: dict[str, Any], shape: tuple[int, ...] = (4,)
) -> tuple[list[dict[str, Any]], Any]:
    """The context and task messages the engine would send, and the options."""
    pack = make_pack(shape, titles=tuple(f"Unit {n}" for n in range(1, len(shape) + 1)))
    handler = handler_for(kind)
    parsed = handler.parse_options(options)
    task = task_with_course(kind, handler.task_block(parsed, None), None)
    messages = [
        {"role": "user", "content": render_sources_block(pack)},
        {"role": "user", "content": task},
    ]
    return messages, (pack, parsed)


async def ask(
    kind: ArtifactKind, options: dict[str, Any], language: str, shape: tuple[int, ...]
) -> tuple[dict[str, Any], Any]:
    messages, (pack, parsed) = messages_for(kind, options, shape)
    handler = handler_for(kind)
    answer = await FakeLlmGateway().complete_json(
        model="m",
        system=course_system_prompt(language),
        messages=messages,
        schema_name=handler.schema_name,
        schema=handler.strict_schema(),
        max_tokens=1000,
    )
    processed = handler.process(
        answer["data"], parsed, ProcessContext(pack, language, 3)
    )
    return processed.content, pack


@pytest.mark.parametrize("language", ["en", "ru", "uz"])
async def test_the_fake_plan_is_valid_and_in_the_language(language: str) -> None:
    """LMS-AI-STUDIO: a section per source, a step per passage, valid output."""
    content, _ = await ask(ArtifactKind.COURSE_PLAN, {}, language, (3, 2))

    assert content["language"] == language
    assert [s["title"] for s in content["sections"]] == ["Unit 1", "Unit 2"]
    assert len(content["sections"][0]["steps"]) == 3
    assert content["goals"] and content["sections"][0]["goals"]
    has_cyrillic = bool(CYRILLIC.search(content["summary"]))
    assert has_cyrillic is (language == "ru")


@pytest.mark.parametrize("language", ["en", "ru", "uz"])
@pytest.mark.parametrize("length", ["short", "standard", "long"])
async def test_the_fake_lesson_meets_the_minimums_of_every_length(
    language: str, length: str
) -> None:
    """LMS-AI-STUDIO: text, enough cards and questions even for a thin source."""
    options = {"include_test": True, "include_flashcards": True, "length": length}

    content, _ = await ask(ArtifactKind.LESSON_DRAFT, options, language, (2,))

    kinds = [b["type"] for b in content["blocks"]]
    assert kinds == ["text", "flashcards", "test"]
    assert "### " in content["blocks"][0]["markdown"]
    assert (
        len(content["blocks"][1]["cards"])
        >= {"short": 3, "standard": 5, "long": 7}[length]
    )
    assert (
        len(content["blocks"][2]["questions"])
        >= {"short": 2, "standard": 3, "long": 4}[length]
    )


async def test_the_fake_lesson_has_no_test_or_cards_unless_asked() -> None:
    """LMS-AI-STUDIO: the fake reads the task like a real model would."""
    content, _ = await ask(ArtifactKind.LESSON_DRAFT, {}, "en", (3,))

    assert [b["type"] for b in content["blocks"]] == ["text"]


def test_other_schemas_are_not_answered_by_the_course_builders() -> None:
    """LMS-AI-STUDIO: the notebook builders keep their schemas."""
    assert build_course_document("nb_quiz", [], "") is None


def test_the_course_kinds_run_on_the_lms_authoring_task() -> None:
    """LMS-AI-STUDIO: one model setting for the plan, the lesson and the assistant."""
    assert task_for_kind(ArtifactKind.COURSE_PLAN) is AiTask.LMS_AUTHORING
    assert task_for_kind(ArtifactKind.LESSON_DRAFT) is AiTask.LMS_AUTHORING
