"""AI-EFF-1: the system prompt is a cache breakpoint only for caching models."""

from app.modules.ai.infrastructure.openrouter import build_payload

MARKED = [{"type": "text", "text": "system", "cache_control": {"type": "ephemeral"}}]


def system_of(model: str, cache_models: tuple[str, ...]) -> object:
    """The content of the system message the gateway sends."""
    body = build_payload(
        model,
        "system",
        [{"role": "user", "content": "hi"}],
        [],
        100,
        None,
        cache_models,
    )
    return body["messages"][0]["content"]


def test_gemini_is_marked_by_default() -> None:
    """AI-EFF-1: Gemini caches explicitly behind OpenRouter, like Anthropic."""
    body = build_payload("google/gemini-3.8-flash", "system", [], [], 100)

    assert body["messages"][0]["content"] == MARKED


def test_the_prefix_list_decides() -> None:
    """AI-EFF-1: `AI__PROMPT_CACHE_MODELS` adds or removes providers."""
    assert system_of("openai/gpt-5", ("openai/",)) == MARKED
    assert system_of("anthropic/claude-haiku-5.5", ()) == "system"


def test_the_stable_prefix_comes_first() -> None:
    """AI-EFF-1: system, then the messages in the order the caller gave them."""
    messages = [
        {"role": "user", "content": "<sources/>"},
        {"role": "assistant", "content": "earlier"},
        {"role": "user", "content": "question"},
    ]
    body = build_payload("anthropic/x", "system", messages, [], 100)

    assert [m["role"] for m in body["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert body["messages"][1:] == messages
