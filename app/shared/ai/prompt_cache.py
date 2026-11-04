"""Provider prompt caching: where `cache_control` goes in a request (AI-EFF-1).

OpenRouter passes `cache_control: {"type": "ephemeral"}` on a content part to the
providers that cache explicitly (Anthropic, Gemini). The provider caches the prefix
up to the marked part, so a request is ordered from the most stable part to the
least stable one: system prompt, sources, conversation summary, history, question.
Only models whose id starts with one of `AI__PROMPT_CACHE_MODELS` get the mark;
others receive plain strings.
"""

from collections.abc import Sequence
from typing import Any, Final

CACHE_MARK: Final[dict[str, str]] = {"type": "ephemeral"}


VOLATILE_MARK: Final = "\x1e"  # splits a system prompt: stable part, volatile tail


def with_volatile_tail(stable: str, tail: str) -> str:
    """A system prompt whose `tail` changes per request and must not break the cache."""
    return f"{stable}{VOLATILE_MARK}{tail}"


def split_system(system: str) -> tuple[str, str]:
    """The stable part and the volatile tail of a system prompt (maybe empty)."""
    stable, _, tail = system.partition(VOLATILE_MARK)
    return stable, tail


def plain_system(system: str) -> str:
    """The system prompt as one text, for a gateway that does not mark the cache."""
    stable, tail = split_system(system)
    return f"{stable}\n\n{tail}" if tail else stable


def supports_prompt_cache(model: str, prefixes: Sequence[str]) -> bool:
    """True when the model id starts with one of the caching prefixes."""
    return any(model.startswith(prefix) for prefix in prefixes if prefix)


def text_part(text: str, *, cache: bool = False) -> dict[str, Any]:
    """One text content part, marked as a cache breakpoint when `cache`."""
    part: dict[str, Any] = {"type": "text", "text": text}
    if cache:
        part["cache_control"] = dict(CACHE_MARK)
    return part


def context_message(
    block: str,
    *,
    model: str,
    prefixes: Sequence[str],
    min_chars: int,
    extra: str | None = None,
) -> dict[str, Any]:
    """The first user message: the stable `block`, then the volatile `extra`.

    The block is marked for caching when the model caches and the block has at
    least `min_chars` characters; `extra` (e.g. a conversation summary) always
    comes after the mark so that it never breaks the cached prefix.
    """
    cache = supports_prompt_cache(model, prefixes) and len(block) >= min_chars
    if not cache and not extra:
        return {"role": "user", "content": block}
    parts = [text_part(block, cache=cache)]
    if extra:
        parts.append(text_part(extra))
    return {"role": "user", "content": parts}
