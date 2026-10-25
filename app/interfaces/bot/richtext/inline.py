"""Inline markdown and math rendering to Telegram HTML."""

import html
import re
from collections.abc import Callable

from app.interfaces.bot.richtext.buttons import is_https_url
from app.interfaces.bot.richtext.latex import latex_to_unicode

_INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<dmath>\$\$[^\n]+?\$\$|\\\[[^\n]+?\\\])"
    r"|(?P<imath>\\\([^\n]+?\\\)|\$(?!\$)[^$\n]+?\$(?!\d))"
    r"|(?P<link>\[[^\]\n]+\]\((?:[^()\s]|\([^()\s]*\))+\))"
    r"|(?P<bold>\*\*[^\n]+?\*\*|__[^\n]+?__)"
    r"|(?P<strike>~~[^\n]+?~~)"
    r"|(?P<italic>\*(?!\s)[^*\n]+?(?<!\s)\*|(?<!\w)_(?!\s)[^_\n]+?(?<!\s)_(?!\w))"
)
_LINK = re.compile(r"\[([^\]\n]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)")


def escape(text: str) -> str:
    """Escape text for Telegram HTML; quotes stay as they are inside element text.

    Args:
        text: Plain text.

    Returns:
        Text with &, < and > replaced by entities.
    """
    return html.escape(text, quote=False)


def render_inline(text: str) -> str:
    """Render inline markdown, LaTeX and links of one line to Telegram HTML.

    Args:
        text: Markdown text without block structure.

    Returns:
        Telegram HTML with every literal character escaped.
    """
    out: list[str] = []
    pos = 0
    for match in _INLINE.finditer(text):
        out.append(escape(text[pos : match.start()]))
        out.append(_HANDLERS[match.lastgroup or ""](match.group(0)))
        pos = match.end()
    out.append(escape(text[pos:]))
    return "".join(out)


def _code(raw: str) -> str:
    """Render an inline code span."""
    return f"<code>{escape(raw[1:-1])}</code>"


def _display_math(raw: str) -> str:
    """Render a display formula that sits inside a line."""
    result = latex_to_unicode(raw[2:-2]).text
    return f"<code>{escape(result)}</code>"


def _inline_math(raw: str) -> str:
    """Render inline LaTeX as plain Unicode text."""
    inner = raw[2:-2] if raw.startswith("\\(") else raw[1:-1]
    result = latex_to_unicode(inner).text
    return escape(result) if result else escape(raw)


def _link(raw: str) -> str:
    """Render a link; anything but an https target keeps only its label."""
    match = _LINK.fullmatch(raw)
    if match is None:
        return escape(raw)
    label, url = match.group(1), match.group(2)
    if not is_https_url(url):
        return render_inline(label)
    return f'<a href="{html.escape(url, quote=True)}">{render_inline(label)}</a>'


def _bold(raw: str) -> str:
    """Render bold text."""
    return f"<b>{render_inline(raw[2:-2])}</b>"


def _strike(raw: str) -> str:
    """Render strikethrough text."""
    return f"<s>{render_inline(raw[2:-2])}</s>"


def _italic(raw: str) -> str:
    """Render italic text."""
    return f"<i>{render_inline(raw[1:-1])}</i>"


_HANDLERS: dict[str, Callable[[str], str]] = {
    "code": _code,
    "dmath": _display_math,
    "imath": _inline_math,
    "link": _link,
    "bold": _bold,
    "strike": _strike,
    "italic": _italic,
    "": escape,
}
