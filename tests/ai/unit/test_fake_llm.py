"""OPENROUTER__MODE=fake: the deterministic gateway used in development and e2e."""

import json

from app.modules.ai.domain.prompts import SUMMARY_SYSTEM_PROMPT
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from tests.ai.conftest import HarnessFactory

SYSTEM = "You help students."


async def ask(fake: FakeLlmGateway, *messages: dict[str, str]) -> dict[str, object]:
    """One request."""
    return await fake.complete(
        model="m", system=SYSTEM, messages=list(messages), tools=[], max_tokens=100
    )


async def test_flash_asks_for_a_flashcard_set_with_three_cards() -> None:
    """UF-WEB-20: "flash" -> create_flashcard_set with 3 cards from the message."""
    result = await ask(
        FakeLlmGateway(), {"role": "user", "content": "Make flash cards on cells"}
    )

    call = result["tool_calls"][0]  # type: ignore[index]
    assert call["name"] == "create_flashcard_set"
    assert len(call["arguments"]["cards"]) == 3
    assert "cells" in call["arguments"]["title"]


async def test_homework_calls_the_homework_tool() -> None:
    """UF-WEB-19: "homework" -> get_homework."""
    result = await ask(FakeLlmGateway(), {"role": "user", "content": "what homework?"})

    assert result["tool_calls"][0]["name"] == "get_homework"  # type: ignore[index]


async def test_after_a_tool_result_it_summarizes_the_result() -> None:
    """The answer after a tool message quotes the tool result."""
    result = await ask(
        FakeLlmGateway(),
        {"role": "user", "content": "homework"},
        {"role": "tool", "content": json.dumps({"untrusted_data": {"items": []}})},
    )

    assert result["tool_calls"] == [] and "untrusted_data" in str(result["text"])


async def test_other_text_is_echoed_and_usage_is_characters_over_four() -> None:
    """Anything else is echoed; usage is characters // 4."""
    result = await ask(FakeLlmGateway(), {"role": "user", "content": "hello"})

    assert result["text"] == "(fake) hello"
    usage = result["usage"]
    assert usage["output"] == len("(fake) hello") // 4  # type: ignore[index]
    assert usage["input"] > 0  # type: ignore[index]


async def test_summaries_are_answered_with_a_fixed_text() -> None:
    """The summarizer request gets a summary, not an echo."""
    fake = FakeLlmGateway()

    result = await fake.complete(
        model="m",
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "<conversation/>"}],
        tools=[],
        max_tokens=10,
    )

    assert "summary" in str(result["text"])


async def test_the_whole_flow_runs_on_the_fake_gateway(
    make_harness: HarnessFactory,
) -> None:
    """UF-WEB-20 end to end with FakeLlmGateway: propose, approve, answer."""
    h = make_harness(llm=FakeLlmGateway())
    chat = await h.new_chat()

    proposed = await h.say(chat.id, "make flash cards about cells")
    call = proposed.new_messages[-1].tool_calls[0]
    done = await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=call.id
    )

    assert proposed.status.value == "awaiting_approval"
    assert done.status.value == "done"
    assert len(h.flashcards.create_calls) == 1
    assert done.new_messages[-1].text.startswith("(fake) Tool result")


async def test_the_fake_stream_ends_with_the_tool_calls_when_tools_are_given() -> None:
    gateway = FakeLlmGateway()
    messages = [{"role": "user", "content": "my homework?"}]

    items = [
        item
        async for item in gateway.stream(
            model="m", system="s", messages=messages, max_tokens=9, tools=[{"x": 1}]
        )
    ]

    assert items[-1]["tool_calls"][0]["name"] == "get_homework"
    assert "usage" in items[-1]
