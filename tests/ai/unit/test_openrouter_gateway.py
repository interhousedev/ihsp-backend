"""AI-13: the OpenRouter adapter against recorded-shape responses (respx)."""

import json
from pathlib import Path
from typing import Any

from app.modules.ai.domain.errors import AiProviderError
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway

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
        app_url="https://sp.ihsu.uz",
        app_title="IHSP",
        timeout_seconds=5,
        sleep=sleeps,
    )


async def ask(
    gateway: OpenRouterGateway, model: str = "anthropic/claude-haiku-4.5"
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
    assert result["usage"] == {"input": 10339, "output": 60, "cached": 10318}


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
    assert request.headers["http-referer"] == "https://sp.ihsu.uz"
    assert request.headers["x-openrouter-title"] == "IHSP"
    assert body["model"] == "anthropic/claude-haiku-4.5" and body["max_tokens"] == 512
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
        model="anthropic/claude-haiku-4.5",
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
