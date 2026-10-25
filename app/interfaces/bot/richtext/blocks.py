"""Block-level markdown parsing: fences, math, headings, quotes, lists, buttons."""

import re
from dataclasses import dataclass

from app.interfaces.bot.richtext.buttons import match_button_line, parse_button_body
from app.interfaces.bot.richtext.inline import escape, render_inline
from app.interfaces.bot.richtext.latex import latex_to_unicode
from app.interfaces.bot.richtext.model import ButtonSpec, FormulaSpec

_FENCE_OPEN = re.compile(r"^\s*```\s*([A-Za-z0-9_+.-]*)\s*$")
_FENCE_CLOSE = re.compile(r"^\s*```\s*$")
_DISPLAY_OPEN = re.compile(r"^\s*(\$\$|\\\[)(.*)$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


@dataclass(frozen=True, slots=True)
class Block:
    """One rendered markdown block; empty html marks a blank or button-only line."""

    html: str = ""
    blank_before: bool = False
    formulas: tuple[FormulaSpec, ...] = ()
    buttons: tuple[ButtonSpec, ...] = ()


def parse_blocks(markdown: str) -> list[Block]:
    """Split markdown into rendered blocks, one per source line or fenced construct.

    Args:
        markdown: Markdown text, possibly with LaTeX and button lines.

    Returns:
        Blocks in source order; blank source lines become marker blocks.
    """
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            blocks.append(Block(blank_before=True))
            i += 1
            continue
        i, block = _parse_one(lines, i)
        blocks.append(block)
    return blocks


def join_blocks(blocks: list[Block]) -> tuple[str, list[int]]:
    """Join block HTML with newlines, keeping one blank line where the source had one.

    Args:
        blocks: Blocks from parse_blocks.

    Returns:
        The full HTML and the start offset of each block that produced HTML.
    """
    parts: list[str] = []
    starts: list[int] = []
    length = 0
    blank = False
    for block in blocks:
        blank = blank or block.blank_before
        if not block.html:
            continue
        if starts:
            separator = "\n\n" if blank else "\n"
            parts.append(separator)
            length += len(separator)
        starts.append(length)
        parts.append(block.html)
        length += len(block.html)
        blank = False
    return "".join(parts), starts


def _parse_one(lines: list[str], i: int) -> tuple[int, Block]:
    """Parse the block that starts at line ``i``."""
    line = lines[i]
    fence = _FENCE_OPEN.match(line)
    if fence:
        return _fenced_code(lines, i, fence.group(1))
    display = _DISPLAY_OPEN.match(line)
    if display:
        return _display_math(lines, i, display.group(1), display.group(2))
    body = match_button_line(line)
    if body is not None:
        return i + 1, _button_line(body)
    if _QUOTE.match(line):
        return _quote(lines, i)
    return i + 1, _single_line(line)


def _single_line(line: str) -> Block:
    """Render a line that is a heading, list item, rule or plain text."""
    if _RULE.match(line):
        return Block()
    heading = _HEADING.match(line)
    if heading:
        return Block(html=f"<b>{render_inline(heading.group(1))}</b>")
    bullet = _BULLET.match(line)
    if bullet:
        indent = "  " * (len(bullet.group(1)) // 2)
        return Block(html=f"{indent}• {render_inline(bullet.group(2))}")
    numbered = _NUMBERED.match(line)
    if numbered:
        indent = "  " * (len(numbered.group(1)) // 2)
        return Block(
            html=f"{indent}{numbered.group(2)}. {render_inline(numbered.group(3))}"
        )
    return Block(html=render_inline(line))


def _fenced_code(lines: list[str], i: int, language: str) -> tuple[int, Block]:
    """Parse a fenced code block; an unclosed fence runs to the end of the text."""
    j = i + 1
    body: list[str] = []
    while j < len(lines) and not _FENCE_CLOSE.match(lines[j]):
        body.append(lines[j])
        j += 1
    end = j + 1 if j < len(lines) else len(lines)
    lang_attr = f' class="language-{language}"' if language else ""
    code = escape("\n".join(body))
    return end, Block(html=f"<pre><code{lang_attr}>{code}</code></pre>")


def _display_math(
    lines: list[str], i: int, delimiter: str, rest: str
) -> tuple[int, Block]:
    r"""Parse a `$$ ... $$` or `\\[ ... \\]` block that may span lines."""
    closer = "$$" if delimiter == "$$" else "\\]"
    parts: list[str] = []
    j = i
    text = rest
    closed = False
    while True:
        if closer in text:
            parts.append(text[: text.index(closer)])
            closed = True
            break
        parts.append(text)
        j += 1
        if j >= len(lines):
            break
        text = lines[j]
    end = j + 1 if closed else len(lines)
    source = "\n".join(parts).strip()
    if not source:
        return end, Block()
    result = latex_to_unicode(source)
    formulas = (FormulaSpec(latex=source, display=True),) if result.needs_image else ()
    return end, Block(html=f"<code>{escape(result.text)}</code>", formulas=formulas)


def _button_line(body: str) -> Block:
    """Turn a button line into a keyboard entry; invalid ones keep their label."""
    spec = parse_button_body(body)
    if spec is not None:
        return Block(buttons=(spec,))
    label = body.partition("|")[0].strip()
    return Block(html=escape(label)) if label else Block()


def _quote(lines: list[str], i: int) -> tuple[int, Block]:
    """Parse consecutive `>` lines into one blockquote."""
    texts: list[str] = []
    j = i
    while j < len(lines) and (quote := _QUOTE.match(lines[j])):
        texts.append(quote.group(1))
        j += 1
    return j, Block(
        html=f"<blockquote>{render_inline(chr(10).join(texts))}</blockquote>"
    )
