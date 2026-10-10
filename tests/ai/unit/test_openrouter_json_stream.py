"""NB-ADAPTERS: structured JSON, streaming, provider routing and cost (respx)."""

import json
from collections.abc import AsyncIterator
from typing import Any

from app.modules.ai.domain.errors import AiInvalidOutputError, AiProviderError
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway

import httpx
import pytest
import respx

URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-haiku-4.5"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}
PROVIDER = {"data_collection": "deny", "require_parameters": True}
SECRET_TEXT = "the secret passage about mitochondria"


class Sleeps:
    """Records how long the adapter waited between attempts."""

    def __init__(self) -> None:
        """Start with no sleeps."""
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        """Record instead of sleeping."""
        self.seconds.append(seconds)


@pytest.fixture
def sleeps() -> Sleeps:
    """The recorded waits."""
    return Sleeps()


@pytest.fixture
def gateway(sleeps: Sleeps) -> OpenRouterGateway:
    """An adapter with a test key, a 5 s default timeout and no real waiting."""
    return OpenRouterGateway(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        app_url="https://my.ihsu.uz",
        app_title="IHT",
        timeout_seconds=5,
        sleep=sleeps,
    )


def completion(content: str, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    """A non-streaming response with the given message content."""
    return {
        "id": "gen-1",
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20},
    }


async def ask_json(
    gateway: OpenRouterGateway,
    *,
    model: str = MODEL,
    provider: dict[str, Any] | None = PROVIDER,
    timeout_seconds: float | None = 180,
) -> dict[str, Any]:
    """One structured request."""
    return await gateway.complete_json(
        model=model,
        system="You turn study sources into learning materials.",
        messages=[{"role": "user", "content": SECRET_TEXT}],
        schema_name="nb_report",
        schema=SCHEMA,
        max_tokens=3000,
        provider=provider,
        timeout_seconds=timeout_seconds,
    )


def body_of(route: respx.Route) -> dict[str, Any]:
    """The JSON body of the last request."""
    body: dict[str, Any] = json.loads(route.calls.last.request.content)
    return body


# - - - complete_json - - -


@respx.mock
async def test_json_request_asks_for_a_strict_schema_with_the_provider_options(
    gateway: OpenRouterGateway,
) -> None:
    """NB-ADAPTERS: response_format json_schema strict, provider, max_tokens."""
    route = respx.post(URL).respond(200, json=completion('{"title": "Cells"}'))

    result = await ask_json(gateway)

    body = body_of(route)
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "nb_report", "strict": True, "schema": SCHEMA},
    }
    assert body["provider"] == PROVIDER
    assert body["max_tokens"] == 3000 and body["model"] == MODEL
    assert "tools" not in body and "tool_choice" not in body
    assert "stream" not in body
    assert body["messages"][1] == {"role": "user", "content": SECRET_TEXT}
    assert result["data"] == {"title": "Cells"}
    assert result["text"] == '{"title": "Cells"}'
    assert result["usage"] == {"input": 100, "output": 20, "cached": 0}


@respx.mock
async def test_json_request_without_a_provider_sends_no_provider_object(
    gateway: OpenRouterGateway,
) -> None:
    """The provider object is optional."""
    route = respx.post(URL).respond(200, json=completion("{}"))

    await ask_json(gateway, provider=None)

    assert "provider" not in body_of(route)


@respx.mock
async def test_the_per_request_timeout_overrides_the_client_default(
    gateway: OpenRouterGateway,
) -> None:
    """NOTEBOOKS__LLM_TIMEOUT_SECONDS=180 beats the 90 s chat default."""
    route = respx.post(URL).respond(200, json=completion("{}"))

    await ask_json(gateway, timeout_seconds=180)
    long = route.calls.last.request.extensions["timeout"]
    await ask_json(gateway, timeout_seconds=None)
    default = route.calls.last.request.extensions["timeout"]

    assert long["read"] == 180 and long["connect"] == 10
    assert default["read"] == 5


@respx.mock
@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"title": "Fenced"}\n```',
        '```\n{"title": "Fenced"}\n```',
        'Here is the document:\n```json\n{"title": "Fenced"}\n```\nHope it helps!',
        'Sure! {"title": "Fenced"} Let me know.',
        '  \n{"title": "Fenced"}\n',
    ],
)
async def test_json_is_found_inside_a_fence_or_surrounding_text(
    gateway: OpenRouterGateway, content: str
) -> None:
    """The object is parsed even when the model wraps it in Markdown or prose."""
    respx.post(URL).respond(200, json=completion(content))

    result = await ask_json(gateway)

    assert result["data"] == {"title": "Fenced"}
    assert result["text"] == content


@respx.mock
@pytest.mark.parametrize(
    "content", ["", "I cannot do that.", "[1, 2, 3]", '"just a string"', '{"title": ']
)
async def test_an_answer_without_a_json_object_is_an_invalid_output(
    gateway: OpenRouterGateway, content: str
) -> None:
    """NB-ADAPTERS: not a JSON object -> AiInvalidOutputError (422), no text echoed."""
    respx.post(URL).respond(200, json=completion(content))

    with pytest.raises(AiInvalidOutputError) as caught:
        await ask_json(gateway)

    assert caught.value.status == 422
    assert content not in caught.value.support_details or content == ""


@respx.mock
async def test_usage_cost_is_returned_in_micro_dollars_only_when_sent(
    gateway: OpenRouterGateway,
) -> None:
    """usage.cost (USD) -> cost_micro; no cost -> the key is absent."""
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "prompt_tokens_details": {"cached_tokens": 800},
        "cost": 0.0012345,
    }
    respx.post(URL).respond(200, json=completion("{}", usage))

    with_cost = await ask_json(gateway)
    respx.post(URL).respond(200, json=completion("{}"))
    without = await ask_json(gateway)

    assert with_cost["usage"] == {
        "input": 1000,
        "output": 200,
        "cached": 800,
        "cost_micro": 1234,
    }
    assert "cost_micro" not in without["usage"]


@respx.mock
async def test_json_provider_failures_use_the_same_retry_policy_as_complete(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """429 is retried once after Retry-After; a second failure is a provider error."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(
                429,
                json={"error": {"code": 429, "message": "slow down"}},
                headers={"Retry-After": "3"},
            ),
            httpx.Response(200, json=completion('{"title": "ok"}')),
        ]
    )

    result = await ask_json(gateway)

    assert route.call_count == 2 and sleeps.seconds == [3.0]
    assert result["data"] == {"title": "ok"}


@respx.mock
async def test_json_server_error_twice_raises_a_provider_error(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """502 twice -> ai/provider-error; the prompt is not echoed."""
    route = respx.post(URL).respond(
        502, json={"error": {"code": 502, "message": "bad gateway"}}
    )

    with pytest.raises(AiProviderError) as caught:
        await ask_json(gateway)

    assert route.call_count == 2 and sleeps.seconds == [2.0]
    assert caught.value.status == 503
    assert SECRET_TEXT not in caught.value.support_details


@respx.mock
async def test_json_client_errors_and_errors_in_a_200_are_provider_errors(
    gateway: OpenRouterGateway,
) -> None:
    """401 is not retried; choices[0].error after HTTP 200 is detected."""
    route = respx.post(URL).respond(401, json={"error": {"message": "bad key"}})
    with pytest.raises(AiProviderError):
        await ask_json(gateway)
    assert route.call_count == 1

    respx.post(URL).respond(
        200,
        json={
            "choices": [
                {"finish_reason": "error", "error": {"message": "upstream failed"}}
            ]
        },
    )
    with pytest.raises(AiProviderError, match="upstream failed"):
        await ask_json(gateway)


@respx.mock
async def test_complete_sends_the_provider_object_only_when_given(
    gateway: OpenRouterGateway,
) -> None:
    """The assistants pass nothing, so their requests stay unchanged."""
    route = respx.post(URL).respond(200, json=completion("hi"))

    await gateway.complete(
        model=MODEL, system="s", messages=[], tools=[], max_tokens=10
    )
    plain = body_of(route)
    await gateway.complete(
        model=MODEL,
        system="s",
        messages=[],
        tools=[],
        max_tokens=10,
        provider=PROVIDER,
    )
    routed = body_of(route)

    assert "provider" not in plain
    assert routed["provider"] == PROVIDER


# - - - stream - - -


def event(data: dict[str, Any] | str) -> str:
    """One server-sent event line."""
    return f"data: {data if isinstance(data, str) else json.dumps(data)}\n\n"


def delta(text: str, finish: str | None = None) -> dict[str, Any]:
    """A streamed chunk with a piece of text."""
    return {
        "id": "gen-1",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}],
    }


def usage_chunk(**usage: Any) -> dict[str, Any]:
    """The last chunk: no choices, only usage."""
    return {"id": "gen-1", "choices": [], "usage": usage}


def sse(*parts: str) -> httpx.Response:
    """A 200 event stream response."""
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(parts).encode(),
    )


async def collect(
    gateway: OpenRouterGateway, **extra: Any
) -> tuple[list[dict[str, Any]], BaseException | None]:
    """Read a whole stream; return the items and the error that ended it."""
    items: list[dict[str, Any]] = []
    try:
        async for item in gateway.stream(
            model=MODEL,
            system="You are the notebook assistant.",
            messages=[{"role": "user", "content": SECRET_TEXT}],
            max_tokens=1200,
            provider={"data_collection": "deny"},
            **extra,
        ):
            items.append(item)
    except (AiProviderError, AiInvalidOutputError) as exc:
        return items, exc
    return items, None


@respx.mock
async def test_stream_request_asks_for_events_with_usage(
    gateway: OpenRouterGateway,
) -> None:
    """NB-ADAPTERS: stream true, include_usage, provider, no tools or schema."""
    route = respx.post(URL).mock(return_value=sse(event(delta("a")), event("[DONE]")))

    await collect(gateway)

    body = body_of(route)
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["provider"] == {"data_collection": "deny"}
    assert body["max_tokens"] == 1200
    assert "tools" not in body and "response_format" not in body
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk-test"


@respx.mock
async def test_stream_yields_deltas_then_the_usage(
    gateway: OpenRouterGateway,
) -> None:
    """Keep-alives, blank lines, empty deltas and event fields are ignored."""
    stream = (
        ": OPENROUTER PROCESSING\n\n"
        + event({"choices": [{"delta": {"role": "assistant", "content": ""}}]})
        + ": keep-alive\n\n"
        + "event: message\n"
        + event(delta("Hello "))
        + "\n\n"
        + event(delta("world", "stop"))
        + event(
            usage_chunk(
                prompt_tokens=50,
                completion_tokens=7,
                prompt_tokens_details={"cached_tokens": 40},
                cost=0.000321,
            )
        )
        + event("[DONE]")
        + event(delta("never read"))
    )
    respx.post(URL).mock(return_value=sse(stream))

    items, error = await collect(gateway)

    assert error is None
    assert items == [
        {"delta": "Hello "},
        {"delta": "world"},
        {"usage": {"input": 50, "output": 7, "cached": 40, "cost_micro": 321}},
    ]


@respx.mock
async def test_stream_without_a_usage_chunk_ends_with_zero_usage(
    gateway: OpenRouterGateway,
) -> None:
    """Some providers send no usage; the last item is still a usage item."""
    respx.post(URL).mock(return_value=sse(event(delta("Hi", "stop")), event("[DONE]")))

    items, error = await collect(gateway)

    assert error is None
    assert items == [
        {"delta": "Hi"},
        {"usage": {"input": 0, "output": 0, "cached": 0}},
    ]


@respx.mock
async def test_the_stream_timeout_is_per_request(gateway: OpenRouterGateway) -> None:
    """timeout_seconds applies to the streamed request too."""
    route = respx.post(URL).mock(return_value=sse(event(delta("a", "stop"))))

    await collect(gateway, timeout_seconds=180)

    assert route.calls.last.request.extensions["timeout"]["read"] == 180


@respx.mock
async def test_an_error_object_inside_the_stream_is_a_provider_error(
    gateway: OpenRouterGateway,
) -> None:
    """NB-ADAPTERS: an error after some text is not retried and ends the stream."""
    route = respx.post(URL).mock(
        return_value=sse(
            event(delta("Partial ")),
            event(
                {
                    "error": {"code": 500, "message": "upstream died"},
                    "choices": [{"delta": {"content": ""}, "finish_reason": "error"}],
                }
            ),
        )
    )

    items, error = await collect(gateway)

    assert items == [{"delta": "Partial "}]
    assert isinstance(error, AiProviderError) and "upstream died" in str(error)
    assert route.call_count == 1


@respx.mock
async def test_a_non_200_status_is_a_provider_error_without_retry_for_4xx(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """401 fails at once and never echoes the prompt."""
    route = respx.post(URL).respond(401, json={"error": {"message": "bad key"}})

    items, error = await collect(gateway)

    assert items == []
    assert isinstance(error, AiProviderError) and error.status == 503
    assert SECRET_TEXT not in error.support_details
    assert route.call_count == 1 and sleeps.seconds == []


@respx.mock
async def test_a_busy_provider_is_retried_once_before_the_first_delta(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """429 with Retry-After: wait, then stream normally."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(
                429,
                json={"error": {"message": "rate limited"}},
                headers={"Retry-After": "4"},
            ),
            sse(event(delta("ok", "stop")), event("[DONE]")),
        ]
    )

    items, error = await collect(gateway)

    assert error is None and items[0] == {"delta": "ok"}
    assert route.call_count == 2 and sleeps.seconds == [4.0]


@respx.mock
async def test_a_connection_failure_before_the_first_delta_is_retried_once(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """One retry, then success."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.ConnectError("refused"),
            sse(event(delta("ok", "stop")), event("[DONE]")),
        ]
    )

    items, error = await collect(gateway)

    assert error is None and items[0] == {"delta": "ok"}
    assert route.call_count == 2 and sleeps.seconds == [2.0]


@respx.mock
async def test_two_connection_failures_are_a_provider_error(
    gateway: OpenRouterGateway,
) -> None:
    """Only one retry."""
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))

    items, error = await collect(gateway)

    assert items == [] and isinstance(error, AiProviderError)
    assert route.call_count == 2


class BrokenStream(httpx.AsyncByteStream):
    """A response body that delivers one event, then the connection drops."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield the first event, then fail like a dropped connection."""
        yield event(delta("Half ")).encode()
        raise httpx.ReadError("connection reset")


@respx.mock
async def test_a_drop_after_the_first_delta_is_not_retried(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """A retry would repeat text the student already saw."""
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, stream=BrokenStream())
    )

    items, error = await collect(gateway)

    assert items == [{"delta": "Half "}]
    assert isinstance(error, AiProviderError)
    assert route.call_count == 1 and sleeps.seconds == []


@respx.mock
async def test_a_stream_cut_off_without_a_finish_is_a_provider_error(
    gateway: OpenRouterGateway,
) -> None:
    """No finish_reason and no [DONE]: the answer is incomplete."""
    respx.post(URL).mock(return_value=sse(event(delta("Cut "))))

    items, error = await collect(gateway)

    assert items == [{"delta": "Cut "}]
    assert isinstance(error, AiProviderError) and "early" in str(error)


@respx.mock
async def test_a_chunk_that_is_not_json_is_a_provider_error(
    gateway: OpenRouterGateway,
) -> None:
    """Garbage in the stream does not leak into the answer."""
    respx.post(URL).mock(return_value=sse("data: {not json\n\n"))

    items, error = await collect(gateway)

    assert items == [] and isinstance(error, AiProviderError)


@respx.mock
async def test_a_consumer_that_stops_early_leaves_the_gateway_usable(
    gateway: OpenRouterGateway,
) -> None:
    """The student closes the tab: the generator is closed, the next call works."""
    route = respx.post(URL).mock(
        return_value=sse(
            event(delta("one ")), event(delta("two ")), event(delta("x", "stop"))
        )
    )

    stream = gateway.stream(
        model=MODEL, system="s", messages=[], max_tokens=10, provider=None
    )
    first = await anext(stream)
    await stream.aclose()
    items, error = await collect(gateway)

    assert first == {"delta": "one "}
    assert error is None and items[0] == {"delta": "one "}
    assert route.call_count == 2
