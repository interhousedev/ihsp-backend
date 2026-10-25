"""AI-EFF-1: prompt caching marks only stable material, only for models that cache."""

from app.settings import Settings
from app.settings_ai import AiSettings
from app.shared.ai.prompt_cache import (
    CACHE_MARK,
    context_message,
    supports_prompt_cache,
)

PREFIXES = ("anthropic/", "google/gemini-")


def test_models_are_matched_by_prefix() -> None:
    """AI-EFF-1: the setting lists model id prefixes."""
    assert supports_prompt_cache("anthropic/claude-haiku-5.5", PREFIXES)
    assert supports_prompt_cache("google/gemini-3.8-flash", PREFIXES)
    assert not supports_prompt_cache("openai/gpt-5", PREFIXES)
    assert not supports_prompt_cache("anthropic/claude-haiku-5.5", ())


def test_a_big_block_for_a_caching_model_gets_the_mark() -> None:
    """AI-EFF-1: the sources go in their own part with `cache_control`."""
    message = context_message(
        "x" * 50, model="anthropic/claude", prefixes=PREFIXES, min_chars=10
    )

    assert message == {
        "role": "user",
        "content": [{"type": "text", "text": "x" * 50, "cache_control": CACHE_MARK}],
    }
    assert CACHE_MARK == {"type": "ephemeral"}


def test_a_small_block_or_another_model_stays_plain() -> None:
    """AI-EFF-1: below the threshold or for other providers nothing is marked."""
    small = context_message(
        "tiny", model="anthropic/claude", prefixes=PREFIXES, min_chars=10
    )
    other = context_message(
        "x" * 50, model="openai/gpt-5", prefixes=PREFIXES, min_chars=10
    )

    assert small == {"role": "user", "content": "tiny"}
    assert other == {"role": "user", "content": "x" * 50}


def test_the_volatile_summary_follows_the_cached_prefix() -> None:
    """AI-EFF-1/2: the stable block first (cached), the conversation summary after."""
    message = context_message(
        "<sources/>",
        model="google/gemini-3.8-flash",
        prefixes=PREFIXES,
        min_chars=0,
        extra="[summary]",
    )

    parts = message["content"]
    assert parts[0]["cache_control"] == CACHE_MARK
    assert parts[1] == {"type": "text", "text": "[summary]"}


def test_the_extra_part_alone_keeps_the_block_uncached() -> None:
    """AI-EFF-1: a model without caching still gets the summary as a second part."""
    message = context_message(
        "<sources/>", model="x/y", prefixes=PREFIXES, min_chars=0, extra="[s]"
    )

    assert message["content"] == [
        {"type": "text", "text": "<sources/>"},
        {"type": "text", "text": "[s]"},
    ]


def test_settings_defaults_and_environment_history_limit() -> None:
    """AI-EFF-3: `AI__CHAT_HISTORY_LIMIT` sets the default of the editable limit."""
    assert Settings(env="test").limits.ai_chat_history_limit == 20
    settings = Settings(env="test", ai=AiSettings(chat_history_limit=8))

    assert settings.limits.ai_chat_history_limit == 8
    assert "anthropic/" in settings.ai.prompt_cache_models
