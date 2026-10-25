"""Plain text of an HTML page for URL sources (stdlib only, linear time).

This is a small forward-only scanner instead of `html.parser.HTMLParser`: the stdlib
parser starts again from the same position after every unfinished tag, comment or
declaration, so a crafted page of 100 KB already takes many seconds and holds the
GIL. Here every character is looked at a bounded number of times, and whatever is
unfinished at the end of the page (a tag, a comment, a script) is dropped, as
browsers do.
"""

import html
import re
from collections.abc import Callable
from dataclasses import dataclass

TITLE_LIMIT = 200

_BR = ""  # a <br> inside a text block
_CELL = ""  # the start of a table cell
_CODE = ""  # the start or end of inline <code>

_BLOCK = "block"
_ITEM = "item"
_ROW = "row"
_PRE = "pre"

_MAIN = 1
_ARTICLE = 2
_MAX_INDENT = 6
_TIGHT = (
    _ITEM,
    _ROW,
)  # consecutive blocks of these kinds are not separated by a blank line
_CELL_LIMIT = 2000  # a longer "cell" is page layout, not a table: keep its blocks

# Elements whose content is never text for the reader.
_HARD_IGNORED = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "canvas",
        "template",
        "select",
        "datalist",
        "textarea",
        "object",
        "audio",
        "video",
    }
)
# Page furniture. A page that is wrapped in one of these (`<form runat="server">`
# around the whole body) is read again without them.
_SOFT_IGNORED = frozenset({"nav", "header", "footer", "aside", "form", "button"})
_STRICT = _HARD_IGNORED | _SOFT_IGNORED
_RELAXED = _HARD_IGNORED | frozenset({"button"})

# The content of these is not markup; skipped up to the closing tag.
_RAW_TEXT = ("script", "style", "textarea", "xmp", "iframe", "noembed", "noframes")
_CLOSERS = {
    name: re.compile(rf"</{name}(?=[\s/>]|$)", re.IGNORECASE) for name in _RAW_TEXT
}
_TITLE_CLOSE = re.compile(r"</title(?=[\s/>]|$)", re.IGNORECASE)

_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
# Elements whose end tag may be left out: a new one closes the previous one.
_OPTIONAL_END = frozenset(
    {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option"}
)
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCKS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "center",
        "dd",
        "details",
        "dir",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "hr",
        "html",
        "legend",
        "main",
        "nav",
        "p",
        "section",
        "summary",
    }
)
_TABLE_PARTS = ("caption", "thead", "tbody", "tfoot")

# Text up to the next real markup; a "<" that starts no tag is text.
_TEXT = re.compile(r"(?:[^<]++|<(?![a-zA-Z/!?]))*+")
# A tag name ends at white space, "/" or ">".
_TAG_NAME = re.compile(r"[a-zA-Z][^\s/>]*")
# The rest of a start tag up to ">": quotes count only after "=". Possessive, so a
# tag that never ends costs one pass over the rest of the page.
_TAG_BODY = re.compile(r"""(?:[^>=]++|=\s*+(?:"[^"]*+"|'[^']*+')?)*+>""")
_ATTRIBUTE = re.compile(
    r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?"""
)
_HIDDEN_HINT = re.compile(r"hidden|display|visibility", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_CODE_SPAN = re.compile(r" ?([^]*?) ?")

_CLEAN = {
    **dict.fromkeys(
        [
            *range(0, 9),
            *range(14, 32),
            127,
            0x200B,
            0xFEFF,
            0xAD,
            *range(0xE000, 0xE004),
        ]
    ),
}


@dataclass(frozen=True, slots=True)
class ExtractedHtml:
    """The title and the main text of a page."""

    title: str | None
    text: str


def extract_html(markup: str) -> ExtractedHtml:
    """Return the `<title>` and the readable text of an HTML page as Markdown-ish lines.

    The text of `<article>` or `<main>` is preferred, else the whole body; scripts,
    styles, navigation and hidden elements are dropped. Headings become `#` lines,
    list items `- ` lines, table rows tab-joined lines; blocks are separated by a
    blank line.
    """
    first = _Extractor(_STRICT)
    first.run(markup)
    text = first.text()
    title = first.title
    if not text:
        second = _Extractor(_RELAXED)
        second.run(markup)
        text = second.text()
        title = title or second.title
    return ExtractedHtml(title=title, text=text)


def _clean(text: str) -> str:
    return text.translate(_CLEAN)


def _collapse(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def _wrap_code(match: re.Match[str]) -> str:
    inner = match.group(1)
    return f"`{inner}`" if inner and "`" not in inner else inner


def _inline(text: str) -> str:
    """Collapse white space; inline `<code>` markers become backticks."""
    text = _collapse(text)
    if _CODE in text:
        text = _collapse(_CODE_SPAN.sub(_wrap_code, text).replace(_CODE, ""))
    return text


def _lines(raw: str) -> str:
    pieces = [_inline(piece) for piece in raw.split(_BR)]
    return "\n".join(piece for piece in pieces if piece)


def _row(raw: str) -> str:
    cells = raw.split(_CELL)
    if not cells[0].strip():
        cells = cells[1:]
    return "\t".join(_inline(cell) for cell in cells).rstrip("\t")


def _fence(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return f"```\n{text}\n```" if text.strip() else ""


def _render(kind: str, raw: str) -> str:
    if kind == _PRE:
        return _fence(raw)
    if kind == _ROW and _CELL in raw:
        return _row(raw)
    return _lines(raw)


def _skip_declaration(markup: str, start: int) -> int:
    """Skip a comment, doctype, CDATA section or processing instruction."""
    if markup.startswith("<!--", start):
        close, width = markup.find("-->", start + 2), 3
    else:
        close, width = markup.find(">", start + 2), 1
    return len(markup) if close < 0 else close + width


def _skip_raw_text(markup: str, start: int, name: str) -> int:
    """Return the position of the closing tag of a script-like element."""
    closer = _CLOSERS[name].search(markup, start)
    return len(markup) if closer is None else closer.start()


def _is_hidden(attributes: str) -> bool:
    """True for `hidden`, `aria-hidden="true"` and `display:none` elements."""
    if _HIDDEN_HINT.search(attributes) is None:
        return False
    for match in _ATTRIBUTE.finditer(attributes):
        value = match.group(2) or match.group(3) or match.group(4) or ""
        if _hides(match.group(1).lower(), value):
            return True
    return False


def _hides(name: str, value: str) -> bool:
    if name == "hidden":
        return True
    if name == "aria-hidden":
        return value.strip().lower() == "true"
    if name == "style":
        compact = _SPACES.sub("", value).lower()
        return "display:none" in compact or "visibility:hidden" in compact
    return False


class _Extractor:
    """One forward pass over the markup that collects blocks of text."""

    def __init__(self, ignored: frozenset[str]) -> None:
        """Set the elements to leave out."""
        self.ignored = ignored
        self.title: str | None = None
        self._entries: list[tuple[str, str, int, int]] = []
        self._parts: list[str] = []
        self._prefix = ""
        self._kind = _BLOCK
        self._skip_tag = ""
        self._skip_depth = 0
        self._pre_depth = 0
        self._list_depth = 0
        self._main = 0
        self._article = 0
        self._in_cell = False
        self._in_heading = False
        self._size = 0
        self._title_lost = False
        self._group = 0  # lines of one list or table are not separated by blank lines
        self._starts = self._start_handlers()
        self._ends = self._end_handlers()

    # - - - Tokenizer - - -

    def run(self, markup: str) -> None:
        """Scan the whole page."""
        pos, size = 0, len(markup)
        while pos < size:
            text = _TEXT.match(markup, pos)
            end = text.end() if text else pos
            if end > pos:
                self._text(markup[pos:end])
            if end >= size:
                break
            pos = self._markup(markup, end)
        self._flush()

    def _markup(self, markup: str, lt: int) -> int:
        """Handle the markup that starts at `lt`; return where the next token is."""
        name = _TAG_NAME.match(markup, lt + 1)
        if name:
            return self._start_tag(markup, name)
        if markup[lt + 1] == "/":
            return self._end_tag(markup, lt)
        return _skip_declaration(markup, lt)

    def _start_tag(self, markup: str, match: re.Match[str]) -> int:
        body = _TAG_BODY.match(markup, match.end())
        if body is None:  # never ends: the rest of the page is lost, as in browsers
            return len(markup)
        name = match.group().lower()
        end = body.end()
        attributes = markup[match.end() : end - 1]
        self_closing = attributes.endswith("/")
        if name == "title" and not self_closing and self._wants_title():
            title_end = self._read_title(markup, end)
            if title_end:
                return title_end
        self._start(name, attributes, self_closing)
        if name in _RAW_TEXT and not self_closing:
            return _skip_raw_text(markup, end, name)
        return end

    def _end_tag(self, markup: str, lt: int) -> int:
        name = _TAG_NAME.match(markup, lt + 2)
        if name:
            self._end(name.group().lower())
        close = markup.find(">", lt + 2)
        return len(markup) if close < 0 else close + 1

    def _wants_title(self) -> bool:
        return self.title is None and not self._title_lost and self._skip_depth == 0

    def _read_title(self, markup: str, start: int) -> int:
        """Read `<title>` as plain text; 0 when it never ends (read as markup)."""
        closer = _TITLE_CLOSE.search(markup, start)
        if closer is None:
            self._title_lost = True  # no later <title> can end either: search once
            return 0
        text = _collapse(_clean(html.unescape(markup[start : closer.start()])))
        self.title = text[:TITLE_LIMIT].strip() or None
        return closer.start()

    # - - - Events - - -

    def _text(self, data: str) -> None:
        if self._skip_depth:
            return
        if "&" in data:
            data = html.unescape(data)
        data = _clean(data)
        self._size += len(data)
        self._parts.append(data)

    def _start(self, name: str, attributes: str, self_closing: bool) -> None:
        if self._skip_depth and not self._leaves_skip(name):
            return
        if name == "br":
            self._parts.append("\n" if self._pre_depth else self._line_break())
        elif self._pre_depth:
            self._start_in_pre(name)
        elif name in self.ignored or (attributes and _is_hidden(attributes)):
            self._begin_skip(name, self_closing)
        elif name in self._starts:
            self._starts[name](name)
            if self_closing:
                self._end(name)

    def _end(self, name: str) -> None:
        if self._skip_depth:
            self._end_in_skip(name)
        elif self._pre_depth:
            self._end_in_pre(name)
        elif name in self._ends:
            self._ends[name](name)

    def _leaves_skip(self, name: str) -> bool:
        """Handle a start tag inside a skipped element; True if the skip ended."""
        if name != self._skip_tag:
            return False
        if name in _OPTIONAL_END:  # `<p hidden>a<p>b`: the second <p> closes the first
            self._skip_depth = 0
            return True
        self._skip_depth += 1
        return False

    def _begin_skip(self, name: str, self_closing: bool) -> None:
        if name not in _VOID and not self_closing:
            self._skip_tag = name
            self._skip_depth = 1

    def _end_in_skip(self, name: str) -> None:
        if name == self._skip_tag:
            self._skip_depth -= 1
        elif name in ("body", "html"):  # an unclosed <nav> must not eat the page
            self._skip_depth = 0

    def _start_in_pre(self, name: str) -> None:
        if name == "pre":
            self._pre_depth += 1

    def _end_in_pre(self, name: str) -> None:
        if name == "pre":
            self._pre_depth -= 1
        elif name in ("body", "html"):
            self._pre_depth = 0
        if not self._pre_depth:
            self._flush()

    def _line_break(self) -> str:
        return " " if self._in_cell or self._in_heading else _BR

    # - - - Handlers by tag - - -

    def _start_handlers(self) -> dict[str, Callable[[str], None]]:
        handlers: dict[str, Callable[[str], None]] = {}
        handlers.update(dict.fromkeys(_BLOCKS, self._block_tag))
        handlers.update(dict.fromkeys(_HEADINGS, self._open_heading))
        handlers.update(dict.fromkeys(("ul", "ol", "menu"), self._open_list))
        handlers.update(dict.fromkeys(("td", "th"), self._open_cell))
        handlers.update(dict.fromkeys(("main", "article"), self._open_scope))
        handlers.update(dict.fromkeys(_TABLE_PARTS, self._open_table))
        handlers.update(
            {
                "li": self._open_item,
                "table": self._open_whole_table,
                "tr": self._open_row,
                "pre": self._open_pre,
                "code": self._code_tag,
            }
        )
        return handlers

    def _end_handlers(self) -> dict[str, Callable[[str], None]]:
        handlers: dict[str, Callable[[str], None]] = {}
        handlers.update(dict.fromkeys(_BLOCKS, self._block_tag))
        handlers.update(dict.fromkeys(_HEADINGS, self._close_heading))
        handlers.update(dict.fromkeys(("ul", "ol", "menu"), self._close_list))
        handlers.update(dict.fromkeys(("td", "th"), self._close_cell))
        handlers.update(dict.fromkeys(("main", "article"), self._close_scope))
        handlers.update(dict.fromkeys(("tr", *_TABLE_PARTS), self._open_table))
        handlers.update(
            {
                "li": self._block_tag,
                "table": self._open_whole_table,
                "code": self._code_tag,
                "pre": self._block_tag,
            }
        )
        return handlers

    def _block_tag(self, name: str) -> None:
        if self._in_cell and self._size < _CELL_LIMIT:
            self._parts.append(" ")
            return
        self._flush()
        self._in_cell = False

    def _code_tag(self, name: str) -> None:
        self._parts.append(_CODE)

    def _open_heading(self, name: str) -> None:
        self._block_tag(name)
        if not self._in_cell:
            self._prefix = "#" * int(name[1]) + " "
            self._in_heading = True

    def _close_heading(self, name: str) -> None:
        self._block_tag(name)
        self._in_heading = False

    def _open_list(self, name: str) -> None:
        self._block_tag(name)
        if self._list_depth == 0:
            self._group += 1
        self._list_depth += 1

    def _close_list(self, name: str) -> None:
        self._block_tag(name)
        self._list_depth = max(0, self._list_depth - 1)
        if self._list_depth == 0:
            self._group += 1

    def _open_item(self, name: str) -> None:
        self._block_tag(name)
        if not self._in_cell:
            indent = min(max(self._list_depth - 1, 0), _MAX_INDENT)
            self._prefix = "  " * indent + "- "
            self._kind = _ITEM

    def _open_table(self, name: str) -> None:
        self._flush()
        self._in_cell = False

    def _open_whole_table(self, name: str) -> None:
        self._open_table(name)
        self._group += 1

    def _open_row(self, name: str) -> None:
        self._open_table(name)
        self._kind = _ROW

    def _open_cell(self, name: str) -> None:
        self._parts.append(_CELL)
        self._in_cell = True
        self._kind = _ROW

    def _close_cell(self, name: str) -> None:
        self._in_cell = False

    def _open_pre(self, name: str) -> None:
        self._block_tag(name)
        if not self._in_cell:
            self._pre_depth = 1
            self._kind = _PRE

    def _open_scope(self, name: str) -> None:
        self._block_tag(name)
        if name == "main":
            self._main += 1
        else:
            self._article += 1

    def _close_scope(self, name: str) -> None:
        self._block_tag(name)
        if name == "main":
            self._main = max(0, self._main - 1)
        else:
            self._article = max(0, self._article - 1)

    # - - - Output - - -

    def _flush(self) -> None:
        """Close the current block of text."""
        parts, kind, prefix = self._parts, self._kind, self._prefix
        self._parts, self._kind, self._prefix = [], _BLOCK, ""
        self._size, self._in_heading = 0, False
        if not parts:
            return
        text = _render(kind, "".join(parts))
        if text:
            scope = (_MAIN if self._main else 0) | (_ARTICLE if self._article else 0)
            self._entries.append((kind, prefix + text, scope, self._group))

    def text(self) -> str:
        """Join the blocks of the preferred scope: main, article, else everything."""
        chosen = self._entries
        for flag in (_MAIN, _ARTICLE):
            scoped = [entry for entry in self._entries if entry[2] & flag]
            if scoped:
                chosen = scoped
                break
        out: list[str] = []
        previous = ("", -1)
        for kind, text, _scope, group in chosen:
            if out:
                tight = (kind, group) == previous and kind in _TIGHT
                out.append("\n" if tight else "\n\n")
            out.append(text)
            previous = (kind, group)
        return "".join(out)
