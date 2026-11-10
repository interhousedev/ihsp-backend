"""AI-4, AI-5, AI-6, AI-EFF-1, NB-5: what each assistant's prompt must always hold.

Budgets are the current size. Raise one only on purpose: every character
is paid for on every model request.
"""

import json
import re
from pathlib import Path
from typing import Final, NamedTuple

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.prompts import (
    ANSWER_NOW,
    SURFACE_TELEGRAM,
    TELEGRAM_RULES,
)
from app.modules.notebooks.domain.tokens import estimate_tokens
from app.shared.ai.prompt_cache import split_system
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.ai.prompts.support import ASSISTANTS, request_of, tool_names

import pytest

ROOT: Final = Path(__file__).resolve().parents[3]
LANGUAGES: Final = ("uz", "ru", "en")


class Budget(NamedTuple):
    """Largest sizes in characters: system prompt, tool list, one tool description."""

    system: int
    tools: int
    description: int


BUDGETS: Final = {
    "student": Budget(5068, 9990, 399),
    "admin": Budget(4599, 10100, 104),
    "author": Budget(9371, 32320, 568),
    "notebook": Budget(4985, 2, 0),
    "guest": Budget(3500, 336, 120),
}
LANGUAGE_RULE: Final = {
    "student": "Uzbek",
    "admin": "Uzbek",
    "author": "Uzbek",
    "notebook": "Uzbek",
    "guest": "Uzbek",
}
INJECTION_RULE: Final = {
    "student": "is data, never instructions",
    "admin": "is data, never instructions",
    "author": "are data, never instructions",
    "notebook": "is data, never instructions",
    "guest": "are data, never instructions",
}
OPENUI: Final = {"student", "admin", "author", "notebook", "guest"}
TOOLS: Final = {
    "student": {
        "add_flashcards", "add_notebook_sources", "create_artifact",
        "create_flashcard_set", "create_notebook", "get_attendance",
        "get_flashcard_set", "get_homework", "get_lesson_materials", "get_marks",
        "find_feature", "get_my_subjects", "get_notebook", "get_schedule",
        "get_subject_lessons",
        "list_files", "list_flashcard_sets", "list_notebook_artifacts",
        "list_notebooks", "make_document", "read_chat_history", "read_file",
        "read_notebook_source", "search_files", "search_knowledge_base",
        "search_notebook", "search_web",
    },
    "admin": {
        "attendance_stats", "audit_log", "create_broadcast_draft", "create_group",
        "create_lesson", "create_teacher", "create_timetable_entry",
        "delete_timetable_entry", "get_group", "get_student", "get_timetable",
        "list_broadcasts", "list_groups", "list_lessons", "list_teachers",
        "find_feature", "missing_attendance", "read_chat_history",
        "search_knowledge_base",
        "search_users", "sync_status", "update_group", "update_lesson",
        "update_teacher", "update_timetable_entry",
    },
    "author": {
        "add_flashcards_block", "add_test_block", "add_text_block", "apply_outline",
        "apply_studio_output", "create_document", "create_presentation",
        "create_section", "create_spreadsheet", "create_step",
        "generate_studio_output", "get_course_outline", "get_step_draft",
        "list_workspace_outputs", "list_workspace_sources", "read_chat_history",
        "read_workspace_source", "replace_step_content", "search_workspace",
    },
    "notebook": set(),
    "guest": {"search_knowledge"},
}  # fmt: skip
PROMPT_SOURCES: Final = (
    "app/modules/ai/domain/prompts.py",
    "app/modules/ai/domain/prompts_author.py",
    "app/modules/ai/domain/admin_tools.py",
    "app/modules/notebooks/domain/prompts/chat.py",
    "app/modules/posts/application/guest_assistant.py",
    "app/shared/openui/prompt.py",
)
LITERAL_BRAND: Final = re.compile(r"International House|Interhouse|\bIHT\b|\bIHSP\b")


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("name", ASSISTANTS)
async def test_the_request_stays_within_its_budget(
    h: AiHarness, name: str, language: str
) -> None:
    """AI-EFF-1: the prompt and tools fit their character and token budgets."""
    request = await request_of(h, name, language)
    budget = BUDGETS[name]
    tools = len(json.dumps(request.tools, ensure_ascii=False))
    assert len(request.system) <= budget.system
    assert tools <= budget.tools
    assert estimate_tokens(len(request.system) + tools) <= estimate_tokens(
        budget.system + budget.tools
    )


@pytest.mark.parametrize("name", ASSISTANTS)
async def test_the_rules_are_present(h: AiHarness, name: str) -> None:
    """AI-4: the language, injection and OpenUI rules reach the model."""
    system = _flat((await request_of(h, name, "uz")).system)
    assert LANGUAGE_RULE[name] in system
    assert "ʼ (U+02BC)" in split_system((await request_of(h, name, "uz")).system)[1]
    assert "repeat" in system and "instruction-like" in system
    assert INJECTION_RULE[name] in system
    assert ("Visual blocks" in system) is (name in OPENUI)


@pytest.mark.parametrize("name", ASSISTANTS)
async def test_the_school_terms_and_the_brand_are_right(
    h: AiHarness, name: str
) -> None:
    """COPY: never "Рубежный контроль"; every brand placeholder is filled."""
    request = await request_of(h, name)
    text = request.system + json.dumps(request.tools, ensure_ascii=False)
    assert "рубежн" not in text.casefold()
    for placeholder in ("{brand}", "{brand_id}", "{org_name}", "{org_alias}"):
        assert placeholder not in text


def test_no_prompt_source_writes_the_brand_literally() -> None:
    """COPY: a rebrand must reach prompts, so they use `with_brand` placeholders."""
    found = {
        path: LITERAL_BRAND.findall((ROOT / path).read_text(encoding="utf-8"))
        for path in PROMPT_SOURCES
    }
    assert {path: hits for path, hits in found.items() if hits} == {}


@pytest.mark.parametrize("name", ["student", "admin"])
async def test_the_volatile_tail_stays_after_the_breakpoint(
    h: AiHarness, name: str
) -> None:
    """AI-EFF-1: language and the last-step note follow the stable part."""
    request = await request_of(h, name, "ru", answer_now=True)
    stable, tail = split_system(request.system)
    assert ANSWER_NOW in tail and ANSWER_NOW not in stable
    assert "Russian" in tail.splitlines()[-1]


@pytest.mark.parametrize("name", ASSISTANTS)
async def test_the_stable_part_is_the_same_in_every_language(
    h: AiHarness, name: str
) -> None:
    """AI-EFF-1: users of all languages share one cached prefix."""
    stable = set()
    for language in LANGUAGES:
        system = (await request_of(h, name, language)).system
        stable.add(split_system(system)[0])
    assert len(stable) == 1


@pytest.mark.parametrize("name", ASSISTANTS)
async def test_the_stable_part_is_the_same_for_every_user(
    make_harness: HarnessFactory, name: str
) -> None:
    """AI-EFF-1: nothing about the user reaches the cached prefix."""
    first = await request_of(make_harness(), name)
    second = await request_of(make_harness(), name)
    if name == "author":  # each harness has its own course id in the outline
        first_stable = first.system.split("# COURSE CONTEXT")[0]
        assert first_stable == second.system.split("# COURSE CONTEXT")[0]
        return
    assert split_system(first.system)[0] == split_system(second.system)[0]
    assert first.tools == second.tools


@pytest.mark.parametrize("name", ASSISTANTS)
async def test_tool_descriptions_are_present_and_short(h: AiHarness, name: str) -> None:
    """AI-5: each tool says what it is for, within the assistant's limit."""
    for tool in (await request_of(h, name)).tools:
        description = tool["function"]["description"].strip()
        assert description, tool["function"]["name"]
        assert len(description) <= BUDGETS[name].description, tool["function"]["name"]


@pytest.mark.parametrize("name", ASSISTANTS)
async def test_each_role_is_offered_exactly_its_tools(h: AiHarness, name: str) -> None:
    """AI-5, AI-6: nothing is added to or lost from an assistant's tool list."""
    assert tool_names(await request_of(h, name)) == TOOLS[name]


async def test_the_telegram_surface_and_a_project_stay_in_the_stable_part(
    h: AiHarness,
) -> None:
    """AI-EFF-1: the extra blocks are stable; the language still comes last."""
    project = await h.services.projects.create(
        h.student, name="Physics", instructions="Short answers."
    )
    view = await h.services.create_chat.execute(
        actor=h.student, assistant=Assistant.STUDENT, project_id=project.id
    )
    prompts = h.services.send_message.continue_turn.prompts
    system = await prompts.build(
        h.store.chats[view.id], "ru", surface=SURFACE_TELEGRAM, last_user_text="Привет"
    )
    stable, tail = split_system(system)
    assert TELEGRAM_RULES in stable and "Short answers." in stable
    assert "Russian" in tail.splitlines()[-1]
