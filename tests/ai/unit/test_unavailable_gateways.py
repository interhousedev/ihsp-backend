"""Without an OpenRouter or Exa key, only a process that must call them stops at start.

The Telegram bot builds the AI module but never calls it: it gets gateways that fail
when reached, so a missing key cannot stop the bot (the api and worker stay strict).
"""

from app.modules.ai.infrastructure.exa import ExaCallError
from app.modules.ai.infrastructure.exa_search import ExaWebSearch
from app.modules.ai.infrastructure.gateway_factory import (
    make_llm_gateway,
    make_web_search_gateway,
)
from app.modules.ai.infrastructure.unavailable import (
    UnavailableExaClient,
    UnavailableLlmGateway,
)
from app.settings import Settings
from app.shared.contracts.ai import AiProviderError

import pytest


@pytest.fixture
def keyless(settings: Settings) -> Settings:
    """Real OpenRouter and Exa without their keys: what the bot sees in production."""
    openrouter = settings.openrouter.model_copy(
        update={"mode": "real", "api_key": None}
    )
    exa = settings.exa.model_copy(update={"mode": "real", "api_key": None})
    return settings.model_copy(update={"openrouter": openrouter, "exa": exa})


def test_api_and_worker_refuse_to_start_without_the_openrouter_key(
    keyless: Settings,
) -> None:
    with pytest.raises(ValueError, match="OPENROUTER__API_KEY is required"):
        make_llm_gateway(keyless)


async def test_the_bot_llm_fails_only_when_a_call_reaches_it(keyless: Settings) -> None:
    gateway = make_llm_gateway(keyless, required=False)

    assert isinstance(gateway, UnavailableLlmGateway)
    with pytest.raises(AiProviderError):
        await gateway.complete(
            model="m", system="s", messages=[], tools=[], max_tokens=1
        )


def test_api_and_worker_refuse_to_start_without_the_exa_key(keyless: Settings) -> None:
    with pytest.raises(ValueError, match="EXA__API_KEY is required"):
        make_web_search_gateway(keyless, None)


def test_the_bot_web_search_is_built_without_the_exa_key(keyless: Settings) -> None:
    assert isinstance(
        make_web_search_gateway(keyless, None, required=False), ExaWebSearch
    )


async def test_an_unavailable_exa_client_reports_why_it_cannot_search() -> None:
    client = UnavailableExaClient("EXA__API_KEY is not set here")

    with pytest.raises(ExaCallError):
        await client.search({"query": "q"})
