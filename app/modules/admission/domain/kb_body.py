"""Rich-content rules for an FAQ article body: OpenUI blocks and safe links."""

import re
from typing import Final

from app.modules.admission.domain.errors import KbBodyInvalidError
from app.shared.openui.blocks import split_blocks
from app.shared.openui.validate import validate_block

MAX_BLOCKS: Final = 3
MAX_BLOCK_CHARS: Final = 6000
_PLACEHOLDER: Final = '"https://example.invalid/x"'
_STRING: Final = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
_BAD_SCHEME: Final = re.compile(
    r"^\s*(javascript|data|vbscript|file|blob):", re.IGNORECASE
)
_FENCE: Final = re.compile(r"^ {0,3}(```|~~~).*?^ {0,3}\1[ \t]*$", re.M | re.S)
_INLINE: Final = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]*)")
_REFDEF: Final = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(\S+)", re.M)
_REFBAD: Final = re.compile(
    r"\]:\s*<?(?:javascript|data|vbscript|file|blob):", re.IGNORECASE
)
_AUTO: Final = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.-]*:[^>\s]*)>")
_HTML: Final = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|style|form|link|meta)\b", re.IGNORECASE
)


def _safe(target: str) -> bool:
    """https:, mailto: or an app-relative path."""
    t = target.strip().lower()
    if t.startswith("/"):
        return not t.startswith("//")
    return t.startswith("https://") or t.startswith("mailto:")


def _relax(match: re.Match[str]) -> str:
    """Swap an allowed relative or mailto literal for a validator-safe link."""
    value = match.group(1)
    if _BAD_SCHEME.match(value):
        raise KbBodyInvalidError(params={"reason": "link"})
    low = value.strip().lower()
    if (low.startswith("/") and not low.startswith("//")) or low.startswith("mailto:"):
        return _PLACEHOLDER
    return match.group(0)


def _check_markdown(text: str) -> None:
    text = _FENCE.sub("", text)
    if _HTML.search(text) or _REFBAD.search(text):
        raise KbBodyInvalidError(params={"reason": "html"})
    targets = [
        *_INLINE.findall(text),
        *_REFDEF.findall(text),
        *_AUTO.findall(text),
    ]
    if not all(_safe(t) for t in targets if t):
        raise KbBodyInvalidError(params={"reason": "link"})


def check_body(body: str) -> None:
    """Reject a body with a bad block, too many blocks or an unsafe link."""
    blocks = 0
    for part in split_blocks(body):
        if part.kind == "pending":
            raise KbBodyInvalidError(params={"reason": "unclosed"})
        if part.kind == "text":
            _check_markdown(part.text)
            continue
        blocks += 1
        if blocks > MAX_BLOCKS:
            raise KbBodyInvalidError(params={"reason": "blocks"})
        if len(part.text.rstrip("\n")) > MAX_BLOCK_CHARS:
            raise KbBodyInvalidError(params={"reason": "block_size"})
        source = _STRING.sub(_relax, part.text)
        if validate_block(source, "chat"):
            raise KbBodyInvalidError(params={"reason": "block"})
