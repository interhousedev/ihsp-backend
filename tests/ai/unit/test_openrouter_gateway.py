"""AI-13: the OpenRouter adapter against recorded-shape responses (respx)."""

import json
from pathlib import Path
from typing import Any

from app.modules.ai.domain.errors import AiProviderError
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.shared.contracts.ai import LlmTuning

import httpx
import pytest
import respx

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openrouter"
URL = "https://openrouter.ai/api/v1/chat/completions"
TOOLS = [{"type": "function", "function": {"name": "get_marks", "parameters": {}}}]


def fixture(name: str) -> dict[str, Any]:
    """Load a recorded response."""
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


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
    """An adapter with a test key and no real waiting."""
    return OpenRouterGateway(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        app_url="https://my.ihsu.uz",
        app_title="IHT",
        timeout_seconds=5,
        sleep=sleeps,
    )


async def ask(
    gateway: OpenRouterGateway, model: str = "anthropic/claude-haiku-5.5"
) -> Any:
    """One request with a user message and the tool list."""
    return await gateway.complete(
        model=model,
        system="You help students.",
        messages=[{"role": "user", "content": "marks?"}],
        tools=TOOLS,
        max_tokens=512,
    )


@respx.mock
async def test_tool_calls_and_usage_are_mapped(gateway: OpenRouterGateway) -> None:
    """AI-13: text, parsed tool arguments and usage with cached tokens."""
    route = respx.post(URL).respond(200, json=fixture("completion_tool_calls"))

    result = await ask(gateway)

    assert route.called
    assert result["text"] == "Let me check your marks."
    assert result["tool_calls"] == [
        {"id": "toolu_01A", "name": "get_marks", "arguments": {"from": "2026-09-01"}},
        {"id": "toolu_01B", "name": "get_homework", "arguments": {}},
    ]
    assert result["usage"] == {
        "input": 10339,
        "output": 60,
        "cached": 10318,
        "cost_micro": 140,  # usage.cost 0.00014 USD
    }


@respx.mock
async def test_request_has_headers_tools_and_a_cache_breakpoint(
    gateway: OpenRouterGateway,
) -> None:
    """AI-13, AI-9: attribution headers, tools, tool_choice, cached system prompt."""
    route = respx.post(URL).respond(200, json=fixture("completion_text"))

    result = await ask(gateway)

    request = route.calls.last.request
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer sk-test"
    assert request.headers["http-referer"] == "https://my.ihsu.uz"
    assert request.headers["x-openrouter-title"] == "IHT"
    assert body["model"] == "anthropic/claude-haiku-5.5" and body["max_tokens"] == 512
    assert body["tools"] == TOOLS and body["tool_choice"] == "auto"
    system = body["messages"][0]
    assert system["role"] == "system"
    assert system["content"] == [
        {
            "type": "text",
            "text": "You help students.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert body["messages"][1] == {"role": "user", "content": "marks?"}
    assert result["text"] == "You have two marks: 5 and 4."
    assert result["usage"]["cached"] == 0


@respx.mock
async def test_other_models_get_a_plain_system_message(
    gateway: OpenRouterGateway,
) -> None:
    """Only Anthropic models receive cache_control."""
    route = respx.post(URL).respond(200, json=fixture("completion_text"))

    await ask(gateway, model="openai/gpt-5")

    body = json.loads(route.calls.last.request.content)
    assert body["messages"][0]["content"] == "You help students."


@respx.mock
async def test_no_tools_means_no_tool_fields(gateway: OpenRouterGateway) -> None:
    """The summarizer sends no tool list."""
    route = respx.post(URL).respond(200, json=fixture("completion_text"))

    await gateway.complete(
        model="anthropic/claude-haiku-5.5",
        system="s",
        messages=[],
        tools=[],
        max_tokens=10,
    )

    body = json.loads(route.calls.last.request.content)
    assert "tools" not in body and "tool_choice" not in body


@respx.mock
async def test_invalid_argument_json_becomes_a_tool_error(
    gateway: OpenRouterGateway,
) -> None:
    """AI-4: the call is returned with an error the loop turns into a failed call."""
    respx.post(URL).respond(200, json=fixture("completion_bad_arguments"))

    result = await ask(gateway)

    call = result["tool_calls"][0]
    assert call["arguments"] == {} and "not valid JSON" in call["error"]


@respx.mock
async def test_rate_limit_is_retried_once_after_the_wait(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """AI-13: 429 -> wait Retry-After -> retry once."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(
                429, json=fixture("error_429"), headers={"Retry-After": "3"}
            ),
            httpx.Response(200, json=fixture("completion_text")),
        ]
    )

    result = await ask(gateway)

    assert route.call_count == 2 and sleeps.seconds == [3.0]
    assert result["text"].startswith("You have")


@respx.mock
async def test_server_error_twice_raises_a_provider_error(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """AI-13: after one retry the failure surfaces as ai/provider-error (503)."""
    route = respx.post(URL).respond(
        502, json={"error": {"code": 502, "message": "bad gateway"}}
    )

    with pytest.raises(AiProviderError) as caught:
        await ask(gateway)

    assert route.call_count == 2 and sleeps.seconds == [2.0]
    assert caught.value.status == 503 and "bad gateway" in caught.value.support_details


@respx.mock
async def test_client_errors_are_not_retried(gateway: OpenRouterGateway) -> None:
    """A bad key (401) fails at once, without echoing the prompt."""
    route = respx.post(URL).respond(401, json=fixture("error_401"))

    with pytest.raises(AiProviderError) as caught:
        await ask(gateway)

    assert route.call_count == 1
    assert "marks?" not in caught.value.support_details


@respx.mock
async def test_error_inside_a_200_response_is_detected(
    gateway: OpenRouterGateway,
) -> None:
    """AI-13: finish_reason error / choices[0].error after HTTP 200."""
    respx.post(URL).respond(200, json=fixture("completion_error_in_200"))

    with pytest.raises(AiProviderError, match="upstream failed"):
        await ask(gateway)


@respx.mock
async def test_network_failure_is_retried_then_reported(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """A transport error gets one retry too."""
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(AiProviderError):
        await ask(gateway)

    assert route.call_count == 2 and len(sleeps.seconds) == 1


# - - - Parameters the newest models refuse - - -

UNSUPPORTED = {
    "error": {
        "message": "No endpoints found that can handle the requested parameters. "
        "To learn more about provider routing, visit: https://openrouter.ai/docs",
        "code": 404,
    }
}
MANDATORY = {
    "error": {
        "message": "Reasoning is mandatory for this endpoint and cannot be disabled.",
        "code": 400,
    }
}


def bodies(route: respx.Route) -> list[dict[str, Any]]:
    """The JSON bodies of every request the route received."""
    return [json.loads(call.request.content) for call in route.calls]


@respx.mock
async def test_temperature_is_dropped_and_remembered_after_a_parameter_404(
    gateway: OpenRouterGateway, sleeps: Sleeps
) -> None:
    """Claude 5.5 and GPT-5.x refuse `temperature`: one retry without it, then never."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(404, json=UNSUPPORTED),
            httpx.Response(200, json=fixture("completion_text")),
            httpx.Response(200, json=fixture("completion_text")),
        ]
    )

    first = await ask(gateway, model="anthropic/claude-haiku-5.5")
    second = await ask(gateway, model="anthropic/claude-haiku-5.5")

    assert first["text"] == second["text"] == "You have two marks: 5 and 4."
    sent = bodies(route)
    assert len(sent) == 3 and sleeps.seconds == []
    assert "temperature" in sent[0]
    assert "temperature" not in sent[1] and "temperature" not in sent[2]


@respx.mock
async def test_a_parameter_404_without_temperature_is_a_provider_error(
    gateway: OpenRouterGateway,
) -> None:
    """Nothing left to drop: the error reaches the caller after one request."""
    route = respx.post(URL).respond(404, json=UNSUPPORTED)
    gateway._no_temperature.add("anthropic/claude-haiku-5.5")  # noqa: SLF001

    with pytest.raises(AiProviderError) as caught:
        await ask(gateway, model="anthropic/claude-haiku-5.5")

    assert route.call_count == 1 and caught.value.params["status"] == 404


@respx.mock
async def test_reasoning_off_falls_back_to_the_lowest_effort_when_mandatory(
    gateway: OpenRouterGateway,
) -> None:
    """Sonnet 5.5 and Gemini 3 always reason: `enabled: false` becomes `effort: low`."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json=MANDATORY),
            httpx.Response(200, json=fixture("completion_text")),
            httpx.Response(200, json=fixture("completion_text")),
        ]
    )
    tuning = LlmTuning(reasoning_effort="none")

    for _ in range(2):
        await gateway.complete(
            model="google/gemini-3.8-flash",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            max_tokens=100,
            tuning=tuning,
        )

    sent = bodies(route)
    assert [body["reasoning"] for body in sent] == [
        {"enabled": False},
        {"effort": "low"},
        {"effort": "low"},
    ]


@respx.mock
async def test_the_default_chat_with_tools_keeps_both_retry_rules(
    gateway: OpenRouterGateway,
) -> None:
    """The default profile (Haiku 5.5, reasoning none) asks with tools: a refused
    temperature is dropped and retried; reasoning stays off on the retry."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(404, json=UNSUPPORTED),
            httpx.Response(200, json=fixture("completion_tool_calls")),
        ]
    )
    tuning = LlmTuning(temperature=0.2, reasoning_effort="none")

    await gateway.complete(
        model="anthropic/claude-haiku-5.5",
        system="s",
        messages=[{"role": "user", "content": "marks?"}],
        tools=TOOLS,
        max_tokens=512,
        tuning=tuning,
    )

    first, retry = bodies(route)
    assert first["temperature"] == 0.2 and "temperature" not in retry
    assert first["reasoning"] == retry["reasoning"] == {"enabled": False}
    assert retry["tools"] == TOOLS


@respx.mock
async def test_mandatory_reasoning_with_tools_falls_back_to_effort_low(
    gateway: OpenRouterGateway,
) -> None:
    """A model that always reasons refuses `enabled: false` even with tools: the retry
    asks for `effort: low` and keeps the tools."""
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json=MANDATORY),
            httpx.Response(200, json=fixture("completion_tool_calls")),
        ]
    )

    await gateway.complete(
        model="anthropic/claude-haiku-5.5",
        system="s",
        messages=[{"role": "user", "content": "marks?"}],
        tools=TOOLS,
        max_tokens=512,
        tuning=LlmTuning(temperature=0.2, reasoning_effort="none"),
    )

    first, retry = bodies(route)
    assert first["reasoning"] == {"enabled": False}
    assert retry["reasoning"] == {"effort": "low"} and retry["tools"] == TOOLS


@respx.mock
async def test_a_streamed_parameter_404_is_retried_without_temperature(
    gateway: OpenRouterGateway,
) -> None:
    """The stream path learns the same way (one retry before the first delta)."""
    stream_body = (
        'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":1,'
        '"completion_tokens":1}}\n\ndata: [DONE]\n\n'
    )
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(404, json=UNSUPPORTED),
            httpx.Response(200, text=stream_body),
        ]
    )

    items = [
        item
        async for item in gateway.stream(
            model="openai/gpt-5.4-mini",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=50,
        )
    ]

    assert [i.get("delta") for i in items if "delta" in i] == ["Hi"]
    sent = bodies(route)
    assert "temperature" in sent[0] and "temperature" not in sent[1]
