"""Email HTML <-> Telegram's HTML subset (MAIL-2, MAIL-4)."""

import html as html_lib
import re
from dataclasses import dataclass

import nh3

TELEGRAM_TAGS = frozenset(
    {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del"}
    | {"a", "code", "pre", "blockquote"}
)
TELEGRAM_LIMIT = 3500
ELLIPSIS = "…"

_URL_SCHEMES = {"http", "https", "mailto"}
_DROPPED_CONTENT = {"script", "style", "head", "title", "svg", "noscript"}
_NEWLINE_BLOCKS = (
    r"<(?:div|tr|h[1-6]|ul|ol|table|section|article|header|footer)\b[^>]*>"
    r"|</(?:div|tr|h[1-6]|ul|ol|table|section|article|header|footer)\s*>"
    r"|<p\b[^>]*>"
)
_BLOCK_RE = re.compile(_NEWLINE_BLOCKS, re.IGNORECASE)
_PARAGRAPH_END_RE = re.compile(r"</p\s*>", re.IGNORECASE)
_BREAK_RE = re.compile(r"<br\b[^>]*>", re.IGNORECASE)
_ITEM_START_RE = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_ITEM_END_RE = re.compile(r"</li\s*>", re.IGNORECASE)
_CELL_END_RE = re.compile(r"</t[dh]\s*>", re.IGNORECASE)
_PRE_RE = re.compile(r"<pre\b.*?</pre\s*>", re.IGNORECASE | re.DOTALL)
_SPACES_RE = re.compile(r"[ \t\n\f\v]+")
_PLACEHOLDER_RE = re.compile("(\\d+)")
_BARE_ANCHOR_RE = re.compile(r"<a>(.*?)</a>", re.DOTALL)
_EMPTY_PAIR_RE = re.compile(
    r"<(b|strong|i|em|u|ins|s|strike|del|code|blockquote)>\s*</\1>"
)
_EMPTY_ANCHOR_RE = re.compile(r'<a href="[^"]*">\s*</a>')
_LINK_RE = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.DOTALL)
_TOKEN_RE = re.compile(r"(<[^>]*>)")
_TAG_NAME_RE = re.compile(r"</?\s*([a-zA-Z0-9]+)")
_NO_NESTING = frozenset({"pre", "code"})


@dataclass(frozen=True, slots=True)
class TelegramText:
    """Converted body and whether it was cut to fit the limit."""

    html: str
    truncated: bool


def _clean(html: str) -> str:
    """Keep only Telegram's tags (and ``href``); drop scripts, styles and images."""
    return nh3.clean(
        html,
        tags=set(TELEGRAM_TAGS),
        attributes={"a": {"href"}},
        clean_content_tags=set(_DROPPED_CONTENT),
        link_rel=None,
        url_schemes=set(_URL_SCHEMES),
        url_relative="deny",
    )


def _stash_pre_blocks(html: str) -> tuple[str, list[str]]:
    """Replace ``<pre>`` blocks by placeholders so their whitespace survives."""
    blocks: list[str] = []

    def stash(match: re.Match[str]) -> str:
        blocks.append(_clean(match.group(0)))
        return f"{len(blocks) - 1}"

    return _PRE_RE.sub(stash, html), blocks


def _restore_pre_blocks(text: str, blocks: list[str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: blocks[int(m.group(1))], text)


def _blocks_to_newlines(html: str) -> str:
    """Turn block-level tags and ``<br>`` into newlines; list items get a bullet."""
    html = _SPACES_RE.sub(" ", html)
    html = _BREAK_RE.sub("\n", html)
    html = _PARAGRAPH_END_RE.sub("\n\n", html)
    html = _BLOCK_RE.sub("\n", html)
    html = _ITEM_START_RE.sub("\n• ", html)
    html = _ITEM_END_RE.sub("", html)
    return _CELL_END_RE.sub(" ", html)


def _tidy(text: str) -> str:
    """Normalize spaces and blank lines."""
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _drop_empty_tags(text: str) -> str:
    for _ in range(4):
        shorter = _EMPTY_ANCHOR_RE.sub("", _EMPTY_PAIR_RE.sub("", text))
        if shorter == text:
            break
        text = shorter
    return text


def _closers(stack: list[str]) -> str:
    return "".join(f"</{name}>" for name in reversed(stack))


def _cut_text(text: str, room: int) -> str:
    """Cut text to ``room`` characters on a space and never inside an entity."""
    if len(text) <= room:
        return text
    cut = text[: max(room, 0)]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary > len(cut) // 2:
        cut = cut[:boundary]
    return cut.rstrip()


def _tag_name(token: str) -> str:
    match = _TAG_NAME_RE.match(token)
    return match.group(1).lower() if match else ""


def _fit(html: str, limit: int | None) -> TelegramText:
    """Walk tags and text; keep tags balanced; stop before ``limit`` characters."""
    budget = limit if limit is not None else len(html) + 100
    out: list[str] = []
    used = 0
    stack: list[str] = []
    for token in _TOKEN_RE.split(html):
        if not token:
            continue
        if token.startswith("<"):
            name = _tag_name(token)
            if stack and stack[-1] in _NO_NESTING and name not in _NO_NESTING:
                continue
            closing = token.startswith("</")
            future = stack[:-1] if closing else [*stack, name]
            if used + len(token) + len(_closers(future)) > budget:
                return _truncated(out, stack)
            out.append(token)
            used += len(token)
            stack = future
            continue
        room = budget - used - len(_closers(stack)) - len(ELLIPSIS)
        piece = _cut_text(token, room)
        if len(piece) < len(token):
            out.append(piece)
            return _truncated(out, stack)
        out.append(token)
        used += len(token)
    return TelegramText(html="".join(out), truncated=False)


def _truncated(out: list[str], stack: list[str]) -> TelegramText:
    body = _drop_empty_tags("".join(out).rstrip() + ELLIPSIS + _closers(stack))
    return TelegramText(html=body, truncated=True)


def html_to_telegram(html: str, *, limit: int | None = TELEGRAM_LIMIT) -> TelegramText:
    """Sanitize email HTML to Telegram's tags, with newlines for blocks (MAIL-2).

    Images are dropped, blank lines collapse, and the result is cut on a tag
    boundary to ``limit`` characters (None = no limit).
    """
    stashed, blocks = _stash_pre_blocks(html.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = _clean(_blocks_to_newlines(stashed))
    cleaned = _BARE_ANCHOR_RE.sub(r"\1", cleaned)
    tidy = _drop_empty_tags(_tidy(cleaned))
    return _fit(_restore_pre_blocks(tidy, blocks), limit)


def plain_to_telegram(text: str, *, limit: int | None = TELEGRAM_LIMIT) -> TelegramText:
    """Escape a plain-text body for Telegram and cut it to ``limit`` characters."""
    escaped = html_lib.escape(
        text.replace("\r\n", "\n").replace("\r", "\n"), quote=False
    )
    return _fit(_tidy(escaped), limit)


def html_to_text(html: str) -> str:
    """Plain text of an HTML body; links become ``text (url)``."""
    stashed, blocks = _stash_pre_blocks(html.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = _clean(_blocks_to_newlines(stashed))
    cleaned = _restore_pre_blocks(cleaned, blocks)
    cleaned = _LINK_RE.sub(_link_to_text, cleaned)
    stripped = nh3.clean(cleaned, tags=set(), clean_content_tags=set(_DROPPED_CONTENT))
    return _tidy(html_lib.unescape(stripped))


def _link_to_text(match: re.Match[str]) -> str:
    url, label = html_lib.unescape(match.group(1)), match.group(2)
    plain = html_lib.unescape(nh3.clean(label, tags=set())).strip()
    if not plain or plain == url or plain == url.removeprefix("mailto:"):
        return label
    return f"{label} ({html_lib.escape(url, quote=False)})"


def telegram_to_email_html(html: str) -> str:
    """Sanitize bot-written Telegram HTML for an email body; newlines become <br>."""
    cleaned = _clean(html.replace("\r\n", "\n").replace("\r", "\n")).strip()
    parts: list[str] = []
    position = 0
    for match in _PRE_RE.finditer(cleaned):
        parts.append(cleaned[position : match.start()].replace("\n", "<br>\n"))
        parts.append(match.group(0))
        position = match.end()
    parts.append(cleaned[position:].replace("\n", "<br>\n"))
    return "".join(parts)
