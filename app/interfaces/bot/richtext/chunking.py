"""Splits Telegram HTML into messages of at most 4096 characters, tag-safe."""

import bisect
import re

TELEGRAM_TEXT_LIMIT = 4096

# Tokens are whole tags, whole entities, whitespace runs or short text runs.
_TOKEN = re.compile(r"<[^>]+>|&[#\w]+;|\s{1,256}|[^\s<&]{1,512}|[<&]")
_TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)[^>]*>")

_Stack = tuple[tuple[str, str], ...]


def pack(
    html: str, starts: list[int], limit: int = TELEGRAM_TEXT_LIMIT
) -> tuple[list[str], dict[int, int]]:
    """Pack HTML into chunks, closing and reopening open tags at each cut.

    Args:
        html: Well-formed Telegram HTML produced by the renderer.
        starts: Offsets where the source blocks begin; used to map blocks to chunks.
        limit: Maximum length of one chunk.

    Returns:
        The chunks, and for each block index the index of the chunk where it starts.
    """
    chunks: list[str] = []
    first_chunk: dict[int, int] = {}
    stack: _Stack = ()
    current: list[str] = []
    current_len = 0
    for match in _TOKEN.finditer(html):
        token = match.group(0)
        next_stack = _apply(stack, token)
        if current and current_len + len(token) + _closing_len(next_stack) > limit:
            chunks.append("".join(current) + _closers(stack))
            reopened = "".join(markup for _, markup in stack)
            current = [reopened]
            current_len = len(reopened)
        block = bisect.bisect_right(starts, match.start()) - 1
        if block >= 0 and block not in first_chunk:
            first_chunk[block] = len(chunks)
        current.append(token)
        current_len += len(token)
        stack = next_stack
    if current:
        chunks.append("".join(current) + _closers(stack))
    return chunks, first_chunk


def _apply(stack: _Stack, token: str) -> _Stack:
    """Return the open-tag stack after a token."""
    match = _TAG.fullmatch(token)
    if match is None:
        return stack
    name = match.group(2)
    if not match.group(1):
        return (*stack, (name, token))
    for index in range(len(stack) - 1, -1, -1):
        if stack[index][0] == name:
            return (*stack[:index], *stack[index + 1 :])
    return stack


def _closers(stack: _Stack) -> str:
    """Closing tags for every open element, innermost first."""
    return "".join(f"</{name}>" for name, _ in reversed(stack))


def _closing_len(stack: _Stack) -> int:
    """Length of the closing tags for an open-tag stack."""
    return sum(len(name) + 3 for name, _ in stack)
