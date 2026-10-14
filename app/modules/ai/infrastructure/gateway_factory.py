"""Chooses the LlmGateway, the WebSearchGateway and the embeddings from the settings."""

from app.modules.ai.infrastructure.anthropic_gateway import AnthropicLlmGateway
from app.modules.ai.infrastructure.exa import ExaApi, ExaClient
from app.modules.ai.infrastructure.exa_rate_limit import ExaRateLimiter, LimitedExa
from app.modules.ai.infrastructure.exa_search import ExaWebSearch
from app.modules.ai.infrastructure.fake_embeddings import FakeEmbeddingGateway
from app.modules.ai.infrastructure.fake_exa import FakeExaClient
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.fallback_gateway import FallbackLlmGateway
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.modules.ai.infrastructure.openrouter_embeddings import OpenRouterEmbeddings
from app.modules.ai.infrastructure.unavailable import (
    UnavailableExaClient,
    UnavailableLlmGateway,
)
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway
from app.shared.contracts.embeddings import EmbeddingGateway
from app.shared.contracts.web_search import WebSearchGateway

from redis.asyncio import Redis


def make_llm_gateway(settings: Settings, *, required: bool = True) -> LlmGateway:
    """Return the real OpenRouter gateway or the fake one (`OPENROUTER__MODE`).

    With `ANTHROPIC__API_KEY` the real gateway falls back to the Anthropic API when
    OpenRouter's credit or limit runs out (the mapped models only).

    A real connection without a key stops the start when `required`; a process that
    holds no key (the bot) gets a gateway that fails only when a call reaches it.
    """
    config = settings.openrouter
    if config.mode == "fake":
        return FakeLlmGateway()
    if config.api_key is None:
        if not required:
            return UnavailableLlmGateway("OPENROUTER__API_KEY is not set here")
        raise ValueError("OPENROUTER__API_KEY is required when OPENROUTER__MODE=real")
    primary = OpenRouterGateway(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        app_url=config.app_url,
        app_title=config.app_title,
        timeout_seconds=config.timeout_seconds,
        cache_models=settings.ai.prompt_cache_models,
    )
    fallback = settings.anthropic
    if not fallback.active or fallback.api_key is None:
        return primary
    anthropic = AnthropicLlmGateway(
        api_key=fallback.api_key.get_secret_value(),
        timeout_seconds=config.timeout_seconds,
    )
    return FallbackLlmGateway(primary, anthropic, fallback.models)


def make_web_search_gateway(
    settings: Settings, redis: Redis | None, *, required: bool = True
) -> WebSearchGateway:
    """The Exa search: the real API in `EXA__MODE=real`, else the deterministic fake.

    A real connection without `EXA__API_KEY` stops the start, like a missing OpenRouter
    key does (unless `required` is False: then searches fail when reached); the key
    itself is never logged. The real API is called through the allowance shared by all
    processes (Redis), so `redis` is required then.
    """
    config = settings.exa
    client: ExaApi
    if config.mode == "fake":
        client = FakeExaClient()
    else:
        if config.api_key is None:
            if not required:
                client = UnavailableExaClient("EXA__API_KEY is not set here")
                return ExaWebSearch(client, settings.web_search, config)
            raise ValueError("EXA__API_KEY is required when EXA__MODE=real")
        if redis is None:
            raise ValueError("Redis is required for the Exa rate limit")
        client = LimitedExa(
            ExaClient(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                timeout_seconds=config.timeout_seconds,
            ),
            ExaRateLimiter(redis),
            config,
        )
    return ExaWebSearch(client, settings.web_search, config)


def make_embedding_gateway(settings: Settings, llm: LlmGateway) -> EmbeddingGateway:
    """Embeddings over the same OpenRouter connection, or the deterministic fake.

    Any gateway that is not the OpenRouter one (the fake, or a test double) gets the
    fake embeddings: only a real connection can embed. The fake reports the profile's
    size and batch size, so the pipeline is shaped as in production.
    """
    profile = settings.ai_profile(AiTask.EMBEDDING)
    if isinstance(llm, FallbackLlmGateway):
        llm = llm.primary
    if settings.openrouter.mode == "real" and isinstance(llm, OpenRouterGateway):
        return OpenRouterEmbeddings(llm, profile)
    return FakeEmbeddingGateway(dims=profile.dimensions, batch_size=profile.batch_size)
