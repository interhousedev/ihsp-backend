"""Answer quality: prompt rules and size, repeated calls, ask before web search."""

import json
from datetime import date
from typing import Any
from uuid import uuid4

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tool_runner import ToolRunner
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.read_chat_history import ReadChatHistory
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.application.tools.search_notebook import _interleaved
from app.modules.ai.application.tools.search_web import SearchWeb
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.prompts import system_prompt
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import ToolAccess, ToolStatus
from app.modules.ai.wiring import make_student_tools
from app.settings import LimitsSettings
from app.shared.actor import Actor, Role
from app.shared.limits import StaticLimits
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply, tool_reply
from tests.fakes.clock import FixedClock

import pytest

TOKEN_BUDGET = 8000  # system prompt + tool schemas, chars / 4


class FindArgs(ToolArgs):
    """A phrase."""

    query: str


class Find(ReadTool[FindArgs]):
    """Counts its runs."""

    name = "find"
    description = "find"
    args_model = FindArgs
    runs = 0

    async def run(self, args: FindArgs, ctx: ToolContext) -> dict[str, Any]:
        Find.runs += 1
        return {"items": [args.query]}


class FakeWeb:
    """Records searches."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, actor: Actor, *, query: str, locale: str, **_: Any) -> Any:
        self.queries.append(query)
        hit = type("Hit", (), {"title": "T", "url": "https://x.uz", "snippet": "s"})
        return type("Outcome", (), {"hits": (hit,)})


def _ctx() -> ToolContext:
    actor = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))
    return ToolContext(actor=actor, chat_id=uuid4(), locale="ru")


def _limits(ask: int) -> StaticLimits:
    return StaticLimits(LimitsSettings(ai_ask_before_web_search=ask))


def test_student_prompt_has_language_and_tool_policy_rules() -> None:
    """The language rule covers notes and tool summaries; the policy caps searches."""
    prompt = system_prompt(Assistant.STUDENT, "uz", date(2026, 10, 17))

    assert "language of the user's last message" in prompt
    assert "summary of tool results" in prompt
    assert "Tool policy" in prompt and "variants" in prompt
    assert "ask whether to search the internet" in prompt
    auto = system_prompt(
        Assistant.STUDENT, "uz", date(2026, 10, 17), ask_before_web=False
    )
    assert "call search_web once" in auto and "ask whether" not in auto


def test_prompt_and_tools_fit_the_token_budget() -> None:
    """Prompt + tool schemas stay small enough for a 100k context."""
    tools = make_student_tools(
        schedule=None,  # type: ignore[arg-type]
        classwork=None,  # type: ignore[arg-type]
        marks=None,  # type: ignore[arg-type]
        files=None,  # type: ignore[arg-type]
        flashcards=None,  # type: ignore[arg-type]
        bindings=LateBindings(),
        limits=_limits(1),
    )
    tools.append(ReadChatHistory(None))  # type: ignore[arg-type]
    schemas = json.dumps([t.spec().to_llm() for t in tools], ensure_ascii=False)
    prompt = system_prompt(Assistant.STUDENT, "ru", date(2026, 10, 17))

    assert (len(prompt) + len(schemas)) // 4 <= TOKEN_BUDGET


async def test_a_repeated_call_in_a_turn_returns_the_earlier_result() -> None:
    """Same tool, same words (case and spaces aside): run once, then repeated."""
    Find.runs = 0
    runner = ToolRunner(ToolRegistry(student=[Find()], admin=[]), FixedClock())
    seen: dict[str, Any] = {}
    raw = [
        {"id": "a", "name": "find", "arguments": {"query": "Jadids"}},
        {"id": "b", "name": "find", "arguments": {"query": " jadids "}},
    ]

    first = await runner.propose(Assistant.STUDENT, _ctx(), raw, set(), seen)
    again = await runner.propose(Assistant.STUDENT, _ctx(), raw[:1], {"a", "b"}, seen)

    assert Find.runs == 1
    assert first[1].result is not None and "repeated" in first[1].result
    assert again[0].result is not None and again[0].result["items"] == ["Jadids"]
    assert len({first[0].id, first[1].id, again[0].id}) == 3


@pytest.mark.parametrize(
    ("ask", "status", "searched"),
    [(1, ToolStatus.PENDING_APPROVAL, 0), (0, ToolStatus.DONE, 1)],
)
async def test_search_web_asks_first_only_while_the_setting_is_on(
    ask: int, status: ToolStatus, searched: int
) -> None:
    """On: an approval card, nothing searched; off: the search runs at once."""
    web = FakeWeb()
    bindings = LateBindings(web=web)  # type: ignore[arg-type]
    tool = SearchWeb(bindings, _limits(ask))
    runner = ToolRunner(ToolRegistry(student=[tool], admin=[]), FixedClock())
    raw = [{"id": "w", "name": "search_web", "arguments": {"query": "Munavvar qori"}}]

    (call,) = await runner.propose(Assistant.STUDENT, _ctx(), raw, set())

    assert call.status is status and len(web.queries) == searched
    if searched:
        assert call.access is ToolAccess.READ
        assert call.result == {
            "pages": [{"title": "T", "url": "https://x.uz", "snippet": "s"}]
        }


def test_variant_hits_are_interleaved_and_deduplicated() -> None:
    """Each phrase's best passage comes first; a passage found twice shows once."""
    a = [{"source_id": "s", "seq": 1}, {"source_id": "s", "seq": 2}]
    b = [{"source_id": "s", "seq": 2}, {"source_id": "s", "seq": 3}]

    rows = _interleaved([a, b], 3)

    assert [r["seq"] for r in rows] == [1, 2, 3]


async def test_a_note_before_an_approval_card_is_progress_not_the_answer(
    h: AiHarness,
) -> None:
    """While a write waits, the round's note is a progress note; the text is empty."""
    chat = await h.new_chat()
    cards = [{"front": "a", "back": "b"}]
    h.llm.push(
        tool_reply(
            ("create_flashcard_set", {"title": "Bio", "cards": cards}),
            text="Сохраню набор на русском. Сначала проверю…",
        )
    )

    first = await h.say(chat.id, "Сделай карточки")

    waiting = h.store.chat_messages(chat.id)[1]
    assert waiting.text == ""
    assert waiting.content.progress == ["Сохраню набор на русском. Сначала проверю…"]
    h.llm.push(text_reply("Набор готов."))
    await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=first.new_messages[1].tool_calls[0].id
    )
    done = h.store.chat_messages(chat.id)[1]
    assert done.text == "Набор готов."
    assert done.content.progress == ["Сохраню набор на русском. Сначала проверю…"]
    sent = h.llm.requests[-1]["messages"]
    assert [m["role"] for m in sent][-2:] == ["assistant", "tool"]
    assert sent[-2]["content"].startswith("Сохраню")


async def test_a_repeated_search_in_one_answer_runs_once(h: AiHarness) -> None:
    """The model asks the same thing twice; the tool runs once."""
    h.marks.summary = []
    chat = await h.new_chat()
    h.llm.push(
        tool_reply(("get_my_subjects", {})),
        tool_reply(("get_my_subjects", {})),
        text_reply("Готово."),
    )

    await h.say(chat.id, "Мои предметы?")

    calls = h.store.chat_messages(chat.id)[1].tool_calls
    assert len(calls) == 2 and "repeated" in (calls[1].result or {})
