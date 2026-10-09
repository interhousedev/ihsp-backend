"""Chooses the LlmGateway and the WebSearchGateway from the settings."""

from app.modules.ai.infrastructure.fake_embeddings import FakeEmbeddingGateway
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.fake_search import FakeWebSearch
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.modules.ai.infrastructure.openrouter_embeddings import OpenRouterEmbeddings
from app.modules.ai.infrastructure.openrouter_search import OpenRouterWebSearch
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway
from app.shared.contracts.embeddings import EmbeddingGateway
from app.shared.contracts.web_search import WebSearchGateway


def make_llm_gateway(settings: Settings) -> LlmGateway:
    """Return the real OpenRouter gateway or the fake one (`OPENROUTER__MODE`)."""
    config = settings.openrouter
    if config.mode == "fake":
        return FakeLlmGateway()
    if config.api_key is None:
        raise ValueError("OPENROUTER__API_KEY is required when OPENROUTER__MODE=real")
    return OpenRouterGateway(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        app_url=config.app_url,
        app_title=config.app_title,
        timeout_seconds=config.timeout_seconds,
    )


def make_web_search_gateway(settings: Settings, llm: LlmGateway) -> WebSearchGateway:
    """The search over the same OpenRouter connection, or the fake one.

    Any gateway that is not the OpenRouter one (the fake, or a test double) gets the
    fake search: only a real connection can run a real search.
    """
    if settings.openrouter.mode == "real" and isinstance(llm, OpenRouterGateway):
        return OpenRouterWebSearch(llm, settings.web_search)
    return FakeWebSearch()


def make_embedding_gateway(settings: Settings, llm: LlmGateway) -> EmbeddingGateway:
    """Embeddings over the same OpenRouter connection, or the deterministic fake.

    Any gateway that is not the OpenRouter one (the fake, or a test double) gets the
    fake embeddings, like the web search: only a real connection can embed. The fake
    reports the profile's size and batch size, so the pipeline is shaped as in
    production.
    """
    profile = settings.ai_profile(AiTask.EMBEDDING)
    if settings.openrouter.mode == "real" and isinstance(llm, OpenRouterGateway):
        return OpenRouterEmbeddings(llm, profile)
    return FakeEmbeddingGateway(dims=profile.dimensions, batch_size=profile.batch_size)
