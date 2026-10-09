"""The ScriptedLlm of the notebooks tests (tests/fakes/notebooks/llm.py)."""

import json
from typing import Any

from app.modules.ai.domain.errors import AiInvalidOutputError, AiProviderError
from tests.fakes.notebooks.llm import ScriptedLlm

import pytest

SOURCES = (
    '<sources>\n<source id="S1" title="T" kind="note">\n'
    "[S1:P1] Cells are small.\n</source>\n</sources>"
)
JSON_ARGS: dict[str, Any] = {
    "model": "m",
    "system": "You turn study sources into learning materials",
    "messages": [{"role": "user", "content": SOURCES}],
    "schema_name": "nb_data_table",
    "schema": {"type": "object"},
    "max_tokens": 50,
    "provider": {"data_collection": "deny"},
    "timeout_seconds": 180.0,
}
TEXT_ARGS: dict[str, Any] = {
    "model": "m",
    "system": "s",
    "messages": [{"role": "user", "content": "hi"}],
    "tools": [],
    "max_tokens": 5,
}
STREAM_ARGS: dict[str, Any] = {
    "model": "m",
    "system": "You are the notebook assistant of the IHSP student platform",
    "messages": [
        {"role": "user", "content": SOURCES},
        {"role": "user", "content": "Q?"},
    ],
    "max_tokens": 5,
}


async def collect(llm: ScriptedLlm, **kwargs: Any) -> list[dict[str, Any]]:
    """All items of a stream."""
    return [item async for item in llm.stream(**kwargs)]


async def test_queued_json_is_returned_once_with_text_and_usage() -> None:
    """The scripted document, its JSON text and the given usage."""
    llm = ScriptedLlm()
    llm.queue_json({"title": "Scripted"}, usage={"input": 7, "output": 3})

    result = await llm.complete_json(**JSON_ARGS)

    assert result["data"] == {"title": "Scripted"}
    assert result["text"] == json.dumps({"title": "Scripted"})
    assert result["usage"] == {"input": 7, "output": 3, "cached": 0, "cost_micro": None}
    assert llm.remaining == 0


async def test_json_falls_back_to_the_fake_when_the_queue_is_empty() -> None:
    """Unscripted calls still get a valid document."""
    llm = ScriptedLlm()
    llm.queue_json({"title": "First"})

    first = await llm.complete_json(**JSON_ARGS)
    second = await llm.complete_json(**JSON_ARGS)

    assert first["data"] == {"title": "First"}
    assert second["data"]["rows"][0]["refs"] == ["S1:P1"]
    assert llm.calls == 2


async def test_queued_errors_are_raised_in_queue_order() -> None:
    """An error, then a document: the first call fails, the retry works."""
    llm = ScriptedLlm()
    llm.queue_error(AiProviderError(support_details="HTTP 502"))
    llm.queue_json({"ok": True})
    llm.queue_json(AiInvalidOutputError())
    llm.queue_error(AiProviderError())

    with pytest.raises(AiProviderError):
        await llm.complete_json(**JSON_ARGS)
    assert (await llm.complete_json(**JSON_ARGS))["data"] == {"ok": True}
    with pytest.raises(AiInvalidOutputError):
        await llm.complete_json(**JSON_ARGS)
    with pytest.raises(AiProviderError):
        await llm.complete_json(**JSON_ARGS)
    assert llm.calls == 4 and llm.remaining == 0


async def test_queued_text_is_returned_as_a_plain_answer() -> None:
    """complete() gives text, no tool calls and the default usage."""
    llm = ScriptedLlm()
    llm.queue_text("Scripted answer [[S1:P1]]")

    result = await llm.complete(**TEXT_ARGS)
    fallback = await llm.complete(**TEXT_ARGS)

    assert result["text"] == "Scripted answer [[S1:P1]]"
    assert result["tool_calls"] == [] and result["usage"]["input"] == 100
    assert fallback["text"] == "(fake) hi"


async def test_queued_stream_yields_the_chunks_then_the_usage() -> None:
    """Deltas in order, the usage last."""
    llm = ScriptedLlm()
    llm.queue_stream(["Hel", "lo ", "[[S1"], usage={"input": 9, "output": 4})

    items = await collect(llm, **STREAM_ARGS)

    assert items == [
        {"delta": "Hel"},
        {"delta": "lo "},
        {"delta": "[[S1"},
        {"usage": {"input": 9, "output": 4, "cached": 0, "cost_micro": None}},
    ]


async def test_a_stream_can_fail_in_the_middle() -> None:
    """An exception among the chunks raises when it is reached."""
    llm = ScriptedLlm()
    llm.queue_stream(["Partial ", AiProviderError(support_details="cut")])
    seen: list[dict[str, Any]] = []

    with pytest.raises(AiProviderError):
        async for item in llm.stream(**STREAM_ARGS):
            seen.append(item)

    assert seen == [{"delta": "Partial "}]


async def test_a_stream_error_raised_at_the_start_and_the_fallback_stream() -> None:
    """queue_error fails the next stream; afterwards the fake streams a cited answer."""
    llm = ScriptedLlm()
    llm.queue_error(AiProviderError())

    with pytest.raises(AiProviderError):
        await collect(llm, **STREAM_ARGS)
    items = await collect(llm, **STREAM_ARGS)

    assert "".join(i["delta"] for i in items[:-1]).startswith(
        "(fake) Cells are small. [[S1:P1]]"
    )
    assert "usage" in items[-1] and llm.calls == 2


async def test_requests_are_recorded_by_kind_with_every_argument() -> None:
    """The tests inspect system, messages, schema_name, provider and model."""
    llm = ScriptedLlm()

    await llm.complete_json(**JSON_ARGS)
    await llm.complete(**TEXT_ARGS)
    await collect(llm, **STREAM_ARGS)

    assert llm.json_requests == [JSON_ARGS]
    assert llm.text_requests == [TEXT_ARGS]
    assert llm.stream_requests == [STREAM_ARGS]
    assert llm.json_requests[0]["provider"] == {"data_collection": "deny"}
    assert llm.json_requests[0]["schema_name"] == "nb_data_table"
    assert llm.calls == 3


async def test_answers_of_other_kinds_are_not_consumed() -> None:
    """A queued stream does not answer a JSON call."""
    llm = ScriptedLlm()
    llm.queue_stream(["only stream"])

    await llm.complete_json(**JSON_ARGS)

    assert llm.remaining == 1
