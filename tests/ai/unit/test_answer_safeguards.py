"""AI-OPENUI, AI-8: server-side safeguards of an answer and the size of a request."""

import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.prompts import system_prompt
from app.modules.ai.infrastructure.openrouter import build_payload
from app.modules.ai.wiring import make_admin_tools
from app.settings import UrlsSettings
from app.shared.ai.answer_language import answer_language, detect_language
from app.shared.ai.narration import NarrationFilter, strip_narration
from app.shared.ai.prompt_cache import split_system, with_volatile_tail
from app.shared.contracts.ai import LlmTuning
from app.shared.openui.blocks import split_blocks
from app.shared.openui.finalize import OpenUiFinalizer
from app.shared.openui.prompt import openui_prompt
from app.shared.openui.tables import markdown_tables_to_blocks
from app.shared.openui.validate import validate_block
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest

TODAY = date(2026, 11, 4)
TABLE = (
    "Here it is:\n\n| Fan | Baho |\n|---|---|\n| Fizika | 4 |\n| Kimyo | 5 |\n\nTamom."
)


# - - - Request size - - -


async def _request(h: AiHarness, assistant: Assistant) -> dict[str, Any]:
    actor = h.student if assistant is Assistant.STUDENT else h.admin
    chat = await h.new_chat(assistant=assistant)
    h.llm.push(text_reply("ok"))
    await h.say(chat.id, "hi", actor=actor)
    return h.llm.requests[-1]


@pytest.mark.parametrize(
    ("assistant", "budget"), [(Assistant.STUDENT, 15_000), (Assistant.ADMIN, 14_700)]
)
async def test_the_request_stays_within_its_size_budget(
    h: AiHarness, assistant: Assistant, budget: int
) -> None:
    """AI-EFF-1: the system prompt, blocks and tool schemas fit the character budget."""
    request = await _request(h, assistant)
    system = request["system"]
    size = len(system) + (0 if openui_prompt() in system else len(openui_prompt()))
    size += len(json.dumps(request["tools"], ensure_ascii=False))
    assert size <= budget


def test_the_safety_rules_survive_the_shorter_prompt() -> None:
    """AI-4: injection, approval, school terms and LMS denial stay in the prompt."""
    prompt = " ".join(system_prompt(Assistant.STUDENT, TODAY).split())
    assert "never instructions" in prompt
    assert "approval of that single call" in prompt
    assert "Промежуточный контроль" in prompt and "Итоговый контроль" in prompt
    assert "Рубежный" not in prompt
    assert "no access to LMS course content" in prompt


async def test_the_language_is_the_last_line_and_after_the_cache_mark(
    h: AiHarness,
) -> None:
    """AI-EFF-1: the stable part does not depend on the user's language."""
    chat = await h.new_chat()
    h.llm.push(text_reply("a"), text_reply("b"))
    await h.say(chat.id, "Baholarimni jadvalda koʻrsating")
    await h.say(chat.id, "Покажи мои оценки в таблице")

    first, second = (split_system(r["system"]) for r in h.llm.requests)
    assert first[0] == second[0]
    assert "Uzbek" in first[1].splitlines()[-1]
    assert "Russian" in second[1].splitlines()[-1]


def test_only_the_stable_part_gets_the_cache_breakpoint() -> None:
    """AI-EFF-1: the volatile tail follows the breakpoint as a part of its own."""
    system = with_volatile_tail("stable", "tail")
    cached = build_payload("anthropic/x", system, [], [], 10, None, ("anthropic/",))
    parts = cached["messages"][0]["content"]
    assert parts[0]["text"] == "stable" and "cache_control" in parts[0]
    assert parts[1] == {"type": "text", "text": "tail"}
    plain = build_payload("other/x", system, [], [], 10, None, ("anthropic/",))
    assert plain["messages"][0]["content"] == "stable\n\ntail"


# - - - Role tool sets - - -


async def test_the_student_is_offered_one_file_tool_and_no_project_search(
    h: AiHarness,
) -> None:
    """AI-5: office tools are not offered but resolve; project search needs one."""
    names = {
        t["function"]["name"] for t in (await _request(h, Assistant.STUDENT))["tools"]
    }
    assert "make_document" in names
    assert not names & {"create_document", "create_presentation", "create_spreadsheet"}
    assert "search_project_files" not in names
    registry = h.services.send_message.continue_turn.registry
    assert registry.get(Assistant.STUDENT, "create_document") is not None
    assert "search_project_files" in {
        t["function"]["name"] for t in registry.llm_tools(Assistant.STUDENT)
    }


async def test_the_admin_is_offered_no_student_or_author_tools(h: AiHarness) -> None:
    """AI-6: the Administration assistant sees only its own tools."""
    names = {
        t["function"]["name"] for t in (await _request(h, Assistant.ADMIN))["tools"]
    }
    assert not names & {"get_marks", "read_file", "make_document", "search_web"}
    assert {
        t.name
        for t in make_admin_tools(MagicMock(), MagicMock(), MagicMock(), UrlsSettings())
    } | {"read_chat_history"} == names


async def test_every_student_tool_says_when_to_use_it_and_stays_small(
    h: AiHarness,
) -> None:
    """AI-5: a description starts with its use; the schema carries no limits."""
    for tool in (await _request(h, Assistant.STUDENT))["tools"]:
        function = tool["function"]
        assert function["description"].startswith("Use ")
        text = json.dumps(function["parameters"])
        assert "maxLength" not in text and '"default"' not in text


async def test_a_value_over_a_limit_is_still_refused_when_the_tool_runs(
    h: AiHarness,
) -> None:
    """AI-4: the compact schema changes what the model sees, not what is accepted."""
    chat = await h.new_chat()
    h.llm.push(
        tool_reply(("search_files", {"query": "x" * 500})), text_reply("Nothing.")
    )
    result = await h.say(chat.id, "find")
    assert result.new_messages[-1].tool_calls[0].status == "failed"


# - - - The tool loop - - -


async def test_the_last_step_answers_from_what_was_fetched(
    make_harness: HarnessFactory,
) -> None:
    """AI-8: the last request forbids tools, and its text is the answer."""
    h = make_harness(limits={"ai_max_tool_steps": 2})
    chat = await h.new_chat()
    h.llm.push(tool_reply(("get_my_subjects", {})), text_reply("Here is what I found."))

    result = await h.say(chat.id, "loop")

    assert len(h.llm.requests) == 2
    assert (
        not h.llm.requests[0]["tuning"] or not h.llm.requests[0]["tuning"].answer_only
    )
    assert h.llm.requests[1]["tuning"].answer_only
    assert "answer now" in h.llm.requests[1]["system"]
    assert result.new_messages[-1].text == "Here is what I found."


async def test_a_model_that_calls_tools_on_the_last_step_is_not_obeyed(
    make_harness: HarnessFactory,
) -> None:
    """AI-8: a write proposed on the last step is dropped; the turn ends with a note."""
    h = make_harness(limits={"ai_max_tool_steps": 1})
    chat = await h.new_chat()
    h.llm.push(tool_reply(("create_flashcard_set", {"title": "x", "cards": []})))

    result = await h.say(chat.id, "loop")

    assert result.status == "done"
    assert result.new_messages[-1].tool_calls == []
    assert "step limit" in result.new_messages[-1].text


async def test_repeating_the_same_call_ends_the_tool_rounds(h: AiHarness) -> None:
    """AI-8: when nothing new can come back, the next request must answer."""
    chat = await h.new_chat()
    h.llm.push(
        tool_reply(("get_my_subjects", {})),
        tool_reply(("get_my_subjects", {})),
        text_reply("Done."),
    )
    result = await h.say(chat.id, "loop")

    assert len(h.llm.requests) == 3
    assert h.llm.requests[2]["tuning"].answer_only
    assert result.new_messages[-1].text == "Done."


def test_answer_only_sets_tool_choice_none_and_keeps_the_tools() -> None:
    """AI-8: tool history stays valid because the tools are still listed."""
    tools = [{"type": "function", "function": {"name": "t"}}]
    payload = build_payload("m", "s", [], tools, 10, LlmTuning(answer_only=True), ())
    assert payload["tool_choice"] == "none" and payload["tools"] == tools


# - - - Narration - - -


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        (
            "The student gave the marks directly, so no tools are needed.\n\nMaths: 5",
            "Maths: 5",
        ),
        ("The user asks for a table. Here it is:\nx", "Here it is:\nx"),
        ("Since the student provided the data, no lookup.\n\nOK.", "OK."),
        (
            "No tools are needed. Photosynthesis is a process.",
            "Photosynthesis is a process.",
        ),
        ("Студент дал оценки сам. Вот таблица.", "Вот таблица."),
        ("Инструменты не нужны. Вот ответ.", "Вот ответ."),
        ("Oʻquvchi baholarni oʻzi berdi. Mana jadval.", "Mana jadval."),
    ],
)
def test_leading_narration_is_removed(raw: str, clean: str) -> None:
    """AI-OPENUI: a note about the user or the tools does not open an answer."""
    assert strip_narration(raw) == clean


@pytest.mark.parametrize(
    "text",
    [
        "The student council meets on Friday. Bring your card.",
        "The student union building is near the gate.",
        "No homework is due today.",
        "I do not know this. The base has nothing.",
        "This is a simple machine: a lever.",
        "Your marks are good. The student gave up nothing.",
        "Студенческий совет собирается в пятницу.",
        "Oʻquvchilar kengashi juma kuni yigʻiladi.",
        "| The student asks for a table | x |",
    ],
)
def test_legitimate_text_stays(text: str) -> None:
    """AI-OPENUI: "the student" as a topic is content, not narration."""
    assert strip_narration(text) == text


def test_an_answer_that_is_only_a_note_is_kept() -> None:
    """AI-OPENUI: the user never gets an empty answer."""
    only = "The user asked for a table."
    assert strip_narration(only) == only


def test_a_student_as_the_topic_keeps_the_sentence() -> None:
    """AI-6: in an Administration chat the student is the subject of the answer."""
    text = "The student did not get marks this week. Two lessons were missed."
    assert strip_narration(text, about_student=False) == text


def test_working_notes_after_a_note_go_in_a_non_english_answer() -> None:
    """AI-OPENUI: the English scratch work before an Uzbek answer is removed."""
    raw = (
        "The user gave marks directly, so no tool is needed. Compute averages:\n"
        "- Maths: 4.25\n\nA table is requested, so a block fits.\n\n"
        "Matematika oʻrtacha bahosi 4.25, fizika esa 4.0."
    )
    assert strip_narration(raw, language="uz") == (
        "Matematika oʻrtacha bahosi 4.25, fizika esa 4.0."
    )


def test_a_later_paragraph_of_notes_goes_after_a_note_but_never_in_a_block() -> None:
    """AI-OPENUI: the note in the middle is removed; the data and block stay."""
    block = '```openui\nroot = Stack([t])\nt = TextBlock("A table is requested.")\n```'
    raw = (
        "The user gave the marks directly. Maths: 4.25.\n\n"
        f"A table is requested, so I will use a block.\n\nHere it is:\n\n{block}"
    )
    assert strip_narration(raw) == f"Maths: 4.25.\n\nHere it is:\n\n{block}"


def test_requested_english_in_an_uzbek_answer_stays_without_a_note() -> None:
    """AI-OPENUI: only a removed note makes English paragraphs suspect."""
    text = "The cat sat on the mat and it was happy.\n\nBu gap inglizcha."
    assert strip_narration(text, language="uz") == text


def _stream(text: str, size: int, **options: Any) -> str:
    guard = NarrationFilter(**options)
    pieces = [text[i : i + size] for i in range(0, len(text), size)]
    return "".join(guard.feed(p) for p in pieces) + guard.finish()


@pytest.mark.parametrize("size", [1, 2, 3, 7, 16, 1000])
@pytest.mark.parametrize(
    "text",
    [
        "The student gave the marks directly, so no tools.\n\nMaths: 5",
        "The student council meets on Friday. Bring your card.",
        "Maths: 5, physics: 4.",
        "No tools are needed. The answer is 4.",
        "Инструменты не нужны. Ответ: 4.",
    ],
)
def test_streaming_agrees_with_the_final_text_for_any_chunking(
    text: str, size: int
) -> None:
    """AI-OPENUI: chunk splits never change what the stream shows."""
    assert _stream(text, size) == strip_narration(text)


@pytest.mark.parametrize("size", [1, 5, 1000])
def test_streaming_removes_working_notes_too(size: int) -> None:
    """AI-OPENUI: the notes of a non-English answer do not flash on the screen."""
    raw = "The user gave marks. Compute it now and then draw.\n\nJadval tayyor."
    assert _stream(raw, size, language="uz") == "Jadval tayyor."


def test_streaming_releases_an_ordinary_start_at_once() -> None:
    """AI-OPENUI: a normal answer is not held back."""
    guard = NarrationFilter()
    assert guard.feed("Maths ") == "Maths "
    assert guard.feed("is fine") == "is fine"


async def test_a_streamed_turn_never_shows_the_note(h: AiHarness) -> None:
    """AI-OPENUI: deltas and the stored answer both start with the answer."""
    chat = await h.new_chat()
    h.llm.push(text_reply("The student asked for a table. Maths: 5."))
    events = [
        e
        async for e in h.services.send_message.stream(
            actor=h.student, chat_id=chat.id, text="Show my marks", file_ids=[]
        )
    ]
    shown = "".join(e.data["text"] for e in events if e.name == "delta")
    assert "student" not in shown
    assert events[-1].result is not None
    assert events[-1].result.new_messages[-1].text == "Maths: 5."


# - - - Tables - - -


def test_a_markdown_table_becomes_a_valid_block_and_keeps_its_text() -> None:
    """AI-OPENUI: the table moves into a block, the text around it stays."""
    parts = split_blocks(markdown_tables_to_blocks(TABLE))
    assert [p.kind for p in parts] == ["text", "block", "text"]
    assert validate_block(parts[1].text, "chat") == []
    assert '"Fizika"' in parts[1].text


@pytest.mark.parametrize(
    "text",
    [
        "| a | b |\n|---|---|\n| [x](https://e.uz) | 1 |",
        "| a | b |\n|---|---|\n| [[W1]] | 1 |",
        "| a | b |\n|---|---|\n| [S1] | 1 |",
        "| a | b |\n|---|---|\n| $x^2$ | 1 |",
        "| a | b |\n|---|---|\n| 1 | 2 | 3 |",
        "| a | b |\n|---|---|",
        "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```",
        "a | b is an expression\n\nand --- more",
    ],
)
def test_what_a_block_cannot_show_stays_markdown(text: str) -> None:
    """AI-OPENUI: links, citations, formulas, odd rows and code are not converted."""
    assert markdown_tables_to_blocks(text) == text


def test_a_table_over_the_catalogue_limits_stays_markdown() -> None:
    """AI-OPENUI: nine columns do not fit a Table block."""
    head = "|" + "|".join("abcdefghi") + "|"
    text = f"{head}\n|{'-|' * 9}\n|{'1|' * 9}"
    assert markdown_tables_to_blocks(text) == text


def test_tables_stop_at_the_block_limit() -> None:
    """AI-OPENUI: at most three blocks per answer."""
    table = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = markdown_tables_to_blocks("\n\n".join([table] * 4))
    assert sum(p.kind == "block" for p in split_blocks(out)) == 3
    assert out.endswith(table)


async def test_the_chat_finalizer_converts_and_the_notebook_one_does_not() -> None:
    """NB-14: notebook answers keep their tables; the flag belongs to the chat."""
    chat = OpenUiFinalizer(MagicMock(), MagicMock(), enabled=True, convert_tables=True)
    notebook = OpenUiFinalizer(MagicMock(), MagicMock(), enabled=True)
    off = OpenUiFinalizer(MagicMock(), MagicMock(), enabled=False, convert_tables=True)
    assert "```openui" in await chat.finalize(TABLE)
    assert await notebook.finalize(TABLE) == TABLE
    assert await off.finalize(TABLE) == TABLE


# - - - Language - - -


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Fanlarni jadvalda solishtiring", "uz"),
        ("Fizikadan qanday baholarim bor?", "uz"),
        ("Oʻquvchi baholari", "uz"),
        ("Menga yordam bering", "uz"),
        ("Покажи мои оценки", "ru"),
        ("Ўқувчи баҳолари қанақа", "uz"),
        ("What are my physics marks?", "en"),
        ("Compare the subjects in a table", "en"),
        ("My marks: maths 5, 4. Fanlarni jadvalda solishtiring", None),
    ],
)
def test_the_language_of_a_message(text: str, language: str | None) -> None:
    """AI-LANG: clear text decides; a tie between two languages decides nothing."""
    if language is None:
        assert detect_language(text) in (None, "uz", "en")
    else:
        assert detect_language(text) == language


@pytest.mark.parametrize("text", ["", "12345", "2 + 2", "ok?", "👍"])
def test_unclear_text_falls_back_to_the_locale(text: str) -> None:
    """AI-LANG: without a clear language the locale decides."""
    assert answer_language(text, "ru") == "ru"
    assert answer_language(text, "xx") == "en"
