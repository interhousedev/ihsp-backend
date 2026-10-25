"""Scripted answers of the fake model for the course author assistant.

`FakeLlmGateway` calls `author_answer` when the system prompt is the author's. The
last user message picks a scenario by keywords (English, Russian, Uzbek); the ids
come from the COURSE CONTEXT of the system prompt, as a real model would take them.
Each write scenario is one tool call, so a development stack without a key shows the
approval cards and writes into a real draft.
"""

import re
from typing import Any

from app.modules.ai.domain.prompts_author import AUTHOR_MARKER
from app.shared.ids import new_id

STEP_ID = re.compile(r"\[step ([0-9a-f-]{36})\]")
SECTION_ID = re.compile(r"\[section ([^\]\s]+)\]")
TOPIC_CHARS = 60

_SCENARIOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("search", ("source", "search", "источник", "найди", "manba", "qidir")),
    ("test", ("test", "quiz", "тест", "savol")),
    ("cards", ("card", "flash", "карточ", "kartochka")),
    ("lesson", ("lesson", "урок", "dars", "текст", "matn")),
    ("outline", ("outline", "plan", "план", "структур", "reja", "tuzilma")),
    ("step", ("step", "шаг", "qadam")),
)


def is_author_chat(system: str) -> bool:
    """True when the request comes from the course author assistant."""
    return AUTHOR_MARKER in system


def author_answer(system: str, last_user: str) -> tuple[str, list[dict[str, Any]]]:
    """Return the text and tool calls for the author's last message."""
    lowered = last_user.lower()
    topic = " ".join(last_user.split())[:TOPIC_CHARS] or "Topic"
    steps = STEP_ID.findall(system)
    sections = SECTION_ID.findall(system)
    scenario = next(
        (name for name, words in _SCENARIOS if any(w in lowered for w in words)),
        None,
    )
    if scenario == "search":
        return "", [_call("search_workspace", {"query": topic, "limit": 5})]
    if scenario in ("test", "cards", "lesson") and steps:
        return "", [_STEP_WRITERS[scenario](steps[0], topic)]
    if scenario == "step" and sections:
        args = {"section_id": sections[-1], "title": f"{topic} (practice)"}
        return "", [_call("create_step", args)]
    if scenario is not None:
        return "", [_call("apply_outline", _outline(topic))]
    return (
        f"(fake author) {last_user}\n\nI can propose a course outline, write a "
        "lesson, a test or flash cards for a step, or search the workspace sources.",
        [],
    )


def _outline(topic: str) -> dict[str, Any]:
    return {
        "sections": [
            {
                "title": f"{topic}: basics",
                "steps": [
                    {
                        "title": "Key ideas",
                        "brief": "**Goals**\n\n- explain the key ideas",
                    },
                    {
                        "title": "Worked examples",
                        "brief": "**Goals**\n\n- solve a typical task",
                    },
                ],
            },
            {
                "title": f"{topic}: practice",
                "steps": [
                    {"title": "Exercises", "brief": "**Goals**\n\n- practise alone"},
                    {"title": "Check yourself", "brief": "**Goals**\n\n- self-check"},
                ],
            },
        ],
        "add_briefs": True,
    }


def _lesson(step_id: str, topic: str) -> dict[str, Any]:
    markdown = (
        f"### {topic}\n\nThis step explains the main idea in short paragraphs.\n\n"
        "### Worked example\n\n1. Read the task.\n2. Apply the rule.\n"
        "3. Check the answer: $2 + 2 = 4$."
    )
    return _call("add_text_block", {"step_id": step_id, "markdown": markdown})


def _test(step_id: str, topic: str) -> dict[str, Any]:
    questions = [
        {
            "type": "single",
            "prompt": f"Which statement about {topic} is true?",
            "options": [
                {"text": "The rule from this step", "correct": True},
                {"text": "A common misconception"},
                {"text": "An unrelated fact"},
            ],
            "explanation": "The step states this rule.",
        },
        {
            "type": "number",
            "prompt": "How much is 2 + 2?",
            "number": 4,
            "explanation": "2 + 2 = 4.",
        },
    ]
    return _call("add_test_block", {"step_id": step_id, "questions": questions})


def _cards(step_id: str, topic: str) -> dict[str, Any]:
    cards = [
        {"front": f"{topic}: term {n}", "back": f"Definition {n}"} for n in (1, 2, 3)
    ]
    return _call("add_flashcards_block", {"step_id": step_id, "cards": cards})


_STEP_WRITERS = {"lesson": _lesson, "test": _test, "cards": _cards}


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"fake_{new_id().hex[-12:]}", "name": name, "arguments": arguments}
