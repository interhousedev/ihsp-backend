"""AI-13: the model profile reaches the OpenRouter request body."""

import json
from typing import Any

from app.modules.ai.infrastructure.openrouter import OpenRouterGateway, build_payload
from app.shared.contracts.ai import LlmTuning
from tests.ai.unit.test_openrouter_gateway import URL, fixture

import pytest
import respx

MODEL = "anthropic/claude-haiku-4.5"


def payload(tuning: LlmTuning | None) -> dict[str, Any]:
    """The request body for one plain message."""
    return build_payload(
        MODEL, "system", [{"role": "user", "content": "hi"}], [], 100, tuning
    )


def test_without_tuning_the_gateway_keeps_its_own_values() -> None:
    """Direct callers get temperature 0.2 and nothing else."""
    body = payload(None)

    assert body["temperature"] == 0.2
    assert "reasoning" not in body and "models" not in body


def test_the_profile_sets_the_temperature() -> None:
    """A task with its own temperature."""
    assert payload(LlmTuning(temperature=0.75))["temperature"] == 0.75


def test_unset_tuning_fields_are_not_sent() -> None:
    """Only what the profile sets goes to OpenRouter."""
    body = payload(LlmTuning())

    assert body["temperature"] == 0.2
    assert "reasoning" not in body and "models" not in body


def test_reasoning_effort_is_sent_as_the_reasoning_object() -> None:
    """Models that support it read `reasoning.effort`."""
    assert payload(LlmTuning(reasoning_effort="high"))["reasoning"] == {
        "effort": "high"
    }


def test_fallbacks_become_the_models_list_with_the_model_first() -> None:
    """OpenRouter tries `models` in order when a provider fails."""
    body = payload(LlmTuning(fallbacks=("x/one", "x/two")))

    assert body["model"] == MODEL
    assert body["models"] == [MODEL, "x/one", "x/two"]


@respx.mock
async def test_the_tuning_and_provider_are_in_the_request(
    gateway: OpenRouterGateway,
) -> None:
    """`complete` sends the profile's temperature, fallbacks and provider routing."""
    route = respx.post(URL).respond(200, json=fixture("completion_text"))

    await gateway.complete(
        model=MODEL,
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        max_tokens=50,
        provider={"data_collection": "deny"},
        tuning=LlmTuning(temperature=0.9, fallbacks=("x/one",)),
    )

    body = json.loads(route.calls.last.request.content)
    assert body["temperature"] == 0.9
    assert body["models"] == [MODEL, "x/one"]
    assert body["provider"] == {"data_collection": "deny"}


@pytest.fixture
def gateway() -> OpenRouterGateway:
    """An adapter with a test key."""
    return OpenRouterGateway(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        app_url="https://my.ihsu.uz",
        app_title="IHT",
        timeout_seconds=5,
    )


def test_reasoning_none_switches_reasoning_off() -> None:
    """`none` sends `reasoning.enabled: false` (Claude 5.5 reasons by default)."""
    assert payload(LlmTuning(reasoning_effort="none"))["reasoning"] == {
        "enabled": False
    }
