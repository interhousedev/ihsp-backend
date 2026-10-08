"""AI-5, AI-6, AI-11: every tool has a strict schema, a note and card labels."""

import json
from typing import Any

from app.modules.ai.domain.admin_tools import ADMIN_TOOLS
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.json_schema import tool_parameters
from app.modules.ai.domain.tools import note_key
from app.shared.i18n.core import I18nCore
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply

import pytest

STUDENT_TOOLS = {
    "get_my_subjects", "get_subject_lessons", "get_lesson_materials", "get_schedule",
    "get_homework", "get_marks", "get_attendance", "list_files", "read_file",
    "search_files", "list_flashcard_sets", "get_flashcard_set",
    "create_flashcard_set", "add_flashcards",
}  # fmt: skip


async def tools_of(h: AiHarness, assistant: Assistant) -> list[dict[str, Any]]:
    """Return the tool list the model receives for an assistant."""
    actor = h.student if assistant is Assistant.STUDENT else h.admin
    chat = await h.new_chat(assistant=assistant)
    h.llm.push(text_reply("ok"))
    await h.say(chat.id, "hi", actor=actor)
    tools: list[dict[str, Any]] = h.llm.requests[-1]["tools"]
    return tools


async def test_student_tools_match_the_spec(h: AiHarness) -> None:
    """AI-5: exactly the student tools, writes only for flash cards."""
    tools = await tools_of(h, Assistant.STUDENT)

    assert {t["function"]["name"] for t in tools} == STUDENT_TOOLS


async def test_admin_tools_match_the_spec(h: AiHarness) -> None:
    """AI-6: the Administration tools of the README."""
    tools = await tools_of(h, Assistant.ADMIN)

    names = [t["function"]["name"] for t in tools]
    assert names == [d.name for d in ADMIN_TOOLS]
    assert len(names) == 22 and len(set(names)) == 22


@pytest.mark.parametrize("assistant", list(Assistant))
async def test_schemas_are_strict_and_self_contained(
    h: AiHarness, assistant: Assistant
) -> None:
    """AI-4: additionalProperties false everywhere, no $ref, no stray titles."""
    tools = await tools_of(h, assistant)

    for tool in tools:
        schema = tool["function"]["parameters"]
        text = json.dumps(schema)
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert "$ref" not in text and "$defs" not in text
        assert tool["function"]["name"] and tool["function"]["description"]


async def test_title_property_survives_title_stripping(h: AiHarness) -> None:
    """The flash card tool really has a `title` argument next to its cards."""
    tools = await tools_of(h, Assistant.STUDENT)

    create = next(t for t in tools if t["function"]["name"] == "create_flashcard_set")
    props = create["function"]["parameters"]["properties"]
    assert set(props) == {"title", "description", "cards"}
    assert props["cards"]["items"]["additionalProperties"] is False


def test_date_arguments_use_the_documented_names() -> None:
    """AI-5: `from` and `to`, as in the README."""
    from app.modules.ai.application.tools.get_schedule import GetScheduleArgs

    schema = tool_parameters(GetScheduleArgs)

    assert set(schema["properties"]) == {"from", "to"}
    assert GetScheduleArgs.model_validate({"from": "2026-10-06", "to": "2026-10-08"})


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
def test_every_tool_has_a_note_and_every_card_label_a_translation(
    i18n: I18nCore, locale: str
) -> None:
    """AI-11: all tool notes, card titles and field labels exist in every language."""
    names = STUDENT_TOOLS | {d.name for d in ADMIN_TOOLS}
    keys = {note_key(name) for name in names}
    keys |= {
        "ai-preview-" + d.name.replace("_", "-")
        for d in ADMIN_TOOLS
        if d.access.value == "write"
    }
    keys |= {"ai-preview-create-flashcard-set", "ai-preview-add-flashcards"}
    for definition in ADMIN_TOOLS:
        if definition.access.value == "write":
            keys |= {
                "ai-field-" + f.replace("_", "-") for f in definition.args.model_fields
            }
    keys |= {"ai-field-title", "ai-field-set", "ai-chat-new", "ai-step-limit"}
    keys |= {f"ai-{code}" for code in (
        "provider-error", "limit-reached", "chat-not-found", "tool-call-not-found",
        "tool-call-not-pending", "tool-call-expired", "turn-in-progress",
        "wrong-assistant", "attachment-invalid", "tool-arguments", "tool-failed",
    )}  # fmt: skip

    missing = [k for k in sorted(keys) if i18n.t(locale, k) == k]

    assert missing == []
