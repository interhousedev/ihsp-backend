"""Chooses the LlmGateway from the settings (for the composition root)."""

from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.settings import Settings
from app.shared.contracts.ai import LlmGateway


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
