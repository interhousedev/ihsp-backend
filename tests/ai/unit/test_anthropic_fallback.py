"""Anthropic fallback: the Messages API adapter and the OpenRouter fallback rule."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from app.modules.ai.domain.errors import AiProviderError
from app.modules.ai.infrastructure.anthropic_gateway import (
    AnthropicLlmGateway,
    build_request,
)
from app.modules.ai.infrastructure.fallback_gateway import (
    FallbackLlmGateway,
    is_limit_error,
    is_overload_error,
    mapped_models,
    same_model,
)
from app.modules.ai.infrastructure.gateway_factory import (
    make_embedding_gateway,
    make_llm_gateway,
)
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.modules.ai.infrastructure.openrouter_embeddings import OpenRouterEmbeddings
from app.settings import AnthropicSettings, Settings
from app.shared.contracts.ai import LlmTuning

import pytest

HAIKU = "anthropic/claude-haiku-5.5"
TARGET = "claude-haiku-5-5"


def _usage(**counts: int) -> SimpleNamespace:
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    return SimpleNamespace(**{**base, **counts})


class FakeStream:
    """The async context manager `messages.stream` returns."""

    def __init__(
        self, texts: list[str], usage: SimpleNamespace, content: list[Any] | None = None
    ) -> None:
        """Keep the deltas, the final usage and the final content blocks."""
        self._texts = texts
        self._usage = usage
        self._content = content or []

    async def __aenter__(self) -> "FakeStream":
        """Open."""
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Close."""

    @property
    def text_stream(self) -> AsyncIterator[str]:
        """The text deltas."""
        return self._gen()

    async def _gen(self) -> AsyncIterator[str]:
        for text in self._texts:
            yield text

    async def get_final_message(self) -> SimpleNamespace:
        """The final message: its content blocks and usage."""
        return SimpleNamespace(usage=self._usage, content=self._content)


class FakeMessages:
    """Records the keyword arguments of each call."""

    def __init__(self, response: Any = None, stream: Any = None) -> None:
        """Answer every call with `response` / `stream`."""
        self.calls: list[dict[str, Any]] = []
        self._response = response
        self._stream = stream

    async def create(self, **params: Any) -> Any:
        """Record and answer."""
        self.calls.append(params)
        return self._response

    def stream(self, **params: Any) -> Any:
        """Record and answer."""
        self.calls.append(params)
        return self._stream


def _gateway(messages: FakeMessages) -> AnthropicLlmGateway:
    client = SimpleNamespace(messages=messages)
    return AnthropicLlmGateway(api_key="k", timeout_seconds=5, client=client)


def test_messages_tools_and_cache_marks_are_translated() -> None:
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "ctx", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "q"},
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "find", "arguments": '{"q": "x"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "found"},
    ]
    tools = [
        {
            "type": "function",
            "function": {"name": "find", "description": "d", "parameters": {"a": 1}},
        }
    ]
    params = build_request(
        TARGET, "sys", messages, tools, 100, LlmTuning(temperature=0.2)
    )

    assert params["system"] == [
        {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
    ]
    assert params["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "ctx", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "q"},
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "c1", "name": "find", "input": {"q": "x"}}
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": "found"}
            ],
        },
    ]
    assert params["tools"] == [
        {"name": "find", "input_schema": {"a": 1}, "description": "d"}
    ]
    assert params["tool_choice"] == {"type": "auto"}
    assert "temperature" not in params and "thinking" not in params


def test_reasoning_none_disables_thinking_at_low_effort() -> None:
    params = build_request(TARGET, "s", [], [], 10, LlmTuning(reasoning_effort="none"))
    assert params["thinking"] == {"type": "disabled"}
    assert params["output_config"] == {"effort": "low"}


async def test_complete_maps_text_tool_calls_and_usage() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="hi"),
            SimpleNamespace(type="tool_use", id="t1", name="find", input={"q": 1}),
        ],
        usage=_usage(
            input_tokens=1000,
            output_tokens=200,
            cache_read_input_tokens=10_000,
            cache_creation_input_tokens=0,
        ),
    )
    messages = FakeMessages(response=response)
    result = await _gateway(messages).complete(
        model=TARGET, system="s", messages=[], tools=[], max_tokens=10
    )

    assert result["text"] == "hi"
    assert result["tool_calls"] == [{"id": "t1", "name": "find", "arguments": {"q": 1}}]
    usage = result["usage"]
    assert (usage["input"], usage["output"], usage["cached"]) == (11_000, 200, 10_000)
    # 1000 * 0.10 + 10000 * 0.01 + 200 * 0.50 micro-dollars
    assert usage["cost_micro"] == 300
    assert usage["model"] == TARGET and usage["provider"] == "anthropic"


async def test_stream_yields_deltas_then_usage() -> None:
    stream = FakeStream(["a", "", "b"], _usage(input_tokens=5, output_tokens=2))
    messages = FakeMessages(stream=stream)
    items = [
        item
        async for item in _gateway(messages).stream(
            model=TARGET, system="s", messages=[], max_tokens=10, timeout_seconds=3
        )
    ]
    assert items[:2] == [{"delta": "a"}, {"delta": "b"}]
    assert items[2]["usage"]["input"] == 5 and items[2]["usage"]["output"] == 2
    assert messages.calls[0]["timeout"] == 3


class Scripted:
    """A gateway that fails with `error` or answers, and records the models."""

    def __init__(self, error: Exception | None = None, deltas: int = 0) -> None:
        """`deltas` items are streamed before `error` is raised."""
        self.models: list[str] = []
        self._error = error
        self._deltas = deltas

    async def complete(self, *, model: str, **_: Any) -> dict[str, Any]:
        """Fail or answer."""
        self.models.append(model)
        if self._error:
            raise self._error
        return {"text": model, "tool_calls": [], "usage": {}}

    async def complete_json(self, *, model: str, **_: Any) -> dict[str, Any]:
        """Fail or answer."""
        self.models.append(model)
        if self._error:
            raise self._error
        return {"data": {}, "text": model, "usage": {}}

    async def stream(self, *, model: str, **_: Any) -> AsyncIterator[dict[str, Any]]:
        """Stream `deltas` items, then fail or end."""
        self.models.append(model)
        for _index in range(self._deltas):
            yield {"delta": model}
        if self._error:
            raise self._error
        yield {"usage": {"model": model}}


def _fallback(error: Exception, deltas: int = 0) -> tuple[Any, Scripted, Scripted]:
    primary, backup = Scripted(error, deltas), Scripted()
    gateway = FallbackLlmGateway(
        primary,
        backup,
        primary_route=same_model,
        secondary_route=mapped_models({HAIKU: TARGET}),
        switch_on=is_limit_error,
    )
    return gateway, primary, backup


def _anthropic_first(
    error: Exception, deltas: int = 0
) -> tuple[Any, Scripted, Scripted]:
    """Mode `default`: the mapped model on Anthropic (primary), OpenRouter after."""
    anthropic, openrouter = Scripted(error, deltas), Scripted()
    gateway = FallbackLlmGateway(
        anthropic,
        openrouter,
        primary_route=mapped_models({HAIKU: TARGET}),
        secondary_route=same_model,
        switch_on=is_overload_error,
    )
    return gateway, anthropic, openrouter


@pytest.mark.parametrize(
    "error",
    [
        AiProviderError(params={"status": 529}),
        AiProviderError(params={"status": 429}),
        AiProviderError(params={"status": 500}),
        AiProviderError(params={"status": 503}),
    ],
)
async def test_default_mode_overload_falls_back_to_openrouter(
    error: AiProviderError,
) -> None:
    gateway, anthropic, openrouter = _anthropic_first(error)
    result = await gateway.complete(model=HAIKU, **ARGS)
    assert result["text"] == HAIKU
    assert (anthropic.models, openrouter.models) == ([TARGET], [HAIKU])


@pytest.mark.parametrize(
    "error",
    [AiProviderError(params={"status": 400}), AiProviderError(params={"status": 401})],
)
async def test_default_mode_other_anthropic_errors_propagate(error: Exception) -> None:
    gateway, _, openrouter = _anthropic_first(error)
    with pytest.raises(type(error)):
        await gateway.complete(model=HAIKU, **ARGS)
    assert openrouter.models == []


async def test_default_mode_sends_unmapped_models_to_openrouter_only() -> None:
    gateway, anthropic, openrouter = _anthropic_first(_status(529))
    result = await gateway.complete(model="google/gemini-3.8-flash", **ARGS)
    assert result["text"] == "google/gemini-3.8-flash"
    assert anthropic.models == [] and openrouter.models == ["google/gemini-3.8-flash"]


async def test_default_mode_stream_falls_back_only_before_the_first_delta() -> None:
    gateway, _, openrouter = _anthropic_first(_status(529))
    items = [i async for i in gateway.stream(model=HAIKU, **_stream_args())]
    assert items == [{"usage": {"model": HAIKU}}]
    assert openrouter.models == [HAIKU]

    gateway, _, openrouter = _anthropic_first(_status(529), deltas=1)
    with pytest.raises(AiProviderError):
        _ = [i async for i in gateway.stream(model=HAIKU, **_stream_args())]
    assert openrouter.models == []


def test_the_default_mode_factory_puts_anthropic_first_and_keeps_openrouter() -> None:
    real = {"mode": "real", "api_key": "sk-or"}
    keyed = Settings(
        openrouter=real, anthropic={"mode": "default", "api_key": "sk-ant"}
    )
    gateway = make_llm_gateway(keyed)
    assert isinstance(gateway, FallbackLlmGateway)
    assert isinstance(gateway.first, AnthropicLlmGateway)
    assert isinstance(gateway.second, OpenRouterGateway)
    # the embeddings keep the OpenRouter connection even when Anthropic is first
    assert isinstance(make_embedding_gateway(keyed, gateway), OpenRouterEmbeddings)


def test_default_mode_without_the_key_stops_the_start() -> None:
    real = {"mode": "real", "api_key": "sk-or"}
    keyless = Settings(openrouter=real, anthropic={"mode": "default"})
    with pytest.raises(ValueError, match="ANTHROPIC__API_KEY is required"):
        make_llm_gateway(keyless)
    # a process that holds no key (the bot) starts on OpenRouter alone
    assert isinstance(make_llm_gateway(keyless, required=False), OpenRouterGateway)


def test_default_mode_without_the_key_is_a_startup_problem_of_the_ai_processes() -> (
    None
):
    real = {"mode": "real", "api_key": "sk-or"}
    exa = {"mode": "real", "api_key": "exa-key"}
    settings = Settings(openrouter=real, exa=exa, anthropic={"mode": "default"})
    assert settings._missing_for("api") == [
        "ANTHROPIC__API_KEY (ANTHROPIC__MODE=default)"
    ]
    assert settings._missing_for("bot") == []


def test_the_mode_is_parsed_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().anthropic.mode == "fallback"
    monkeypatch.setenv("IHSP_ANTHROPIC__MODE", "default")
    assert Settings().anthropic.mode == "default"
    monkeypatch.setenv("IHSP_ANTHROPIC__MODE", "sometimes")
    with pytest.raises(ValueError):
        Settings()


def test_default_mode_is_active_without_the_fallback_flag() -> None:
    config = AnthropicSettings(mode="default", api_key="k", fallback_enabled=False)
    assert config.active
    assert not AnthropicSettings(
        mode="fallback", api_key="k", fallback_enabled=False
    ).active


def _status(status: int, text: str = "") -> AiProviderError:
    return AiProviderError(params={"status": status}, support_details=text)


ARGS: dict[str, Any] = {"system": "s", "messages": [], "tools": [], "max_tokens": 9}


@pytest.mark.parametrize(
    "error",
    [_status(402), _status(429), _status(403, "HTTP 403: Key limit exceeded")],
)
async def test_limit_errors_fall_back_with_the_mapped_model(
    error: AiProviderError,
) -> None:
    gateway, primary, backup = _fallback(error)
    result = await gateway.complete(model=HAIKU, **ARGS)
    assert result["text"] == TARGET
    assert (primary.models, backup.models) == ([HAIKU], [TARGET])


@pytest.mark.parametrize("error", [_status(500), _status(400), ValueError("x")])
async def test_other_errors_propagate(error: Exception) -> None:
    gateway, _, backup = _fallback(error)
    with pytest.raises(type(error)):
        await gateway.complete(model=HAIKU, **ARGS)
    assert backup.models == []


async def test_models_outside_the_map_do_not_fall_back() -> None:
    gateway, _, backup = _fallback(_status(402))
    with pytest.raises(AiProviderError):
        await gateway.complete_json(
            model="google/gemini-3.8-flash",
            system="s",
            messages=[],
            schema_name="n",
            schema={},
            max_tokens=9,
        )
    assert backup.models == []


async def test_a_stream_falls_back_only_before_the_first_delta() -> None:
    gateway, _, backup = _fallback(_status(402))
    items = [i async for i in gateway.stream(model=HAIKU, **_stream_args())]
    assert items == [{"usage": {"model": TARGET}}]

    gateway, _, backup = _fallback(_status(402), deltas=1)
    with pytest.raises(AiProviderError):
        _ = [i async for i in gateway.stream(model=HAIKU, **_stream_args())]
    assert backup.models == []


def _stream_args() -> dict[str, Any]:
    return {"system": "s", "messages": [], "max_tokens": 9}


def test_the_factory_wraps_openrouter_only_with_an_anthropic_key() -> None:
    real = {"mode": "real", "api_key": "sk-or"}
    plain = make_llm_gateway(Settings(openrouter=real))
    assert not isinstance(plain, FallbackLlmGateway)

    keyed = Settings(openrouter=real, anthropic={"api_key": "sk-ant"})
    assert isinstance(make_llm_gateway(keyed), FallbackLlmGateway)

    off = Settings(
        openrouter=real, anthropic={"api_key": "sk-ant", "fallback_enabled": False}
    )
    assert not isinstance(make_llm_gateway(off), FallbackLlmGateway)


def test_the_model_map_is_parsed_and_an_empty_key_means_no_fallback() -> None:
    config = AnthropicSettings(model_map=" a=b , c=d ", api_key="")
    assert config.models == {"a": "b", "c": "d"}
    assert not config.active
    assert AnthropicSettings().models == {HAIKU: TARGET}


async def test_stream_with_tools_ends_with_the_tool_use_blocks() -> None:
    """Text from `text_stream`; tool_use blocks from the final message."""
    block = SimpleNamespace(type="tool_use", id="tu1", name="get_marks", input={"a": 1})
    text = SimpleNamespace(type="text", text="Looking.")
    stream = FakeStream(["Looking."], _usage(input_tokens=5), [text, block])
    messages = FakeMessages(stream=stream)
    tools = [{"type": "function", "function": {"name": "get_marks", "parameters": {}}}]

    items = [
        item
        async for item in _gateway(messages).stream(
            model=TARGET, system="s", messages=[], max_tokens=10, tools=tools
        )
    ]

    assert items[0] == {"delta": "Looking."}
    assert items[-1]["tool_calls"] == [
        {"id": "tu1", "name": "get_marks", "arguments": {"a": 1}}
    ]
    assert messages.calls[0]["tools"][0]["name"] == "get_marks"
    assert messages.calls[0]["tool_choice"] == {"type": "auto"}


async def test_the_fallback_stream_passes_the_tools_on() -> None:
    """The tools reach the gateway that streams."""
    seen: list[Any] = []

    class Spy(Scripted):
        async def stream(  # type: ignore[override]
            self, *, model: str, **kwargs: Any
        ) -> AsyncIterator[dict[str, Any]]:
            seen.append(kwargs.get("tools"))
            yield {"usage": {}, "tool_calls": [{"id": "x", "name": "t"}]}

    gateway = FallbackLlmGateway(
        Spy(),
        Scripted(),
        primary_route=same_model,
        secondary_route=same_model,
        switch_on=is_limit_error,
    )
    tools = [{"type": "function", "function": {"name": "t"}}]

    items = [
        i async for i in gateway.stream(model=HAIKU, **_stream_args(), tools=tools)
    ]

    assert seen == [tools] and items[-1]["tool_calls"][0]["name"] == "t"
